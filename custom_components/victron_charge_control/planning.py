"""Auto schedule calculation — pick cheapest/most expensive hours from EPEX.

Extracted from ``coordinator.py``. The pure price-comparison and
slot-building logic lives here; the coordinator's wrapper applies the
returned slots back to its own state and triggers the save+refresh
side effects.
"""

from __future__ import annotations

import logging
from typing import Any

from .const import EPEX_KEY_START_TIME, MODE_AUTO
from .epex import (
    extract_price_ct,
    find_epex_data,
    parse_epex_start_time,
)
from .schedule import ScheduleSlot, sort_slots

_LOGGER = logging.getLogger(__name__)


def calculate_auto_schedule(
    hass: Any,
    *,
    epex_spot_entity: str,
    control_mode: str,
    cheapest_hours: int,
    expensive_hours: int,
    charge_price_threshold: float,
    discharge_price_threshold: float,
    blocked_charging_hours: list[int],
    blocked_discharging_hours: list[int],
    pv_charge_hours: list[ScheduleSlot],
    now: Any,
) -> list[ScheduleSlot] | None:
    """Compute optimal charge/discharge hours from EPEX spot prices.

    Returns a tuple ``(charge_slots, discharge_slots)`` of new slot
    lists, or ``None`` when the call was a no-op (not in auto mode, no
    EPEX entity, or no future hours with price data).
    """
    if control_mode != MODE_AUTO:
        return None

    epex_state = hass.states.get(epex_spot_entity)
    if epex_state is None:
        _LOGGER.warning("EPEX entity %s not found", epex_spot_entity)
        return None

    epex_data = find_epex_data(epex_state.attributes)
    if not epex_data:
        _LOGGER.warning(
            "No EPEX price data available in %s", epex_spot_entity
        )
        return None

    current_slot = (now.strftime("%Y-%m-%d"), now.hour)

    prices: list[dict[str, Any]] = []
    for item in epex_data:
        sdt = parse_epex_start_time(item.get(EPEX_KEY_START_TIME))
        if sdt is None:
            continue

        slot_date = sdt.strftime("%Y-%m-%d")
        slot_hour = sdt.hour
        slot = (slot_date, slot_hour)

        if slot >= current_slot:
            price = extract_price_ct(item)
            if price is not None:
                prices.append({"date": slot_date, "hour": slot_hour, "price": price})

    if not prices:
        _LOGGER.info("No future hours with price data available")
        return None

    prices.sort(key=lambda x: x["price"])

    pv_charge_set = set(pv_charge_hours)

    charge_slots: list[ScheduleSlot] = []
    for item in prices:
        if len(charge_slots) >= cheapest_hours:
            break
        slot = (item["date"], item["hour"])
        if slot in pv_charge_set:
            continue
        if (
            item["hour"] not in blocked_charging_hours
            and item["price"] <= charge_price_threshold
        ):
            charge_slots.append(slot)

    discharge_slots: list[ScheduleSlot] = []
    for item in reversed(prices):
        if len(discharge_slots) >= expensive_hours:
            break
        slot = (item["date"], item["hour"])
        if slot in pv_charge_set:
            continue
        if (
            item["hour"] not in blocked_discharging_hours
            and item["price"] >= discharge_price_threshold
        ):
            discharge_slots.append(slot)

    # Resolve conflicts: discharge wins (remove from charge).
    discharge_set = set(discharge_slots)
    charge_slots = [s for s in charge_slots if s not in discharge_set]

    _LOGGER.info(
        "Auto schedule calculated — Charge: %s, Discharge: %s (%d hours evaluated)",
        charge_slots,
        discharge_slots,
        len(prices),
    )
    return sort_slots(charge_slots), sort_slots(discharge_slots)
