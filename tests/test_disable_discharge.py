"""Charge-window discharge holds, durable cleanup and independent controls."""
from __future__ import annotations

from tests.slots import utc_slot

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import CoreState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.victron_charge_control.config_flow import (
    STEP_USER_DATA_SCHEMA, _validate_entities,
)
from custom_components.victron_charge_control.const import (
    CONF_MAX_DISCHARGE_POWER_ENTITY, MODE_AUTO, MODE_MANUAL, MODE_OFF,
    MODE_FORCE_CHARGE, MODE_FORCE_DISCHARGE,
)
from custom_components.victron_charge_control.coordinator import VictronChargeControlCoordinator
from custom_components.victron_charge_control.switch import SWITCHES, VictronCCSwitch
from .conftest import MOCK_CONFIG_DATA, MockConfigEntry, MockState
from .test_grid_consumer import consumer, native_consumer  # noqa: F401

LIMIT = "number.max_discharge_power"
OTHER = "number.other_discharge_power"
KEY = "discharge_release_entity"
RAM = "number.ac_grid_setpoint"


def writes(coord, entity=LIMIT):
    return [call.args[2]["value"] for call in coord.hass.services.async_call.call_args_list
            if call.args[0] == "number" and call.args[2].get("entity_id") == entity]


def configure(context):
    coord, _, clock, change, states = context
    states[LIMIT] = MockState("-1", {"unit_of_measurement": "W"})
    coord.update_entity_references({**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: LIMIT})
    desc = next(desc for desc in SWITCHES if desc.key == "disable_discharge")
    switch = VictronCCSwitch(coord, coord.config_entry, desc)
    switch.async_write_ha_state = MagicMock()
    return coord, switch, clock, change, states


def slot(now=None):
    now = now or dt_util.now()
    return utc_slot(now.strftime("%Y-%m-%d"), now.hour)


@pytest.mark.parametrize("mode", [MODE_FORCE_CHARGE, MODE_AUTO, MODE_MANUAL])
@pytest.mark.parametrize("constraint", ["none", "max_soc", "zero_power", "charge_not_allowed"])
async def test_hold_is_window_not_charge_eligibility(consumer, mock_store, mode, constraint):
    coord, switch, clock, _, states = configure(consumer)
    coord.control_mode = mode
    coord._charge_hours = [slot()]
    coord.action_confirm_seconds = 600
    if constraint == "max_soc":
        states["sensor.battery_soc"] = MockState("100")
    elif constraint == "zero_power":
        coord.charge_power = 0
    elif constraint == "charge_not_allowed":
        coord.charge_allowed = False
    await switch.async_turn_on()
    assert writes(coord) == [0]
    assert mock_store._data[KEY] == LIMIT
    for _ in range(10):
        await coord.async_request_refresh()
    assert writes(coord) == [0]  # Readback/event echoes do not repeat writes.
    await clock.advance(15)
    assert writes(coord) == [0, 0, 0, 0]
    coord._charge_hours = []
    coord.control_mode = MODE_OFF
    await coord.async_request_refresh()
    assert writes(coord) == [0, 0, 0, 0, -1]
    assert mock_store._data[KEY] is None
    assert coord._ram_timer is None


@pytest.mark.parametrize("mode", [MODE_AUTO, MODE_MANUAL])
@pytest.mark.parametrize("kind", ["pv_overlap", "pv_only", "yesterday", "tomorrow", "other_hour"])
async def test_only_current_regular_charge_slots_hold(consumer, mode, kind):
    coord, switch, _, _, _ = configure(consumer)
    coord.control_mode = mode
    coord._charge_hours = [slot()]
    if kind in ("pv_overlap", "pv_only"):
        coord._pv_charge_hours = [slot()]
        if kind == "pv_only":
            coord._charge_hours = []
    elif kind == "other_hour":
        coord._charge_hours = [slot(dt_util.now() + timedelta(hours=1))]
    else:
        coord._charge_hours = [slot(dt_util.now() + timedelta(days=1 if kind == "tomorrow" else -1))]
    await switch.async_turn_on()
    assert not writes(coord)
    coord._pv_charge_hours = []
    coord._charge_hours = [slot()]
    await coord.async_request_refresh()
    assert writes(coord) == [0]
    coord._pv_charge_hours = [slot()]
    await coord.async_request_refresh()
    assert writes(coord) == [0, -1]


@pytest.mark.parametrize("stop", ["toggle", "off", "discharge", "window", "watchdog"])
async def test_release_bypasses_action_debounce(consumer, mock_store, stop):
    coord, switch, _, _, states = configure(consumer)
    await switch.async_turn_on()
    coord.action_confirm_seconds = 600
    if stop == "toggle":
        await switch.async_turn_off()
    else:
        if stop == "watchdog":
            states["sensor.battery_soc"] = MockState("unavailable")
        else:
            coord.control_mode = {"off": MODE_OFF, "discharge": MODE_FORCE_DISCHARGE, "window": MODE_MANUAL}[stop]
        await coord.async_request_refresh()
    assert writes(coord) == [0, -1]
    assert mock_store._data[KEY] is None


@pytest.mark.parametrize("state", ["unknown", None, "null"])
async def test_inactive_limit_can_hold_refresh_and_release(consumer, mock_store, state):
    coord, switch, clock, _, states = configure(consumer)
    successful = coord.hass.services.async_call.side_effect

    async def write(domain, service, data, **kwargs):
        if data.get("entity_id") == LIMIT:
            assert mock_store._data[KEY] == LIMIT
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = write
    states[LIMIT] = MockState(state)
    await switch.async_turn_on()
    assert writes(coord) == [0]
    states[LIMIT] = MockState(state)
    await clock.advance(5)
    assert writes(coord) == [0, 0]
    states[LIMIT] = MockState(state)
    await switch.async_turn_off()
    assert writes(coord) == [0, 0, -1]
    assert mock_store._data[KEY] is None
    assert coord.control_mode == MODE_FORCE_CHARGE


@pytest.mark.parametrize("bad", [None, "unavailable", "service"])
async def test_hold_failure_retries_without_stopping_grid_controls(consumer, mock_store, caplog, bad):
    coord, switch, clock, _, states = configure(consumer)
    successful = coord.hass.services.async_call.side_effect
    if bad == "service":
        async def failing(domain, service, data, **kwargs):
            if data.get("entity_id") == LIMIT:
                raise HomeAssistantError("offline")
            await successful(domain, service, data, **kwargs)
        coord.hass.services.async_call.side_effect = failing
    elif bad is None:
        states.pop(LIMIT)
    else:
        states[LIMIT] = MockState(bad)
    await switch.async_turn_on()
    await clock.advance(10)
    assert coord.control_mode == MODE_FORCE_CHARGE
    assert float(states[RAM].state) == coord.charge_power
    assert writes(coord, RAM)[-2:] == [coord.charge_power, coord.charge_power]
    assert "discharge power" in caplog.text
    assert writes(coord) == ([0, 0, 0] if bad == "service" else [])
    assert (mock_store._data or {}).get(KEY) == (LIMIT if bad == "service" else None)
    states[LIMIT] = MockState("-1")
    coord.hass.services.async_call.side_effect = successful
    await clock.advance(5)
    assert writes(coord)[-1] == 0
    assert states[LIMIT].state == "0"


@pytest.mark.parametrize("bad", [None, "unavailable"])
@pytest.mark.parametrize("restart", [False, True])
async def test_unavailable_hold_never_owns_existing_limit(consumer, mock_store, bad, restart):
    coord, switch, clock, _, states = configure(consumer)
    states[LIMIT] = None if bad is None else MockState(bad)
    await switch.async_turn_on()
    await clock.advance(10)
    assert not writes(coord)
    assert not coord._discharge_may_be_applied
    assert all(payload.get(KEY) is None for payload in mock_store.save_calls)
    await switch.async_turn_off()
    if restart:
        await coord.async_shutdown()
        coord = VictronChargeControlCoordinator(
            coord.hass, MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: LIMIT})
        )
        await coord._async_load_schedule()
    states[LIMIT] = MockState("2500")
    await clock.advance(5)
    await coord._async_update_data()
    assert not writes(coord)
    assert states[LIMIT].state == "2500"
    if restart:
        await coord.async_shutdown()


@pytest.mark.parametrize("bad", [None, "unavailable"])
@pytest.mark.parametrize("keep_enabled", [False, True])
async def test_unavailable_during_persistence_clears_unapplied_hold(
    consumer, mock_store, bad, keep_enabled,
):
    coord, switch, clock, _, states = configure(consumer)
    entered, release = asyncio.Event(), asyncio.Event()
    save = mock_store.async_save

    async def delayed(data):
        if data.get(KEY) == LIMIT:
            entered.set()
            await release.wait()
        await save(data)

    mock_store.async_save = delayed
    enable = asyncio.create_task(switch.async_turn_on())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        states[LIMIT] = None if bad is None else MockState(bad)
    finally:
        release.set()
        await enable
    assert not writes(coord)
    assert not coord._discharge_may_be_applied
    assert mock_store._data[KEY] is None
    if keep_enabled:
        states[LIMIT] = MockState("2500")
        await clock.advance(4.99)
        assert not writes(coord)
        await clock.advance(0.01)
        assert writes(coord) == [0]
        assert mock_store._data[KEY] == LIMIT
        return
    await switch.async_turn_off()
    await coord.async_shutdown()
    restarted = VictronChargeControlCoordinator(
        coord.hass, MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: LIMIT})
    )
    await restarted._async_load_schedule()
    states[LIMIT] = MockState("2500")
    await clock.advance(5)
    await restarted._async_update_data()
    assert not writes(restarted)
    assert states[LIMIT].state == "2500"
    await restarted.async_shutdown()


async def test_failed_hold_attempt_still_requires_release(consumer, mock_store):
    coord, switch, _, _, states = configure(consumer)
    successful = coord.hass.services.async_call.side_effect

    async def ambiguous_failure(domain, service, data, **kwargs):
        await successful(domain, service, data, **kwargs)
        if data.get("entity_id") == LIMIT and data["value"] == 0:
            raise HomeAssistantError("confirmation lost after write")

    coord.hass.services.async_call.side_effect = ambiguous_failure
    await switch.async_turn_on()
    assert states[LIMIT].state == "0"
    assert mock_store._data[KEY] == LIMIT
    await switch.async_turn_off()
    assert writes(coord) == [0, -1]
    assert mock_store._data[KEY] is None


@pytest.mark.parametrize("bad", [None, "unavailable", "service"])
async def test_failed_release_keeps_timer_during_off_and_recovery(consumer, mock_store, bad):
    coord, switch, clock, _, states = configure(consumer)
    await switch.async_turn_on()
    successful = coord.hass.services.async_call.side_effect
    if bad == "service":
        async def failing(domain, service, data, **kwargs):
            if data.get("entity_id") == LIMIT:
                raise HomeAssistantError("release rejected")
            await successful(domain, service, data, **kwargs)
        coord.hass.services.async_call.side_effect = failing
        states[LIMIT] = MockState("unknown")
    else:
        states[LIMIT] = None if bad is None else MockState(bad)
    coord.control_mode = MODE_OFF
    await switch.async_turn_off()
    assert switch.available
    assert mock_store._data[KEY] == LIMIT
    assert coord._ram_timer is not None
    await clock.advance(10)
    assert mock_store._data[KEY] == LIMIT
    assert writes(coord) == ([0, -1, -1, -1] if bad == "service" else [0])
    coord.hass.services.async_call.side_effect = successful
    states[LIMIT] = MockState("unknown")
    await clock.advance(5)
    assert writes(coord)[-1] == -1
    assert states[LIMIT].state == "-1"
    assert mock_store._data[KEY] is None
    assert coord._ram_timer is None


@pytest.mark.parametrize("silent", [False, True])
async def test_persistence_failure_prevents_unmanaged_hold(consumer, mock_store, silent):
    coord, switch, clock, _, _ = configure(consumer)
    save = mock_store.async_save
    mock_store.async_save = AsyncMock(side_effect=None if silent else OSError("disk full"))
    await switch.async_turn_on()
    for _ in range(10):
        await coord.async_request_refresh()
    assert not writes(coord)
    assert float(consumer[-1][RAM].state) == coord.charge_power
    await clock.advance(5)
    assert 0 not in writes(coord)
    mock_store.async_save = save
    await clock.advance(5)
    assert writes(coord)[-1] == 0
    assert mock_store._data[KEY] == LIMIT


async def test_release_save_failure_retries_without_losing_obligation(consumer, mock_store):
    coord, switch, clock, _, _ = configure(consumer)
    await switch.async_turn_on()
    save = mock_store.async_save
    mock_store.async_save = AsyncMock()  # HA Store can swallow disk failures.
    await switch.async_turn_off()
    assert writes(coord) == [0, -1]
    assert mock_store._data[KEY] == LIMIT
    assert coord._discharge_release_entity == LIMIT
    mock_store.async_save = save
    await clock.advance(5)
    assert writes(coord) == [0, -1, -1]
    assert mock_store._data[KEY] is None


@pytest.mark.parametrize("changed", [False, True])
async def test_restart_cleans_old_entity_before_new_hold(consumer, mock_store, changed):
    coord, _, _, _, states = configure(consumer)
    states[OTHER] = MockState("-1")
    mock_store._data = {KEY: LIMIT, "charge_hours": [[value.isoformat() for value in slot()]]}
    entry = MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: OTHER if changed else LIMIT})
    restarted = VictronChargeControlCoordinator(coord.hass, entry)
    restarted.data = coord.data
    restarted.control_mode = MODE_MANUAL
    restarted.disable_discharge = changed
    await restarted._async_load_schedule()
    coord.hass.services.async_call.reset_mock()
    await restarted._async_update_data()
    assert writes(restarted) == [-1]
    assert writes(restarted, OTHER) == ([0] if changed else [])
    assert restarted._charge_hours == [slot()]
    assert mock_store._data[KEY] == (OTHER if changed else None)
    await restarted.async_shutdown()


async def test_config_change_requires_old_cleanup_before_new_hold(consumer, mock_store):
    coord, switch, clock, _, states = configure(consumer)
    await switch.async_turn_on()
    states[LIMIT] = MockState("unavailable")
    states[OTHER] = MockState("-1")
    coord.update_entity_references({**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: OTHER})
    await clock.drain()
    assert not writes(coord, OTHER)
    assert mock_store._data[KEY] == LIMIT
    states[LIMIT] = MockState("0")
    await clock.advance(5)
    assert writes(coord) == [0, -1]
    assert writes(coord, OTHER) == [0]
    coord.update_entity_references(MOCK_CONFIG_DATA)
    await clock.drain()
    assert writes(coord, OTHER) == [0, -1]
    assert not coord.disable_discharge


@pytest.mark.parametrize("fails", [False, True])
async def test_shutdown_releases_or_leaves_durable_retry(consumer, mock_store, fails):
    coord, switch, clock, _, states = configure(consumer)
    await switch.async_turn_on()
    if fails:
        states[LIMIT] = MockState("unavailable")
    await coord.async_shutdown()
    assert mock_store._data[KEY] == (LIMIT if fails else None)
    assert writes(coord) == ([0] if fails else [0, -1])
    assert coord._ram_timer is None
    await clock.advance(20)
    assert writes(coord) == ([0] if fails else [0, -1])


@pytest.mark.parametrize("during", ["persist", "hold", "ram", "feed_in"])
async def test_off_during_await_releases_in_same_update(native_consumer, mock_store, during):
    coord, switch, clock, _, states = configure(native_consumer)
    await clock.drain()
    entered, release = asyncio.Event(), asyncio.Event()
    successful = coord.hass.services.async_call.side_effect
    save = mock_store.async_save
    if during == "persist":
        async def delayed_save(data):
            if data.get(KEY) == LIMIT:
                entered.set()
                await release.wait()
            await save(data)
        mock_store.async_save = delayed_save
    else:
        coord.charge_power = 4000
        coord.grid_feed_in_control_enabled = during == "feed_in"
        coord.default_max_grid_feed_in = 10000
        entity = {"hold": LIMIT, "ram": RAM, "feed_in": "number.max_grid_feed_in"}[during]
        async def delayed(domain, service, data, **kwargs):
            if data.get("entity_id") == entity and data.get("value") != -1:
                entered.set()
                await release.wait()
            await successful(domain, service, data, **kwargs)
        coord.hass.services.async_call.side_effect = delayed
    coord.disable_discharge = True
    update = asyncio.create_task(coord.async_refresh())
    await asyncio.wait_for(entered.wait(), 2)
    coord.control_mode = MODE_OFF
    release.set()
    await update
    await clock.drain()
    assert writes(coord) == ([] if during == "persist" else [0, -1])
    assert states[RAM].state == "0.0"
    assert mock_store._data[KEY] is None


async def test_switch_default_restore_and_enable_guard(consumer):
    coord, _, _, _, _ = consumer
    desc = next(desc for desc in SWITCHES if desc.key == "disable_discharge")
    switch = VictronCCSwitch(coord, coord.config_entry, desc)
    switch.async_write_ha_state = MagicMock()
    assert not switch.is_on
    assert not switch.available
    with pytest.raises(ServiceValidationError, match="Configure"):
        await switch.async_turn_on()
    coord, switch, _, _, states = configure(consumer)
    states[LIMIT] = MockState("unavailable")
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass", new=AsyncMock()):
        switch.async_get_last_state = AsyncMock(return_value=MockState("on"))
        await switch.async_added_to_hass()
    assert switch.is_on
    assert switch.available
    coord.last_update_success = False
    await switch.async_turn_off()
    assert not switch.is_on


@pytest.mark.parametrize("entity,error", [
    (RAM, "distinct_discharge_limit"), ("number.grid_setpoint", "distinct_discharge_limit"),
    ("number.max_grid_feed_in", "distinct_discharge_limit"), ("sensor.wrong", "number_required"),
    ("number.missing", "entity_not_found"),
])
def test_config_rejects_conflicting_or_invalid_actuators(mock_hass, entity, error):
    mock_hass.states.get.side_effect = lambda key: None if key == "number.missing" else MockState("-1")
    assert _validate_entities(mock_hass, {**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: entity}) == {CONF_MAX_DISCHARGE_POWER_ENTITY: error}
    assert STEP_USER_DATA_SCHEMA.schema[CONF_MAX_DISCHARGE_POWER_ENTITY].config["domain"] == ["number"]


async def test_no_hold_when_ha_is_stopping(consumer):
    coord, switch, _, _, _ = configure(consumer)
    coord.hass.state = CoreState.stopping
    await switch.async_turn_on()
    assert not writes(coord)


async def test_failed_initial_save_then_disable_never_changes_existing_limit(consumer, mock_store):
    coord, switch, clock, _, states = configure(consumer)
    states[LIMIT] = MockState("2500")
    save = mock_store.async_save
    mock_store.async_save = AsyncMock(side_effect=OSError("disk full"))
    await switch.async_turn_on()
    await clock.advance(5)
    await switch.async_turn_off()
    assert not writes(coord)
    assert states[LIMIT].state == "2500"
    mock_store.async_save = save
    await clock.advance(5)
    assert not writes(coord)
    assert mock_store._data[KEY] is None


async def test_store_save_queue_cannot_erase_new_release_obligation(consumer, mock_store):
    coord, switch, clock, _, _ = configure(consumer)
    entered, release = asyncio.Event(), asyncio.Event()
    save = mock_store.async_save
    calls = 0
    async def delayed(data):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        await save(data)
    mock_store.async_save = delayed
    old_save = asyncio.create_task(coord._async_save_schedule())
    await entered.wait()
    enable = asyncio.create_task(switch.async_turn_on())
    await asyncio.sleep(0)
    queued_save = asyncio.create_task(coord._async_save_schedule())
    release.set()
    await asyncio.gather(old_save, enable, queued_save)
    await clock.drain()
    assert mock_store._data[KEY] == LIMIT
    assert writes(coord) == [0]
    assert all(payload[KEY] == LIMIT for payload in mock_store.save_calls[1:])


async def test_independent_hold_and_ram_deadlines_and_event_storms(consumer):
    coord, switch, clock, _, _ = configure(consumer)
    await clock.advance(2)
    coord.hass.services.async_call.reset_mock()
    await switch.async_turn_on()
    assert writes(coord) == [0]
    for _ in range(10):
        await coord.async_request_refresh()
    assert not writes(coord, RAM)
    await clock.advance(3)  # Existing RAM deadline at t=5.
    assert writes(coord, RAM) == [3000]
    assert writes(coord) == [0]
    await clock.advance(2)  # Hold deadline at t=7, not t=10.
    assert writes(coord) == [0, 0]
    assert writes(coord, RAM) == [3000]
    await clock.advance(3)
    assert writes(coord, RAM) == [3000, 3000]
    assert writes(coord) == [0, 0]


async def test_shutdown_while_store_load_pending_cleans_restored_obligation(consumer, mock_store):
    coord, _, _, _, states = configure(consumer)
    entered, release = asyncio.Event(), asyncio.Event()
    mock_store._data = {KEY: LIMIT, "charge_hours": [[value.isoformat() for value in slot()]]}
    load = mock_store.async_load
    async def delayed_load():
        entered.set()
        await release.wait()
        return await load()
    mock_store.async_load = delayed_load
    restarted = VictronChargeControlCoordinator(coord.hass, MockConfigEntry())
    with (
        patch("custom_components.victron_charge_control.coordinator.async_track_state_change_event"),
        patch("custom_components.victron_charge_control.coordinator.async_track_time_change"),
    ):
        setup = asyncio.create_task(restarted.async_setup())
        await entered.wait()
        stop = asyncio.create_task(restarted.async_shutdown())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(setup, stop)
    assert writes(restarted) == [-1]
    assert mock_store._data[KEY] is None
    assert restarted._charge_hours == [slot()]
    assert not restarted._unsub_listeners
    assert restarted._ram_timer is None


async def test_store_load_failure_defers_hold_and_recovers_existing_cleanup(consumer, mock_store):
    coord, _, clock, _, states = configure(consumer)
    states[OTHER] = MockState("0")
    mock_store._data = {KEY: OTHER, "charge_hours": [[value.isoformat() for value in slot()]]}
    load = mock_store.async_load
    mock_store.async_load = AsyncMock(side_effect=OSError("cannot read"))
    restarted = VictronChargeControlCoordinator(coord.hass, MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: LIMIT}))
    restarted.control_mode = MODE_FORCE_CHARGE
    restarted.disable_discharge = True
    restarted.data = coord.data
    async def refresh():
        restarted.data = await restarted._async_update_data()
    restarted.async_request_refresh = AsyncMock(side_effect=refresh)
    await restarted._async_load_schedule()
    await refresh()
    assert not writes(restarted)
    assert mock_store._data[KEY] == OTHER
    mock_store.async_load = load
    await clock.advance(5)
    assert writes(restarted, OTHER) == [-1]
    assert writes(restarted) == [0]
    assert restarted._charge_hours == [slot()]
    await restarted.async_shutdown()


async def test_real_store_swallowed_write_error_prevents_hold(consumer, tmp_path):
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store
    from homeassistant.util.file import WriteError

    coord, switch, _, _, _ = configure(consumer)
    real_hass = HomeAssistant(str(tmp_path))
    coord._store = Store(real_hass, 1, "test.discharge")
    with patch.object(coord._store, "_async_write_data", new=AsyncMock(side_effect=WriteError("disk full"))):
        await switch.async_turn_on()
        assert not writes(coord)
    await switch.async_turn_off()
    assert not writes(coord)


@pytest.mark.parametrize("held", [False, True])
async def test_shutdown_drains_real_store_before_replacement(consumer, tmp_path, held):
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

    coord, switch, clock, _, states = configure(consumer)
    real_hass = HomeAssistant(str(tmp_path))
    coord._store = Store(real_hass, 1, "test.discharge")
    if held:
        await switch.async_turn_on()
    await clock.drain()
    entered, release = asyncio.Event(), asyncio.Event()
    queued_entered, queued_release = asyncio.Event(), asyncio.Event()
    write = coord._store._async_write_data
    write_count = 0

    async def delayed(data):
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            entered.set()
            await release.wait()
        elif write_count == 2:
            queued_entered.set()
            await queued_release.wait()
        await write(data)

    with patch.object(coord._store, "_async_write_data", side_effect=delayed):
        coord.set_charge_hours([slot()])
        await asyncio.wait_for(entered.wait(), 2)
        coord.set_blocked_charging_hours([18, 19])  # Accepted while the first save is in flight.
        stop = asyncio.create_task(coord.async_shutdown())
        try:
            await asyncio.sleep(0)
            assert not stop.done()
            release.set()
            await asyncio.wait_for(queued_entered.wait(), 2)
            assert not stop.done()
        finally:
            release.set()
            queued_release.set()
            await asyncio.wait_for(stop, 2)

    stored = json.loads(Path(coord._store.path).read_text())["data"]
    assert stored["charge_hours"] == [[value.isoformat() for value in slot()]]
    assert stored["blocked_charging_hours"] == [18, 19]
    assert stored[KEY] is None
    assert writes(coord) == ([0, -1] if held else [])
    restarted = VictronChargeControlCoordinator(
        coord.hass, MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_MAX_DISCHARGE_POWER_ENTITY: LIMIT})
    )
    restarted._store = Store(real_hass, 1, coord._store.key)
    restarted.control_mode = MODE_FORCE_CHARGE
    restarted.disable_discharge = True
    await restarted._async_load_schedule()
    await restarted._async_update_data()
    assert states[LIMIT].state == "0"
    assert restarted._charge_hours == [slot()]
    coord.set_discharge_hours([slot()])  # Stale callbacks cannot schedule new saves after shutdown.
    await clock.drain()
    assert json.loads(Path(restarted._store.path).read_text())["data"][KEY] == LIMIT
    await restarted.async_shutdown()


@pytest.mark.parametrize("stop", ["unload", "ha_stop"])
async def test_lifecycle_release_entrypoints(consumer, mock_store, stop):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from custom_components.victron_charge_control import async_unload_entry
    from custom_components.victron_charge_control.const import DOMAIN

    coord, switch, _, _, _ = configure(consumer)
    await switch.async_turn_on()
    if stop == "unload":
        coord.hass.data[DOMAIN] = {coord.config_entry.entry_id: coord}
        coord.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        with patch("custom_components.victron_charge_control.async_unload_services", new=AsyncMock()):
            assert await async_unload_entry(coord.hass, coord.config_entry)
    else:
        callback = next(call.args[1] for call in coord.hass.bus.async_listen_once.call_args_list
                        if call.args[0] == EVENT_HOMEASSISTANT_STOP)
        await callback(None)
    assert writes(coord) == [0, -1]
    assert mock_store._data[KEY] is None
    assert coord._ram_timer is None


async def test_slow_failed_write_is_paced_from_completion(consumer):
    coord, switch, clock, _, _ = configure(consumer)
    successful = coord.hass.services.async_call.side_effect
    async def slow_failure(domain, service, data, **kwargs):
        if data.get("entity_id") == LIMIT:
            clock.now += 6
            await asyncio.sleep(0)
            raise HomeAssistantError("slow rejection")
        await successful(domain, service, data, **kwargs)
    coord.hass.services.async_call.side_effect = slow_failure
    await switch.async_turn_on()
    assert writes(coord) == [0]
    for _ in range(10):
        await coord.async_request_refresh()
    assert writes(coord) == [0]
    coord.hass.services.async_call.side_effect = successful


@pytest.mark.parametrize("pv_next", [False, True])
async def test_quarter_boundary_releases_discharge_hold(consumer, monkeypatch, pv_next):
    coord, switch, clock, _, states = configure(consumer)
    coord.control_mode = MODE_MANUAL
    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    current = start + timedelta(minutes=14, seconds=59)
    monkeypatch.setattr(dt_util, "now", lambda: current)
    coord._charge_hours = [(start, start + timedelta(minutes=15))]
    if pv_next:
        coord._pv_charge_hours = [(start+timedelta(minutes=15), start+timedelta(minutes=30))]
    await switch.async_turn_on()
    assert writes(coord)[-1] == 0
    current = start + timedelta(minutes=15)
    await coord.async_request_refresh()
    assert writes(coord)[-1] == -1
    assert coord._discharge_release_entity is None
    before = len(writes(coord))
    await clock.advance(5)
    assert len(writes(coord)) == before
