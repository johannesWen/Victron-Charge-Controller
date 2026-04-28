"""Tests for the Victron Charge Control config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control.config_flow import (
    VictronChargeControlConfigFlow,
    VictronChargeControlOptionsFlow,
)
from custom_components.victron_charge_control.const import (
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    DOMAIN,
)

from .conftest import MOCK_CONFIG_DATA, MockState


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


class TestOptionsFlow:
    """Tests for the options flow."""

    @pytest.fixture
    def options_flow(self):
        """Create an options flow with mocked config entry."""
        config_entry = MagicMock()
        config_entry.data = dict(MOCK_CONFIG_DATA)
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
        new_data = {**MOCK_CONFIG_DATA, CONF_BATTERY_SOC_ENTITY: "sensor.new_soc"}
        await options_flow.async_step_init(user_input=new_data)
        options_flow.hass.config_entries.async_update_entry.assert_called_once()
        options_flow.async_create_entry.assert_called_once()

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
