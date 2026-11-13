"""Business-day helpers.

Simplification: only weekends are treated as non-business days.
A production system would also load the NSE trading-holiday calendar.
"""

import numpy as np
import pandas as pd

from .config import SETTLEMENT_DAYS


def add_business_days(date, days: int) -> pd.Timestamp:
    """Move a date forward by a number of business days (Mon-Fri)."""
    d = np.datetime64(pd.Timestamp(date).date())
    return pd.Timestamp(np.busday_offset(d, days, roll="forward"))


def settlement_date(trade_date) -> pd.Timestamp:
    """Settlement date of a trade under the T+N cycle set in config."""
    return add_business_days(trade_date, SETTLEMENT_DAYS)
