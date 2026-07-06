"""EPEX spot price parsing helpers.

Extracted from ``coordinator.py``. All helpers are pure functions that
operate on attributes / state values without touching the coordinator
state directly — the coordinator's static wrappers stay around for
backwards-compatibility with tests and existing call sites.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import (
    EPEX_ATTR_DATA,
    EPEX_KEY_PRICE,
    EPEX_KEY_PRICE_EUR,
    EPEX_KEY_START_TIME,
)


def find_epex_data(attributes: dict[str, Any]) -> list[dict[str, Any]]:
    """Find the list of price entries from EPEX entity attributes.

    Supports mampfes/ha-epex-spot ('data' attribute) and other integrations
    that store entries under alternative attribute names.
    """
    data = attributes.get(EPEX_ATTR_DATA)
    if isinstance(data, list) and data:
        return data
    for attr_name, attr_value in attributes.items():
        if not isinstance(attr_value, list) or not attr_value:
            continue
        first = attr_value[0]
        if isinstance(first, dict) and (
            EPEX_KEY_START_TIME in first
            or EPEX_KEY_PRICE in first
            or EPEX_KEY_PRICE_EUR in first
        ):
            return attr_value
    return []


def extract_price_ct(item: dict[str, Any]) -> float | None:
    """Extract price in ct/kWh from a single EPEX entry.

    Handles both 'price_ct_per_kwh' (cents) and 'price_per_kwh' (EUR).
    """
    price = item.get(EPEX_KEY_PRICE)
    if price is not None:
        try:
            return float(price)
        except (ValueError, TypeError):
            return None
    price_eur = item.get(EPEX_KEY_PRICE_EUR)
    if price_eur is not None:
        try:
            return float(price_eur) * 100.0
        except (ValueError, TypeError):
            return None
    return None


def normalize_price_eur_per_kwh(
    state_value: str | float | int | None,
    attributes: dict[str, Any],
) -> float | None:
    """Normalize an EPEX state value to EUR/kWh for cost accounting."""
    if state_value in (None, "unavailable", "unknown"):
        return None
    try:
        price = float(state_value)
    except (ValueError, TypeError):
        return None

    unit = str(attributes.get("unit_of_measurement", "")).strip().lower()
    if "ct" in unit or "cent" in unit or unit.startswith("c/") or " c/" in unit:
        return price / 100.0
    return price


def get_current_price_ct(hass: Any, entity_id: str) -> float | None:
    """Read the EPEX spot price in ct/kWh from the given entity.

    Returns ``None`` when the sensor is unavailable or unparseable.
    """
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        return None
    price_eur_kwh = normalize_price_eur_per_kwh(
        state.state, dict(state.attributes)
    )
    if price_eur_kwh is None:
        return None
    return price_eur_kwh * 100.0


def get_battery_soc(hass: Any, entity_id: str) -> float | None:
    """Read the battery SOC, returning ``None`` when unavailable or invalid."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        return None
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return None


def get_entity_float(hass: Any, entity_id: str | None) -> float | None:
    """Read a numeric entity state, returning ``None`` when unavailable or invalid."""
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        return None
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return None


def parse_epex_start_time(start_time: Any) -> datetime | None:
    """Parse a ``start_time`` field from an EPEX entry into a local datetime.

    Returns ``None`` when the field is missing or unparseable.
    """
    if isinstance(start_time, str):
        try:
            parsed = _parse_datetime(start_time)
        except (ValueError, TypeError):
            return None
        return _as_local(parsed) if parsed is not None else None
    if isinstance(start_time, datetime):
        return _as_local(start_time)
    return None


def _parse_datetime(value: str) -> datetime | None:
    from homeassistant.util import dt as dt_util

    return dt_util.parse_datetime(value)


def _as_local(value: datetime) -> datetime:
    from homeassistant.util import dt as dt_util

    return dt_util.as_local(value)
