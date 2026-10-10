"""S&P 500 constituents source — the fetcher is a fake throughout. No test
here may hit Wikipedia or any other network."""

from core.cache import FileCache
from sources.index_constituents import (
    SP500ConstituentsSource,
    normalise_symbol,
    parse_wikipedia_symbols,
)


WIKI_HTML = """
<table id="constituents" class="wikitable sortable">
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>
<tr><td><a href="#">MMM</a></td><td>3M</td><td>Industrials</td></tr>
<tr><td><a href="#">brk.b</a></td><td>Berkshire Hathaway</td><td>Financials</td></tr>
<tr><td><a href="#">AAPL</a></td><td>Apple</td><td>Information Technology</td></tr>
<tr><td><a href="#">AAPL</a></td><td>Apple (dup row)</td><td>Information Technology</td></tr>
</table>
<table id="changes" class="wikitable"><tr><th>Date</th><th>Added</th></tr><tr><td>2026-01-01</td><td>ZZZ</td></tr></table>
"""


class TestNormaliseSymbol:
    def test_upper_cases(self):
        assert normalise_symbol("aapl") == "AAPL"

    def test_dot_share_classes_become_yahoo_dashes(self):
        # Wikipedia writes BRK.B / BF.B; yfinance only knows BRK-B / BF-B.
        assert normalise_symbol("BRK.B") == "BRK-B"

    def test_strips_whitespace(self):
        assert normalise_symbol("  MSFT \n") == "MSFT"


class TestParseWikipediaSymbols:
    def test_reads_only_the_constituents_table(self):
        symbols = parse_wikipedia_symbols(WIKI_HTML)
        assert "ZZZ" not in symbols  # the "changes" table is not the index

    def test_sorted_unique_normalised(self):
        assert parse_wikipedia_symbols(WIKI_HTML) == ["AAPL", "BRK-B", "MMM"]


def big_wiki_html(n: int = 500) -> str:
    rows = "".join(f"<tr><td>T{i}</td><td>Co {i}</td><td>Sector</td></tr>" for i in range(n))
    return f'<table id="constituents" class="wikitable"><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>{rows}</table>'


class TestSP500ConstituentsSource:
    def test_uses_injected_fetcher_and_caches(self, tmp_path):
        calls = []

        def fetcher() -> str:
            calls.append(1)
            return big_wiki_html()

        source = SP500ConstituentsSource(cache=FileCache(tmp_path / "cache"), fetcher=fetcher)
        first = source.get_constituents()
        second = source.get_constituents()
        assert len(first) == 500 and first[0] == "T0"
        assert second == first
        assert len(calls) == 1  # second call served from cache

    def test_truncated_table_raises_rather_than_caching_a_small_pool(self, tmp_path):
        import pytest

        source = SP500ConstituentsSource(cache=FileCache(tmp_path / "cache"), fetcher=lambda: big_wiki_html(50))
        with pytest.raises(RuntimeError):
            source.get_constituents()

    def test_empty_table_raises_rather_than_returning_an_empty_pool(self, tmp_path):
        import pytest

        source = SP500ConstituentsSource(cache=FileCache(tmp_path / "cache"), fetcher=lambda: "<html></html>")
        with pytest.raises(RuntimeError):
            source.get_constituents()
