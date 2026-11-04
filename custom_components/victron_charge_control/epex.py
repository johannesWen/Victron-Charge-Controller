"""EPEX spot price parsing helpers.

Extracted from ``coordinator.py``. All helpers are pure functions that
operate on attributes / state values without touching the coordinator
state directly — the coordinator's static wrappers stay around for
backwards-compatibility with tests and existing call sites.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    EPEX_ATTR_DATA,
    EPEX_KEY_END_TIME,
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
        if any(isinstance(item, dict) and (
            EPEX_KEY_START_TIME in item
            or EPEX_KEY_PRICE in item
            or EPEX_KEY_PRICE_EUR in item
        ) for item in attr_value):
            return attr_value
    return []


def extract_price_ct(item: dict[str, Any]) -> float | None:
    """Extract price in ct/kWh from a single EPEX entry.

    Handles both 'price_ct_per_kwh' (cents) and 'price_per_kwh' (EUR).
    """
    price = item.get(EPEX_KEY_PRICE)
    if price is not None:
        if isinstance(price, bool):
            return None
        try:
            value = float(price)
            return value if isfinite(value) else None
        except (ValueError, TypeError, OverflowError):
            return None
    price_eur = item.get(EPEX_KEY_PRICE_EUR)
    if price_eur is not None:
        if isinstance(price_eur, bool):
            return None
        try:
            value = float(price_eur) * 100.0
            return value if isfinite(value) else None
        except (ValueError, TypeError, OverflowError):
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
    except (ValueError, TypeError, OverflowError):
        return None

    if not isfinite(price):
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
    except (ValueError, TypeError, OverflowError):
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
    except (ValueError, TypeError, OverflowError):
        return None


def parse_epex_start_time(value: Any) -> datetime | None:
    """Parse an offset-bearing instant; naive timestamps are ambiguous at DST."""
    try:
        parsed = dt_util.parse_datetime(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True)
class PriceInterval:
    """One indivisible source interval, identified by UTC bounds."""

    start: datetime
    end: datetime
    price: float

    @property
    def slot(self) -> tuple[datetime, datetime]:
        return self.start, self.end


def normalize_price_intervals(attributes: dict[str, Any]) -> list[PriceInterval]:
    """Validate source periods without averaging prices or bridging missing data."""
    entries: list[tuple[datetime, datetime | None, float | None]] = []
    for item in find_epex_data(attributes):
        if not isinstance(item, dict):
            continue
        start = parse_epex_start_time(item.get(EPEX_KEY_START_TIME))
        if start is None or start.second or start.microsecond or start.minute % 15:
            continue
        end = parse_epex_start_time(item.get(EPEX_KEY_END_TIME))
        # Keep invalid entries as boundaries so inference cannot fill their gaps.
        price = extract_price_ct(item)
        if EPEX_KEY_END_TIME in item and end is None:
            price = None
        entries.append((start, end, price))
    entries.sort(key=lambda entry: entry[0])
    starts = sorted({start for start, _, _ in entries})
    differences = [(b - a) for a, b in zip(starts, starts[1:])]
    explicit = [end - start for start, end, _ in entries if end is not None]
    quarter = timedelta(minutes=15)
    hour = timedelta(hours=1)
    cadence = quarter if quarter in differences or quarter in explicit or any(s.minute for s in starts) else hour
    next_start = dict(zip(starts, starts[1:]))
    candidates: list[PriceInterval] = []
    for start, end, price in entries:
        if end is None:
            # A longer gap cannot distinguish missing quarters from an hourly period.
            following = next_start.get(start)
            duration = min(following - start, cadence) if following else cadence
            try:
                end = start + duration
            except OverflowError:
                continue
        if price is None or end - start not in (quarter, hour):
            continue
        candidates.append(PriceInterval(start, end, price))
    candidates = sorted(set(candidates), key=lambda item: (item.start, item.end, item.price))
    invalid: set[int] = set()
    for index, item in enumerate(candidates):
        for following in range(index + 1, len(candidates)):
            if candidates[following].start >= item.end:
                break
            invalid.update((index, following))
    return [item for index, item in enumerate(candidates) if index not in invalid]


def price_timeline(
    intervals: list[PriceInterval], date_str: str,
    schedule: Sequence[tuple[datetime, datetime]] = (),
) -> list[dict[str, Any]]:
    """Clip source coverage to a civil day and split it at schedule boundaries."""
    from .schedule import slot_attributes

    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    start = day.astimezone(timezone.utc)
    end = (day + timedelta(days=1)).astimezone(timezone.utc)
    periods = [item for item in intervals if item.start < end and item.end > start]
    cadence = timedelta(minutes=15) if any(
        item.end - item.start == timedelta(minutes=15) for item in intervals
    ) else timedelta(hours=1)
    # Retained schedules can have finer action boundaries than the current source prices.
    boundaries = sorted({instant for slot in schedule for instant in slot if start < instant < end})

    def gap_stop(cursor: datetime, limit: datetime) -> datetime:
        stop = min(start + ((cursor - start) // cadence + 1) * cadence, limit)
        return next((boundary for boundary in boundaries if cursor < boundary < stop), stop)

    result = []
    cursor = start
    for item in periods:
        begin, finish = max(start, item.start), min(end, item.end)
        while cursor < begin:
            stop = gap_stop(cursor, begin)
            result.append(slot_attributes((cursor, stop)))
            cursor = stop
        splits = [begin, *(boundary for boundary in boundaries if begin < boundary < finish), finish]
        for left, right in zip(splits, splits[1:]):
            result.append({**slot_attributes((left, right)), "price": item.price})
        cursor = finish
    while cursor < end:
        stop = gap_stop(cursor, end)
        result.append(slot_attributes((cursor, stop)))
        cursor = stop
    return result
