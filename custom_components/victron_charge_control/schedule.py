"""Schedule slot operations.

Pure functions that operate on schedule state. Extracted from
``coordinator.py`` so the coordinator's public mutators become thin
wrappers that combine the slot update with the save-and-refresh
side effects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import ACTION_BLOCKED, ACTION_CHARGE, ACTION_DISCHARGE, ACTION_PV_CHARGE

ScheduleSlot = tuple[str, int]


def sort_slots(slots: list[ScheduleSlot]) -> list[ScheduleSlot]:
    """Sort and deduplicate schedule slots by (date, hour)."""
    return sorted(set(slots))


def valid_slot(date_str: str, hour: int) -> bool:
    """Validate a (date_str, hour) tuple."""
    if not (0 <= hour <= 23):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def today_str(now: datetime | None = None) -> str:
    """Return today's date as ISO string."""
    if now is None:
        from homeassistant.util import dt as dt_util

        now = dt_util.now()
    return now.strftime("%Y-%m-%d")


def clean_expired_slots(
    charge: list[ScheduleSlot],
    discharge: list[ScheduleSlot],
    pv_charge: list[ScheduleSlot],
    now: datetime | None = None,
) -> tuple[list[ScheduleSlot], list[ScheduleSlot], list[ScheduleSlot]]:
    """Remove schedule slots that are in the past.

    Returns a new tuple of (charge, discharge, pv_charge) with only
    future slots remaining. The input lists are not mutated.
    """
    current = now if now is not None else _now()
    current_date = current.strftime("%Y-%m-%d")
    current_hour = current.hour

    def is_future(slot: ScheduleSlot) -> bool:
        d, h = slot
        if d > current_date:
            return True
        if d == current_date and h >= current_hour:
            return True
        return False

    return (
        [s for s in charge if is_future(s)],
        [s for s in discharge if is_future(s)],
        [s for s in pv_charge if is_future(s)],
    )


def set_charge_slots(slots: list[ScheduleSlot]) -> list[ScheduleSlot]:
    """Validate, sort and deduplicate the supplied charge slots."""
    return sort_slots([s for s in slots if valid_slot(s[0], s[1])])


def set_discharge_slots(slots: list[ScheduleSlot]) -> list[ScheduleSlot]:
    """Validate, sort and deduplicate the supplied discharge slots."""
    return sort_slots([s for s in slots if valid_slot(s[0], s[1])])


def normalize_blocked_hours(hours: list[int]) -> list[int]:
    """Filter, deduplicate and sort a list of hour-of-day values."""
    return sorted(set(h for h in hours if 0 <= h <= 23))


def toggle_hour(
    hour: int,
    date_str: str | None,
    charge: list[ScheduleSlot],
    discharge: list[ScheduleSlot],
    pv_charge: list[ScheduleSlot],
    blocked_charging: list[int],
    blocked_discharging: list[int],
) -> tuple[
    list[ScheduleSlot],
    list[ScheduleSlot],
    list[ScheduleSlot],
    list[int],
    list[int],
    bool,
]:
    """Cycle an hour through idle → charge → pv_charge → discharge → blocked → idle.

    Returns the new lists and a bool indicating whether the call was a
    no-op (invalid hour, invalid date) so the caller can skip the
    save-and-refresh side effects.
    """
    if hour < 0 or hour > 23:
        return charge, discharge, pv_charge, blocked_charging, blocked_discharging, True
    if date_str is None:
        date_str = today_str()
    if not valid_slot(date_str, hour):
        return charge, discharge, pv_charge, blocked_charging, blocked_discharging, True

    slot: ScheduleSlot = (date_str, hour)

    if slot in charge:
        # charge → pv_charge
        new_charge = [s for s in charge if s != slot]
        if slot not in pv_charge:
            new_pv_charge = sort_slots(pv_charge + [slot])
        else:
            new_pv_charge = pv_charge
        return new_charge, discharge, new_pv_charge, blocked_charging, blocked_discharging, False

    if slot in pv_charge:
        # pv_charge → discharge
        new_pv_charge = [s for s in pv_charge if s != slot]
        if slot not in discharge:
            new_discharge = sort_slots(discharge + [slot])
        else:
            new_discharge = discharge
        return charge, new_discharge, new_pv_charge, blocked_charging, blocked_discharging, False

    if slot in discharge:
        # discharge → blocked (both, recurring)
        new_discharge = [s for s in discharge if s != slot]
        new_blocked_charging = (
            sorted(blocked_charging + [hour]) if hour not in blocked_charging else blocked_charging
        )
        new_blocked_discharging = (
            sorted(blocked_discharging + [hour])
            if hour not in blocked_discharging
            else blocked_discharging
        )
        return charge, new_discharge, pv_charge, new_blocked_charging, new_blocked_discharging, False

    if hour in blocked_charging or hour in blocked_discharging:
        # blocked → idle
        new_blocked_charging = [h for h in blocked_charging if h != hour]
        new_blocked_discharging = [h for h in blocked_discharging if h != hour]
        return charge, discharge, pv_charge, new_blocked_charging, new_blocked_discharging, False

    # idle → charge
    return sort_slots(charge + [slot]), discharge, pv_charge, blocked_charging, blocked_discharging, False


def set_hour_action(
    hour: int,
    action: str,
    date_str: str | None,
    charge: list[ScheduleSlot],
    discharge: list[ScheduleSlot],
    pv_charge: list[ScheduleSlot],
    blocked_charging: list[int],
    blocked_discharging: list[int],
) -> tuple[
    list[ScheduleSlot],
    list[ScheduleSlot],
    list[ScheduleSlot],
    list[int],
    list[int],
    bool,
]:
    """Set a specific (date, hour) to one of the supported actions.

    The recurring ``blocked_charging_hours`` / ``blocked_discharging_hours``
    lists are preserved across non-BLOCKED actions so that a per-day
    override (e.g. picked from the plan card for a blocked bar) only
    applies to ``(date_str, hour)`` while the same hour on future days
    stays blocked. Returns the new lists and a no-op flag.
    """
    if hour < 0 or hour > 23:
        return charge, discharge, pv_charge, blocked_charging, blocked_discharging, True
    if date_str is None:
        date_str = today_str()
    if not valid_slot(date_str, hour):
        return charge, discharge, pv_charge, blocked_charging, blocked_discharging, True

    slot: ScheduleSlot = (date_str, hour)

    # Remove from date-specific lists.
    new_charge = [s for s in charge if s != slot]
    new_discharge = [s for s in discharge if s != slot]
    new_pv_charge = [s for s in pv_charge if s != slot]

    # Add to the right list.
    if action == ACTION_CHARGE:
        new_charge = sort_slots(new_charge + [slot])
    elif action == ACTION_PV_CHARGE:
        new_pv_charge = sort_slots(new_pv_charge + [slot])
    elif action == ACTION_DISCHARGE:
        new_discharge = sort_slots(new_discharge + [slot])
    elif action == ACTION_BLOCKED:
        if hour not in blocked_charging:
            blocked_charging = sorted(blocked_charging + [hour])
        if hour not in blocked_discharging:
            blocked_discharging = sorted(blocked_discharging + [hour])

    return new_charge, new_discharge, new_pv_charge, blocked_charging, blocked_discharging, False


def clear_all() -> tuple[
    list[ScheduleSlot],
    list[ScheduleSlot],
    list[ScheduleSlot],
    list[int],
    list[int],
]:
    """Return empty lists for every schedule slot and blocked hour bucket."""
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


def apply_fixed_plan(
    charge: list[ScheduleSlot],
    discharge: list[ScheduleSlot],
    pv_charge: list[ScheduleSlot],
    fixed_plan: dict[str, Any] | None,
    dates: list[str],
) -> tuple[list[ScheduleSlot], list[ScheduleSlot], list[ScheduleSlot], list[ScheduleSlot]]:
    """Merge fixed-plan hours on top of existing slot lists (fixed wins).

    A fixed plan holds recurring hour-of-day values per action bucket.
    Each bucket is expanded to ``(date, hour)`` slots for every date in
    ``dates`` and merged into the matching list, where the fixed plan
    wins: the hour is removed from the other two lists first (extend +
    overwrite semantics). When the same hour appears in several buckets
    of the fixed plan itself, precedence is pv_charge > charge >
    discharge (matching the plan display and decision engine).

    Returns ``(charge, discharge, pv_charge, applied)`` where ``applied``
    is the sorted list of every ``(date, hour)`` slot written by this
    call — the caller keeps it to retract the merge cleanly later.
    """
    normalized = normalize_fixed_plan(fixed_plan)

    # One action per hour within the plan: build an action map so later
    # (higher-precedence) buckets overwrite earlier ones.
    action_map: dict[ScheduleSlot, str] = {}
    for date_str in dates:
        for hour in normalized["discharge_hours"]:
            action_map[(date_str, hour)] = ACTION_DISCHARGE
        for hour in normalized["charge_hours"]:
            action_map[(date_str, hour)] = ACTION_CHARGE
        for hour in normalized["pv_charge_hours"]:
            action_map[(date_str, hour)] = ACTION_PV_CHARGE

    applied = sorted(action_map)
    applied_set = set(applied)
    expanded_charge = sorted(s for s, a in action_map.items() if a == ACTION_CHARGE)
    expanded_discharge = sorted(s for s, a in action_map.items() if a == ACTION_DISCHARGE)
    expanded_pv = sorted(s for s, a in action_map.items() if a == ACTION_PV_CHARGE)

    new_charge = sort_slots([s for s in charge if s not in applied_set] + expanded_charge)
    new_discharge = sort_slots([s for s in discharge if s not in applied_set] + expanded_discharge)
    new_pv_charge = sort_slots([s for s in pv_charge if s not in applied_set] + expanded_pv)
    return new_charge, new_discharge, new_pv_charge, applied


def _now() -> datetime:
    from homeassistant.util import dt as dt_util

    return dt_util.now()
