"""
Step 3 - Processing engine. One function per event type.

Every processor receives:
    event     - the validated event (one row of the feed)
    holders   - {account_id: settled quantity on the record date}
    book      - the PositionBook (updated in place)
    ctx       - shared lookups: accounts, instructions, run timestamp

and returns a dict of lists that the pipeline collects:
    entitlements, audit, cash, expected, instructions, votes, exceptions
"""

import math

import pandas as pd

from .exceptions import make_exception
from .tax import dividend_tds

TOLERANCE = 0.01  # Rs - for cost-basis checks


def _empty_result():
    return {k: [] for k in ["entitlements", "audit", "cash", "expected",
                            "instructions", "votes", "exceptions"]}


def _entitled(quantity, ratio_new, ratio_old):
    """Whole-share entitlement and the fraction that is dropped."""
    exact = quantity * ratio_new / ratio_old
    whole = math.floor(exact + 1e-9)
    return whole, round(exact - whole, 4)


def _audit_row(event, ctx, account_id, qty_before, qty_after, cost_before, cost_after,
               cash=0.0, expected_cost_change=0.0, new_security=None, new_qty=0, note=""):
    ok = abs((cost_after - cost_before) - expected_cost_change) <= TOLERANCE
    return {
        "event_id": event["event_id"], "event_type": event["event_type"],
        "ticker": event["ticker"], "account_id": account_id,
        "quantity_before": qty_before, "quantity_after": qty_after,
        "new_security": new_security, "new_security_quantity": new_qty,
        "cost_before": round(cost_before, 2), "cost_after": round(cost_after, 2),
        "expected_cost_change": round(expected_cost_change, 2),
        "cash_movement": round(cash, 2),
        "basis_check": "PASS" if ok else "FAIL",
        "note": note, "processed_at": ctx["run_timestamp"],
    }


def _base_entitlement(event, account_id, holding):
    return {"event_id": event["event_id"], "event_type": event["event_type"],
            "ticker": event["ticker"], "account_id": account_id,
            "holding_at_record": holding}


# ---------------------------------------------------------------------------
# BONUS - free extra shares; total cost unchanged, cost per share falls
# ---------------------------------------------------------------------------
def process_bonus(event, holders, book, ctx):
    out = _empty_result()
    t = event["ticker"]
    for acc, qty in sorted(holders.items()):
        bonus, frac = _entitled(qty, event["ratio_new"], event["ratio_old"])
        cost_before = book.cost(acc, t)
        book.add_shares(acc, t, bonus, cost_added=0.0)
        out["entitlements"].append({**_base_entitlement(event, acc, qty),
                                    "entitled_security": t, "entitled_quantity": bonus,
                                    "fraction_ignored": frac})
        out["expected"].append({"event_id": event["event_id"], "account_id": acc,
                                "credit_type": "SHARES", "ticker": t,
                                "expected_quantity": bonus, "expected_net_cash": None,
                                "expected_tds": None, "expected_date": event["pay_date"]})
        out["audit"].append(_audit_row(event, ctx, acc, qty, book.quantity(acc, t),
                                       cost_before, book.cost(acc, t),
                                       note=f"{int(event['ratio_new'])}:{int(event['ratio_old'])} bonus"))
    return out


# ---------------------------------------------------------------------------
# CASH DIVIDEND - cash paid per share, less TDS; shares and cost unchanged
# ---------------------------------------------------------------------------
def process_cash_dividend(event, holders, book, ctx):
    out = _empty_result()
    t = event["ticker"]
    accounts = ctx["accounts"]
    for acc, qty in sorted(holders.items()):
        client = accounts.loc[acc]
        gross = round(qty * event["cash_amount"], 2)
        rate, tds, reason = dividend_tds(client["client_type"], client["pan_available"], gross)
        net = round(gross - tds, 2)
        cost = book.cost(acc, t)
        out["entitlements"].append({**_base_entitlement(event, acc, qty),
                                    "entitled_security": "INR", "gross_cash": gross,
                                    "tds_rate": rate, "tds_amount": tds, "net_cash": net,
                                    "tax_note": reason})
        out["cash"].append({"event_id": event["event_id"], "account_id": acc, "ticker": t,
                            "movement": "DIVIDEND RECEIVED", "gross": gross, "tds": tds,
                            "net_amount": net, "value_date": event["pay_date"]})
        out["expected"].append({"event_id": event["event_id"], "account_id": acc,
                                "credit_type": "CASH", "ticker": t, "expected_quantity": None,
                                "expected_net_cash": net, "expected_tds": tds,
                                "expected_date": event["pay_date"]})
        out["audit"].append(_audit_row(event, ctx, acc, qty, qty, cost, cost, cash=net,
                                       note=f"Rs {event['cash_amount']:.2f}/share, TDS {rate:.0%}"))
    return out


# ---------------------------------------------------------------------------
# DEMERGER - new company's shares created; original cost split between the two
# ---------------------------------------------------------------------------
def process_demerger(event, holders, book, ctx):
    out = _empty_result()
    parent, child = event["ticker"], event["new_ticker"]
    p_pct, c_pct = event["parent_cost_pct"] / 100, event["child_cost_pct"] / 100
    for acc, qty in sorted(holders.items()):
        child_qty, frac = _entitled(qty, event["ratio_new"], event["ratio_old"])
        cost_before = book.cost(acc, parent)
        book.set_cost(acc, parent, cost_before * p_pct)
        book.add_shares(acc, child, child_qty, cost_added=cost_before * c_pct)
        cost_after = book.cost(acc, parent) + book.cost(acc, child)
        out["entitlements"].append({**_base_entitlement(event, acc, qty),
                                    "entitled_security": child, "entitled_quantity": child_qty,
                                    "fraction_ignored": frac})
        out["expected"].append({"event_id": event["event_id"], "account_id": acc,
                                "credit_type": "SHARES", "ticker": child,
                                "expected_quantity": child_qty, "expected_net_cash": None,
                                "expected_tds": None, "expected_date": event["pay_date"]})
        out["audit"].append(_audit_row(event, ctx, acc, qty, book.quantity(acc, parent),
                                       cost_before, cost_after, new_security=child,
                                       new_qty=child_qty,
                                       note=f"Cost split {event['parent_cost_pct']:.2f}% / {event['child_cost_pct']:.2f}%"))
    return out


# ---------------------------------------------------------------------------
# RIGHTS ISSUE - voluntary: client chooses to SUBSCRIBE, RENOUNCE (sell) or LAPSE
# ---------------------------------------------------------------------------
OPTION_PRIORITY = {"SUBSCRIBE": 1, "RENOUNCE": 2, "LAPSE": 3}


def process_rights(event, holders, book, ctx):
    out = _empty_result()
    t, eid, price = event["ticker"], event["event_id"], event["offer_price"]
    instr = ctx["instructions"]
    instr = instr[instr["event_id"] == eid].copy()
    instr["priority"] = instr["option"].map(OPTION_PRIORITY)

    for acc in sorted(set(holders) | set(instr["account_id"])):
        qty = holders.get(acc, 0)
        rights_entitlement, frac = _entitled(qty, event["ratio_new"], event["ratio_old"])
        acc_instr = instr[instr["account_id"] == acc].sort_values(["priority", "received_date"])

        # --- Not a holder on record date: any instruction is rejected ---
        if qty == 0:
            for _, ins in acc_instr.iterrows():
                out["exceptions"].append(make_exception(
                    "Instructions", "INELIGIBLE_INSTRUCTION", eid,
                    f"{ins['instruction_id']}: {ins['option']} {ins['quantity']} - no settled holding on "
                    f"record date {event['record_date']:%d-%b-%Y}",
                    ins["received_date"], acc, t))
                out["instructions"].append({"instruction_id": ins["instruction_id"], "event_id": eid,
                                            "account_id": acc, "option": ins["option"],
                                            "requested_qty": ins["quantity"], "processed_qty": 0,
                                            "received_date": ins["received_date"], "status": "REJECTED",
                                            "comment": "Not eligible - not a holder on record date"})
            continue

        if acc_instr.empty:
            out["exceptions"].append(make_exception(
                "Instructions", "NO_INSTRUCTION", eid,
                f"No election for {rights_entitlement} rights entitlements - default LAPSE applied",
                event["client_deadline"], acc, t))

        remaining, done = rights_entitlement, {"SUBSCRIBE": 0, "RENOUNCE": 0, "LAPSE": 0}
        for _, ins in acc_instr.iterrows():
            requested, status, comment = int(ins["quantity"]), "ACCEPTED", ""
            processed = requested
            hard_deadline = (event["renunciation_deadline"] if ins["option"] == "RENOUNCE"
                             else event["market_deadline"])
            if ins["received_date"] > hard_deadline:
                processed, status = 0, "REJECTED"
                comment = f"Received after the {hard_deadline:%d-%b-%Y} market deadline"
                out["exceptions"].append(make_exception("Instructions", "REJECTED_LATE", eid,
                                                        f"{ins['instruction_id']}: {comment}",
                                                        ins["received_date"], acc, t))
            else:
                if ins["received_date"] > event["client_deadline"]:
                    status, comment = "ACCEPTED_LATE", "Late - submitted on best-efforts basis"
                    out["exceptions"].append(make_exception(
                        "Instructions", "LATE_INSTRUCTION", eid,
                        f"{ins['instruction_id']}: received {ins['received_date']:%d-%b-%Y}, client deadline "
                        f"was {event['client_deadline']:%d-%b-%Y}", ins["received_date"], acc, t))
                if processed > remaining:
                    out["exceptions"].append(make_exception(
                        "Instructions", "OVER_ELECTION", eid,
                        f"{ins['instruction_id']}: asked to {ins['option']} {requested} but only "
                        f"{remaining} entitlements available - capped", ins["received_date"], acc, t))
                    processed, status = remaining, status + " (CAPPED)"
                    comment = (comment + "; " if comment else "") + f"Capped at {remaining}"
            remaining -= processed
            done[ins["option"]] += processed
            out["instructions"].append({"instruction_id": ins["instruction_id"], "event_id": eid,
                                        "account_id": acc, "option": ins["option"],
                                        "requested_qty": requested, "processed_qty": processed,
                                        "received_date": ins["received_date"], "status": status,
                                        "comment": comment})

        lapsed = done["LAPSE"] + remaining
        subscribed = done["SUBSCRIBE"]
        payable = round(subscribed * price, 2)
        cost_before, qty_before = book.cost(acc, t), book.quantity(acc, t)
        book.add_shares(acc, t, subscribed, cost_added=payable)

        out["entitlements"].append({**_base_entitlement(event, acc, qty),
                                    "entitled_security": f"{t} rights entitlements",
                                    "entitled_quantity": rights_entitlement, "fraction_ignored": frac,
                                    "subscribed": subscribed, "renounced": done["RENOUNCE"],
                                    "lapsed": lapsed, "amount_payable": payable})
        if subscribed:
            out["cash"].append({"event_id": eid, "account_id": acc, "ticker": t,
                                "movement": "RIGHTS SUBSCRIPTION PAID", "gross": -payable, "tds": 0.0,
                                "net_amount": -payable, "value_date": event["market_deadline"]})
            out["expected"].append({"event_id": eid, "account_id": acc, "credit_type": "SHARES",
                                    "ticker": t, "expected_quantity": subscribed,
                                    "expected_net_cash": None, "expected_tds": None,
                                    "expected_date": event["pay_date"]})
        out["audit"].append(_audit_row(event, ctx, acc, qty_before, book.quantity(acc, t),
                                       cost_before, book.cost(acc, t), cash=-payable,
                                       expected_cost_change=payable,
                                       note=f"Subscribed {subscribed}, renounced {done['RENOUNCE']}, lapsed {lapsed}"))
    return out


# ---------------------------------------------------------------------------
# MEETING (AGM e-voting) - client votes, capped at holding on the cut-off date
# ---------------------------------------------------------------------------
def process_meeting(event, holders, book, ctx):
    out = _empty_result()
    t, eid = event["ticker"], event["event_id"]
    votes = ctx["instructions"]
    votes = votes[votes["event_id"] == eid]

    for acc in sorted(set(holders) | set(votes["account_id"])):
        eligible = holders.get(acc, 0)
        acc_votes = votes[votes["account_id"] == acc]

        if eligible > 0:
            out["entitlements"].append({**_base_entitlement(event, acc, eligible),
                                        "entitled_security": "Votes", "entitled_quantity": eligible})
            out["audit"].append(_audit_row(event, ctx, acc, eligible, eligible,
                                           book.cost(acc, t), book.cost(acc, t),
                                           note="Voting only - no position change"))
        if eligible > 0 and acc_votes.empty:
            out["exceptions"].append(make_exception("Voting", "NO_VOTE", eid,
                                                    f"No vote received for {eligible} eligible shares",
                                                    event["client_deadline"], acc, t))

        for _, v in acc_votes.iterrows():
            requested, counted, status = int(v["quantity"]), int(v["quantity"]), "COUNTED"
            if eligible == 0:
                counted, status = 0, "REJECTED"
                out["exceptions"].append(make_exception("Voting", "INELIGIBLE_INSTRUCTION", eid,
                                                        f"{v['instruction_id']}: no holding on cut-off date",
                                                        v["received_date"], acc, t))
            elif v["received_date"] > event["market_deadline"]:
                counted, status = 0, "REJECTED"
                out["exceptions"].append(make_exception("Voting", "REJECTED_LATE", eid,
                                                        f"{v['instruction_id']}: received after e-voting closed",
                                                        v["received_date"], acc, t))
            else:
                if v["received_date"] > event["client_deadline"]:
                    status = "COUNTED_LATE"
                    out["exceptions"].append(make_exception("Voting", "LATE_INSTRUCTION", eid,
                                                            f"{v['instruction_id']}: received after client deadline",
                                                            v["received_date"], acc, t))
                if requested > eligible:
                    counted, status = eligible, status + " (CAPPED)"
                    out["exceptions"].append(make_exception(
                        "Voting", "OVER_VOTE", eid,
                        f"{v['instruction_id']}: voted {requested} on {v['resolution']} but holds {eligible}",
                        v["received_date"], acc, t))
            out["votes"].append({"instruction_id": v["instruction_id"], "event_id": eid,
                                 "account_id": acc, "resolution": v["resolution"],
                                 "vote": v["option"], "eligible_shares": eligible,
                                 "requested_votes": requested, "counted_votes": counted,
                                 "received_date": v["received_date"], "status": status})
    return out


PROCESSORS = {
    "BONUS": process_bonus,
    "CASH_DIVIDEND": process_cash_dividend,
    "DEMERGER": process_demerger,
    "RIGHTS": process_rights,
    "MEETING": process_meeting,
}
