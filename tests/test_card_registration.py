"""Tests for the bundled Lovelace card registration in ``__init__``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control import _async_register_card
from custom_components.victron_charge_control.const import (
    CARD_FILE_NAME,
    CARD_REGISTERED_KEY,
    CARD_URL_PATH,
    DOMAIN,
)

CARD_PATH_TARGET = "custom_components.victron_charge_control.Path"
ADD_JS_URL_TARGET = "custom_components.victron_charge_control.add_extra_js_url"
STATIC_PATH_CONFIG_TARGET = "custom_components.victron_charge_control.StaticPathConfig"


def _patch_card_path(monkeypatch, *, is_file: bool) -> MagicMock:
    """Patch ``Path`` so the card path resolves to a controllable mock.

    The production code computes ``Path(__file__).parent / "static" / CARD_FILE_NAME``
    so we wire the ``__truediv__`` chain to return a mock whose ``is_file()``
    behaves as requested.
    """
    card_path = MagicMock()
    card_path.is_file.return_value = is_file

    mock_path_cls = MagicMock()
    parent = mock_path_cls.return_value.parent
    # parent / "static" returns the intermediate; intermediate / CARD_FILE_NAME returns card_path
    parent.__truediv__.return_value.__truediv__.return_value = card_path

    monkeypatch.setattr(CARD_PATH_TARGET, mock_path_cls)
    return card_path


class TestAsyncRegisterCard:
    """Tests for ``_async_register_card``."""

    @pytest.mark.asyncio
    async def test_skips_when_already_registered(self, mock_hass, monkeypatch):
        """If the card was already registered, do not register again."""
        mock_hass.data = {DOMAIN: {CARD_REGISTERED_KEY: True}}
        _patch_card_path(monkeypatch, is_file=True)

        await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_card_file_missing(self, mock_hass, monkeypatch):
        """If the built card file is absent, log and skip without registering."""
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=False)

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ) as mock_spc:
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_not_called()
        mock_add_url.assert_not_called()
        mock_spc.assert_not_called()
        assert CARD_REGISTERED_KEY not in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_registers_when_card_present(self, mock_hass, monkeypatch):
        """When the card file exists, register a static path and auto-load it."""
        mock_hass.data = {DOMAIN: {}}
        card_path = _patch_card_path(monkeypatch, is_file=True)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ) as mock_spc:
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_awaited_once()
        # The static path config should be built with the public URL and the
        # resolved card path, with caching disabled during development.
        mock_spc.assert_called_once_with(
            CARD_URL_PATH, str(card_path), cache_headers=True
        )
        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_PATH)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True

    @pytest.mark.asyncio
    async def test_handles_missing_frontend_integration(self, mock_hass, monkeypatch):
        """If the frontend integration is not loaded (KeyError), skip gracefully."""
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=True)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET, side_effect=KeyError) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_awaited_once()
        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_PATH)
        # Registration is not marked as complete, so a later setup can retry.
        assert CARD_REGISTERED_KEY not in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_idempotent_across_calls(self, mock_hass, monkeypatch):
        """A second call after a successful registration is a no-op."""
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=True)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_awaited_once()
        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_PATH)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True