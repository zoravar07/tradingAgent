"""NAV and drawdown tracking — not in §6's original schema. Added on top of
the spec at the user's request: NAV is the sum of held positions' market
value plus cash (the user said "sum of market values" for the positions
half; cash is added separately because that's what NAV means and the risk
gates need a true total, not just the equities sleeve — flagged here since
it's a reading, not a literal instruction). Drawdown and daily-loss history
build up run over run and start at zero on the first run, per the user's
explicit instruction — there's no bootstrap NAV to compare against yet.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import NavSnapshot


def compute_nav(position_values_usd: Sequence[float], cash_usd: float) -> float:
    return sum(position_values_usd) + cash_usd


@dataclass
class NavStatus:
    nav_usd: float
    peak_nav_usd: float
    drawdown_pct: float
    daily_loss_pct: float


def _latest_snapshot(session: Session) -> NavSnapshot | None:
    stmt = select(NavSnapshot).order_by(NavSnapshot.recorded_at.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def record_nav(session: Session, run_id: int, nav_usd: float, as_of: dt.datetime) -> NavStatus:
    """Compares against the single most recent snapshot (if any), records a
    new one, and returns the derived status. "Start it at zero on first
    run": with no prior snapshot, this run's NAV becomes the peak (drawdown
    0%) and there's nothing to compare a daily loss against (0%)."""
    last = _latest_snapshot(session)

    if last is None:
        peak_nav_usd = nav_usd
        drawdown_pct = 0.0
        daily_loss_pct = 0.0
    else:
        peak_nav_usd = max(nav_usd, last.peak_nav_usd)
        drawdown_pct = max(0.0, (peak_nav_usd - nav_usd) / peak_nav_usd * 100) if peak_nav_usd > 0 else 0.0
        daily_loss_pct = max(0.0, (last.nav_usd - nav_usd) / last.nav_usd * 100) if last.nav_usd > 0 else 0.0

    session.add(
        NavSnapshot(
            run_id=run_id, nav_usd=nav_usd, peak_nav_usd=peak_nav_usd,
            drawdown_pct=drawdown_pct, daily_loss_pct=daily_loss_pct, recorded_at=as_of,
        )
    )
    session.flush()

    return NavStatus(nav_usd=nav_usd, peak_nav_usd=peak_nav_usd, drawdown_pct=drawdown_pct, daily_loss_pct=daily_loss_pct)
