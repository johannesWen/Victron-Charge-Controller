"""Consumer offset configuration, controls, and fixed-deadline batching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from custom_components.victron_charge_control import (
    _async_update_listener,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    CONF_GRID_CONSUMER_ENTITY,
    CONF_SOLAR_SURPLUS_ENTITY,
    DOMAIN,
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

    @property
    def consumer_pending(self):
        return [timer for timer in self.pending if "_accept_latest" in repr(timer.args)]

    async def drain(self):
        while tasks := [task for task in self.hass._scheduled_tasks if not task.done()]:
            await asyncio.gather(*tasks)

    async def advance(self, seconds, *, drain=True):
        deadline = self.now + seconds
        while due := [timer for timer in self.pending if timer.when <= deadline]:
            timer = min(due, key=lambda item: item.when)
            self.now = timer.when
            # HA runs callbacks sharing a deadline before the next loop turn.
            for timer in sorted(due, key=lambda item: item.when):
                if timer.when == self.now:
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
        "number.ac_grid_setpoint": MockState("0"),
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


@pytest.fixture
async def native_consumer(consumer):
    """Run the real HA debouncer, including eager jobs and cooldown timers."""
    coord, _, clock, _, _ = consumer
    hass = coord.hass

    def create_task(coro, name=None, *, eager_start=True):
        task = asyncio.create_task(coro, name=name, eager_start=eager_start)
        hass._scheduled_tasks.append(task)
        return task

    def run_job(job, *args, **kwargs):
        result = job.target(*args)
        if asyncio.iscoroutine(result):
            return create_task(result)
        return result

    hass.async_create_task.side_effect = create_task
    hass.async_run_hass_job.side_effect = run_job
    hass.loop.call_later.side_effect = (
        lambda delay, callback, *args: clock.call_at(clock.now + delay, callback, *args)
    )
    del coord.async_request_refresh
    yield consumer
    await clock.drain()
    for task in hass._scheduled_tasks:
        if not task.cancelled():
            assert task.exception() is None


@pytest.fixture
async def solar_consumer(consumer):
    coord, _, clock, change, _ = consumer
    change("0", source="sensor.solar")
    coord.update_entity_references({
        **coord.config_entry.data, CONF_SOLAR_SURPLUS_ENTITY: "sensor.solar",
    })
    await clock.drain()
    return consumer


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1000", "W", 0), ("750", "W", 0), ("250", "W", 500),
        ("749.5", "W", 0.5), ("0", "W", 750), ("-100", "W", 750),
        (None, "W", 750), ("unavailable", "W", 750), ("unknown", "W", 750),
        ("bad", "W", 750), ("NaN", "W", 750), ("inf", "W", 750),
        ("-inf", "W", 750), ("1e309", "W", 750),
        ("1000", None, 750), ("1000", "kWh", 750), ("1000", "kW", 750),
    ],
)
async def test_instantaneous_solar_shortfall(solar_consumer, value, unit, expected):
    coord, switch, clock, change, _ = solar_consumer
    change("0.75", "kW")
    change(value, unit, source="sensor.solar")
    # An old mean must never decide the consumer offset.
    coord._solar_samples.append((dt_util.now(), 10000))
    await switch.async_turn_on()
    await clock.advance(5)
    assert coord.grid_consumer_power == 750
    assert coord.grid_consumer_offset == expected
    assert coord.data.target_setpoint == coord.charge_power + expected
    assert coord.data.setpoint_calculation["grid_consumer_w"] == expected


async def test_solar_only_changes_batch_to_first_deadline(solar_consumer):
    coord, switch, clock, change, _ = solar_consumer
    await switch.async_turn_on()
    await clock.advance(5)
    change("250", source="sensor.solar")
    first = clock.consumer_pending[0]
    await clock.advance(2)
    change("1000", source="sensor.solar")
    await clock.advance(2.99)
    change("500", source="sensor.solar")
    assert clock.consumer_pending == [first]
    assert coord.grid_consumer_offset == 750
    await clock.advance(0.01)
    assert coord.grid_consumer_offset == 250
    change("750", source="sensor.solar")
    await clock.advance(5)
    assert coord.grid_consumer_offset == 0
    change("unavailable", source="sensor.solar")
    await clock.advance(4.99)
    assert coord.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert coord.grid_consumer_offset == 750


async def test_expiry_rereads_solar_without_event(solar_consumer):
    coord, switch, clock, change, _ = solar_consumer
    await switch.async_turn_on()
    change("1000", source="sensor.solar", notify=False)
    await clock.advance(5)
    assert coord.grid_consumer_offset == 0
    change("250", source="sensor.solar")
    change("unavailable", source="sensor.solar", notify=False)
    await clock.advance(5)
    assert coord.grid_consumer_offset == 750


@pytest.mark.parametrize("replacement", [None, "sensor.solar_replacement"])
async def test_solar_source_change_cancels_old_batch_and_rebinds(solar_consumer, replacement):
    coord, switch, clock, change, _ = solar_consumer
    await switch.async_turn_on()
    await clock.advance(5)
    change("1000", source="sensor.solar")
    stale = clock.consumer_pending[0]
    change("250", source="sensor.solar_replacement")
    coord.update_entity_references({
        **coord.config_entry.data, CONF_SOLAR_SURPLUS_ENTITY: replacement,
    })
    assert stale.cancelled
    stale.fire()
    await clock.drain()
    assert coord.grid_consumer_offset == 0
    await clock.advance(4.99)
    assert coord.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert coord.grid_consumer_offset == (500 if replacement else 750)
    change("0", source="sensor.solar")
    assert not clock.consumer_pending
    if replacement:
        change("1000", source=replacement)
        await clock.advance(5)
        assert coord.grid_consumer_offset == 0


@pytest.mark.parametrize("solar", ["250", "750", "1000"])
async def test_restored_switch_uses_current_solar(solar_consumer, solar):
    coord, switch, clock, change, _ = solar_consumer
    change(solar, source="sensor.solar")
    switch.async_get_last_state = AsyncMock(return_value=MockState("on"))
    with patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock()):
        await switch.async_added_to_hass()
    await clock.advance(4.99)
    assert coord.grid_consumer_offset == 0
    await clock.advance(0.01)
    assert coord.grid_consumer_offset == max(750 - float(solar), 0)


@pytest.mark.parametrize("operation", ["invalid", "off", "disable"])
async def test_solar_batch_cannot_survive_consumer_clear(solar_consumer, operation):
    coord, switch, clock, change, _ = solar_consumer
    await switch.async_turn_on()
    await clock.advance(5)
    change("250", source="sensor.solar")
    stale = clock.consumer_pending[0]
    if operation == "invalid":
        change("unavailable")
    elif operation == "off":
        coord.control_mode = MODE_OFF
        await coord.async_request_refresh()
    else:
        await switch.async_turn_off()
    assert coord.grid_consumer_offset == 0
    assert stale.cancelled
    stale.fire()
    await clock.advance(5)
    await clock.drain()
    assert coord.grid_consumer_offset == 0
    assert coord.data.target_setpoint == (
        coord.idle_setpoint if operation == "off" else coord.charge_power
    )


async def test_solar_offset_obeys_setpoint_limits(solar_consumer):
    coord, switch, clock, change, _ = solar_consumer
    change("250", source="sensor.solar")
    coord.max_grid_setpoint = coord.charge_power + 100
    await switch.async_turn_on()
    await clock.advance(5)
    assert coord.grid_consumer_offset == 500
    assert coord.data.target_setpoint == coord.max_grid_setpoint
    coord.min_grid_setpoint = -100
    assert coord._compute_setpoint(ACTION_DISCHARGE) == -100


@pytest.mark.parametrize("solar", ["NaN", "inf", "-inf"])
async def test_nonfinite_solar_mean_does_not_publish_invalid_calculation(solar_consumer, solar):
    coord, _, _, change, _ = solar_consumer
    coord.control_mode = MODE_FORCE_DISCHARGE
    coord._last_published_action = None
    change(solar, source="sensor.solar", notify=False)
    await coord.async_request_refresh()
    assert coord.data.setpoint_calculation["surplus_w"] == 0


@pytest.mark.parametrize("replace_source", [False, True])
async def test_solar_change_during_awaited_write_is_reconciled(native_consumer, replace_source):
    coord, switch, clock, change, states = native_consumer
    change("0", source="sensor.solar")
    coord.update_entity_references({
        **coord.config_entry.data, CONF_SOLAR_SURPLUS_ENTITY: "sensor.solar",
    })
    await clock.drain()
    await switch.async_turn_on()
    await clock.advance(5)
    started, release = asyncio.Event(), asyncio.Event()
    write = coord.hass.services.async_call.side_effect

    async def delayed_write(domain, service, data, **kwargs):
        if data.get("value") == coord.charge_power + 1000:
            started.set()
            await release.wait()
        await write(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = delayed_write
    change("1000")
    await clock.advance(5, drain=False)
    await asyncio.wait_for(started.wait(), 1)
    if replace_source:
        change("800", source="sensor.replacement")
        coord.update_entity_references({
            **coord.config_entry.data, CONF_SOLAR_SURPLUS_ENTITY: "sensor.replacement",
        })
    else:
        change("800", source="sensor.solar")
    await clock.advance(5, drain=False)
    release.set()
    await clock.drain()
    await clock.advance(6)
    assert coord.grid_consumer_offset == 200
    assert coord.data.target_setpoint == coord.charge_power + 200
    assert float(states["number.ac_grid_setpoint"].state) == coord.charge_power + 200


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
    first = clock.consumer_pending[0]
    await clock.advance(2)
    change("1.2", "kW")
    await clock.advance(2.9)
    change("900")
    assert clock.consumer_pending == [first]
    assert coord.grid_consumer_offset == 0
    assert coord.data.target_setpoint == coord.charge_power
    before = coord.data.setpoint_calculation
    assert before["grid_consumer_w"] == 0
    await clock.advance(0.1)
    assert coord.grid_consumer_offset == 900
    assert coord.data.target_setpoint == coord.charge_power + 900
    assert coord.data.setpoint_calculation["grid_consumer_w"] == 900
    assert before["grid_consumer_w"] == 0
    sensor = TargetSetpointSensor(coord, MockConfigEntry())
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_coordinator_update()
    assert sensor.native_value == coord.charge_power + 900


@pytest.mark.parametrize("idle", [-500, 500])
async def test_off_snapshot_shows_actual_unclamped_idle(consumer, idle):
    coord, switch, clock, _, states = consumer
    await switch.async_turn_on()
    await clock.advance(5)
    coord.min_grid_setpoint = -100
    coord.max_grid_setpoint = 100
    coord.idle_setpoint = idle
    coord.control_mode = MODE_OFF
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == idle
    assert float(states["number.ac_grid_setpoint"].state) == idle
    assert coord.data.setpoint_calculation == {
        "setting_w": idle, "pv_charge_w": 0, "surplus_w": 0,
        "grid_consumer_w": 0, "limits_w": 0,
    }


async def test_calculation_does_not_read_new_settings_after_awaited_write(native_consumer):
    coord, switch, clock, _, _ = native_consumer
    started, release = asyncio.Event(), asyncio.Event()
    write = coord.hass.services.async_call.side_effect

    async def delayed_write(*args, **kwargs):
        started.set()
        await release.wait()
        await write(*args, **kwargs)

    await switch.async_turn_on()
    coord.hass.services.async_call.side_effect = delayed_write
    await clock.advance(5, drain=False)
    await asyncio.wait_for(started.wait(), 1)
    coord.charge_power = 6000
    release.set()
    await clock.drain()
    assert coord.data.target_setpoint == 3750
    assert coord.data.setpoint_calculation == {
        "setting_w": 3000, "pv_charge_w": 0, "surplus_w": 0,
        "grid_consumer_w": 750, "limits_w": 0,
    }


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
    stale = clock.consumer_pending[0]
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
        states["number.ac_grid_setpoint"] = MockState("unavailable")
        # Test retry without changing the watchdog's existing startup policy.
        coord._safety_startup_deadline = None
    elif failure == "service_error":
        service.side_effect = HomeAssistantError("device rejected write")
    await switch.async_turn_off()
    assert coord.grid_consumer_offset == 0
    if failure:
        states["number.ac_grid_setpoint"] = MockState(str(previous))
        service.side_effect = successful_write
        coord.control_mode = action
        coord._last_published_action = None
        await coord.async_request_refresh()
    assert coord._last_applied_setpoint == previous - 50
    assert float(states["number.ac_grid_setpoint"].state) == previous - 50


async def test_periodic_refresh_applies_small_offset_changes(consumer):
    coord, switch, clock, change, _ = consumer
    await switch.async_turn_on()
    await clock.advance(5)
    previous = coord._last_applied_setpoint
    coord.setpoint_deadband = 200
    change("800")
    await clock.advance(5)
    assert coord.data.target_setpoint == coord.charge_power + 800
    assert coord._last_applied_setpoint == previous + 50


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
    assert float(states["number.ac_grid_setpoint"].state) == coord.charge_power
    states["number.ac_grid_setpoint"] = MockState(str(coord.charge_power + 150))
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
    assert float(states["number.ac_grid_setpoint"].state) == coord.charge_power
    assert not coord._grid_consumer_clear_pending
    coord.hass.services.async_call.reset_mock()
    await coord.async_request_refresh()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.parametrize("operation", ["disable", "invalid"])
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
    else:
        change("unavailable", notify=False)
        # The source listener clears synchronously, before its requested refresh runs.
        coord._sample_grid_consumer()
    release.set()
    await updating
    assert coord.grid_consumer_offset == 0
    assert float(states["number.ac_grid_setpoint"].state) == previous - 50
    assert coord.data.target_setpoint == previous - 50


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize("write_fails", [False, True])
async def test_entry_unload_drains_write_before_replacement(native_consumer, reload, write_fails):
    old, switch, clock, change, states = native_consumer
    hass, entry = old.hass, old.config_entry
    hass.data[DOMAIN] = {entry.entry_id: old}
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    await switch.async_turn_on()
    await clock.advance(5)
    assert float(states["number.ac_grid_setpoint"].state) == 3750
    started, release = asyncio.Event(), asyncio.Event()
    write = hass.services.async_call.side_effect

    async def delayed_write(domain, service, data, **kwargs):
        if data.get("value") == 3150:
            started.set()
            await release.wait()
            if write_fails:
                raise HomeAssistantError("Device write failed")
        await write(domain, service, data, **kwargs)

    hass.services.async_call.side_effect = delayed_write
    change("150")
    await clock.advance(5, drain=False)
    await asyncio.wait_for(started.wait(), 1)
    # Also leave a native debouncer request queued behind the active write.
    await old.async_request_refresh()

    async def restore_controls(*_):
        new = hass.data[DOMAIN][entry.entry_id]
        new.control_mode = MODE_FORCE_CHARGE
        new.grid_consumer_enabled = True

    async def reload_entry(_):
        assert await async_unload_entry(hass, entry)
        assert await async_setup_entry(hass, entry)

    hass.config_entries.async_forward_entry_setups.side_effect = restore_controls
    hass.config_entries.async_reload.side_effect = reload_entry
    with (
        patch("custom_components.victron_charge_control.async_register_commands"),
        patch("custom_components.victron_charge_control._async_register_card", new_callable=AsyncMock),
        patch.object(old.forecast_coordinator, "async_shutdown", new_callable=AsyncMock),
    ):
        if reload:
            entry.data = dict(MOCK_CONFIG_DATA)
            stopping = asyncio.create_task(_async_update_listener(hass, entry), eager_start=True)
        else:
            stopping = asyncio.create_task(async_unload_entry(hass, entry), eager_start=True)
        waited_for_write = not stopping.done()
        setups_before_release = hass.config_entries.async_forward_entry_setups.await_count
        release.set()
        await asyncio.wait_for(stopping, 1)
        await clock.drain()
        assert waited_for_write
        assert setups_before_release == 0
        assert old.last_update_success  # Write failure is retained for retry, not a failed data refresh.
        assert old.grid_consumer_offset == 0
        if reload:
            new = hass.data[DOMAIN][entry.entry_id]
            assert new.grid_consumer_entity is None
            assert not new.grid_consumer_enabled
            assert float(states["number.ac_grid_setpoint"].state) == 3000
            await new.async_refresh()
            await clock.advance(6)
            assert float(states["number.ac_grid_setpoint"].state) == 3000
            assert await async_unload_entry(hass, entry)
        else:
            assert entry.entry_id not in hass.data[DOMAIN]
            # A subsequent controller can set its target after unload returns.
            states["number.ac_grid_setpoint"] = MockState("3000")
            writes_after_unload = hass.services.async_call.call_count
            await clock.advance(6)
            await old.async_request_refresh()
            assert float(states["number.ac_grid_setpoint"].state) == 3000
            assert hass.services.async_call.call_count == writes_after_unload


@pytest.mark.parametrize("clear", [False, True])
async def test_slow_writes_finish_and_recheck_watchdog(native_consumer, clear):
    coord, switch, clock, change, states = native_consumer
    await switch.async_turn_on()
    await clock.advance(5)
    write = coord.hass.services.async_call.side_effect
    writes = []

    async def slow_write(domain, service, data, **kwargs):
        if data.get("entity_id") == "number.ac_grid_setpoint":
            writes.append(data["value"])
            if len(writes) <= 12:
                states["sensor.battery_soc"] = MockState("unavailable")
                change("unavailable" if clear else ("1200" if len(writes) % 2 else "750"))
                await clock.advance(6, drain=False)
        await write(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = slow_write
    states["number.ac_grid_setpoint"] = MockState("0")
    await coord.async_refresh()
    assert coord.last_update_success
    assert len(writes) == 2  # A changed safety input is corrected immediately.
    assert clock.now == 17
    if clear:
        assert coord.control_mode == MODE_OFF
    # Ordinary accepted loads yield to the next refresh, including its watchdog.
    coord.hass.services.async_call.side_effect = write
    await clock.advance(1)
    assert coord.control_mode == MODE_OFF
    assert float(states["number.ac_grid_setpoint"].state) == coord.idle_setpoint
    assert coord.data.target_setpoint == coord.idle_setpoint


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
