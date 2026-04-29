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
    ACTION_BLOCKED,
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    DEFAULT_CHARGE_POWER,
    DEFAULT_CHARGE_PRICE_THRESHOLD,
    DEFAULT_CHEAPEST_HOURS,
    DEFAULT_DEADBAND,
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
    blocked_charging_hours: list[int] = field(default_factory=list)
    blocked_discharging_hours: list[int] = field(default_factory=list)
    current_price: float | None = None
    prices_today: list[dict[str, Any]] = field(default_factory=list)
    grid_feed_in_active: bool = False
    applied_max_grid_feed_in: float | None = None
    last_schedule_update: datetime | None = None


class VictronChargeControlCoordinator(DataUpdateCoordinator[ChargeControlData]):
    """Central coordinator that runs the decision engine."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,  # driven by events, not polling
        )

        # --- Entity references from config ---
        self._battery_soc_entity: str = entry.data[CONF_BATTERY_SOC_ENTITY]
        self._grid_setpoint_entity: str = entry.data[CONF_GRID_SETPOINT_ENTITY]
        self._epex_spot_entity: str = entry.data[CONF_EPEX_SPOT_ENTITY]
        self._max_grid_feed_in_entity: str = entry.data[CONF_MAX_GRID_FEED_IN_ENTITY]

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

        # --- Grid feed-in control ---
        self.grid_feed_in_control_enabled: bool = False
        self.grid_feed_in_price_threshold: float = DEFAULT_GRID_FEED_IN_PRICE_THRESHOLD
        self.default_max_grid_feed_in: float = DEFAULT_MAX_GRID_FEED_IN
        self.reduced_max_grid_feed_in: float = DEFAULT_REDUCED_GRID_FEED_IN
        self._last_applied_feed_in: float | None = None

        # --- Schedule state ---
        self._charge_hours: list[int] = []
        self._discharge_hours: list[int] = []
        self._blocked_charging_hours: list[int] = []
        self._blocked_discharging_hours: list[int] = []

        # --- Listener removal callbacks ---
        self._unsub_listeners: list[Any] = []

        # --- Last applied setpoint (for deadband) ---
        self._last_applied_setpoint: float | None = None

        # --- Last schedule update timestamp ---
        self._last_schedule_update: datetime | None = None

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
    def epex_spot_entity(self) -> str:
        return self._epex_spot_entity

    @property
    def max_grid_feed_in_entity(self) -> str:
        return self._max_grid_feed_in_entity

    def update_entity_references(self, data: dict[str, str]) -> None:
        """Update entity references from config entry data."""
        self._battery_soc_entity = data[CONF_BATTERY_SOC_ENTITY]
        self._grid_setpoint_entity = data[CONF_GRID_SETPOINT_ENTITY]
        self._epex_spot_entity = data[CONF_EPEX_SPOT_ENTITY]
        self._max_grid_feed_in_entity = data[CONF_MAX_GRID_FEED_IN_ENTITY]

    @property
    def charge_hours(self) -> list[int]:
        return list(self._charge_hours)

    @property
    def discharge_hours(self) -> list[int]:
        return list(self._discharge_hours)

    @property
    def blocked_charging_hours(self) -> list[int]:
        return list(self._blocked_charging_hours)

    @property
    def blocked_discharging_hours(self) -> list[int]:
        return list(self._blocked_discharging_hours)

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    def set_charge_hours(self, hours: list[int]) -> None:
        """Set charge hours and trigger update."""
        self._charge_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_discharge_hours(self, hours: list[int]) -> None:
        """Set discharge hours and trigger update."""
        self._discharge_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_blocked_charging_hours(self, hours: list[int]) -> None:
        """Set blocked charging hours and trigger update."""
        self._blocked_charging_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_blocked_discharging_hours(self, hours: list[int]) -> None:
        """Set blocked discharging hours and trigger update."""
        self._blocked_discharging_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def toggle_hour(self, hour: int) -> None:
        """Cycle an hour: idle → charge → discharge → blocked → idle.

        'blocked' in this cycle means blocked for both charging and discharging.
        """
        if hour < 0 or hour > 23:
            return
        if hour in self._charge_hours:
            # charge → discharge
            self._charge_hours = [h for h in self._charge_hours if h != hour]
            if hour not in self._discharge_hours:
                self._discharge_hours = sorted(self._discharge_hours + [hour])
        elif hour in self._discharge_hours:
            # discharge → blocked (both)
            self._discharge_hours = [h for h in self._discharge_hours if h != hour]
            if hour not in self._blocked_charging_hours:
                self._blocked_charging_hours = sorted(self._blocked_charging_hours + [hour])
            if hour not in self._blocked_discharging_hours:
                self._blocked_discharging_hours = sorted(self._blocked_discharging_hours + [hour])
        elif hour in self._blocked_charging_hours or hour in self._blocked_discharging_hours:
            # blocked → idle
            self._blocked_charging_hours = [h for h in self._blocked_charging_hours if h != hour]
            self._blocked_discharging_hours = [h for h in self._blocked_discharging_hours if h != hour]
        else:
            # idle → charge
            self._charge_hours = sorted(self._charge_hours + [hour])
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_hour_action(self, hour: int, action: str) -> None:
        """Set a specific hour to charge, discharge, blocked, or idle."""
        if hour < 0 or hour > 23:
            return
        # Remove from all lists
        self._charge_hours = [h for h in self._charge_hours if h != hour]
        self._discharge_hours = [h for h in self._discharge_hours if h != hour]
        self._blocked_charging_hours = [h for h in self._blocked_charging_hours if h != hour]
        self._blocked_discharging_hours = [h for h in self._blocked_discharging_hours if h != hour]
        # Add to correct list
        if action == ACTION_CHARGE:
            self._charge_hours = sorted(self._charge_hours + [hour])
        elif action == ACTION_DISCHARGE:
            self._discharge_hours = sorted(self._discharge_hours + [hour])
        elif action == ACTION_BLOCKED:
            self._blocked_charging_hours = sorted(self._blocked_charging_hours + [hour])
            self._blocked_discharging_hours = sorted(self._blocked_discharging_hours + [hour])
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def clear_schedule(self) -> None:
        """Clear all scheduled hours."""
        self._charge_hours = []
        self._discharge_hours = []
        self._blocked_charging_hours = []
        self._blocked_discharging_hours = []
        self._last_schedule_update = dt_util.now()
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

        # Build price list for all future hours (today's remaining + tomorrow)
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

            # Include any hour that hasn't ended yet
            if sdt >= now.replace(minute=0, second=0, microsecond=0):
                price = self._extract_price_ct(item)
                if price is not None:
                    prices.append({"hour": sdt.hour, "price": price})

        if not prices:
            _LOGGER.info("No future hours with price data available")
            return

        # When multiple days have the same hour, keep the one closest to now
        # (deduplicate by hour, preferring the earliest future occurrence)
        seen_hours: dict[int, float] = {}
        for item in prices:
            h = item["hour"]
            if h not in seen_hours:
                seen_hours[h] = item["price"]
        deduped = [{"hour": h, "price": p} for h, p in seen_hours.items()]

        # Sort ascending by price
        deduped.sort(key=lambda x: x["price"])

        # Pick cheapest N hours below charge threshold (skip blocked charging hours)
        charge_hours: list[int] = []
        for item in deduped:
            if len(charge_hours) >= self.cheapest_hours:
                break
            if item["hour"] not in self._blocked_charging_hours and item["price"] <= self.charge_price_threshold:
                charge_hours.append(item["hour"])

        # Pick most expensive N hours above discharge threshold (skip blocked discharging hours)
        discharge_hours: list[int] = []
        for item in reversed(deduped):
            if len(discharge_hours) >= self.expensive_hours:
                break
            if item["hour"] not in self._blocked_discharging_hours and item["price"] >= self.discharge_price_threshold:
                discharge_hours.append(item["hour"])

        # Resolve conflicts: discharge wins (remove from charge)
        charge_hours = [h for h in charge_hours if h not in discharge_hours]

        self._charge_hours = sorted(charge_hours)
        self._discharge_hours = sorted(discharge_hours)
        self._last_schedule_update = dt_util.now()

        _LOGGER.info(
            "Auto schedule calculated — Charge: %s, Discharge: %s (%d hours evaluated)",
            self._charge_hours,
            self._discharge_hours,
            len(deduped),
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

        # Priority 4: Blocked hours — override schedule per action type
        if self.control_mode in (MODE_AUTO, MODE_MANUAL):
            hour = dt_util.now().hour

            # Priority 5: Auto or Manual — look up schedule
            if hour in self._charge_hours and self.charge_allowed and soc < self.max_soc:
                if hour not in self._blocked_charging_hours:
                    return ACTION_CHARGE
            if hour in self._discharge_hours and self.discharge_allowed and soc > self.min_soc:
                if hour not in self._blocked_discharging_hours:
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
    # Grid feed-in control
    # ------------------------------------------------------------------

    async def _apply_grid_feed_in(self, current_price: float | None) -> tuple[bool, float | None]:
        """Control max grid feed-in based on spot price.

        Returns (is_reduced, applied_value).
        """
        if not self.grid_feed_in_control_enabled:
            # Reset to default when feature is disabled
            if self._last_applied_feed_in is not None and self._last_applied_feed_in != self.default_max_grid_feed_in:
                state = self.hass.states.get(self._max_grid_feed_in_entity)
                if state is not None and state.state not in ("unavailable", "unknown"):
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {"entity_id": self._max_grid_feed_in_entity, "value": self.default_max_grid_feed_in},
                        blocking=True,
                    )
                    _LOGGER.info(
                        "Grid feed-in control disabled — reset to default %.0fW",
                        self.default_max_grid_feed_in,
                    )
                self._last_applied_feed_in = None
            return False, None

        if current_price is None:
            _LOGGER.debug("No current price available — skipping grid feed-in control")
            return False, None

        # Determine target feed-in value
        if current_price < self.grid_feed_in_price_threshold:
            target_feed_in = self.reduced_max_grid_feed_in
            is_reduced = True
        else:
            target_feed_in = self.default_max_grid_feed_in
            is_reduced = False

        # Check entity availability
        state = self.hass.states.get(self._max_grid_feed_in_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            _LOGGER.warning(
                "Max grid feed-in entity %s is unavailable — skipping",
                self._max_grid_feed_in_entity,
            )
            return is_reduced, None

        # Skip if value hasn't changed
        try:
            current_val = float(state.state)
        except (ValueError, TypeError):
            current_val = 0.0

        if (
            self._last_applied_feed_in is not None
            and abs(target_feed_in - current_val) <= DEFAULT_DEADBAND
        ):
            return is_reduced, target_feed_in

        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": self._max_grid_feed_in_entity, "value": target_feed_in},
            blocking=True,
        )
        self._last_applied_feed_in = target_feed_in
        _LOGGER.info(
            "Grid feed-in: %.0fW → %.0fW (price=%.2f ct/kWh, threshold=%.2f ct/kWh)",
            current_val,
            target_feed_in,
            current_price,
            self.grid_feed_in_price_threshold,
        )
        return is_reduced, target_feed_in

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

        # Grid feed-in control
        feed_in_active, applied_feed_in = await self._apply_grid_feed_in(current_price)

        return ChargeControlData(
            desired_action=action,
            target_setpoint=setpoint,
            charge_hours=list(self._charge_hours),
            discharge_hours=list(self._discharge_hours),
            blocked_charging_hours=list(self._blocked_charging_hours),
            blocked_discharging_hours=list(self._blocked_discharging_hours),
            current_price=current_price,
            prices_today=prices_today,
            grid_feed_in_active=feed_in_active,
            applied_max_grid_feed_in=applied_feed_in,
            last_schedule_update=self._last_schedule_update,
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

        # At 14:30 — recalculate for tomorrow prices
        @callback
        def _afternoon_recalc(_now: datetime) -> None:
            if self.control_mode == MODE_AUTO:
                self.calculate_auto_schedule()
                self.hass.async_create_task(self.async_request_refresh())

        self._unsub_listeners.append(
            async_track_time_change(
                self.hass, _afternoon_recalc, hour=14, minute=30, second=0
            )
        )

        # Initial data
        self.data = ChargeControlData()

        # Initial schedule calculation if already in auto mode (e.g. after restart)
        if self.control_mode == MODE_AUTO:
            self.calculate_auto_schedule()

        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Remove all listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
