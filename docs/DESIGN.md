# Victron Charge Control — Design Document

> **Goal:** Automatically charge/discharge a Victron home battery from/to the grid based on EPEX Spot hourly electricity prices, with manual scheduling, SOC/setpoint safety limits, and a Home Assistant dashboard.

---

## 1. Solution Architecture

### Approach

The entire solution is built with **native Home Assistant** capabilities:

| Layer | Mechanism |
|---|---|
| Configuration & limits | `input_number`, `input_boolean`, `input_select`, `input_text` helpers |
| Price processing & schedule | Jinja2 template sensors + a script that recalculates the schedule |
| Decision engine | A template sensor (`sensor.victron_desired_action`) with a deterministic priority stack |
| Actuation | An automation that writes the computed setpoint to the Victron grid setpoint entity via modbusTCP |
| Dashboard | Lovelace YAML with `apexcharts-card` (price chart) and `button-card` (hour selector grid) from HACS |
| Safety | Automations for watchdog, mode-off reset, SOC clamping |

**No custom integration or custom Python code is required.**

Two HACS frontend cards are recommended for the dashboard:

1. **`apexcharts-card`** — bar chart of hourly EPEX prices, color-coded by schedule.
2. **`button-card`** — hour selector grid (24 buttons, one per hour).

Both are mature, widely used, and well-maintained. A fallback using only native HA cards is possible but significantly less usable (documented in §5).

### Component Diagram

```
┌──────────────────────────────────────────────────────┐
│  EPEX Spot Integration          Victron modbusTCP    │
│  sensor.epex_spot_*             number.grid_setpoint │
│           │                     sensor.battery_soc   │
│           │                     sensor.grid_power    │
│           ▼                     sensor.battery_power │
│  ┌─────────────────┐                   ▲             │
│  │ Schedule Calc.   │                   │             │
│  │ (script)         │──▶ input_text     │             │
│  └─────────────────┘   charge/discharge │             │
│           │              hours          │             │
│           ▼                             │             │
│  ┌─────────────────┐    ┌────────────┐  │             │
│  │ Decision Engine  │───▶│ Setpoint   │──┘             │
│  │ (template sensor)│    │ Automation │               │
│  └─────────────────┘    └────────────┘               │
│           ▲                                           │
│  input_select.mode  input_number.soc_limits           │
│  input_boolean.*    input_number.setpoint_limits      │
└──────────────────────────────────────────────────────┘
```

### File Layout

```
homeassistant/
  packages/
    victron_charge_control.yaml   ← all helpers, sensors, automations, scripts
  dashboards/
    victron_energy.yaml           ← Lovelace dashboard
```

Everything lives in a single HA **package** file for clean separation from the rest of the HA config. The package is loaded via `configuration.yaml`:

```yaml
homeassistant:
  packages:
    victron_charge_control: !include packages/victron_charge_control.yaml
```

---

## 2. Functional Requirements Breakdown

| # | Feature | Mechanism |
|---|---------|-----------|
| F1 | **Auto charge** on low EPEX prices | Script ranks today's hours by price, picks cheapest N that are below threshold → stores in `input_text.victron_charge_hours` |
| F2 | **Auto discharge** on high EPEX prices | Same script picks most expensive N above threshold → stores in `input_text.victron_discharge_hours` |
| F3 | **Configurable min/max SOC** | `input_number.victron_min_soc` / `max_soc` — enforced in the decision-engine template |
| F4 | **Configurable min/max grid setpoint** | `input_number.victron_min_grid_setpoint` / `max_grid_setpoint` — clamped in `sensor.victron_target_setpoint` |
| F5 | **Manual hourly schedule** | User clicks hour buttons on dashboard → updates `input_text` charge/discharge hours |
| F6 | **Dashboard with price chart + controls** | `apexcharts-card` + `button-card` grid + entities cards |
| F7 | **Control modes: off / auto / manual / force_charge / force_discharge** | `input_select.victron_control_mode` |
| F8 | **Safety: watchdog, SOC limits, unavailability handling** | Dedicated automations |
| F9 | **Observability** | `system_log.write`, `persistent_notification`, template sensor attributes |

---

## 3. Entity and Helper Design

### 3.1 Input Helpers

#### `input_select`

| Entity ID | Options | Default | Purpose |
|-----------|---------|---------|---------|
| `input_select.victron_control_mode` | off, auto, manual, force_charge, force_discharge | off | Master control mode |

#### `input_boolean`

| Entity ID | Default | Purpose |
|-----------|---------|---------|
| `input_boolean.victron_charge_allowed` | on | Master charge enable — blocks all charging when off |
| `input_boolean.victron_discharge_allowed` | on | Master discharge enable — blocks all discharging when off |

#### `input_number`

| Entity ID | Min | Max | Step | Default | Unit | Purpose |
|-----------|-----|-----|------|---------|------|---------|
| `victron_min_soc` | 0 | 100 | 1 | 10 | % | Floor SOC — never discharge below |
| `victron_max_soc` | 0 | 100 | 1 | 95 | % | Ceiling SOC — never charge above |
| `victron_charge_power` | 0 | 15000 | 100 | 3000 | W | Grid setpoint used when charging (positive) |
| `victron_discharge_power` | 0 | 15000 | 100 | 3000 | W | Grid setpoint magnitude when discharging (applied as negative) |
| `victron_idle_setpoint` | -500 | 500 | 10 | 0 | W | Grid setpoint during idle |
| `victron_min_grid_setpoint` | -15000 | 0 | 100 | -5000 | W | Hard floor for any setpoint sent to Victron |
| `victron_max_grid_setpoint` | 0 | 15000 | 100 | 5000 | W | Hard ceiling for any setpoint sent to Victron |
| `victron_cheapest_hours` | 0 | 12 | 1 | 4 | — | Number of cheapest hours to charge (auto mode) |
| `victron_expensive_hours` | 0 | 12 | 1 | 4 | — | Number of most expensive hours to discharge (auto mode) |
| `victron_charge_price_threshold` | -50 | 100 | 0.5 | 10 | ct/kWh | Max price for auto-charge — hours above this are excluded even if among cheapest N |
| `victron_discharge_price_threshold` | -50 | 100 | 0.5 | 20 | ct/kWh | Min price for auto-discharge — hours below this are excluded even if among most expensive N |

#### `input_text`

| Entity ID | Default | Purpose |
|-----------|---------|---------|
| `input_text.victron_charge_hours` | "" | Comma-separated hours to charge, e.g. `"1,2,3,4"` |
| `input_text.victron_discharge_hours` | "" | Comma-separated hours to discharge, e.g. `"17,18,19,20"` |

### 3.2 Template Sensors

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.victron_desired_action` | string | Core decision engine output: `charge`, `discharge`, or `idle` |
| `sensor.victron_target_setpoint` | number (W) | Computed grid setpoint (clamped to min/max limits) |

### 3.3 External Entities (user must map)

| Placeholder | Expected Type | Source |
|-------------|---------------|--------|
| `sensor.YOUR_VICTRON_BATTERY_SOC` | 0–100 (%) | Victron GX modbusTCP or Venus MQTT |
| `number.YOUR_VICTRON_GRID_SETPOINT` | number (W) | Victron GX modbusTCP — the ESS grid setpoint register |
| `sensor.YOUR_VICTRON_GRID_POWER` | number (W) | Victron — positive = import, negative = export |
| `sensor.YOUR_VICTRON_BATTERY_POWER` | number (W) | Victron — positive = charging, negative = discharging |
| `sensor.YOUR_EPEX_SPOT_PRICE` | number (ct/kWh) | EPEX Spot integration — must have `data` attribute with hourly prices |

---

## 4. Control Logic

### Priority Stack (deterministic, top wins)

```
Priority 1 — HARD SAFETY
  IF control_mode == "off"                        → idle
  IF battery SOC is unavailable/unknown           → idle
  IF victron grid setpoint entity is unavailable  → do not actuate (skip)

Priority 2 — FORCE MODES
  IF control_mode == "force_charge"
    IF charge_allowed AND soc < max_soc           → charge
    ELSE                                          → idle
  IF control_mode == "force_discharge"
    IF discharge_allowed AND soc > min_soc        → discharge
    ELSE                                          → idle

Priority 3 — SCHEDULE (auto or manual)
  IF control_mode IN ("auto", "manual")
    IF current_hour IN charge_hours
       AND charge_allowed AND soc < max_soc       → charge
    ELIF current_hour IN discharge_hours
       AND discharge_allowed AND soc > min_soc    → discharge
    ELSE                                          → idle

Priority 4 — FALLBACK
  → idle
```

### Auto vs Manual

| Aspect | Auto Mode | Manual Mode |
|--------|-----------|-------------|
| Schedule source | Calculated by `script.victron_calculate_schedule` from EPEX prices | Set by user via dashboard buttons |
| Recalculation | On price update, at 14:00 (tomorrow prices), at 00:05 (daily reset), on parameter change | Only when user clicks buttons |
| Execution | Same decision engine (`sensor.victron_desired_action`) | Same decision engine |

Both modes share the same `input_text.victron_charge_hours` and `input_text.victron_discharge_hours`. In auto mode, the script overwrites these. In manual mode, only the user changes them.

### Setpoint Calculation

```
IF action == "charge":
    raw_setpoint = +charge_power       (positive → import from grid)
IF action == "discharge":
    raw_setpoint = -discharge_power    (negative → export to grid)
IF action == "idle":
    raw_setpoint = idle_setpoint       (typically 0)

final_setpoint = clamp(raw_setpoint, min_grid_setpoint, max_grid_setpoint)
```

### Anti-Oscillation

The actuation automation includes a **deadband**: the setpoint is only written to the Victron if `|target - current| > 50W`. Combined with the per-minute evaluation interval, this prevents rapid toggling.

### Missing / Stale Data

| Condition | Behavior |
|-----------|----------|
| Battery SOC unavailable | Decision engine returns `idle` |
| EPEX prices unavailable | Auto schedule calculation skipped; existing schedule preserved |
| Grid setpoint entity unavailable | Watchdog automation switches mode to `off` after 2 min |
| HA restart | All `input_*` helpers restore their last state (HA default). Automations re-trigger on next time pattern. |

### Negative Prices

Negative EPEX prices are handled naturally — they will be among the cheapest hours and selected for charging. The charge price threshold can be set to a negative value to only charge during negative-price hours.

### Very High Prices

Very high prices will be among the most expensive hours and selected for discharge. The discharge price threshold provides a floor — only hours above this threshold are selected.

---

## 5. Dashboard Design

### Layout

```
┌──────────────────────────────────────────────────┐
│  STATUS BAR                                       │
│  Mode: Auto │ Action: Charging │ SOC: 72%        │
│  Setpoint: +3000W │ Price: 5.2 ct/kWh            │
├──────────────────────────────────────────────────┤
│  POWER GAUGES                                     │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐         │
│  │ SOC  │  │ Grid │  │ Batt │  │Price │         │
│  │ 72%  │  │+3.0kW│  │+2.8kW│  │ 5.2¢ │         │
│  └──────┘  └──────┘  └──────┘  └──────┘         │
├──────────────────────────────────────────────────┤
│  EPEX PRICE CHART (apexcharts-card)              │
│  ████ ██ ██ ██ ██████ ████ ████ ██ ██            │
│  green=charge  red=discharge  gray=idle          │
├──────────────────────────────────────────────────┤
│  HOUR SELECTOR (button-card grid, 4×6)           │
│  00 01 02 03 04 05                               │
│  06 07 08 09 10 11                               │
│  12 13 14 15 16 17                               │
│  18 19 20 21 22 23                               │
│  ■ = charge  ■ = discharge  □ = idle             │
│  Tap to cycle: idle → charge → discharge → idle  │
├──────────────────────────────────────────────────┤
│  CONTROLS                                         │
│  Mode selector: off / auto / manual / force_*    │
│  Charge allowed: [toggle]                         │
│  Discharge allowed: [toggle]                      │
├──────────────────────────────────────────────────┤
│  CONFIGURATION                                    │
│  Min SOC ───●──── Max SOC                         │
│  Charge power     Discharge power                 │
│  Idle setpoint    Min/Max setpoint                │
│  Cheapest hours   Expensive hours                 │
│  Charge threshold Discharge threshold             │
└──────────────────────────────────────────────────┘
```

### Custom Card Dependencies

| Card | HACS Repo | Purpose | Fallback |
|------|-----------|---------|----------|
| `apexcharts-card` | `RomRider/apexcharts-card` | Price bar chart with color-coded schedule | `history-graph` (no color coding, limited) |
| `button-card` | `custom-cards/button-card` | Hour selector grid | `entities` card with 24 `input_select` helpers (verbose, less usable) |

### Hour Selector UX

Each button cycles through three states on tap:

```
idle (gray) → charge (green) → discharge (red) → idle (gray)
```

The current hour gets a highlighted border. In auto mode the buttons reflect the auto-calculated schedule; the user can view but should understand that the next auto recalculation will overwrite any manual changes. In manual mode, changes persist until the user modifies them.

---

## 6. Price-Processing Approach

### Data Source

The EPEX Spot integration (assumed: `mampfes/ha-epex-spot`) provides:

- **State:** current price in ct/kWh
- **Attribute `data`:** list of price entries, each containing:
  - `start_time` — hour start (datetime)
  - `end_time` — hour end (datetime)
  - `price_ct_per_kwh` — price (float)

Today's prices are available from midnight. Tomorrow's prices typically become available around **13:00–14:00 CET** (after EPEX day-ahead auction results).

### Algorithm (v1 — practical first version)

```
1. Read all prices from sensor attribute 'data'
2. Filter to today's remaining hours (hour >= current_hour)
3. Sort ascending by price
4. CHARGE hours = cheapest N where price ≤ charge_threshold
5. DISCHARGE hours = most expensive N where price ≥ discharge_threshold
6. Store as comma-separated strings in input_text helpers
```

**Dual constraint:** an hour must be both among the top N AND pass the threshold test. This prevents charging during merely "less expensive" hours when all prices are high, and prevents discharging during merely "more expensive" hours when all prices are low.

### Algorithm (v2 — extensible)

Future enhancements (not implemented in v1):

- **Cross-day optimization:** when tomorrow prices are available, optimize across 24–48 hours
- **Spread constraint:** require a minimum price spread between charge and discharge hours to ensure profitability (accounting for round-trip efficiency losses ~10-15%)
- **SOC-aware planning:** limit charge hours based on battery capacity and charge rate
- **Rolling recalculation:** recalculate remaining schedule at each hour boundary, not just once per day
- **Percentile logic:** charge below 25th percentile, discharge above 75th percentile (adapts to overall price level)

### Timezone / Day Rollover

- All time comparisons use `now()` and `as_local` to work in the HA instance's configured timezone
- Schedule is recalculated at 00:05 (not 00:00 to avoid midnight edge cases)
- `input_text` charge/discharge hours are always for **today** (0–23)
- When tomorrow prices arrive (~14:00), the auto script only schedules today's remaining hours

### Missing Tomorrow Prices

If tomorrow's prices are not yet available, the auto schedule only covers today. The 14:00 trigger will re-run when prices appear. If prices never arrive, the next-day 00:05 trigger recalculates with whatever data is available.

---

## 7. Recommended Implementation Approach

### Phase Plan

| Phase | Scope | Effort |
|-------|-------|--------|
| **Phase 1** | Install package with helpers, decision engine sensor, actuation automation. Test with `force_charge` / `force_discharge` modes. | Minimal |
| **Phase 2** | Add auto schedule calculation script. Verify cheapest/expensive hour selection against known EPEX data. | Low |
| **Phase 3** | Install HACS cards. Deploy dashboard. Test hour button toggling in manual mode. | Medium |
| **Phase 4** | Add safety watchdog, notification automation. Tune thresholds, SOC limits, deadband. | Low |
| **Phase 5** | Optional: cross-day optimization, spread constraint, percentile logic, efficiency factor. | Optional |

### Phase 1 — Validation Checklist

- [ ] `input_select.victron_control_mode` appears in HA
- [ ] Setting mode to `force_charge` writes a positive setpoint to Victron
- [ ] Setting mode to `force_discharge` writes a negative setpoint
- [ ] Setting mode to `off` resets setpoint to idle
- [ ] SOC limits are enforced (battery stops charging at max_soc)
- [ ] Setpoint clamping works (never exceeds min/max grid setpoint)

---

## 8. Concrete Home Assistant Implementation

All implementation is in two files:

| File | Contents |
|------|----------|
| `homeassistant/packages/victron_charge_control.yaml` | All helpers, template sensors, automations, scripts |
| `homeassistant/dashboards/victron_energy.yaml` | Complete Lovelace dashboard |

See those files for full YAML. Key implementation notes:

### Entity ID Replacement

Search and replace these 5 placeholders with your actual entity IDs:

```
sensor.YOUR_VICTRON_BATTERY_SOC
number.YOUR_VICTRON_GRID_SETPOINT
sensor.YOUR_VICTRON_GRID_POWER
sensor.YOUR_VICTRON_BATTERY_POWER
sensor.YOUR_EPEX_SPOT_PRICE
```

### Template Sensor: Decision Engine

The `sensor.victron_desired_action` template implements the priority stack from §4 in a single Jinja2 template. It evaluates every minute (due to `now()` usage) and on any input state change.

### Actuation Automation

The `victron_apply_setpoint` automation watches `sensor.victron_target_setpoint` and the 1-minute time pattern. It applies the setpoint to the Victron only when the difference exceeds 50W (deadband).

### Schedule Calculation Script

The `victron_calculate_schedule` script reads the EPEX `data` attribute, sorts today's remaining hours by price, picks the cheapest/most expensive N that pass threshold tests, and stores the result in the `input_text` helpers.

---

## 9. Safety and Operational Constraints

### Hard Constraints

| Constraint | Enforcement |
|------------|-------------|
| Never charge above `max_soc` | Decision engine returns `idle` when `soc >= max_soc` |
| Never discharge below `min_soc` | Decision engine returns `idle` when `soc <= min_soc` |
| Never exceed `max_grid_setpoint` | `sensor.victron_target_setpoint` clamps with `min()` |
| Never go below `min_grid_setpoint` | `sensor.victron_target_setpoint` clamps with `max()` |
| No accidental export when discharge disabled | `input_boolean.victron_discharge_allowed` checked before any discharge action |
| No accidental import when charge disabled | `input_boolean.victron_charge_allowed` checked before any charge action |

### Failure Modes

| Failure | Response |
|---------|----------|
| HA restart | All `input_*` helpers restore last state. Automations re-trigger within 1 minute. |
| Victron entities unavailable | Watchdog switches mode to `off` after 2 minutes. Persistent notification created. |
| EPEX prices unavailable | Schedule calculation skipped. Existing schedule preserved (stale but safe). |
| SOC sensor unavailable | Decision engine returns `idle`. |

### Logging

- Every setpoint change is logged via `system_log.write` at `info` level under logger `victron_charge_control`.
- Action changes trigger `persistent_notification` with mode, SOC, price, and setpoint details.
- Failed schedule calculations are logged at `warning` level.

### Optional Enhancements

- Push notifications via `notify` service (uncomment/add in the notification automation)
- History tracking via `utility_meter` sensors for energy charged/discharged per day
- Logbook entries for audit trail

---

## 10. Final Recommendation

### Best Architecture

**Native HA packages** with template sensors for the decision engine, automations for actuation, and scripts for schedule calculation. No custom integration needed.

### Simplest Working Version

1. Install the package file
2. Replace 5 entity ID placeholders
3. Set mode to `force_charge` or `force_discharge` to verify control works
4. Then switch to `auto` mode

### Recommended Dashboard UX

- `apexcharts-card` price chart with color-coded bars (green=charge, red=discharge, gray=idle)
- `button-card` grid for hour selection (tap to cycle idle/charge/discharge)
- Standard HA entity cards for configuration sliders

### Recommended Helper Model

- Single `input_select` for mode (not separate booleans for auto/manual)
- Two `input_text` for schedule storage (simpler than 24 individual input_selects)
- Separate `input_number` for charge power and discharge power (not a single setpoint)
- Dual constraint for auto schedule: top-N AND threshold (not just one)

### Next Steps

1. Copy `victron_charge_control.yaml` to your HA `packages/` directory
2. Replace the 5 entity ID placeholders
3. Reload HA (or restart)
4. Verify helpers appear in Developer Tools → States
5. Test with `force_charge` and `force_discharge` modes
6. Install `apexcharts-card` and `button-card` from HACS
7. Add the dashboard
8. Switch to `auto` mode and observe schedule calculation

---

## Questions / Assumptions to Validate Before Deployment

> These are assumptions made in the design. Validate before going live, but the design is not blocked on them.

| # | Assumption | Validation |
|---|-----------|------------|
| A1 | The Victron ESS is configured for **external control** (Mode 3) via modbusTCP | Check Victron GX settings → ESS → Mode |
| A2 | The grid setpoint entity is a `number` entity writable via `number.set_value` | Test in Developer Tools → Services |
| A3 | Sign convention: positive setpoint = import/charge, negative = export/discharge | Set a small positive value and verify battery charges |
| A4 | The EPEX Spot sensor has a `data` attribute containing a list of price dicts with `start_time`, `end_time`, `price_ct_per_kwh` keys | Check in Developer Tools → States → Attributes |
| A5 | The EPEX Spot `data` attribute contains both today and tomorrow prices (when available) | Check after 14:00 CET |
| A6 | Battery SOC entity reports 0–100 (not 0.0–1.0) | Check in Developer Tools → States |
| A7 | The Victron system can handle setpoint changes every minute without issues | Typically fine; increase deadband if needed |
| A8 | HA timezone is configured correctly (matching your local time and the EPEX market zone) | Check Settings → General → Time Zone |
| A9 | The modbusTCP connection is stable and the Victron entities don't frequently go unavailable | Monitor for a day before enabling auto mode |
| A10 | Grid power sensor: positive = importing, negative = exporting (for dashboard display) | Check during known import/export |
