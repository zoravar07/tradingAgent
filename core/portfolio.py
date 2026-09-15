"""Portfolio module — §10 build-order step 2.

Owns Z Money's own `positions` table (the source of truth, per §2) and the three
ways positions get into it:

  1. `record_broker_sync` — IBKR Flex Web Service Open Positions + Cash Report (sources/ibkr_flex.py), reconciled
                            against the current book.
  2. `mark_filled`       — you placed an order manually in IBKR; tell Z Money
                            what actually filled and it updates its book.
  3. `add_manual_position` / `edit_manual_position` / `remove_position`
                            — hand entry, mainly for the initial load.

Design notes that aren't obvious from the spec text alone:

* Reconciliation trusts the CSV as ground truth for *what's actually held*.
  An IBKR "Open Positions" Flex Query lists every open position in the
  account, so a ticker present in Z Money's book but absent from the CSV really
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
  SGD-denominated figures, not USD. The Flex Web Service sync (sources/ibkr_flex.py) guards against this by
  reading only the Cash Report's USD row and only USD-denominated equity
  lines, and the manual `--cash` override that once bypassed that guard is
  gone.
  Always ask "which currency is this figure actually in" before trusting a
  dashboard number, and see core/money.py for why NAV/cash are `Money`
  (currency-tagged), not bare floats, specifically at this boundary.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import PortfolioConfig, SleevesConfig
from core.models import Position, PositionImport
from core.money import Money, usd
from core.sleeves import resolve_sleeve

# Reconciliation tolerances: Flex Query numbers are broker-rounded, so exact
# equality is too strict. Quantities should match exactly for equities
# (no partial-share drip in this account type); cost basis is allowed a small
# absolute-or-relative slop before it's flagged as a real mismatch.
QTY_TOLERANCE = 1e-6
COST_ABS_TOLERANCE = 0.01
COST_REL_TOLERANCE = 0.001

class ReconciliationError(ValueError):
    """Raised when broker rows can't be reconciled into positions."""


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


def _costs_match(a: float, b: float) -> bool:
    return abs(a - b) <= max(COST_ABS_TOLERANCE, COST_REL_TOLERANCE * max(abs(a), abs(b)))


class PortfolioService:
    def __init__(self, session: Session, config: PortfolioConfig | None = None, sleeves: SleevesConfig | None = None):
        self.session = session
        self.config = config or PortfolioConfig()
        self.sleeves = sleeves or SleevesConfig()

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
            sleeve=resolve_sleeve(ticker, self.sleeves),
        )
        self.session.add(position)
        self.session.flush()
        return position

    def reclassify_sleeve(self, position_id: int, new_sleeve: str) -> Position:
        """The only writer of Position.sleeve besides initial assignment.
        Unused by anything in this codebase yet — reserved for Part 4's
        SPECULATIVE-crosses-15%-NAV-weight reclassification rule. Deliberately
        separate from edit_manual_position: reclassification is a distinct,
        rare, rule-triggered event, not a general field edit."""
        position = self.session.get(Position, position_id)
        if position is None:
            raise PortfolioError(f"no position with id {position_id}")
        position.sleeve = new_sleeve
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
                    sleeve=resolve_sleeve(ticker, self.sleeves),
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

    # ---------------------------------------------------------- broker sync

    def record_broker_sync(
        self,
        rows: list[ImportedPosition],
        cash_usd: Money,
        source: str,
        imported_at: dt.datetime | None = None,
    ) -> ReconciliationResult:
        """Reconcile the book against broker-reported USD equity rows and
        record the sync as a `position_imports` row. `cash_usd` must be the
        USD cash figure only — sources/ibkr_flex.py reads it from the Flex
        Cash Report's USD row, never the base-currency (SGD) summary."""
        if cash_usd.currency != "USD":
            raise ReconciliationError(f"cash must be USD, got {cash_usd.currency}")
        result = self.reconcile(rows, filename=source, imported_at=imported_at)
        record = PositionImport(
            imported_at=result.imported_at,
            filename=source,
            rows=result.rows,
            reconciliation_json=result.as_json(),
            cash_usd=cash_usd.amount,
        )
        self.session.add(record)
        self.session.flush()
        return result

    def latest_cash_balance(self) -> Money | None:
        """None if there's never been a broker sync — distinct from an
        actual zero balance."""
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
        """Compare imported broker positions against Z Money's book and update
        the book to match. Does not write a `position_imports` row itself —
        `record_broker_sync` does that; call this directly only for a dry-run
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
                    sleeve=resolve_sleeve(ticker, self.sleeves),
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

def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
