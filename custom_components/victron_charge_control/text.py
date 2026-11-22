"""Text platform for Victron Charge Control."""

from __future__ import annotations

import logging
import re

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_BUY_PRICE,
    CONF_SELL_PRICE,
    DEFAULT_BLOCKED_CHARGING_HOURS,
    DEFAULT_BLOCKED_DISCHARGING_HOURS,
    DEFAULT_REPLAN_HOURS,
    DOMAIN,
)
from .coordinator import VictronChargeControlCoordinator
from .energy import parse_tariff_eur_per_kwh

_LOGGER = logging.getLogger(__name__)

_VALID_PATTERN = re.compile(r"^(\d{1,2}(,\s*\d{1,2})*)?$")


def _parse_hours(value: str) -> list[int]:
    """Parse a comma-separated string of hours into a sorted list of valid hours."""
    if not value or not value.strip():
        return []
    parts = [p.strip() for p in value.split(",") if p.strip()]
    hours: list[int] = []
    for part in parts:
        try:
            h = int(part)
        except ValueError:
            continue
        if 0 <= h <= 23 and h not in hours:
            hours.append(h)
    return sorted(hours)


def _format_hours(hours: list[int]) -> str:
    """Format a list of hours into a comma-separated string."""
    return ", ".join(str(h) for h in sorted(hours))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up text entities."""
    coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        BlockedChargingHoursText(coordinator, entry),
        BlockedDischargingHoursText(coordinator, entry),
        ReplanHoursText(coordinator, entry),
        TariffText(entry, CONF_BUY_PRICE),
        TariffText(entry, CONF_SELL_PRICE),
    ])


class TariffText(TextEntity):
    """A fixed History tariff persisted in the config entry options."""

    _attr_has_entity_name = True
    _attr_unit_of_measurement = "ct/kWh"

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self._entry = entry
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}_text"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str:
        """Return the fixed price in ct/kWh, or an empty string for EPEX."""
        value = self._entry.options.get(self._key, "")
        return value if parse_tariff_eur_per_kwh(value) is not None else ""

    async def async_set_value(self, value: str) -> None:
        """Save a fixed price or clear it to restore EPEX accounting."""
        value = value.strip()
        if value and parse_tariff_eur_per_kwh(value) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_tariff",
            )
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, self._key: value},
        )
        self.async_write_ha_state()


class BlockedChargingHoursText(
    CoordinatorEntity[VictronChargeControlCoordinator], TextEntity, RestoreEntity
):
    """Text entity to set blocked charging hours as a comma-separated list."""

    _attr_has_entity_name = True
    _attr_translation_key = "blocked_charging_hours"
    _attr_icon = "mdi:clock-remove-outline"
    _attr_native_max = 100
    _attr_pattern = r"^(\d{1,2}(,\s*\d{1,2})*)?$"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_blocked_charging_hours_text"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str:
        """Return current blocked charging hours as comma-separated string."""
        return _format_hours(self.coordinator.blocked_charging_hours)

    async def async_set_value(self, value: str) -> None:
        """Parse the input and update blocked charging hours."""
        hours = _parse_hours(value)
        self.coordinator.set_blocked_charging_hours(hours)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in ("unknown", "unavailable"):
            self.coordinator.set_blocked_charging_hours(list(DEFAULT_BLOCKED_CHARGING_HOURS))
        else:
            hours = _parse_hours(last_state.state)
            self.coordinator.set_blocked_charging_hours(hours)


class BlockedDischargingHoursText(
    CoordinatorEntity[VictronChargeControlCoordinator], TextEntity, RestoreEntity
):
    """Text entity to set blocked discharging hours as a comma-separated list."""

    _attr_has_entity_name = True
    _attr_translation_key = "blocked_discharging_hours"
    _attr_icon = "mdi:clock-remove-outline"
    _attr_native_max = 100
    _attr_pattern = r"^(\d{1,2}(,\s*\d{1,2})*)?$"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_blocked_discharging_hours_text"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str:
        """Return current blocked discharging hours as comma-separated string."""
        return _format_hours(self.coordinator.blocked_discharging_hours)

    async def async_set_value(self, value: str) -> None:
        """Parse the input and update blocked discharging hours."""
        hours = _parse_hours(value)
        self.coordinator.set_blocked_discharging_hours(hours)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in ("unknown", "unavailable"):
            self.coordinator.set_blocked_discharging_hours(list(DEFAULT_BLOCKED_DISCHARGING_HOURS))
        else:
            hours = _parse_hours(last_state.state)
            self.coordinator.set_blocked_discharging_hours(hours)


class ReplanHoursText(
    CoordinatorEntity[VictronChargeControlCoordinator], TextEntity, RestoreEntity
):
    """Text entity to set the hours (comma-separated) at which the auto/manual
    schedule is recalculated.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "replan_hours"
    _attr_icon = "mdi:calendar-refresh"
    _attr_native_max = 100
    _attr_pattern = r"^(\d{1,2}(,\s*\d{1,2})*)?$"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_replan_hours_text"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str:
        """Return current replan hours as comma-separated string."""
        return _format_hours(self.coordinator.replan_hours)

    async def async_set_value(self, value: str) -> None:
        """Parse the input and update replan hours."""
        hours = _parse_hours(value)
        self.coordinator.set_replan_hours(hours)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in ("unknown", "unavailable"):
            self.coordinator.set_replan_hours(list(DEFAULT_REPLAN_HOURS))
        else:
            hours = _parse_hours(last_state.state)
            self.coordinator.set_replan_hours(hours)
