"""Victron Charge Control integration for Home Assistant.

Automates Victron ESS battery charge/discharge based on EPEX Spot prices.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_FILE_NAME, CARD_REGISTERED_KEY, CARD_URL_PATH, DOMAIN
from .coordinator import VictronChargeControlCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.TEXT,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Victron Charge Control integration.

    Registers the bundled Lovelace card once per HA boot, independent of
    any config entry. This lets users add the card to a dashboard before
    they have completed the integration's config flow.
    """
    hass.data.setdefault(DOMAIN, {})
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Register and auto-load the bundled Lovelace card.

    The card is built from ``frontend/`` at release time and shipped inside
    the integration directory under ``static/``. HACS installs it together
    with the Python code, so users do not need a separate Lovelace resource
    entry. Registration is idempotent and only runs once per HA boot.
    """
    if hass.data[DOMAIN].get(CARD_REGISTERED_KEY):
        return

    card_path = Path(__file__).parent / "static" / CARD_FILE_NAME
    if not card_path.is_file():
        _LOGGER.warning(
            "Bundled Lovelace card not found at %s; the card will not be "
            "auto-loaded. Build it with `npm run build` in the frontend/ "
            "directory. The integration itself remains functional.",
            card_path,
        )
        return

    # Home Assistant serves static paths with a one-month ``Cache-Control:
    # public, max-age`` header and the card lives at a fixed, unversioned URL.
    # Desktop browsers revalidate (or get hard-refreshed during development),
    # but the Android/iOS companion apps keep a persistent WebView HTTP cache
    # that honors that max-age across app and HA restarts. Without a
    # cache-busting token they keep serving a stale build -- or a 404 cached
    # from a boot where the card was not yet registered -- so the card shows up
    # in the browser but is "not available" in the app. Appending the
    # integration version to the injected URL changes it on every release,
    # which invalidates the cached copy, while unchanged versions still cache
    # long-term. The static path itself stays unversioned because aiohttp
    # routes on the path and ignores the query string.
    card_url = CARD_URL_PATH
    try:
        integration = await async_get_integration(hass, DOMAIN)
        if integration.version is not None:
            card_url = f"{CARD_URL_PATH}?v={integration.version}"
    except Exception:  # noqa: BLE001 - version is best-effort cache-busting only
        _LOGGER.debug(
            "Could not resolve integration version for card cache-busting; "
            "serving the card at its unversioned URL.",
            exc_info=True,
        )

    # The frontend integration populates the URL manager used by
    # ``add_extra_js_url``. If it is not loaded (e.g. a user disabled it),
    # skip auto-loading the card rather than crashing setup.
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=True)]
        )
        add_extra_js_url(hass, card_url)
    except KeyError:
        _LOGGER.warning(
            "Frontend integration is not loaded; the bundled Lovelace card "
            "will not be auto-loaded. Enable the frontend integration to use "
            "the card."
        )
        return
    hass.data[DOMAIN][CARD_REGISTERED_KEY] = True
    _LOGGER.info("Bundled Lovelace card registered at %s", card_url)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Victron Charge Control from a config entry."""
    coordinator = VictronChargeControlCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_setup()

    # Register services once, when the first config entry is set up.
    # Count only config-entry keys (the card_registered flag also lives in
    # hass.data[DOMAIN] but is not a config entry).
    config_entry_count = sum(
        1
        for key in hass.data[DOMAIN]
        if key != CARD_REGISTERED_KEY
    )
    if config_entry_count == 1:
        await async_setup_services(hass)

    # Register the bundled card (idempotent: skips if already registered,
    # e.g. by ``async_setup`` for YAML setups or a previous config entry).
    await _async_register_card(hass)

    # Reload integration when config entry data changes (options flow)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info("Victron Charge Control loaded")
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when the config entry is updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_shutdown()

        # Unregister services if no config entries are left (the
        # card_registered flag remains in hass.data[DOMAIN] for the
        # lifetime of the HA boot, so count only config-entry keys).
        config_entry_count = sum(
            1
            for key in hass.data[DOMAIN]
            if key != CARD_REGISTERED_KEY
        )
        if config_entry_count == 0:
            await async_unload_services(hass)

    return unload_ok