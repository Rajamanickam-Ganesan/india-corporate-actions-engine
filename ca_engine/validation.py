"""
Step 1 - Event validation ("scrubbing").

Every event from the vendor feed is checked BEFORE it can touch a client
position. Bad events go to the exception queue instead of being processed.
"""

import pandas as pd

from .config import DUPLICATE_KEY, REQUIRED_FIELDS, SUPPORTED_EVENT_TYPES
from .exceptions import make_exception


def _dup_key(event: pd.Series) -> tuple:
    """Key for duplicate detection. Blank fields become None so two blanks compare equal."""
    return tuple(None if pd.isna(event.get(k)) else event.get(k) for k in DUPLICATE_KEY)


def _check_event(event: pd.Series, held_tickers: set, accepted_keys: set):
    """Return (reason_code, issue_text) for the first rule that fails, or (None, None)."""
    etype = event["event_type"]

    # 1. Do we know how to process this type of event?
    if etype not in SUPPORTED_EVENT_TYPES:
        return "UNSUPPORTED_TYPE", f"Event type '{etype}' is not supported"

    # 2. Are all the fields needed for this event type filled in?
    missing = [f for f in REQUIRED_FIELDS[etype] if pd.isna(event.get(f))]
    if missing:
        return "MISSING_FIELDS", f"Missing field(s): {', '.join(missing)}"

    # 3. Is this the same event we already accepted from another source?
    if _dup_key(event) in accepted_keys:
        return "DUPLICATE_EVENT", "Same ticker, event type, record date and terms as an event already accepted"

    # 4. Are the economic terms sensible?
    if etype == "CASH_DIVIDEND" and event["cash_amount"] <= 0:
        return "INVALID_AMOUNT", f"Dividend amount must be positive (received {event['cash_amount']})"
    if etype in {"BONUS", "RIGHTS", "DEMERGER"}:
        if event["ratio_new"] <= 0 or event["ratio_old"] <= 0:
            return "INVALID_RATIO", f"Ratio must be positive (received {event['ratio_new']}:{event['ratio_old']})"
    if etype == "RIGHTS" and event["offer_price"] <= 0:
        return "INVALID_AMOUNT", f"Rights offer price must be positive (received {event['offer_price']})"
    if etype == "DEMERGER":
        total = event["parent_cost_pct"] + event["child_cost_pct"]
        if abs(total - 100) > 0.01:
            return "ALLOCATION_NOT_100", f"Cost split adds to {total}% instead of 100%"

    # 5. Are the dates in a sensible order?
    if event["ex_date"] > event["record_date"]:
        return "DATE_SEQUENCE", "Ex-date is after record date"
    if event["pay_date"] < event["record_date"]:
        return "DATE_SEQUENCE", "Pay date is before record date"
    if etype == "RIGHTS":
        if not (event["record_date"] < event["renunciation_deadline"] <= event["market_deadline"]):
            return "DATE_SEQUENCE", "Rights deadlines are out of order"
        if event["client_deadline"] > event["market_deadline"]:
            return "DATE_SEQUENCE", "Client deadline is after the market deadline"

    # 6. Does any client actually hold this stock?
    if event["ticker"] not in held_tickers:
        return "TICKER_NOT_HELD", f"No client holds {event['ticker']}"

    return None, None


def validate_feed(events: pd.DataFrame, held_tickers: set):
    """
    Validate every event in the feed.

    Returns:
        valid_events  - events that passed every check (ready to process)
        results       - one row per event showing pass/fail and why
        exceptions    - list of exception records for failed events
    """
    results, exceptions, accepted_keys, valid_ids = [], [], set(), []

    for _, event in events.iterrows():
        code, issue = _check_event(event, held_tickers, accepted_keys)
        is_valid = code is None
        if is_valid:
            accepted_keys.add(_dup_key(event))
            valid_ids.append(event["event_id"])
        else:
            exceptions.append(make_exception(
                stage="Event validation", code=code, event_id=event["event_id"],
                ticker=event["ticker"], detail=issue,
                detected_date=event["announcement_date"],
            ))
        results.append({
            "event_id": event["event_id"],
            "source": event["source"],
            "ticker": event["ticker"],
            "event_type": event["event_type"],
            "record_date": event["record_date"],
            "is_valid": is_valid,
            "processing_status": "READY" if is_valid else "FLAGGED",
            "reason_code": code,
            "issue": issue,
        })

    valid_events = events[events["event_id"].isin(valid_ids)].copy()
    return valid_events, pd.DataFrame(results), exceptions
