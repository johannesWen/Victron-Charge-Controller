"""Regression tests for SOC discharge stages and their device setpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    MODE_AUTO,
    MODE_FORCE_CHARGE,
    MODE_FORCE_DISCHARGE,
    MODE_MANUAL,
    MODE_OFF,
)
from custom_components.victron_charge_control.coordinator import ChargeControlData
from custom_components.victron_charge_control.sensor import SolarSurplusStatusSensor

from .conftest import MockConfigEntry, MockState


@pytest.fixture
def discharge_controller(coordinator):
    """A controller with independent SOC, surplus, and grid setpoint readings."""
    coordinator.control_mode = MODE_FORCE_DISCHARGE
    coordinator.min_soc = 20.0
    coordinator.soc_hysteresis = 2.0
    coordinator.discharge_power = 3000.0
    coordinator.idle_setpoint = 50.0
    coordinator._solar_surplus_entity = "sensor.solar_surplus"
    coordinator._solar_surplus_mean = 1500.0
    states = {
        coordinator.battery_soc_entity: MockState("25"),
        coordinator.grid_setpoint_entity: MockState("-4500"),
        "sensor.solar_surplus": MockState("1500"),
    }
    coordinator.hass.states.get.side_effect = states.get
    return coordinator, states


def set_soc(controller, states, soc):
    """Update just the SOC reading, leaving the other entities intact."""
    states[controller.battery_soc_entity] = MockState(str(soc))


@pytest.mark.parametrize("mode", [MODE_FORCE_DISCHARGE, MODE_AUTO, MODE_MANUAL])
def test_falling_and_rising_stages(discharge_controller, mode):
    controller, states = discharge_controller
    controller.control_mode = mode
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    controller._discharge_hours = [("2026-10-01", 12)]
    # Includes jitter, equality, and the same SOC reached in both directions.
    sequence = [
        (25, ACTION_DISCHARGE, -4500),
        (20.1, ACTION_DISCHARGE, -4500),
        (20, ACTION_DISCHARGE, -1500),
        (20.1, ACTION_DISCHARGE, -1500),
        (19, ACTION_DISCHARGE, -1500),
        (18, ACTION_IDLE, 50),
        (18.1, ACTION_IDLE, 50),
        (19.9, ACTION_IDLE, 50),
        (20, ACTION_DISCHARGE, -1500),
        (19.9, ACTION_DISCHARGE, -1500),
        (22, ACTION_DISCHARGE, -1500),
        (22.1, ACTION_DISCHARGE, -4500),
        (22, ACTION_DISCHARGE, -4500),
        (20, ACTION_DISCHARGE, -1500),
        (17, ACTION_IDLE, 50),
        (25, ACTION_DISCHARGE, -4500),
        (17, ACTION_IDLE, 50),
    ]
    with patch("custom_components.victron_charge_control.coordinator.dt_util.now", return_value=now):
        for soc, expected_action, expected_setpoint in sequence:
            set_soc(controller, states, soc)
            action = controller._determine_action()
            assert action == expected_action, soc
            assert controller._compute_setpoint(action) == expected_setpoint, soc


@pytest.mark.parametrize("has_solar", [True, False])
@pytest.mark.parametrize("soc", [0, 18, 19, 20, 21, 22, 22.1])
def test_conservative_startup(discharge_controller, has_solar, soc):
    controller, states = discharge_controller
    if not has_solar:
        controller._solar_surplus_entity = None
        controller._solar_surplus_mean = None
    set_soc(controller, states, soc)
    _, _, action, setpoint = controller._step_decide()
    if soc > 22:
        assert (action, setpoint) == (ACTION_DISCHARGE, -4500 if has_solar else -3000)
    elif has_solar and soc >= 20:
        assert (action, setpoint) == (ACTION_DISCHARGE, -1500)
    else:
        assert (action, setpoint) == (ACTION_IDLE, 50)


@pytest.mark.parametrize("has_solar", [True, False])
def test_zero_hysteresis_cutoff_wins(discharge_controller, has_solar):
    controller, states = discharge_controller
    controller.soc_hysteresis = 0
    if not has_solar:
        controller._solar_surplus_entity = None
    for soc, expected in [(20, ACTION_IDLE), (21, ACTION_DISCHARGE), (20, ACTION_IDLE), (19, ACTION_IDLE)]:
        set_soc(controller, states, soc)
        assert controller._determine_action() == expected


def test_lower_cutoff_clamped_to_zero(discharge_controller):
    controller, states = discharge_controller
    controller.min_soc = 1
    controller.soc_hysteresis = 2
    for soc, expected in [(4, ACTION_DISCHARGE), (1, ACTION_DISCHARGE), (0.1, ACTION_DISCHARGE), (0, ACTION_IDLE), (0.1, ACTION_IDLE), (1, ACTION_DISCHARGE)]:
        set_soc(controller, states, soc)
        assert controller._determine_action() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("has_solar", [True, False])
async def test_cutoff_immediate_and_recovery_confirmed(discharge_controller, has_solar):
    controller, states = discharge_controller
    if not has_solar:
        controller._solar_surplus_entity = None
        controller._solar_surplus_mean = None
    controller.setpoint_deadband = 10000
    start = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    with patch("custom_components.victron_charge_control.coordinator.dt_util.now") as now:
        now.return_value = start
        _, _, action, setpoint = controller._step_decide()
        assert action == ACTION_DISCHARGE
        controller._last_applied_setpoint = setpoint
        controller._pending_action = ACTION_DISCHARGE
        controller._pending_action_since = start
        set_soc(controller, states, 18 if has_solar else 20)
        now.return_value = start + timedelta(seconds=1)
        _, _, action, setpoint = controller._step_decide()
        assert (action, setpoint) == (ACTION_IDLE, 50)
        assert controller._pending_action is None
        assert controller._pending_action_since is None
        await controller._step_apply_setpoint(action, setpoint)
        controller.hass.services.async_call.assert_awaited_once_with(
            "number", "set_value",
            {"entity_id": controller.grid_setpoint_entity, "value": 50}, blocking=True,
        )
        set_soc(controller, states, 20 if has_solar else 22.1)
        now.return_value = start + timedelta(seconds=2)
        assert controller._step_decide()[2:] == (ACTION_IDLE, 50)
        now.return_value = start + timedelta(seconds=31)
        assert controller._step_decide()[2:] == (ACTION_IDLE, 50)
        now.return_value = start + timedelta(seconds=32)
        assert controller._step_decide()[2:] == (ACTION_DISCHARGE, -1500 if has_solar else -3000)


@pytest.mark.asyncio
async def test_solar_only_reduction_bypasses_deadband_and_retries(discharge_controller):
    controller, states = discharge_controller
    controller.discharge_power = 100
    controller.setpoint_deadband = 200
    controller._step_decide()
    controller._last_applied_setpoint = -1600
    states[controller.grid_setpoint_entity] = MockState("-1600")
    set_soc(controller, states, 20)
    _, _, action, setpoint = controller._step_decide()
    assert (action, setpoint) == (ACTION_DISCHARGE, -1500)
    # An unavailable device must not consume the protective reduction.
    states[controller.grid_setpoint_entity] = MockState("unavailable")
    await controller._step_apply_setpoint(action, setpoint)
    controller.hass.services.async_call.assert_not_awaited()
    states[controller.grid_setpoint_entity] = MockState("-1600")
    await controller._step_apply_setpoint(action, setpoint)
    controller.hass.services.async_call.assert_awaited_once_with(
        "number", "set_value",
        {"entity_id": controller.grid_setpoint_entity, "value": -1500}, blocking=True,
    )
    states[controller.grid_setpoint_entity] = MockState("-1500")
    await controller._step_apply_setpoint(action, setpoint)
    assert controller.hass.services.async_call.await_count == 1


def test_disabled_or_unscheduled_discharge_stays_idle(discharge_controller):
    controller, states = discharge_controller
    controller.discharge_allowed = False
    assert controller._determine_action() == ACTION_IDLE
    controller.discharge_allowed = True
    controller.control_mode = MODE_AUTO
    assert controller._determine_action() == ACTION_IDLE
    controller.control_mode = MODE_OFF
    assert controller._determine_action() == ACTION_IDLE


def test_lower_soc_protection_does_not_block_charging(discharge_controller):
    controller, states = discharge_controller
    controller.control_mode = MODE_FORCE_CHARGE
    set_soc(controller, states, 17)
    assert controller._step_decide()[2:] == (ACTION_CHARGE, controller.charge_power)


def test_pending_discharge_cannot_survive_cutoff(discharge_controller):
    controller, states = discharge_controller
    controller._last_published_action = ACTION_IDLE
    controller._pending_action = ACTION_DISCHARGE
    controller._pending_action_since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    set_soc(controller, states, 18)
    assert controller._step_decide()[2:] == (ACTION_IDLE, 50)
    assert controller._pending_action is None


@pytest.mark.parametrize("surplus", [None, 0, 1500])
@pytest.mark.parametrize("reduced", [False, True])
def test_solar_only_setpoint_respects_surplus_and_limits(discharge_controller, surplus, reduced):
    controller, states = discharge_controller
    controller._solar_surplus_mean = surplus
    controller.min_grid_setpoint = -1000
    controller.reduced_max_grid_feed_in = 500
    set_soc(controller, states, 20)
    action = controller._determine_action()
    assert action == ACTION_DISCHARGE
    expected = -min(surplus or 0, 500 if reduced else 1000)
    assert controller._compute_setpoint(action, is_reduced=reduced) == expected


@pytest.mark.asyncio
async def test_blocked_stage_is_published_in_snapshot(discharge_controller):
    controller, states = discharge_controller
    set_soc(controller, states, 18)
    data = await controller._async_update_data()
    assert data.desired_action == ACTION_IDLE
    assert data.target_setpoint == 50
    assert data.discharge_blocked_by_soc is True


@pytest.mark.parametrize("blocked, solar_only, expected", [
    (True, True, "blocked"), (False, True, "solar_only"), (False, False, "normal"),
])
def test_status_sensor_reports_discharge_stage(coordinator, blocked, solar_only, expected):
    coordinator.data = ChargeControlData(
        discharge_blocked_by_soc=blocked, discharge_solar_only=solar_only,
    )
    sensor = SolarSurplusStatusSensor(coordinator, MockConfigEntry())
    sensor.async_write_ha_state = MagicMock()
    assert sensor.native_value == expected
    sensor._handle_coordinator_update()
    assert sensor._attr_native_value == expected
