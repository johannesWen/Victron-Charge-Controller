"""Exercise tariff settings and History through Home Assistant."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest

from homeassistant import auth, loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.restore_state import RestoreStateData
from homeassistant.setup import async_setup_component

from custom_components import victron_charge_control
from custom_components.victron_charge_control.const import DOMAIN
from custom_components.victron_charge_control.sensor import GridEnergyCostSensor

from .conftest import MOCK_CONFIG_DATA_WITH_COST


@pytest.fixture
def start_hass(tmp_path, monkeypatch):
    """Start an isolated HA instance with simulated meter and setpoint entities."""
    monkeypatch.setattr(victron_charge_control, "_async_register_card", AsyncMock())
    (tmp_path / "custom_components").symlink_to(
        Path(__file__).resolve().parents[1] / "custom_components",
        target_is_directory=True,
    )

    @asynccontextmanager
    async def start(import_kwh, export_kwh, price, *, pricing=None, sell_back=None):
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
        hass.states.async_set("sensor.grid_consumption_kwh", str(import_kwh))
        hass.states.async_set("sensor.grid_feed_in_kwh", str(export_kwh))
        hass.states.async_set("sensor.epex_spot", price, {"unit_of_measurement": "ct/kWh"})
        if sell_back is not None:
            hass.states.async_set("sensor.sell_back", sell_back, {"unit_of_measurement": "EUR/kWh"})

        async def set_number(call):
            hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

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


async def test_second_epex_entry_and_fixed_buy_override(start_hass):
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
    buy = "text.victron_charge_control_buy_price"
    sell = "text.victron_charge_control_sell_price"

    async def set_tariff(hass, entity_id, value):
        await hass.services.async_call(
            "text", "set_value", {"entity_id": entity_id, "value": value}, blocking=True,
        )

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
        for invalid in ("NaN", "-Infinity", "3,5", "1_000", "1e2", "4 €/kWh"):
            with pytest.raises(ServiceValidationError):
                await set_tariff(hass, buy, invalid)
        assert hass.states.get(buy).state == "+12.50"
        assert hass.states.get(sell).state == "-5.5"
        await coordinator.async_refresh()
        assert _history(hass) == pytest.approx((0.40, 0.20, 2, 1))
        assert coordinator.data.current_price_eur_per_kwh == 0.20

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
        assert coordinator.data.current_price_eur_per_kwh is None

        await set_tariff(hass, buy, "0")
        await set_tariff(hass, sell, "")
        assert hass.states.get(buy).state == "0"
        assert hass.states.get(sell).state == ""
        assert _history(hass) == pytest.approx((0.885, 0.20, 5, 3))

    async with start_hass(106, 24, "40") as (hass, _):
        assert hass.states.get(buy).state == "0"
        assert hass.states.get(sell).state == ""
        assert _history(hass) == pytest.approx((0.885, 0.60, 6, 4))
