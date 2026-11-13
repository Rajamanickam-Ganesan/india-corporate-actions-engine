"""Load the input CSV files and parse dates."""

from pathlib import Path

import pandas as pd

DATE_COLUMNS = {
    "events_feed.csv": ["announcement_date", "ex_date", "record_date", "pay_date",
                        "renunciation_deadline", "client_deadline", "market_deadline"],
    "trades.csv": ["trade_date"],
    "client_instructions.csv": ["received_date"],
    "depository_credits.csv": ["credit_date"],
}


def load_inputs(data_dir: Path) -> dict:
    """Read every input file into a DataFrame. Returns a dict keyed by short name."""
    data_dir = Path(data_dir)
    files = {
        "accounts": "accounts.csv",
        "securities": "securities.csv",
        "positions": "opening_positions.csv",
        "trades": "trades.csv",
        "events": "events_feed.csv",
        "instructions": "client_instructions.csv",
        "credits": "depository_credits.csv",
    }
    data = {}
    for name, filename in files.items():
        df = pd.read_csv(data_dir / filename)
        for col in DATE_COLUMNS.get(filename, []):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        data[name] = df
    return data
