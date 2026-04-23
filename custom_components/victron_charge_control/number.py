"""Number platform for Victron Charge Control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_CHARGE_POWER,
    DEFAULT_CHARGE_PRICE_THRESHOLD,
    DEFAULT_CHEAPEST_HOURS,
    DEFAULT_DISCHARGE_POWER,
    DEFAULT_DISCHARGE_PRICE_THRESHOLD,
    DEFAULT_EXPENSIVE_HOURS,
    DEFAULT_GRID_FEED_IN_PRICE_THRESHOLD,
    DEFAULT_IDLE_SETPOINT,
    DEFAULT_MAX_GRID_FEED_IN,
    DEFAULT_MAX_GRID_SETPOINT,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_GRID_SETPOINT,
    DEFAULT_MIN_SOC,
    DEFAULT_REDUCED_GRID_FEED_IN,
    DOMAIN,
)
from .coordinator import VictronChargeControlCoordinator


@dataclass(frozen=True, kw_only=True)
class VictronCCNumberDescription(NumberEntityDescription):
    """Extended description for Victron CC number entities."""

    coordinator_attr: str
    default_value: float
    native_min_value: float = 0
    native_max_value: float = 100
    native_step: float = 1


NUMBERS: tuple[VictronCCNumberDescription, ...] = (
    VictronCCNumberDescription(
        key="min_soc",
        translation_key="min_soc",
        icon="mdi:battery-low",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        coordinator_attr="min_soc",
        default_value=DEFAULT_MIN_SOC,
    ),
    VictronCCNumberDescription(
        key="max_soc",
        translation_key="max_soc",
        icon="mdi:battery-high",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        coordinator_attr="max_soc",
        default_value=DEFAULT_MAX_SOC,
    ),
    VictronCCNumberDescription(
        key="charge_power",
        translation_key="charge_power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        coordinator_attr="charge_power",
        default_value=DEFAULT_CHARGE_POWER,
    ),
    VictronCCNumberDescription(
        key="discharge_power",
        translation_key="discharge_power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        coordinator_attr="discharge_power",
        default_value=DEFAULT_DISCHARGE_POWER,
    ),
    VictronCCNumberDescription(
        key="idle_setpoint",
        translation_key="idle_setpoint",
        icon="mdi:pause-circle",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=-500,
        native_max_value=500,
        native_step=10,
        coordinator_attr="idle_setpoint",
        default_value=DEFAULT_IDLE_SETPOINT,
    ),
    VictronCCNumberDescription(
        key="min_grid_setpoint",
        translation_key="min_grid_setpoint",
        icon="mdi:arrow-down-bold",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=-15000,
        native_max_value=0,
        native_step=100,
        coordinator_attr="min_grid_setpoint",
        default_value=DEFAULT_MIN_GRID_SETPOINT,
    ),
    VictronCCNumberDescription(
        key="max_grid_setpoint",
        translation_key="max_grid_setpoint",
        icon="mdi:arrow-up-bold",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        coordinator_attr="max_grid_setpoint",
        default_value=DEFAULT_MAX_GRID_SETPOINT,
    ),
    VictronCCNumberDescription(
        key="cheapest_hours",
        translation_key="cheapest_hours",
        icon="mdi:clock-fast",
        native_min_value=0,
        native_max_value=12,
        native_step=1,
        coordinator_attr="cheapest_hours",
        default_value=DEFAULT_CHEAPEST_HOURS,
    ),
    VictronCCNumberDescription(
        key="expensive_hours",
        translation_key="expensive_hours",
        icon="mdi:clock-alert",
        native_min_value=0,
        native_max_value=12,
        native_step=1,
        coordinator_attr="expensive_hours",
        default_value=DEFAULT_EXPENSIVE_HOURS,
    ),
    VictronCCNumberDescription(
        key="charge_price_threshold",
        translation_key="charge_price_threshold",
        icon="mdi:currency-eur",
        native_unit_of_measurement="ct/kWh",
        native_min_value=-50,
        native_max_value=100,
        native_step=0.5,
        coordinator_attr="charge_price_threshold",
        default_value=DEFAULT_CHARGE_PRICE_THRESHOLD,
    ),
    VictronCCNumberDescription(
        key="discharge_price_threshold",
        translation_key="discharge_price_threshold",
        icon="mdi:currency-eur",
        native_unit_of_measurement="ct/kWh",
        native_min_value=-50,
        native_max_value=100,
        native_step=0.5,
        coordinator_attr="discharge_price_threshold",
        default_value=DEFAULT_DISCHARGE_PRICE_THRESHOLD,
    ),
    VictronCCNumberDescription(
        key="grid_feed_in_price_threshold",
        translation_key="grid_feed_in_price_threshold",
        icon="mdi:currency-eur",
        native_unit_of_measurement="ct/kWh",
        native_min_value=-50,
        native_max_value=100,
        native_step=0.5,
        coordinator_attr="grid_feed_in_price_threshold",
        default_value=DEFAULT_GRID_FEED_IN_PRICE_THRESHOLD,
    ),
    VictronCCNumberDescription(
        key="default_max_grid_feed_in",
        translation_key="default_max_grid_feed_in",
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        coordinator_attr="default_max_grid_feed_in",
        default_value=DEFAULT_MAX_GRID_FEED_IN,
    ),
    VictronCCNumberDescription(
        key="reduced_max_grid_feed_in",
        translation_key="reduced_max_grid_feed_in",
        icon="mdi:transmission-tower-off",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        coordinator_attr="reduced_max_grid_feed_in",
        default_value=DEFAULT_REDUCED_GRID_FEED_IN,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VictronCCNumber(coordinator, entry, desc) for desc in NUMBERS
    )


class VictronCCNumber(CoordinatorEntity[VictronChargeControlCoordinator], NumberEntity, RestoreEntity):
    """A configurable number entity that writes directly to the coordinator."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    entity_description: VictronCCNumberDescription

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
        description: VictronCCNumberDescription,
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
        # Use box mode for thresholds
        if "threshold" in description.key:
            self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float:
        return getattr(self.coordinator, self.entity_description.coordinator_attr)

    async def async_set_native_value(self, value: float) -> None:
        """Update the coordinator attribute and trigger refresh."""
        attr = self.entity_description.coordinator_attr
        # Use int for hour counts
        if attr in ("cheapest_hours", "expensive_hours"):
            setattr(self.coordinator, attr, int(value))
        else:
            setattr(self.coordinator, attr, value)

        # Recalculate schedule if auto-mode params changed
        if attr in (
            "cheapest_hours",
            "expensive_hours",
            "charge_price_threshold",
            "discharge_price_threshold",
        ) and self.coordinator.control_mode == "auto":
            self.coordinator.calculate_auto_schedule()

        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last known value from HA state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unavailable", "unknown"):
            try:
                value = float(last_state.state)
                attr = self.entity_description.coordinator_attr
                if attr in ("cheapest_hours", "expensive_hours"):
                    setattr(self.coordinator, attr, int(value))
                else:
                    setattr(self.coordinator, attr, value)
            except (ValueError, TypeError):
                pass
