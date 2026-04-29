"""Constants for the Victron Charge Control integration."""

from __future__ import annotations

DOMAIN = "victron_charge_control"

# --- Config entry keys (from config flow) ---
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_GRID_SETPOINT_ENTITY = "grid_setpoint_entity"
CONF_EPEX_SPOT_ENTITY = "epex_spot_entity"
CONF_MAX_GRID_FEED_IN_ENTITY = "max_grid_feed_in_entity"

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
ACTION_DISCHARGE = "discharge"
ACTION_BLOCKED = "blocked"

# --- Defaults ---
DEFAULT_MIN_SOC = 10.0
DEFAULT_MAX_SOC = 95.0
DEFAULT_CHARGE_POWER = 3000.0
DEFAULT_DISCHARGE_POWER = 3000.0
DEFAULT_IDLE_SETPOINT = 0.0
DEFAULT_MIN_GRID_SETPOINT = -5000.0
DEFAULT_MAX_GRID_SETPOINT = 5000.0
DEFAULT_CHEAPEST_HOURS = 4
DEFAULT_EXPENSIVE_HOURS = 4
DEFAULT_CHARGE_PRICE_THRESHOLD = 10.0
DEFAULT_DISCHARGE_PRICE_THRESHOLD = 20.0
DEFAULT_DEADBAND = 50.0
DEFAULT_BLOCKED_CHARGING_HOURS = [18, 19, 20, 21, 22, 23]
DEFAULT_BLOCKED_DISCHARGING_HOURS = [15, 16, 17]
DEFAULT_GRID_FEED_IN_PRICE_THRESHOLD = 0.0
DEFAULT_MAX_GRID_FEED_IN = 5000.0
DEFAULT_REDUCED_GRID_FEED_IN = 0.0

# --- Update interval ---
UPDATE_INTERVAL_SECONDS = 60

# --- EPEX data attribute keys (mampfes/ha-epex-spot) ---
EPEX_ATTR_DATA = "data"
EPEX_KEY_START_TIME = "start_time"
EPEX_KEY_END_TIME = "end_time"
EPEX_KEY_PRICE = "price_ct_per_kwh"
# Alternative price key (EUR/kWh, used by some integrations)
EPEX_KEY_PRICE_EUR = "price_per_kwh"
