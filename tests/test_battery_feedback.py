
from tests.slots import utc_slot
"""Battery feedback sampling, successful-write baselines, and safe fallbacks."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.victron_charge_control.config_flow import (
    STEP_USER_DATA_SCHEMA, _validate_entities,
)
from custom_components.victron_charge_control.const import (
    ACTION_CHARGE, ACTION_DISCHARGE, ACTION_IDLE, ACTION_PV_CHARGE,
    CONF_BATTERY_POWER_ENTITY,
    MODE_FORCE_CHARGE, MODE_FORCE_DISCHARGE, MODE_MANUAL, MODE_OFF,
)
from custom_components.victron_charge_control.coordinator import VictronChargeControlCoordinator
from custom_components.victron_charge_control.decision import compute_setpoint
from custom_components.victron_charge_control.switch import SWITCHES, VictronCCSwitch

from .conftest import MOCK_CONFIG_DATA, MockConfigEntry, MockState
from .test_grid_consumer import Clock

BATTERY = "sensor.battery_power"
RAM = "number.ac_grid_setpoint"
BASE = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
async def feedback(mock_hass):
    states = {
        "sensor.battery_soc": MockState("50"),
        RAM: MockState("0"),
        "number.grid_setpoint": MockState("0"),
        "sensor.epex_spot": MockState("5", {"unit_of_measurement": "ct/kWh"}),
        "number.max_grid_feed_in": MockState("15000"),
    }
    mock_hass.states.get.side_effect = states.get
    clock = Clock(mock_hass)
    listeners = []

    def subscribe(hass, entities, callback):
        listener = [entities, callback, True]
        listeners.append(listener)
        return lambda: listener.__setitem__(2, False)

    def report(value="2000", unit="W", *, age=0, source=BATTERY, notify=True):
        stamp = BASE + timedelta(seconds=clock.now - age)
        states[source] = None if value is None else State(
            source, value, {"unit_of_measurement": unit, "device_class": "power"},
            last_reported=stamp, last_changed=BASE, last_updated=BASE,
        )
        if notify:
            for entities, callback, active in listeners:
                if active and source in entities:
                    callback(None)

    report(notify=False)
    entry = MockConfigEntry(data={**MOCK_CONFIG_DATA, CONF_BATTERY_POWER_ENTITY: BATTERY})
    coord = VictronChargeControlCoordinator(mock_hass, entry)
    coord.action_confirm_seconds = 0
    coord.control_mode = MODE_FORCE_CHARGE
    coord.max_grid_setpoint = 10000
    coord.min_grid_setpoint = -10000

    async def write(domain, service, data, **kwargs):
        if domain == "number":
            states[data["entity_id"]] = MockState(str(data["value"]))

    mock_hass.services.async_call.side_effect = write

    async def refresh():
        coord.data = await coord._async_update_data()
        coord.async_update_listeners()

    coord.async_request_refresh = AsyncMock(side_effect=refresh)
    desc = next(item for item in SWITCHES if item.key == "battery_power_control_enabled")
    switch = VictronCCSwitch(coord, entry, desc)
    switch.async_write_ha_state = MagicMock()
    with (
        patch("custom_components.victron_charge_control.coordinator.async_track_state_change_event", side_effect=subscribe),
        patch("custom_components.victron_charge_control.coordinator.async_track_time_change"),
        patch("custom_components.victron_charge_control.coordinator.dt_util.utcnow", side_effect=lambda: BASE + timedelta(seconds=clock.now)),
        patch("custom_components.victron_charge_control.coordinator.dt_util.now", side_effect=lambda: BASE + timedelta(seconds=clock.now)),
    ):
        await coord.async_setup()
        yield coord, switch, clock, report, states, listeners
        await coord.async_shutdown()
        await clock.drain()
        assert all(not listener[2] for listener in listeners)


async def settled(feedback, value="2000", unit="W"):
    coord, switch, clock, report, _, _ = feedback
    await switch.async_turn_on()
    await clock.advance(5)
    report(value, unit)
    await coord.async_request_refresh()
    return coord.data.target_setpoint


@pytest.mark.parametrize("measured,unit,target", [("2000", "W", 4000), ("2", "kW", 4000), ("-2000", "W", 8000)])
async def test_charge_arithmetic_and_signed_units(feedback, measured, unit, target):
    coord, switch, _, _, _, _ = feedback
    assert await settled(feedback, measured, unit) == target
    assert coord.data.setpoint_calculation == {
        "setting_w": 3000, "battery_feedback_w": target - 3000,
        "pv_charge_w": 0, "surplus_w": 0, "grid_consumer_w": 0, "limits_w": 0,
    }
    assert switch.extra_state_attributes == {
        "source_entity": BATTERY, "power_w": float(measured) * (1000 if unit == "kW" else 1),
        "feedback_status": "active",
    }


async def test_reports_consumed_once_settle_from_write_and_equal_values_are_new(feedback):
    coord, switch, clock, report, _, _ = feedback
    await switch.async_turn_on()
    assert coord.data.target_setpoint == 3000
    assert switch.extra_state_attributes["feedback_status"] == "waiting"
    await clock.advance(4)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 3000
    await clock.advance(1)
    # A pre-settling report never becomes eligible just by waiting.
    assert coord.data.target_setpoint == 3000
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    await clock.advance(10)
    assert coord.data.target_setpoint == 4000
    report()  # same value, new last_reported; unchanged keepalives did not postpone settling
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 5000
    for _ in range(3):
        await coord.async_request_refresh()
    assert coord.data.target_setpoint == 5000


async def test_consumption_uses_last_reported_not_last_changed(feedback):
    coord, _, clock, report, states, _ = feedback
    await settled(feedback)
    await clock.advance(5)
    report("3000")
    assert states[BATTERY].last_changed == BASE
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    await clock.advance(5)
    # HA mutates last_reported on a repeated report without a state_changed event.
    states[BATTERY].last_reported = BASE + timedelta(seconds=clock.now)
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    assert coord._battery_last_report == states[BATTERY].last_reported


async def test_solar_load_changes_and_consumer_not_double_counted(feedback):
    coord, _, clock, report, _, _ = feedback
    coord._grid_consumer_offset = 700
    coord._solar_surplus_entity = "sensor.solar"
    coord._solar_surplus_mean = 2000
    # Legacy baseline includes the consumer; feedback must then replace both terms.
    assert await settled(feedback, "3000") == 3700
    for measured, target in [("2000", 4700), ("6000", 1700), ("5000", -300)]:
        await clock.advance(5)
        report(measured)
        await coord.async_request_refresh()
        assert coord.data.target_setpoint == target
        terms = coord.data.setpoint_calculation
        assert terms["grid_consumer_w"] == terms["surplus_w"] == terms["pv_charge_w"] == 0
        assert sum(terms.values()) == target


@pytest.mark.parametrize("value,unit", [(None,"W"), ("unavailable","W"), ("unknown","W"), ("bad","W"), ("nan","W"), ("inf","W"), ("-inf","W"), ("2","MW"), ("1e308","kW")])
async def test_invalid_reports_prompt_legacy_fallback_and_recover(feedback, value, unit):
    coord, switch, clock, report, states, _ = feedback
    await settled(feedback)
    report(value, unit)
    await clock.drain()
    assert coord.data.target_setpoint == 3000
    assert coord.control_mode == MODE_FORCE_CHARGE
    assert switch.available
    assert switch.extra_state_attributes["feedback_status"] == "fallback"
    assert switch.extra_state_attributes["power_w"] is None
    report("2000")
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 3000
    assert coord.battery_feedback_status == "waiting"
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    assert float(states[RAM].state) == 4000


async def test_stale_reports_clear_feedback_on_existing_timer(feedback):
    coord, _, clock, report, _, _ = feedback
    await settled(feedback)
    await clock.advance(120)
    assert coord.battery_feedback_status == "active"  # Exactly 120 seconds is accepted.
    await clock.advance(5)
    assert coord.battery_feedback_status == "fallback"
    assert coord.data.target_setpoint == 3000
    report()
    await clock.advance(5)
    assert coord.battery_feedback_status == "waiting"
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000


async def test_failed_write_retries_target_without_new_correction(feedback):
    coord, switch, clock, report, states, _ = feedback
    await switch.async_turn_on()
    successful = coord.hass.services.async_call.side_effect
    coord.hass.services.async_call.side_effect = HomeAssistantError("offline")
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    assert coord._battery_baseline == 3000
    await clock.advance(5)
    report("1000")
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    coord.hass.services.async_call.side_effect = successful
    await coord.async_request_refresh()
    assert float(states[RAM].state) == 4000
    await clock.advance(5)
    # Report from before successful write must not correct its baseline.
    assert coord.data.target_setpoint == 4000
    report("3000")
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000


async def test_lagging_ram_echo_is_not_feedback_baseline(feedback):
    coord, _, clock, report, states, _ = feedback
    await settled(feedback)
    states[RAM] = MockState("3000")
    coord.hass.services.async_call.side_effect = None  # successful writes, delayed echo
    await clock.advance(5)
    report("3000")
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    assert coord._battery_baseline == 4000


@pytest.mark.parametrize("mode,measured,expected", [(MODE_FORCE_CHARGE,"6000",-500), (MODE_FORCE_DISCHARGE,"-2000",-500)])
async def test_reduced_export_limit_also_applies_during_charge(feedback, mode, measured, expected):
    coord, _, clock, report, _, _ = feedback
    coord.control_mode = mode
    await settled(feedback, measured)
    coord.grid_feed_in_control_enabled = True
    coord.grid_feed_in_price_threshold = 10
    coord.reduced_max_grid_feed_in = 500
    await clock.advance(5)
    report(measured)
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == expected
    assert sum(coord.data.setpoint_calculation.values()) == expected


async def test_saturation_uses_clamped_successful_baseline_and_recovers(feedback):
    coord, _, clock, report, _, _ = feedback
    coord.max_grid_setpoint = 3500
    assert await settled(feedback) == 3500
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 3500
    await clock.advance(5)
    report("4000")
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 2500


@pytest.mark.parametrize("action,solar_only", [(ACTION_IDLE,False),(ACTION_PV_CHARGE,False),(ACTION_DISCHARGE,True)])
def test_pure_helper_ignores_feedback_for_excluded_actions(action, solar_only):
    args = dict(
        charge_power=3000, discharge_power=3000, idle_setpoint=50,
        min_grid_setpoint=-10000, max_grid_setpoint=10000,
        charge_blocked_by_soc=False, discharge_solar_only=solar_only,
        solar_surplus_mean=2000, pv_charge_share=50,
        reduced_max_grid_feed_in=500, grid_consumer_offset=750,
    )
    calculation = {}
    assert compute_setpoint(action, **args, battery_feedback=(3000,2000),calculation=calculation) == compute_setpoint(action, **args)
    assert calculation["battery_feedback_w"] == 0


@pytest.mark.parametrize("mode,soc,action", [(MODE_FORCE_CHARGE,"100",ACTION_IDLE),(MODE_FORCE_DISCHARGE,"10",ACTION_IDLE),(MODE_FORCE_DISCHARGE,"20",ACTION_DISCHARGE)])
async def test_soc_protection_wins_and_solar_only_exits_feedback(feedback, mode, soc, action):
    coord, _, _, _, states, _ = feedback
    coord.control_mode = mode
    coord.min_soc = 20
    coord._solar_surplus_entity = "sensor.solar"
    states["sensor.solar"] = MockState("1000", {"unit_of_measurement":"W"})
    await settled(feedback, "-2000" if mode == MODE_FORCE_DISCHARGE else "2000")
    states["sensor.battery_soc"] = MockState(soc)
    await coord.async_request_refresh()
    assert coord.data.desired_action == action
    assert coord.battery_feedback_status == "inactive"
    assert coord.data.setpoint_calculation["battery_feedback_w"] == 0


async def test_disable_and_reference_replacement_clear_even_inside_deadband(feedback):
    coord, switch, clock, report, states, listeners = feedback
    assert await settled(feedback, "2999") == 3001
    await switch.async_turn_off()
    assert float(states[RAM].state) == 3000
    assert coord.battery_feedback_status == "disabled"
    await settled(feedback)
    report("2000", source="sensor.new")
    old = next(listener for listener in listeners if listener[0] == [BATTERY])
    coord.update_entity_references({**MOCK_CONFIG_DATA, CONF_BATTERY_POWER_ENTITY:"sensor.new"})
    await clock.drain()
    assert not old[2]
    assert coord.data.target_setpoint == 3000
    assert coord.battery_feedback_status == "waiting"
    await clock.advance(5)
    report("2000", source="sensor.new")
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000
    coord.update_entity_references(MOCK_CONFIG_DATA)
    await clock.drain()
    assert not switch.is_on
    assert coord.data.target_setpoint == 3000


@pytest.mark.parametrize("change", ["disable", "remove", "invalid", "soc", "off", "settings"])
async def test_in_flight_write_cannot_reinstate_stale_feedback(feedback, change):
    coord, switch, clock, report, states, _ = feedback
    await switch.async_turn_on()
    await clock.advance(5)
    successful = coord.hass.services.async_call.side_effect
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(domain, service, data, **kwargs):
        if data.get("entity_id") == RAM and data["value"] == 4000:
            started.set()
            await release.wait()
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = delayed
    report()
    task = asyncio.create_task(coord.async_request_refresh())
    await asyncio.wait_for(started.wait(), 1)
    if change == "disable":
        coord.battery_power_control_enabled = False
    elif change == "remove":
        coord.update_entity_references(MOCK_CONFIG_DATA)
    elif change == "invalid":
        report("unavailable")
    elif change == "soc":
        states["sensor.battery_soc"] = MockState("100")
    elif change == "settings":
        coord.charge_power = 2500
    else:
        coord.control_mode = MODE_OFF
    release.set()
    await task
    await clock.drain()
    expected = coord.idle_setpoint if change in ("soc", "off") else 3500 if change == "settings" else 3000
    assert float(states[RAM].state) == expected
    assert coord.data.target_setpoint == expected
    if change != "settings":
        assert coord._battery_feedback is None


async def test_switch_restore_does_not_restore_feedback_and_disable_survives_outage(feedback):
    coord, switch, _, report, _, _ = feedback
    assert not switch.is_on
    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()),
        patch.object(switch, "async_get_last_state", return_value=MockState("on")),
    ):
        await switch.async_added_to_hass()
    assert switch.is_on
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 3000
    assert coord.battery_feedback_status == "waiting"
    report("unavailable")
    coord.last_update_success = False
    assert switch.available
    await switch.async_turn_off()
    assert not switch.is_on
    coord.update_entity_references(MOCK_CONFIG_DATA)
    with pytest.raises(ServiceValidationError, match="Configure"):
        await switch.async_turn_on()


@pytest.mark.parametrize("entity,unit,device_class,error", [(BATTERY,"W","power",None),(BATTERY,"kW","power",None),(BATTERY,"MW","power","battery_power_required"),(BATTERY,"W","energy","battery_power_required"),("number.battery","W","power","battery_power_required")])
def test_battery_selector_validation(mock_hass, entity, unit, device_class, error):
    mock_hass.states.get.return_value = MockState("unavailable",{"unit_of_measurement":unit,"device_class":device_class})
    result = _validate_entities(mock_hass,{**MOCK_CONFIG_DATA, CONF_BATTERY_POWER_ENTITY:entity})
    assert result == ({CONF_BATTERY_POWER_ENTITY:error} if error else {})
    selector = STEP_USER_DATA_SCHEMA.schema[CONF_BATTERY_POWER_ENTITY]
    assert selector.config["domain"] == ["sensor"]
    assert selector.config["device_class"] == ["power"]


@pytest.mark.parametrize("measured,expected", [("-2000", -4000), ("-4000", -2000), ("1000", -7000)])
async def test_full_discharge_signs(feedback, measured, expected):
    coord, switch, clock, report, _, _ = feedback
    coord.control_mode = MODE_FORCE_DISCHARGE
    # Let the existing action debounce publish discharge before establishing its baseline.
    await coord.async_request_refresh()
    await coord.async_request_refresh()
    await switch.async_turn_on()
    assert coord.data.target_setpoint == -3000
    await clock.advance(5)
    report(measured)
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == expected
    assert coord.data.setpoint_calculation["setting_w"] == -3000


@pytest.mark.parametrize("action", [ACTION_IDLE, ACTION_PV_CHARGE])
async def test_leaving_eligible_action_resets_and_reentry_waits(feedback, action):
    coord, _, clock, report, states, _ = feedback
    coord.control_mode = MODE_MANUAL
    coord._charge_hours = [utc_slot("2026-11-03", 12)]
    await settled(feedback)
    assert coord.battery_feedback_status == "active"
    coord._charge_hours = []
    if action == ACTION_PV_CHARGE:
        coord._solar_surplus_entity = "sensor.solar"
        states["sensor.solar"] = MockState("1000", {"unit_of_measurement":"W"})
        coord._pv_charge_hours = [utc_slot("2026-11-03", 12)]
    await coord.async_request_refresh()
    await coord.async_request_refresh()
    assert coord.data.desired_action == action
    assert coord.battery_feedback_status == "inactive"
    assert coord.data.setpoint_calculation["battery_feedback_w"] == 0
    coord._pv_charge_hours = []
    coord._charge_hours = [utc_slot("2026-11-03", 12)]
    await coord.async_request_refresh()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 3000
    assert coord.battery_feedback_status == "waiting"
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000


async def test_no_feedback_until_first_successful_baseline(feedback):
    coord, switch, clock, report, _, _ = feedback
    successful = coord.hass.services.async_call.side_effect
    coord.hass.services.async_call.side_effect = HomeAssistantError("offline")
    await switch.async_turn_on()
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.battery_feedback_status == "waiting"
    assert coord.data.target_setpoint == 3000
    coord.hass.services.async_call.side_effect = successful
    await coord.async_request_refresh()
    await clock.advance(5)
    assert coord.data.target_setpoint == 3000
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000


async def test_reset_correction_retries_after_failed_clear(feedback):
    coord, switch, clock, _, states, _ = feedback
    await settled(feedback,"2999")
    successful = coord.hass.services.async_call.side_effect
    coord.hass.services.async_call.side_effect = HomeAssistantError("offline")
    await switch.async_turn_off()
    assert float(states[RAM].state) == 3001
    coord.hass.services.async_call.side_effect = successful
    await clock.advance(5)
    assert float(states[RAM].state) == 3000


async def test_failed_permanent_fallback_discards_feedback(feedback):
    coord, _, clock, report, states, _ = feedback
    await settled(feedback)
    successful = coord.hass.services.async_call.side_effect
    states["number.grid_setpoint"] = MockState("900")

    async def failed_fallback(domain, service, data, **kwargs):
        if data.get("entity_id") == "number.grid_setpoint":
            raise HomeAssistantError("offline")
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = failed_fallback
    await coord.async_request_refresh()
    assert float(states[RAM].state) == coord.idle_setpoint
    assert coord._battery_feedback is None
    assert coord._battery_baseline is None
    coord.hass.services.async_call.side_effect = successful
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 3000
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert coord.data.target_setpoint == 4000


async def test_restart_preserves_plan_and_only_restores_switch(feedback, mock_store):
    coord, switch, _, _, _, _ = feedback
    await settled(feedback)
    coord._charge_hours = [utc_slot("2026-11-03", 13)]
    await coord._async_save_schedule()
    saved = mock_store._data.copy()
    replacement = VictronChargeControlCoordinator(coord.hass, coord.config_entry)
    desc = switch.entity_description
    restored = VictronCCSwitch(replacement, coord.config_entry, desc)
    with (
        patch.object(CoordinatorEntity,"async_added_to_hass",new=AsyncMock()),
        patch.object(restored,"async_get_last_state",return_value=MockState("on")),
    ):
        await restored.async_added_to_hass()
    await replacement._async_load_schedule()
    assert restored.is_on
    assert replacement._battery_baseline is None
    assert replacement._battery_feedback is None
    assert replacement._charge_hours == [utc_slot("2026-11-03", 13)]
    assert mock_store._data == saved


async def test_actuator_reference_change_during_write_needs_new_baseline(feedback):
    coord, switch, clock, report, states, _ = feedback
    await switch.async_turn_on()
    await clock.advance(5)
    successful = coord.hass.services.async_call.side_effect
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(domain, service, data, **kwargs):
        if data.get("entity_id") == RAM and data["value"] == 4000:
            started.set()
            await release.wait()
        await successful(domain, service, data, **kwargs)

    coord.hass.services.async_call.side_effect = delayed
    report()
    task = asyncio.create_task(coord.async_request_refresh())
    await asyncio.wait_for(started.wait(), 1)
    states["number.new_ram"] = MockState("unknown")
    coord.update_entity_references({
        **MOCK_CONFIG_DATA, CONF_BATTERY_POWER_ENTITY: BATTERY,
        "ac_grid_setpoint_entity": "number.new_ram",
    })
    release.set()
    await task
    await clock.drain()
    assert coord.data.target_setpoint == 3000
    assert float(states["number.new_ram"].state) == 3000
    assert coord.battery_feedback_status == "waiting"
    await clock.advance(5)
    report()
    await coord.async_request_refresh()
    assert float(states["number.new_ram"].state) == 4000
