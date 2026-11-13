"""
The full processing run, start to finish:

    1. Load inputs
    2. Validate the event feed           (bad events -> exception queue)
    3. Apply settled trades up to each record date and find eligible holders
    4. Process each event                (bonus / dividend / rights / demerger / AGM vote)
    5. Reconcile expected vs received    (breaks -> exception queue)
    6. Run control checks, write notices and reports
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import SEVERITY_ORDER
from .data_loader import load_inputs
from .dates import settlement_date
from .notifications import write_notifications
from .position_book import PositionBook
from .processors import PROCESSORS
from .reconciliation import reconcile
from .reporting import write_outputs
from .validation import validate_feed


def _frame(rows, columns=None):
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns or [])


def _elections_within_entitlement(instructions, entitlements) -> bool:
    if instructions.empty:
        return True
    processed = instructions.groupby(["event_id", "account_id"])["processed_qty"].sum()
    allowed = (entitlements[entitlements["event_type"] == "RIGHTS"]
               .set_index(["event_id", "account_id"])["entitled_quantity"]
               .reindex(processed.index, fill_value=0))
    return bool((processed <= allowed).all())


def run_pipeline(data_dir="data", output_dir="outputs", write=True) -> dict:
    data = load_inputs(Path(data_dir))
    accounts = data["accounts"].set_index("account_id")
    ctx = {"accounts": accounts, "instructions": data["instructions"],
           "run_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # ------------------------------------------------------------------ setup
    book = PositionBook(data["positions"])
    opening_positions = book.to_frame()
    opening_cost = book.total_cost()

    trades = data["trades"].copy()
    trades["settlement_date"] = trades["trade_date"].apply(settlement_date)
    trades = trades.sort_values(["settlement_date", "trade_id"]).reset_index(drop=True)
    applied, trade_cost_change = set(), 0.0

    def apply_trades_settled_by(cutoff):
        nonlocal trade_cost_change
        for _, tr in trades.iterrows():
            if tr["trade_id"] not in applied and tr["settlement_date"] <= cutoff:
                before = book.total_cost()
                book.apply_trade(tr["account_id"], tr["ticker"], tr["side"], int(tr["quantity"]), tr["price"])
                trade_cost_change += book.total_cost() - before
                applied.add(tr["trade_id"])

    # ------------------------------------------------------- 2. validation
    held = set(data["positions"]["ticker"]) | set(trades["ticker"])
    valid_events, validation, exceptions = validate_feed(data["events"], held)

    # -------------------------------------------- 3 + 4. eligibility & processing
    collected = {k: [] for k in ["entitlements", "audit", "cash", "expected", "instructions", "votes"]}
    eligibility = []

    for _, event in valid_events.sort_values(["record_date", "event_id"]).iterrows():
        apply_trades_settled_by(event["record_date"])
        holders = book.holders(event["ticker"])

        # Eligibility snapshot - including trades that had NOT settled by record date
        pending = trades[(trades["ticker"] == event["ticker"])
                         & (trades["trade_date"] <= event["record_date"])
                         & (trades["settlement_date"] > event["record_date"])]
        for acc in sorted(set(holders) | set(pending["account_id"])):
            acc_pending = pending[pending["account_id"] == acc]
            eligibility.append({
                "event_id": event["event_id"], "ticker": event["ticker"],
                "record_date": event["record_date"], "account_id": acc,
                "settled_qty_on_record_date": holders.get(acc, 0),
                "unsettled_trades": "; ".join(
                    f"{r.trade_id} {r.side} {r.quantity} (trade {r.trade_date:%d-%b}, settles {r.settlement_date:%d-%b})"
                    for r in acc_pending.itertuples()) or None,
                "eligible": "Y" if holders.get(acc, 0) > 0 else "N",
            })

        result = PROCESSORS[event["event_type"]](event, holders, book, ctx)
        for k in collected:
            collected[k].extend(result[k])
        exceptions.extend(result["exceptions"])

    apply_trades_settled_by(pd.Timestamp.max)   # any trades after the last event

    # ------------------------------------------------------ 5. reconciliation
    expected = _frame(collected["expected"])
    recon, recon_exceptions = reconcile(expected, data["credits"])
    exceptions.extend(recon_exceptions)

    # ------------------------------------------------------------ tidy tables
    entitlements = _frame(collected["entitlements"])
    audit = _frame(collected["audit"])
    cash = _frame(collected["cash"])
    instructions = _frame(collected["instructions"])
    votes = _frame(collected["votes"])
    exc = _frame(exceptions)
    exc["severity_rank"] = exc["severity"].map(SEVERITY_ORDER)
    exc = (exc.sort_values(["severity_rank", "event_id", "account_id"])
              .drop(columns="severity_rank").reset_index(drop=True))
    exc.insert(0, "exception_id", [f"EXC-{i:03d}" for i in range(1, len(exc) + 1)])

    validation.loc[validation["is_valid"], "processing_status"] = "PROCESSED"
    final_positions = book.to_frame()

    # ------------------------------------------------------------ 6. controls
    final_cost = book.total_cost()
    rights_paid = -cash.loc[cash["movement"] == "RIGHTS SUBSCRIPTION PAID", "net_amount"].sum()
    explained = opening_cost + trade_cost_change + rights_paid
    expected_ids = set(expected[["event_id", "account_id"]].itertuples(index=False, name=None))
    recon_ids = set(recon[["event_id", "account_id"]].itertuples(index=False, name=None))

    def ctrl(name, ok, detail):
        return {"control": name, "result": "PASS" if ok else "FAIL", "detail": detail}

    controls = pd.DataFrame([
        ctrl("Feed has no duplicate event IDs", not data["events"]["event_id"].duplicated().any(),
             f"{data['events']['event_id'].nunique()} unique IDs in {len(data['events'])} records"),
        ctrl("Every invalid event is in the exception queue",
             set(validation.loc[~validation["is_valid"], "event_id"])
             <= set(exc.loc[exc["stage"] == "Event validation", "event_id"]),
             f"{(~validation['is_valid']).sum()} events flagged"),
        ctrl("Cost basis preserved on every processed event", (audit["basis_check"] == "PASS").all(),
             f"{(audit['basis_check'] == 'PASS').sum()} of {len(audit)} audit rows PASS"),
        ctrl("Total cost explained (opening + trades + rights paid = final)",
             abs(final_cost - explained) <= 0.01,
             f"Opening Rs {opening_cost:,.2f} + trades Rs {trade_cost_change:,.2f} + rights "
             f"Rs {rights_paid:,.2f} = Rs {explained:,.2f}; final book Rs {final_cost:,.2f}"),
        ctrl("No election processed above entitlement", _elections_within_entitlement(instructions, entitlements),
             "Processed elections compared with rights entitlements per event and account"),
        ctrl("No votes counted above eligible holding",
             votes.empty or (votes["counted_votes"] <= votes["eligible_shares"]).all(),
             f"{len(votes)} vote instructions checked"),
        ctrl("Every expected credit has been reconciled", expected_ids <= recon_ids,
             f"{len(expected)} expected credits, {len(recon)} recon rows"),
        ctrl("Every exception has an owner and SLA due date",
             exc["owner"].notna().all() and exc["sla_due_date"].notna().all(),
             f"{len(exc)} exceptions"),
    ])

    # ---------------------------------------------------------------- KPIs
    n_events, n_ok = len(validation), int(validation["is_valid"].sum())
    matched = int((recon["status"] == "MATCHED").sum())
    divs = cash[cash["movement"] == "DIVIDEND RECEIVED"]
    kpis = pd.DataFrame([
        ("Events received", n_events),
        ("Events processed automatically", n_ok),
        ("Events flagged at validation", n_events - n_ok),
        ("Straight-through processing (STP) rate", f"{n_ok / n_events:.0%}"),
        ("Client accounts", len(accounts)),
        ("Entitlement rows calculated", len(entitlements)),
        ("Expected depository/registrar credits", len(expected)),
        ("Credits matched", matched),
        ("Reconciliation breaks", len(recon) - matched),
        ("Reconciliation match rate", f"{matched / len(recon):.0%}"),
        ("Exceptions - total", len(exc)),
        ("Exceptions - High", int((exc["severity"] == "High").sum())),
        ("Exceptions - Medium", int((exc["severity"] == "Medium").sum())),
        ("Exceptions - Low", int((exc["severity"] == "Low").sum())),
        ("Dividends - gross (Rs)", round(divs["gross"].sum(), 2)),
        ("Dividends - TDS (Rs)", round(divs["tds"].sum(), 2)),
        ("Dividends - net (Rs)", round(divs["net_amount"].sum(), 2)),
        ("Rights subscription paid (Rs)", round(rights_paid, 2)),
        ("Controls passed", f"{(controls['result'] == 'PASS').sum()} of {len(controls)}"),
    ], columns=["metric", "value"])
    kpis["value"] = kpis["value"].astype(str)

    results = {
        "kpis": kpis, "validation": validation, "eligibility": _frame(eligibility),
        "entitlements": entitlements, "instructions": instructions, "votes": votes,
        "cash": cash, "recon": recon, "exceptions": exc, "audit": audit,
        "controls": controls, "opening_positions": opening_positions,
        "final_positions": final_positions, "expected": expected,
    }

    if write:
        out = Path(output_dir)
        results["notifications"] = write_notifications(valid_events, entitlements, accounts,
                                                       out / "notifications")
        results["report_path"] = write_outputs(results, out)
        results["notifications"].to_csv(out / "csv" / "notifications.csv", index=False)
    return results
