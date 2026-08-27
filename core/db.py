"""DB engine/session setup. Uses `Base.metadata.create_all` for now — Alembic
migrations are build-order step 1 (skeleton) work, not yet wired up. Swap
`init_db` for an Alembic `upgrade head` call when that lands; don't let both
mechanisms manage the schema at once.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models import Base

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "z_money.db"


def make_engine(db_path: str | Path = DEFAULT_DB_PATH):
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"
    else:
        url = "sqlite://"
    return create_engine(url, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
