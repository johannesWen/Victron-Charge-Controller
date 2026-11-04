"""Plan persistence helpers.

Pure helpers for serialising and deserialising the coordinator's
schedule state. The actual ``Store`` instance is constructed in
``coordinator.py`` (so the test conftest patch on
``custom_components.victron_charge_control.coordinator.Store`` keeps
working) and the async save/load methods stay on the coordinator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.helpers.storage import Store

from .epex import parse_epex_start_time
from .schedule import ScheduleSlot, local_hour_slots, normalize_fixed_plan, sort_slots


class ScheduleStore(Store):
    """Upgrade actual HA storage envelopes, preserving unrelated recovery fields."""

    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        if old_major_version != 1 or not isinstance(old_data, dict):
            raise ValueError("Unsupported schedule store version")
        data = dict(old_data)
        for key in ("charge_hours", "discharge_hours", "pv_charge_hours"):
            data[key] = serialize_slots(deserialize_slots(data.get(key)))
        return data


def serialize_slots(slots: list[ScheduleSlot]) -> list[list[str]]:
    """Serialize UTC interval bounds for JSON storage."""
    return [[start.isoformat(), end.isoformat()] for start, end in slots]


def deserialize_slots(raw: Any) -> list[ScheduleSlot]:
    """Read v2 intervals and legacy dated hours, dropping malformed entries."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        if isinstance(item[0], str) and isinstance(item[1], int):
            result.extend(local_hour_slots(*item))
            continue
        start, end = (parse_epex_start_time(value) for value in item)
        if start is not None and end is not None and start < end:
            duration = (end - start).total_seconds()
            if (duration <= 3600 and duration % 900 == 0
                    and not start.second and not start.microsecond and start.minute % 15 == 0):
                result.append((start, end))
    return sort_slots(result)


def deserialize_hours(raw: Any) -> list[int]:
    """Deserialise an hour-of-day list, dropping any out-of-range value."""
    if not isinstance(raw, list):
        return []
    return sorted({int(h) for h in raw if isinstance(h, int) and 0 <= h <= 23})


def serialize_fixed_plans(
    fixed_plans: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Serialise the fixed-plan definitions for JSON storage.

    JSON requires string keys, so the plan numbers are stringified.
    """
    return {str(plan): normalize_fixed_plan(data) for plan, data in sorted(fixed_plans.items())}


def deserialize_fixed_plans(raw: Any) -> dict[int, dict[str, Any]]:
    """Deserialise the fixed-plan definitions, dropping malformed plans."""
    if not isinstance(raw, dict):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for key, plan_data in raw.items():
        if not isinstance(plan_data, dict):
            continue
        try:
            plan = int(key)
        except (TypeError, ValueError):
            continue
        if plan < 1:
            continue
        result[plan] = normalize_fixed_plan(plan_data)
    return result


def deserialize_active_fixed_plan(raw: Any, fixed_plans: dict[int, Any]) -> int | None:
    """Deserialise the active fixed-plan number, if it references a known plan."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw in fixed_plans:
        return raw
    if isinstance(raw, str):
        try:
            plan = int(raw)
        except ValueError:
            return None
        if plan in fixed_plans:
            return plan
    return None


def build_plan_payload(
    *,
    charge_hours: list[ScheduleSlot],
    discharge_hours: list[ScheduleSlot],
    pv_charge_hours: list[ScheduleSlot],
    blocked_charging_hours: list[int],
    blocked_discharging_hours: list[int],
    fixed_plans: dict[int, dict[str, Any]] | None = None,
    active_fixed_plan: int | None = None,
    last_schedule_update: datetime | None,
) -> dict[str, Any]:
    """Build the JSON payload written to the persistent Store."""
    return {
        "charge_hours": serialize_slots(charge_hours),
        "discharge_hours": serialize_slots(discharge_hours),
        "pv_charge_hours": serialize_slots(pv_charge_hours),
        "blocked_charging_hours": list(blocked_charging_hours),
        "blocked_discharging_hours": list(blocked_discharging_hours),
        "fixed_plans": serialize_fixed_plans(fixed_plans or {}),
        "active_fixed_plan": active_fixed_plan,
        "last_schedule_update": (
            last_schedule_update.isoformat() if last_schedule_update is not None else None
        ),
    }


def apply_loaded_plan(
    data: Any,
) -> dict[str, Any] | None:
    """Parse a Store payload and return the state to apply, or ``None`` if invalid.

    The returned dict has the same shape consumed by ``_async_load_schedule``
    on the coordinator (validated slot lists, deserialised hours, parsed
    timestamp, ``loaded=True`` flag). Returns ``None`` if the payload is
    not a dict — in that case the caller leaves in-memory state alone.
    """
    if not isinstance(data, dict):
        return None
    fixed_plans = deserialize_fixed_plans(data.get("fixed_plans"))
    return {
        "charge_hours": deserialize_slots(data.get("charge_hours")),
        "discharge_hours": deserialize_slots(data.get("discharge_hours")),
        "pv_charge_hours": deserialize_slots(data.get("pv_charge_hours")),
        "blocked_charging_hours": deserialize_hours(data.get("blocked_charging_hours")),
        "blocked_discharging_hours": deserialize_hours(data.get("blocked_discharging_hours")),
        "fixed_plans": fixed_plans,
        "active_fixed_plan": deserialize_active_fixed_plan(
            data.get("active_fixed_plan"), fixed_plans
        ),
        "last_schedule_update": _parse_iso_datetime(data.get("last_schedule_update")),
        "loaded": True,
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    from homeassistant.util import dt as dt_util

    return dt_util.parse_datetime(value)
