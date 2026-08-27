"""FastAPI app — §4's `api/server.py + routes/`, §10 step 10. Serves the UI
(ui/) its data. Single-user local app: no auth, CORS scoped to localhost dev
origins (Vite's default port and a couple of common alternates) — this is
not designed to be exposed beyond the machine it runs on.

Run with: .venv/bin/uvicorn api.server:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.briefing import router as briefing_router
from core.db import init_db, make_engine, make_session_factory

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "z_money.db"


def create_app(db_path: str | Path = DB_PATH) -> FastAPI:
    app = FastAPI(title="Z Money API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",  # Vite default
            "http://localhost:3000", "http://127.0.0.1:3000",  # common alternate
        ],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    engine = make_engine(db_path)
    init_db(engine)
    app.state.session_factory = make_session_factory(engine)

    app.include_router(briefing_router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
