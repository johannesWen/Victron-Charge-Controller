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
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_BLOCKED,
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    CONF_BATTERY_SOC_ENTITY,
    CONF_DC_COUPLED_PV_FEED_IN_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_CONSUMPTION_ENTITY,
    CONF_GRID_FEED_IN_ENERGY_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    CONF_SAFETY_STARTUP_GRACE_SECONDS,
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
    DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
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
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)

from .solar import sample_solar_surplus
from .epex import (
    extract_price_ct,
    find_epex_data,
    get_battery_soc,
    get_current_price_ct,
    get_entity_float,
    normalize_price_eur_per_kwh,
)
from .schedule import (
    clean_expired_slots,
    clear_all as schedule_clear_all,
    normalize_blocked_hours,
    set_charge_slots,
    set_discharge_slots,
    set_hour_action as schedule_set_hour_action,
    sort_slots,
    today_str as schedule_today_str,
    toggle_hour as schedule_toggle_hour,
    valid_slot,
)
from .persistence import (
    apply_loaded_plan,
    build_plan_payload,
    deserialize_hours,
    deserialize_slots,
    serialize_slots,
)
from .energy import accumulate_cost_tracking, read_meter_delta
from .decision import (
    DebounceState,
    DecisionState,
    SocHysteresisState,
    compute_setpoint as decision_compute_setpoint,
    determine_action as decision_determine_action,
    resolve_published_action as decision_resolve_published_action,
    update_soc_hysteresis as decision_update_soc_hysteresis,
)
from .actuation import (
    apply_dc_coupled_feed_in as actuation_apply_dc_coupled_feed_in,
    apply_grid_feed_in as actuation_apply_grid_feed_in,
    apply_setpoint as actuation_apply_setpoint,
    is_reduced_feed_in_mode as actuation_is_reduced_feed_in_mode,
)
from .safety import check_safety as safety_check_safety, is_in_startup_grace
from .planning import calculate_auto_schedule as planning_calculate_auto_schedule

_LOGGER = logging.getLogger(__name__)

# Type alias for a date-qualified schedule slot: (ISO date "YYYY-MM-DD", hour 0-23)
ScheduleSlot = tuple[str, int]


@dataclass
class EpexPriceView:
    """Snapshot of the EPEX data extracted on a single tick.

    Built by ``_step_load_epex_view`` and consumed by the cost tracker
    and the ``ChargeControlData`` snapshot — keeps the per-tick
    arguments grouped so the pipeline method signatures stay short.
    """

    current_price: float | None
    eur_per_kwh: float | None
    attributes: dict[str, Any]
    prices_today: list[dict[str, Any]]
    prices_tomorrow: list[dict[str, Any]]


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
        self._dc_coupled_pv_feed_in_entity: str | None = (
            entry.data.get(CONF_DC_COUPLED_PV_FEED_IN_ENTITY) or None
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

        # --- DC coupled PV feed-in control ---
        # When enabled, the linked external switch is driven ON (normal
        # mode) / OFF (reduced mode) in lock-step with the grid feed-in
        # reduced-mode predicate. Inert unless both this feature and
        # ``grid_feed_in_control_enabled`` are on, and the integration is
        # not in MODE_OFF. ``_last_applied_dc_feed_in_state`` dedups
        # redundant switch.turn_on/off calls across ticks.
        self.control_dc_coupled_feed_in: bool = False
        self._last_applied_dc_feed_in_state: bool | None = None

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

        # --- Safety watchdog startup grace period ---
        # On HA startup the first coordinator refresh typically runs before
        # the upstream Victron / EPEX integrations have published a real
        # state. Without a grace window the safety watchdog would see
        # ``"unavailable"`` and spuriously switch the system to OFF on
        # every restart. The deadline is cleared early on the first tick
        # where all critical entities report a real state, so a healthy
        # startup exits the grace period almost immediately. The grace
        # period length is user-configurable via the options flow.
        grace_seconds: int = int(
            entry.options.get(
                CONF_SAFETY_STARTUP_GRACE_SECONDS,
                DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
            )
        )
        self.safety_startup_grace_seconds: int = grace_seconds
        self._safety_startup_deadline: datetime | None = (
            dt_util.now() + timedelta(seconds=grace_seconds)
        ) if grace_seconds > 0 else None

        # --- Persistent plan storage ---
        # The charge/discharge/pv_charge slots and the blocked-hour lists
        # are persisted to a Home Assistant ``Store`` so they survive
        # restarts. The Store is keyed by config entry id so multiple
        # entries would not collide (today only one is allowed by the
        # config flow, but the per-entry key keeps the code future-proof).
        # ``_schedule_loaded_from_store`` tracks whether async_setup()
        # actually applied a payload from disk; it is used to keep the
        # post-load save decision sensible (no point writing back an
        # empty default state on every restart).
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
        )
        self._schedule_loaded_from_store: bool = False
        # ``_suspend_save`` blocks fire-and-forget Store writes for the
        # entire ``async_setup`` window. Without it, the three text
        # entities (``BlockedChargingHoursText``,
        # ``BlockedDischargingHoursText``, ``ReplanHoursText``) call
        # their setters from ``async_added_to_hass`` during
        # ``forward_entry_setups`` and schedule a save. The first
        # ``await`` inside ``async_setup`` then lets the event loop run
        # those pending saves — which write the (still empty) charge
        # / discharge / pv_charge slots to the Store, overwriting the
        # user's persisted plan before ``_async_load_schedule`` ever
        # gets to read it. The flag is cleared at the very end of
        # ``async_setup`` so the first real user mutation after startup
        # is persisted.
        self._suspend_save: bool = True

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
    def dc_coupled_pv_feed_in_entity(self) -> str | None:
        return self._dc_coupled_pv_feed_in_entity

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
        self._dc_coupled_pv_feed_in_entity = (
            data.get(CONF_DC_COUPLED_PV_FEED_IN_ENTITY) or None
        )

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
        return sort_slots(slots)

    @staticmethod
    def _valid_slot(date_str: str, hour: int) -> bool:
        """Validate a schedule slot."""
        return valid_slot(date_str, hour)

    def _today_str(self) -> str:
        """Get today's date as ISO string."""
        return schedule_today_str()

    def _clean_expired_slots(self) -> None:
        """Remove schedule slots that are in the past."""
        self._charge_hours, self._discharge_hours, self._pv_charge_hours = clean_expired_slots(
            self._charge_hours, self._discharge_hours, self._pv_charge_hours
        )

    def set_charge_hours(self, slots: list[ScheduleSlot]) -> None:
        """Set charge hours (date-aware) and trigger update."""
        self._charge_hours = set_charge_slots(slots)
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    def set_discharge_hours(self, slots: list[ScheduleSlot]) -> None:
        """Set discharge hours (date-aware) and trigger update."""
        self._discharge_hours = set_discharge_slots(slots)
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    def set_blocked_charging_hours(self, hours: list[int]) -> None:
        """Set blocked charging hours (recurring daily) and trigger update."""
        self._blocked_charging_hours = normalize_blocked_hours(hours)
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    def set_blocked_discharging_hours(self, hours: list[int]) -> None:
        """Set blocked discharging hours (recurring daily) and trigger update."""
        self._blocked_discharging_hours = normalize_blocked_hours(hours)
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    def set_replan_hours(self, hours: list[int]) -> None:
        """Set replan hours (recurring daily) and (re)install the time listener.

        Empty list disables automatic replanning. Triggers a refresh so the
        text entity state stays in sync.
        """
        normalized = normalize_blocked_hours(hours)
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
        self._async_schedule_save()
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
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    def toggle_hour(self, hour: int, date_str: str | None = None) -> None:
        """Cycle an hour: idle → charge → pv_charge → discharge → blocked → idle.

        'blocked' in this cycle means blocked for both charging and discharging
        (recurring, hour-of-day only).

        Args:
            hour: Hour of day (0-23).
            date_str: ISO date string (YYYY-MM-DD). Defaults to today.
        """
        (
            self._charge_hours,
            self._discharge_hours,
            self._pv_charge_hours,
            self._blocked_charging_hours,
            self._blocked_discharging_hours,
            no_op,
        ) = schedule_toggle_hour(
            hour,
            date_str,
            self._charge_hours,
            self._discharge_hours,
            self._pv_charge_hours,
            self._blocked_charging_hours,
            self._blocked_discharging_hours,
        )
        if no_op:
            return
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
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
        (
            self._charge_hours,
            self._discharge_hours,
            self._pv_charge_hours,
            self._blocked_charging_hours,
            self._blocked_discharging_hours,
            no_op,
        ) = schedule_set_hour_action(
            hour,
            action,
            date_str,
            self._charge_hours,
            self._discharge_hours,
            self._pv_charge_hours,
            self._blocked_charging_hours,
            self._blocked_discharging_hours,
        )
        if no_op:
            return
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    def clear_schedule(self) -> None:
        """Clear all scheduled hours."""
        (
            self._charge_hours,
            self._discharge_hours,
            self._pv_charge_hours,
            self._blocked_charging_hours,
            self._blocked_discharging_hours,
        ) = schedule_clear_all()
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()
        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # Plan persistence
    # ------------------------------------------------------------------
    #
    # The charge/discharge/pv_charge plan and the blocked-hour lists are
    # written to a Home Assistant ``Store`` on every change and reloaded
    # on startup. The Store payload is intentionally minimal: slot lists
    # are serialized as ``[[date, hour], ...]`` and the schedule update
    # timestamp as an ISO string (or ``None``). Malformed entries are
    # silently dropped at load time so a corrupted Store can never wedge
    # the integration; the user can always press the **Recalculate
    # Schedule** button to rebuild the plan.
    #
    # On startup, if the Store is empty the coordinator's in-memory state
    # is left untouched. This is important for two reasons:
    #   1. A fresh install must not auto-replan (the user has explicitly
    #      asked for that behavior).
    #   2. Migrating from a version that did not write to the Store
    #      leaves the RestoreEntity-restored state on the coordinator
    #      intact, so blocked hours / replan hours / control mode are
    #      still recovered.
    #
    # Once the user changes anything, the next save populates the Store
    # and the migration path is no longer needed.

    @staticmethod
    def _serialize_slots(slots: list[ScheduleSlot]) -> list[list[Any]]:
        """Serialize schedule slots for JSON storage."""
        return serialize_slots(slots)

    @staticmethod
    def _deserialize_slots(raw: Any) -> list[ScheduleSlot]:
        """Deserialize slot list from JSON, dropping any malformed entry."""
        return deserialize_slots(raw)

    @staticmethod
    def _deserialize_hours(raw: Any) -> list[int]:
        """Deserialize an hour-of-day list, dropping any out-of-range value."""
        return deserialize_hours(raw)

    async def _async_save_schedule(self) -> None:
        """Persist the current plan to the Home Assistant Store."""
        payload = build_plan_payload(
            charge_hours=self._charge_hours,
            discharge_hours=self._discharge_hours,
            pv_charge_hours=self._pv_charge_hours,
            blocked_charging_hours=self._blocked_charging_hours,
            blocked_discharging_hours=self._blocked_discharging_hours,
            last_schedule_update=self._last_schedule_update,
        )
        try:
            await self._store.async_save(payload)
        except Exception:  # noqa: BLE001
            # Persistence is best-effort. A failed write must not break
            # the running integration; the next change will retry.
            _LOGGER.warning("Failed to persist charge plan to Store", exc_info=True)

    def _async_schedule_save(self) -> None:
        """Schedule a fire-and-forget save of the current plan.

        Used by the public mutators (``set_charge_hours``,
        ``toggle_hour``, ...) so the call site stays sync and the
        disk write does not block the caller.

        No-op while ``_suspend_save`` is True (the entire
        ``async_setup`` window). This is what prevents the text
        entities' ``async_added_to_hass`` from clobbering the
        persisted plan during HA startup — see the comment on the
        ``_suspend_save`` attribute in ``__init__``.
        """
        if self._suspend_save:
            return
        self.hass.async_create_task(self._async_save_schedule())

    async def _async_load_schedule(self) -> None:
        """Load the plan from the Store and apply it to the coordinator.

        If the Store is empty (fresh install, first ever start, or a
        migration from a pre-persistence version), the coordinator's
        in-memory state is left untouched. This is the desired behavior
        because:

        * A fresh install must not auto-replan (the user explicitly
          requested no replan on HA restart).
        * On a migration, the RestoreEntity callbacks on
          ``text.py``/``select.py`` have already restored blocked hours,
          replan hours and the control mode into the coordinator; the
          Store load must not wipe them.
        """
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Failed to load charge plan from Store", exc_info=True)
            return

        applied = apply_loaded_plan(data)
        if applied is None:
            # Empty Store or unsupported payload shape: keep whatever the
            # RestoreEntity callbacks already populated.
            return

        self._charge_hours = applied["charge_hours"]
        self._discharge_hours = applied["discharge_hours"]
        self._pv_charge_hours = applied["pv_charge_hours"]
        self._blocked_charging_hours = applied["blocked_charging_hours"]
        self._blocked_discharging_hours = applied["blocked_discharging_hours"]
        self._last_schedule_update = applied["last_schedule_update"]
        self._schedule_loaded_from_store = applied["loaded"]
        _LOGGER.info(
            "Loaded charge plan from Store: %d charge, %d discharge, %d pv_charge slots",
            len(self._charge_hours),
            len(self._discharge_hours),
            len(self._pv_charge_hours),
        )

    # ------------------------------------------------------------------
    # EPEX data extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_epex_data(attributes: dict[str, Any]) -> list[dict[str, Any]]:
        """Find the list of price entries from EPEX entity attributes."""
        return find_epex_data(attributes)

    @staticmethod
    def _extract_price_ct(item: dict[str, Any]) -> float | None:
        """Extract price in ct/kWh from a single EPEX entry."""
        return extract_price_ct(item)

    # ------------------------------------------------------------------
    # Auto schedule calculation from EPEX prices
    # ------------------------------------------------------------------

    def calculate_auto_schedule(self) -> None:
        """Calculate optimal charge/discharge hours from EPEX spot prices."""
        result = planning_calculate_auto_schedule(
            self.hass,
            epex_spot_entity=self._epex_spot_entity,
            control_mode=self.control_mode,
            cheapest_hours=self.cheapest_hours,
            expensive_hours=self.expensive_hours,
            charge_price_threshold=self.charge_price_threshold,
            discharge_price_threshold=self.discharge_price_threshold,
            blocked_charging_hours=self._blocked_charging_hours,
            blocked_discharging_hours=self._blocked_discharging_hours,
            pv_charge_hours=self._pv_charge_hours,
            now=dt_util.now(),
        )
        if result is None:
            return
        charge_slots, discharge_slots = result
        self._charge_hours = charge_slots
        self._discharge_hours = discharge_slots
        self._last_schedule_update = dt_util.now()
        self._async_schedule_save()

    # ------------------------------------------------------------------
    # Decision engine
    # ------------------------------------------------------------------

    def _get_battery_soc(self) -> float | None:
        """Get current battery SOC, or None if unavailable."""
        return get_battery_soc(self.hass, self._battery_soc_entity)

    @staticmethod
    def _normalize_price_eur_per_kwh(
        state_value: str | float | int | None,
        attributes: dict[str, Any],
    ) -> float | None:
        """Normalize an EPEX state value to EUR/kWh for cost accounting."""
        return normalize_price_eur_per_kwh(state_value, attributes)

    def _get_current_price_ct(self) -> float | None:
        """Read the EPEX spot price in the same unit as ``grid_feed_in_price_threshold``.

        Returns ``None`` when the EPEX sensor is unavailable or unparseable.
        Used to determine the reduced-mode status before computing the
        setpoint, so the PV-Charge/Discharge setpoints can be clamped to
        the active feed-in limit in the same tick.
        """
        return get_current_price_ct(self.hass, self._epex_spot_entity)

    def _get_entity_float(self, entity_id: str | None) -> float | None:
        """Read a numeric entity state, returning None when unavailable or invalid."""
        return get_entity_float(self.hass, entity_id)

    def _read_meter_delta(
        self,
        *,
        entity_id: str | None,
        last_attr: str,
    ) -> tuple[bool, float | None]:
        """Return a positive meter delta and update the stored baseline."""
        last_kwh = getattr(self, last_attr)
        new_last, delta, _ = read_meter_delta(self.hass, entity_id, last_kwh)
        if new_last is not None:
            setattr(self, last_attr, new_last)
            return True, delta
        return False, None

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

        new_cost, new_revenue, new_import, new_export, baselines_changed = (
            accumulate_cost_tracking(
                consumption_delta_kwh=consumption_delta_kwh,
                feed_in_delta_kwh=feed_in_delta_kwh,
                current_price_eur_per_kwh=current_price_eur_per_kwh,
                cost=self._grid_energy_cost,
                revenue=self._grid_energy_revenue,
                import_kwh=self._grid_energy_import,
                export_kwh=self._grid_energy_export,
            )
        )
        self._grid_energy_cost = new_cost
        self._grid_energy_revenue = new_revenue
        self._grid_energy_import = new_import
        self._grid_energy_export = new_export

        if updated_consumption or updated_feed_in or baselines_changed:
            self._last_cost_update = dt_util.now()

    def _sample_solar_surplus(self) -> None:
        """Append a solar surplus sample and recompute the 15-min sliding mean.

        Skips silently when the optional entity is not configured, unavailable,
        or has an invalid/non-numeric state. Negative values are treated as zero.
        The deque is trimmed to the last 15 minutes on every call.
        """
        self._solar_surplus_mean = sample_solar_surplus(
            self.hass, self._solar_surplus_entity, self._solar_samples
        )

    def _update_soc_hysteresis(self, soc: float) -> None:
        """Update SOC hysteresis blocked flags (Schmitt-trigger style)."""
        new_state = decision_update_soc_hysteresis(
            soc,
            max_soc=self.max_soc,
            min_soc=self.min_soc,
            hysteresis=self.soc_hysteresis,
            state=SocHysteresisState(
                charge_blocked_by_soc=self._charge_blocked_by_soc,
                discharge_blocked_by_soc=self._discharge_blocked_by_soc,
                discharge_solar_only=self._discharge_solar_only,
            ),
        )
        self._charge_blocked_by_soc = new_state.charge_blocked_by_soc
        self._discharge_blocked_by_soc = new_state.discharge_blocked_by_soc
        self._discharge_solar_only = new_state.discharge_solar_only

    def _determine_action(self) -> str:
        """Deterministic priority stack — returns charge/discharge/idle."""
        # The decision engine does not touch the SOC flags unless it had
        # a usable SOC reading. Build the result with the latched state
        # preserved, then apply the new flags back to the coordinator.
        result = decision_determine_action(
            state=DecisionState(
                control_mode=self.control_mode,
                charge_allowed=self.charge_allowed,
                discharge_allowed=self.discharge_allowed,
                max_soc=self.max_soc,
                min_soc=self.min_soc,
                soc_hysteresis=self.soc_hysteresis,
                charge_hours=self._charge_hours,
                discharge_hours=self._discharge_hours,
                pv_charge_hours=self._pv_charge_hours,
                solar_surplus_entity=self._solar_surplus_entity,
            ),
            soc_state=SocHysteresisState(
                charge_blocked_by_soc=self._charge_blocked_by_soc,
                discharge_blocked_by_soc=self._discharge_blocked_by_soc,
                discharge_solar_only=self._discharge_solar_only,
            ),
            hass=self.hass,
            battery_soc_entity=self._battery_soc_entity,
            now=dt_util.now(),
        )
        if result.action == ACTION_IDLE and self._get_battery_soc() is None:
            _LOGGER.debug("Battery SOC unavailable — falling back to idle")
        self._charge_blocked_by_soc = result.soc_state.charge_blocked_by_soc
        self._discharge_blocked_by_soc = result.soc_state.discharge_blocked_by_soc
        self._discharge_solar_only = result.soc_state.discharge_solar_only
        return result.action

    def _resolve_published_action(self, live_action: str) -> str:
        """Apply the action-change debounce to a live decision-engine result."""
        result = decision_resolve_published_action(
            live_action,
            control_mode=self.control_mode,
            action_confirm_seconds=self.action_confirm_seconds,
            state=DebounceState(
                last_published_action=self._last_published_action,
                pending_action=self._pending_action,
                pending_action_since=self._pending_action_since,
            ),
            now=dt_util.now(),
        )
        self._last_published_action = result.state.last_published_action
        self._pending_action = result.state.pending_action
        self._pending_action_since = result.state.pending_action_since
        return result.published_action

    def _compute_setpoint(self, action: str, *, is_reduced: bool = False) -> float:
        """Compute the clamped grid setpoint for the given action."""
        return decision_compute_setpoint(
            action,
            is_reduced=is_reduced,
            charge_power=self.charge_power,
            discharge_power=self.discharge_power,
            idle_setpoint=self.idle_setpoint,
            min_grid_setpoint=self.min_grid_setpoint,
            max_grid_setpoint=self.max_grid_setpoint,
            charge_blocked_by_soc=self._charge_blocked_by_soc,
            discharge_solar_only=self._discharge_solar_only,
            solar_surplus_mean=self._solar_surplus_mean,
            pv_charge_share=self.pv_charge_share,
            reduced_max_grid_feed_in=self.reduced_max_grid_feed_in,
        )

    # ------------------------------------------------------------------
    # Setpoint application
    # ------------------------------------------------------------------

    async def _apply_setpoint(
        self, target_setpoint: float, action: str | None = None
    ) -> None:
        """Write the target setpoint to the Victron grid setpoint entity.

        When ``action`` is ``ACTION_IDLE`` the deadband is bypassed so the
        grid setpoint is always reset to ``idle_setpoint``, regardless of
        how close the previous value is. Without this, a transition from
        PV-Charging (or any other state) to Idle could leave the entity
        holding the old setpoint whenever the difference falls within
        ``setpoint_deadband``.
        """
        def _log(current: float, target: float) -> None:
            _LOGGER.info(
                "Setpoint: %.0fW → %.0fW (action=%s, mode=%s, SOC=%s)",
                current,
                target,
                self.data.desired_action if self.data else "?",
                self.control_mode,
                self._get_battery_soc(),
            )

        self._last_applied_setpoint = await actuation_apply_setpoint(
            self.hass,
            entity_id=self._grid_setpoint_entity,
            target_setpoint=target_setpoint,
            action=action,
            last_applied_setpoint=self._last_applied_setpoint,
            setpoint_deadband=self.setpoint_deadband,
            on_log=_log,
        )

    # ------------------------------------------------------------------
    # Grid feed-in control
    # ------------------------------------------------------------------

    def _is_reduced_feed_in_mode(self, current_price: float | None) -> bool:
        """Return whether the reduced grid feed-in mode should be active."""
        return actuation_is_reduced_feed_in_mode(
            grid_feed_in_control_enabled=self.grid_feed_in_control_enabled,
            current_price=current_price,
            grid_feed_in_price_threshold=self.grid_feed_in_price_threshold,
        )

    async def _apply_grid_feed_in(self, current_price: float | None) -> tuple[bool, float | None]:
        """Control max grid feed-in based on spot price.

        Returns (is_reduced, applied_value).
        """
        is_reduced, applied_value, new_last = await actuation_apply_grid_feed_in(
            self.hass,
            entity_id=self._max_grid_feed_in_entity,
            grid_feed_in_control_enabled=self.grid_feed_in_control_enabled,
            current_price=current_price,
            default_max_grid_feed_in=self.default_max_grid_feed_in,
            reduced_max_grid_feed_in=self.reduced_max_grid_feed_in,
            grid_feed_in_price_threshold=self.grid_feed_in_price_threshold,
            last_applied_feed_in=self._last_applied_feed_in,
        )
        self._last_applied_feed_in = new_last
        return is_reduced, applied_value

    async def _apply_dc_coupled_feed_in(self, is_reduced: bool) -> None:
        """Drive the linked external DC-coupled PV feed-in switch.

        The ``is_reduced`` flag is the same predicate used by
        ``_apply_grid_feed_in`` so the two actuators never disagree.
        See ``actuation.apply_dc_coupled_feed_in`` for the inert-conditions
        and dedup behavior.
        """
        self._last_applied_dc_feed_in_state = (
            await actuation_apply_dc_coupled_feed_in(
                self.hass,
                entity_id=self._dc_coupled_pv_feed_in_entity,
                control_dc_coupled_feed_in=self.control_dc_coupled_feed_in,
                grid_feed_in_control_enabled=self.grid_feed_in_control_enabled,
                control_mode=self.control_mode,
                is_reduced=is_reduced,
                last_applied_state=self._last_applied_dc_feed_in_state,
            )
        )

    # ------------------------------------------------------------------
    # Safety watchdog
    # ------------------------------------------------------------------

    def _check_safety(self) -> bool:
        """Check critical entities. Returns True if safe, False to trigger shutdown."""
        return safety_check_safety(
            self.hass,
            [self._battery_soc_entity, self._grid_setpoint_entity],
        )

    # ------------------------------------------------------------------
    # Core update method
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> ChargeControlData:
        """Run the decision engine and apply the setpoint.

        The tick is broken into named pipeline methods to keep each
        concern testable in isolation:

        1. ``_sample_solar_surplus`` — refresh the 15-minute solar mean
        2. ``_step_safety`` — watchdog + startup grace + OFF switch
        3. ``_step_decide`` — current price → live action → published
           action (debounced) → computed setpoint
        4. ``_step_apply_setpoint`` — write the setpoint to the ESS
        5. ``_step_load_epex_view`` — read EPEX state, build the
           today/tomorrow price list, normalize the current price
        6. ``_clean_expired_slots`` — drop past schedule slots
        7. ``_apply_grid_feed_in`` — push reduced/default feed-in to ESS
        8. ``_update_cost_tracking`` — accumulate cost/revenue/import/export
        9. ``_build_snapshot`` — assemble the ChargeControlData result
        """
        self._sample_solar_surplus()
        await self._step_safety()
        current_price_ct, is_reduced, action, setpoint = self._step_decide()
        await self._step_apply_setpoint(action, setpoint)
        price_view = self._step_load_epex_view()
        self._clean_expired_slots()
        feed_in_active, applied_feed_in = await self._apply_grid_feed_in(
            current_price_ct
        )
        await self._apply_dc_coupled_feed_in(is_reduced=is_reduced)
        self._update_cost_tracking(price_view.eur_per_kwh)
        return self._build_snapshot(
            action=action,
            setpoint=setpoint,
            price_view=price_view,
            feed_in_active=feed_in_active,
            applied_feed_in=applied_feed_in,
        )

    async def _step_safety(self) -> None:
        """Run the safety watchdog for this tick."""
        now = dt_util.now()
        in_startup_grace = is_in_startup_grace(now, self._safety_startup_deadline)
        safe = self._check_safety()
        if safe and self._safety_startup_deadline is not None:
            # First tick with all critical entities reporting a real state
            # ends the grace period early — the watchdog becomes fully
            # active for the rest of the run.
            self._safety_startup_deadline = None
            _LOGGER.debug(
                "Safety watchdog startup grace period cleared after first safe tick"
            )
        if (
            self.control_mode != MODE_OFF
            and not safe
            and not in_startup_grace
        ):
            _LOGGER.warning(
                "Safety watchdog: critical entity unavailable — switching to OFF"
            )
            self.control_mode = MODE_OFF
            self._safety_startup_deadline = None
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Victron Charge Control — Safety Stop",
                    "message": (
                        "A critical Victron entity became unavailable. "
                        "System switched to OFF."
                    ),
                    "notification_id": "victron_cc_safety_stop",
                },
                blocking=False,
            )
        elif not safe and in_startup_grace:
            remaining = (self._safety_startup_deadline - now).total_seconds()
            _LOGGER.debug(
                "Safety watchdog: critical entity unavailable during startup "
                "grace (%.0fs remaining) — tolerating",
                remaining,
            )

    def _step_decide(self) -> tuple[float | None, bool, str, float]:
        """Read the current price, pick an action, and compute the setpoint.

        The current price is read once here (in ct/kWh) so both the
        reduced-mode predicate and ``_apply_grid_feed_in`` see the same
        value in the same tick.
        """
        current_price_ct = self._get_current_price_ct()
        is_reduced = self._is_reduced_feed_in_mode(current_price_ct)
        live_action = self._determine_action()
        action = self._resolve_published_action(live_action)
        setpoint = self._compute_setpoint(action, is_reduced=is_reduced)
        return current_price_ct, is_reduced, action, setpoint

    async def _step_apply_setpoint(self, action: str, setpoint: float) -> None:
        """Write the computed setpoint (or reset to idle when turning OFF)."""
        if self.control_mode != MODE_OFF:
            await self._apply_setpoint(setpoint, action=action)
        elif self._last_applied_setpoint != self.idle_setpoint:
            # When turning off, reset to idle so the ESS does not stay
            # pinned at a stale charge/discharge setpoint.
            await self._apply_setpoint(self.idle_setpoint, action=ACTION_IDLE)

    def _step_load_epex_view(self) -> EpexPriceView:
        """Read the EPEX state and assemble the today/tomorrow price lists."""
        epex_state = self.hass.states.get(self._epex_spot_entity)
        current_price: float | None = None
        current_price_eur_per_kwh: float | None = None
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
                epex_state.state, epex_attributes
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

        return EpexPriceView(
            current_price=current_price,
            eur_per_kwh=current_price_eur_per_kwh,
            attributes=epex_attributes,
            prices_today=prices_today,
            prices_tomorrow=prices_tomorrow,
        )

    def _build_snapshot(
        self,
        *,
        action: str,
        setpoint: float,
        price_view: EpexPriceView,
        feed_in_active: bool,
        applied_feed_in: float | None,
    ) -> ChargeControlData:
        """Assemble the per-tick ``ChargeControlData`` returned to entities."""
        return ChargeControlData(
            desired_action=action,
            target_setpoint=setpoint,
            charge_hours=[{"date": d, "hour": h} for d, h in self._charge_hours],
            discharge_hours=[{"date": d, "hour": h} for d, h in self._discharge_hours],
            pv_charge_hours=[{"date": d, "hour": h} for d, h in self._pv_charge_hours],
            blocked_charging_hours=list(self._blocked_charging_hours),
            blocked_discharging_hours=list(self._blocked_discharging_hours),
            current_price=price_view.current_price,
            epex_attributes=price_view.attributes,
            prices_today=price_view.prices_today,
            prices_tomorrow=price_view.prices_tomorrow,
            grid_feed_in_active=feed_in_active,
            applied_max_grid_feed_in=applied_feed_in,
            grid_energy_cost=self.grid_energy_cost,
            grid_energy_revenue=self.grid_energy_revenue,
            grid_energy_import=self.grid_energy_import,
            grid_energy_export=self.grid_energy_export,
            current_price_eur_per_kwh=price_view.eur_per_kwh,
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

        # Restore the previous charge plan from the persistent Store. If
        # the Store is empty (fresh install, first ever start, or a
        # migration from a pre-persistence version) the coordinator's
        # in-memory state is left untouched — in particular we
        # deliberately do NOT call calculate_auto_schedule() here so the
        # user's previous plan is not silently overwritten on a Home
        # Assistant restart. The user can still trigger a fresh plan via
        # the **Recalculate Schedule** button or by waiting for the next
        # configured replan hour.
        #
        # The load is the very first ``await`` in this method on
        # purpose: it runs before any other code that could yield, and
        # combined with ``_suspend_save`` (still True at this point) it
        # guarantees the text entities' ``async_added_to_hass``
        # restore-setters, which ran earlier during
        # ``forward_entry_setups``, did not write a stale empty plan
        # over the user's persisted one.
        await self._async_load_schedule()

        await self.async_request_refresh()

        # From this point on, public mutators are allowed to write to
        # the Store again. Set last so a race between any
        # ``hass.async_create_task`` save scheduled during
        # ``forward_entry_setups`` and the load above cannot clobber
        # the restored state.
        self._suspend_save = False

    async def async_shutdown(self) -> None:
        """Remove all listeners."""
        if self._replan_unsub is not None:
            self._replan_unsub()
            self._replan_unsub = None
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        self._safety_startup_deadline = None
