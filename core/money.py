"""A minimal currency-tagged amount.

Added after a real bug during the first live run: IBKR's account dashboard
(NAV, cash, "excess liquidity") displays figures in the account's BASE
CURRENCY by default — e.g. SGD — even when every position is USD, and a
bare float has no way to catch that. The user read off the SGD figures by
mistake; a plain `float` couldn't have stopped that, and a bare NAV/cash
number flowing through this codebase can't be checked against anything.

Scope, deliberately narrow: this wraps NAV and cash — the figures a human
reads off a broker dashboard and might type in from the wrong currency
column — not every dollar amount in the codebase. Per-share prices and
position values come from FMP quotes, which are always USD by construction
(a single, controlled data source, not a human transcribing a screen), so
they aren't wrapped — see core/portfolio.py's module docstring for the
fuller "currency trap" note and why the CSV import path already guards
against this for cash specifically.

This is NOT a general-purpose currency/forex library — it does no
conversion, and arithmetic between different currencies raises rather than
silently mixing them. If Z Money ever needs true multi-currency accounts,
this needs real conversion logic, not just a bigger version of this class.
"""

from __future__ import annotations

from dataclasses import dataclass


class CurrencyMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str = "USD"

    def __post_init__(self):
        if not self.currency:
            raise ValueError("Money requires a non-empty currency code")

    def _check(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if self.currency != other.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __radd__(self, other) -> "Money":
        # supports sum([...]) which starts its accumulator at the int 0
        if other == 0:
            return self
        return self.__add__(other)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: float) -> "Money":
        return Money(self.amount * factor, self.currency)

    def __rmul__(self, factor: float) -> "Money":
        return self.__mul__(factor)

    def __truediv__(self, other):
        if isinstance(other, Money):
            self._check(other)
            return self.amount / other.amount  # ratio of two amounts is dimensionless
        return Money(self.amount / other, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount >= other.amount

    def __eq__(self, other) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __repr__(self) -> str:
        return f"{self.currency} {self.amount:,.2f}"


def usd(amount: float) -> Money:
    return Money(amount, "USD")
