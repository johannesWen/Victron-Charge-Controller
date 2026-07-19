"""Tests for the Victron Charge Control __init__ module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control import (
    PLATFORMS,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.victron_charge_control.const import (
    CARD_REGISTERED_KEY,
    DOMAIN,
)

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
    @patch("custom_components.victron_charge_control._async_register_card")
    async def test_setup_entry(
        self, mock_register_card, mock_setup_services, mock_coord_cls, mock_hass, mock_entry
    ):
        calls = []
        mock_coordinator = MagicMock()
        mock_coordinator.async_setup = AsyncMock()
        mock_coordinator.async_setup.side_effect = lambda: calls.append("setup")
        mock_hass.config_entries.async_forward_entry_setups.side_effect = (
            lambda *_args: calls.append("platforms")
        )
        mock_coord_cls.return_value = mock_coordinator

        result = await async_setup_entry(mock_hass, mock_entry)

        assert result is True
        assert DOMAIN in mock_hass.data
        assert mock_entry.entry_id in mock_hass.data[DOMAIN]
        mock_coordinator.async_setup.assert_called_once()
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            mock_entry, PLATFORMS
        )
        assert calls == ["platforms", "setup"]
        mock_register_card.assert_awaited_once_with(mock_hass)

    @pytest.mark.asyncio
    @patch(
        "custom_components.victron_charge_control.VictronChargeControlCoordinator"
    )
    @patch("custom_components.victron_charge_control.async_setup_services")
    @patch("custom_components.victron_charge_control._async_register_card")
    async def test_setup_entry_registers_services_once(
        self, mock_register_card, mock_setup_services, mock_coord_cls, mock_hass, mock_entry
    ):
        mock_coordinator = MagicMock()
        mock_coordinator.async_setup = AsyncMock()
        mock_coord_cls.return_value = mock_coordinator

        await async_setup_entry(mock_hass, mock_entry)

        mock_setup_services.assert_called_once_with(mock_hass)
        mock_register_card.assert_awaited_once_with(mock_hass)

    @pytest.mark.asyncio
    @patch(
        "custom_components.victron_charge_control.VictronChargeControlCoordinator"
    )
    @patch("custom_components.victron_charge_control.async_setup_services")
    @patch("custom_components.victron_charge_control._async_register_card")
    async def test_setup_entry_skips_services_for_second_entry(
        self, mock_register_card, mock_setup_services, mock_coord_cls, mock_hass, mock_entry
    ):
        mock_coordinator = MagicMock()
        mock_coordinator.async_setup = AsyncMock()
        mock_coord_cls.return_value = mock_coordinator
        # Simulate an already-loaded entry.
        mock_hass.data[DOMAIN] = {
            "existing_entry": MagicMock(),
            CARD_REGISTERED_KEY: True,
        }

        await async_setup_entry(mock_hass, mock_entry)

        mock_setup_services.assert_not_called()
        # The card registration is idempotent: it is invoked on every setup
        # entry, but the helper is a no-op when CARD_REGISTERED_KEY is set.
        mock_register_card.assert_awaited_once_with(mock_hass)


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    @pytest.mark.asyncio
    @patch("custom_components.victron_charge_control.async_unload_services")
    async def test_unload_entry(self, mock_unload_services, mock_hass, mock_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: mock_coordinator,
            CARD_REGISTERED_KEY: True,
        }

        result = await async_unload_entry(mock_hass, mock_entry)

        assert result is True
        mock_coordinator.async_shutdown.assert_called_once()
        assert mock_entry.entry_id not in mock_hass.data.get(DOMAIN, {})
        # The card_registered flag is preserved across entry unload.
        assert CARD_REGISTERED_KEY in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    @patch("custom_components.victron_charge_control.async_unload_services")
    async def test_unload_last_entry_unloads_services(
        self, mock_unload_services, mock_hass, mock_entry
    ):
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: mock_coordinator,
            CARD_REGISTERED_KEY: True,
        }

        await async_unload_entry(mock_hass, mock_entry)

        mock_unload_services.assert_called_once_with(mock_hass)
        # DOMAIN remains in hass.data because the card is still registered.
        assert DOMAIN in mock_hass.data

    @pytest.mark.asyncio
    @patch("custom_components.victron_charge_control.async_unload_services")
    async def test_unload_not_last_entry(self, mock_unload_services, mock_hass, mock_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()
        other_coordinator = MagicMock()
        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: mock_coordinator,
            "other_entry": other_coordinator,
            CARD_REGISTERED_KEY: True,
        }

        await async_unload_entry(mock_hass, mock_entry)

        mock_unload_services.assert_not_called()
        assert DOMAIN in mock_hass.data

    @pytest.mark.asyncio
    async def test_unload_failure(self, mock_hass, mock_entry):
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        mock_coordinator = MagicMock()
        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: mock_coordinator,
            CARD_REGISTERED_KEY: True,
        }

        result = await async_unload_entry(mock_hass, mock_entry)

        assert result is False
        assert mock_entry.entry_id in mock_hass.data[DOMAIN]