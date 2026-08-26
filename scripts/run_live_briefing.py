"""One-off diagnostic script: a real, live end-to-end run against FMP,
yfinance, and Anthropic, using whatever positions are already in
data/zopro.db. Prints the assembled briefing as plain text and what the run
cost. Prices/historicals come from yfinance (free, uncapped); fundamentals/
earnings/analysts/13F stay on FMP — see sources/live_gateway.py.

This is NOT the app (main.py, the nightly scheduler, the API server) — it's
for looking at pipeline output before there's a UI to show it in, and for
checking the picks/reasoning are worth trusting before investing in step 10.

Usage:
    # positions already imported:
    .venv/bin/python scripts/run_live_briefing.py

    # import a Flex Query CSV first, then run:
    .venv/bin/python scripts/run_live_briefing.py --import-csv path/to/positions.csv

    # add positions by hand first, then run (repeatable):
    .venv/bin/python scripts/run_live_briefing.py --manual AMD,10,142.30 --manual NBIS,8,218.00

    # override cash directly (e.g. no Flex CSV imported this session yet) —
    # BE SURE this is your USD cash balance, not your account's base currency
    # if it differs (see core/money.py's docstring for why that matters):
    .venv/bin/python scripts/run_live_briefing.py --cash 41.91

    # see the resolved universe without spending anything:
    .venv/bin/python scripts/run_live_briefing.py --dry-run-universe

Requires ANTHROPIC_API_KEY and FMP_API_KEY in zopro/.env (yfinance needs no
key). Every LLM call costs real money (billed against config.yaml's
budget.monthly_api_cap_usd); FMP calls cost nothing on the free tier but
count against the 250/day cap; yfinance has no cap this codebase tracks.

Note: config.risk.max_unpriced_held_positions defaults to 0 — if yfinance
can't price even one held position, the run blocks before spending on
Stage 1/2/Research and prints why, rather than publish on a broken NAV.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.briefing import render_briefing_text  # noqa: E402
from core.cache import DailyCallBudget, FileCache  # noqa: E402
from core.config import load_config  # noqa: E402
from core.db import init_db, make_engine, make_session_factory  # noqa: E402
from core.llm import LLMClient, MonthlySpendTracker  # noqa: E402
from core.money import usd  # noqa: E402
from core.orchestrator import NightlyRunInputs, resolve_universe, run_nightly  # noqa: E402
from core.portfolio import PortfolioService  # noqa: E402
from sources.fmp import FMPClient  # noqa: E402
from sources.live_gateway import LiveMarketDataGateway  # noqa: E402
from sources.yfinance_source import YFinanceClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--import-csv", type=str, default=None, help="Flex Query CSV path to import before running")
    parser.add_argument("--manual", action="append", default=[], help="TICKER,QTY,AVG_COST — repeatable")
    parser.add_argument(
        "--cash", type=float, default=None,
        help="USD cash balance override — use this if no Flex CSV has been imported. "
        "Must be USD, not the account's base currency if different (see core/money.py).",
    )
    parser.add_argument("--dry-run-universe", action="store_true", help="Print the resolved universe and exit; no API calls")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = parse_args()

    load_dotenv(ROOT / ".env")
    config = load_config(ROOT / "config.yaml")

    engine = make_engine(ROOT / "data" / "zopro.db")
    init_db(engine)
    session = make_session_factory(engine)()
    portfolio = PortfolioService(session, config=config.portfolio)

    if args.import_csv:
        csv_path = Path(args.import_csv)
        result = portfolio.import_flex_csv(csv_path.read_text(), filename=csv_path.name)
        session.commit()
        print(f"Imported {csv_path.name}: {result.summary()}")

    for spec in args.manual:
        ticker, qty, avg_cost = spec.split(",")
        portfolio.add_manual_position(ticker.strip().upper(), float(qty), float(avg_cost))
        session.commit()
        print(f"Added manual position: {ticker} {qty} @ {avg_cost}")

    held_positions = portfolio.list_positions()
    if not held_positions:
        print(
            "WARNING: no positions in the book. Import a Flex CSV with --import-csv, "
            "or add positions with --manual, before running for real.",
            file=sys.stderr,
        )
    held_tickers = [p.ticker for p in held_positions]

    fmp_cache = FileCache(ROOT / "data" / "cache")
    fmp_budget = DailyCallBudget(ROOT / "data" / "fmp_call_budget.json", daily_limit=250)
    fmp_client = FMPClient(api_key=_require_env("FMP_API_KEY"), cache=fmp_cache, budget=fmp_budget, session=requests.Session())

    try:
        pool = fmp_client.get_sp500_constituents()  # one call
    except Exception as exc:  # noqa: BLE001 — plan-tier gating is common here (402/403)
        print(f"WARNING: could not fetch S&P 500 constituents ({exc}); rotating pool is empty for this run.", file=sys.stderr)
        pool = []
    as_of = dt.datetime.utcnow()
    universe = resolve_universe(held_tickers=held_tickers, pool=pool, config=config.universe, as_of=as_of)

    print(f"S&P 500 pool: {len(pool)} names. Resolved universe for today: {len(universe)} names -> {universe}")
    if args.dry_run_universe:
        return

    yf_cache = FileCache(ROOT / "data" / "yf_cache")
    yf_client = YFinanceClient(cache=yf_cache)
    gateway = LiveMarketDataGateway(
        fmp_client, yf_client,
        cluster_overrides=config.universe.cluster_overrides,
        etf_tickers=config.universe.etf_tickers,
    )

    anthropic_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    llm_budget = MonthlySpendTracker(ROOT / "data" / "llm_spend.json", config.budget.monthly_api_cap_usd)
    llm = LLMClient(anthropic_client, llm_budget)

    if args.cash is not None:
        cash = usd(args.cash)
        print(f"Using --cash override: {cash} (not read from any import)")
    else:
        cash = portfolio.latest_cash_balance() or usd(0.0)
    inputs = NightlyRunInputs(as_of=as_of, universe_tickers=universe, held_tickers=held_tickers, cash=cash)

    spent_before = llm_budget.spent_this_month()
    fmp_used_before = fmp_budget.used_today()

    briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=inputs)
    session.commit()

    print()
    print(render_briefing_text(briefing))
    print()
    print("--- Run cost ---")
    print(f"Anthropic spend this run: ${llm_budget.spent_this_month() - spent_before:.4f}")
    print(f"Anthropic spend this month total: ${llm_budget.spent_this_month():.4f} / ${config.budget.monthly_api_cap_usd:.2f} cap")
    print(f"FMP calls used today: {fmp_budget.used_today()} / {fmp_budget.daily_limit} ({fmp_budget.used_today() - fmp_used_before} this run)")


def _require_env(name: str) -> str:
    import os

    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set in zopro/.env")
    return value


if __name__ == "__main__":
    main()
