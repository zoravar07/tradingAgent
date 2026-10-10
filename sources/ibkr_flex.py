"""IBKR Flex Web Service — automated position and cash sync.

A standalone HTTP API (no TWS/Gateway; works on IBKR Lite) that runs a
pre-built Activity Flex Query and returns the report. Two GET endpoints, per
https://www.interactivebrokers.com/docs/web-api/flex-web-service/ :

    SendRequest?t=<token>&q=<query id>&v=3   -> <ReferenceCode> (or an error)
    GetStatement?t=<token>&q=<reference>&v=3 -> the report, or code 1019
                                                 "Statement generation in progress"

Pacing is 1 request/second and 10/minute per token; every request must carry
a User-Agent header. Retryable codes (1001, 1004-1009, 1018, 1019, 1021)
are polled with backoff up to `max_wait_seconds`; everything else — bad
token (1015), expired token (1012), IP restriction (1013), invalid query
(1014) — fails immediately with the IBKR message attached.

The query must include two sections, both at Summary level of detail:
Open Positions (symbol, position, cost basis price, currency, asset
category) and Cash Report (currency, ending cash). The parser here is
attribute-driven, so extra fields are harmless and missing ones are named
in the error.

**Base currency vs position currency.** This account's base currency is
SGD; the book and every price in the pipeline are USD. The Cash Report
carries one row per currency plus a BASE_SUMMARY row converted to SGD —
`FlexStatement.usd_cash()` reads only the USD row, and `sync_positions`
puts only USD-denominated equities into the book, reporting anything else
as skipped rather than silently converting it. The SGD figures are kept on
the statement for the log, never used for NAV.

All network I/O goes through an injectable `http_get`; tests pass canned
XML and never touch IBKR.
"""

from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select

from core.money import Money, usd
from core.models import AccountValue
from core.portfolio import ImportedPosition, PortfolioService, ReconciliationResult

BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
FLEX_VERSION = "3"
USER_AGENT = "z-money/0.1 (Flex Web Service client; personal research tool)"
RETRYABLE_CODES = {1001, 1004, 1005, 1006, 1007, 1008, 1009, 1018, 1019, 1021}
RATE_LIMIT_CODE = 1018
EQUITY_ASSET_CATEGORIES = {"STK"}
# IBKR files contingent value rights, rights, warrants and SPAC units under
# STK with a dotted suffix (NLSP.CVR, XYZ.RTS, ABC.WS, ABC.U). None is
# priceable by yfinance, none has a cost basis, and one of them in the book
# blocks the run at the pricing gate — so they are reported as skipped.
NON_TRADEABLE_SUFFIXES = (".CVR", ".RT", ".RTS", ".WS", ".WT", ".WTS", ".U", ".UN")

HttpGet = Callable[[str, dict, dict, float], tuple[int, str]]  # (url, params, headers, timeout) -> (status, body)


class FlexError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


@dataclass
class FlexPosition:
    ticker: str
    qty: float
    avg_cost: float
    currency: str
    asset_category: str
    market_value: float | None = None
    fx_rate_to_base: float | None = None


@dataclass
class FlexCash:
    currency: str
    ending_cash: float | None
    ending_settled_cash: float | None


@dataclass
class FlexNav:
    """One day's account value in the base currency, from the Net Asset
    Value (NAV) / Equity Summary in Base section."""

    report_date: str  # YYYY-MM-DD
    total_base: float


@dataclass
class FlexStatement:
    account_id: str | None
    when_generated: dt.datetime | None
    positions: list[FlexPosition] = field(default_factory=list)
    cash: list[FlexCash] = field(default_factory=list)
    has_cash_report: bool = False
    nav_history: list[FlexNav] = field(default_factory=list)
    base_currency: str | None = None

    def usd_fx_rate_to_base(self) -> float | None:
        """Base-currency units per 1 USD, from any USD position's
        fxRateToBase (1.0 would mean the base currency is USD)."""
        for p in self.positions:
            if p.currency.upper() == "USD" and p.fx_rate_to_base:
                return p.fx_rate_to_base
        return None

    def usd_cash(self) -> Money | None:
        """The USD cash row's ending cash — the only cash figure the USD
        book may use. None when the statement carried no Cash Report at
        all; usd(0) when the report exists but holds no USD row."""
        if not self.has_cash_report:
            return None
        for row in self.cash:
            if row.currency.upper() == "USD" and row.ending_cash is not None:
                return usd(row.ending_cash)
        return usd(0.0)

    def base_summary(self) -> FlexCash | None:
        return next((row for row in self.cash if row.currency.upper() == "BASE_SUMMARY"), None)

    def usd_equity_positions(self) -> list[ImportedPosition]:
        return [ImportedPosition(ticker=p.ticker, qty=p.qty, avg_cost=p.avg_cost) for p in self.positions if _is_book_equity(p)]

    def skipped_positions(self) -> list[FlexPosition]:
        """Everything that is not a non-zero, tradeable USD equity: other
        currencies, options/futures/bonds, closed lines, CVRs/rights/
        warrants. Reported, never converted."""
        return [p for p in self.positions if not _is_book_equity(p)]


def _is_book_equity(p: "FlexPosition") -> bool:
    return (
        p.asset_category in EQUITY_ASSET_CATEGORIES
        and p.currency.upper() == "USD"
        and p.qty != 0
        and not p.ticker.upper().endswith(NON_TRADEABLE_SUFFIXES)
    )


# ------------------------------------------------------------- parsing


def _float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _error_from_response(root: ET.Element) -> FlexError:
    code = _float(root.findtext("ErrorCode"))
    message = (root.findtext("ErrorMessage") or "unknown Flex Web Service error").strip()
    code_int = int(code) if code is not None else None
    return FlexError(f"IBKR Flex Web Service error {code_int}: {message}", code=code_int)


def parse_send_response(xml_text: str) -> str:
    """The SendRequest reply: a ReferenceCode on Success, FlexError otherwise."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FlexError(f"SendRequest returned non-XML: {xml_text[:120]!r}") from exc
    if root.tag != "FlexStatementResponse":
        raise FlexError(f"SendRequest returned unexpected root <{root.tag}>")
    if (root.findtext("Status") or "").strip() != "Success":
        raise _error_from_response(root)
    reference = (root.findtext("ReferenceCode") or "").strip()
    if not reference:
        raise FlexError("SendRequest succeeded but carried no ReferenceCode")
    return reference


def _parse_when_generated(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    for fmt in ("%Y%m%d;%H%M%S", "%Y%m%d"):
        try:
            return dt.datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_statement(xml_text: str) -> FlexStatement:
    """The GetStatement reply. A FlexStatementResponse root means IBKR is
    still generating (1019) or refused; raise so the client can decide to
    poll or fail."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FlexError(f"GetStatement returned non-XML: {xml_text[:120]!r}") from exc
    if root.tag == "FlexStatementResponse":
        raise _error_from_response(root)
    if root.tag != "FlexQueryResponse":
        raise FlexError(f"GetStatement returned unexpected root <{root.tag}>")

    statement = root.find("./FlexStatements/FlexStatement")
    if statement is None:
        raise FlexError("Flex report has no <FlexStatement> — is the query an Activity Flex Query?")

    positions: list[FlexPosition] = []
    open_positions = statement.find("OpenPositions")
    if open_positions is None:
        raise FlexError("Flex report has no <OpenPositions> section — add 'Open Positions' to the query")
    for el in open_positions.findall("OpenPosition"):
        level = (el.get("levelOfDetail") or "SUMMARY").upper()
        if level != "SUMMARY":
            continue  # lot-level rows duplicate the summary line
        symbol = (el.get("symbol") or "").strip().upper()
        qty = _float(el.get("position"))
        cost = _float(el.get("costBasisPrice"))
        if cost is None:
            money = _float(el.get("costBasisMoney"))
            cost = (money / qty) if (money is not None and qty) else None
        if not symbol or qty is None:
            raise FlexError(f"OpenPosition row missing symbol/position: {dict(el.attrib)}")
        if cost is None:
            raise FlexError(f"OpenPosition {symbol} has no costBasisPrice or costBasisMoney — add 'Cost Basis Price' to the query")
        positions.append(
            FlexPosition(
                ticker=symbol, qty=qty, avg_cost=cost,
                currency=(el.get("currency") or "").strip().upper(),
                asset_category=(el.get("assetCategory") or "").strip().upper(),
                market_value=_float(el.get("positionValue")),
                fx_rate_to_base=_float(el.get("fxRateToBase")),
            )
        )

    cash: list[FlexCash] = []
    cash_report = statement.find("CashReport")
    if cash_report is not None:
        for el in cash_report.findall("CashReportCurrency"):
            cash.append(
                FlexCash(
                    currency=(el.get("currency") or "").strip().upper(),
                    ending_cash=_float(el.get("endingCash")),
                    ending_settled_cash=_float(el.get("endingSettledCash")),
                )
            )

    # Net Asset Value (NAV) section. IBKR emits it as <EquitySummaryInBase>
    # rows (EquitySummaryByReportDateInBase) or <NetAssetValue> rows; both
    # carry a report date and a `total` in the base currency.
    nav_history: list[FlexNav] = []
    base_currency: str | None = None
    for el in statement.iter():
        tag = el.tag.lower()
        if not (("equitysummary" in tag or "netassetvalue" in tag) and el.get("total") is not None):
            continue
        date_raw = el.get("reportDate") or el.get("date") or ""
        total = _float(el.get("total"))
        if len(date_raw) == 8 and date_raw.isdigit() and total is not None:
            nav_history.append(FlexNav(report_date=f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}", total_base=total))
            base_currency = base_currency or el.get("currency")
    nav_history.sort(key=lambda n: n.report_date)

    return FlexStatement(
        account_id=statement.get("accountId"),
        when_generated=_parse_when_generated(statement.get("whenGenerated")),
        positions=positions,
        cash=cash,
        has_cash_report=cash_report is not None,
        nav_history=nav_history,
        base_currency=base_currency,
    )


# ------------------------------------------------------------- client


def _default_http_get(url: str, params: dict, headers: dict, timeout: float) -> tuple[int, str]:
    import requests

    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    return response.status_code, response.text


@dataclass
class FlexWebServiceClient:
    token: str
    query_id: str
    http_get: HttpGet = _default_http_get
    sleep: Callable[[float], None] = time.sleep
    poll_interval: float = 5.0
    max_wait_seconds: float = 180.0
    timeout: float = 30.0

    def _get(self, endpoint: str, q: str) -> str:
        status, body = self.http_get(
            f"{BASE_URL}/{endpoint}", {"t": self.token, "q": q, "v": FLEX_VERSION},
            {"User-Agent": USER_AGENT}, self.timeout,
        )
        if status != 200:
            raise FlexError(f"{endpoint} returned HTTP {status}: {body[:200]}")
        return body

    def send_request(self) -> str:
        """Ask IBKR to generate the report; returns the reference code.
        Retries the transient codes with backoff inside max_wait_seconds."""
        waited = 0.0
        while True:
            try:
                return parse_send_response(self._get("SendRequest", self.query_id))
            except FlexError as exc:
                if exc.code not in RETRYABLE_CODES or waited >= self.max_wait_seconds:
                    raise
                delay = self.poll_interval * (3 if exc.code == RATE_LIMIT_CODE else 1)
                self.sleep(delay)
                waited += delay

    def get_statement(self, reference_code: str) -> FlexStatement:
        """Poll GetStatement until the report is ready or max_wait_seconds
        passes. Code 1019 is the normal 'not yet' answer."""
        waited = 0.0
        while True:
            try:
                return parse_statement(self._get("GetStatement", reference_code))
            except FlexError as exc:
                if exc.code not in RETRYABLE_CODES or waited >= self.max_wait_seconds:
                    raise
                delay = self.poll_interval * (3 if exc.code == RATE_LIMIT_CODE else 1)
                self.sleep(delay)
                waited += delay

    def fetch_statement(self) -> FlexStatement:
        reference = self.send_request()
        self.sleep(1.0)  # pacing: 1 request/second per token
        return self.get_statement(reference)


# ------------------------------------------------------------- sync


@dataclass
class SyncResult:
    reconciliation: ReconciliationResult
    cash_usd: Money
    account_id: str | None
    when_generated: dt.datetime | None
    skipped: list[FlexPosition]
    base_summary: FlexCash | None
    nav_days_written: int = 0
    nav_note: str = ""

    def summary(self) -> str:
        counts = self.reconciliation.summary()
        parts = [f"{counts.get(k, 0)} {k}" for k in ("matched", "updated", "added", "removed")]
        skipped = f"; skipped {len(self.skipped)} non-USD/non-equity line(s): {', '.join(p.ticker + '/' + p.currency for p in self.skipped)}" if self.skipped else ""
        base = f"; base-currency cash {self.base_summary.currency} {self.base_summary.ending_cash}" if self.base_summary else ""
        return f"account {self.account_id or '?'}: {', '.join(parts)}; USD cash {self.cash_usd}{base}{skipped}; {self.nav_note}"


def sync_positions(portfolio: PortfolioService, statement: FlexStatement, imported_at: dt.datetime | None = None) -> SyncResult:
    """Reconcile the book against the broker statement and record the sync
    as a `position_imports` row (source = the Flex account and generation
    time). Raises FlexError, without touching the book, when the statement
    can't answer the two questions the pipeline needs: what USD equities
    are held, and how much USD cash there is."""
    if not statement.has_cash_report:
        raise FlexError("Flex report has no <CashReport> section — add 'Cash Report' to the query; USD cash is required for NAV")
    cash = statement.usd_cash()
    assert cash is not None  # has_cash_report guarantees a Money
    rows = statement.usd_equity_positions()
    label = f"flex-web-service:{statement.account_id or 'unknown'}:{statement.when_generated.isoformat() if statement.when_generated else 'unknown'}"
    result = portfolio.record_broker_sync(rows, cash_usd=cash, source=label, imported_at=imported_at)
    nav_written, nav_note = record_account_values(portfolio.session, statement, source=label, synced_at=result.imported_at)
    return SyncResult(
        reconciliation=result, cash_usd=cash, account_id=statement.account_id,
        when_generated=statement.when_generated, skipped=statement.skipped_positions(), base_summary=statement.base_summary(),
        nav_days_written=nav_written, nav_note=nav_note,
    )


def record_account_values(session, statement: FlexStatement, source: str, synced_at: dt.datetime) -> tuple[int, str]:
    """Upsert one `account_values` row per NAV day in the statement,
    converting base currency -> USD with the report's own USD fx rate.
    Returns (rows written, a one-line note for the log). Nothing is written
    when the section is missing or the fx rate can't be read — and the note
    says which, so a chart that stays empty has a stated cause."""
    if not statement.nav_history:
        return 0, "no NAV rows in the report (add the 'Net Asset Value (NAV)' section to the Flex query)"
    fx = statement.usd_fx_rate_to_base()
    if not fx:
        return 0, f"{len(statement.nav_history)} NAV row(s) but no USD fx rate on the report; not stored"
    base = (statement.base_currency or "BASE").upper()
    written = 0
    for nav in statement.nav_history:
        row = session.execute(select(AccountValue).where(AccountValue.report_date == nav.report_date)).scalar_one_or_none()
        nav_usd = nav.total_base / fx
        if row is None:
            session.add(AccountValue(report_date=nav.report_date, nav_base=nav.total_base, base_currency=base, fx_rate_to_base=fx, nav_usd=nav_usd, source=source, synced_at=synced_at))
        else:
            row.nav_base, row.base_currency, row.fx_rate_to_base, row.nav_usd, row.source, row.synced_at = nav.total_base, base, fx, nav_usd, source, synced_at
        written += 1
    session.flush()
    first, last = statement.nav_history[0].report_date, statement.nav_history[-1].report_date
    return written, f"stored {written} NAV day(s) {first}..{last} at {fx:.4f} {base}/USD (latest USD {statement.nav_history[-1].total_base / fx:,.2f})"
