"""Data update coordinator for Victron Charge Control.

Runs the decision engine every 60 seconds and whenever relevant entities change.
Manages the schedule (charge/discharge hours) and computes the target setpoint.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    ACTION_PV_CHARGE,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_CONSUMPTION_ENTITY,
    CONF_GRID_FEED_IN_ENERGY_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    CONF_SOLAR_SURPLUS_ENTITY,
    DEFAULT_ACTION_CONFIRM_SECONDS,
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
    DEFAULT_PV_CHARGE_SHARE,
    DEFAULT_REDUCED_GRID_FEED_IN,
    DEFAULT_REPLAN_HOURS,
    DEFAULT_SOC_HYSTERESIS,
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

# Type alias for a date-qualified schedule slot: (ISO date "YYYY-MM-DD", hour 0-23)
ScheduleSlot = tuple[str, int]


@dataclass
class ChargeControlData:
    """Snapshot of all computed state, exposed to sensor entities."""

    desired_action: str = ACTION_IDLE
    target_setpoint: float = 0.0
    charge_hours: list[dict[str, Any]] = field(default_factory=list)
    discharge_hours: list[dict[str, Any]] = field(default_factory=list)
    pv_charge_hours: list[dict[str, Any]] = field(default_factory=list)
    blocked_charging_hours: list[int] = field(default_factory=list)
    blocked_discharging_hours: list[int] = field(default_factory=list)
    current_price: float | None = None
    epex_attributes: dict[str, Any] = field(default_factory=dict)
    prices_today: list[dict[str, Any]] = field(default_factory=list)
    prices_tomorrow: list[dict[str, Any]] = field(default_factory=list)
    grid_feed_in_active: bool = False
    applied_max_grid_feed_in: float | None = None
    grid_energy_cost: float | None = None
    grid_energy_revenue: float | None = None
    grid_energy_import: float | None = None
    grid_energy_export: float | None = None
    current_price_eur_per_kwh: float | None = None
    last_schedule_update: datetime | None = None
    last_cost_update: datetime | None = None
    solar_surplus_mean: float | None = None
    solar_surplus_window_samples: int = 0
    discharge_solar_only: bool = False


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
        self._grid_consumption_entity: str | None = entry.data.get(
            CONF_GRID_CONSUMPTION_ENTITY
        ) or None
        self._grid_feed_in_energy_entity: str | None = entry.data.get(
            CONF_GRID_FEED_IN_ENERGY_ENTITY
        ) or None
        self._solar_surplus_entity: str | None = (
            entry.data.get(CONF_SOLAR_SURPLUS_ENTITY) or None
        )

        # --- Configurable parameters (modified by number/select/switch entities) ---
        self.control_mode: str = MODE_OFF
        self.charge_allowed: bool = True
        self.discharge_allowed: bool = True
        self.min_soc: float = DEFAULT_MIN_SOC
        self.max_soc: float = DEFAULT_MAX_SOC
        self.soc_hysteresis: float = DEFAULT_SOC_HYSTERESIS
        self._charge_blocked_by_soc: bool = False
        self._discharge_blocked_by_soc: bool = False
        self.charge_power: float = DEFAULT_CHARGE_POWER
        self.discharge_power: float = DEFAULT_DISCHARGE_POWER
        self.idle_setpoint: float = DEFAULT_IDLE_SETPOINT
        self.min_grid_setpoint: float = DEFAULT_MIN_GRID_SETPOINT
        self.max_grid_setpoint: float = DEFAULT_MAX_GRID_SETPOINT
        self.cheapest_hours: int = DEFAULT_CHEAPEST_HOURS
        self.expensive_hours: int = DEFAULT_EXPENSIVE_HOURS
        self.charge_price_threshold: float = DEFAULT_CHARGE_PRICE_THRESHOLD
        self.discharge_price_threshold: float = DEFAULT_DISCHARGE_PRICE_THRESHOLD
        self.setpoint_deadband: float = DEFAULT_DEADBAND
        self.pv_charge_share: float = DEFAULT_PV_CHARGE_SHARE

        # --- Grid feed-in control ---
        self.grid_feed_in_control_enabled: bool = False
        self.grid_feed_in_price_threshold: float = DEFAULT_GRID_FEED_IN_PRICE_THRESHOLD
        self.default_max_grid_feed_in: float = DEFAULT_MAX_GRID_FEED_IN
        self.reduced_max_grid_feed_in: float = DEFAULT_REDUCED_GRID_FEED_IN
        self._last_applied_feed_in: float | None = None

        # --- Cost tracking from cumulative kWh meters ---
        self._last_grid_consumption_kwh: float | None = None
        self._last_grid_feed_in_kwh: float | None = None
        self._grid_energy_cost: float = 0.0
        self._grid_energy_revenue: float = 0.0
        self._grid_energy_import: float = 0.0
        self._grid_energy_export: float = 0.0
        self._last_cost_update: datetime | None = None

        # --- Solar surplus tracking (optional) ---
        self._solar_samples: deque[tuple[datetime, float]] = deque(maxlen=64)
        self._solar_surplus_mean: float | None = None
        self._discharge_solar_only: bool = False

        # --- Schedule state ---
        # Charge/discharge are date-aware: list of (date_iso, hour) tuples
        self._charge_hours: list[ScheduleSlot] = []
        self._discharge_hours: list[ScheduleSlot] = []
        self._pv_charge_hours: list[ScheduleSlot] = []
        # Blocked hours are recurring (hour-of-day only)
        self._blocked_charging_hours: list[int] = []
        self._blocked_discharging_hours: list[int] = []
        # Replan hours are recurring (hour-of-day only)
        self._replan_hours: list[int] = list(DEFAULT_REPLAN_HOURS)
        self._replan_unsub: Any = None

        # --- Listener removal callbacks ---
        self._unsub_listeners: list[Any] = []

        # --- Last applied setpoint (for deadband) ---
        self._last_applied_setpoint: float | None = None

        # --- Last schedule update timestamp ---
        self._last_schedule_update: datetime | None = None

        # --- Action-change debounce ---
        # The decision engine is re-evaluated on every coordinator tick
        # (~60s) and on every relevant entity change. A single noisy SOC
        # reading can briefly flip _determine_action() to a different
        # value, which would otherwise cause the grid setpoint and the
        # dashboard's desired_action badge to flap in lock-step with the
        # sensor jitter. To absorb those transient flips, a new action
        # must persist for at least action_confirm_seconds before it is
        # published and applied; the previous action continues to be
        # reported in the meantime.
        # ``_last_published_action`` starts as None so the very first
        # decision is published immediately rather than being held back
        # for action_confirm_seconds.
        self.action_confirm_seconds: float = DEFAULT_ACTION_CONFIRM_SECONDS
        self._last_published_action: str | None = None
        self._pending_action: str | None = None
        self._pending_action_since: datetime | None = None

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

    @property
    def grid_consumption_entity(self) -> str | None:
        return self._grid_consumption_entity

    @property
    def grid_feed_in_energy_entity(self) -> str | None:
        return self._grid_feed_in_energy_entity

    @property
    def solar_surplus_entity(self) -> str | None:
        return self._solar_surplus_entity

    @property
    def grid_energy_cost(self) -> float | None:
        if (
            self._grid_consumption_entity is None
            and self._grid_feed_in_energy_entity is None
        ):
            return None
        return self._grid_energy_cost

    @property
    def grid_energy_revenue(self) -> float | None:
        if (
            self._grid_consumption_entity is None
            and self._grid_feed_in_energy_entity is None
        ):
            return None
        return self._grid_energy_revenue

    @property
    def grid_energy_import(self) -> float | None:
        if (
            self._grid_consumption_entity is None
            and self._grid_feed_in_energy_entity is None
        ):
            return None
        return self._grid_energy_import

    @property
    def grid_energy_export(self) -> float | None:
        if (
            self._grid_consumption_entity is None
            and self._grid_feed_in_energy_entity is None
        ):
            return None
        return self._grid_energy_export

    @property
    def last_grid_consumption_kwh(self) -> float | None:
        return self._last_grid_consumption_kwh

    @property
    def last_grid_feed_in_kwh(self) -> float | None:
        return self._last_grid_feed_in_kwh

    @property
    def last_cost_update(self) -> datetime | None:
        return self._last_cost_update

    @property
    def last_energy_update(self) -> datetime | None:
        return self._last_cost_update

    def update_entity_references(self, data: dict[str, Any]) -> None:
        """Update entity references from config entry data."""
        self._battery_soc_entity = data[CONF_BATTERY_SOC_ENTITY]
        self._grid_setpoint_entity = data[CONF_GRID_SETPOINT_ENTITY]
        self._epex_spot_entity = data[CONF_EPEX_SPOT_ENTITY]
        self._max_grid_feed_in_entity = data[CONF_MAX_GRID_FEED_IN_ENTITY]
        self._grid_consumption_entity = data.get(CONF_GRID_CONSUMPTION_ENTITY) or None
        self._grid_feed_in_energy_entity = (
            data.get(CONF_GRID_FEED_IN_ENERGY_ENTITY) or None
        )
        self._solar_surplus_entity = data.get(CONF_SOLAR_SURPLUS_ENTITY) or None

    def restore_cost_state(
        self,
        tracker: str,
        total: float | None,
        last_update: datetime | None = None,
        last_grid_consumption_kwh: float | None = None,
        last_grid_feed_in_kwh: float | None = None,
    ) -> None:
        """Restore persisted cumulative cost tracker state."""
        if tracker == "grid_cost":
            if total is not None:
                self._grid_energy_cost = total
        elif tracker == "grid_revenue":
            if total is not None:
                self._grid_energy_revenue = total

        if last_grid_consumption_kwh is not None:
            self._last_grid_consumption_kwh = last_grid_consumption_kwh

        if last_grid_feed_in_kwh is not None:
            self._last_grid_feed_in_kwh = last_grid_feed_in_kwh

        if last_update is not None and (
            self._last_cost_update is None or last_update > self._last_cost_update
        ):
            self._last_cost_update = last_update

    def restore_energy_state(
        self,
        tracker: str,
        total: float | None,
        last_update: datetime | None = None,
        last_grid_consumption_kwh: float | None = None,
        last_grid_feed_in_kwh: float | None = None,
    ) -> None:
        """Restore persisted cumulative energy (kWh) tracker state."""
        if tracker == "grid_import":
            if total is not None:
                self._grid_energy_import = total
        elif tracker == "grid_export":
            if total is not None:
                self._grid_energy_export = total

        if last_grid_consumption_kwh is not None:
            self._last_grid_consumption_kwh = last_grid_consumption_kwh

        if last_grid_feed_in_kwh is not None:
            self._last_grid_feed_in_kwh = last_grid_feed_in_kwh

        if last_update is not None and (
            self._last_cost_update is None or last_update > self._last_cost_update
        ):
            self._last_cost_update = last_update

    @property
    def charge_hours(self) -> list[ScheduleSlot]:
        return list(self._charge_hours)

    @property
    def discharge_hours(self) -> list[ScheduleSlot]:
        return list(self._discharge_hours)

    @property
    def pv_charge_hours(self) -> list[ScheduleSlot]:
        return list(self._pv_charge_hours)

    @property
    def blocked_charging_hours(self) -> list[int]:
        return list(self._blocked_charging_hours)

    @property
    def blocked_discharging_hours(self) -> list[int]:
        return list(self._blocked_discharging_hours)

    @property
    def replan_hours(self) -> list[int]:
        return list(self._replan_hours)

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    @staticmethod
    def _sort_slots(slots: list[ScheduleSlot]) -> list[ScheduleSlot]:
        """Sort schedule slots by (date, hour)."""
        return sorted(set(slots))

    @staticmethod
    def _valid_slot(date_str: str, hour: int) -> bool:
        """Validate a schedule slot."""
        if not (0 <= hour <= 23):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _today_str(self) -> str:
        """Get today's date as ISO string."""
        return dt_util.now().strftime("%Y-%m-%d")

    def _clean_expired_slots(self) -> None:
        """Remove schedule slots that are in the past."""
        now = dt_util.now()
        current_date = now.strftime("%Y-%m-%d")
        current_hour = now.hour

        def is_future(slot: ScheduleSlot) -> bool:
            d, h = slot
            if d > current_date:
                return True
            if d == current_date and h >= current_hour:
                return True
            return False

        self._charge_hours = [s for s in self._charge_hours if is_future(s)]
        self._discharge_hours = [s for s in self._discharge_hours if is_future(s)]
        self._pv_charge_hours = [s for s in self._pv_charge_hours if is_future(s)]

    def set_charge_hours(self, slots: list[ScheduleSlot]) -> None:
        """Set charge hours (date-aware) and trigger update."""
        self._charge_hours = self._sort_slots(
            [s for s in slots if self._valid_slot(s[0], s[1])]
        )
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_discharge_hours(self, slots: list[ScheduleSlot]) -> None:
        """Set discharge hours (date-aware) and trigger update."""
        self._discharge_hours = self._sort_slots(
            [s for s in slots if self._valid_slot(s[0], s[1])]
        )
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_blocked_charging_hours(self, hours: list[int]) -> None:
        """Set blocked charging hours (recurring daily) and trigger update."""
        self._blocked_charging_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_blocked_discharging_hours(self, hours: list[int]) -> None:
        """Set blocked discharging hours (recurring daily) and trigger update."""
        self._blocked_discharging_hours = sorted(set(h for h in hours if 0 <= h <= 23))
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_replan_hours(self, hours: list[int]) -> None:
        """Set replan hours (recurring daily) and (re)install the time listener.

        Empty list disables automatic replanning. Triggers a refresh so the
        text entity state stays in sync.
        """
        normalized = sorted(set(h for h in hours if 0 <= h <= 23))
        if normalized == self._replan_hours:
            return
        self._replan_hours = normalized
        self._install_replan_listener()
        if not normalized:
            _LOGGER.warning(
                "Replan hours set to empty — automatic replanning disabled. "
                "Use the 'calculate_schedule' service or the Recalculate button."
            )
        else:
            _LOGGER.info("Replan hours updated to %s", normalized)
        self.hass.async_create_task(self.async_request_refresh())

    def _install_replan_listener(self) -> None:
        """(Re)install the time-change listener for replan hours.

        Unsubscribes any previously installed listener and, if at least one
        replan hour is configured, registers a new one that fires at the
        top of each configured hour.
        """
        if self._replan_unsub is not None:
            self._replan_unsub()
            self._replan_unsub = None
        if not self._replan_hours:
            return

        self._replan_unsub = async_track_time_change(
            self.hass, self._run_replan,
            hour=tuple(self._replan_hours), minute=0, second=0,
        )

    def _run_replan(self, _now: datetime | None = None) -> None:
        """Run the daily replan: clean expired slots + recalc/reset.

        Mirrors the original 00:05 behavior — in auto mode the schedule is
        recomputed from EPEX prices, in manual mode the user-picked hours are
        cleared so the next day starts fresh.
        """
        self._clean_expired_slots()
        if self.control_mode == MODE_AUTO:
            self.calculate_auto_schedule()
        elif self.control_mode == MODE_MANUAL:
            self._charge_hours = []
            self._discharge_hours = []
            _LOGGER.info("Daily schedule reset (manual mode)")
        self.hass.async_create_task(self.async_request_refresh())

    def toggle_hour(self, hour: int, date_str: str | None = None) -> None:
        """Cycle an hour: idle → charge → pv_charge → discharge → blocked → idle.

        'blocked' in this cycle means blocked for both charging and discharging
        (recurring, hour-of-day only).

        Args:
            hour: Hour of day (0-23).
            date_str: ISO date string (YYYY-MM-DD). Defaults to today.
        """
        if hour < 0 or hour > 23:
            return
        if date_str is None:
            date_str = self._today_str()
        if not self._valid_slot(date_str, hour):
            return

        slot: ScheduleSlot = (date_str, hour)

        if slot in self._charge_hours:
            # charge → pv_charge
            self._charge_hours = [s for s in self._charge_hours if s != slot]
            if slot not in self._pv_charge_hours:
                self._pv_charge_hours = self._sort_slots(self._pv_charge_hours + [slot])
        elif slot in self._pv_charge_hours:
            # pv_charge → discharge
            self._pv_charge_hours = [s for s in self._pv_charge_hours if s != slot]
            if slot not in self._discharge_hours:
                self._discharge_hours = self._sort_slots(self._discharge_hours + [slot])
        elif slot in self._discharge_hours:
            # discharge → blocked (both, recurring)
            self._discharge_hours = [s for s in self._discharge_hours if s != slot]
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
            self._charge_hours = self._sort_slots(self._charge_hours + [slot])
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def set_hour_action(self, hour: int, action: str, date_str: str | None = None) -> None:
        """Set a specific hour to charge, discharge, blocked, or idle.

        The recurring ``blocked_charging_hours`` / ``blocked_discharging_hours``
        lists are preserved across non-blocked actions so that a per-day
        override (e.g. picked from the plan card for a blocked bar) only
        applies to ``(date_str, hour)`` while the same hour on future days
        stays blocked. To remove the block entirely, use the dedicated
        ``set_blocked_charging_hours`` / ``set_blocked_discharging_hours``
        services.

        Args:
            hour: Hour of day (0-23).
            action: One of ACTION_CHARGE, ACTION_DISCHARGE, ACTION_BLOCKED, ACTION_IDLE.
            date_str: ISO date string (YYYY-MM-DD). Defaults to today.
        """
        if hour < 0 or hour > 23:
            return
        if date_str is None:
            date_str = self._today_str()
        if not self._valid_slot(date_str, hour):
            return

        slot: ScheduleSlot = (date_str, hour)

        # Remove from charge/discharge/pv_charge lists (date-specific).
        # The recurring blocked_*_hours lists are intentionally left intact
        # for non-BLOCKED actions; the override lives only in the per-day
        # slot and the decision engine treats a per-day slot for a blocked
        # hour as a user override.
        self._charge_hours = [s for s in self._charge_hours if s != slot]
        self._discharge_hours = [s for s in self._discharge_hours if s != slot]
        self._pv_charge_hours = [s for s in self._pv_charge_hours if s != slot]

        # Add to correct list
        if action == ACTION_CHARGE:
            self._charge_hours = self._sort_slots(self._charge_hours + [slot])
        elif action == ACTION_PV_CHARGE:
            self._pv_charge_hours = self._sort_slots(self._pv_charge_hours + [slot])
        elif action == ACTION_DISCHARGE:
            self._discharge_hours = self._sort_slots(self._discharge_hours + [slot])
        elif action == ACTION_BLOCKED:
            if hour not in self._blocked_charging_hours:
                self._blocked_charging_hours = sorted(self._blocked_charging_hours + [hour])
            if hour not in self._blocked_discharging_hours:
                self._blocked_discharging_hours = sorted(self._blocked_discharging_hours + [hour])
        self._last_schedule_update = dt_util.now()
        self.hass.async_create_task(self.async_request_refresh())

    def clear_schedule(self) -> None:
        """Clear all scheduled hours."""
        self._charge_hours = []
        self._discharge_hours = []
        self._pv_charge_hours = []
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
        current_slot = (now.strftime("%Y-%m-%d"), now.hour)

        # Build price list for all future hours (today + tomorrow)
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

            slot_date = sdt.strftime("%Y-%m-%d")
            slot_hour = sdt.hour
            slot = (slot_date, slot_hour)

            # Include any hour that hasn't ended yet
            if slot >= current_slot:
                price = self._extract_price_ct(item)
                if price is not None:
                    prices.append({"date": slot_date, "hour": slot_hour, "price": price})

        if not prices:
            _LOGGER.info("No future hours with price data available")
            return

        # Sort ascending by price
        prices.sort(key=lambda x: x["price"])

        # Pick cheapest N hours below charge threshold (skip blocked charging hours)
        # and never override manually-set PV charging slots.
        pv_charge_set = set(self._pv_charge_hours)
        charge_slots: list[ScheduleSlot] = []
        for item in prices:
            if len(charge_slots) >= self.cheapest_hours:
                break
            slot = (item["date"], item["hour"])
            if slot in pv_charge_set:
                continue
            if item["hour"] not in self._blocked_charging_hours and item["price"] <= self.charge_price_threshold:
                charge_slots.append(slot)

        # Pick most expensive N hours above discharge threshold (skip blocked discharging hours)
        discharge_slots: list[ScheduleSlot] = []
        for item in reversed(prices):
            if len(discharge_slots) >= self.expensive_hours:
                break
            slot = (item["date"], item["hour"])
            if slot in pv_charge_set:
                continue
            if item["hour"] not in self._blocked_discharging_hours and item["price"] >= self.discharge_price_threshold:
                discharge_slots.append(slot)

        # Resolve conflicts: discharge wins (remove from charge)
        discharge_set = set(discharge_slots)
        charge_slots = [s for s in charge_slots if s not in discharge_set]

        self._charge_hours = self._sort_slots(charge_slots)
        self._discharge_hours = self._sort_slots(discharge_slots)
        self._last_schedule_update = dt_util.now()

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

    @staticmethod
    def _normalize_price_eur_per_kwh(
        state_value: str | float | int | None,
        attributes: dict[str, Any],
    ) -> float | None:
        """Normalize an EPEX state value to EUR/kWh for cost accounting."""
        if state_value in (None, "unavailable", "unknown"):
            return None
        try:
            price = float(state_value)
        except (ValueError, TypeError):
            return None

        unit = str(attributes.get("unit_of_measurement", "")).strip().lower()
        if "ct" in unit or "cent" in unit or unit.startswith("c/") or " c/" in unit:
            return price / 100.0
        return price

    def _get_entity_float(self, entity_id: str | None) -> float | None:
        """Read a numeric entity state, returning None when unavailable or invalid."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _read_meter_delta(
        self,
        *,
        entity_id: str | None,
        last_attr: str,
    ) -> tuple[bool, float | None]:
        """Return a positive meter delta and update the stored baseline."""
        if entity_id is None:
            return False, None

        current_kwh = self._get_entity_float(entity_id)
        if current_kwh is None:
            return False, None

        last_kwh = getattr(self, last_attr)
        if last_kwh is None:
            setattr(self, last_attr, current_kwh)
            return True, None

        delta_kwh = current_kwh - last_kwh
        if delta_kwh < 0:
            # The selected energy sensor reset or was replaced. Re-baseline only.
            setattr(self, last_attr, current_kwh)
            return True, None
        if delta_kwh == 0:
            return False, None

        setattr(self, last_attr, current_kwh)
        return True, delta_kwh

    def _update_cost_tracking(self, current_price_eur_per_kwh: float | None) -> None:
        """Update cumulative grid energy costs, revenue, and kWh import/export."""
        updated_consumption, consumption_delta_kwh = self._read_meter_delta(
            entity_id=self._grid_consumption_entity,
            last_attr="_last_grid_consumption_kwh",
        )
        updated_feed_in, feed_in_delta_kwh = self._read_meter_delta(
            entity_id=self._grid_feed_in_energy_entity,
            last_attr="_last_grid_feed_in_kwh",
        )

        # Accumulate kWh import/export (price-independent)
        if consumption_delta_kwh is not None:
            self._grid_energy_import += consumption_delta_kwh

        if feed_in_delta_kwh is not None:
            self._grid_energy_export += feed_in_delta_kwh

        if current_price_eur_per_kwh is not None:
            price_abs = abs(current_price_eur_per_kwh)
            if consumption_delta_kwh is not None:
                amount = consumption_delta_kwh * price_abs
                if current_price_eur_per_kwh >= 0:
                    self._grid_energy_cost += amount
                else:
                    self._grid_energy_revenue += amount

            if feed_in_delta_kwh is not None:
                amount = feed_in_delta_kwh * price_abs
                if current_price_eur_per_kwh >= 0:
                    self._grid_energy_revenue += amount
                else:
                    self._grid_energy_cost += amount

        if updated_consumption or updated_feed_in:
            self._last_cost_update = dt_util.now()

    def _sample_solar_surplus(self) -> None:
        """Append a solar surplus sample and recompute the 15-min sliding mean.

        Skips silently when the optional entity is not configured, unavailable,
        or has an invalid/non-numeric state. Negative values are treated as zero.
        The deque is trimmed to the last 15 minutes on every call.
        """
        if self._solar_surplus_entity is None:
            return

        state = self.hass.states.get(self._solar_surplus_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return

        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return

        if value < 0.0:
            value = 0.0

        now = dt_util.now()
        self._solar_samples.append((now, value))

        cutoff = now - timedelta(minutes=15)
        while self._solar_samples and self._solar_samples[0][0] < cutoff:
            self._solar_samples.popleft()

        if self._solar_samples:
            self._solar_surplus_mean = sum(
                v for _, v in self._solar_samples
            ) / len(self._solar_samples)
        else:
            self._solar_surplus_mean = None

    def _update_soc_hysteresis(self, soc: float) -> None:
        """Update SOC hysteresis blocked flags.

        All three flags are latched (Schmitt-trigger style): once a limit
        is reached the flag stays set until the SOC moves a full
        ``soc_hysteresis`` margin *back* across the threshold. This
        prevents the ±1% sensor jitter near the SOC boundaries from
        flapping the desired action and grid setpoint.
        """
        if soc >= self.max_soc:
            self._charge_blocked_by_soc = True
        elif soc < self.max_soc - self.soc_hysteresis:
            self._charge_blocked_by_soc = False

        if soc <= self.min_soc:
            self._discharge_blocked_by_soc = True
        elif soc > self.min_soc + self.soc_hysteresis:
            self._discharge_blocked_by_soc = False

        # Soft protection: when SOC is near the lower boundary, switch
        # discharge setpoint math to solar-only (no battery discharge term).
        # Latched symmetrically to the other flags above — without this,
        # a single noisy reading at the threshold toggles the discharge
        # math between solar-only and full-battery modes, and the desired
        # action oscillates with it. Release requires a full hysteresis
        # margin back above the threshold.
        if soc <= self.min_soc + self.soc_hysteresis:
            self._discharge_solar_only = True
        elif soc > self.min_soc + (2 * self.soc_hysteresis):
            self._discharge_solar_only = False

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

        self._update_soc_hysteresis(soc)

        # Priority 3: Force modes
        if self.control_mode == MODE_FORCE_CHARGE:
            if self.charge_allowed and not self._charge_blocked_by_soc:
                return ACTION_CHARGE
            return ACTION_IDLE

        if self.control_mode == MODE_FORCE_DISCHARGE:
            if self.discharge_allowed and not self._discharge_blocked_by_soc:
                return ACTION_DISCHARGE
            return ACTION_IDLE

        # Priority 4: Blocked hours — override schedule per action type
        if self.control_mode in (MODE_AUTO, MODE_MANUAL):
            now = dt_util.now()
            current_date = now.strftime("%Y-%m-%d")
            hour = now.hour
            current_slot: ScheduleSlot = (current_date, hour)

            # Priority 5: Auto or Manual — look up schedule (date-aware)
            # PV Charging takes precedence over plain charge/discharge so a
            # manually-set PV slot is honored even when the auto scheduler
            # also marked the hour. Requires the optional solar surplus
            # sensor; otherwise the slot falls back to idle.
            # PV charging is independent of `charge_allowed` and
            # `blocked_charging_hours` because it never draws from the grid
            # — it only splits the existing solar surplus between battery
            # and grid export. SOC blocking still applies.
            if (
                current_slot in self._pv_charge_hours
                and not self._charge_blocked_by_soc
                and self._solar_surplus_entity is not None
            ):
                return ACTION_PV_CHARGE
            if current_slot in self._charge_hours and self.charge_allowed and not self._charge_blocked_by_soc:
                # A per-day charge slot for a blocked hour is a user override
                # (set_hour_action leaves blocked_charging_hours intact and
                # the auto-scheduler skips blocked hours, so the slot can
                # only have been placed explicitly). Honor it.
                return ACTION_CHARGE
            if current_slot in self._discharge_hours and self.discharge_allowed and not self._discharge_blocked_by_soc:
                return ACTION_DISCHARGE
            return ACTION_IDLE

        # Priority 5: Fallback
        return ACTION_IDLE

    def _resolve_published_action(self, live_action: str) -> str:
        """Apply the action-change debounce to a live decision-engine result.

        Returns the action that should be published to the dashboard and
        used to compute the grid setpoint. A new ``live_action`` must
        persist for ``action_confirm_seconds`` before it replaces the
        currently published one; while it is being confirmed, the previous
        action is returned instead, so the grid setpoint and the
        ``desired_action`` sensor both stay stable.

        MODE_OFF bypasses the debounce and forces ``ACTION_IDLE`` immediately
        — switching the system off is a user-initiated safety state and
        must not be delayed.

        The first ever call also publishes immediately (no prior state to
        confirm against), so the integration does not appear stuck at
        ``idle`` for ``action_confirm_seconds`` after startup.
        """
        if self.control_mode == MODE_OFF:
            self._pending_action = None
            self._pending_action_since = None
            self._last_published_action = ACTION_IDLE
            return ACTION_IDLE

        if self._last_published_action is None:
            # First ever publish — no prior state to confirm against.
            self._last_published_action = live_action
            self._pending_action = None
            self._pending_action_since = None
            return live_action

        if live_action == self._last_published_action:
            # Live action matches what is already published — clear any
            # pending change so the next genuine flip starts fresh.
            self._pending_action = None
            self._pending_action_since = None
            return self._last_published_action

        # Live action differs from the published one. If we have not yet
        # seen this candidate, start the confirmation timer; if it is the
        # same candidate as last tick, check whether it has been stable
        # long enough to publish.
        now = dt_util.now()
        if self._pending_action != live_action:
            self._pending_action = live_action
            self._pending_action_since = now
            return self._last_published_action

        elapsed = (now - self._pending_action_since).total_seconds()
        if elapsed >= self.action_confirm_seconds:
            self._last_published_action = live_action
            self._pending_action = None
            self._pending_action_since = None
            return live_action

        return self._last_published_action

    def _compute_setpoint(self, action: str) -> float:
        """Compute the clamped grid setpoint for the given action."""
        if action == ACTION_CHARGE:
            raw = self.charge_power  # positive = import
        elif action == ACTION_PV_CHARGE:
            if self._charge_blocked_by_soc:
                # Battery full — can't absorb surplus; fall back to idle.
                raw = self.idle_setpoint
            else:
                # Split the solar surplus between battery and grid.
                # f=0 -> export all surplus (G=-surplus); f=1 -> self-consume
                # so surplus charges the battery (G=idle_setpoint).
                surplus = self._solar_surplus_mean or 0.0
                f = max(0.0, min(1.0, self.pv_charge_share / 100.0))
                raw = (1.0 - f) * (-surplus) + f * self.idle_setpoint
        elif action == ACTION_DISCHARGE:
            surplus = self._solar_surplus_mean or 0.0
            if self._discharge_solar_only:
                # Soft SOC protection: only export what solar is producing
                raw = -surplus
            else:
                # Normal discharge: discharge power + solar surplus
                raw = -(self.discharge_power + surplus)
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
            and abs(target_setpoint - current) <= self.setpoint_deadband
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
        # Sample solar surplus (no-op when entity not configured)
        self._sample_solar_surplus()

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
        live_action = self._determine_action()
        # Apply the action-change debounce: a new desired action must
        # persist for action_confirm_seconds before it is published and
        # written to the grid setpoint. This absorbs transient flips of
        # the decision engine (e.g. a single noisy SOC reading) without
        # delaying genuine schedule transitions, since those persist.
        action = self._resolve_published_action(live_action)
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
        current_price_eur_per_kwh = None
        epex_attributes: dict[str, Any] = {}
        prices_today: list[dict[str, Any]] = []
        prices_tomorrow: list[dict[str, Any]] = []
        if epex_state is not None and epex_state.state not in (
            "unavailable",
            "unknown",
        ):
            try:
                current_price = float(epex_state.state)
            except (ValueError, TypeError):
                pass
            epex_attributes = dict(epex_state.attributes)
            current_price_eur_per_kwh = self._normalize_price_eur_per_kwh(
                epex_state.state,
                epex_attributes,
            )
            raw_data = self._find_epex_data(epex_state.attributes)
            if raw_data:
                now = dt_util.now()
                today_str = now.strftime("%Y-%m-%d")
                tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
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
                    if sdt is not None:
                        date_str = sdt.strftime("%Y-%m-%d")
                        price = self._extract_price_ct(item)
                        if price is not None:
                            entry = {"hour": sdt.hour, "price": price}
                            if date_str == today_str:
                                prices_today.append(entry)
                            elif date_str == tomorrow_str:
                                prices_tomorrow.append(entry)
                prices_today.sort(key=lambda x: x["hour"])
                prices_tomorrow.sort(key=lambda x: x["hour"])

        # Clean expired schedule slots
        self._clean_expired_slots()

        # Grid feed-in control
        current_price_ct = current_price_eur_per_kwh * 100 if current_price_eur_per_kwh is not None else None
        feed_in_active, applied_feed_in = await self._apply_grid_feed_in(current_price_ct)

        # Cost tracking from optional cumulative kWh meters
        self._update_cost_tracking(current_price_eur_per_kwh)

        # Serialize schedule slots to dicts for sensor consumption
        charge_hours_data = [{"date": d, "hour": h} for d, h in self._charge_hours]
        discharge_hours_data = [{"date": d, "hour": h} for d, h in self._discharge_hours]
        pv_charge_hours_data = [{"date": d, "hour": h} for d, h in self._pv_charge_hours]

        return ChargeControlData(
            desired_action=action,
            target_setpoint=setpoint,
            charge_hours=charge_hours_data,
            discharge_hours=discharge_hours_data,
            pv_charge_hours=pv_charge_hours_data,
            blocked_charging_hours=list(self._blocked_charging_hours),
            blocked_discharging_hours=list(self._blocked_discharging_hours),
            current_price=current_price,
            epex_attributes=epex_attributes,
            prices_today=prices_today,
            prices_tomorrow=prices_tomorrow,
            grid_feed_in_active=feed_in_active,
            applied_max_grid_feed_in=applied_feed_in,
            grid_energy_cost=self.grid_energy_cost,
            grid_energy_revenue=self.grid_energy_revenue,
            grid_energy_import=self.grid_energy_import,
            grid_energy_export=self.grid_energy_export,
            current_price_eur_per_kwh=current_price_eur_per_kwh,
            last_schedule_update=self._last_schedule_update,
            last_cost_update=self._last_cost_update,
            solar_surplus_mean=self._solar_surplus_mean,
            solar_surplus_window_samples=len(self._solar_samples),
            discharge_solar_only=self._discharge_solar_only,
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
        if self._grid_consumption_entity is not None:
            entities_to_watch.append(self._grid_consumption_entity)
        if self._grid_feed_in_energy_entity is not None:
            entities_to_watch.append(self._grid_feed_in_energy_entity)
        if self._solar_surplus_entity is not None:
            entities_to_watch.append(self._solar_surplus_entity)

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

        # At each configured replan hour (default 18:00) — clean expired
        # slots, recalculate auto schedule (if auto mode), or reset manual
        # hours (if manual mode). The listener is (re)installed via
        # set_replan_hours(); here we just do the first install.
        self._install_replan_listener()

        # Initial data
        self.data = ChargeControlData()

        # Initial schedule calculation if already in auto mode (e.g. after restart)
        if self.control_mode == MODE_AUTO:
            self.calculate_auto_schedule()

        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Remove all listeners."""
        if self._replan_unsub is not None:
            self._replan_unsub()
            self._replan_unsub = None
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
