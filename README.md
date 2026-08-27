# Z Money

A single-user, multi-agent investment research system for a real IBKR
portfolio. Z Money never touches your broker — it reads market data, reads
your imported positions, and produces a nightly briefing (proposed trades,
a watchlist, portfolio health) for you to act on by hand.

See `../SPEC.md` for the full build specification (§ references throughout
the codebase point back to it).

## Layout

```
core/           domain logic: portfolio, scoring, risk rules, briefing assembly, DB models
agents/         screener (Stage 1/2) and research/order-builder LLM agents
sources/        FMP, yfinance, and price/technical-indicator adapters
api/            FastAPI app serving the UI (api/server.py + routes/)
ui/             Vite + React + TypeScript frontend
scripts/        run_live_briefing.py — one-off live pipeline runs
config.yaml     universe, screening, risk, and budget configuration
tests/          pytest suite (backend); no frontend tests yet
```

## Running it

Backend API:

```bash
.venv/bin/uvicorn api.server:app --reload --port 8000
```

Frontend:

```bash
cd ui && npm run dev
```

A live pipeline run against real market data and the LLM (costs real
money — see `config.yaml`'s `budget` section):

```bash
.venv/bin/python scripts/run_live_briefing.py
```

Requires `ANTHROPIC_API_KEY` and `FMP_API_KEY` in `zopro/.env` (yfinance
needs no key).

## Tests

```bash
.venv/bin/python -m pytest -q
```
