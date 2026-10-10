"""IBKR Flex Web Service sync — every request goes through a fake http_get.
No test here may reach interactivebrokers.com."""

import datetime as dt

import pytest

from core.money import usd
from sources.ibkr_flex import (
    BASE_URL,
    FlexError,
    FlexWebServiceClient,
    parse_send_response,
    parse_statement,
    sync_positions,
)

SEND_OK = '<FlexStatementResponse timestamp="10 September, 2026 01:00 AM EDT"><Status>Success</Status><ReferenceCode>7788990011</ReferenceCode><Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url></FlexStatementResponse>'
SEND_BAD_TOKEN = '<FlexStatementResponse timestamp="x"><Status>Fail</Status><ErrorCode>1015</ErrorCode><ErrorMessage>Token is invalid.</ErrorMessage></FlexStatementResponse>'
IN_PROGRESS = '<FlexStatementResponse timestamp="x"><Status>Warn</Status><ErrorCode>1019</ErrorCode><ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage></FlexStatementResponse>'
RATE_LIMITED = '<FlexStatementResponse timestamp="x"><Status>Fail</Status><ErrorCode>1018</ErrorCode><ErrorMessage>Too many requests have been made from this token.</ErrorMessage></FlexStatementResponse>'

STATEMENT = '''<FlexQueryResponse queryName="z-money-sync" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1234567" fromDate="20260909" toDate="20260909" period="LastBusinessDay" whenGenerated="20260910;010203">
<OpenPositions>
<OpenPosition accountId="U1234567" currency="USD" fxRateToBase="1.2841" assetCategory="STK" symbol="AMD" position="3.5084" markPrice="505.74" positionValue="1774.34" costBasisPrice="205.9962" costBasisMoney="722.71" levelOfDetail="SUMMARY"/>
<OpenPosition accountId="U1234567" currency="USD" fxRateToBase="1.2841" assetCategory="STK" symbol="AMD" position="1.5084" markPrice="505.74" positionValue="762.86" costBasisPrice="180.0" costBasisMoney="271.5" levelOfDetail="LOT"/>
<OpenPosition accountId="U1234567" currency="USD" fxRateToBase="1.2841" assetCategory="STK" symbol="VTI" position="3" markPrice="377.6" positionValue="1132.8" costBasisPrice="" costBasisMoney="1014.0" levelOfDetail="SUMMARY"/>
<OpenPosition accountId="U1234567" currency="SGD" fxRateToBase="1" assetCategory="STK" symbol="D05" position="100" markPrice="40.1" positionValue="4010" costBasisPrice="38.0" costBasisMoney="3800" levelOfDetail="SUMMARY"/>
<OpenPosition accountId="U1234567" currency="USD" fxRateToBase="1.2841" assetCategory="OPT" symbol="AMD 260117C00600000" position="1" markPrice="2.1" positionValue="210" costBasisPrice="3.0" costBasisMoney="300" levelOfDetail="SUMMARY"/>
<OpenPosition accountId="U1234567" currency="USD" fxRateToBase="1.2841" assetCategory="STK" symbol="GONE" position="0" markPrice="1" positionValue="0" costBasisPrice="5" costBasisMoney="0" levelOfDetail="SUMMARY"/>
<OpenPosition accountId="U1234567" currency="USD" fxRateToBase="1.2841" assetCategory="STK" symbol="NLSP.CVR" position="40" markPrice="0" positionValue="0" costBasisPrice="0" costBasisMoney="0" levelOfDetail="SUMMARY"/>
</OpenPositions>
<EquitySummaryInBase>
<EquitySummaryByReportDateInBase accountId="U1234567" currency="SGD" reportDate="20260908" cash="1300.0" stock="14500.0" total="15800.0"/>
<EquitySummaryByReportDateInBase accountId="U1234567" currency="SGD" reportDate="20260909" cash="1319.77" stock="14570.23" total="15890.0"/>
</EquitySummaryInBase>
<CashReport>
<CashReportCurrency accountId="U1234567" currency="BASE_SUMMARY" fromDate="20260909" toDate="20260909" endingCash="1319.77" endingSettledCash="1319.77"/>
<CashReportCurrency accountId="U1234567" currency="SGD" endingCash="1265.96" endingSettledCash="1265.96"/>
<CashReportCurrency accountId="U1234567" currency="USD" endingCash="41.91" endingSettledCash="41.91"/>
</CashReport>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>'''

NO_CASH_REPORT = STATEMENT.split("<CashReport>")[0] + "</FlexStatement></FlexStatements></FlexQueryResponse>"


class FakeHttp:
    """Serves a scripted sequence of (status, body) replies and records every call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, params, headers, timeout):
        self.calls.append((url, dict(params), dict(headers)))
        return self.replies.pop(0)


def make_client(replies, **kw):
    slept = []
    client = FlexWebServiceClient(token="tok", query_id="800969", http_get=FakeHttp(replies), sleep=slept.append, poll_interval=5.0, max_wait_seconds=30.0, **kw)
    return client, slept


class TestParseSendResponse:
    def test_success_returns_reference_code(self):
        assert parse_send_response(SEND_OK) == "7788990011"

    def test_failure_raises_with_ibkr_code_and_message(self):
        with pytest.raises(FlexError) as exc:
            parse_send_response(SEND_BAD_TOKEN)
        assert exc.value.code == 1015 and "Token is invalid" in str(exc.value)

    def test_non_xml_raises(self):
        with pytest.raises(FlexError):
            parse_send_response("<html>login page</html>")


class TestParseStatement:
    def test_parses_summary_positions_and_cash_rows(self):
        st = parse_statement(STATEMENT)
        assert st.account_id == "U1234567"
        assert st.when_generated == dt.datetime(2026, 9, 10, 1, 2, 3)
        by = {p.ticker: p for p in st.positions}
        assert by["AMD"].qty == 3.5084 and by["AMD"].avg_cost == 205.9962 and by["AMD"].currency == "USD"
        assert sum(1 for p in st.positions if p.ticker == "AMD") == 1  # the LOT row is dropped
        assert by["VTI"].avg_cost == pytest.approx(1014.0 / 3)  # costBasisMoney / position when price blank
        assert st.has_cash_report and {c.currency for c in st.cash} == {"BASE_SUMMARY", "SGD", "USD"}

    def test_usd_cash_reads_only_the_usd_row(self):
        st = parse_statement(STATEMENT)
        assert st.usd_cash() == usd(41.91)  # not the SGD row, not the SGD-converted BASE_SUMMARY
        assert st.base_summary().ending_cash == 1319.77

    def test_only_nonzero_usd_equities_enter_the_book(self):
        st = parse_statement(STATEMENT)
        assert [p.ticker for p in st.usd_equity_positions()] == ["AMD", "VTI"]
        skipped = {(p.ticker, p.currency, p.asset_category) for p in st.skipped_positions()}
        # Seen live 2026-09-10: IBKR files a contingent value right as STK/USD with zero cost; yfinance cannot price it
        assert skipped == {("D05", "SGD", "STK"), ("AMD 260117C00600000", "USD", "OPT"), ("GONE", "USD", "STK"), ("NLSP.CVR", "USD", "STK")}

    def test_in_progress_reply_raises_1019(self):
        with pytest.raises(FlexError) as exc:
            parse_statement(IN_PROGRESS)
        assert exc.value.code == 1019

    def test_missing_open_positions_section_is_an_error(self):
        xml = '<FlexQueryResponse><FlexStatements count="1"><FlexStatement accountId="U1"><CashReport/></FlexStatement></FlexStatements></FlexQueryResponse>'
        with pytest.raises(FlexError, match="Open Positions"):
            parse_statement(xml)

    def test_no_cash_report_means_cash_unknown_not_zero(self):
        st = parse_statement(NO_CASH_REPORT)
        assert st.has_cash_report is False and st.usd_cash() is None

    def test_cash_report_without_usd_row_is_zero_usd(self):
        xml = STATEMENT.replace('<CashReportCurrency accountId="U1234567" currency="USD" endingCash="41.91" endingSettledCash="41.91"/>', "")
        assert parse_statement(xml).usd_cash() == usd(0.0)


class TestClient:
    def test_two_step_flow_with_polling(self):
        client, slept = make_client([(200, SEND_OK), (200, IN_PROGRESS), (200, IN_PROGRESS), (200, STATEMENT)])
        st = client.fetch_statement()
        assert st.account_id == "U1234567"
        calls = client.http_get.calls
        assert calls[0][0] == f"{BASE_URL}/SendRequest" and calls[0][1] == {"t": "tok", "q": "800969", "v": "3"}
        assert calls[1][0] == f"{BASE_URL}/GetStatement" and calls[1][1]["q"] == "7788990011"
        assert all(c[2]["User-Agent"].startswith("z-money") for c in calls)
        assert slept == [1.0, 5.0, 5.0]  # pacing gap, then one poll interval per 1019

    def test_rate_limit_backs_off_longer(self):
        client, slept = make_client([(200, SEND_OK), (200, RATE_LIMITED), (200, STATEMENT)])
        client.fetch_statement()
        assert slept == [1.0, 15.0]

    def test_non_retryable_error_fails_fast(self):
        client, slept = make_client([(200, SEND_BAD_TOKEN)])
        with pytest.raises(FlexError) as exc:
            client.fetch_statement()
        assert exc.value.code == 1015 and slept == []

    def test_gives_up_after_max_wait(self):
        client, slept = make_client([(200, SEND_OK)] + [(200, IN_PROGRESS)] * 20, )
        with pytest.raises(FlexError) as exc:
            client.fetch_statement()
        assert exc.value.code == 1019
        assert sum(slept) <= 30.0 + 5.0 + 1.0

    def test_http_error_is_a_flex_error(self):
        client, _ = make_client([(503, "Service Unavailable")])
        with pytest.raises(FlexError, match="HTTP 503"):
            client.fetch_statement()


class TestSyncPositions:
    def test_reconciles_book_and_records_import_with_usd_cash(self, session, portfolio):
        # The test portfolio fixture disallows fractional shares (config.yaml
        # allows them); AMD's 3.5084 is a real fractional holding, so build a
        # fractional-friendly service for this one.
        from core.config import PortfolioConfig
        from core.portfolio import PortfolioService

        portfolio = PortfolioService(session, config=PortfolioConfig(allow_fractional=True))
        portfolio.add_manual_position("AMD", qty=3.5084, avg_cost=205.9962)
        portfolio.add_manual_position("STALE", qty=5, avg_cost=10.0)
        result = sync_positions(portfolio, parse_statement(STATEMENT), imported_at=dt.datetime(2026, 9, 10, 1, 5))

        assert result.reconciliation.summary() == {"matched": 1, "added": 1, "removed": 1}
        assert {p.ticker for p in portfolio.list_positions()} == {"AMD", "VTI"}
        assert result.cash_usd == usd(41.91) and portfolio.latest_cash_balance() == usd(41.91)
        last = portfolio.last_import()
        assert last.filename == "flex-web-service:U1234567:2026-09-10T01:02:03" and last.imported_at == dt.datetime(2026, 9, 10, 1, 5)
        assert [p.ticker for p in result.skipped] == ["D05", "AMD 260117C00600000", "GONE", "NLSP.CVR"]
        assert "USD cash USD 41.91" in result.summary() and "SGD" not in result.summary().split("base-currency")[0]

    def test_missing_cash_report_halts_without_touching_the_book(self, session, portfolio):
        portfolio.add_manual_position("STALE", qty=5, avg_cost=10.0)
        with pytest.raises(FlexError, match="Cash Report"):
            sync_positions(portfolio, parse_statement(NO_CASH_REPORT))
        assert [p.ticker for p in portfolio.list_positions()] == ["STALE"]
        assert portfolio.last_import() is None


class TestNavHistory:
    def test_parses_nav_days_in_base_currency(self):
        st = parse_statement(STATEMENT)
        assert [(n.report_date, n.total_base) for n in st.nav_history] == [("2026-09-08", 15800.0), ("2026-09-09", 15890.0)]
        assert st.base_currency == "SGD" and st.usd_fx_rate_to_base() == 1.2841

    def test_sync_stores_usd_account_values_and_upserts(self, session, portfolio):
        from core.config import PortfolioConfig
        from core.models import AccountValue
        from core.portfolio import PortfolioService
        from sqlalchemy import select

        portfolio = PortfolioService(session, config=PortfolioConfig(allow_fractional=True))
        result = sync_positions(portfolio, parse_statement(STATEMENT), imported_at=dt.datetime(2026, 9, 10, 1, 5))
        assert result.nav_days_written == 2 and "stored 2 NAV day(s)" in result.nav_note
        rows = {r.report_date: r for r in session.execute(select(AccountValue)).scalars()}
        assert round(rows["2026-09-09"].nav_usd, 2) == round(15890.0 / 1.2841, 2)
        assert rows["2026-09-09"].base_currency == "SGD" and rows["2026-09-09"].fx_rate_to_base == 1.2841
        # a second sync of the same days updates in place, no duplicates
        sync_positions(portfolio, parse_statement(STATEMENT.replace('total="15890.0"', 'total="15900.0"')), imported_at=dt.datetime(2026, 9, 11, 1, 5))
        rows = list(session.execute(select(AccountValue)).scalars())
        assert len(rows) == 2 and any(r.nav_base == 15900.0 for r in rows)

    def test_missing_nav_section_is_reported_not_fatal(self, session, portfolio):
        from core.config import PortfolioConfig
        from core.portfolio import PortfolioService

        portfolio = PortfolioService(session, config=PortfolioConfig(allow_fractional=True))
        xml = STATEMENT.split("<EquitySummaryInBase>")[0] + STATEMENT.split("</EquitySummaryInBase>")[1]
        result = sync_positions(portfolio, parse_statement(xml))
        assert result.nav_days_written == 0 and "Net Asset Value" in result.nav_note
