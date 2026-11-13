"""Simplified TDS (tax deducted at source) on cash dividends. Not tax advice."""

from .config import TDS_RATE_NO_PAN, TDS_RATES, TDS_THRESHOLD


def dividend_tds(client_type: str, pan_available: str, gross: float):
    """Return (tds_rate, tds_amount, reason) for one client's dividend."""
    if client_type == "MUTUAL_FUND":
        return 0.0, 0.0, "Exempt - mutual fund"

    if client_type == "NON_RESIDENT":
        rate = TDS_RATES["NON_RESIDENT"]
        return rate, round(gross * rate, 2), "Non-resident rate (no treaty documents on file)"

    # Residents: no TDS at or below the threshold
    if gross <= TDS_THRESHOLD:
        return 0.0, 0.0, f"Below Rs {TDS_THRESHOLD:,} threshold"

    if pan_available != "Y":
        return TDS_RATE_NO_PAN, round(gross * TDS_RATE_NO_PAN, 2), "No PAN on file - higher rate"

    rate = TDS_RATES[client_type]
    return rate, round(gross * rate, 2), "Standard resident rate"
