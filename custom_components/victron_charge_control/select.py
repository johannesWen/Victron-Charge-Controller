"""Select platform for Victron Charge Control."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROL_MODES, DOMAIN, MODE_AUTO, MODE_OFF
from .coordinator import VictronChargeControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ControlModeSelect(coordinator, entry)])


class ControlModeSelect(CoordinatorEntity[VictronChargeControlCoordinator], SelectEntity, RestoreEntity):
    """Select entity for the control mode (off/auto/manual/force_charge/force_discharge)."""

    _attr_has_entity_name = True
    _attr_translation_key = "control_mode"
    _attr_icon = "mdi:battery-sync"
    _attr_options = CONTROL_MODES

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_control_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def current_option(self) -> str:
        return self.coordinator.control_mode

    async def async_select_option(self, option: str) -> None:
        """Set the control mode."""
        if option not in CONTROL_MODES:
            return
        self.coordinator.control_mode = option
        # Recalculate schedule when switching to auto
        if option == MODE_AUTO:
            self.coordinator.calculate_auto_schedule()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and last_state.state in CONTROL_MODES
        ):
            self.coordinator.control_mode = last_state.state
