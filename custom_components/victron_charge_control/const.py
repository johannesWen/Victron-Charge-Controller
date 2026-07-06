"""Constants for the Victron Charge Control integration."""

from __future__ import annotations

DOMAIN = "victron_charge_control"

# --- Persistent storage ---
# Used to save the charge/discharge plan so it survives Home Assistant
# restarts. The actual Store key is unique per config entry and is
# constructed as ``f"{STORAGE_KEY_PREFIX}.{entry_id}"``. Bump
# ``STORAGE_VERSION`` whenever the persisted shape changes; Home Assistant
# will then ignore previously written data and start fresh.
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_schedule"

# --- Config entry keys (from config flow) ---
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_GRID_SETPOINT_ENTITY = "grid_setpoint_entity"
CONF_EPEX_SPOT_ENTITY = "epex_spot_entity"
CONF_MAX_GRID_FEED_IN_ENTITY = "max_grid_feed_in_entity"
CONF_GRID_CONSUMPTION_ENTITY = "grid_consumption_entity"
CONF_GRID_FEED_IN_ENERGY_ENTITY = "grid_feed_in_energy_entity"
CONF_SOLAR_SURPLUS_ENTITY = "solar_surplus_entity"

# --- Config options keys (from options flow) ---
CONF_SAFETY_STARTUP_GRACE_SECONDS = "safety_startup_grace_seconds"

# --- Control modes ---
MODE_OFF = "off"
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_FORCE_CHARGE = "force_charge"
MODE_FORCE_DISCHARGE = "force_discharge"

CONTROL_MODES = [
    MODE_OFF,
    MODE_AUTO,
    MODE_MANUAL,
    MODE_FORCE_CHARGE,
    MODE_FORCE_DISCHARGE,
]

# --- Actions ---
ACTION_IDLE = "idle"
ACTION_CHARGE = "charge"
ACTION_PV_CHARGE = "pv_charge"
ACTION_DISCHARGE = "discharge"
ACTION_BLOCKED = "blocked"

# --- Defaults ---
DEFAULT_MIN_SOC = 10.0
DEFAULT_MAX_SOC = 95.0
DEFAULT_SOC_HYSTERESIS = 2.0
DEFAULT_CHARGE_POWER = 3000.0
DEFAULT_DISCHARGE_POWER = 3000.0
DEFAULT_IDLE_SETPOINT = 0.0
DEFAULT_MIN_GRID_SETPOINT = -5000.0
DEFAULT_MAX_GRID_SETPOINT = 5000.0
DEFAULT_CHEAPEST_HOURS = 4
DEFAULT_EXPENSIVE_HOURS = 4
DEFAULT_CHARGE_PRICE_THRESHOLD = 10.0
DEFAULT_DISCHARGE_PRICE_THRESHOLD = 20.0
DEFAULT_DEADBAND = 200.0
DEFAULT_BLOCKED_CHARGING_HOURS = [18, 19, 20, 21, 22, 23]
DEFAULT_BLOCKED_DISCHARGING_HOURS = [15, 16, 17]
DEFAULT_REPLAN_HOURS = [18]
DEFAULT_GRID_FEED_IN_PRICE_THRESHOLD = 0.0
DEFAULT_MAX_GRID_FEED_IN = 5000.0
DEFAULT_REDUCED_GRID_FEED_IN = 0.0
DEFAULT_PV_CHARGE_SHARE = 100.0

# How long a new desired action must persist before it is published/applied.
# Acts as a debounce: short, transient flips of the decision engine (e.g. a
# noisy SOC reading bouncing across a limit) are absorbed and never reach
# the grid setpoint or the dashboard. 30s is long enough to swallow a single
# 60s-coordinator-cadence flap and short enough that a genuine schedule
# transition (cheap hour starting, etc.) feels instant to the user.
DEFAULT_ACTION_CONFIRM_SECONDS = 30.0

# Grace period (seconds) after HA startup during which the safety watchdog
# tolerates unavailable critical entities. The first coordinator refresh
# typically runs before all upstream integrations (Victron Venus, etc.) have
# published a real state, so without a grace window the watchdog would
# spuriously switch the system to OFF on every Home Assistant restart.
# The deadline is cleared early on the first tick where all critical entities
# report a real state, so a healthy startup exits the grace period almost
# immediately.
DEFAULT_SAFETY_STARTUP_GRACE_SECONDS = 90

# --- Update interval ---
UPDATE_INTERVAL_SECONDS = 60

# --- EPEX data attribute keys (mampfes/ha-epex-spot) ---
EPEX_ATTR_DATA = "data"
EPEX_KEY_START_TIME = "start_time"
EPEX_KEY_END_TIME = "end_time"
EPEX_KEY_PRICE = "price_ct_per_kwh"
# Alternative price key (EUR/kWh, used by some integrations)
EPEX_KEY_PRICE_EUR = "price_per_kwh"
