"""Button platform for Victron Charge Control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VictronChargeControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RecalculateScheduleButton(coordinator, entry)])


class RecalculateScheduleButton(ButtonEntity):
    """Button to recalculate the charge/discharge schedule from EPEX prices."""

    _attr_has_entity_name = True
    _attr_translation_key = "recalculate_schedule"
    _attr_icon = "mdi:calculator-variant"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_recalculate_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Recalculate the schedule."""
        self._coordinator.calculate_auto_schedule()
        await self._coordinator.async_request_refresh()
