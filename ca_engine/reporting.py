"""Step 6 - Write every output table to CSV and to one formatted Excel workbook."""

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
STATUS_FILLS = {
    "PASS": "C6EFCE", "MATCHED": "C6EFCE", "PROCESSED": "C6EFCE",
    "FAIL": "FFC7CE", "BREAK": "FFC7CE", "FLAGGED": "FFC7CE",
    "High": "FFC7CE", "Medium": "FFEB9C", "Low": "DDEBF7",
}

# sheet name -> key in the results dict
SHEETS = [
    ("Summary", "kpis"),
    ("Event_Validation", "validation"),
    ("Eligibility", "eligibility"),
    ("Entitlements", "entitlements"),
    ("Instructions", "instructions"),
    ("Votes", "votes"),
    ("Cash_Ledger", "cash"),
    ("Reconciliation", "recon"),
    ("Exceptions", "exceptions"),
    ("Audit_Log", "audit"),
    ("Controls", "controls"),
    ("Opening_Positions", "opening_positions"),
    ("Final_Positions", "final_positions"),
]


def _format_sheet(ws):
    for cell in ws[1]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "A2"
    for col_idx, col in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row), start=1):
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(width + 2, 10), 60)
        for c in col[1:]:
            fill = STATUS_FILLS.get(str(c.value))
            if fill:
                c.fill = PatternFill("solid", fgColor=fill)
            if isinstance(c.value, float):
                c.number_format = "#,##0.00"
            elif hasattr(c.value, "year"):
                c.number_format = "dd-mmm-yyyy"


def write_outputs(results: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    csv_dir = out_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    xlsx = out_dir / "corporate_actions_report.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        for sheet, key in SHEETS:
            df = results[key]
            df.to_csv(csv_dir / f"{key}.csv", index=False)
            df.to_excel(writer, sheet_name=sheet, index=False)
            _format_sheet(writer.sheets[sheet])
    return xlsx
