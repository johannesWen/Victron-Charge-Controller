"""Consumer offset configuration, controls, and fixed-deadline batching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    CONF_GRID_CONSUMER_ENTITY,
    MODE_AUTO,
    MODE_FORCE_CHARGE,
    MODE_FORCE_DISCHARGE,
    MODE_MANUAL,
    MODE_OFF,
)
from custom_components.victron_charge_control.coordinator import (
    VictronChargeControlCoordinator,
)
from custom_components.victron_charge_control.sensor import TargetSetpointSensor
from custom_components.victron_charge_control.switch import SWITCHES, VictronCCSwitch

from .conftest import MOCK_CONFIG_DATA, MockConfigEntry, MockState


@dataclass
class Timer:
    when: float
    callback: object
    args: tuple
    cancelled: bool = False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback(*self.args)


class Clock:
    """Drive HA's native async_call_later through a controllable loop clock."""

    def __init__(self, hass):
        self.hass = hass
        self.now = 0.0
        self.timers = []
        hass.loop.time.side_effect = lambda: self.now
        hass.loop.call_at.side_effect = self.call_at
        hass.async_run_hass_job.side_effect = lambda job, *args: job.target(*args)

    def call_at(self, when, callback, *args):
        timer = Timer(when, callback, args)
        self.timers.append(timer)
        return timer

    @property
    def pending(self):
        return [timer for timer in self.timers if not timer.cancelled]

    async def drain(self):
        while tasks := [task for task in self.hass._scheduled_tasks if not task.done()]:
            await asyncio.gather(*tasks)

    async def advance(self, seconds, *, drain=True):
        deadline = self.now + seconds
        while due := [timer for timer in self.pending if timer.when <= deadline]:
            timer = min(due, key=lambda item: item.when)
            self.now = timer.when
            timer.cancel()
            timer.fire()
            if drain:
                await self.drain()
        self.now = deadline


@pytest.fixture
async def consumer(mock_hass):
    """Use real control/actuation logic with fake source states and clock I/O."""
    states = {
        "sensor.battery_soc": MockState("50"),
        "number.grid_setpoint": MockState("0"),
        "sensor.epex_spot": MockState("5", {"unit_of_measurement": "ct/kWh"}),
        "number.max_grid_feed_in": MockState("15000"),
        "sensor.consumer": MockState("750", {"unit_of_measurement": "W"}),
    }
    mock_hass.states.get.side_effect = states.get

    async def write(domain, service, data, **kwargs):
        if domain == "number":
            states[data["entity_id"]] = MockState(str(data["value"]))

    mock_hass.services.async_call.side_effect = write
    entry = MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_GRID_CONSUMER_ENTITY: "sensor.consumer"})
    coord = VictronChargeControlCoordinator(mock_hass, entry)
    clock = Clock(mock_hass)
    subscriptions = []

    def subscribe(hass, entities, callback):
        listener = [entities, callback, True]
        subscriptions.append(listener)
        return lambda: listener.__setitem__(2, False)

    def change(value, unit="W", *, source="sensor.consumer", notify=True):
        states[source] = None if value is None else MockState(value, {"unit_of_measurement": unit})
        if notify:
            for entities, callback, active in subscriptions:
                if active and source in entities:
                    callback(None)

    async def refresh():
        coord.data = await coord._async_update_data()
        coord.async_update_listeners()

    coord.async_request_refresh = AsyncMock(side_effect=refresh)
    coord.control_mode = MODE_FORCE_CHARGE
    desc = next(item for item in SWITCHES if item.key == "grid_consumer_enabled")
    switch = VictronCCSwitch(coord, entry, desc)
    switch.async_write_ha_state = MagicMock()
    with (
        patch("custom_components.victron_charge_control.coordinator.async_track_state_change_event", side_effect=subscribe),
        patch("custom_components.victron_charge_control.coordinator.async_track_time_change"),
    ):
        await coord.async_setup()
        yield coord, switch, clock, change, states
        await coord.async_shutdown()
        await clock.drain()


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("123.5", "W", 123.5), ("1.25", "kW", 1250),
        ("-100", "W", 0), ("-0.25", "kW", 0), ("0", "W", 0),
        (None, "W", None), ("unavailable", "W", None), ("unknown", "W", None),
        ("bad", "W", None), ("NaN", "W", None), ("inf", "W", None),
        ("-inf", "W", None), ("1e309", "W", None),
        ("1e308", "kW", None), ("-1e308", "kW", None),
        ("100", None, None), ("100", "", None), ("100", "MW", None),
        ("100", "kWh", None),
    ],
)
async def test_power_normalization(consumer, value, unit, expected):
    coord, switch, clock, change, _ = consumer
    change(value, unit)
    assert switch.extra_state_attributes == {
        "source_entity": "sensor.consumer", "power_w": expected, "offset_w": 0,
    }
    assert switch.available
    await switch.async_turn_on()
    await clock.advance(5)
    assert coord.grid_consumer_offset == (expected or 0)
    assert coord.control_mode == MODE_FORCE_CHARGE


async def test_switch_default_availability_and_missing_source(consumer):
    coord, switch, _, _, _ = consumer
    assert not switch.is_on
    assert switch.available
    coord.update_entity_references(MOCK_CONFIG_DATA)
    assert not switch.available
    assert switch.extra_state_attributes == {"source_entity": None, "power_w": None, "offset_w": 0}
    with pytest.raises(ServiceValidationError, match="power sensor"):
        await switch.async_turn_on()
    assert not switch.is_on


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize("restored", ["on", "off", "unavailable"])
async def test_switch_restore_starts_from_zero(consumer, configured, restored):
    coord, switch, clock, _, _ = consumer
    if not configured:
        coord.update_entity_references(MOCK_CONFIG_DATA)
    switch.async_get_last_state = AsyncMock(return_value=MockState(restored))
    with patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock()):
        await switch.async_added_to_hass()
    assert switch.is_on == (configured and restored == "on")
    assert coord.grid_consumer_offset == 0
    await clock.advance(4.99)
    assert coord.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert coord.grid_consumer_offset == (750 if configured and restored == "on" else 0)


async def test_burst_uses_first_deadline_and_latest_value(consumer):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    first = clock.pending[0]
    await clock.advance(2)
    change("1.2", "kW")
    await clock.advance(2.9)
    change("900")
    assert clock.pending == [first]
    assert coord.grid_consumer_offset == 0
    assert coord.data.target_setpoint == coord.charge_power
    await clock.advance(0.1)
    assert coord.grid_consumer_offset == 900
    assert coord.data.target_setpoint == coord.charge_power + 900
    sensor = TargetSetpointSensor(coord, MockConfigEntry())
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_coordinator_update()
    assert sensor.native_value == coord.charge_power + 900


async def test_continuous_noise_does_not_starve_timer(consumer):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    for second in range(1, 21):
        change(str(100 * second))
        await clock.advance(1)
        assert coord.grid_consumer_offset == (second // 5) * 500


async def test_expiry_rereads_source_without_an_event(consumer):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    change("1250", notify=False)
    await clock.advance(5)
    assert coord.data.target_setpoint == coord.charge_power + 1250
    change("1500")
    change("unavailable", notify=False)
    await clock.advance(5)
    assert coord.grid_consumer_offset == 0
    assert coord.data.target_setpoint == coord.charge_power


@pytest.mark.parametrize("operation", ["disable", "off", "remove", "replace", "invalid", "unload"])
@pytest.mark.parametrize("accepted", [False, True])
async def test_cancellation_cannot_resurrect_an_offset(consumer, operation, accepted):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    if accepted:
        await clock.advance(5)
        change("1000")
    stale = clock.pending[0]
    if operation == "disable":
        await switch.async_turn_off()
    elif operation == "off":
        coord.control_mode = MODE_OFF
        await coord.async_request_refresh()
    elif operation == "remove":
        coord.update_entity_references(MOCK_CONFIG_DATA)
        assert not switch.is_on
    elif operation == "replace":
        change("300", source="sensor.replacement")
        coord.update_entity_references({**MOCK_CONFIG_DATA, CONF_GRID_CONSUMER_ENTITY: "sensor.replacement"})
    elif operation == "invalid":
        change("unavailable")
        assert switch.is_on and switch.available
    else:
        await coord.async_shutdown()
    assert coord.grid_consumer_offset == 0
    assert stale.cancelled
    stale.fire()  # An already queued callback must also be harmless.
    await clock.drain()
    assert coord.grid_consumer_offset == 0
    await clock.advance(5)
    assert coord.grid_consumer_offset == (300 if operation == "replace" else 0)
    if operation == "off":
        assert coord._last_applied_setpoint == coord.idle_setpoint


@pytest.mark.parametrize("operation", ["disable", "off", "invalid"])
async def test_recovery_batches_from_zero(consumer, operation):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    await clock.advance(5)
    if operation == "disable":
        await switch.async_turn_off()
        await switch.async_turn_on()
    elif operation == "off":
        coord.control_mode = MODE_OFF
        coord.control_mode = MODE_FORCE_CHARGE
        await coord.async_request_refresh()
    else:
        change("unavailable")
        change("750")
    await clock.drain()
    assert coord.grid_consumer_offset == 0
    assert coord.data.target_setpoint == coord.charge_power
    await clock.advance(4.99)
    assert coord.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert coord.grid_consumer_offset == 750


@pytest.mark.parametrize("mode", [MODE_AUTO, MODE_MANUAL, MODE_FORCE_CHARGE, MODE_FORCE_DISCHARGE])
async def test_all_active_modes_add_offset_without_changing_action(consumer, mode):
    coord, switch, clock, _, _ = consumer
    coord.control_mode = mode
    coord._last_published_action = None
    await coord.async_request_refresh()
    previous_action = coord.data.desired_action
    base_target = coord.data.target_setpoint
    await switch.async_turn_on()
    await clock.advance(5)
    assert coord.data.desired_action == previous_action
    assert coord.data.target_setpoint == base_target + 750


@pytest.mark.parametrize(
    ("action", "reduced", "minimum", "maximum", "expected"),
    [
        (ACTION_CHARGE, False, -10000, 10000, 3750),
        (ACTION_IDLE, False, -10000, 10000, 750),
        (ACTION_DISCHARGE, False, -10000, 10000, -4250),
        (ACTION_PV_CHARGE, False, -10000, 10000, -250),
        (ACTION_DISCHARGE, True, -10000, 10000, -500),
        (ACTION_PV_CHARGE, True, -10000, 10000, -250),
        (ACTION_DISCHARGE, False, -500, 10000, -500),
        (ACTION_CHARGE, False, -10000, 3200, 3200),
    ],
)
async def test_offset_precedes_reduced_and_final_limits(consumer, action, reduced, minimum, maximum, expected):
    coord, switch, clock, _, _ = consumer
    await switch.async_turn_on()
    await clock.advance(5)
    coord.charge_power = 3000
    coord.discharge_power = 3000
    coord.idle_setpoint = 0
    coord._solar_surplus_mean = 2000
    coord.pv_charge_share = 50
    coord.reduced_max_grid_feed_in = 500
    coord.min_grid_setpoint = minimum
    coord.max_grid_setpoint = maximum
    assert coord._compute_setpoint(action, is_reduced=reduced) == expected


async def test_safety_action_change_during_batch_is_immediate(consumer):
    coord, switch, clock, _, states = consumer
    coord.control_mode = MODE_FORCE_DISCHARGE
    coord._last_published_action = None
    await switch.async_turn_on()
    states["sensor.battery_soc"] = MockState("0")
    await coord.async_request_refresh()
    assert coord.data.desired_action == ACTION_IDLE
    assert coord.data.target_setpoint == coord.idle_setpoint
    assert coord._discharge_blocked_by_soc
    await clock.advance(5)
    assert coord.data.desired_action == ACTION_IDLE
    assert coord.data.target_setpoint == coord.idle_setpoint + 750


@pytest.mark.parametrize("action", [MODE_FORCE_CHARGE, MODE_FORCE_DISCHARGE])
@pytest.mark.parametrize("failure", [None, "unavailable", "service_error"])
async def test_clearing_bypasses_deadband_and_retries(consumer, action, failure):
    coord, switch, clock, change, states = consumer
    coord.control_mode = action
    coord._last_published_action = None
    coord.setpoint_deadband = 10
    change("50")
    await switch.async_turn_on()
    await clock.advance(5)
    previous = coord._last_applied_setpoint
    coord.setpoint_deadband = 200
    service = coord.hass.services.async_call
    successful_write = service.side_effect
    if failure == "unavailable":
        states["number.grid_setpoint"] = MockState("unavailable")
        # Test retry without changing the watchdog's existing startup policy.
        coord._safety_startup_deadline = None
    elif failure == "service_error":
        service.side_effect = HomeAssistantError("device rejected write")
    if failure == "service_error":
        with pytest.raises(HomeAssistantError):
            await switch.async_turn_off()
    else:
        await switch.async_turn_off()
    assert coord.grid_consumer_offset == 0
    if failure:
        states["number.grid_setpoint"] = MockState(str(previous))
        service.side_effect = successful_write
        coord.control_mode = action
        coord._last_published_action = None
        await coord.async_request_refresh()
    assert coord._last_applied_setpoint == previous - 50
    assert float(states["number.grid_setpoint"].state) == previous - 50


async def test_ordinary_offset_changes_obey_deadband(consumer):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    await clock.advance(5)
    previous = coord._last_applied_setpoint
    coord.setpoint_deadband = 200
    change("800")
    await clock.advance(5)
    assert coord.data.target_setpoint == coord.charge_power + 800
    assert coord._last_applied_setpoint == previous


@pytest.mark.parametrize("operation", ["disable", "invalid", "remove", "replace"])
async def test_explicit_clear_removes_residual_after_accepted_zero(consumer, operation):
    coord, switch, clock, change, states = consumer
    coord.setpoint_deadband = 0
    change("150")
    await switch.async_turn_on()
    await clock.advance(5)
    coord.setpoint_deadband = 200
    change("0")
    await clock.advance(5)
    assert coord.grid_consumer_offset == 0
    assert float(states["number.grid_setpoint"].state) == coord.charge_power + 150
    if operation == "disable":
        await switch.async_turn_off()
    elif operation == "invalid":
        change("unavailable")
    elif operation == "remove":
        coord.update_entity_references(MOCK_CONFIG_DATA)
    else:
        change("50", source="sensor.replacement")
        coord.update_entity_references({**MOCK_CONFIG_DATA, CONF_GRID_CONSUMER_ENTITY: "sensor.replacement"})
    await clock.drain()
    assert float(states["number.grid_setpoint"].state) == coord.charge_power
    assert not coord._grid_consumer_clear_pending
    coord.hass.services.async_call.reset_mock()
    await coord.async_request_refresh()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.parametrize("operation", ["disable", "invalid", "unload"])
async def test_clear_during_awaited_write_cannot_leave_stale_target(consumer, operation):
    coord, switch, clock, change, states = consumer
    coord.setpoint_deadband = 0
    change("50")
    await switch.async_turn_on()
    await clock.advance(5)
    previous = coord._last_applied_setpoint
    started, release = asyncio.Event(), asyncio.Event()
    service = coord.hass.services.async_call
    successful_write = service.side_effect

    async def delayed_write(*args, **kwargs):
        if not started.is_set():
            started.set()
            await release.wait()
        await successful_write(*args, **kwargs)

    service.side_effect = delayed_write
    coord._last_applied_setpoint = None
    updating = asyncio.create_task(coord.async_request_refresh())
    await started.wait()
    coord.setpoint_deadband = 200
    if operation == "disable":
        coord.grid_consumer_enabled = False
    elif operation == "invalid":
        change("unavailable", notify=False)
        # The source listener clears synchronously, before its requested refresh runs.
        coord._sample_grid_consumer()
    else:
        await coord.async_shutdown()
    writes_before_resume = service.call_count
    release.set()
    await updating
    assert coord.grid_consumer_offset == 0
    if operation == "unload":
        assert service.call_count == writes_before_resume
    else:
        assert float(states["number.grid_setpoint"].state) == previous - 50
        assert coord.data.target_setpoint == previous - 50


@pytest.mark.parametrize("operation", ["disable", "unload"])
async def test_queued_refresh_after_expiry_cannot_restore_cleared_offset(consumer, operation):
    coord, switch, clock, _, _ = consumer
    await switch.async_turn_on()
    await clock.advance(5, drain=False)
    if operation == "disable":
        await switch.async_turn_off()
    else:
        await coord.async_shutdown()
    coord.hass.services.async_call.reset_mock()
    await clock.drain()
    assert coord.grid_consumer_offset == 0
    assert all(
        call.args[2].get("value") != coord.charge_power + 750
        for call in coord.hass.services.async_call.call_args_list
    )
    if operation == "unload":
        coord.hass.services.async_call.assert_not_called()


async def test_reload_starts_zero_with_restored_enable(consumer):
    old, _, clock, _, _ = consumer
    old.grid_consumer_enabled = True
    await clock.advance(5)
    await old.async_shutdown()
    new = VictronChargeControlCoordinator(old.hass, old.config_entry)
    new.control_mode = MODE_FORCE_CHARGE
    new.grid_consumer_enabled = True
    new.async_request_refresh = AsyncMock(side_effect=new._async_update_data)
    await new.async_setup()
    assert new.grid_consumer_offset == 0
    await clock.advance(4.99)
    assert new.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert new.grid_consumer_offset == 750
    await new.async_shutdown()


async def test_startup_waits_for_schedule_restore_before_batching(consumer):
    old, _, clock, _, _ = consumer
    await old.async_shutdown()
    new = VictronChargeControlCoordinator(old.hass, old.config_entry)
    new.control_mode = MODE_FORCE_CHARGE
    new.grid_consumer_enabled = True
    new.async_request_refresh = AsyncMock(side_effect=new._async_update_data)
    restoring, release = asyncio.Event(), asyncio.Event()

    async def load():
        restoring.set()
        await release.wait()

    new._async_load_schedule = load
    setup = asyncio.create_task(new.async_setup())
    await restoring.wait()
    await clock.advance(10)
    assert new.grid_consumer_offset == 0
    new.async_request_refresh.assert_not_awaited()
    release.set()
    await setup
    await clock.advance(4.99)
    assert new.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert new.grid_consumer_offset == 750
    await new.async_shutdown()
