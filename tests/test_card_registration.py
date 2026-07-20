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
GET_INTEGRATION_TARGET = (
    "custom_components.victron_charge_control.async_get_integration"
)

TEST_VERSION = "2.0.0"
CARD_URL_VERSIONED = f"{CARD_URL_PATH}?v={TEST_VERSION}"


def _patch_integration_version(monkeypatch, version: str | None) -> None:
    """Patch ``async_get_integration`` to report a controllable version.

    The production code appends the integration version to the injected card
    URL as a cache-busting token; this lets tests exercise that behavior
    without a real Home Assistant integration manifest.
    """
    integration = MagicMock()
    integration.version = version
    monkeypatch.setattr(
        GET_INTEGRATION_TARGET, AsyncMock(return_value=integration)
    )


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
        _patch_integration_version(monkeypatch, TEST_VERSION)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ) as mock_spc:
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_awaited_once()
        # The static path is registered at the bare (unversioned) URL: aiohttp
        # routes on the path and ignores the query string used for cache
        # busting. Long-term caching stays enabled for unchanged versions.
        mock_spc.assert_called_once_with(
            CARD_URL_PATH, str(card_path), cache_headers=True
        )
        # The URL injected into the frontend carries the version query so the
        # companion apps' persistent WebView cache is busted on each release.
        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_VERSIONED)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True

    @pytest.mark.asyncio
    async def test_handles_missing_frontend_integration(self, mock_hass, monkeypatch):
        """If the frontend integration is not loaded (KeyError), skip gracefully."""
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=True)
        _patch_integration_version(monkeypatch, TEST_VERSION)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET, side_effect=KeyError) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_awaited_once()
        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_VERSIONED)
        # Registration is not marked as complete, so a later setup can retry.
        assert CARD_REGISTERED_KEY not in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_idempotent_across_calls(self, mock_hass, monkeypatch):
        """A second call after a successful registration is a no-op."""
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=True)
        _patch_integration_version(monkeypatch, TEST_VERSION)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)
            await _async_register_card(mock_hass)

        mock_hass.http.async_register_static_paths.assert_awaited_once()
        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_VERSIONED)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_bare_url_without_version(
        self, mock_hass, monkeypatch
    ):
        """If the manifest has no version, inject the unversioned URL."""
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=True)
        _patch_integration_version(monkeypatch, None)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)

        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_PATH)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_bare_url_when_version_lookup_fails(
        self, mock_hass, monkeypatch
    ):
        """A failure resolving the integration version must not break setup.

        Cache-busting is best-effort: if the version cannot be resolved the
        card is still registered, just at its unversioned URL.
        """
        mock_hass.data = {DOMAIN: {}}
        _patch_card_path(monkeypatch, is_file=True)
        monkeypatch.setattr(
            GET_INTEGRATION_TARGET, AsyncMock(side_effect=RuntimeError("boom"))
        )
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)

        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_PATH)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True