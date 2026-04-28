# Victron Charge Controller for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](http://www.apache.org/licenses/LICENSE-2.0)
[![CI](https://github.com/johannesWen/Victron-Charge-Controller/actions/workflows/ci.yml/badge.svg)](https://github.com/johannesWen/Victron-Charge-Controller/actions/workflows/ci.yml)
<!-- [![codecov](https://codecov.io/gh/johannesWen/Victron-Charge-Controller/graph/badge.svg?token=MU30OBSTG3)](https://codecov.io/gh/johannesWen/Victron-Charge-Controller) -->

Automated battery charge/discharge control for Victron ESS systems using EPEX Spot hourly electricity prices, with a Home Assistant custom integration installable via HACS.

## What It Does

- **Auto mode:** Charges the battery during the cheapest hours and discharges during the most expensive hours, based on EPEX Spot day-ahead prices.
- **Manual mode:** Lets you pick specific hours to charge or discharge via a dashboard with clickable hour buttons.
- **Force modes:** Immediately charge or discharge at the configured power level.
- **Safety:** Enforces SOC limits, setpoint limits, and automatically shuts down if Victron entities become unavailable.

## Prerequisites

| Component | Purpose |
|-----------|---------|
| Home Assistant 2026.2+ | Core platform |
| [Victron GX modbusTCP](https://github.com/sfstar/hass-victron) | Provides writable grid setpoint entity |
| [Victron Venus MQTT](https://github.com/tomer-w/ha-victron-mqtt) | Provides battery SOC, power readings |
| [EPEX Spot](https://github.com/mampfes/ha_epex_spot) | Provides hourly electricity prices |
|
## Installation

### HACS Custom Integration

1. Open HACS in your Home Assistant instance
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/johannesWen/Victron-Charge-Controller` with category **Integration**
4. Click **Install**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration → Victron Charge Control**
7. Select your Victron and EPEX Spot entities in the config flow

## Setup

After installation, add the integration via the UI:

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Victron Charge Control**
3. Select your 5 entities:
   - **Battery SOC sensor** — battery state of charge (0–100%)
   - **Grid setpoint entity** — writable ESS grid setpoint (Watts)
   - **Grid power sensor** — current grid import/export (Watts)
   - **Battery power sensor** — current battery charge/discharge (Watts)
   - **EPEX Spot price sensor** — hourly electricity prices

The integration creates a device with all configuration entities:

### Entities Created

| Entity | Type | Description |
|--------|------|-------------|
| Control Mode | Select | off / auto / manual / force_charge / force_discharge |
| Charge Allowed | Switch | Master enable for charging |
| Discharge Allowed | Switch | Master enable for discharging |
| Min SOC | Number | Floor SOC — never discharge below this |
| Max SOC | Number | Ceiling SOC — never charge above this |
| Charge Power | Number | Grid import power when charging (W) |
| Discharge Power | Number | Grid export power when discharging (W) |
| Idle Setpoint | Number | Grid setpoint during idle (W) |
| Min Grid Setpoint | Number | Hard floor for setpoint (W) |
| Max Grid Setpoint | Number | Hard ceiling for setpoint (W) |
| Cheapest Hours | Number | # cheapest hours to auto-charge |
| Expensive Hours | Number | # most expensive hours to auto-discharge |
| Charge Price Threshold | Number | Max price for auto-charge (ct/kWh) |
| Discharge Price Threshold | Number | Min price for auto-discharge (ct/kWh) |
| Desired Action | Sensor | Current computed action (charge/discharge/idle) |
| Target Setpoint | Sensor | Computed grid setpoint (W) |
| Charge Hours | Sensor | Currently scheduled charge hours |
| Discharge Hours | Sensor | Currently scheduled discharge hours |

### Services

| Service | Description |
|---------|-------------|
| `victron_charge_control.toggle_hour` | Cycle an hour: idle → charge → discharge → idle |
| `victron_charge_control.set_hour_action` | Set a specific hour to charge/discharge/idle |
| `victron_charge_control.calculate_schedule` | Recalculate auto schedule from EPEX prices |
| `victron_charge_control.clear_schedule` | Clear all scheduled hours |


## Configuration Defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| Min SOC | 10% | Battery won't discharge below this |
| Max SOC | 95% | Battery won't charge above this |
| Charge Power | 3000 W | Grid import power when charging |
| Discharge Power | 3000 W | Grid export power when discharging |
| Cheapest Hours | 4 | Number of cheapest hours to auto-charge |
| Expensive Hours | 4 | Number of most expensive hours to auto-discharge |
| Charge Price Threshold | 10 ct/kWh | Only auto-charge when price ≤ this |
| Discharge Price Threshold | 20 ct/kWh | Only auto-discharge when price ≥ this |

All parameters are adjustable at runtime via the UI — no YAML editing needed.

## Sign Convention

| Setpoint Value | Meaning |
|----------------|---------|
| Positive (e.g., +3000 W) | Import from grid → charge battery |
| Negative (e.g., -3000 W) | Export to grid → discharge battery |
| Zero | Idle / self-consumption |
