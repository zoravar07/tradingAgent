from pathlib import Path

import pytest

from core.config import PortfolioConfig
from core.db import init_db, make_engine, make_session_factory
from core.portfolio import PortfolioService

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def session():
    engine = make_engine(":memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def portfolio(session):
    return PortfolioService(session, config=PortfolioConfig(allow_fractional=False))
