# Dev Home Assistant Setup

This directory contains the Home Assistant dev configuration used to test the
Victron Charge Control integration together with its bundled Lovelace card.

## Using the devcontainer

With Docker Compose v2.24.4+ and the VS Code Dev Containers extension installed, open
the repository and run **Dev Containers: Reopen in Container**. The configuration
extends the root Compose file with a Python 3.14 development service and Node 20,
matching CI. It installs `requirements-dev.txt` and the frontend dependencies,
then builds the bundled card automatically.

Home Assistant runs alongside the editor container at <http://localhost:8123>.
After the build, startup automatically completes onboarding, creates the Charge
Control integration using the dummy entities, and enables Auto mode on the new
integration. Wait for the **Development dashboard ready** message, then sign in:

- Username: `dev`
- Password: `victron-dev`
- Dashboard: <http://localhost:8123/victron-dev/settings> (**Victron Dev** in the sidebar)

These credentials are for local development only; the devcontainer publishes
Home Assistant on `127.0.0.1` only. The dashboard includes **Settings**, **Plan**,
**History**, and **Dev Controls** tabs. Costs collect from startup; use the backfill
command below when you want historical sample data.

The bootstrap uses Home Assistant's onboarding and config-flow APIs. It runs on
each start, preserves existing users and configured integration settings, and
does not write Home Assistant's internal storage files. For an already onboarded
instance with different credentials, run it from the editor terminal with
`HA_DEV_USERNAME` and `HA_DEV_PASSWORD` set to an existing administrator account:

```bash
python dev/bootstrap_home_assistant.py
```

The existing integration and dummy configuration mounts are reused.
Home Assistant's database and onboarding settings persist in the
`homeassistant-data` Docker volume across rebuilds. Closing the devcontainer stops
both services.

If the standalone Compose stack is already running, stop it before opening the
devcontainer: both use port 8123. The devcontainer uses a Compose-generated
container name so it can coexist with a stopped `ha-dev` container. Existing data
stored only in that standalone container is not migrated into the new volume.

For linked Git worktrees, use Git on the host or open a regular clone: the
external Git metadata directory is not mounted into the editor container.

From the devcontainer terminal:

```bash
pytest
npm --prefix frontend test
npm --prefix frontend run watch
```

The watcher writes directly into the integration mounted by Home Assistant.
Refresh the browser after frontend changes; restart Home Assistant from its UI
after Python changes. Commands inside the editor container reach Home Assistant
at `http://homeassistant:8123`, for example:

```bash
HA_TOKEN="your-long-lived-token" ./dev/backfill_cost_statistics.py --url http://homeassistant:8123 --days 30
```

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

The History view reads Home Assistant long-term statistics for:

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
- Refresh the History view after the import finishes.
- If Home Assistant is not on `localhost:8123`, pass `--url`.
