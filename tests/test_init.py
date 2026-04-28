"""Tests for the Victron Charge Control __init__ module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control import (
    PLATFORMS,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.victron_charge_control.const import DOMAIN

from .conftest import MOCK_CONFIG_DATA, MOCK_ENTRY_ID


@pytest.fixture
def mock_entry():
    """Create a mock config entry for init tests."""
    entry = MagicMock()
    entry.entry_id = MOCK_ENTRY_ID
    entry.data = dict(MOCK_CONFIG_DATA)
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    entry.async_on_unload = MagicMock()
    return entry


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.victron_charge_control.VictronChargeControlCoordinator"
    )
    @patch("custom_components.victron_charge_control.async_setup_services")
    async def test_setup_entry(self, mock_setup_services, mock_coord_cls, mock_hass, mock_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_setup = AsyncMock()
        mock_coord_cls.return_value = mock_coordinator

        result = await async_setup_entry(mock_hass, mock_entry)

        assert result is True
        assert DOMAIN in mock_hass.data
        assert mock_entry.entry_id in mock_hass.data[DOMAIN]
        mock_coordinator.async_setup.assert_called_once()
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            mock_entry, PLATFORMS
        )

    @pytest.mark.asyncio
    @patch(
        "custom_components.victron_charge_control.VictronChargeControlCoordinator"
    )
    @patch("custom_components.victron_charge_control.async_setup_services")
    async def test_setup_entry_registers_services_once(
        self, mock_setup_services, mock_coord_cls, mock_hass, mock_entry
    ):
        mock_coordinator = MagicMock()
        mock_coordinator.async_setup = AsyncMock()
        mock_coord_cls.return_value = mock_coordinator

        await async_setup_entry(mock_hass, mock_entry)

        mock_setup_services.assert_called_once_with(mock_hass)


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    @pytest.mark.asyncio
    @patch("custom_components.victron_charge_control.async_unload_services")
    async def test_unload_entry(self, mock_unload_services, mock_hass, mock_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        mock_hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

        result = await async_unload_entry(mock_hass, mock_entry)

        assert result is True
        mock_coordinator.async_shutdown.assert_called_once()
        assert mock_entry.entry_id not in mock_hass.data.get(DOMAIN, {})

    @pytest.mark.asyncio
    @patch("custom_components.victron_charge_control.async_unload_services")
    async def test_unload_last_entry_removes_domain(
        self, mock_unload_services, mock_hass, mock_entry
    ):
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        mock_hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

        await async_unload_entry(mock_hass, mock_entry)

        mock_unload_services.assert_called_once_with(mock_hass)
        assert DOMAIN not in mock_hass.data

    @pytest.mark.asyncio
    @patch("custom_components.victron_charge_control.async_unload_services")
    async def test_unload_not_last_entry(self, mock_unload_services, mock_hass, mock_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        other_coordinator = MagicMock()
        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: mock_coordinator,
            "other_entry": other_coordinator,
        }

        await async_unload_entry(mock_hass, mock_entry)

        mock_unload_services.assert_not_called()
        assert DOMAIN in mock_hass.data

    @pytest.mark.asyncio
    async def test_unload_failure(self, mock_hass, mock_entry):
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        mock_coordinator = MagicMock()
        mock_hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

        result = await async_unload_entry(mock_hass, mock_entry)

        assert result is False
        assert mock_entry.entry_id in mock_hass.data[DOMAIN]
