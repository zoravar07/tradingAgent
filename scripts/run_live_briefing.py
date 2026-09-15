"""One-off diagnostic script: a real, live end-to-end run against FMP,
yfinance, and Anthropic, using whatever positions are already in
data/z_money.db. Prints the assembled briefing as plain text and what the run
cost. Prices/historicals come from yfinance (free, uncapped); fundamentals/
earnings/analysts/13F stay on FMP — see sources/live_gateway.py.

This is NOT the app (main.py, the nightly scheduler, the API server) — it's
for looking at pipeline output before there's a UI to show it in, and for
checking the picks/reasoning are worth trusting before investing in step 10.

Usage:
    # nightly run — syncs positions and cash from IBKR first, then screens:
    .venv/bin/python scripts/run_live_briefing.py

    # just sync positions from IBKR and print the reconciliation (no FMP/LLM spend):
    .venv/bin/python scripts/run_live_briefing.py --sync-only

    # see the resolved universe and cost projection without spending anything:
    .venv/bin/python scripts/run_live_briefing.py --dry-run-universe

Positions and cash come from IBKR's Flex Web Service (sources/ibkr_flex.py)
before every run, and the run halts if that sync fails — there is no manual
CSV import and no cash override: a briefing built on a stale or hand-typed
book is worse than none. Needs IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in
.env alongside the API keys.

Requires ANTHROPIC_API_KEY, FMP_API_KEY, IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env (yfinance needs no
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
from core.orchestrator import NightlyRunInputs, holdings_due_for_refresh, resolve_universe, run_nightly  # noqa: E402
from core.portfolio import PortfolioService  # noqa: E402
from sources.fmp import FMPClient  # noqa: E402
from sources.ibkr_flex import FlexError, FlexWebServiceClient, sync_positions  # noqa: E402
from sources.index_constituents import SP500ConstituentsSource  # noqa: E402
from sources.us_listing import USEquityScreen, USListingSource, apply_liquidity_pregate  # noqa: E402
from sources.live_gateway import LiveMarketDataGateway  # noqa: E402
from sources.yfinance_source import YFinanceClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sync-only", action="store_true", help="Sync positions/cash from IBKR, print the reconciliation, and exit (no FMP/LLM spend)")
    parser.add_argument("--dry-run-universe", action="store_true", help="Print the resolved universe and exit; no API calls")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip the credit probe and the max_run_cost_usd guard")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = parse_args()

    load_dotenv(ROOT / ".env")
    config = load_config(ROOT / "config.yaml")

    engine = make_engine(ROOT / "data" / "z_money.db")
    init_db(engine)
    session = make_session_factory(engine)()
    portfolio = PortfolioService(session, config=config.portfolio, sleeves=config.sleeves)

    # Positions and cash from the broker, before anything else. A failed
    # sync halts the run: every downstream number (NAV, weights, sizing,
    # every exit trigger) is built on this book, and proceeding on
    # yesterday's book would be a wrong-looking-confident briefing.
    if args.dry_run_universe:
        print("Dry run: skipping the IBKR sync, using the book as last synced.")
        sync = None
    else:
        sync = _sync_positions(session, portfolio)
        print(f"IBKR sync: {sync.summary()}")
    if args.sync_only and sync is not None:
        for item in sync.reconciliation.items:
            print(f"  {item.action:<8} {item.ticker:<6} {item.detail if item.detail else ''}")
        return

    held_positions = portfolio.list_positions()
    if not held_positions:
        print("WARNING: the broker reports no USD equity positions; the run will screen new names only.", file=sys.stderr)
    held_tickers = [p.ticker for p in held_positions]

    fmp_cache = FileCache(ROOT / "data" / "cache")
    fmp_budget = DailyCallBudget(ROOT / "data" / "fmp_call_budget.json", daily_limit=250)
    fmp_client = FMPClient(api_key=_require_env("FMP_API_KEY"), cache=fmp_cache, budget=fmp_budget, session=requests.Session())

    # S&P 500 membership from Wikipedia (free, no key, cached 30 days) — FMP's
    # constituents endpoint is 402-gated on this plan, and the old fallback
    # of "warn and continue with an empty pool" is exactly how runs 1-5 came
    # to screen nothing but the positions already held. A missing pool is
    # now a hard stop, not a warning.
    yf_cache = FileCache(ROOT / "data" / "yf_cache")
    yf_client = YFinanceClient(cache=yf_cache)
    try:
        pool, pool_note = _build_scan_pool(config, yf_client)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"ERROR: could not build the scan pool ({exc}); refusing to run with an empty scan pool.")
    as_of = dt.datetime.utcnow()
    universe = resolve_universe(held_tickers=held_tickers, pool=pool, config=config.universe, as_of=as_of)

    new_names = [t for t in universe if t not in held_tickers]
    print(pool_note + f" Extra tickers: {config.universe.extra_tickers}.")
    print(f"Resolved universe for today: {len(universe)} names ({len(held_tickers)} held + {len(new_names)} not held).")
    due_held = holdings_due_for_refresh(session, held_tickers, run_id=10**9, refresh_days=config.research.holdings_refresh_days)
    projected = _projected_llm_cost(config, held_tickers, len(due_held))
    if args.dry_run_universe:
        print(f"First 40: {universe[:40]}")
        _print_call_projection(config, held_tickers, len(universe), len(due_held))
        _print_cost_projection(config, held_tickers, len(due_held), projected)
        return

    gateway = LiveMarketDataGateway(
        fmp_client, yf_client,
        cluster_overrides=config.universe.cluster_overrides,
        etf_tickers=config.universe.etf_tickers,
    )

    anthropic_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    llm_budget = MonthlySpendTracker(ROOT / "data" / "llm_spend.json", config.budget.monthly_api_cap_usd)
    llm = LLMClient(anthropic_client, llm_budget)
    _print_cost_projection(config, held_tickers, len(due_held), projected)
    if not args.skip_preflight:
        _preflight(anthropic_client, llm_budget, config, projected)
    news_cache = FileCache(ROOT / "data" / "news_cache")

    cash = portfolio.latest_cash_balance()
    if cash is None:  # cannot happen after a successful sync; never default to zero silently
        raise SystemExit("ERROR: no USD cash balance on record after sync; refusing to run.")
    inputs = NightlyRunInputs(as_of=as_of, universe_tickers=universe, held_tickers=held_tickers, cash=cash)

    spent_before = llm_budget.spent_this_month()
    fmp_used_before = fmp_budget.used_today()

    briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=inputs, news_cache=news_cache)
    session.commit()

    print()
    print(render_briefing_text(briefing))
    print()
    print("--- Run cost ---")
    print(f"Anthropic spend this run: ${llm_budget.spent_this_month() - spent_before:.4f}")
    print(f"Anthropic spend this month total: ${llm_budget.spent_this_month():.4f} / ${config.budget.monthly_api_cap_usd:.2f} cap")
    print(f"FMP calls used today: {fmp_budget.used_today()} / {fmp_budget.daily_limit} ({fmp_budget.used_today() - fmp_used_before} this run)")


def _sync_positions(session, portfolio):
    """Two-step Flex Web Service fetch, reconcile, commit. Any failure —
    bad or expired token, IP restriction, query missing a section, IBKR
    unreachable — is a hard stop with the IBKR message attached."""
    token = _require_env("IBKR_FLEX_TOKEN")
    query_id = _require_env("IBKR_FLEX_QUERY_ID")
    client = FlexWebServiceClient(token=token, query_id=query_id)
    try:
        statement = client.fetch_statement()
        result = sync_positions(portfolio, statement)
        session.commit()
    except FlexError as exc:
        session.rollback()
        raise SystemExit(f"POSITION SYNC FAILED: {exc}\nRefusing to run on a stale book. Fix the Flex query/token and retry.")
    except Exception as exc:  # noqa: BLE001 — network, parse, DB: all are a stop, not a warning
        session.rollback()
        raise SystemExit(f"POSITION SYNC FAILED ({type(exc).__name__}): {exc}\nRefusing to run on a stale book.")
    return result


def _build_scan_pool(config, yf_client: YFinanceClient) -> tuple[list[str], str]:
    """The scan pool per config.universe.rotating_pool_source, and a one-line
    note for the log. For US_ALL the liquidity/market-cap gates run here, on
    screener data, before any per-name fetch — and the screener rows seed
    the quote cache so Stage 1 makes no fast_info calls for these names."""
    source = config.universe.rotating_pool_source.upper()
    if source == "SP500":
        pool = SP500ConstituentsSource(cache=FileCache(ROOT / "data" / "index_cache")).get_constituents()
        return pool, f"S&P 500 pool: {len(pool)} names."
    if source == "US_ALL":
        listing = USListingSource(cache=FileCache(ROOT / "data" / "index_cache")).get_symbols()
        quotes = USEquityScreen(cache=FileCache(ROOT / "data" / "index_cache")).get_quotes()
        s1 = config.screener.stage1
        pool = apply_liquidity_pregate(
            listing, quotes, min_market_cap_usd=s1.min_market_cap_usd, min_avg_daily_volume_usd=s1.min_avg_daily_volume_usd
        )
        seeded = yf_client.prefetch_quotes({t: quotes[t] for t in pool})
        return pool, (
            f"US listing: {len(listing)} common stocks; screener rows for {len(quotes)}; "
            f"{len(pool)} pass the liquidity pre-gate (mcap >= ${s1.min_market_cap_usd/1e9:.0f}B, "
            f"ADV >= ${s1.min_avg_daily_volume_usd/1e6:.0f}M); quote cache seeded for {seeded}."
        )
    raise SystemExit(f"unknown universe.rotating_pool_source {source!r} (expected SP500 or US_ALL)")


# Measured unit costs (USD), from runs 5-7's token counts and the web
# search smoke tests — re-measure if models or prompts change.
UNIT_COST = {
    "stage2_call": 0.02,        # one batched Haiku ranking call (~40 names)
    "memo_sonnet": 0.032,       # Sonnet 4.6 memo, run 6 average
    "digest_haiku_1search": 0.022,  # Haiku + 1 basic search incl. result tokens
    "digest_sonnet_1search": 0.05,
}


def _projected_llm_cost(config, held_tickers: list[str], due_held: int) -> float:
    s1, s2, research = config.screener.stage1, config.screener.stage2, config.research
    stage2_calls = -(-s1.max_survivors // s2.batch_size)
    memos = min(s2.max_survivors, research.max_candidates_per_run) + due_held
    digest_unit = UNIT_COST["digest_haiku_1search" if "haiku" in research.digest_model else "digest_sonnet_1search"]
    digest_unit *= max(1, research.web_search_max_uses) / 1.0 if research.web_search_max_uses > 1 else 1.0
    digests = memos if research.web_search_enabled else 0
    return stage2_calls * UNIT_COST["stage2_call"] + memos * UNIT_COST["memo_sonnet"] + digests * digest_unit


def _print_cost_projection(config, held_tickers: list[str], due_held: int, projected: float) -> None:
    research = config.research
    new_names = min(config.screener.stage2.max_survivors, research.max_candidates_per_run)
    print(
        f"Projected LLM cost this run: ${projected:.2f} "
        f"(Stage 2 batched ranking + {new_names} new memos + {due_held} holdings refresh of {len(held_tickers)}"
        f"{', digests cached up to ' + str(research.news_cache_hours) + 'h' if research.web_search_enabled else ', digests off'})"
        f" — guard max_run_cost_usd=${config.budget.max_run_cost_usd:.2f}"
    )


# Exit codes: 0 ran, 1 failed (sync, data, crash), 2 skipped on purpose by
# the pre-flight guard (over budget, out of credit) — scripts/nightly.sh
# treats 2 as a clean, logged no-op so launchd doesn't record a failure.
EXIT_SKIPPED = 2


def _skip(reason: str) -> None:
    print(f"SKIPPED: {reason}")
    raise SystemExit(EXIT_SKIPPED)


def _preflight(anthropic_client, llm_budget, config, projected: float) -> None:
    """Refuse to start a run that can't finish: a ~$0.0005 probe catches an
    exhausted Anthropic balance up front (there is no balance API, so this
    can't see a balance that will run out mid-run), and the projected cost
    is checked against both the per-run guard and what's left of the
    monthly cap."""
    remaining = llm_budget.remaining_this_month()
    if projected > config.budget.max_run_cost_usd:
        _skip(
            f"pre-flight: projected ${projected:.2f} exceeds budget.max_run_cost_usd ${config.budget.max_run_cost_usd:.2f}. "
            "Lower max_candidates_per_run / web_search_max_uses, or raise the guard. (--skip-preflight to override)"
        )
    if projected > remaining:
        _skip(f"pre-flight: projected ${projected:.2f} exceeds the ${remaining:.2f} left of the monthly cap.")
    try:
        anthropic_client.messages.create(
            model=config.screener.stage2.model, max_tokens=1, messages=[{"role": "user", "content": "ok"}]
        )
    except Exception as exc:  # noqa: BLE001
        _skip(f"pre-flight: Anthropic API probe failed — {str(exc)[:200]}")
    print("Pre-flight: API probe OK; projected cost within guard.")


def _print_call_projection(config, held_tickers: list[str], universe_size: int, due_held: int | None = None) -> None:
    """Worst-case per-run external call counts, from config caps — printed
    before anything is spent so the FMP 250/day budget can be sanity-checked
    against the universe size (§10 step 3's original concern)."""
    from sources.yfinance_source import BATCH_CHUNK

    etfs = {t.upper() for t in config.universe.etf_tickers}
    held = [t.upper() for t in held_tickers]
    s1, s2, research = config.screener.stage1, config.screener.stage2, config.research
    if due_held is None:
        due_held = len(held)

    # Stage 1 is yfinance-only; FMP is touched only for names that reach Research.
    fmp_per_name = 6  # profile, earnings-surprises, analyst-estimates, price-target-summary, 13F, insider (ETF: profile only)
    new_names = min(s2.max_survivors, research.max_candidates_per_run)
    researched = due_held + new_names
    fmp_worst = researched * fmp_per_name
    history_batches = -(-(universe_size + 1) // BATCH_CHUNK)  # + SPY, batched via yf.download
    pregated = config.universe.rotating_pool_source.upper() == "US_ALL"
    quote_calls = len(held) if pregated else universe_size  # screener seeds quotes for pre-gated names
    yf_cold = quote_calls + (universe_size - len(etfs & set(held))) * 2 + history_batches  # + income & cashflow per name
    yf_warm = quote_calls + history_batches  # fundamentals cached 30 days
    stage2_calls = -(-s1.max_survivors // s2.batch_size)

    print()
    print("--- Projected external calls per run (worst case, from config caps) ---")
    print(
        f"Stage 1 (quant, {universe_size} names): FMP 0 | yfinance ~{yf_cold} cold-cache, ~{yf_warm} steady-state "
        f"(history in {history_batches} batched downloads of <= {BATCH_CHUNK})"
    )
    print(f"Stage 2 (Haiku ranking over cached numbers): {stage2_calls} batched call(s) for up to {s1.max_survivors} non-held names, no web search")
    print(
        f"Research: {researched} names ({due_held} holdings due of {len(held)} + {new_names} new) -> FMP up to {fmp_worst} calls cold-cache (cap 250); "
        f"LLM {researched} memos + up to {researched} digests ({research.digest_model}, {research.web_search_max_uses} search each, cached {research.news_cache_hours}h)"
        f"{'' if research.web_search_enabled else ' [digests DISABLED]'}"
    )


def _require_env(name: str) -> str:
    import os

    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set in .env")
    return value


if __name__ == "__main__":
    main()
