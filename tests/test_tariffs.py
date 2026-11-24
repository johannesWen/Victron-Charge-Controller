"""Exercise tariff settings and History through Home Assistant."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest

from homeassistant import auth, loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreStateData
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components import victron_charge_control
from custom_components.victron_charge_control.const import CONF_REPLAN_TARIFFS, DOMAIN
from custom_components.victron_charge_control.sensor import GridEnergyCostSensor

from .conftest import MOCK_CONFIG_DATA_WITH_COST

BUY = "text.victron_charge_control_buy_price"
SELL = "text.victron_charge_control_sell_price"
PLAN = "sensor.victron_charge_control_charge_plan"
RATE = "sensor.victron_charge_control_current_price"


@pytest.fixture
def start_hass(tmp_path, monkeypatch, unused_tcp_port):
    """Start an isolated HA instance with simulated meter and setpoint entities."""
    monkeypatch.setattr(victron_charge_control, "_async_register_card", AsyncMock())
    (tmp_path / "custom_components").symlink_to(
        Path(__file__).resolve().parents[1] / "custom_components",
        target_is_directory=True,
    )

    @asynccontextmanager
    async def start(
        import_kwh, export_kwh, price, *, pricing=None, sell_back=None, with_intervals=False, max_discharge_power=-1,
    ):
        hass = HomeAssistant(str(tmp_path))
        hass.config.skip_pip = True
        loader.async_setup(hass)
        hass.config_entries = ConfigEntries(hass, {})
        await loader.async_get_custom_components(hass)
        assert await async_load_base_functionality(hass)
        hass.auth = await auth.auth_manager_from_config(hass, [], [])

        hass.states.async_set("sensor.battery_soc", "50")
        hass.states.async_set("number.grid_setpoint", "0")
        hass.states.async_set("number.ac_grid_setpoint", "0")
        hass.states.async_set("number.max_grid_feed_in", "5000")
        hass.states.async_set("number.max_discharge_power", str(max_discharge_power))
        hass.states.async_set("sensor.grid_consumption_kwh", str(import_kwh))
        hass.states.async_set("sensor.grid_feed_in_kwh", str(export_kwh))
        hass.states.async_set("sensor.epex_spot", price, {"unit_of_measurement": "ct/kWh"})
        if with_intervals:
            publish_intervals(hass)
        if sell_back is not None:
            hass.states.async_set("sensor.sell_back", sell_back, {"unit_of_measurement": "EUR/kWh"})

        async def set_number(call):
            hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

        assert await async_setup_component(hass, "http", {
            "http": {"server_host": "127.0.0.1", "server_port": unused_tcp_port},
        })
        assert await async_setup_component(hass, "number", {})
        hass.services.async_register("number", "set_value", set_number)
        entry = None
        try:
            if pricing is not None:
                flow = hass.config_entries.flow
                form = await flow.async_init(DOMAIN, context={"source": "user"})
                result = await flow.async_configure(form["flow_id"], {
                    **MOCK_CONFIG_DATA_WITH_COST, **pricing,
                })
                assert result["type"] == "create_entry"
                entry = result["result"]
            elif not hass.config_entries.async_entries(DOMAIN):
                entry = ConfigEntry(
                    domain=DOMAIN, title="Victron Charge Control",
                    data=MOCK_CONFIG_DATA_WITH_COST, options={"use_solcast_forecast": False},
                    version=1, minor_version=1, source="user", unique_id=DOMAIN,
                    discovery_keys=MappingProxyType({}), subentries_data=None,
                )
                await hass.config_entries.async_add(entry)
            else:
                entry, = hass.config_entries.async_entries(DOMAIN)
                assert await hass.config_entries.async_setup(entry.entry_id)
            assert entry.state is ConfigEntryState.LOADED
            coordinator = hass.data[DOMAIN][entry.entry_id]
            await coordinator.async_refresh()
            yield hass, coordinator
        finally:
            if hass.state is not CoreState.stopped:
                if entry is not None and entry.state is ConfigEntryState.LOADED:
                    await RestoreStateData.async_save_persistent_states(hass)
                    await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_stop(force=True)

    return start


def _history(hass):
    """Get the published cumulative cost, revenue, import and export."""
    return tuple(
        float(hass.states.get(f"sensor.victron_charge_control_grid_energy_{suffix}").state)
        for suffix in ("cost", "revenue", "import", "export")
    )


async def set_tariff(hass, entity_id, value):
    await hass.services.async_call(
        "text", "set_value", {"entity_id": entity_id, "value": value}, blocking=True,
    )


async def select_mode(hass, mode):
    await hass.services.async_call("select", "select_option", {
        "entity_id": "select.victron_charge_control_control_mode", "option": mode,
    }, blocking=True)


def publish_intervals(hass, entity_id="sensor.epex_spot"):
    tomorrow = (dt_util.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    periods = [
        {"start_time": (tomorrow + timedelta(hours=i)).isoformat(), "price_ct_per_kwh": price}
        for i, price in enumerate((5, 15))
    ]
    hass.states.async_set(entity_id, "5", {"unit_of_measurement": "ct/kWh", "data": periods})


def priced_actions(hass):
    return [p["action"] for p in hass.states.get(PLAN).attributes["plan"] if "price" in p]


async def test_same_market_input_values_import_and_export_independently(start_hass):
    pricing = {"import_price_formula": "(price + 10 + 2) * 1.21"}
    async with start_hass(100, 20, "8", pricing=pricing) as (hass, coordinator):
        hass.states.async_set("sensor.grid_consumption_kwh", "101")
        hass.states.async_set("sensor.grid_feed_in_kwh", "21")
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0.242, 0.08, 1, 1))
        rates = hass.states.get("sensor.victron_charge_control_current_price").attributes
        assert rates["import_price_eur_per_kwh"] == pytest.approx(0.242)
        assert rates["export_price_eur_per_kwh"] == pytest.approx(0.08)

        hass.states.async_set("sensor.epex_spot", "-0.02", {"unit_of_measurement": "EUR/kWh"})
        hass.states.async_set("sensor.grid_consumption_kwh", "102")
        hass.states.async_set("sensor.grid_feed_in_kwh", "22")
        await coordinator.async_refresh()
        # Negative export adds to gross cost, alongside the adjusted import price.
        assert _history(hass) == pytest.approx((0.242 + 0.121 + 0.02, 0.08, 2, 2))


async def test_second_epex_entry_and_fixed_buy_formula(start_hass):
    pricing = {"epex_export_entity": "sensor.sell_back", "export_price_formula": "price / 2"}
    async with start_hass(100, 20, "30", pricing=pricing, sell_back="0.08") as (hass, coordinator):
        await hass.services.async_call("text", "set_value", {
            "entity_id": "text.victron_charge_control_buy_price", "value": "0",
        }, blocking=True)
        hass.states.async_set("sensor.grid_consumption_kwh", "101")
        hass.states.async_set("sensor.grid_feed_in_kwh", "21")
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0, 0.04, 1, 1))
        hass.states.async_set("sensor.sell_back", "unavailable")
        hass.states.async_set("sensor.grid_feed_in_kwh", "22")
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0, 0.04, 1, 2))
        assert coordinator.data.export_price_eur_per_kwh is None


async def test_history_tariffs_apply_to_new_deltas_and_survive_restart(start_hass, monkeypatch):
    buy, sell = BUY, SELL

    async with start_hass(100, 20, "20") as (hass, coordinator):
        assert set(hass.states.async_entity_ids("text")) == {
            buy, sell, "text.victron_charge_control_blocked_charging_hours",
            "text.victron_charge_control_blocked_discharging_hours",
            "text.victron_charge_control_replan_hours",
        }
        for entity_id in (buy, sell):
            state = hass.states.get(entity_id)
            assert state.state == ""
            assert state.attributes["unit_of_measurement"] == "ct/kWh"
            assert state.attributes["min"] == 0

        hass.states.async_set("sensor.grid_consumption_kwh", "102")
        hass.states.async_set("sensor.grid_feed_in_kwh", "21")
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0.40, 0.20, 2, 1))

        await set_tariff(hass, buy, " +12.50 ")
        await set_tariff(hass, sell, "-5.5")
        for invalid in ("NaN", "-Infinity", "3,5", "1 / 0", "round(price)", "4 €/kWh"):
            with pytest.raises(ServiceValidationError):
                await set_tariff(hass, buy, invalid)
        assert hass.states.get(buy).state == "+12.50"
        assert hass.states.get(sell).state == "-5.5"
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0.40, 0.20, 2, 1))
        assert coordinator.data.current_price_eur_per_kwh == 0.125

        hass.states.async_set("sensor.grid_consumption_kwh", "104")
        hass.states.async_set("sensor.grid_feed_in_kwh", "22")
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0.705, 0.20, 4, 2))

    restore_cost = GridEnergyCostSensor.async_added_to_hass

    async def restore_with_early_refresh(sensor):
        # A startup refresh can land while the sensor and text platforms restore.
        if sensor.translation_key == "grid_energy_revenue":
            await sensor.coordinator.async_refresh()
        await restore_cost(sensor)

    monkeypatch.setattr(GridEnergyCostSensor, "async_added_to_hass", restore_with_early_refresh)
    async with start_hass(105, 23, "unavailable") as (hass, coordinator):
        assert hass.states.get(buy).state == "+12.50"
        assert hass.states.get(sell).state == "-5.5"
        assert _history(hass) == pytest.approx((0.885, 0.20, 5, 3))
        assert coordinator.data.current_price_eur_per_kwh == 0.125
        assert not priced_actions(hass)

        await set_tariff(hass, buy, "0")
        await set_tariff(hass, sell, "")
        assert hass.states.get(buy).state == "0"
        assert hass.states.get(sell).state == ""
        assert _history(hass) == pytest.approx((0.885, 0.20, 5, 3))

    async with start_hass(106, 24, "40") as (hass, _):
        assert hass.states.get(buy).state == "0"
        assert hass.states.get(sell).state == ""
        assert _history(hass) == pytest.approx((0.885, 0.60, 6, 4))


@pytest.mark.parametrize("route", ["text", "options", "reconfigure"])
async def test_tariff_edits_replan_auto_and_publish_rates(start_hass, route):
    initial = {"import_price_formula": "price + 20", "export_price_formula": "0"}
    async with start_hass(100, 20, "5", pricing=initial) as (hass, coordinator):
        publish_intervals(hass)
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        assert priced_actions(hass) == ["idle", "idle"]
        entry = coordinator.config_entry
        updated = {"import_price_formula": "price", "export_price_formula": "price + 8"}
        if route == "text":
            await set_tariff(hass, BUY, "price")
            await set_tariff(hass, SELL, "price + 8")
            form = await hass.config_entries.options.async_init(entry.entry_id)
            for field in form["data_schema"].schema:
                if field.schema in updated:
                    assert field.description["suggested_value"] == updated[field.schema]
        else:
            if route == "options":
                flow = hass.config_entries.options
                form = await flow.async_init(entry.entry_id)
            else:
                flow = hass.config_entries.flow
                form = await flow.async_init(DOMAIN, context={"source": route, "entry_id": entry.entry_id})
            result = await flow.async_configure(form["flow_id"], {**entry.data, **updated})
            assert result["type"] == ("create_entry" if route == "options" else "abort")
            await hass.async_block_till_done()
        assert hass.states.get(BUY).state == entry.data["import_price_formula"] == "price"
        assert hass.states.get(SELL).state == entry.data["export_price_formula"] == "price + 8"
        assert CONF_REPLAN_TARIFFS not in entry.data
        assert priced_actions(hass) == ["charge", "discharge"]
        rates = hass.states.get(RATE).attributes
        assert rates["import_price_eur_per_kwh"] == 0.05
        assert rates["export_price_eur_per_kwh"] == 0.13

        await select_mode(hass, "manual")
        await set_tariff(hass, BUY, "+0025")
        await set_tariff(hass, SELL, "")
        assert float(hass.states.get(BUY).state) == 25
        assert "export_price_formula" not in entry.data
        assert priced_actions(hass) == ["charge", "discharge"]


@pytest.mark.parametrize("restart_after_migration", [False, True])
async def test_legacy_fixed_input_migrates_before_first_delta(start_hass, restart_after_migration):
    renamed = "text.custom_buy_rate"
    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        entry = coordinator.config_entry
        registry = er.async_get(hass)
        unique_id = registry.async_get(BUY).unique_id
        registry.async_update_entity(BUY, new_entity_id=renamed)
        await select_mode(hass, "auto")
        await hass.services.async_call(DOMAIN, "set_fixed_plan_hour", {
            "plan": 1, "hour": 10, "action": "pv_charge",
        }, blocking=True)
        await hass.services.async_call("select", "select_option", {
            "entity_id": "select.victron_charge_control_active_fixed_plan", "option": "1",
        }, blocking=True)
        hass.states.async_set("sensor.grid_consumption_kwh", "102")
        hass.states.async_set("sensor.grid_feed_in_kwh", "21")
        await coordinator.async_refresh()
        assert priced_actions(hass) == ["pv_charge", "idle"]
        assert _history(hass) == pytest.approx((0.10, 0.05, 2, 1))
        # Recreate an existing installation awaiting its first startup after the upgrade.
        hass.config_entries.async_update_entry(entry, minor_version=1, data={
            **entry.data, "import_price_formula": " ", "export_price_formula": "price - 1",
        }, options={**entry.options, "buy_price": "-0012", "sell_price": "99", "other": 42})
        if restart_after_migration:
            # Setup can fail after HA has already saved the migrated config entry.
            assert await victron_charge_control.async_migrate_entry(hass, entry)

    async with start_hass(103, 22, "5", with_intervals=True) as (hass, coordinator):
        entry = coordinator.config_entry
        assert er.async_get(hass).async_get(renamed).unique_id == unique_id
        assert float(hass.states.get(renamed).state) == -12
        assert hass.states.get(SELL).state == "price - 1"
        assert entry.minor_version == 2
        assert CONF_REPLAN_TARIFFS not in entry.data
        assert entry.options == {"use_solcast_forecast": False, "other": 42}
        assert _history(hass) == pytest.approx((0.10, 0.21, 3, 2))
        assert priced_actions(hass) == ["pv_charge", "charge"]
        await set_tariff(hass, renamed, "")
        assert "import_price_formula" not in entry.data

    async with start_hass(104, 23, "10") as (hass, _):
        assert hass.states.get(renamed).state == ""
        assert _history(hass) == pytest.approx((0.20, 0.30, 4, 3))


@pytest.mark.parametrize("already_pending", [False, True])
async def test_options_save_during_inflight_refresh_prices_next_reading_once(start_hass, monkeypatch, already_pending):
    async with start_hass(100, 20, "5") as (hass, coordinator):
        if already_pending:
            await select_mode(hass, "auto")
            await set_tariff(hass, BUY, "10")
            assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
        entered, released = asyncio.Event(), asyncio.Event()

        async def slow_write(**kwargs):
            entered.set()
            await released.wait()

        monkeypatch.setattr(coordinator, "_apply_dc_coupled_feed_in", slow_write)
        running = hass.async_create_task(coordinator.async_refresh())
        await asyncio.wait_for(entered.wait(), 2)
        entry = coordinator.config_entry
        flow = hass.config_entries.options
        try:
            form = await flow.async_init(entry.entry_id)
            result = await flow.async_configure(form["flow_id"], {
                **MOCK_CONFIG_DATA_WITH_COST, "import_price_formula": "25",
            })
            assert result["type"] == "create_entry"
            hass.states.async_set("sensor.grid_consumption_kwh", "101")
        finally:
            released.set()
        await running
        await hass.async_block_till_done()
        assert _history(hass) == pytest.approx((0.25, 0, 1, 0))


@pytest.mark.parametrize("mode_after_restart", ["auto", "manual"])
async def test_pending_tariff_recovers_on_forecast_event_after_restart(start_hass, mock_store, mode_after_restart):
    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        assert priced_actions(hass) == ["charge", "idle"]
        await hass.async_block_till_done()
        writes = len(mock_store.save_calls)
        hass.states.async_set("sensor.epex_spot", "unavailable")
        await set_tariff(hass, BUY, "0")
        await coordinator.async_refresh()
        assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
        assert not priced_actions(hass)
        assert len(coordinator.charge_hours) == 1
        assert len(mock_store.save_calls) == writes

    async with start_hass(100, 20, "unavailable") as (hass, coordinator):
        assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
        if mode_after_restart == "manual":
            await select_mode(hass, "manual")
            await coordinator.async_refresh()
        expected = ["charge", "charge" if mode_after_restart == "auto" else "idle"]
        updated = asyncio.Event()

        @callback
        def on_plan(event):
            if priced_actions(hass) == expected:
                updated.set()

        unsubscribe = async_track_state_change_event(hass, [PLAN], on_plan)
        try:
            publish_intervals(hass)
            await asyncio.wait_for(updated.wait(), 4)
        finally:
            unsubscribe()
        assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data


async def test_tariff_waits_for_separate_export_forecast(start_hass, mock_store):
    pricing = {"epex_export_entity": "sensor.sell_back"}
    async with start_hass(100, 20, "5", with_intervals=True, sell_back="unavailable", pricing=pricing) as (hass, coordinator):
        await select_mode(hass, "auto")
        await set_tariff(hass, SELL, "price + 30")
        assert priced_actions(hass) == ["charge", "idle"]
        assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
        await hass.services.async_call(DOMAIN, "calculate_schedule", {}, blocking=True)
        await hass.async_block_till_done()
        writes = len(mock_store.save_calls)
        await coordinator.async_refresh()
        assert len(mock_store.save_calls) == writes

    async with start_hass(100, 20, "5", with_intervals=True, sell_back="unavailable") as (hass, coordinator):
        assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
        assert priced_actions(hass) == ["charge", "idle"]
        assert len(mock_store.save_calls) == writes
        publish_intervals(hass, "sensor.sell_back")
        await coordinator.async_refresh()
        assert priced_actions(hass) == ["discharge", "discharge"]
        assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data


@pytest.mark.parametrize("partial", [False, True])
async def test_failed_plan_write_retries_before_acknowledging_tariff(start_hass, mock_store, monkeypatch, partial):
    pricing = {"epex_export_entity": "sensor.sell_back"} if partial else {}
    async with start_hass(100, 20, "5", with_intervals=True, sell_back="unavailable", pricing=pricing) as (hass, coordinator):
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert len(mock_store._data["charge_hours"]) == 1
        with monkeypatch.context() as fault:
            # HA Store can log a failed write and return normally.
            fault.setattr(mock_store, "async_save", AsyncMock())
            await set_tariff(hass, BUY, "0")
            assert priced_actions(hass) == ["charge", "charge"]
            assert len(mock_store._data["charge_hours"]) == 1
            assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
        await coordinator.async_refresh()
        assert len(mock_store._data["charge_hours"]) == 2
        if partial:
            assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
            publish_intervals(hass, "sensor.sell_back")
            await coordinator.async_refresh()
        assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data


@pytest.mark.parametrize("older_copy", ["config", "plan"])
async def test_restore_mismatched_tariff_and_auto_plan(start_hass, mock_store, older_copy):
    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        old_config = dict(coordinator.config_entry.data)
        old_plan = deepcopy(mock_store._data)
        await set_tariff(hass, BUY, "0")
        assert priced_actions(hass) == ["charge", "charge"]
        if older_copy == "config":
            hass.config_entries.async_update_entry(coordinator.config_entry, data=old_config)

    # A power loss or a backup can leave either store at its earlier revision.
    if older_copy == "plan":
        mock_store._data = old_plan
    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        expected = ["charge", "idle" if older_copy == "config" else "charge"]
        assert priced_actions(hass) == expected
        assert len(mock_store._data["charge_hours"]) == expected.count("charge")
        assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data


async def test_restore_keeps_later_slot_edit_after_tariff_write_during_unload(start_hass, mock_store, monkeypatch):
    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        started, release = asyncio.Event(), asyncio.Event()
        save = mock_store.async_save

        async def stall_save(payload):
            started.set()
            await release.wait()
            await save(payload)

        with monkeypatch.context() as fault:
            fault.setattr(mock_store, "async_save", stall_save)
            try:
                await set_tariff(hass, BUY, "0")
                await asyncio.wait_for(started.wait(), 2)
                assert priced_actions(hass) == ["charge", "charge"]
                first = next(p for p in hass.states.get(PLAN).attributes["plan"] if "price" in p)
                await hass.services.async_call(DOMAIN, "set_slot_action", {
                    "start_time": first["start_time"], "action": "idle",
                }, blocking=True)
                await RestoreStateData.async_save_persistent_states(hass)
                unload = asyncio.create_task(hass.config_entries.async_unload(coordinator.config_entry.entry_id))
                async with asyncio.timeout(2):
                    while not coordinator._shutdown_requested:
                        await asyncio.sleep(0)
            finally:
                release.set()
            assert await unload
        assert len(mock_store._data["charge_hours"]) == 1
        assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]

    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        assert priced_actions(hass) == ["idle", "charge"]
        assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data


async def test_tariff_edits_queued_behind_another_store_writer(start_hass, mock_store, monkeypatch):
    async with start_hass(100, 20, "5", with_intervals=True) as (hass, coordinator):
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        writes = []
        save = mock_store.async_save

        async def record_save(payload):
            writes.append(payload["auto_plan_tariffs"]["import"][1])
            await save(payload)

        monkeypatch.setattr(mock_store, "async_save", record_save)
        async with coordinator._store_lock:
            for value in ("0", "-1", "-2"):
                await asyncio.wait_for(set_tariff(hass, BUY, value), 2)
            assert not writes
        await hass.async_block_till_done()
        assert writes == ["-2"]
        assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data


@pytest.mark.parametrize(("held", "cleanup_fails"), [(False, False), (True, False), (True, True)])
async def test_ha_stop_during_tariff_write_preserves_discharge_ownership(start_hass, monkeypatch, held, cleanup_fails):
    ram = "number.ac_grid_setpoint"
    limit = "number.max_discharge_power"
    marker = "discharge_release_entity"
    monkeypatch.setattr("custom_components.victron_charge_control.coordinator.Store", Store)
    pricing = {"max_discharge_power_entity": limit, "import_price_formula": "5" if held else "25"}
    async with start_hass(100, 20, "5", pricing=pricing, max_discharge_power=800) as (hass, coordinator):
        hour = dt_util.now().replace(minute=0, second=0, microsecond=0)
        hass.states.async_set("sensor.epex_spot", "5", {
            "unit_of_measurement": "ct/kWh",
            "data": [{"start_time": hour.isoformat(), "price_ct_per_kwh": 5}],
        })
        await set_tariff(hass, "text.victron_charge_control_blocked_charging_hours", "")
        coordinator.action_confirm_seconds = 0
        await hass.services.async_call("switch", "turn_on", {
            "entity_id": "switch.victron_charge_control_disable_discharge",
        }, blocking=True)
        await select_mode(hass, "auto")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert float(hass.states.get(limit).state) == (0 if held else 800)

        started, release, idle = asyncio.Event(), asyncio.Event(), asyncio.Event()
        written = []
        store = coordinator._store
        write = store._async_write_data

        async def stall_write(data):
            written.append(data["data"][marker])
            started.set()
            await release.wait()
            if held and data["data"][marker] is None:
                assert hass.state is CoreState.final_write
                if cleanup_fails:
                    return
            await write(data)

        monkeypatch.setattr(store, "_async_write_data", stall_write)
        try:
            await set_tariff(hass, BUY, "1")
            await asyncio.wait_for(started.wait(), 2)
            await coordinator.async_refresh()
            assert float(hass.states.get(ram).state) == 3000
            assert float(hass.states.get(limit).state) == (0 if held else 800)

            @callback
            def observe_ram(event):
                if float(event.data["new_state"].state) == 0:
                    idle.set()

            async_track_state_change_event(hass, [ram], observe_ram)
            stop = asyncio.create_task(hass.async_stop(force=True))
            await asyncio.wait_for(idle.wait(), 3)
            assert float(hass.states.get(limit).state) == (-1 if held else 800)
            assert not stop.done()
        finally:
            release.set()
        await asyncio.wait_for(stop, 5)
        if not held:
            assert limit not in written
        expected_marker = limit if cleanup_fails else None
        assert json.loads(Path(store.path).read_text())["data"][marker] == expected_marker
        assert coordinator._discharge_release_entity == expected_marker

    # Boot after the Charge window. Only a failed durable cleanup should replay a release.
    monkeypatch.setattr(dt_util, "now", lambda time_zone=None: (hour + timedelta(hours=2)).astimezone(time_zone))
    async with start_hass(100, 20, "5", max_discharge_power=800) as (hass, _):
        assert float(hass.states.get(limit).state) == (-1 if cleanup_fails else 800)


@pytest.mark.parametrize("discharge_limit", ["unused", "held", "new_hold"])
async def test_watchdog_corrects_ram_during_stalled_tariff_saves(start_hass, mock_store, monkeypatch, discharge_limit):
    ram = "number.ac_grid_setpoint"
    limit = "number.max_discharge_power"
    pricing = {"max_discharge_power_entity": limit} if discharge_limit != "unused" else {}
    if discharge_limit == "new_hold":
        pricing["import_price_formula"] = "25"
    async with start_hass(100, 20, "5", pricing=pricing) as (hass, coordinator):
        assert await async_setup_component(hass, "persistent_notification", {})
        hour = dt_util.now().replace(minute=0, second=0, microsecond=0)
        hass.states.async_set("sensor.epex_spot", "5", {
            "unit_of_measurement": "ct/kWh",
            "data": [{"start_time": hour.isoformat(), "price_ct_per_kwh": 5}],
        })
        await set_tariff(hass, "text.victron_charge_control_blocked_charging_hours", "")
        coordinator.action_confirm_seconds = 0
        coordinator.disable_discharge = discharge_limit != "unused"
        await select_mode(hass, "auto")
        # The first evaluation starts confirmation of Charge, the next publishes it.
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert float(hass.states.get(ram).state) == (0 if discharge_limit == "new_hold" else 3000)
        assert float(hass.states.get(limit).state) == (0 if discharge_limit == "held" else -1)

        started = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        wrote = []
        save = mock_store.async_save

        async def slow_save(payload):
            index = len(wrote)
            wrote.append(payload["auto_plan_tariffs"]["import"][1])
            if index < len(started):
                started[index].set()
                await release[index].wait()
            await save(payload)

        monkeypatch.setattr(mock_store, "async_save", slow_save)
        try:
            await asyncio.wait_for(set_tariff(hass, BUY, "0"), 2)
            await asyncio.wait_for(started[0].wait(), 2)
            for value in ("-1", "-2"):
                await asyncio.wait_for(set_tariff(hass, BUY, value), 2)
            assert hass.states.get(RATE).attributes["import_price_eur_per_kwh"] == -0.02
            assert float(hass.states.get(ram).state) == 3000
            assert float(hass.states.get(limit).state) == (0 if discharge_limit == "held" else -1)
            assert wrote == ["0"]
            assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]

            idle = asyncio.Event()

            @callback
            def observe_ram(event):
                if float(event.data["new_state"].state) == 0:
                    idle.set()

            unsubscribe = async_track_state_change_event(hass, [ram], observe_ram)
            try:
                hass.states.async_set("sensor.battery_soc", "unavailable")
                await asyncio.wait_for(idle.wait(), 3)
            finally:
                unsubscribe()
            assert coordinator.control_mode == "off"
            assert float(hass.states.get(ram).state) == 0
            assert float(hass.states.get(limit).state) == -1
            assert not release[0].is_set()

            release[0].set()
            await asyncio.wait_for(started[1].wait(), 2)
            assert wrote == ["0", "-2"]
            assert coordinator.config_entry.data[CONF_REPLAN_TARIFFS]
            release[1].set()
            await hass.async_block_till_done()
            assert CONF_REPLAN_TARIFFS not in coordinator.config_entry.data
            assert mock_store._data["auto_plan_tariffs"]["import"][1] == "-2"
        finally:
            for gate in release:
                gate.set()
