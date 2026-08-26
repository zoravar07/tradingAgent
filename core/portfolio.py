"""Portfolio module — §10 build-order step 2.

Owns Zopro's own `positions` table (the source of truth, per §2) and the three
ways positions get into it:

  1. `import_flex_csv`   — IBKR Flex Query "Open Positions" CSV, reconciled
                            against the current book.
  2. `mark_filled`       — you placed an order manually in IBKR; tell Zopro
                            what actually filled and it updates its book.
  3. `add_manual_position` / `edit_manual_position` / `remove_position`
                            — hand entry, mainly for the initial load.

Design notes that aren't obvious from the spec text alone:

* Reconciliation trusts the CSV as ground truth for *what's actually held*.
  An IBKR "Open Positions" Flex Query lists every open position in the
  account, so a ticker present in Zopro's book but absent from the CSV really
  is gone (sold outside the app, a bad manual entry, a mark-filled mistake) —
  removing it is correct, not destructive-by-accident. Every change
  reconciliation makes is recorded in `reconciliation_json` on the
  `position_imports` row so mismatches are visible, not just silently fixed.

* The §2 drift warning ("last import more than N days old") is computed from
  the most recent `position_imports.imported_at`, not from any position's
  `last_verified_at`. `mark_filled` does update `last_verified_at` on the
  position it touches (useful audit trail — "when did we last hear anything
  about this position"), but it must NOT clear the drift warning: it's a
  self-reported fill, not a broker-confirmed one, which is exactly the kind
  of entry error CSV reconciliation exists to catch.

* **The base-currency trap.** IBKR's account dashboard — NAV, cash balance,
  "excess liquidity" — displays figures in the account's BASE CURRENCY by
  default (e.g. SGD), even when every position traded is USD. This bit a
  real user during development: they read "$53.21 excess liquidity" and
  "$15,523 market value" off the dashboard, both of which were actually the
  SGD-denominated figures, not USD. `parse_flex_cash_balance` already
  guards against this for CSV imports — it filters to `CurrencyPrimary ==
  "USD"` rows before summing — but there is no equivalent guard for a
  number a human transcribes by hand into `--cash` or a manual entry.
  Always ask "which currency is this figure actually in" before trusting a
  dashboard number, and see core/money.py for why NAV/cash are `Money`
  (currency-tagged), not bare floats, specifically at this boundary.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from dataclasses import dataclass, field
from typing import IO, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import PortfolioConfig
from core.models import Position, PositionImport
from core.money import Money, usd

# Reconciliation tolerances: Flex Query numbers are broker-rounded, so exact
# equality is too strict. Quantities should match exactly for equities
# (no partial-share drip in this account type); cost basis is allowed a small
# absolute-or-relative slop before it's flagged as a real mismatch.
QTY_TOLERANCE = 1e-6
COST_ABS_TOLERANCE = 0.01
COST_REL_TOLERANCE = 0.001

# Candidate column names (case-insensitive) in an IBKR Flex Query "Open
# Positions" export, in preference order. Flex Query field selection is
# user-configurable, so exact headers vary — this list is a best-effort
# mapping; if a real export doesn't parse, add its header spelling here.
_TICKER_COLUMNS = ["Symbol", "Ticker"]
_QTY_COLUMNS = ["Position", "Quantity", "Qty"]
_COST_PRICE_COLUMNS = ["CostBasisPrice", "AvgCost", "AverageCost", "OpenPrice"]
_COST_MONEY_COLUMNS = ["CostBasisMoney", "CostBasis"]
_ASSET_CLASS_COLUMNS = ["AssetClass"]
_EQUITY_ASSET_CLASSES = {"STK"}
_CASH_ASSET_CLASSES = {"CASH"}
_CURRENCY_COLUMNS = ["CurrencyPrimary", "Currency"]


class ReconciliationError(ValueError):
    """Raised when a Flex Query CSV can't be parsed into positions."""


class PortfolioError(ValueError):
    """Raised for invalid manual entry / mark-filled operations."""


@dataclass
class ImportedPosition:
    ticker: str
    qty: float
    avg_cost: float


@dataclass
class ReconciliationItem:
    ticker: str
    action: Literal["matched", "updated", "added", "removed"]
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "action": self.action, "detail": self.detail}


@dataclass
class ReconciliationResult:
    imported_at: dt.datetime
    filename: str
    rows: int
    items: list[ReconciliationItem]

    def as_json(self) -> str:
        return json.dumps([item.to_dict() for item in self.items])

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.action] = counts.get(item.action, 0) + 1
        return counts


@dataclass
class DriftStatus:
    stale: bool
    last_import_at: dt.datetime | None
    days_since_import: float | None
    threshold_days: int


def _normalize_headers(fieldnames: list[str]) -> dict[str, str]:
    """Map lowercased header -> original header, for case-insensitive lookup."""
    return {name.strip().lower(): name for name in fieldnames}


def _find_column(header_map: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        original = header_map.get(candidate.lower())
        if original is not None:
            return original
    return None


def parse_flex_csv(source: str | IO[str]) -> list[ImportedPosition]:
    """Parse an IBKR Flex Query "Open Positions" CSV into normalized rows.

    `source` is either CSV text or a file-like object opened in text mode.
    Rows with zero quantity are skipped. If an AssetClass column is present,
    only equities (STK — this covers both stocks and ETFs in IBKR's
    classification) are kept; options/futures are out of scope until §9's
    `options.enabled` flips on.
    """
    text = source.read() if hasattr(source, "read") else source
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ReconciliationError("CSV has no header row")

    header_map = _normalize_headers(reader.fieldnames)
    ticker_col = _find_column(header_map, _TICKER_COLUMNS)
    qty_col = _find_column(header_map, _QTY_COLUMNS)
    if ticker_col is None or qty_col is None:
        raise ReconciliationError(
            f"could not find ticker/quantity columns in header: {reader.fieldnames}"
        )
    cost_price_col = _find_column(header_map, _COST_PRICE_COLUMNS)
    cost_money_col = _find_column(header_map, _COST_MONEY_COLUMNS)
    asset_class_col = _find_column(header_map, _ASSET_CLASS_COLUMNS)

    if cost_price_col is None and cost_money_col is None:
        raise ReconciliationError(
            f"could not find a cost basis column in header: {reader.fieldnames}"
        )

    out: list[ImportedPosition] = []
    for row in reader:
        if asset_class_col is not None:
            asset_class = (row.get(asset_class_col) or "").strip().upper()
            if asset_class and asset_class not in _EQUITY_ASSET_CLASSES:
                continue

        ticker = (row.get(ticker_col) or "").strip().upper()
        if not ticker:
            continue

        try:
            qty = float(row[qty_col])
        except (TypeError, ValueError) as exc:
            raise ReconciliationError(f"bad quantity for {ticker!r}: {row.get(qty_col)!r}") from exc
        if qty == 0:
            continue

        avg_cost = None
        if cost_price_col is not None and (row.get(cost_price_col) or "").strip():
            avg_cost = float(row[cost_price_col])
        elif cost_money_col is not None and (row.get(cost_money_col) or "").strip():
            avg_cost = float(row[cost_money_col]) / qty
        if avg_cost is None:
            raise ReconciliationError(f"no usable cost basis for {ticker!r}")

        out.append(ImportedPosition(ticker=ticker, qty=qty, avg_cost=avg_cost))

    return out


def parse_flex_cash_balance(source: str | IO[str]) -> Money | None:
    """Sums CASH-classified rows' Position value from an IBKR Flex Query
    export — added for core/nav.py's NAV calculation, on top of §2's
    original CSV parsing which only cared about equities.

    USD-only: a CurrencyPrimary column, if present, filters to USD rows
    only — this is what protects an import from the base-currency trap
    (module docstring) that bit a manually-entered figure. A multi-currency
    account needs this extended — a documented gap, not a silent one.
    Returns None (not $0) when the balance can't be determined at all — the
    caller must not confuse "no cash data in this export" with "zero cash"."""
    text = source.read() if hasattr(source, "read") else source
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return None

    header_map = _normalize_headers(reader.fieldnames)
    asset_class_col = _find_column(header_map, _ASSET_CLASS_COLUMNS)
    qty_col = _find_column(header_map, _QTY_COLUMNS)
    if asset_class_col is None or qty_col is None:
        return None
    currency_col = _find_column(header_map, _CURRENCY_COLUMNS)

    total = 0.0
    found = False
    for row in reader:
        asset_class = (row.get(asset_class_col) or "").strip().upper()
        if asset_class not in _CASH_ASSET_CLASSES:
            continue
        if currency_col is not None:
            currency = (row.get(currency_col) or "").strip().upper()
            if currency and currency != "USD":
                continue
        try:
            total += float(row[qty_col])
            found = True
        except (TypeError, ValueError):
            continue

    return usd(total) if found else None


def _costs_match(a: float, b: float) -> bool:
    return abs(a - b) <= max(COST_ABS_TOLERANCE, COST_REL_TOLERANCE * max(abs(a), abs(b)))


class PortfolioService:
    def __init__(self, session: Session, config: PortfolioConfig | None = None):
        self.session = session
        self.config = config or PortfolioConfig()

    # ---------------------------------------------------------------- reads

    def get_position(self, ticker: str) -> Position | None:
        stmt = select(Position).where(Position.ticker == ticker.upper())
        return self.session.execute(stmt).scalar_one_or_none()

    def list_positions(self) -> list[Position]:
        stmt = select(Position).order_by(Position.ticker)
        return list(self.session.execute(stmt).scalars())

    def last_import(self) -> PositionImport | None:
        stmt = select(PositionImport).order_by(PositionImport.imported_at.desc()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------- manual

    def add_manual_position(
        self,
        ticker: str,
        qty: float,
        avg_cost: float,
        opened_at: dt.datetime | None = None,
        conviction_at_entry: float | None = None,
    ) -> Position:
        ticker = ticker.upper()
        if self.get_position(ticker) is not None:
            raise PortfolioError(f"{ticker} already has an open position — use edit_manual_position")
        self._validate_qty(qty)
        if qty <= 0:
            raise PortfolioError("qty must be positive")
        if avg_cost <= 0:
            raise PortfolioError("avg_cost must be positive")

        now = opened_at or _utcnow()
        position = Position(
            ticker=ticker,
            qty=qty,
            avg_cost=avg_cost,
            opened_at=now,
            source="manual",
            last_verified_at=now,
            conviction_at_entry=conviction_at_entry,
            peak_price_since_activation=None,
        )
        self.session.add(position)
        self.session.flush()
        return position

    def edit_manual_position(self, position_id: int, **fields) -> Position:
        position = self.session.get(Position, position_id)
        if position is None:
            raise PortfolioError(f"no position with id {position_id}")
        allowed = {"qty", "avg_cost", "opened_at", "conviction_at_entry", "peak_price_since_activation"}
        unknown = set(fields) - allowed
        if unknown:
            raise PortfolioError(f"cannot edit fields: {sorted(unknown)}")
        if "qty" in fields:
            self._validate_qty(fields["qty"])
            if fields["qty"] <= 0:
                raise PortfolioError("qty must be positive — use remove_position to close it out")
        for key, value in fields.items():
            setattr(position, key, value)
        self.session.flush()
        return position

    def remove_position(self, position_id: int) -> None:
        position = self.session.get(Position, position_id)
        if position is None:
            raise PortfolioError(f"no position with id {position_id}")
        self.session.delete(position)
        self.session.flush()

    # --------------------------------------------------------- mark-filled

    def mark_filled(
        self,
        ticker: str,
        action: Literal["BUY", "SELL"],
        qty: float,
        fill_price: float,
        filled_at: dt.datetime | None = None,
        conviction_at_entry: float | None = None,
    ) -> Position | None:
        """Record a manually-placed order's actual fill. Returns the resulting
        Position, or None if a SELL closed it out entirely."""
        ticker = ticker.upper()
        if qty <= 0:
            raise PortfolioError("qty must be positive")
        if fill_price <= 0:
            raise PortfolioError("fill_price must be positive")
        self._validate_qty(qty)

        now = filled_at or _utcnow()
        position = self.get_position(ticker)

        if action == "BUY":
            if position is None:
                position = Position(
                    ticker=ticker,
                    qty=qty,
                    avg_cost=fill_price,
                    opened_at=now,
                    source="fill",
                    last_verified_at=now,
                    conviction_at_entry=conviction_at_entry,
                    peak_price_since_activation=None,
                )
                self.session.add(position)
            else:
                new_qty = position.qty + qty
                position.avg_cost = (position.qty * position.avg_cost + qty * fill_price) / new_qty
                position.qty = new_qty
                position.last_verified_at = now
            self.session.flush()
            return position

        if action == "SELL":
            if position is None:
                raise PortfolioError(f"no open position for {ticker} to sell")
            if qty - position.qty > QTY_TOLERANCE:
                raise PortfolioError(
                    f"selling {qty} of {ticker} but only {position.qty} held — book is out of sync"
                )
            remaining = position.qty - qty
            if remaining <= QTY_TOLERANCE:
                self.session.delete(position)
                self.session.flush()
                return None
            position.qty = remaining
            position.last_verified_at = now
            self.session.flush()
            return position

        raise PortfolioError(f"unknown action {action!r}")

    def _validate_qty(self, qty: float) -> None:
        if not self.config.allow_fractional and abs(qty - round(qty)) > QTY_TOLERANCE:
            raise PortfolioError(f"fractional qty {qty} not allowed (portfolio.allow_fractional is false)")

    # ----------------------------------------------------------- CSV import

    def import_flex_csv(self, source: str | IO[str], filename: str) -> ReconciliationResult:
        text = source.read() if hasattr(source, "read") else source
        rows = parse_flex_csv(text)
        cash = parse_flex_cash_balance(text)  # already USD-filtered — see module docstring's currency trap note
        result = self.reconcile(rows, filename=filename)
        record = PositionImport(
            imported_at=result.imported_at,
            filename=filename,
            rows=result.rows,
            reconciliation_json=result.as_json(),
            cash_usd=cash.amount if cash is not None else None,
        )
        self.session.add(record)
        self.session.flush()
        return result

    def latest_cash_balance(self) -> Money | None:
        """None if there's never been an import, or the import's CSV had no
        parseable cash row — distinct from an actual zero balance."""
        last = self.last_import()
        if last is None or last.cash_usd is None:
            return None
        return usd(last.cash_usd)

    def reconcile(
        self,
        imported: list[ImportedPosition],
        filename: str = "manual-reconcile",
        imported_at: dt.datetime | None = None,
    ) -> ReconciliationResult:
        """Compare imported broker positions against Zopro's book and update
        the book to match. Does not write a `position_imports` row itself —
        `import_flex_csv` does that; call this directly only for a dry-run
        style reconciliation against an already-parsed row list."""
        now = imported_at or _utcnow()
        imported_by_ticker = {row.ticker: row for row in imported}
        current = {p.ticker: p for p in self.list_positions()}

        items: list[ReconciliationItem] = []

        for ticker, imp in imported_by_ticker.items():
            existing = current.get(ticker)
            if existing is None:
                position = Position(
                    ticker=ticker,
                    qty=imp.qty,
                    avg_cost=imp.avg_cost,
                    opened_at=now,
                    source="import",
                    last_verified_at=now,
                    conviction_at_entry=None,
                    peak_price_since_activation=None,
                )
                self.session.add(position)
                items.append(
                    ReconciliationItem(
                        ticker=ticker,
                        action="added",
                        detail={"qty": imp.qty, "avg_cost": imp.avg_cost, "note": "opened_at approximated at import time"},
                    )
                )
                continue

            qty_matches = abs(existing.qty - imp.qty) <= QTY_TOLERANCE
            cost_matches = _costs_match(existing.avg_cost, imp.avg_cost)
            if qty_matches and cost_matches:
                existing.last_verified_at = now
                items.append(ReconciliationItem(ticker=ticker, action="matched"))
                continue

            detail = {}
            if not qty_matches:
                detail["qty"] = {"was": existing.qty, "now": imp.qty}
            if not cost_matches:
                detail["avg_cost"] = {"was": existing.avg_cost, "now": imp.avg_cost}
            existing.qty = imp.qty
            existing.avg_cost = imp.avg_cost
            existing.last_verified_at = now
            items.append(ReconciliationItem(ticker=ticker, action="updated", detail=detail))

        for ticker, existing in current.items():
            if ticker in imported_by_ticker:
                continue
            items.append(
                ReconciliationItem(
                    ticker=ticker,
                    action="removed",
                    detail={"was_qty": existing.qty, "was_avg_cost": existing.avg_cost},
                )
            )
            self.session.delete(existing)

        self.session.flush()
        return ReconciliationResult(imported_at=now, filename=filename, rows=len(imported), items=items)

    # ------------------------------------------------------------- drift

    def check_drift(self, as_of: dt.datetime | None = None) -> DriftStatus:
        """§2 drift warning: stale if the last CSV import is more than
        `import_reminder_days` old. A never-imported book with open positions
        counts as stale — those positions have no broker confirmation at
        all. An empty book (nothing held) is never stale."""
        now = as_of or _utcnow()
        threshold = self.config.import_reminder_days
        last = self.last_import()

        if last is None:
            has_positions = len(self.list_positions()) > 0
            return DriftStatus(
                stale=has_positions,
                last_import_at=None,
                days_since_import=None,
                threshold_days=threshold,
            )

        days_since = (now - last.imported_at).total_seconds() / 86400
        return DriftStatus(
            stale=days_since > threshold,
            last_import_at=last.imported_at,
            days_since_import=days_since,
            threshold_days=threshold,
        )


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
