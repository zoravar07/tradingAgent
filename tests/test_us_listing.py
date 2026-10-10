"""US listing + liquidity pre-gate — fetchers are fakes throughout. No test
here may hit NASDAQ Trader or Yahoo."""

import pytest

from core.cache import FileCache
from sources.us_listing import (
    USEquityScreen,
    USListingSource,
    apply_liquidity_pregate,
    parse_us_common_stocks,
    screen_rows_to_quotes,
)

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
ZTEST|Test Issue|G|Y|N|100|N|N
ACIW|ACI Worldwide - Warrants|G|N|N|100|N|N
AACOU|Some Acquisition Corp - Units|G|N|N|100|N|N
File Creation Time: 0909202600:00|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
JPM|JPMorgan Chase - Common Stock|N|JPM|N|100|N|JPM
BRK.B|Berkshire Hathaway Class B|N|BRK B|N|100|N|BRK=B
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
ABC$P|Preferred Series P|N|ABCp|N|100|N|ABC-P
XYZ|Some Corp Depositary Shares|N|XYZ|N|100|N|XYZ
IEXQ|IEX listed|V|IEXQ|N|100|N|IEXQ
File Creation Time: 0909202600:00|||||||
"""


class TestParse:
    def test_keeps_common_stock_only(self):
        assert parse_us_common_stocks(NASDAQ, OTHER) == ["AAPL", "JPM"]


class TestUSListingSource:
    def test_caches_and_refuses_small_listings(self, tmp_path):
        calls = []

        def fetcher():
            calls.append(1)
            import itertools, string

            symbols = ["".join(c) for c in itertools.islice(itertools.product(string.ascii_uppercase, repeat=3), 3500)]
            n = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n" + "".join(
                f"{sym}|Co {sym} Common Stock|Q|N|N|100|N|N\n" for sym in symbols
            )
            return n, OTHER

        source = USListingSource(cache=FileCache(tmp_path / "c"), fetcher=fetcher)
        first = source.get_symbols()
        assert len(first) == 3500 and source.get_symbols() == first and calls == [1]  # JPM is among the synthetic combos

        small = USListingSource(cache=FileCache(tmp_path / "d"), fetcher=lambda: (NASDAQ, OTHER))
        with pytest.raises(RuntimeError):
            small.get_symbols()


class TestScreen:
    def test_pages_until_total_and_maps_rows(self, tmp_path):
        pages = {
            0: ([{"symbol": "AAPL", "quoteType": "EQUITY", "marketCap": 3e12, "averageDailyVolume3Month": 5e7, "regularMarketPrice": 200.0},
                 {"symbol": "SPY", "quoteType": "ETF", "marketCap": None, "averageDailyVolume3Month": 7e7, "regularMarketPrice": 500.0}], 3),
            2: ([{"symbol": "tiny", "quoteType": "EQUITY", "marketCap": 1e8, "averageDailyVolume3Month": 1e4, "regularMarketPrice": 3.0}], 3),
        }
        seen = []

        def fetcher(offset, size):
            seen.append(offset)
            return pages[offset]

        screen = USEquityScreen(cache=FileCache(tmp_path / "c"), page_fetcher=fetcher, page_size=2)
        quotes = screen.get_quotes()
        assert seen == [0, 2]
        assert set(quotes) == {"AAPL", "TINY"}  # the ETF row is dropped, symbols upper-cased
        assert quotes["AAPL"] == {"market_cap": 3e12, "three_month_avg_volume": 5e7, "last_price": 200.0, "quote_type": "EQUITY"}
        assert screen.get_quotes() == quotes and seen == [0, 2]  # cached

    def test_rows_to_quotes_shape_matches_fast_info_cache(self):
        q = screen_rows_to_quotes([{"symbol": "x", "quoteType": "EQUITY", "marketCap": 1, "averageDailyVolume3Month": 2, "regularMarketPrice": 3}])
        assert q == {"X": {"market_cap": 1, "three_month_avg_volume": 2, "last_price": 3, "quote_type": "EQUITY"}}


class TestPregate:
    def test_applies_both_floors_and_drops_unknown_symbols(self):
        quotes = {
            "BIG": {"market_cap": 5e9, "three_month_avg_volume": 1e6, "last_price": 100.0},  # $100M ADV
            "ILLIQ": {"market_cap": 5e9, "three_month_avg_volume": 1e4, "last_price": 100.0},  # $1M ADV
            "SMALL": {"market_cap": 5e8, "three_month_avg_volume": 1e6, "last_price": 100.0},
        }
        out = apply_liquidity_pregate(["big", "ILLIQ", "SMALL", "NOROW"], quotes, min_market_cap_usd=2e9, min_avg_daily_volume_usd=20e6)
        assert out == ["BIG"]
