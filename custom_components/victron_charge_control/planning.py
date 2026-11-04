"""Select whole source price intervals within hour-based duration budgets."""

from __future__ import annotations

from datetime import timedelta, timezone
from math import isfinite
from typing import Any

from homeassistant.util import dt as dt_util

from .const import MODE_AUTO
from .epex import normalize_price_intervals
from .schedule import ScheduleSlot, overlaps, sort_slots


def valid_duration(hours: Any) -> bool:
    """Accept only finite quarter-hour budgets within the duration controls' range."""
    return (
        isinstance(hours, (int, float)) and not isinstance(hours, bool)
        and 0 <= hours <= 12 and isfinite(hours) and hours % 0.25 == 0
    )


def calculate_auto_schedule(
    hass: Any,
    *,
    epex_spot_entity: str,
    control_mode: str,
    cheapest_hours: float,
    expensive_hours: float,
    charge_price_threshold: float,
    discharge_price_threshold: float,
    blocked_charging_hours: list[int],
    blocked_discharging_hours: list[int],
    pv_charge_hours: list[ScheduleSlot],
    now: Any,
) -> tuple[list[ScheduleSlot], list[ScheduleSlot]] | None:
    """Count full interval durations, including the current partial interval."""
    if control_mode != MODE_AUTO:
        return None
    state = hass.states.get(epex_spot_entity)
    if state is None or state.state in ("unavailable", "unknown"):
        return None
    prices = [item for item in normalize_price_intervals(state.attributes)
              if item.end > now.astimezone(timezone.utc)]
    if not prices:
        return None

    def select(hours, blocked, threshold, discharge=False):
        if not valid_duration(hours):
            return []
        remaining = hours * 3600
        selected = []
        # Earliest instant breaks ties in either price direction.
        for item in sorted(prices, key=lambda item: (-item.price if discharge else item.price, item.start)):
            duration = (item.end - item.start).total_seconds()
            if duration > remaining or any(
                dt_util.as_local(item.start + timedelta(seconds=offset)).hour in blocked
                for offset in range(0, int(duration), 900)
            ):
                continue
            if any(overlaps(item.slot, pv) for pv in pv_charge_hours):
                continue
            if (item.price < threshold if discharge else item.price > threshold):
                continue
            selected.append(item.slot)
            remaining -= duration
        return selected

    charge = select(cheapest_hours, blocked_charging_hours, charge_price_threshold)
    discharge = select(expensive_hours, blocked_discharging_hours, discharge_price_threshold, True)
    return sort_slots([slot for slot in charge if slot not in discharge]), sort_slots(discharge)
