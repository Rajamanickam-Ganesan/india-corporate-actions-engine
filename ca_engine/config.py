"""
Settings and business rules for the engine.

Everything an operations team might want to change lives here, so the
processing code does not hard-code any rule.

NOTE: all events and numbers in /data are FAKE practice data.
The tax rules below are SIMPLIFIED for learning - they are not tax advice.
"""

# ---------------------------------------------------------------------------
# Settlement cycle
# ---------------------------------------------------------------------------
# Indian equities settle T+1 (trade date + 1 business day).
# A buyer only appears on the register once the trade has SETTLED, so a share
# bought ON the record date settles the day after and is NOT eligible.
SETTLEMENT_DAYS = 1

# ---------------------------------------------------------------------------
# Event types this engine knows how to process
# ---------------------------------------------------------------------------
SUPPORTED_EVENT_TYPES = {"BONUS", "CASH_DIVIDEND", "RIGHTS", "DEMERGER", "MEETING"}

# Fields that must be filled in for each event type
REQUIRED_FIELDS = {
    "BONUS": ["ratio_new", "ratio_old", "record_date", "pay_date"],
    "CASH_DIVIDEND": ["cash_amount", "record_date", "pay_date"],
    "RIGHTS": ["ratio_new", "ratio_old", "offer_price", "record_date", "pay_date",
               "renunciation_deadline", "client_deadline", "market_deadline"],
    "DEMERGER": ["ratio_new", "ratio_old", "new_ticker", "parent_cost_pct",
                 "child_cost_pct", "record_date", "pay_date"],
    "MEETING": ["record_date", "pay_date", "client_deadline", "market_deadline"],
}

# Fields used to spot the same event arriving twice (e.g. from two vendors)
DUPLICATE_KEY = ["ticker", "event_type", "record_date", "ratio_new", "ratio_old", "cash_amount"]

# ---------------------------------------------------------------------------
# TDS (tax deducted at source) on dividends - SIMPLIFIED
# ---------------------------------------------------------------------------
TDS_THRESHOLD = 10_000          # no TDS for residents if dividend is at or below this
TDS_RATES = {
    "RESIDENT_INDIVIDUAL": 0.10,
    "RESIDENT_COMPANY": 0.10,
    "NON_RESIDENT": 0.20,       # simplified: ignores surcharge, cess and treaty rates
    "MUTUAL_FUND": 0.00,        # mutual funds are exempt from dividend TDS
}
TDS_RATE_NO_PAN = 0.20          # higher rate when the client has no PAN on file

# ---------------------------------------------------------------------------
# Reconciliation tolerances
# ---------------------------------------------------------------------------
CASH_TOLERANCE = 1.00           # Rs - differences of Rs 1 or less are treated as rounding
QTY_TOLERANCE = 0               # shares must match exactly

# ---------------------------------------------------------------------------
# Exception catalogue
# code: (severity, owner team, SLA in business days, required action)
# ---------------------------------------------------------------------------
EXCEPTION_CATALOGUE = {
    # --- event data problems (found when the feed is validated) ---
    "UNSUPPORTED_TYPE": ("High", "Event Management", 1,
                         "Event type not supported - process manually and raise a system enhancement"),
    "MISSING_FIELDS": ("High", "Event Management", 1,
                       "Complete the missing fields from the NSE/BSE announcement before processing"),
    "DUPLICATE_EVENT": ("Medium", "Event Management", 1,
                        "Compare both vendor records with the exchange announcement; keep one golden record"),
    "INVALID_AMOUNT": ("High", "Event Management", 1,
                       "Check the amount against the issuer's exchange filing and correct the event"),
    "INVALID_RATIO": ("High", "Event Management", 1,
                      "Check the ratio against the issuer's exchange filing and correct the event"),
    "DATE_SEQUENCE": ("High", "Event Management", 1,
                      "Dates are in the wrong order - confirm ex/record/pay dates with the issuer filing"),
    "ALLOCATION_NOT_100": ("High", "Event Management", 1,
                           "Cost split does not add to 100% - confirm the cost apportionment with the issuer"),
    "TICKER_NOT_HELD": ("Low", "Event Management", 2,
                        "No client holds this stock - close the event with no action"),
    # --- client instruction problems (voluntary events) ---
    "INELIGIBLE_INSTRUCTION": ("Medium", "Corporate Actions Analyst", 1,
                               "Reject - tell the client they were not a holder on the record date"),
    "OVER_ELECTION": ("High", "Corporate Actions Analyst", 0,
                      "Processed up to the entitlement only - contact the client about the excess"),
    "LATE_INSTRUCTION": ("High", "Corporate Actions Supervisor", 0,
                         "Received after client deadline - escalate and submit on a best-efforts basis"),
    "REJECTED_LATE": ("High", "Corporate Actions Supervisor", 0,
                      "Received after the market deadline - cannot be submitted; inform the client"),
    "NO_INSTRUCTION": ("Medium", "Corporate Actions Analyst", 1,
                       "No instruction received - default option (lapse) applied; log the client chaser"),
    "OVER_VOTE": ("High", "Proxy Voting Team", 0,
                  "Votes capped at eligible holding - confirm the correct number with the client"),
    "NO_VOTE": ("Low", "Proxy Voting Team", 1,
                "No vote submitted - no action unless the client asks"),
    # --- reconciliation breaks (expected vs received) ---
    "QTY_BREAK": ("High", "Reconciliation Team", 1,
                  "Share credit differs from entitlement - raise a claim with the depository/registrar"),
    "CASH_BREAK": ("High", "Reconciliation Team", 1,
                   "Cash received differs from entitlement - investigate with the registrar"),
    "TDS_MISMATCH": ("High", "Tax Operations", 2,
                     "Registrar applied a different TDS rate - check client tax documents and raise a correction"),
    "NOT_RECEIVED": ("High", "Reconciliation Team", 1,
                     "Expected credit not received - chase the depository/registrar"),
    "UNEXPECTED_CREDIT": ("Medium", "Reconciliation Team", 1,
                          "Credit received with no matching entitlement - investigate before releasing"),
}

SEVERITY_ORDER = {"High": 1, "Medium": 2, "Low": 3}
