"""
Step 4 - Reconciliation: what we EXPECTED vs what the depository/registrar
actually CREDITED. Every difference becomes a break in the exception queue.
"""

import pandas as pd

from .config import CASH_TOLERANCE, QTY_TOLERANCE
from .exceptions import make_exception

KEY = ["event_id", "account_id", "credit_type", "ticker"]


def reconcile(expected: pd.DataFrame, credits: pd.DataFrame):
    """Return (recon_table, exceptions)."""
    received = (credits.groupby(KEY, dropna=False)
                .agg(received_quantity=("quantity", "sum"),
                     received_net_cash=("net_cash", "sum"),
                     received_tds=("tds_deducted", "sum"),
                     credit_ids=("credit_id", lambda s: ", ".join(s)),
                     credit_date=("credit_date", "max"),
                     credit_source=("source", "first"))
                .reset_index())

    merged = expected.merge(received, on=KEY, how="outer", indicator=True)
    rows, exceptions = [], []

    for _, r in merged.iterrows():
        code, detail = None, ""
        detected = r["credit_date"] if pd.notna(r.get("credit_date")) else r.get("expected_date")

        if r["_merge"] == "left_only":
            code = "NOT_RECEIVED"
            what = (f"{int(r['expected_quantity'])} {r['ticker']} shares" if r["credit_type"] == "SHARES"
                    else f"Rs {r['expected_net_cash']:,.2f}")
            detail = f"Expected {what} - nothing credited"
        elif r["_merge"] == "right_only":
            code = "UNEXPECTED_CREDIT"
            detail = f"Credit {r['credit_ids']} has no matching entitlement"
        elif r["credit_type"] == "SHARES":
            diff = r["received_quantity"] - r["expected_quantity"]
            if abs(diff) > QTY_TOLERANCE:
                code = "QTY_BREAK"
                detail = (f"Expected {int(r['expected_quantity'])} {r['ticker']}, received "
                          f"{int(r['received_quantity'])} (difference {int(diff):+d})")
        else:  # CASH
            diff = r["received_net_cash"] - r["expected_net_cash"]
            if abs(diff) > CASH_TOLERANCE:
                tds_diff = r["received_tds"] - r["expected_tds"]
                code = "TDS_MISMATCH" if abs(tds_diff) > CASH_TOLERANCE else "CASH_BREAK"
                detail = (f"Expected net Rs {r['expected_net_cash']:,.2f} (TDS Rs {r['expected_tds']:,.2f}), "
                          f"received Rs {r['received_net_cash']:,.2f} (TDS Rs {r['received_tds']:,.2f})")

        if code:
            exceptions.append(make_exception("Reconciliation", code, r["event_id"], detail,
                                             detected, r["account_id"], r["ticker"]))
        rows.append({
            "event_id": r["event_id"], "account_id": r["account_id"],
            "credit_type": r["credit_type"], "ticker": r["ticker"],
            "expected_quantity": r.get("expected_quantity"),
            "received_quantity": r.get("received_quantity") if r["_merge"] != "left_only" else None,
            "expected_net_cash": r.get("expected_net_cash"),
            "received_net_cash": r.get("received_net_cash") if r["_merge"] != "left_only" else None,
            "expected_tds": r.get("expected_tds"),
            "received_tds": r.get("received_tds") if r["_merge"] != "left_only" else None,
            "credit_ids": r.get("credit_ids"), "credit_source": r.get("credit_source"),
            "status": "MATCHED" if code is None else "BREAK",
            "break_code": code, "detail": detail,
        })

    table = pd.DataFrame(rows).sort_values(["event_id", "account_id"]).reset_index(drop=True)
    # For readability: share recons show only quantities, cash recons only amounts
    shares = table["credit_type"] == "SHARES"
    table.loc[shares, ["expected_net_cash", "received_net_cash", "expected_tds", "received_tds"]] = None
    table.loc[~shares, ["expected_quantity", "received_quantity"]] = None
    return table, exceptions
