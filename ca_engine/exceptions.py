"""Builds exception records in one consistent, supervisor-ready format."""

import pandas as pd

from .config import EXCEPTION_CATALOGUE
from .dates import add_business_days


def make_exception(stage, code, event_id, detail, detected_date, account_id=None, ticker=None):
    """Create one exception row, enriched from the exception catalogue."""
    severity, owner, sla_days, action = EXCEPTION_CATALOGUE[code]
    detected = pd.Timestamp(detected_date) if pd.notna(detected_date) else pd.NaT
    due = add_business_days(detected, sla_days) if pd.notna(detected) else pd.NaT
    return {
        "stage": stage,                 # Event validation / Instructions / Voting / Reconciliation
        "reason_code": code,
        "event_id": event_id,
        "account_id": account_id,
        "ticker": ticker,
        "detail": detail,
        "severity": severity,
        "owner": owner,
        "detected_date": detected,
        "sla_due_date": due,
        "required_action": action,
        "status": "OPEN",
    }
