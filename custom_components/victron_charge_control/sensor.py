"""Sensor platform for Victron Charge Control."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ChargeControlData, VictronChargeControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: VictronChargeControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DesiredActionSensor(coordinator, entry),
            TargetSetpointSensor(coordinator, entry),
            ScheduleSensor(coordinator, entry, "charge"),
            ScheduleSensor(coordinator, entry, "discharge"),
            ScheduleSensor(coordinator, entry, "blocked"),
            ChargePlanSensor(coordinator, entry),
        ]
    )


class VictronCCBaseSensor(CoordinatorEntity[VictronChargeControlCoordinator], SensorEntity):
    """Base class for Victron CC sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Victron Charge Control",
            manufacturer="Victron Energy",
            entry_type=DeviceEntryType.SERVICE,
        )


class DesiredActionSensor(VictronCCBaseSensor):
    """Sensor showing the current desired action (charge/discharge/idle)."""

    _attr_translation_key = "desired_action"
    _attr_icon = "mdi:battery-sync"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_desired_action"

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = "idle"
        else:
            self._attr_native_value = data.desired_action
            self._attr_icon = {
                "charge": "mdi:battery-charging",
                "discharge": "mdi:battery-arrow-down",
            }.get(data.desired_action, "mdi:battery-outline")
        self._attr_extra_state_attributes = {
            "mode": self.coordinator.control_mode,
            "charge_hours": self.coordinator.charge_hours,
            "discharge_hours": self.coordinator.discharge_hours,
            "blocked_hours": self.coordinator.blocked_hours,
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return data.desired_action if data else "idle"


class TargetSetpointSensor(VictronCCBaseSensor):
    """Sensor showing the target grid setpoint in Watts."""

    _attr_translation_key = "target_setpoint"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_target_setpoint"

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = 0.0
        else:
            self._attr_native_value = data.target_setpoint
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        data = self.coordinator.data
        return data.target_setpoint if data else 0.0


class ScheduleSensor(VictronCCBaseSensor):
    """Sensor showing scheduled charge or discharge hours as a comma-separated string."""

    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
        schedule_type: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._schedule_type = schedule_type
        self._attr_unique_id = f"{entry.entry_id}_{schedule_type}_hours"
        self._attr_translation_key = f"{schedule_type}_hours"
        self._attr_icon = {
            "charge": "mdi:battery-charging",
            "discharge": "mdi:battery-arrow-down",
            "blocked": "mdi:cancel",
        }.get(schedule_type, "mdi:clock-outline")

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = ""
        else:
            hours = {
                "charge": data.charge_hours,
                "discharge": data.discharge_hours,
                "blocked": data.blocked_hours,
            }.get(self._schedule_type, [])
            self._attr_native_value = ",".join(str(h) for h in hours)
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data is None:
            return ""
        hours = {
            "charge": data.charge_hours,
            "discharge": data.discharge_hours,
            "blocked": data.blocked_hours,
        }.get(self._schedule_type, [])
        return ",".join(str(h) for h in hours)


class ChargePlanSensor(VictronCCBaseSensor):
    """Sensor showing the full charge/discharge plan based on EPEX prices."""

    _attr_translation_key = "charge_plan"
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_charge_plan"

    def _build_plan(self, data: ChargeControlData) -> list[dict]:
        """Build hour-by-hour plan from coordinator data."""
        price_map = {p["hour"]: p["price"] for p in data.prices_today}
        plan = []
        for hour in range(24):
            if hour in data.blocked_hours:
                action = "blocked"
            elif hour in data.charge_hours:
                action = "charge"
            elif hour in data.discharge_hours:
                action = "discharge"
            else:
                action = "idle"
            entry = {"hour": hour, "action": action}
            if hour in price_map:
                entry["price"] = price_map[hour]
            plan.append(entry)
        return plan

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = "unknown"
            self._attr_extra_state_attributes = {"plan": []}
        else:
            charge_count = len(data.charge_hours)
            discharge_count = len(data.discharge_hours)
            self._attr_native_value = (
                f"{charge_count} charge, {discharge_count} discharge"
            )
            self._attr_extra_state_attributes = {
                "plan": self._build_plan(data),
                "charge_hours": data.charge_hours,
                "discharge_hours": data.discharge_hours,
                "blocked_hours": data.blocked_hours,
            }
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data is None:
            return "unknown"
        return f"{len(data.charge_hours)} charge, {len(data.discharge_hours)} discharge"
