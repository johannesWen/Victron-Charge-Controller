"""Victron Charge Control integration for Home Assistant.

Automates Victron ESS battery charge/discharge based on EPEX Spot prices.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import VictronChargeControlCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SWITCH, Platform.BUTTON, Platform.TEXT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Victron Charge Control from a config entry."""
    coordinator = VictronChargeControlCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

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
        coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        # Unregister services if no entries left
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)
            hass.data.pop(DOMAIN)

    return unload_ok
