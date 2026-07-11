"""Actuation helpers — write to number entities and compute feed-in mode.

Extracted from ``coordinator.py``. The helpers do the actual
``hass.services.async_call`` work and return the new state to apply
to the coordinator's private attributes (``_last_applied_setpoint``,
``_last_applied_feed_in``).
"""

from __future__ import annotations

import logging
from typing import Any

from .const import ACTION_IDLE, DEFAULT_DEADBAND, MODE_OFF

_LOGGER = logging.getLogger(__name__)


def is_reduced_feed_in_mode(
    *,
    grid_feed_in_control_enabled: bool,
    current_price: float | None,
    grid_feed_in_price_threshold: float,
) -> bool:
    """Return whether the reduced grid feed-in mode should be active.

    Used by both ``_compute_setpoint`` (to clamp the export side of the
    PV-Charge and Discharge setpoints) and ``_apply_grid_feed_in`` (to
    decide which limit to push to the ESS). The two paths must agree
    so the setpoint and the ESS feed-in limit never contradict each
    other.
    """
    if not grid_feed_in_control_enabled:
        return False
    if current_price is None:
        return False
    return current_price < grid_feed_in_price_threshold


async def apply_setpoint(
    hass: Any,
    *,
    entity_id: str,
    target_setpoint: float,
    action: str | None,
    last_applied_setpoint: float | None,
    setpoint_deadband: float,
    on_log: Any = None,
) -> float | None:
    """Write the target setpoint to the grid setpoint entity.

    Returns the new ``last_applied_setpoint`` (equal to the input when
    the call was skipped, or ``target_setpoint`` after a successful
    write).
    """
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        _LOGGER.warning(
            "Grid setpoint entity %s is unavailable — skipping actuation",
            entity_id,
        )
        return last_applied_setpoint

    try:
        current = float(state.state)
    except (ValueError, TypeError):
        current = 0.0

    if (
        action != ACTION_IDLE
        and last_applied_setpoint is not None
        and abs(target_setpoint - current) <= setpoint_deadband
    ):
        return last_applied_setpoint

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": target_setpoint},
        blocking=True,
    )
    if on_log is not None:
        on_log(current, target_setpoint)
    return target_setpoint


async def apply_grid_feed_in(
    hass: Any,
    *,
    entity_id: str,
    grid_feed_in_control_enabled: bool,
    current_price: float | None,
    default_max_grid_feed_in: float,
    reduced_max_grid_feed_in: float,
    grid_feed_in_price_threshold: float,
    last_applied_feed_in: float | None,
) -> tuple[bool, float | None, float | None]:
    """Control the ESS max grid feed-in based on spot price.

    Returns ``(is_reduced, applied_value, new_last_applied_feed_in)``.
    """
    is_reduced = is_reduced_feed_in_mode(
        grid_feed_in_control_enabled=grid_feed_in_control_enabled,
        current_price=current_price,
        grid_feed_in_price_threshold=grid_feed_in_price_threshold,
    )

    if not grid_feed_in_control_enabled:
        # Reset to default when feature is disabled
        if (
            last_applied_feed_in is not None
            and last_applied_feed_in != default_max_grid_feed_in
        ):
            state = hass.states.get(entity_id)
            if state is not None and state.state not in ("unavailable", "unknown"):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": entity_id,
                        "value": default_max_grid_feed_in,
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "Grid feed-in control disabled — reset to default %.0fW",
                    default_max_grid_feed_in,
                )
            return is_reduced, None, None
        return False, None, last_applied_feed_in

    if current_price is None:
        _LOGGER.debug("No current price available — skipping grid feed-in control")
        return False, None, last_applied_feed_in

    target_feed_in = (
        reduced_max_grid_feed_in if is_reduced else default_max_grid_feed_in
    )

    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        _LOGGER.warning(
            "Max grid feed-in entity %s is unavailable — skipping",
            entity_id,
        )
        return is_reduced, None, last_applied_feed_in

    try:
        current_val = float(state.state)
    except (ValueError, TypeError):
        current_val = 0.0

    if (
        last_applied_feed_in is not None
        and abs(target_feed_in - current_val) <= DEFAULT_DEADBAND
    ):
        return is_reduced, target_feed_in, last_applied_feed_in

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": target_feed_in},
        blocking=True,
    )
    _LOGGER.info(
        "Grid feed-in: %.0fW → %.0fW (price=%.2f ct/kWh, threshold=%.2f ct/kWh)",
        current_val,
        target_feed_in,
        current_price,
        grid_feed_in_price_threshold,
    )
    return is_reduced, target_feed_in, target_feed_in


async def apply_dc_coupled_feed_in(
    hass: Any,
    *,
    entity_id: str | None,
    control_dc_coupled_feed_in: bool,
    grid_feed_in_control_enabled: bool,
    control_mode: str,
    is_reduced: bool,
    last_applied_state: bool | None,
) -> bool | None:
    """Drive the linked external DC-coupled PV feed-in switch.

    Returns the new ``last_applied_state`` (``True`` = ON, ``False`` = OFF,
    ``None`` = never written).

    The switch is **inert** (left untouched, no service call) when any of
    the following holds:

    * the "Control DC Coupled Feed In" integration switch is off,
    * the existing ``grid_feed_in_control_enabled`` switch is off (the
      reduced mode predicate is never true in that case, so the feature
      has no opinion),
    * the integration ``control_mode`` is ``OFF`` (the whole ESS is
      idle — suspend the feature entirely),
    * no linked external switch entity is configured, or
    * the linked entity is currently ``unavailable``/``unknown``.

    Otherwise, in normal mode (price >= threshold) the linked switch is
    turned **ON** (DC feed-in enabled); in reduced mode (price <
    threshold) it is turned **OFF** (DC feed-in disabled). A
    ``last_applied_state`` guard avoids redundant ``switch.turn_on``/
    ``switch.turn_off`` calls on every 60s tick.
    """
    if (
        not control_dc_coupled_feed_in
        or not grid_feed_in_control_enabled
        or control_mode == MODE_OFF
        or not entity_id
    ):
        return last_applied_state

    desired_on = not is_reduced  # normal → ON ; reduced → OFF
    if last_applied_state is not None and desired_on == last_applied_state:
        return last_applied_state

    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        _LOGGER.warning(
            "DC coupled PV feed-in switch %s is unavailable — skipping",
            entity_id,
        )
        return last_applied_state

    service = "turn_on" if desired_on else "turn_off"
    await hass.services.async_call(
        "switch",
        service,
        {"entity_id": entity_id},
        blocking=True,
    )
    _LOGGER.info(
        "DC coupled PV feed-in %s → %s (reduced=%s)",
        entity_id,
        "ON" if desired_on else "OFF",
        is_reduced,
    )
    return desired_on
