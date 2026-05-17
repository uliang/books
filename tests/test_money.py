"""Money value object — ADR-0017.

Integer minor units + Currency, immutable, same-currency arithmetic only,
no implicit cross-currency conversion.
"""

import pytest

from books.platform.money import Currency, Money


def test_myr_helper_is_minor_units():
    assert Money.myr(1000_00) == Money(1000_00, Currency.MYR)


def test_is_immutable():
    m = Money.myr(100)
    with pytest.raises(AttributeError):
        m.minor_units = 200  # type: ignore[misc]


def test_same_currency_addition_and_subtraction():
    assert Money.myr(300) + Money.myr(200) == Money.myr(500)
    assert Money.myr(500) - Money.myr(200) == Money.myr(300)


def test_cross_currency_arithmetic_is_rejected():
    with pytest.raises(ValueError, match="currency"):
        Money(100, Currency.MYR) + Money(100, Currency.SGD)


def test_equality_requires_same_currency():
    assert Money(100, Currency.MYR) != Money(100, Currency.SGD)


def test_no_float_construction():
    with pytest.raises(TypeError):
        Money(10.5, Currency.MYR)  # type: ignore[arg-type]
