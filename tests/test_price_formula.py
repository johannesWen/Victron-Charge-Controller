"""Arithmetic accepted by the import and export pricing forms."""

import pytest

from custom_components.victron_charge_control.price_formula import apply_formula, parse_formula


@pytest.mark.parametrize("formula", [
    "price +", "amount", "price.real", "abs(price)", "True", "price ** 2",
    "price // 2", "1e999", "price / (2 - 2)", "1e300 * 1e300", "1+" * 70 + "1",
])
def test_invalid_formula(formula):
    with pytest.raises(ValueError):
        parse_formula(formula)


def test_runtime_arithmetic_and_missing_readings():
    assert apply_formula(" +price * -2 + 1 ", -3) == 7
    assert apply_formula("0", -2) == 0
    assert apply_formula("", -2) == -2
    assert apply_formula("1 / price", 0) is None
    assert apply_formula("1 / price", -2) == -0.5
    assert apply_formula("price * 1e200", 1e200) is None
    assert apply_formula("1 / (price * 1e200)", 1e200) is None
    assert apply_formula("0", None) == 0
    assert apply_formula("-(2 + 3.5)", None) == -5.5
    assert apply_formula("price * 0", None) is None
    assert apply_formula("", None) is None
