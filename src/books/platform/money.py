"""Money value object (ADR-0017).

``Money`` is ``(integer minor units, Currency)``, immutable. No floats.
Same-currency arithmetic only; cross-currency conversion happens elsewhere
via an explicit rate and is out of scope for the tracer thread.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Currency(enum.Enum):
    MYR = "MYR"
    SGD = "SGD"


@dataclass(frozen=True, slots=True)
class Money:
    minor_units: int
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.minor_units, int) or isinstance(self.minor_units, bool):
            raise TypeError("minor_units must be an int (no floats)")

    @classmethod
    def myr(cls, minor_units: int) -> Money:
        return cls(minor_units, Currency.MYR)

    @classmethod
    def sgd(cls, minor_units: int) -> Money:
        return cls(minor_units, Currency.SGD)

    def _same_currency(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError(
                f"cross-currency operation: {self.currency} vs {other.currency}"
            )

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)
