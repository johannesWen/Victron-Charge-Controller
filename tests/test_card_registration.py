"""Tests for the bundled Lovelace card registration in ``__init__``."""

from __future__ import annotations

import hashlib
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

CARD_CONTENT_A = b"// card build A"
CARD_CONTENT_B = b"// card build B - different content"


def _hash_url(content: bytes) -> str:
    """Compute the cache-busting URL the production code derives for content."""
    import hashlib

    digest = hashlib.sha256(content).hexdigest()[:12]
    return f"{CARD_URL_PATH}?v={digest}"


def _patch_card_path(monkeypatch, *, is_file: bool, content: bytes = CARD_CONTENT_A) -> MagicMock:
    """Patch ``Path`` so the card path resolves to a controllable mock.

    The production code computes ``Path(__file__).parent / "static" / CARD_FILE_NAME``
    so we wire the ``__truediv__`` chain to return a mock whose ``is_file()``
    behaves as requested and whose ``read_bytes()`` supplies hashable content.
    """
    card_path = MagicMock()
    card_path.is_file.return_value = is_file
    card_path.read_bytes.return_value = content

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
        # The static path is registered at the bare (unversioned) URL: aiohttp
        # routes on the path and ignores the query string used for cache
        # busting. Long-term caching stays enabled for unchanged builds.
        mock_spc.assert_called_once_with(
            CARD_URL_PATH, str(card_path), cache_headers=True
        )
        # The URL injected into the frontend carries the content-hash query
        # so the companion apps' persistent WebView cache is busted whenever
        # the shipped card changes.
        mock_add_url.assert_called_once_with(mock_hass, _hash_url(CARD_CONTENT_A))
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True

    @pytest.mark.asyncio
    async def test_url_changes_when_card_content_changes(self, mock_hass, monkeypatch):
        """Different card builds must produce different cache-bust tokens.

        Release candidates share one manifest version on purpose, so a
        version-based token could serve a stale rc card; the content hash
        keeps the URL unique per shipped file.
        """
        mock_hass.data = {DOMAIN: {}}
        card_path = _patch_card_path(monkeypatch, is_file=True, content=CARD_CONTENT_A)
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url_a, patch(STATIC_PATH_CONFIG_TARGET):
            await _async_register_card(mock_hass)

        # Registration is idempotent per boot; simulate a new boot with a
        # rebuilt card so the second call goes through with new content.
        mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] = False
        _patch_card_path(monkeypatch, is_file=True, content=CARD_CONTENT_B)
        with patch(ADD_JS_URL_TARGET) as mock_add_url_b, patch(STATIC_PATH_CONFIG_TARGET):
            await _async_register_card(mock_hass)

        url_a = mock_add_url_a.call_args.args[1]
        url_b = mock_add_url_b.call_args.args[1]
        assert url_a == _hash_url(CARD_CONTENT_A)
        assert url_b == _hash_url(CARD_CONTENT_B)
        assert url_a != url_b

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
        mock_add_url.assert_called_once_with(mock_hass, _hash_url(CARD_CONTENT_A))
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
        mock_add_url.assert_called_once_with(mock_hass, _hash_url(CARD_CONTENT_A))
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_bare_url_when_hashing_fails(
        self, mock_hass, monkeypatch
    ):
        """A failure hashing the card must not break setup.

        Cache-busting is best-effort: if the content cannot be read the
        card is still registered, just at its unversioned URL.
        """
        mock_hass.data = {DOMAIN: {}}
        card_path = _patch_card_path(monkeypatch, is_file=True)
        card_path.read_bytes.side_effect = OSError("disk gone")
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(ADD_JS_URL_TARGET) as mock_add_url, patch(
            STATIC_PATH_CONFIG_TARGET
        ):
            await _async_register_card(mock_hass)

        mock_add_url.assert_called_once_with(mock_hass, CARD_URL_PATH)
        assert mock_hass.data[DOMAIN][CARD_REGISTERED_KEY] is True
