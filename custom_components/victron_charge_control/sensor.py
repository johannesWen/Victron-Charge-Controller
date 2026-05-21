"""Sensor platform for Victron Charge Control."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

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
            CurrentPriceSensor(coordinator, entry),
            ScheduleSensor(coordinator, entry, "charge"),
            ScheduleSensor(coordinator, entry, "discharge"),
            ScheduleSensor(coordinator, entry, "blocked_charging"),
            ScheduleSensor(coordinator, entry, "blocked_discharging"),
            ChargePlanSensor(coordinator, entry),
            LastScheduleUpdateSensor(coordinator, entry),
            GridFeedInStatusSensor(coordinator, entry),
            GridEnergyCostSensor(coordinator, entry, "grid_cost"),
            GridEnergyCostSensor(coordinator, entry, "grid_revenue"),
            GridEnergySensor(coordinator, entry, "grid_import"),
            GridEnergySensor(coordinator, entry, "grid_export"),
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


class VictronCCBaseRestoreSensor(
    CoordinatorEntity[VictronChargeControlCoordinator],
    RestoreSensor,
):
    """Base class for Victron CC sensors that restore state."""

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

    @staticmethod
    def _as_float(value: object) -> float | None:
        try:
            if value in (None, "unknown", "unavailable"):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return dt_util.parse_datetime(value)
        return None


class GridEnergyCostSensor(VictronCCBaseRestoreSensor):
    """Sensor showing cumulative gross cost/revenue from optional kWh meters."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:currency-eur"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
        tracker: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._tracker = tracker
        self._attr_translation_key = {
            "grid_cost": "grid_energy_cost",
            "grid_revenue": "grid_energy_revenue",
        }[tracker]
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"

    @property
    def _source_entities(self) -> list[str]:
        return [
            entity_id
            for entity_id in (
                self.coordinator.grid_consumption_entity,
                self.coordinator.grid_feed_in_energy_entity,
            )
            if entity_id is not None
        ]

    @property
    def _coordinator_value(self) -> float | None:
        if self._tracker == "grid_cost":
            return self.coordinator.grid_energy_cost
        return self.coordinator.grid_energy_revenue

    @property
    def available(self) -> bool:
        return bool(self._source_entities) and super().available

    async def async_added_to_hass(self) -> None:
        """Restore cumulative EUR value and last kWh baseline."""
        await super().async_added_to_hass()
        await self._restore_cost_state()

    async def _restore_cost_state(self) -> None:
        """Restore cumulative EUR value and meter baseline from HA storage."""
        total = None
        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data is not None:
            total = self._as_float(last_sensor_data.native_value)

        last_state = await self.async_get_last_state()
        last_grid_consumption_kwh = None
        last_grid_feed_in_kwh = None
        last_cost_update = None
        if last_state is not None:
            if total is None:
                total = self._as_float(last_state.state)
            last_grid_consumption_kwh = self._as_float(
                last_state.attributes.get("last_grid_consumption_kwh")
            )
            last_grid_feed_in_kwh = self._as_float(
                last_state.attributes.get("last_grid_feed_in_kwh")
            )
            last_cost_update = self._as_datetime(
                last_state.attributes.get("last_cost_update")
            )

        self.coordinator.restore_cost_state(
            self._tracker,
            total,
            last_cost_update,
            last_grid_consumption_kwh,
            last_grid_feed_in_kwh,
        )
        if self._source_entities:
            self.coordinator.hass.async_create_task(
                self.coordinator.async_request_refresh()
            )

    def _build_attributes(self) -> dict[str, object]:
        data: ChargeControlData | None = self.coordinator.data
        last_cost_update = self.coordinator.last_cost_update
        return {
            "source_entities": self._source_entities,
            "last_grid_consumption_kwh": self.coordinator.last_grid_consumption_kwh,
            "last_grid_feed_in_kwh": self.coordinator.last_grid_feed_in_kwh,
            "last_cost_update": (
                last_cost_update.isoformat() if last_cost_update else None
            ),
            "current_price_eur_per_kwh": (
                data.current_price_eur_per_kwh if data else None
            ),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self.native_value
        self._attr_extra_state_attributes = self._build_attributes()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self._coordinator_value

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return self._build_attributes()


class GridEnergySensor(VictronCCBaseRestoreSensor):
    """Sensor showing cumulative energy import/export in kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:transmission-tower"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
        tracker: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._tracker = tracker
        self._attr_translation_key = {
            "grid_import": "grid_energy_import",
            "grid_export": "grid_energy_export",
        }[tracker]
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"

    @property
    def _coordinator_value(self) -> float | None:
        if self._tracker == "grid_import":
            return self.coordinator.grid_energy_import
        return self.coordinator.grid_energy_export

    @property
    def available(self) -> bool:
        return bool(self._source_entities) and super().available

    @property
    def _source_entities(self) -> list[str]:
        return [
            entity_id
            for entity_id in (
                self.coordinator.grid_consumption_entity,
                self.coordinator.grid_feed_in_energy_entity,
            )
            if entity_id is not None
        ]

    async def async_added_to_hass(self) -> None:
        """Restore cumulative kWh value and baseline."""
        await super().async_added_to_hass()
        await self._restore_energy_state()

    async def _restore_energy_state(self) -> None:
        """Restore cumulative kWh value and meter baseline from HA storage."""
        total = None
        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data is not None:
            total = self._as_float(last_sensor_data.native_value)

        last_state = await self.async_get_last_state()
        last_grid_consumption_kwh = None
        last_grid_feed_in_kwh = None
        last_energy_update = None
        if last_state is not None:
            if total is None:
                total = self._as_float(last_state.state)
            last_grid_consumption_kwh = self._as_float(
                last_state.attributes.get("last_grid_consumption_kwh")
            )
            last_grid_feed_in_kwh = self._as_float(
                last_state.attributes.get("last_grid_feed_in_kwh")
            )
            last_energy_update = self._as_datetime(
                last_state.attributes.get("last_energy_update")
            )

        self.coordinator.restore_energy_state(
            self._tracker,
            total,
            last_energy_update,
            last_grid_consumption_kwh,
            last_grid_feed_in_kwh,
        )
        if self._source_entities:
            self.coordinator.hass.async_create_task(
                self.coordinator.async_request_refresh()
            )

    def _build_attributes(self) -> dict[str, object]:
        data: ChargeControlData | None = self.coordinator.data
        last_energy_update = self.coordinator.last_energy_update
        return {
            "source_entities": self._source_entities,
            "last_grid_consumption_kwh": self.coordinator.last_grid_consumption_kwh,
            "last_grid_feed_in_kwh": self.coordinator.last_grid_feed_in_kwh,
            "last_energy_update": (
                last_energy_update.isoformat() if last_energy_update else None
            ),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self.native_value
        self._attr_extra_state_attributes = self._build_attributes()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self._coordinator_value

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return self._build_attributes()


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
            "charge_hours": self.coordinator.data.charge_hours if self.coordinator.data else [],
            "discharge_hours": self.coordinator.data.discharge_hours if self.coordinator.data else [],
            "blocked_charging_hours": self.coordinator.blocked_charging_hours,
            "blocked_discharging_hours": self.coordinator.blocked_discharging_hours,
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


class CurrentPriceSensor(VictronCCBaseSensor):
    """Sensor showing the current EPEX spot price."""

    _attr_translation_key = "current_price"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "€/kWh"
    _attr_icon = "mdi:currency-eur"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_price"

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
        else:
            self._attr_native_value = data.current_price
            self._attr_extra_state_attributes = dict(data.epex_attributes)
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return data.current_price if data else None


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
            "blocked_charging": "mdi:cancel",
            "blocked_discharging": "mdi:cancel",
        }.get(schedule_type, "mdi:clock-outline")

    @staticmethod
    def _format_slots(slots: list[dict]) -> str:
        """Format date-aware slots into compact grouped string.

        Input:  [{"date": "2026-05-05", "hour": 2}, {"date": "2026-05-05", "hour": 3}, {"date": "2026-05-06", "hour": 1}]
        Output: "2026-05-05:2,3|2026-05-06:1"
        """
        if not slots:
            return ""
        grouped: dict[str, list[int]] = {}
        for s in slots:
            grouped.setdefault(s["date"], []).append(s["hour"])
        parts = []
        for date_str in sorted(grouped):
            hours = ",".join(str(h) for h in sorted(grouped[date_str]))
            parts.append(f"{date_str}:{hours}")
        return "|".join(parts)

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = ""
        else:
            if self._schedule_type in ("charge", "discharge"):
                slots = {
                    "charge": data.charge_hours,
                    "discharge": data.discharge_hours,
                }.get(self._schedule_type, [])
                self._attr_native_value = self._format_slots(slots)
            else:
                hours = {
                    "blocked_charging": data.blocked_charging_hours,
                    "blocked_discharging": data.blocked_discharging_hours,
                }.get(self._schedule_type, [])
                self._attr_native_value = ",".join(str(h) for h in hours)
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data is None:
            return ""
        if self._schedule_type in ("charge", "discharge"):
            slots = {
                "charge": data.charge_hours,
                "discharge": data.discharge_hours,
            }.get(self._schedule_type, [])
            return self._format_slots(slots)
        hours = {
            "blocked_charging": data.blocked_charging_hours,
            "blocked_discharging": data.blocked_discharging_hours,
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
        """Build hour-by-hour plan from coordinator data (today + tomorrow)."""
        now = dt_util.now()
        today_str = now.strftime("%Y-%m-%d")
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        # Build lookup sets for charge/discharge slots
        charge_set = {(s["date"], s["hour"]) for s in data.charge_hours}
        discharge_set = {(s["date"], s["hour"]) for s in data.discharge_hours}

        # Price maps per day
        price_map_today = {p["hour"]: p["price"] for p in data.prices_today}
        price_map_tomorrow = {p["hour"]: p["price"] for p in data.prices_tomorrow}

        plan = []
        for day_str, price_map in [(today_str, price_map_today), (tomorrow_str, price_map_tomorrow)]:
            for hour in range(24):
                if hour in data.blocked_charging_hours and hour in data.blocked_discharging_hours:
                    action = "blocked"
                elif hour in data.blocked_charging_hours:
                    action = "blocked_charging"
                elif hour in data.blocked_discharging_hours:
                    action = "blocked_discharging"
                elif (day_str, hour) in charge_set:
                    action = "charge"
                elif (day_str, hour) in discharge_set:
                    action = "discharge"
                else:
                    action = "idle"
                entry = {"date": day_str, "hour": hour, "action": action}
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
                "blocked_charging_hours": data.blocked_charging_hours,
                "blocked_discharging_hours": data.blocked_discharging_hours,
            }
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data is None:
            return "unknown"
        return f"{len(data.charge_hours)} charge, {len(data.discharge_hours)} discharge"


class LastScheduleUpdateSensor(VictronCCBaseSensor):
    """Sensor showing the timestamp of the last schedule update."""

    _attr_translation_key = "last_schedule_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_schedule_update"

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = None
        else:
            self._attr_native_value = data.last_schedule_update
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        return data.last_schedule_update if data else None


class GridFeedInStatusSensor(VictronCCBaseSensor):
    """Sensor showing whether grid feed-in is in default or reduced mode."""

    _attr_translation_key = "grid_feed_in_status"
    _attr_icon = "mdi:transmission-tower"

    def __init__(
        self,
        coordinator: VictronChargeControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_grid_feed_in_status"

    @callback
    def _handle_coordinator_update(self) -> None:
        data: ChargeControlData | None = self.coordinator.data
        if data is None:
            self._attr_native_value = "default"
        else:
            self._attr_native_value = "reduced" if data.grid_feed_in_active else "default"
        self._attr_extra_state_attributes = {
            "applied_max_grid_feed_in": data.applied_max_grid_feed_in if data else None,
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data is None:
            return "default"
        return "reduced" if data.grid_feed_in_active else "default"
