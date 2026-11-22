"""Energy and cost tracking helpers.

Extracted from ``coordinator.py``. The helpers operate on plain values
that the coordinator threads in and out — they never reach back into
the coordinator instance, which keeps them unit-testable in isolation
while the coordinator's public/private surface stays unchanged.
"""

from __future__ import annotations

import re
from datetime import datetime
from math import isfinite
from typing import Any

from .epex import get_entity_float

_TARIFF_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def parse_tariff_eur_per_kwh(value: object) -> float | None:
    """Convert a signed decimal tariff from ct/kWh to EUR/kWh."""
    if not isinstance(value, str) or not _TARIFF_PATTERN.fullmatch(value):
        return None
    price = float(value)
    return price / 100 if isfinite(price) else None


def read_meter_delta(
    hass: Any,
    entity_id: str | None,
    last_kwh: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Compute a positive meter delta and the new baseline.

    Returns ``(new_last_kwh, delta_kwh, _unused)`` where ``new_last_kwh``
    is the updated baseline (only set when the meter is configured AND
    produced a usable reading), and ``delta_kwh`` is the positive kWh
    difference since ``last_kwh``, or ``None`` when no delta is
    available. A negative delta (meter reset) re-baselines without
    contributing a delta.
    """
    if entity_id is None:
        return None, None, None

    current_kwh = get_entity_float(hass, entity_id)
    if current_kwh is None:
        return None, None, None

    if last_kwh is None:
        return current_kwh, None, None

    delta_kwh = current_kwh - last_kwh
    if delta_kwh < 0:
        return current_kwh, None, None
    if delta_kwh == 0:
        return None, None, None

    return current_kwh, delta_kwh, None


def accumulate_cost_tracking(
    *,
    consumption_delta_kwh: float | None,
    feed_in_delta_kwh: float | None,
    buy_price: float | None,
    sell_price: float | None,
    cost: float,
    revenue: float,
    import_kwh: float,
    export_kwh: float,
) -> tuple[float, float, float, float, bool]:
    """Update cumulative grid energy cost/revenue/import/export trackers.

    Returns ``(new_cost, new_revenue, new_import, new_export,
    baselines_changed)``. ``baselines_changed`` is True when at least
    one meter reading was applied (i.e. the caller should refresh
    ``_last_cost_update``).
    """
    if consumption_delta_kwh is not None:
        import_kwh += consumption_delta_kwh
        if buy_price is not None:
            amount = consumption_delta_kwh * buy_price
            if amount >= 0:
                cost += amount
            else:
                revenue -= amount

    if feed_in_delta_kwh is not None:
        export_kwh += feed_in_delta_kwh
        if sell_price is not None:
            amount = feed_in_delta_kwh * sell_price
            if amount >= 0:
                revenue += amount
            else:
                cost -= amount

    baselines_changed = consumption_delta_kwh is not None or feed_in_delta_kwh is not None
    return cost, revenue, import_kwh, export_kwh, baselines_changed


def _now() -> datetime:
    from homeassistant.util import dt as dt_util

    return dt_util.now()
