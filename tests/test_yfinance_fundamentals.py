"""Equivalence tests for the yfinance -> FMP fundamentals field mapping.

The fixtures in tests/fixtures/fundamentals/ are REAL data captured from
both APIs for the same tickers at the same moment during development (not
synthetic) — {ticker}_fmp_income.json / {ticker}_fmp_cashflow.json are raw
FMPClient responses; {ticker}_yf_income_raw.json / {ticker}_yf_cashflow_raw.json
are yfinance's income_stmt/cashflow DataFrames transposed to plain dicts
(sources.yfinance_source._dataframe_to_raw_rows' output shape). This file
verifies map_statement_row transforms the yfinance side into values that
exactly match the FMP side, field by field — the actual claim in
sources/yfinance_source.py's module docstring, checked rather than assumed.

No network calls — everything here reads frozen JSON.
"""

import json
from pathlib import Path

import pytest

from sources.yfinance_source import (
    CASH_FLOW_FIELD_MAP,
    INCOME_STATEMENT_FIELD_MAP,
    map_statement_row,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fundamentals"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("ticker", ["amd", "msft"])
class TestIncomeStatementEquivalence:
    def test_every_mapped_field_matches_fmp_exactly(self, ticker):
        fmp_rows = load(f"{ticker}_fmp_income.json")
        yf_raw_rows = load(f"{ticker}_yf_income_raw.json")
        assert len(fmp_rows) == len(yf_raw_rows)

        for fmp_row, yf_raw_row in zip(fmp_rows, yf_raw_rows):
            mapped = map_statement_row(yf_raw_row, INCOME_STATEMENT_FIELD_MAP)
            for fmp_key in INCOME_STATEMENT_FIELD_MAP:
                assert mapped[fmp_key] == pytest.approx(fmp_row[fmp_key], rel=1e-9), (
                    f"{ticker} {fmp_key}: mapped={mapped[fmp_key]} fmp={fmp_row[fmp_key]}"
                )

    def test_fields_that_diverged_across_periods_are_not_mapped(self, ticker):
        # these matched for the latest fiscal year but diverged for the
        # prior one — asserting their absence keeps this test honest if
        # someone adds one back without re-checking both periods
        for dropped in ("incomeBeforeTax", "sellingGeneralAndAdministrativeExpenses", "operatingIncome", "ebitda"):
            assert dropped not in INCOME_STATEMENT_FIELD_MAP


@pytest.mark.parametrize("ticker", ["amd", "msft"])
class TestCashFlowStatementEquivalence:
    def test_every_mapped_field_matches_fmp_exactly(self, ticker):
        fmp_rows = load(f"{ticker}_fmp_cashflow.json")
        yf_raw_rows = load(f"{ticker}_yf_cashflow_raw.json")
        assert len(fmp_rows) == len(yf_raw_rows)

        for fmp_row, yf_raw_row in zip(fmp_rows, yf_raw_rows):
            mapped = map_statement_row(yf_raw_row, CASH_FLOW_FIELD_MAP)
            for fmp_key in CASH_FLOW_FIELD_MAP:
                assert mapped[fmp_key] == pytest.approx(fmp_row[fmp_key], rel=1e-9), (
                    f"{ticker} {fmp_key}: mapped={mapped[fmp_key]} fmp={fmp_row[fmp_key]}"
                )

    def test_depreciation_and_amortization_is_deliberately_not_mapped(self, ticker):
        assert "depreciationAndAmortization" not in CASH_FLOW_FIELD_MAP


class TestMapStatementRow:
    def test_missing_field_maps_to_none(self):
        result = map_statement_row({"date": "2026-01-01"}, {"revenue": "Total Revenue"})
        assert result == {"date": "2026-01-01", "revenue": None}

    def test_nan_maps_to_none(self):
        result = map_statement_row({"date": "2026-01-01", "Total Revenue": float("nan")}, {"revenue": "Total Revenue"})
        assert result["revenue"] is None

    def test_non_numeric_maps_to_none(self):
        result = map_statement_row({"date": "2026-01-01", "Total Revenue": "not a number"}, {"revenue": "Total Revenue"})
        assert result["revenue"] is None

    def test_ordinary_value_passes_through_as_float(self):
        result = map_statement_row({"date": "2026-01-01", "Total Revenue": 1000}, {"revenue": "Total Revenue"})
        assert result["revenue"] == 1000.0
