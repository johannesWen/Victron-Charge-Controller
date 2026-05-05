"""Tests for Victron Charge Control services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    DOMAIN,
)
from custom_components.victron_charge_control.coordinator import VictronChargeControlCoordinator
from custom_components.victron_charge_control.services import (
    SERVICE_CALCULATE_SCHEDULE,
    SERVICE_CLEAR_SCHEDULE,
    SERVICE_SET_BLOCKED_CHARGING_HOURS,
    SERVICE_SET_BLOCKED_DISCHARGING_HOURS,
    SERVICE_SET_HOUR_ACTION,
    SERVICE_TOGGLE_HOUR,
    _get_coordinator,
    async_setup_services,
    async_unload_services,
)


class TestGetCoordinator:
    """Tests for the _get_coordinator helper."""

    def test_returns_coordinator(self, mock_hass, coordinator):
        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        result = _get_coordinator(mock_hass)
        assert result is coordinator

    def test_returns_none_when_no_domain(self, mock_hass):
        result = _get_coordinator(mock_hass)
        assert result is None

    def test_returns_none_when_empty(self, mock_hass):
        mock_hass.data[DOMAIN] = {}
        result = _get_coordinator(mock_hass)
        assert result is None

    def test_returns_none_when_wrong_type(self, mock_hass):
        mock_hass.data[DOMAIN] = {"entry1": "not a coordinator"}
        result = _get_coordinator(mock_hass)
        assert result is None


class TestAsyncSetupServices:
    """Tests for service registration."""

    @pytest.mark.asyncio
    async def test_registers_all_services(self, mock_hass):
        await async_setup_services(mock_hass)

        registered = [
            call.args[1] for call in mock_hass.services.async_register.call_args_list
        ]
        assert SERVICE_TOGGLE_HOUR in registered
        assert SERVICE_SET_HOUR_ACTION in registered
        assert SERVICE_SET_BLOCKED_CHARGING_HOURS in registered
        assert SERVICE_SET_BLOCKED_DISCHARGING_HOURS in registered
        assert SERVICE_CALCULATE_SCHEDULE in registered
        assert SERVICE_CLEAR_SCHEDULE in registered

    @pytest.mark.asyncio
    async def test_registers_in_correct_domain(self, mock_hass):
        await async_setup_services(mock_hass)

        for call in mock_hass.services.async_register.call_args_list:
            assert call.args[0] == DOMAIN


class TestAsyncUnloadServices:
    """Tests for service unregistration."""

    @pytest.mark.asyncio
    async def test_removes_all_services(self, mock_hass):
        await async_unload_services(mock_hass)

        removed = [
            call.args[1] for call in mock_hass.services.async_remove.call_args_list
        ]
        assert SERVICE_TOGGLE_HOUR in removed
        assert SERVICE_CLEAR_SCHEDULE in removed
        assert len(removed) == 6


class TestServiceHandlers:
    """Tests for individual service handler logic via the coordinator."""

    @pytest.mark.asyncio
    async def test_toggle_hour_handler(self, mock_hass, coordinator):
        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        await async_setup_services(mock_hass)

        # Get the registered handler for toggle_hour
        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_TOGGLE_HOUR:
                handler = call.args[2]
                break

        assert handler is not None

        # Create mock service call (date defaults to today via coordinator)
        service_call = MagicMock()
        service_call.data = {"hour": 5, "date": "2026-05-02"}

        await handler(service_call)

        assert ("2026-05-02", 5) in coordinator.charge_hours

    @pytest.mark.asyncio
    async def test_set_hour_action_handler(self, mock_hass, coordinator):
        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_SET_HOUR_ACTION:
                handler = call.args[2]
                break

        service_call = MagicMock()
        service_call.data = {"hour": 10, "action": ACTION_DISCHARGE, "date": "2026-05-02"}

        await handler(service_call)

        assert ("2026-05-02", 10) in coordinator.discharge_hours

    @pytest.mark.asyncio
    async def test_clear_schedule_handler(self, mock_hass, coordinator):
        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        coordinator._charge_hours = [("2026-05-02", 1), ("2026-05-02", 2)]
        coordinator._discharge_hours = [("2026-05-02", 20)]

        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_CLEAR_SCHEDULE:
                handler = call.args[2]
                break

        service_call = MagicMock()
        await handler(service_call)

        assert coordinator.charge_hours == []
        assert coordinator.discharge_hours == []

    @pytest.mark.asyncio
    async def test_set_blocked_charging_hours_handler(self, mock_hass, coordinator):
        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_SET_BLOCKED_CHARGING_HOURS:
                handler = call.args[2]
                break

        service_call = MagicMock()
        service_call.data = {"hours": [18, 19, 20]}
        await handler(service_call)

        assert coordinator.blocked_charging_hours == [18, 19, 20]

    @pytest.mark.asyncio
    async def test_handler_no_coordinator(self, mock_hass):
        """Handlers should not crash when no coordinator is found."""
        mock_hass.data = {}
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_TOGGLE_HOUR:
                handler = call.args[2]
                break

        service_call = MagicMock()
        service_call.data = {"hour": 5}

        # Should not raise
        await handler(service_call)
