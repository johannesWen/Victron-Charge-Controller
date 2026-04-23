"""Switch platform for Victron Charge Control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VictronChargeControlCoordinator


@dataclass(frozen=True, kw_only=True)
class VictronCCSwitchDescription(SwitchEntityDescription):
    """Extended description for Victron CC switch entities."""

    coordinator_attr: str
    default_value: bool = True


SWITCHES: tuple[VictronCCSwitchDescription, ...] = (
    VictronCCSwitchDescription(
        key="charge_allowed",
        translation_key="charge_allowed",
        icon="mdi:battery-plus",
        coordinator_attr="charge_allowed",
        default_value=True,
    ),
    VictronCCSwitchDescription(
        key="discharge_allowed",
        translation_key="discharge_allowed",
        icon="mdi:battery-minus",
        coordinator_attr="discharge_allowed",
        default_value=True,
    ),
    VictronCCSwitchDescription(
        key="grid_feed_in_control_enabled",
        translation_key="grid_feed_in_control_enabled",
        icon="mdi:transmission-tower",
        coordinator_attr="grid_feed_in_control_enabled",
        default_value=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VictronCCSwitch(coordinator, entry, desc) for desc in SWITCHES
    )


class VictronCCSwitch(CoordinatorEntity[VictronChargeControlCoordinator], SwitchEntity, RestoreEntity):
    """Toggle switch for charge/discharge allowed."""

    _attr_has_entity_name = True
    entity_description: VictronCCSwitchDescription

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
        description: VictronCCSwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return getattr(self.coordinator, self.entity_description.coordinator_attr)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        setattr(self.coordinator, self.entity_description.coordinator_attr, True)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        setattr(self.coordinator, self.entity_description.coordinator_attr, False)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            setattr(
                self.coordinator,
                self.entity_description.coordinator_attr,
                last_state.state == "on",
            )
