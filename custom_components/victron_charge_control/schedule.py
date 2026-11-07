"""UTC interval schedules and local-hour compatibility operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.util import dt as dt_util

from .const import ACTION_BLOCKED, ACTION_CHARGE, ACTION_DISCHARGE, ACTION_PV_CHARGE

ScheduleSlot = tuple[datetime, datetime]


def sort_slots(slots: list[ScheduleSlot]) -> list[ScheduleSlot]:
    """Sort and deduplicate intervals by their actual instants."""
    return sorted(set(slots))


def valid_slot(date_str: str, hour: int) -> bool:
    """Validate an external local-hour input."""
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        return False
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d") == date_str
    except (ValueError, TypeError):
        return False


def today_str(now: datetime | None = None) -> str:
    """Return the date in HA local time."""
    return (now or dt_util.now()).strftime("%Y-%m-%d")


def local_hour_slots(date_str: str, hour: int) -> list[ScheduleSlot]:
    """Expand a local hour to both fall-back occurrences, or none in spring."""
    if not valid_slot(date_str, hour):
        return []
    naive = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour)
    starts = set()
    for fold in (0, 1):
        local = naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE, fold=fold)
        utc = local.astimezone(timezone.utc)
        if dt_util.as_local(utc).replace(tzinfo=None) == naive:
            starts.add(utc)
    return [(start, start + timedelta(hours=1)) for start in sorted(starts)]


def slot_attributes(slot: ScheduleSlot) -> dict[str, Any]:
    start, end = slot
    local = dt_util.as_local(start)
    return {"start_time": start.isoformat(), "end_time": end.isoformat(),
            "date": local.date().isoformat(), "hour": local.hour, "minute": local.minute}


def active_slot(slots: list[ScheduleSlot], now: datetime) -> bool:
    """Test half-open coverage by actual instant, including repeated local hours."""
    instant = now.astimezone(timezone.utc)
    return any(start <= instant < end for start, end in slots)


def overlaps(left: ScheduleSlot, right: ScheduleSlot) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def subtract_slots(slots: list[ScheduleSlot], removed: list[ScheduleSlot]) -> list[ScheduleSlot]:
    """Remove coverage, retaining untouched parts of a migrated hourly slot."""
    result = list(slots)
    for begin, end in removed:
        remaining = []
        for start, stop in result:
            if stop <= begin or start >= end:
                remaining.append((start, stop))
            else:
                if start < begin:
                    remaining.append((start, begin))
                if stop > end:
                    remaining.append((end, stop))
        result = remaining
    return sort_slots(result)


def clean_expired_slots(charge, discharge, pv_charge, now=None):
    instant = (now or dt_util.now()).astimezone(timezone.utc)
    return tuple([slot for slot in slots if slot[1] > instant] for slots in (charge, discharge, pv_charge))


def set_charge_slots(slots) -> list[ScheduleSlot]:
    """Accept legacy local-hour inputs at the public coordinator boundary."""
    result = []
    for start, end in slots:
        if isinstance(start, str) and isinstance(end, int):
            result.extend(local_hour_slots(start, end))
        elif (isinstance(start, datetime) and isinstance(end, datetime)
              and start.tzinfo is not None and end.tzinfo is not None and start < end):
            result.append((start.astimezone(timezone.utc), end.astimezone(timezone.utc)))
    return sort_slots(result)


set_discharge_slots = set_charge_slots


def normalize_blocked_hours(hours: list[int]) -> list[int]:
    return sorted(set(h for h in hours if 0 <= h <= 23))


def hour_intervals(date_str: str, hour: int, source: list[ScheduleSlot]) -> list[ScheduleSlot]:
    """Partition a whole local hour at source boundaries without losing gaps."""
    result = []
    for start, end in local_hour_slots(date_str, hour):
        boundaries = {start, end}
        for begin, stop in source:
            if start < begin < end:
                boundaries.add(begin)
            if start < stop < end:
                boundaries.add(stop)
        ordered = sorted(boundaries)
        result.extend(zip(ordered, ordered[1:]))
    return result


def set_hour_action(hour, action, date_str, charge, discharge, pv_charge,
                    blocked_charging, blocked_discharging, source=()):
    date_str = date_str or today_str()
    if not valid_slot(date_str, hour):
        return charge, discharge, pv_charge, blocked_charging, blocked_discharging, True
    targets = hour_intervals(date_str, hour, list(source))
    charge, discharge, pv_charge = (subtract_slots(slots, targets) for slots in (charge, discharge, pv_charge))
    if action == ACTION_CHARGE:
        charge = sort_slots(charge + targets)
    elif action == ACTION_PV_CHARGE:
        pv_charge = sort_slots(pv_charge + targets)
    elif action == ACTION_DISCHARGE:
        discharge = sort_slots(discharge + targets)
    elif action == ACTION_BLOCKED:
        blocked_charging = sorted(set(blocked_charging + [hour]))
        blocked_discharging = sorted(set(blocked_discharging + [hour]))
    return charge, discharge, pv_charge, blocked_charging, blocked_discharging, False


def toggle_hour(hour, date_str, charge, discharge, pv_charge,
                blocked_charging, blocked_discharging, source=()):
    date_str = date_str or today_str()
    targets = local_hour_slots(date_str, hour)
    if not targets:
        return charge, discharge, pv_charge, blocked_charging, blocked_discharging, True
    def contains(slots):
        return any(overlaps(slot, target) for slot in slots for target in targets)
    if contains(charge):
        action = ACTION_PV_CHARGE
    elif contains(pv_charge):
        action = ACTION_DISCHARGE
    elif contains(discharge):
        action = ACTION_BLOCKED
    elif hour in blocked_charging or hour in blocked_discharging:
        action = "idle"
        blocked_charging = [h for h in blocked_charging if h != hour]
        blocked_discharging = [h for h in blocked_discharging if h != hour]
    else:
        action = ACTION_CHARGE
    return set_hour_action(hour, action, date_str, charge, discharge, pv_charge,
                           blocked_charging, blocked_discharging, source)


def clear_all():
    return [], [], [], [], []


FIXED_PLAN_BUCKETS = ("charge_hours", "discharge_hours", "pv_charge_hours")

MAX_FIXED_PLAN_NAME_LENGTH = 10


def normalize_fixed_plan_name(name: Any) -> str:
    """Validate a fixed-plan display name.

    Non-strings are dropped (empty result); strings are trimmed and
    truncated to ``MAX_FIXED_PLAN_NAME_LENGTH`` characters.
    """
    if not isinstance(name, str):
        return ""
    return name.strip()[:MAX_FIXED_PLAN_NAME_LENGTH]


def normalize_fixed_plan(plan: Any) -> dict[str, Any]:
    """Validate a fixed-plan dict, returning a normalized copy.

    A fixed plan maps bucket names (``charge_hours``, ``discharge_hours``,
    ``pv_charge_hours``) to lists of recurring hour-of-day values plus an
    optional user-defined ``name``. Unknown buckets, out-of-range hours and
    corrupt names are dropped so a corrupt store cannot produce invalid
    state.
    """
    normalized: dict[str, Any] = {
        "charge_hours": [],
        "discharge_hours": [],
        "pv_charge_hours": [],
        "name": "",
    }
    if not isinstance(plan, dict):
        return normalized
    for key in FIXED_PLAN_BUCKETS:
        raw = plan.get(key, [])
        if not isinstance(raw, list):
            continue
        normalized[key] = sorted({h for h in raw if isinstance(h, int) and 0 <= h <= 23})
    normalized["name"] = normalize_fixed_plan_name(plan.get("name"))
    return normalized


def apply_fixed_plan(charge, discharge, pv_charge, fixed_plan, dates, source=()):
    """Overlay recurring local hours on source intervals; preserve PV precedence."""
    normalized = normalize_fixed_plan(fixed_plan)
    applied = []
    for date_str in dates:
        for bucket, action in (("discharge_hours", ACTION_DISCHARGE),
                               ("charge_hours", ACTION_CHARGE),
                               ("pv_charge_hours", ACTION_PV_CHARGE)):
            for hour in normalized[bucket]:
                charge, discharge, pv_charge, _, _, _ = set_hour_action(
                    hour, action, date_str, charge, discharge, pv_charge, [], [], source)
                applied.extend(hour_intervals(date_str, hour, list(source)))
    return charge, discharge, pv_charge, sort_slots(applied)
