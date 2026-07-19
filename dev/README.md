# Dev Home Assistant Setup

This directory contains the Home Assistant dev configuration used to test the
Victron Charge Control integration together with its bundled Lovelace card.

## Running the dev stack

The card is built from `frontend/` and shipped inside the integration under
`custom_components/victron_charge_control/static/`. Build it first, then start
the dev container:

```bash
cd frontend
npm install
npm run build     # writes custom_components/victron_charge_control/static/victron-charge-controller-card.js
cd ..
docker compose up -d
```

Then open Home Assistant at <http://localhost:8123>.

The integration auto-loads the bundled card (`add_extra_js_url`), so no manual
Lovelace `resources:` entry is required. Stop the stack with:

```bash
docker compose down
```

## Backfill Cost Statistics

The Costs view reads Home Assistant long-term statistics for:

- `sensor.victron_charge_control_grid_energy_cost`
- `sensor.victron_charge_control_grid_energy_revenue`

The dev config provides dummy grid consumption, grid feed-in, and EPEX spot
price sensors. To make the day/week/month/year cost plots useful immediately,
backfill the recorder statistics with:

```bash
./dev/backfill_cost_statistics.py --dry-run --days 30
```

If the preview looks good, create a Home Assistant long-lived access token:

1. Open Home Assistant.
2. Go to your user profile.
3. Create a long-lived access token.
4. Export it as `HA_TOKEN`.

Then import the statistics:

```bash
HA_TOKEN="your-long-lived-token" ./dev/backfill_cost_statistics.py --days 30 --clear-first
```

`--clear-first` removes existing cost/revenue statistics for the two dev
entities before importing the generated rows. This is usually what you want
when iterating on dummy data.

Useful options:

```bash
./dev/backfill_cost_statistics.py \
  --url http://localhost:8123 \
  --days 30 \
  --timezone Europe/Berlin \
  --prefix victron_charge_control \
  --clear-first
```

Notes:

- The script imports long-term statistics, not raw entity history.
- The card uses Home Assistant's `recorder/statistics_during_period` API, so
  the plot needs recorder statistics rows.
- The generated data mirrors the dummy profiles in `configuration.yaml`.
- Refresh the Costs view after the import finishes.
- If Home Assistant is not on `localhost:8123`, pass `--url`.