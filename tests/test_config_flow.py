"""Tests for the Victron Charge Control config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control.config_flow import (
    OPTIONAL_ENTITY_KEYS,
    VictronChargeControlConfigFlow,
    VictronChargeControlOptionsFlow,
)
from custom_components.victron_charge_control.const import (
    CONF_BATTERY_SOC_ENTITY,
    CONF_DC_COUPLED_PV_FEED_IN_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_CONSUMPTION_ENTITY,
    CONF_GRID_FEED_IN_ENERGY_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    CONF_SAFETY_STARTUP_GRACE_SECONDS,
    CONF_SOLAR_SURPLUS_ENTITY,
    CONF_USE_SOLCAST_FORECAST,
    DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
    DOMAIN,
)

from .conftest import (
    MOCK_CONFIG_DATA,
    MOCK_CONFIG_DATA_WITH_COST,
    MOCK_CONFIG_DATA_WITH_DC_FEED_IN,
    MOCK_CONFIG_DATA_WITH_SOLAR,
    MockState,
)


class TestConfigFlow:
    """Tests for the initial config flow."""

    @pytest.fixture
    def flow(self):
        """Create a config flow instance with mocked hass."""
        flow = VictronChargeControlConfigFlow()
        flow.hass = MagicMock()
        flow.hass.states.get = MagicMock(return_value=MockState("50"))
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_show_form_on_no_input(self, flow):
        result = await flow.async_step_user(user_input=None)
        flow.async_show_form.assert_called_once()
        assert result["type"] == "form"

    @pytest.mark.asyncio
    async def test_create_entry_on_valid_input(self, flow):
        result = await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA))
        flow.async_create_entry.assert_called_once_with(
            title="Victron Charge Control",
            data=MOCK_CONFIG_DATA,
        )

    @pytest.mark.asyncio
    async def test_create_entry_with_optional_cost_entities(self, flow):
        await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA_WITH_COST))
        flow.async_create_entry.assert_called_once_with(
            title="Victron Charge Control",
            data=MOCK_CONFIG_DATA_WITH_COST,
        )

    @pytest.mark.asyncio
    async def test_create_entry_with_solar_entity(self, flow):
        await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA_WITH_SOLAR))
        flow.async_create_entry.assert_called_once_with(
            title="Victron Charge Control",
            data=MOCK_CONFIG_DATA_WITH_SOLAR,
        )

    @pytest.mark.asyncio
    async def test_create_entry_with_dc_feed_in_entity(self, flow):
        await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA_WITH_DC_FEED_IN))
        flow.async_create_entry.assert_called_once_with(
            title="Victron Charge Control",
            data=MOCK_CONFIG_DATA_WITH_DC_FEED_IN,
        )

    @pytest.mark.asyncio
    async def test_blank_optional_entities_are_not_stored(self, flow):
        user_input = {
            **MOCK_CONFIG_DATA,
            CONF_GRID_CONSUMPTION_ENTITY: "",
            CONF_GRID_FEED_IN_ENERGY_ENTITY: "",
            CONF_SOLAR_SURPLUS_ENTITY: "",
            CONF_DC_COUPLED_PV_FEED_IN_ENTITY: "",
        }

        await flow.async_step_user(user_input=user_input)

        flow.async_create_entry.assert_called_once_with(
            title="Victron Charge Control",
            data=MOCK_CONFIG_DATA,
        )

    @pytest.mark.asyncio
    async def test_error_on_missing_entity(self, flow):
        """Show error if an entity doesn't exist."""

        def side_effect(entity_id):
            if entity_id == "sensor.battery_soc":
                return None  # Entity not found
            return MockState("50")

        flow.hass.states.get = MagicMock(side_effect=side_effect)

        result = await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA))

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors") or call_kwargs[1].get("errors", {})
        assert CONF_BATTERY_SOC_ENTITY in errors

    @pytest.mark.asyncio
    async def test_error_on_missing_optional_entity(self, flow):
        """Show error if a configured optional energy entity doesn't exist."""

        def side_effect(entity_id):
            if entity_id == "sensor.grid_consumption_kwh":
                return None
            return MockState("50")

        flow.hass.states.get = MagicMock(side_effect=side_effect)

        await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA_WITH_COST))

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors") or call_kwargs[1].get("errors", {})
        assert CONF_GRID_CONSUMPTION_ENTITY in errors

    @pytest.mark.asyncio
    async def test_error_on_missing_dc_feed_in_entity(self, flow):
        """Show error if the configured optional DC feed-in switch doesn't exist."""

        def side_effect(entity_id):
            if entity_id == "switch.dc_pv_feed_in":
                return None
            return MockState("50")

        flow.hass.states.get = MagicMock(side_effect=side_effect)

        await flow.async_step_user(user_input=dict(MOCK_CONFIG_DATA_WITH_DC_FEED_IN))

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors") or call_kwargs[1].get("errors", {})
        assert CONF_DC_COUPLED_PV_FEED_IN_ENTITY in errors


class TestOptionsFlow:
    """Tests for the options flow."""

    @pytest.fixture
    def options_flow(self):
        """Create an options flow with mocked config entry."""
        config_entry = MagicMock()
        config_entry.data = dict(MOCK_CONFIG_DATA)
        config_entry.options = {}
        flow = VictronChargeControlOptionsFlow(config_entry)
        flow.hass = MagicMock()
        flow.hass.states.get = MagicMock(return_value=MockState("50"))
        flow.hass.config_entries = MagicMock()
        flow.hass.config_entries.async_update_entry = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_show_form_on_no_input(self, options_flow):
        result = await options_flow.async_step_init(user_input=None)
        options_flow.async_show_form.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_entry_on_valid_input(self, options_flow):
        new_data = {
            **MOCK_CONFIG_DATA,
            CONF_BATTERY_SOC_ENTITY: "sensor.new_soc",
            CONF_SAFETY_STARTUP_GRACE_SECONDS: DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
        }
        await options_flow.async_step_init(user_input=new_data)
        options_flow.hass.config_entries.async_update_entry.assert_called_once()
        options_flow.async_create_entry.assert_called_once()
        _, kwargs = options_flow.async_create_entry.call_args
        assert kwargs["data"][CONF_SAFETY_STARTUP_GRACE_SECONDS] == DEFAULT_SAFETY_STARTUP_GRACE_SECONDS

    @pytest.mark.asyncio
    async def test_update_entry_with_optional_cost_entities(self, options_flow):
        user_input = {
            **MOCK_CONFIG_DATA_WITH_COST,
            CONF_SAFETY_STARTUP_GRACE_SECONDS: DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
        }
        await options_flow.async_step_init(user_input=user_input)
        options_flow.hass.config_entries.async_update_entry.assert_called_once()
        _, kwargs = options_flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"][CONF_GRID_CONSUMPTION_ENTITY] == "sensor.grid_consumption_kwh"
        assert kwargs["data"][CONF_GRID_FEED_IN_ENERGY_ENTITY] == "sensor.grid_feed_in_kwh"

    @pytest.mark.asyncio
    async def test_update_entry_with_solar_entity(self, options_flow):
        user_input = {
            **MOCK_CONFIG_DATA_WITH_SOLAR,
            CONF_SAFETY_STARTUP_GRACE_SECONDS: DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
        }
        await options_flow.async_step_init(user_input=user_input)
        _, kwargs = options_flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"][CONF_SOLAR_SURPLUS_ENTITY] == "sensor.solar_surplus"

    @pytest.mark.asyncio
    async def test_update_entry_with_dc_feed_in_entity(self, options_flow):
        user_input = {
            **MOCK_CONFIG_DATA_WITH_DC_FEED_IN,
            CONF_SAFETY_STARTUP_GRACE_SECONDS: DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
        }
        await options_flow.async_step_init(user_input=user_input)
        _, kwargs = options_flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"][CONF_DC_COUPLED_PV_FEED_IN_ENTITY] == "switch.dc_pv_feed_in"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("optional_key", OPTIONAL_ENTITY_KEYS)
    @pytest.mark.parametrize("blank", ["", None])
    async def test_clears_blank_optional_entity(self, options_flow, optional_key, blank):
        options_flow._config_entry.data = {**MOCK_CONFIG_DATA, optional_key: "sensor.old"}

        await options_flow.async_step_init({**MOCK_CONFIG_DATA, optional_key: blank})

        saved = options_flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert saved == MOCK_CONFIG_DATA

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "removed_keys", [(key,) for key in OPTIONAL_ENTITY_KEYS] + [OPTIONAL_ENTITY_KEYS]
    )
    async def test_cleared_selectors_stay_empty_after_reopening(
        self, options_flow, removed_keys
    ):
        configured = {
            **MOCK_CONFIG_DATA_WITH_COST,
            **MOCK_CONFIG_DATA_WITH_SOLAR,
            **MOCK_CONFIG_DATA_WITH_DC_FEED_IN,
        }
        options_flow._config_entry.data = {**configured, "unrelated_setting": "preserved"}
        await options_flow.async_step_init()
        schema = options_flow.async_show_form.call_args.kwargs["data_schema"]
        for key in schema.schema:
            if key in OPTIONAL_ENTITY_KEYS:
                assert key.description["suggested_value"] == configured[key]

        submitted = {
            key: value for key, value in configured.items() if key not in removed_keys
        }
        submitted[CONF_BATTERY_SOC_ENTITY] = "sensor.new_soc"
        submitted[CONF_SAFETY_STARTUP_GRACE_SECONDS] = 45
        validated = schema(submitted)
        assert all(key not in validated for key in removed_keys)
        await options_flow.async_step_init(validated)

        saved = options_flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        expected = {
            key: value
            for key, value in submitted.items()
            if key not in (CONF_SAFETY_STARTUP_GRACE_SECONDS, CONF_USE_SOLCAST_FORECAST)
        }
        assert saved == {**expected, "unrelated_setting": "preserved"}
        assert options_flow.async_create_entry.call_args.kwargs["data"] == {
            CONF_SAFETY_STARTUP_GRACE_SECONDS: 45,
            CONF_USE_SOLCAST_FORECAST: True,
        }

        options_flow._config_entry.data = saved
        await options_flow.async_step_init()
        reopened_schema = options_flow.async_show_form.call_args.kwargs["data_schema"]
        for key in reopened_schema.schema:
            if key in removed_keys:
                assert not key.description.get("suggested_value")
        assert all(key not in reopened_schema(submitted) for key in removed_keys)

    @pytest.mark.asyncio
    async def test_save_with_unconfigured_optional_entities(self, options_flow):
        await options_flow.async_step_init()
        schema = options_flow.async_show_form.call_args.kwargs["data_schema"]
        submitted = {**MOCK_CONFIG_DATA, CONF_BATTERY_SOC_ENTITY: "sensor.new_soc"}

        await options_flow.async_step_init(schema(submitted))

        saved = options_flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert saved == submitted

    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [True, False])
    async def test_forecast_option_preserves_entities_and_other_options(self, options_flow, enabled):
        options_flow._config_entry.options = {
            CONF_SAFETY_STARTUP_GRACE_SECONDS: 45,
            "unrelated_option": "preserved",
        }
        await options_flow.async_step_init({**MOCK_CONFIG_DATA, CONF_USE_SOLCAST_FORECAST: enabled})

        assert options_flow.hass.config_entries.async_update_entry.call_args.kwargs["data"] == MOCK_CONFIG_DATA
        assert options_flow.async_create_entry.call_args.kwargs["data"] == {
            CONF_SAFETY_STARTUP_GRACE_SECONDS: 45,
            CONF_USE_SOLCAST_FORECAST: enabled,
            "unrelated_option": "preserved",
        }

    @pytest.mark.asyncio
    async def test_forecast_defaults_and_validation_redisplay(self, options_flow):
        await options_flow.async_step_init()
        schema = options_flow.async_show_form.call_args.kwargs["data_schema"]
        assert schema(MOCK_CONFIG_DATA)[CONF_USE_SOLCAST_FORECAST] is True
        options_flow.hass.states.get.return_value = None
        await options_flow.async_step_init({**MOCK_CONFIG_DATA, CONF_USE_SOLCAST_FORECAST: False})
        schema = options_flow.async_show_form.call_args.kwargs["data_schema"]
        assert schema(MOCK_CONFIG_DATA)[CONF_USE_SOLCAST_FORECAST] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_key", [CONF_BATTERY_SOC_ENTITY, CONF_SOLAR_SURPLUS_ENTITY]
    )
    async def test_validation_error_preserves_cleared_selection(
        self, options_flow, invalid_key
    ):
        options_flow._config_entry.data = dict(MOCK_CONFIG_DATA_WITH_COST)
        submitted = {**MOCK_CONFIG_DATA, invalid_key: "sensor.missing"}
        options_flow.hass.states.get.side_effect = (
            lambda entity_id: None if entity_id == "sensor.missing" else MockState("50")
        )

        await options_flow.async_step_init(submitted)

        options_flow.hass.config_entries.async_update_entry.assert_not_called()
        options_flow.async_create_entry.assert_not_called()
        form = options_flow.async_show_form.call_args.kwargs
        assert form["errors"] == {invalid_key: "entity_not_found"}
        for key in form["data_schema"].schema:
            if key in (CONF_GRID_CONSUMPTION_ENTITY, CONF_GRID_FEED_IN_ENERGY_ENTITY):
                assert not key.description.get("suggested_value")
        validated = form["data_schema"](submitted)
        assert CONF_GRID_CONSUMPTION_ENTITY not in validated
        assert CONF_GRID_FEED_IN_ENERGY_ENTITY not in validated

    @pytest.mark.asyncio
    async def test_grace_period_value_is_persisted_to_options(self, options_flow):
        """User-chosen grace period lands in entry.options (not entry.data)."""
        user_input = {
            **MOCK_CONFIG_DATA,
            CONF_SAFETY_STARTUP_GRACE_SECONDS: 45,
        }

        await options_flow.async_step_init(user_input=user_input)

        # The grace period must be in options (the create_entry return value),
        # never in data (the entity reference store).
        _, update_kwargs = options_flow.hass.config_entries.async_update_entry.call_args
        assert CONF_SAFETY_STARTUP_GRACE_SECONDS not in update_kwargs["data"]
        _, create_kwargs = options_flow.async_create_entry.call_args
        assert create_kwargs["data"][CONF_SAFETY_STARTUP_GRACE_SECONDS] == 45

    @pytest.mark.asyncio
    async def test_error_on_missing_entity(self, options_flow):
        def side_effect(entity_id):
            if entity_id == "sensor.battery_soc":
                return None
            return MockState("50")

        options_flow.hass.states.get = MagicMock(side_effect=side_effect)

        await options_flow.async_step_init(user_input=dict(MOCK_CONFIG_DATA))

        options_flow.async_show_form.assert_called_once()
        call_kwargs = options_flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors") or call_kwargs[1].get("errors", {})
        assert CONF_BATTERY_SOC_ENTITY in errors
