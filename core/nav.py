"""NAV and drawdown tracking — not in §6's original schema. Added on top of
the spec at the user's request: NAV is the sum of held positions' market
value plus cash (the user said "sum of market values" for the positions
half; cash is added separately because that's what NAV means and the risk
gates need a true total, not just the equities sleeve — flagged here since
it's a reading, not a literal instruction). Drawdown and daily-loss history
build up run over run and start at zero on the first run, per the user's
explicit instruction — there's no bootstrap NAV to compare against yet.

Every dollar amount here is `Money` (core/money.py), not a bare float — a
real bug during the first live run: the user read NAV and cash off IBKR's
account dashboard, which showed SGD (their account's base currency) instead
of USD (their trading currency), and a bare float gave no way to catch it.
`compute_nav` refuses non-Money inputs; a caller cannot pass a suspicious
bare number in unnoticed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import NavSnapshot
from core.money import Money, usd


def compute_nav(position_values: Sequence[Money], cash: Money) -> Money:
    total = cash
    for value in position_values:
        total = total + value  # Money.__add__ raises on a currency mismatch
    return total


@dataclass
class NavStatus:
    nav: Money
    peak_nav: Money
    drawdown_pct: float
    daily_loss_pct: float


def _latest_snapshot(session: Session) -> NavSnapshot | None:
    stmt = select(NavSnapshot).order_by(NavSnapshot.recorded_at.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def record_nav(session: Session, run_id: int, nav: Money, as_of: dt.datetime) -> NavStatus:
    """Compares against the single most recent snapshot (if any), records a
    new one, and returns the derived status. "Start it at zero on first
    run": with no prior snapshot, this run's NAV becomes the peak (drawdown
    0%) and there's nothing to compare a daily loss against (0%)."""
    last = _latest_snapshot(session)

    if last is None:
        peak_nav = nav
        drawdown_pct = 0.0
        daily_loss_pct = 0.0
    else:
        last_nav = usd(last.nav_usd)
        last_peak = usd(last.peak_nav_usd)
        peak_nav = nav if nav > last_peak else last_peak
        drawdown_pct = max(0.0, (peak_nav - nav) / peak_nav * 100) if peak_nav.amount > 0 else 0.0
        daily_loss_pct = max(0.0, (last_nav - nav) / last_nav * 100) if last_nav.amount > 0 else 0.0

    session.add(
        NavSnapshot(
            run_id=run_id, nav_usd=nav.amount, peak_nav_usd=peak_nav.amount,
            drawdown_pct=drawdown_pct, daily_loss_pct=daily_loss_pct, recorded_at=as_of,
        )
    )
    session.flush()

    return NavStatus(nav=nav, peak_nav=peak_nav, drawdown_pct=drawdown_pct, daily_loss_pct=daily_loss_pct)
