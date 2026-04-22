"""Data update coordinator for Victron Charge Control.

Runs the decision engine every 60 seconds and whenever relevant entities change.
Manages the schedule (charge/discharge hours) and computes the target setpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    DEFAULT_CHARGE_POWER,
    DEFAULT_CHARGE_PRICE_THRESHOLD,
    DEFAULT_CHEAPEST_HOURS,
    DEFAULT_DEADBAND,
    DEFAULT_DISCHARGE_POWER,
    DEFAULT_DISCHARGE_PRICE_THRESHOLD,
    DEFAULT_EXPENSIVE_HOURS,
    DEFAULT_IDLE_SETPOINT,
    DEFAULT_MAX_GRID_SETPOINT,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_GRID_SETPOINT,
    DEFAULT_MIN_SOC,
    DOMAIN,
    EPEX_ATTR_DATA,
    EPEX_KEY_PRICE,
    EPEX_KEY_PRICE_EUR,
    EPEX_KEY_START_TIME,
    MODE_AUTO,
    MODE_FORCE_CHARGE,
    MODE_FORCE_DISCHARGE,
    MODE_MANUAL,
    MODE_OFF,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ChargeControlData:
    """Snapshot of all computed state, exposed to sensor entities."""

    desired_action: str = ACTION_IDLE
    target_setpoint: float = 0.0
    charge_hours: list[int] = field(default_factory=list)
    discharge_hours: list[int] = field(default_factory=list)
    current_price: float | None = None
    prices_today: list[dict[str, Any]] = field(default_factory=list)


class VictronChargeControlCoordinator(DataUpdateCoordinator[ChargeControlData]):
    """Central coordinator that runs the decision engine."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # driven by events, not polling
        )
        self.config_entry = entry

        # --- Entity references from config ---
        self._battery_soc_entity: str = entry.data[CONF_BATTERY_SOC_ENTITY]
        self._grid_setpoint_entity: str = entry.data[CONF_GRID_SETPOINT_ENTITY]
        self._grid_power_entity: str = entry.data[CONF_GRID_POWER_ENTITY]
        self._battery_power_entity: str = entry.data[CONF_BATTERY_POWER_ENTITY]
        self._epex_spot_entity: str = entry.data[CONF_EPEX_SPOT_ENTITY]

        # --- Configurable parameters (modified by number/select/switch entities) ---
        self.control_mode: str = MODE_OFF
        self.charge_allowed: bool = True
        self.discharge_allowed: bool = True
        self.min_soc: float = DEFAULT_MIN_SOC
        self.max_soc: float = DEFAULT_MAX_SOC
        self.charge_power: float = DEFAULT_CHARGE_POWER
        self.discharge_power: float = DEFAULT_DISCHARGE_POWER
        self.idle_setpoint: float = DEFAULT_IDLE_SETPOINT
        self.min_grid_setpoint: float = DEFAULT_MIN_GRID_SETPOINT
        self.max_grid_setpoint: float = DEFAULT_MAX_GRID_SETPOINT
        self.cheapest_hours: int = DEFAULT_CHEAPEST_HOURS
        self.expensive_hours: int = DEFAULT_EXPENSIVE_HOURS
        self.charge_price_threshold: float = DEFAULT_CHARGE_PRICE_THRESHOLD
        self.discharge_price_threshold: float = DEFAULT_DISCHARGE_PRICE_THRESHOLD

        # --- Schedule state ---
        self._charge_hours: list[int] = []
        self._discharge_hours: list[int] = []

        # --- Listener removal callbacks ---
        self._unsub_listeners: list[Any] = []

        # --- Last applied setpoint (for deadband) ---
        self._last_applied_setpoint: float | None = None

    # ------------------------------------------------------------------
    # Properties for entity access
    # ------------------------------------------------------------------

    @property
    def battery_soc_entity(self) -> str:
        return self._battery_soc_entity

    @property
    def grid_setpoint_entity(self) -> str:
        return self._grid_setpoint_entity

    @property
    def grid_power_entity(self) -> str:
        return self._grid_power_entity

    @property
    def battery_power_entity(self) -> str:
        return self._battery_power_entity

    @property
    def epex_spot_entity(self) -> str:
        return self._epex_spot_entity

    def update_entity_references(self, data: dict[str, str]) -> None:
        """Update entity references from config entry data."""
        self._battery_soc_entity = data[CONF_BATTERY_SOC_ENTITY]
        self._grid_setpoint_entity = data[CONF_GRID_SETPOINT_ENTITY]
        self._grid_power_entity = data[CONF_GRID_POWER_ENTITY]
        self._battery_power_entity = data[CONF_BATTERY_POWER_ENTITY]
        self._epex_spot_entity = data[CONF_EPEX_SPOT_ENTITY]

    @property
    def charge_hours(self) -> list[int]:
        return list(self._charge_hours)

    @property
    def discharge_hours(self) -> list[int]:
        return list(self._discharge_hours)

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    def set_charge_hours(self, hours: list[int]) -> None:
        """Set charge hours and trigger update."""
        self._charge_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self.hass.async_create_task(self.async_request_refresh())

    def set_discharge_hours(self, hours: list[int]) -> None:
        """Set discharge hours and trigger update."""
        self._discharge_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self.hass.async_create_task(self.async_request_refresh())

    def toggle_hour(self, hour: int) -> None:
        """Cycle an hour: idle → charge → discharge → idle."""
        if hour < 0 or hour > 23:
            return
        if hour in self._charge_hours:
            # charge → discharge
            self._charge_hours = [h for h in self._charge_hours if h != hour]
            if hour not in self._discharge_hours:
                self._discharge_hours = sorted(self._discharge_hours + [hour])
        elif hour in self._discharge_hours:
            # discharge → idle
            self._discharge_hours = [h for h in self._discharge_hours if h != hour]
        else:
            # idle → charge
            self._charge_hours = sorted(self._charge_hours + [hour])
        self.hass.async_create_task(self.async_request_refresh())

    def set_hour_action(self, hour: int, action: str) -> None:
        """Set a specific hour to charge, discharge, or idle."""
        if hour < 0 or hour > 23:
            return
        # Remove from both lists
        self._charge_hours = [h for h in self._charge_hours if h != hour]
        self._discharge_hours = [h for h in self._discharge_hours if h != hour]
        # Add to correct list
        if action == ACTION_CHARGE:
            self._charge_hours = sorted(self._charge_hours + [hour])
        elif action == ACTION_DISCHARGE:
            self._discharge_hours = sorted(self._discharge_hours + [hour])
        self.hass.async_create_task(self.async_request_refresh())

    def clear_schedule(self) -> None:
        """Clear all scheduled hours."""
        self._charge_hours = []
        self._discharge_hours = []
        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # EPEX data extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_epex_data(attributes: dict[str, Any]) -> list[dict[str, Any]]:
        """Find the list of price entries from EPEX entity attributes.

        Supports mampfes/ha-epex-spot ('data' attribute) and other integrations
        that store entries under alternative attribute names.
        """
        # Try the known attribute name first
        data = attributes.get(EPEX_ATTR_DATA)
        if isinstance(data, list) and data:
            return data
        # Fallback: search for any list attribute containing price-like dicts
        for attr_name, attr_value in attributes.items():
            if not isinstance(attr_value, list) or not attr_value:
                continue
            first = attr_value[0]
            if isinstance(first, dict) and (
                EPEX_KEY_START_TIME in first
                or EPEX_KEY_PRICE in first
                or EPEX_KEY_PRICE_EUR in first
            ):
                return attr_value
        return []

    @staticmethod
    def _extract_price_ct(item: dict[str, Any]) -> float | None:
        """Extract price in ct/kWh from a single EPEX entry.

        Handles both 'price_ct_per_kwh' (cents) and 'price_per_kwh' (EUR).
        """
        price = item.get(EPEX_KEY_PRICE)
        if price is not None:
            try:
                return float(price)
            except (ValueError, TypeError):
                return None
        price_eur = item.get(EPEX_KEY_PRICE_EUR)
        if price_eur is not None:
            try:
                return float(price_eur) * 100.0  # EUR → ct
            except (ValueError, TypeError):
                return None
        return None

    # ------------------------------------------------------------------
    # Auto schedule calculation from EPEX prices
    # ------------------------------------------------------------------

    def calculate_auto_schedule(self) -> None:
        """Calculate optimal charge/discharge hours from EPEX spot prices."""
        if self.control_mode != MODE_AUTO:
            return

        epex_state = self.hass.states.get(self._epex_spot_entity)
        if epex_state is None:
            _LOGGER.warning("EPEX entity %s not found", self._epex_spot_entity)
            return

        epex_data = self._find_epex_data(epex_state.attributes)
        if not epex_data:
            _LOGGER.warning("No EPEX price data available in %s", self._epex_spot_entity)
            return

        now = dt_util.now()
        today_str = now.strftime("%Y-%m-%d")
        current_hour = now.hour

        # Build price list for today's remaining hours
        prices: list[dict[str, Any]] = []
        for item in epex_data:
            start_time = item.get(EPEX_KEY_START_TIME)
            if start_time is None:
                continue
            if isinstance(start_time, str):
                try:
                    sdt = dt_util.parse_datetime(start_time)
                    if sdt is not None:
                        sdt = dt_util.as_local(sdt)
                except (ValueError, TypeError):
                    continue
            elif isinstance(start_time, datetime):
                sdt = dt_util.as_local(start_time)
            else:
                continue

            if sdt is None:
                continue

            if sdt.strftime("%Y-%m-%d") == today_str and sdt.hour >= current_hour:
                price = self._extract_price_ct(item)
                if price is not None:
                    try:
                        prices.append({"hour": sdt.hour, "price": price})
                    except (ValueError, TypeError):
                        continue

        if not prices:
            _LOGGER.info("No remaining hours with price data for today")
            return

        # Sort ascending by price
        prices.sort(key=lambda x: x["price"])

        # Pick cheapest N hours below charge threshold
        charge_hours: list[int] = []
        for item in prices:
            if len(charge_hours) >= self.cheapest_hours:
                break
            if item["price"] <= self.charge_price_threshold:
                charge_hours.append(item["hour"])

        # Pick most expensive N hours above discharge threshold
        discharge_hours: list[int] = []
        for item in reversed(prices):
            if len(discharge_hours) >= self.expensive_hours:
                break
            if item["price"] >= self.discharge_price_threshold:
                discharge_hours.append(item["hour"])

        # Resolve conflicts: discharge wins (remove from charge)
        charge_hours = [h for h in charge_hours if h not in discharge_hours]

        self._charge_hours = sorted(charge_hours)
        self._discharge_hours = sorted(discharge_hours)

        _LOGGER.info(
            "Auto schedule calculated — Charge: %s, Discharge: %s (%d hours evaluated)",
            self._charge_hours,
            self._discharge_hours,
            len(prices),
        )

    # ------------------------------------------------------------------
    # Decision engine
    # ------------------------------------------------------------------

    def _get_battery_soc(self) -> float | None:
        """Get current battery SOC, or None if unavailable."""
        state = self.hass.states.get(self._battery_soc_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _determine_action(self) -> str:
        """Deterministic priority stack — returns charge/discharge/idle."""
        # Priority 1: System off
        if self.control_mode == MODE_OFF:
            return ACTION_IDLE

        # Priority 2: SOC unavailable
        soc = self._get_battery_soc()
        if soc is None:
            _LOGGER.debug("Battery SOC unavailable — falling back to idle")
            return ACTION_IDLE

        # Priority 3: Force modes
        if self.control_mode == MODE_FORCE_CHARGE:
            if self.charge_allowed and soc < self.max_soc:
                return ACTION_CHARGE
            return ACTION_IDLE

        if self.control_mode == MODE_FORCE_DISCHARGE:
            if self.discharge_allowed and soc > self.min_soc:
                return ACTION_DISCHARGE
            return ACTION_IDLE

        # Priority 4: Auto or Manual — look up schedule
        if self.control_mode in (MODE_AUTO, MODE_MANUAL):
            hour = dt_util.now().hour
            if hour in self._charge_hours and self.charge_allowed and soc < self.max_soc:
                return ACTION_CHARGE
            if hour in self._discharge_hours and self.discharge_allowed and soc > self.min_soc:
                return ACTION_DISCHARGE
            return ACTION_IDLE

        # Priority 5: Fallback
        return ACTION_IDLE

    def _compute_setpoint(self, action: str) -> float:
        """Compute the clamped grid setpoint for the given action."""
        if action == ACTION_CHARGE:
            raw = self.charge_power  # positive = import
        elif action == ACTION_DISCHARGE:
            raw = -self.discharge_power  # negative = export
        else:
            raw = self.idle_setpoint

        return max(self.min_grid_setpoint, min(raw, self.max_grid_setpoint))

    # ------------------------------------------------------------------
    # Setpoint application
    # ------------------------------------------------------------------

    async def _apply_setpoint(self, target_setpoint: float) -> None:
        """Write the target setpoint to the Victron grid setpoint entity."""
        # Check entity availability
        state = self.hass.states.get(self._grid_setpoint_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            _LOGGER.warning(
                "Grid setpoint entity %s is unavailable — skipping actuation",
                self._grid_setpoint_entity,
            )
            return

        # Deadband: skip if difference is too small
        try:
            current = float(state.state)
        except (ValueError, TypeError):
            current = 0.0

        if (
            self._last_applied_setpoint is not None
            and abs(target_setpoint - current) <= DEFAULT_DEADBAND
        ):
            return

        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": self._grid_setpoint_entity, "value": target_setpoint},
            blocking=True,
        )
        self._last_applied_setpoint = target_setpoint
        _LOGGER.info(
            "Setpoint: %.0fW → %.0fW (action=%s, mode=%s, SOC=%s)",
            current,
            target_setpoint,
            self.data.desired_action if self.data else "?",
            self.control_mode,
            self._get_battery_soc(),
        )

    # ------------------------------------------------------------------
    # Safety watchdog
    # ------------------------------------------------------------------

    def _check_safety(self) -> bool:
        """Check critical entities. Returns True if safe, False to trigger shutdown."""
        for entity_id in (self._battery_soc_entity, self._grid_setpoint_entity):
            state = self.hass.states.get(entity_id)
            if state is not None and state.state in ("unavailable", "unknown"):
                return False
        return True

    # ------------------------------------------------------------------
    # Core update method
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> ChargeControlData:
        """Run the decision engine and apply the setpoint."""
        # Safety check
        if self.control_mode != MODE_OFF and not self._check_safety():
            _LOGGER.warning(
                "Safety watchdog: critical entity unavailable — switching to OFF"
            )
            self.control_mode = MODE_OFF
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Victron Charge Control — Safety Stop",
                    "message": "A critical Victron entity became unavailable. System switched to OFF.",
                    "notification_id": "victron_cc_safety_stop",
                },
                blocking=False,
            )

        # Decision engine
        action = self._determine_action()
        setpoint = self._compute_setpoint(action)

        # Apply setpoint (only when not OFF)
        if self.control_mode != MODE_OFF:
            await self._apply_setpoint(setpoint)
        elif self._last_applied_setpoint != self.idle_setpoint:
            # When turning off, reset to idle
            await self._apply_setpoint(self.idle_setpoint)

        # Current price
        epex_state = self.hass.states.get(self._epex_spot_entity)
        current_price = None
        prices_today: list[dict[str, Any]] = []
        if epex_state is not None and epex_state.state not in (
            "unavailable",
            "unknown",
        ):
            try:
                current_price = float(epex_state.state)
            except (ValueError, TypeError):
                pass
            raw_data = self._find_epex_data(epex_state.attributes)
            if raw_data:
                now = dt_util.now()
                today_str = now.strftime("%Y-%m-%d")
                for item in raw_data:
                    st = item.get(EPEX_KEY_START_TIME)
                    if st is None:
                        continue
                    if isinstance(st, str):
                        try:
                            sdt = dt_util.parse_datetime(st)
                            if sdt is not None:
                                sdt = dt_util.as_local(sdt)
                        except (ValueError, TypeError):
                            continue
                    elif isinstance(st, datetime):
                        sdt = dt_util.as_local(st)
                    else:
                        continue
                    if sdt is not None and sdt.strftime("%Y-%m-%d") == today_str:
                        price = self._extract_price_ct(item)
                        if price is not None:
                            prices_today.append(
                                {"hour": sdt.hour, "price": price}
                            )
                prices_today.sort(key=lambda x: x["hour"])

        return ChargeControlData(
            desired_action=action,
            target_setpoint=setpoint,
            charge_hours=list(self._charge_hours),
            discharge_hours=list(self._discharge_hours),
            current_price=current_price,
            prices_today=prices_today,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Set up event listeners for state changes and time triggers."""
        # Track changes to the Victron entities we read
        entities_to_watch = [
            self._battery_soc_entity,
            self._grid_setpoint_entity,
            self._epex_spot_entity,
        ]

        @callback
        def _state_changed(event: Any) -> None:
            """Handle state changes of tracked entities."""
            entity_id = event.data.get("entity_id", "")
            # If EPEX price data attribute changed and we're in auto mode, recalculate
            if entity_id == self._epex_spot_entity and self.control_mode == MODE_AUTO:
                self.calculate_auto_schedule()
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, entities_to_watch, _state_changed
            )
        )

        # Every minute, re-evaluate (catches hour boundaries)
        @callback
        def _minute_tick(_now: datetime) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_listeners.append(
            async_track_time_change(self.hass, _minute_tick, second=0)
        )

        # At 00:05 — daily schedule recalculation for auto mode
        @callback
        def _daily_recalc(_now: datetime) -> None:
            if self.control_mode == MODE_AUTO:
                self.calculate_auto_schedule()
            elif self.control_mode == MODE_MANUAL:
                self._charge_hours = []
                self._discharge_hours = []
                _LOGGER.info("Daily schedule reset (manual mode)")
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_listeners.append(
            async_track_time_change(self.hass, _daily_recalc, hour=0, minute=5, second=0)
        )

        # At 14:05 — recalculate for tomorrow prices
        @callback
        def _afternoon_recalc(_now: datetime) -> None:
            if self.control_mode == MODE_AUTO:
                self.calculate_auto_schedule()
                self.hass.async_create_task(self.async_request_refresh())

        self._unsub_listeners.append(
            async_track_time_change(
                self.hass, _afternoon_recalc, hour=14, minute=5, second=0
            )
        )

        # Initial data
        self.data = ChargeControlData()
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Remove all listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
