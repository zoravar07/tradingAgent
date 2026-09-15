"""FastAPI app — §4's `api/server.py + routes/`, §10 step 10. Serves the UI
(ui/) its data. Single-user local app: no auth, CORS scoped to localhost dev
origins (Vite's default port and a couple of common alternates) — this is
not designed to be exposed beyond the machine it runs on.

Run with: .venv/bin/uvicorn api.server:app --reload --port 8000
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.briefing import router as briefing_router
from api.routes.config import router as config_router
from api.routes.dashboard import router as dashboard_router
from api.routes.journal import router as journal_router
from api.routes.screens import router as screens_router
from core.config import load_config
from core.db import init_db, make_engine, make_session_factory
from core.portfolio import PortfolioService
from core.sleeves import find_sleeve_drift

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "z_money.db"
CONFIG_PATH = ROOT / "config.yaml"


def _log_sleeve_drift(engine, config_path: Path) -> None:
    """Startup reconciliation check (user-requested): sleeve is assigned
    once at position-open time and never auto-corrected, so editing
    config.yaml's ticker lists afterward can silently orphan a position's
    stored sleeve. Logs a warning per mismatch; never writes anything."""
    try:
        config = load_config(config_path)
    except Exception as exc:  # noqa: BLE001 - startup check must never block app boot
        logging.getLogger(__name__).warning("sleeve drift check skipped: could not load config: %s", exc)
        return
    session_factory = make_session_factory(engine)
    session = session_factory()
    try:
        positions = PortfolioService(session, config=config.portfolio, sleeves=config.sleeves).list_positions()
        drift = find_sleeve_drift([(p.ticker, p.sleeve) for p in positions], config.sleeves)
        for d in drift:
            logging.getLogger(__name__).warning(
                "sleeve drift: %s stored as %s but config now resolves it to %s",
                d.ticker, d.stored_sleeve, d.resolved_sleeve,
            )
    finally:
        session.close()


def create_app(
    db_path: str | Path = DB_PATH, config_path: str | Path = CONFIG_PATH, data_dir: str | Path | None = None
) -> FastAPI:
    app = FastAPI(title="Z Money API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",  # Vite default
            "http://localhost:3000", "http://127.0.0.1:3000",  # common alternate
            "tauri://localhost", "http://tauri.localhost",       # the desktop app (src-tauri/)
        ],
        # DELETE is here for the Journal screen — the one place the UI
        # removes a record rather than overwriting config.
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    engine = make_engine(db_path)
    init_db(engine)
    app.state.session_factory = make_session_factory(engine)
    app.state.config_path = Path(config_path)
    # Spend counters and the yfinance cache live beside the DB (data/); the
    # dashboard reads them read-only. Tests point this at a temp dir.
    app.state.data_dir = Path(data_dir) if data_dir is not None else Path(db_path).resolve().parent

    _log_sleeve_drift(engine, Path(config_path))

    app.include_router(briefing_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(screens_router, prefix="/api")
    app.include_router(journal_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
