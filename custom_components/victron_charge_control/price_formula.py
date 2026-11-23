"""Bounded arithmetic on a single market price in ct/kWh."""

import ast
import operator
from collections.abc import Callable
from functools import lru_cache
from math import isfinite

type Term = float | Callable[[float], float]

_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
}


def _value(term: Term, price: float) -> float:
    return term(price) if callable(term) else term


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError("Non-finite price expression")
    return value


def _term(node: ast.expr) -> Term:
    if isinstance(node, ast.Name) and node.id == "price":
        return lambda price: price
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        result = float(node.value)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _term(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        return (lambda price: -operand(price)) if callable(operand) else -operand
    elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        op = _OPERATORS[type(node.op)]
        left, right = _term(node.left), _term(node.right)
        if op is operator.truediv and right == 0:
            raise ValueError("Division by zero")
        if callable(left) or callable(right):
            return lambda price: _finite(op(_value(left, price), _value(right, price)))
        result = op(left, right)
    else:
        raise ValueError("Unsupported price expression")
    return _finite(result)


@lru_cache(maxsize=32)
def parse_formula(formula: str) -> Term:
    """Validate the expression and fold constant arithmetic once."""
    if len(formula) > 128:
        raise ValueError("Price formula exceeds 128 characters")
    try:
        return _term(ast.parse(formula.strip() or "price", mode="eval").body)
    except (SyntaxError, OverflowError) as err:
        raise ValueError("Invalid price formula") from err


def apply_formula(formula: str, price: float | None) -> float | None:
    """Return the effective ct/kWh price, or None for an undefined result."""
    if price is None or not isfinite(price):
        return None
    try:
        return _value(parse_formula(formula), price)
    except (ValueError, ArithmeticError):
        return None
