"""
Client notifications - one notice per event per eligible client.
In a bank this would be sent as a SWIFT MT564 or an email/portal notice.
"""

from pathlib import Path

import pandas as pd


def _fmt(d):
    return f"{d:%d-%b-%Y}" if pd.notna(d) else "-"


def _body(event, ent, client_name):
    lines = [
        "CORPORATE ACTION NOTIFICATION",
        "=" * 60,
        f"To:            {client_name} ({ent['account_id']})",
        f"Event ref:     {ent['event_id']}   ISO code: {event['iso_caev']} ({event['mand_volu']})",
        f"Security:      {event['ticker']}",
        f"Event:         {event['description']}",
        f"Ex-date:       {_fmt(event['ex_date'])}",
        f"Record date:   {_fmt(event['record_date'])}",
        f"Pay/credit:    {_fmt(event['pay_date'])}",
        "",
        f"Your settled holding on the record date: {int(ent['holding_at_record']):,} shares",
    ]
    etype = event["event_type"]
    if etype == "BONUS":
        lines.append(f"Bonus shares to be credited: {int(ent['entitled_quantity']):,} {event['ticker']}")
        lines.append("No action required. Your total cost is unchanged; cost per share falls.")
    elif etype == "CASH_DIVIDEND":
        lines += [f"Gross dividend:  Rs {ent['gross_cash']:,.2f}",
                  f"TDS deducted:    Rs {ent['tds_amount']:,.2f} ({ent['tds_rate']:.0%} - {ent['tax_note']})",
                  f"Net payable:     Rs {ent['net_cash']:,.2f}",
                  "No action required."]
    elif etype == "DEMERGER":
        lines += [f"New shares to be credited: {int(ent['entitled_quantity']):,} {event['new_ticker']}",
                  f"Cost split: {event['parent_cost_pct']:.2f}% {event['ticker']} / "
                  f"{event['child_cost_pct']:.2f}% {event['new_ticker']}",
                  "No action required."]
    elif etype == "RIGHTS":
        lines += [f"Rights entitlements (REs): {int(ent['entitled_quantity']):,}"
                  + (f"  (fraction {ent['fraction_ignored']} ignored)" if ent["fraction_ignored"] else ""),
                  f"Offer price: Rs {event['offer_price']:,.2f} per share",
                  "",
                  "ACTION REQUIRED - please choose one or more options:",
                  "  SUBSCRIBE - apply for new shares (pay offer price)",
                  f"  RENOUNCE  - sell your REs (by {_fmt(event['renunciation_deadline'])})",
                  "  LAPSE     - do nothing (REs expire worthless)",
                  f"Our deadline for your instruction: {_fmt(event['client_deadline'])}",
                  f"DEFAULT if no instruction: LAPSE"]
    elif etype == "MEETING":
        lines += [f"Votes you can cast: {int(ent['entitled_quantity']):,} per resolution",
                  "",
                  "ACTION REQUIRED - vote FOR / AGAINST / ABSTAIN on each resolution.",
                  f"Our deadline for your vote: {_fmt(event['client_deadline'])}",
                  "DEFAULT if no instruction: no vote cast"]
    lines += ["", "Corporate Actions Team - this is a practice notice generated from fake data."]
    return "\n".join(lines)


def write_notifications(events: pd.DataFrame, entitlements: pd.DataFrame,
                        accounts: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    ev = events.set_index("event_id")
    for _, ent in entitlements.iterrows():
        event = ev.loc[ent["event_id"]]
        name = accounts.loc[ent["account_id"], "client_name"]
        path = out_dir / f"{ent['event_id']}_{ent['account_id']}.txt"
        path.write_text(_body(event, ent, name), encoding="utf-8")
        index.append({"event_id": ent["event_id"], "account_id": ent["account_id"],
                      "action_required": event["mand_volu"] == "VOLU", "file": path.name})
    return pd.DataFrame(index)
