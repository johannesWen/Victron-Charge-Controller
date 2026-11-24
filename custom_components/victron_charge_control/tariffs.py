"""Shared tariff input and compatibility with fixed History prices."""

import re
from math import isfinite

from .price_formula import parse_formula

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def legacy_fixed_formula(value: object) -> str | None:
    """Keep valid decimal text, including old values such as +0012."""
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        return None
    rate = float(value)
    if not isfinite(rate):
        return None
    try:
        parse_formula(value)
    except ValueError:
        return str(rate)
    return value


def validated_formula(value: str) -> str:
    """Validate the shared formula, accepting legacy signed decimal inputs."""
    try:
        parse_formula(value)
    except ValueError:
        legacy = legacy_fixed_formula(value.strip())
        if legacy is None or len(value) > 128:
            raise
        return legacy
    return value.strip()
