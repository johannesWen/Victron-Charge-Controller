# Dev Home Assistant Setup

This directory contains the Home Assistant dev configuration used to test the
Victron Charge Control integration together with its bundled Lovelace card.

## Using the devcontainer

With Docker Compose v2.24.4+ and the VS Code Dev Containers extension installed, open
the repository and run **Dev Containers: Reopen in Container**. The configuration
extends the root Compose file with a Python 3.14 development service and Node 20,
matching CI. It installs `requirements-dev.txt` and the frontend dependencies,
then builds the bundled card automatically.

For Solcast forecasts, first copy the root template and fill in your rooftop API
key locally:

```bash
cp .env.example .env
# Edit .env and set SOLCAST_API_KEY to your Solcast rooftop API key.
```

Then run **Dev Containers: Rebuild and Reopen in Container** (also after changing
`.env`). Compose reads this optional file into the editor/bootstrap service and
passes `SOLCAST_API_KEY` to Home Assistant to select the real forecast path;
the key is never a build argument or part of an image. All dotenv files, including
nested and environment-specific files, are gitignored except the root
`.env.example`. Keep the real `.env` private.

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

A one-shot init service installs [Solcast PV Forecast v4.6.1](https://github.com/BJReplay/ha-solcast-solar/releases/tag/v4.6.1)
into that config volume **before Home Assistant starts**, with a pinned release
checksum. It also works with an existing volume, preserves any existing
`custom_components/solcast_solar` directory, and leaves HA configuration untouched.
The first install requires network access to GitHub; installation failure stops
HA startup rather than starting with incomplete code. Retry the rebuild after
resolving the download or volume-permission issue. Existing Solcast code is never
automatically upgraded or replaced.

When `SOLCAST_API_KEY` is set and no Solcast entry exists, the bootstrap creates
one through Home Assistant's config-flow API. This stores the key in HA's config
volume, as normal integration setup does. With a missing/blank key, Solcast code
is installed but remains unconfigured. If no saved Solcast entry exists, the
devcontainer supplies **synthetic PV test data**, so the Plan PV view works
without a cloud account. Its deterministic central/lower daylight curves include
zero nights and continuous half-hour intervals for today and tomorrow in HA's
timezone, including 23/25-hour DST days. The existing five-minute forecast poll
regenerates the horizon and timestamp, including after midnight; there are no
network/API requests for synthetic forecasts. Diagnostics, WebSocket `reason`,
and the provider activation log explicitly label the data synthetic. Disabling
**Use Solcast forecast** disables this data too.

Only `.devcontainer/docker-compose.yml` mounts `dev/victron_dev_forecast.py` and
sets `VICTRON_DEV_FORECAST=1`. Standalone Compose and release packages do not
include the provider. A supplied key or **any** saved Solcast entry always selects
real Solcast; setup errors, unloaded entries, and query failures never fall back
to test data. A Solcast setup failure leaves Victron available; finish setup from
**Settings → Devices & services → Add integration → Solcast PV Forecast**.
Existing Solcast entries and their keys/settings are preserved on every startup:
change an existing entry's key in Home Assistant's Solcast configuration UI;
editing `.env` does not replace it.

Solcast setup validates your rooftop sites against its cloud API and enables
daylight forecast updates with a default allowance of **10 API calls per day**.
Those real cloud requests consume your Solcast account quota; use your account's
actual allowance and Solcast's HA options when sharing the key with other
clients. Victron's separate five-minute forecast polling only reads Solcast's
local cache and does not fetch cloud data or consume additional API calls.

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
