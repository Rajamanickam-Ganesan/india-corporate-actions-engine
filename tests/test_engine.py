"""
Tests - run with:  python -m pytest -q

Each test checks one business rule, so a failing test tells you exactly
which rule broke.
"""

from pathlib import Path

import pandas as pd
import pytest

from ca_engine import run_pipeline
from ca_engine.dates import settlement_date
from ca_engine.processors import _entitled
from ca_engine.tax import dividend_tds

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def results():
    return run_pipeline(DATA, write=False)


def _row(df, **filters):
    mask = pd.Series(True, index=df.index)
    for col, val in filters.items():
        mask &= df[col] == val
    assert mask.sum() == 1, f"expected exactly one row for {filters}"
    return df[mask].iloc[0]


# ---------- settlement & eligibility ----------
def test_t_plus_1_settlement_skips_weekend():
    assert settlement_date("2026-02-13") == pd.Timestamp("2026-02-16")   # Fri -> Mon


def test_buy_on_record_date_is_not_eligible(results):
    row = _row(results["eligibility"], event_id="CA-2026-0002", account_id="CLT005")
    assert row["eligible"] == "N"


def test_buy_day_before_record_date_is_eligible(results):
    row = _row(results["eligibility"], event_id="CA-2026-0001", account_id="CLT002")
    assert row["settled_qty_on_record_date"] == 100      # 50 opening + 50 bought 13-Feb


def test_sell_on_record_date_keeps_entitlement(results):
    row = _row(results["entitlements"], event_id="CA-2026-0001", account_id="CLT003")
    assert row["entitled_quantity"] == 200


# ---------- event calculations ----------
def test_rights_fraction_is_dropped():
    assert _entitled(150, 1, 14) == (10, 0.7143)


def test_bonus_2_for_1(results):
    assert _row(results["entitlements"], event_id="CA-2026-0003", account_id="CLT004")["entitled_quantity"] == 2400


def test_demerger_cost_split_preserves_total(results):
    fp = results["final_positions"].set_index(["account_id", "ticker"])
    total = fp.loc[("CLT001", "TATAMOTORS"), "total_cost"] + fp.loc[("CLT001", "TMCV"), "total_cost"]
    assert total == pytest.approx(250 * 700)
    assert fp.loc[("CLT001", "TMCV"), "total_cost"] == pytest.approx(250 * 700 * 0.35)


# ---------- tax ----------
@pytest.mark.parametrize("client_type,pan,gross,expected_tds", [
    ("RESIDENT_INDIVIDUAL", "Y", 1_600, 0),        # below threshold
    ("RESIDENT_INDIVIDUAL", "N", 24_000, 4_800),   # no PAN -> 20%
    ("NON_RESIDENT", "Y", 4_000, 800),             # 20%, no threshold
    ("MUTUAL_FUND", "Y", 160_000, 0),              # exempt
    ("RESIDENT_COMPANY", "Y", 20_000, 2_000),      # 10%
])
def test_dividend_tds(client_type, pan, gross, expected_tds):
    assert dividend_tds(client_type, pan, gross)[1] == expected_tds


# ---------- validation ----------
@pytest.mark.parametrize("event_id,code", [
    ("CA-2026-0004", "DUPLICATE_EVENT"),
    ("CA-2026-0008", "INVALID_AMOUNT"),
    ("CA-2026-0009", "TICKER_NOT_HELD"),
    ("CA-2026-0010", "DATE_SEQUENCE"),
])
def test_bad_events_are_flagged(results, event_id, code):
    assert _row(results["validation"], event_id=event_id)["reason_code"] == code


def test_duplicate_bonus_not_applied_twice(results):
    fp = results["final_positions"].set_index(["account_id", "ticker"])
    assert fp.loc[("CLT004", "BSE"), "quantity"] == 3600     # 1200 + 2400, not + 4800


# ---------- instructions & votes ----------
def test_over_election_is_capped(results):
    assert _row(results["instructions"], instruction_id="INS-003")["processed_qty"] == 10


def test_over_vote_is_capped(results):
    assert _row(results["votes"], instruction_id="VOT-001")["counted_votes"] == 200


# ---------- reconciliation & controls ----------
@pytest.mark.parametrize("event_id,account_id,code", [
    ("CA-2026-0001", "CLT005", "QTY_BREAK"),
    ("CA-2026-0005", "CLT002", "TDS_MISMATCH"),
    ("CA-2026-0005", "CLT004", "TDS_MISMATCH"),
    ("CA-2026-0007", "CLT003", "NOT_RECEIVED"),
])
def test_recon_breaks_found(results, event_id, account_id, code):
    assert _row(results["recon"], event_id=event_id, account_id=account_id)["break_code"] == code


def test_all_controls_pass(results):
    assert (results["controls"]["result"] == "PASS").all()
