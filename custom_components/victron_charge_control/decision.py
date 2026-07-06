"""Decision engine helpers.

Extracted from ``coordinator.py``. The helpers are pure functions
that take the relevant state and return the new state — the
coordinator's private methods stay as thin wrappers that apply the
returned values back to the coordinator instance, which keeps the
public/test surface (e.g. ``_determine_action()``, ``_charge_blocked_by_soc``)
identical to before the refactor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    MODE_AUTO,
    MODE_FORCE_CHARGE,
    MODE_FORCE_DISCHARGE,
    MODE_MANUAL,
    MODE_OFF,
)
from .epex import get_battery_soc
from .schedule import ScheduleSlot


@dataclass
class SocHysteresisState:
    """Latched SOC blocking flags updated by ``update_soc_hysteresis``."""

    charge_blocked_by_soc: bool
    discharge_blocked_by_soc: bool
    discharge_solar_only: bool


def update_soc_hysteresis(
    soc: float,
    *,
    max_soc: float,
    min_soc: float,
    hysteresis: float,
    state: SocHysteresisState,
) -> SocHysteresisState:
    """Update SOC hysteresis blocked flags (Schmitt-trigger style).

    All three flags are latched: once a limit is reached the flag stays
    set until the SOC moves a full ``hysteresis`` margin *back* across
    the threshold. This prevents ±1% sensor jitter near the SOC
    boundaries from flapping the desired action and grid setpoint.
    """
    if soc >= max_soc:
        charge_blocked = True
    elif soc < max_soc - hysteresis:
        charge_blocked = False
    else:
        charge_blocked = state.charge_blocked_by_soc

    if soc <= min_soc:
        discharge_blocked = True
    elif soc > min_soc + hysteresis:
        discharge_blocked = False
    else:
        discharge_blocked = state.discharge_blocked_by_soc

    if soc <= min_soc + hysteresis:
        discharge_solar_only = True
    elif soc > min_soc + (2 * hysteresis):
        discharge_solar_only = False
    else:
        discharge_solar_only = state.discharge_solar_only

    return SocHysteresisState(
        charge_blocked_by_soc=charge_blocked,
        discharge_blocked_by_soc=discharge_blocked,
        discharge_solar_only=discharge_solar_only,
    )


@dataclass
class DecisionState:
    """Inputs the decision engine needs to pick an action."""

    control_mode: str
    charge_allowed: bool
    discharge_allowed: bool
    max_soc: float
    min_soc: float
    soc_hysteresis: float
    charge_hours: list[ScheduleSlot]
    discharge_hours: list[ScheduleSlot]
    pv_charge_hours: list[ScheduleSlot]
    solar_surplus_entity: str | None


@dataclass
class DecisionResult:
    """Output of the decision engine: the chosen action + SOC latch state."""

    action: str
    soc_state: SocHysteresisState


def determine_action(
    *,
    state: DecisionState,
    soc_state: SocHysteresisState,
    hass: Any,
    battery_soc_entity: str,
    now: datetime,
) -> DecisionResult:
    """Deterministic priority stack — returns charge/discharge/idle/pv_charge/idle.

    See the inline docstring on the coordinator for the full priority
    list and the rationale for the per-priority block (especially the
    PV-Charge override and the per-day charge slot for blocked hours).

    ``soc_state`` is the latched SOC blocking state from the previous
    call — the priority stack may update it (via ``update_soc_hysteresis``)
    or preserve it (when the system is OFF or the SOC is unavailable).
    """

    # Priority 1: System off
    if state.control_mode == MODE_OFF:
        return DecisionResult(action=ACTION_IDLE, soc_state=soc_state)

    # Priority 2: SOC unavailable
    soc = get_battery_soc(hass, battery_soc_entity)
    if soc is None:
        return DecisionResult(action=ACTION_IDLE, soc_state=soc_state)

    soc_state = update_soc_hysteresis(
        soc,
        max_soc=state.max_soc,
        min_soc=state.min_soc,
        hysteresis=state.soc_hysteresis,
        state=soc_state,
    )

    # Priority 3: Force modes
    if state.control_mode == MODE_FORCE_CHARGE:
        if state.charge_allowed and not soc_state.charge_blocked_by_soc:
            return DecisionResult(action=ACTION_CHARGE, soc_state=soc_state)
        return DecisionResult(action=ACTION_IDLE, soc_state=soc_state)

    if state.control_mode == MODE_FORCE_DISCHARGE:
        if state.discharge_allowed and not soc_state.discharge_blocked_by_soc:
            return DecisionResult(action=ACTION_DISCHARGE, soc_state=soc_state)
        return DecisionResult(action=ACTION_IDLE, soc_state=soc_state)

    # Priority 4: Blocked hours — override schedule per action type
    if state.control_mode in (MODE_AUTO, MODE_MANUAL):
        current_date = now.strftime("%Y-%m-%d")
        hour = now.hour
        current_slot: ScheduleSlot = (current_date, hour)

        # PV charging takes precedence over plain charge/discharge so a
        # manually-set PV slot is honored even when the auto scheduler
        # also marked the hour. Requires the optional solar surplus
        # sensor; otherwise the slot falls back to idle. PV charging is
        # independent of `charge_allowed` and `blocked_charging_hours`
        # because it never draws from the grid — it only splits the
        # existing solar surplus between battery and grid export. SOC
        # blocking still applies.
        if (
            current_slot in state.pv_charge_hours
            and not soc_state.charge_blocked_by_soc
            and state.solar_surplus_entity is not None
        ):
            return DecisionResult(action=ACTION_PV_CHARGE, soc_state=soc_state)

        # A per-day charge slot for a blocked hour is a user override
        # (set_hour_action leaves blocked_charging_hours intact and the
        # auto-scheduler skips blocked hours, so the slot can only have
        # been placed explicitly). Honor it.
        if (
            current_slot in state.charge_hours
            and state.charge_allowed
            and not soc_state.charge_blocked_by_soc
        ):
            return DecisionResult(action=ACTION_CHARGE, soc_state=soc_state)

        if (
            current_slot in state.discharge_hours
            and state.discharge_allowed
            and not soc_state.discharge_blocked_by_soc
        ):
            return DecisionResult(action=ACTION_DISCHARGE, soc_state=soc_state)

        return DecisionResult(action=ACTION_IDLE, soc_state=soc_state)

    # Priority 5: Fallback
    return DecisionResult(action=ACTION_IDLE, soc_state=soc_state)


@dataclass
class DebounceState:
    """Latched state of the action-change debounce."""

    last_published_action: str | None
    pending_action: str | None
    pending_action_since: datetime | None


@dataclass
class DebounceResult:
    """Output of the action debounce."""

    published_action: str
    state: DebounceState


def resolve_published_action(
    live_action: str,
    *,
    control_mode: str,
    action_confirm_seconds: float,
    state: DebounceState,
    now: datetime,
) -> DebounceResult:
    """Apply the action-change debounce to a live decision-engine result.

    A new ``live_action`` must persist for ``action_confirm_seconds``
    before it replaces the currently published one. MODE_OFF bypasses
    the debounce and forces ``ACTION_IDLE`` immediately. The first ever
    call also publishes immediately (no prior state to confirm against).
    """
    if control_mode == MODE_OFF:
        return DebounceResult(
            published_action=ACTION_IDLE,
            state=DebounceState(
                last_published_action=ACTION_IDLE,
                pending_action=None,
                pending_action_since=None,
            ),
        )

    if state.last_published_action is None:
        return DebounceResult(
            published_action=live_action,
            state=DebounceState(
                last_published_action=live_action,
                pending_action=None,
                pending_action_since=None,
            ),
        )

    if live_action == state.last_published_action:
        return DebounceResult(
            published_action=state.last_published_action,
            state=DebounceState(
                last_published_action=state.last_published_action,
                pending_action=None,
                pending_action_since=None,
            ),
        )

    if state.pending_action != live_action:
        return DebounceResult(
            published_action=state.last_published_action,
            state=DebounceState(
                last_published_action=state.last_published_action,
                pending_action=live_action,
                pending_action_since=now,
            ),
        )

    elapsed = (now - state.pending_action_since).total_seconds()
    if elapsed >= action_confirm_seconds:
        return DebounceResult(
            published_action=live_action,
            state=DebounceState(
                last_published_action=live_action,
                pending_action=None,
                pending_action_since=None,
            ),
        )

    return DebounceResult(
        published_action=state.last_published_action,
        state=state,
    )


def compute_setpoint(
    action: str,
    *,
    is_reduced: bool = False,
    charge_power: float,
    discharge_power: float,
    idle_setpoint: float,
    min_grid_setpoint: float,
    max_grid_setpoint: float,
    charge_blocked_by_soc: bool,
    discharge_solar_only: bool,
    solar_surplus_mean: float | None,
    pv_charge_share: float,
    reduced_max_grid_feed_in: float,
) -> float:
    """Compute the clamped grid setpoint for the given action.

    ``is_reduced`` is True when the reduced grid feed-in mode is active.
    In that case the PV-Charge and Discharge setpoints are clamped on
    the export side so the integration never asks the ESS to feed more
    into the grid than the active feed-in limit allows.
    """
    if action == ACTION_CHARGE:
        raw = charge_power
    elif action == ACTION_PV_CHARGE:
        if charge_blocked_by_soc:
            raw = idle_setpoint
        else:
            surplus = solar_surplus_mean or 0.0
            f = max(0.0, min(1.0, pv_charge_share / 100.0))
            raw = (1.0 - f) * (-surplus) + f * idle_setpoint
        if is_reduced:
            raw = max(raw, -reduced_max_grid_feed_in)
    elif action == ACTION_DISCHARGE:
        surplus = solar_surplus_mean or 0.0
        if discharge_solar_only:
            raw = -surplus
        else:
            raw = -(discharge_power + surplus)
        if is_reduced:
            raw = max(raw, -reduced_max_grid_feed_in)
    else:
        raw = idle_setpoint

    return max(min_grid_setpoint, min(raw, max_grid_setpoint))
