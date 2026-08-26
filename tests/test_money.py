import pytest

from core.money import CurrencyMismatch, Money, usd


class TestMoneyArithmetic:
    def test_add_same_currency(self):
        assert usd(10) + usd(5) == usd(15)

    def test_add_mismatched_currency_raises(self):
        with pytest.raises(CurrencyMismatch):
            usd(10) + Money(5, "SGD")

    def test_sub_same_currency(self):
        assert usd(10) - usd(3) == usd(7)

    def test_mul_by_scalar(self):
        assert usd(10) * 3 == usd(30)
        assert 3 * usd(10) == usd(30)

    def test_div_by_scalar_returns_money(self):
        assert usd(10) / 2 == usd(5)

    def test_div_by_money_returns_ratio(self):
        assert usd(10) / usd(4) == 2.5

    def test_div_by_mismatched_money_raises(self):
        with pytest.raises(CurrencyMismatch):
            usd(10) / Money(4, "SGD")

    def test_negation(self):
        assert -usd(10) == usd(-10)

    def test_sum_of_list_works(self):
        # sum() starts its accumulator at int 0 — __radd__ must handle that
        assert sum([usd(1), usd(2), usd(3)]) == usd(6)

    def test_sum_of_empty_list_is_int_zero_not_money(self):
        # this is a real, known sharp edge — sum([]) can't know the currency
        assert sum([]) == 0


class TestMoneyComparison:
    def test_ordering(self):
        assert usd(5) < usd(10)
        assert usd(10) > usd(5)
        assert usd(5) <= usd(5)
        assert usd(5) >= usd(5)

    def test_ordering_mismatched_currency_raises(self):
        with pytest.raises(CurrencyMismatch):
            usd(5) < Money(10, "SGD")

    def test_equality_requires_same_currency_and_amount(self):
        assert usd(10) == usd(10)
        assert usd(10) != Money(10, "SGD")

    def test_equality_with_non_money_is_not_equal(self):
        assert (usd(10) == 10) is False


class TestMoneyConstruction:
    def test_default_currency_is_usd(self):
        assert Money(5).currency == "USD"

    def test_empty_currency_rejected(self):
        with pytest.raises(ValueError):
            Money(5, "")


class TestMoneyRepr:
    def test_repr_is_readable(self):
        assert repr(usd(1234.5)) == "USD 1,234.50"
