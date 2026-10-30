"""Dual-actuator lifecycle regressions using real HA refresh serialization."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.victron_charge_control import async_setup_entry
from custom_components.victron_charge_control.config_flow import (
    STEP_USER_DATA_SCHEMA,
    VictronChargeControlConfigFlow,
    VictronChargeControlOptionsFlow,
    _validate_entities,
)
from custom_components.victron_charge_control.const import (
    ACTION_IDLE, CONF_AC_GRID_SETPOINT_ENTITY, CONF_GRID_CONSUMER_ENTITY,
    CONF_GRID_SETPOINT_ENTITY, MODE_FORCE_CHARGE, MODE_FORCE_DISCHARGE,
    MODE_MANUAL, MODE_OFF,
)
from .conftest import MOCK_CONFIG_DATA, MockConfigEntry, MockState
from .test_grid_consumer import consumer, native_consumer  # noqa: F401

RAM = "number.ac_grid_setpoint"
PERMANENT = "number.grid_setpoint"


def writes(coord, entity=RAM):
    return [call.args[2]["value"] for call in coord.hass.services.async_call.call_args_list
            if call.args[:2] == ("number", "set_value") and call.args[2]["entity_id"] == entity]


@pytest.mark.parametrize("ram", [None, "", "sensor.wrong", PERMANENT])
async def test_old_or_invalid_entry_cannot_start(mock_hass, mock_store, ram):
    data = dict(MOCK_CONFIG_DATA)
    data.pop(CONF_AC_GRID_SETPOINT_ENTITY)
    if ram is not None:
        data[CONF_AC_GRID_SETPOINT_ENTITY] = ram
    entry = MockConfigEntry(data=data)
    mock_store._data = {"charge_hours": [{"date": "2026-10-30", "hour": 12}]}
    with patch("custom_components.victron_charge_control.VictronChargeControlCoordinator") as controller:
        with pytest.raises(ConfigEntryError, match="Reconfigure"):
            await async_setup_entry(mock_hass, entry)
    controller.assert_not_called()
    mock_hass.config_entries.async_forward_entry_setups.assert_not_awaited()
    mock_hass.services.async_call.assert_not_awaited()
    assert not mock_store.save_calls
    assert entry.data == data


@pytest.mark.parametrize("ram, error", [(PERMANENT, "distinct_setpoints"), ("sensor.wrong", "number_required"), ("number.missing", "entity_not_found")])
def test_validate_ram_selection(mock_hass, ram, error):
    mock_hass.states.get.side_effect = lambda entity: None if entity == "number.missing" else MockState("unknown")
    assert _validate_entities(mock_hass, {**MOCK_CONFIG_DATA, CONF_AC_GRID_SETPOINT_ENTITY: ram}) == {CONF_AC_GRID_SETPOINT_ENTITY: error}


async def test_setup_options_require_ram_and_allow_inactive_unknown(mock_hass):
    mock_hass.states.get.return_value = MockState("unknown")
    assert not _validate_entities(mock_hass, MOCK_CONFIG_DATA)
    assert STEP_USER_DATA_SCHEMA.schema[CONF_AC_GRID_SETPOINT_ENTITY].config["domain"] == ["number"]
    flow = VictronChargeControlOptionsFlow(MockConfigEntry())
    flow.hass = mock_hass
    flow.async_show_form = MagicMock()
    await flow.async_step_init()
    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    assert schema(MOCK_CONFIG_DATA)[CONF_AC_GRID_SETPOINT_ENTITY] == RAM
    await flow.async_step_init({**MOCK_CONFIG_DATA, CONF_AC_GRID_SETPOINT_ENTITY: PERMANENT})
    assert flow.async_show_form.call_args.kwargs["errors"] == {CONF_AC_GRID_SETPOINT_ENTITY: "distinct_setpoints"}


async def test_reconfigure_preserves_entry_and_settings_and_clears_optional(mock_hass, mock_store):
    data = {**MOCK_CONFIG_DATA, "custom_setting": 123, CONF_GRID_CONSUMER_ENTITY: "sensor.old"}
    data.pop(CONF_AC_GRID_SETPOINT_ENTITY)
    entry = MockConfigEntry(data=data)
    entry.options = {"safety_startup_grace_seconds": 45}
    mock_store._data = {"charge_hours": ["preserved"]}
    flow = VictronChargeControlConfigFlow()
    flow.hass = mock_hass
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": "abort"})
    mock_hass.states.get.return_value = MockState("unknown")
    await flow.async_step_reconfigure(dict(MOCK_CONFIG_DATA))
    args, kwargs = flow.async_update_reload_and_abort.call_args
    assert args == (entry,)
    assert kwargs == {"data": {**MOCK_CONFIG_DATA, "custom_setting": 123}}
    assert entry.options == {"safety_startup_grace_seconds": 45}
    assert mock_store._data == {"charge_hours": ["preserved"]}
    assert not mock_store.save_calls


async def test_fallback_precedes_ram_and_readback_lag_does_not_repeat_flash(consumer):
    coord, _, clock, _, states = consumer
    coord.hass.services.async_call.reset_mock()
    states[PERMANENT] = MockState("900")
    successful = coord.hass.services.async_call.side_effect

    async def lagged(domain, service, data, **kwargs):
        if data.get("entity_id") != PERMANENT:
            await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = lagged
    await coord.async_request_refresh()
    await clock.advance(20)
    assert writes(coord, PERMANENT) == [0]
    assert writes(coord) == [3000] * 4
    assert coord._last_permanent_write == 0
    # Once acknowledged, genuine external changes are corrected immediately.
    states[PERMANENT] = MockState("0")
    await coord.async_request_refresh()
    states[PERMANENT] = MockState("800")
    await coord.async_request_refresh()
    assert writes(coord, PERMANENT) == [0, 0]


async def test_fallback_failure_blocks_active_target_and_retries(consumer):
    coord, _, clock, _, states = consumer
    states[PERMANENT] = MockState("900")
    coord.hass.services.async_call.reset_mock()
    successful = coord.hass.services.async_call.side_effect

    async def failure(domain, service, data, **kwargs):
        if data.get("entity_id") == PERMANENT:
            raise HomeAssistantError("fallback rejected")
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = failure
    await coord.async_request_refresh()
    assert writes(coord) == [0]
    assert coord._last_permanent_write is None
    coord.hass.services.async_call.side_effect = successful
    await clock.advance(5)
    assert writes(coord)[-1] == 3000
    assert states[PERMANENT].state == "0.0"
    calls = coord.hass.services.async_call.call_args_list
    assert [call.args[2]["entity_id"] for call in calls[-2:]] == [PERMANENT, RAM]


@pytest.mark.parametrize("operation", ["disable", "invalid"])
@pytest.mark.parametrize("ram_fails", [False, True])
async def test_consumer_clear_during_fallback_recomputes_ram(native_consumer, operation, ram_fails):
    coord, switch, clock, change, states = native_consumer
    change("50")
    await switch.async_turn_on()
    await clock.advance(5)
    assert float(states[RAM].state) == 3050
    coord.setpoint_deadband = 200
    states[PERMANENT] = MockState("900")
    started, release = asyncio.Event(), asyncio.Event()
    service = coord.hass.services.async_call
    successful = service.side_effect
    service.reset_mock()

    async def delayed_fallback(domain, service, data, **kwargs):
        if data.get("entity_id") == PERMANENT:
            started.set()
            await release.wait()
        elif data.get("entity_id") == RAM and ram_fails:
            raise HomeAssistantError("RAM correction rejected")
        await successful(domain, service, data, **kwargs)

    service.side_effect = delayed_fallback
    updating = asyncio.create_task(coord.async_refresh())
    await started.wait()
    if operation == "disable":
        coord.grid_consumer_enabled = False
    else:
        change("unavailable")
    assert coord._grid_consumer_clear_pending
    release.set()
    await updating
    await clock.drain()
    assert writes(coord, PERMANENT) == [0]
    assert writes(coord) and all(value == 3000 for value in writes(coord))
    assert coord.data.target_setpoint == 3000
    assert coord.data.setpoint_calculation["grid_consumer_w"] == 0
    if ram_fails:
        assert float(states[RAM].state) == 3050
        assert coord._grid_consumer_clear_pending
        service.side_effect = successful
        await coord.async_refresh()
    assert float(states[RAM].state) == 3000
    assert not coord._grid_consumer_clear_pending


@pytest.mark.parametrize("discharge_power", [100, 3000])
@pytest.mark.parametrize("correction_fails", [False, True])
async def test_soc_reduction_during_ram_write_ignores_stale_readback(native_consumer, discharge_power, correction_fails):
    coord, _, clock, _, states = native_consumer
    coord.control_mode = MODE_FORCE_DISCHARGE
    coord._last_published_action = None
    coord.action_confirm_seconds = 0
    coord.min_soc = 20
    coord.soc_hysteresis = 2
    coord.discharge_power = discharge_power
    coord.setpoint_deadband = 200
    coord._solar_surplus_entity = "sensor.solar"
    states["sensor.solar"] = MockState("1500", {"unit_of_measurement": "W"})
    states["sensor.battery_soc"] = MockState("25")
    states[RAM] = MockState("-1500")
    started, release = asyncio.Event(), asyncio.Event()
    service = coord.hass.services.async_call
    successful = service.side_effect
    service.reset_mock()

    async def lagged_ram(domain, service, data, **kwargs):
        if data.get("entity_id") == RAM:
            if data["value"] == -1500 - discharge_power:
                started.set()
                await release.wait()
            elif correction_fails:
                raise HomeAssistantError("SOC correction rejected")
            # MQTT readback remains at the old, apparently safe target.
            return
        await successful(domain, service, data, **kwargs)

    service.side_effect = lagged_ram
    await clock.advance(5, drain=False)
    await asyncio.wait_for(started.wait(), timeout=2)
    states["sensor.battery_soc"] = MockState("20")
    release.set()
    await clock.drain()
    assert writes(coord) == [-1500 - discharge_power, -1500]
    assert coord.data.target_setpoint == -1500
    assert coord.data.discharge_solar_only
    if correction_fails:
        assert coord._last_applied_setpoint == -1500 - discharge_power
        service.side_effect = successful
        await coord.async_refresh()
        assert writes(coord)[-1] == -1500
    assert coord._last_applied_setpoint == -1500


@pytest.mark.parametrize("off_during", ["ram", "feed_in"])
@pytest.mark.parametrize("feed_in_fails", [False, True])
async def test_off_correction_precedes_feed_in_and_survives_its_failure(native_consumer, off_during, feed_in_fails):
    coord, _, clock, _, states = native_consumer
    coord.charge_power = 4000
    coord.grid_feed_in_control_enabled = True
    coord.default_max_grid_feed_in = 10000
    ram_started, release_ram = asyncio.Event(), asyncio.Event()
    feed_in_started, release_feed_in = asyncio.Event(), asyncio.Event()
    successful = coord.hass.services.async_call.side_effect

    async def delayed(domain, service, data, **kwargs):
        if data.get("entity_id") == RAM and data["value"] == 4000:
            ram_started.set()
            await release_ram.wait()
        elif data.get("entity_id") == "number.max_grid_feed_in":
            feed_in_started.set()
            await release_feed_in.wait()
            if feed_in_fails:
                raise HomeAssistantError("feed-in rejected")
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = delayed
    updating = asyncio.create_task(coord.async_refresh())
    await asyncio.wait_for(ram_started.wait(), timeout=2)
    if off_during == "ram":
        coord.control_mode = MODE_OFF
    release_ram.set()
    await asyncio.wait_for(feed_in_started.wait(), timeout=2)
    ram_before_feed_in_completion = float(states[RAM].state)
    if off_during == "feed_in":
        coord.control_mode = MODE_OFF
    release_feed_in.set()
    await updating
    await clock.drain()
    if off_during == "ram":
        assert ram_before_feed_in_completion == 0
    assert float(states[RAM].state) == 0
    assert coord._last_applied_setpoint == 0
    assert coord._ram_timer is None
    assert coord.last_update_success is not feed_in_fails


async def test_safety_change_during_grid_feed_in_is_corrected_before_dc_feed_in(native_consumer):
    coord, _, clock, _, states = native_consumer
    coord.grid_feed_in_control_enabled = True
    coord.default_max_grid_feed_in = 10000
    grid_started, release_grid = asyncio.Event(), asyncio.Event()
    dc_started, release_dc = asyncio.Event(), asyncio.Event()
    successful = coord.hass.services.async_call.side_effect

    async def delayed_grid(domain, service, data, **kwargs):
        if data.get("entity_id") == "number.max_grid_feed_in":
            grid_started.set()
            await release_grid.wait()
        await successful(domain, service, data, **kwargs)

    async def delayed_dc(**kwargs):
        dc_started.set()
        await release_dc.wait()

    coord.hass.services.async_call.side_effect = delayed_grid
    coord._apply_dc_coupled_feed_in = AsyncMock(side_effect=delayed_dc)
    updating = asyncio.create_task(coord.async_refresh())
    await asyncio.wait_for(grid_started.wait(), timeout=2)
    states["sensor.battery_soc"] = MockState("100")
    release_grid.set()
    await asyncio.wait_for(dc_started.wait(), timeout=2)
    ram_before_dc_completion = float(states[RAM].state)
    release_dc.set()
    await updating
    await clock.drain()
    assert ram_before_dc_completion == 0
    assert coord.data.target_setpoint == 0


async def test_due_refresh_recomputes_target_and_event_updates_keep_deadband(consumer):
    coord, _, clock, _, _ = consumer
    coord.hass.services.async_call.reset_mock()
    await clock.advance(2)
    coord.charge_power = 3050
    await coord.async_request_refresh()
    assert not writes(coord)
    assert coord._last_ram_write == 0
    await clock.advance(3)
    assert writes(coord) == [3050]
    assert coord._last_ram_write == 5
    await clock.advance(5)
    assert writes(coord) == [3050, 3050]
    assert not writes(coord, PERMANENT)


@pytest.mark.parametrize("mode", [MODE_FORCE_CHARGE, MODE_FORCE_DISCHARGE])
async def test_refresh_failure_does_not_advance_timestamp_and_retries(consumer, mode):
    coord, _, clock, _, _ = consumer
    coord.control_mode = mode
    coord._last_published_action = None
    await coord.async_request_refresh()
    previous, timestamp = coord._last_applied_setpoint, coord._last_ram_write
    successful = coord.hass.services.async_call.side_effect
    coord.hass.services.async_call.side_effect = HomeAssistantError("write rejected")
    await clock.advance(5)
    assert coord._last_applied_setpoint == previous
    assert coord._last_ram_write == timestamp
    coord.hass.services.async_call.side_effect = successful
    await clock.advance(5)
    assert coord._last_ram_write == 10


@pytest.mark.parametrize("stop", ["off", "idle", "soc", "disconnect"])
async def test_stops_write_ram_idle_then_cancel_active_timer(consumer, stop):
    coord, _, clock, change, states = consumer
    coord.hass.services.async_call.reset_mock()
    if stop == "off":
        coord.control_mode = MODE_OFF
    elif stop == "idle":
        coord.control_mode = MODE_MANUAL
        coord.action_confirm_seconds = 0
        await coord.async_request_refresh()  # Begin normal action confirmation.
    elif stop == "soc":
        states["sensor.battery_soc"] = MockState("100")
    else:
        states["sensor.battery_soc"] = MockState("unavailable")
    await coord.async_request_refresh()
    assert writes(coord) == [0]
    assert coord._ram_timer is None
    await clock.advance(20)
    await coord.async_request_refresh()  # Output echoes do not repeat idle writes.
    assert writes(coord) == [0]
    assert not writes(coord, PERMANENT)


async def test_failed_idle_reset_retries_and_survives_unknown_inactive(consumer):
    coord, _, clock, _, states = consumer
    timestamp = coord._last_ram_write
    successful = coord.hass.services.async_call.side_effect
    coord.hass.services.async_call.side_effect = HomeAssistantError("idle rejected")
    coord.control_mode = MODE_OFF
    await coord.async_request_refresh()
    assert coord._idle_correction_pending
    assert coord._last_ram_write == timestamp
    states[RAM] = MockState("unknown")
    coord.hass.services.async_call.side_effect = successful
    await clock.advance(5)
    assert states[RAM].state == "0.0"
    assert not coord._idle_correction_pending
    assert coord._ram_timer is None


@pytest.mark.parametrize("state", ["unknown", None, "null"])
async def test_inactive_ram_can_activate_without_safety_stop(consumer, state):
    coord, _, clock, _, states = consumer
    states[RAM] = MockState(state)
    await clock.advance(5)
    assert coord.control_mode == MODE_FORCE_CHARGE
    assert states[RAM].state == "3000.0"
    assert coord._last_ram_write == 5


async def test_disconnect_trips_watchdog_and_recovery_corrects_idle(consumer):
    coord, _, clock, _, states = consumer
    timestamp = coord._last_ram_write
    states[RAM] = MockState("unavailable")
    await clock.advance(5)
    assert coord.control_mode == MODE_OFF
    assert coord._last_ram_write == timestamp
    assert coord._idle_correction_pending
    states[RAM] = MockState("3000")
    await clock.advance(5)
    assert states[RAM].state == "0.0"
    assert not coord._idle_correction_pending
    assert coord._ram_timer is None


async def test_missing_ram_preserves_startup_grace(consumer):
    coord, _, _, _, states = consumer
    deadline = dt_util.now() + timedelta(seconds=90)
    coord._safety_startup_deadline = deadline
    states.pop(RAM)
    await coord.async_request_refresh()
    assert coord.control_mode == MODE_FORCE_CHARGE
    assert coord._safety_startup_deadline == deadline
    states[RAM] = MockState("unknown")
    await coord.async_request_refresh()
    assert coord._safety_startup_deadline is None
    assert coord.control_mode == MODE_FORCE_CHARGE


async def test_idle_with_consumer_adjustment_is_active(consumer):
    coord, switch, clock, _, states = consumer
    coord.control_mode = MODE_MANUAL
    coord.action_confirm_seconds = 0
    await switch.async_turn_on()
    await clock.advance(5)
    assert coord.data.desired_action == ACTION_IDLE
    assert states[RAM].state == "750.0"
    coord.hass.services.async_call.reset_mock()
    await clock.advance(5)
    assert writes(coord) == [750]
    assert not writes(coord, PERMANENT)


@pytest.mark.parametrize("action, expected", [("charge", 3000), ("discharge", -3000), ("pv_charge", -1000)])
async def test_scheduled_targets_route_only_to_ram(consumer, action, expected):
    coord, _, clock, _, states = consumer
    coord.control_mode = MODE_MANUAL
    coord.action_confirm_seconds = 0
    now = dt_util.now()
    slot = (now.strftime("%Y-%m-%d"), now.hour)
    setattr(coord, f"_{action}_hours", [slot])
    if action == "pv_charge":
        coord._solar_surplus_entity = "sensor.solar"
        states["sensor.solar"] = MockState("2000", {"unit_of_measurement": "W"})
        coord.pv_charge_share = 50
    coord.hass.services.async_call.reset_mock()
    await coord.async_request_refresh()
    await clock.advance(5)
    assert writes(coord)[-1] == expected
    assert not writes(coord, PERMANENT)


async def test_periodic_and_event_refreshes_serialize_with_shutdown(native_consumer):
    coord, _, clock, _, states = native_consumer
    started, release = asyncio.Event(), asyncio.Event()
    successful = coord.hass.services.async_call.side_effect
    active_writes = 0
    max_concurrent = 0

    async def slow(domain, service, data, **kwargs):
        nonlocal active_writes, max_concurrent
        active_writes += 1
        max_concurrent = max(max_concurrent, active_writes)
        if data.get("entity_id") == RAM and data.get("value") == 3000:
            started.set()
            await release.wait()
        await successful(domain, service, data, **kwargs)
        active_writes -= 1

    coord.hass.services.async_call.side_effect = slow
    await clock.advance(5, drain=False)
    await started.wait()
    event = asyncio.create_task(coord.async_refresh())
    shutdown = asyncio.create_task(coord.async_shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await asyncio.gather(event, shutdown)
    await clock.drain()
    assert max_concurrent == 1
    assert states[RAM].state == "0.0"
    assert coord._ram_timer is None
    count = coord.hass.services.async_call.call_count
    await clock.advance(20)
    assert coord.hass.services.async_call.call_count == count


async def test_unload_attempts_idle_even_when_fallback_fails(consumer):
    coord, _, _, _, states = consumer
    states[PERMANENT] = MockState("1000")
    successful = coord.hass.services.async_call.side_effect

    async def failure(domain, service, data, **kwargs):
        if data.get("entity_id") == PERMANENT:
            raise HomeAssistantError("fallback rejected")
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = failure
    await coord.async_shutdown()
    assert states[RAM].state == "0.0"
    assert not coord._idle_correction_pending
    assert coord._ram_timer is None
