"""Render the shipped dummy EPEX feed in Home Assistant's template runtime."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.template.sensor import SENSOR_YAML_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import MAX_TEMPLATE_OUTPUT
from homeassistant.util import dt as dt_util, yaml as yaml_util

from custom_components.victron_charge_control.const import MODE_AUTO
from custom_components.victron_charge_control.epex import normalize_price_intervals
from custom_components.victron_charge_control.planning import calculate_auto_schedule
from dev.backfill_cost_statistics import price_for_hour

LOCAL = ZoneInfo("Europe/Berlin")


@pytest.fixture
async def feed(tmp_path, monkeypatch):
    config = yaml_util.load_yaml(str(Path(__file__).parents[1] / "dev/configuration.yaml"))
    sensor = next(
        sensor for block in config["template"] for sensor in block.get("sensor", [])
        if sensor["unique_id"] == "dummy_epex_spot"
    )
    hass = HomeAssistant(str(tmp_path))
    hass.config.time_zone = config["homeassistant"]["time_zone"]
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", LOCAL)
    sensor = SENSOR_YAML_SCHEMA(sensor)

    def render(at, history_days=30):
        now = datetime.fromisoformat(at).astimezone(LOCAL)
        monkeypatch.setattr(dt_util, "now", lambda: now)
        hass.states.async_set("input_number.energy_history_days", str(history_days))
        results = []
        for template in (sensor["state"], sensor["attributes"]["data"]):
            template.hass = hass
            info = template.async_render_to_info()
            results.append(info.result())
            assert info.has_time  # HA refreshes now()-dependent templates each minute.
        return now, *results

    yield hass, render
    await hass.async_stop()


def utc_bounds(entry):
    start, end = (datetime.fromisoformat(entry[key]) for key in ("start_time", "end_time"))
    assert start.utcoffset() is not None and end.utcoffset() is not None
    return start.astimezone(UTC), end.astimezone(UTC)


@pytest.mark.parametrize("day,counts", [
    ("2026-05-02", [96, 96]),
    ("2026-03-28", [96, 92]),
    ("2026-03-29", [92, 96]),
    ("2026-10-24", [96, 100]),
    ("2026-10-25", [100, 96]),
])
async def test_today_and_tomorrow_cover_actual_local_days(feed, day, counts):
    _, render = feed
    now, _, entries = render(f"{day}T12:00:00+00:00", 0)
    by_day = defaultdict(list)
    bounds = [utc_bounds(entry) for entry in entries]
    assert len({start for start, _ in bounds}) == sum(counts)
    assert all((end-start).total_seconds() == 900 for start, end in bounds)
    assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))
    for entry in entries:
        by_day[datetime.fromisoformat(entry["start_time"]).astimezone(LOCAL).date()].append(entry)
        assert isfinite(entry["price_per_kwh"])
    assert [len(by_day[now.date()+timedelta(days=d)]) for d in range(2)] == counts
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    assert bounds[0][0] == midnight.astimezone(UTC)
    assert bounds[-1][1] == (midnight+timedelta(days=2)).astimezone(UTC)
    normalized = normalize_price_intervals({"data": entries})
    assert len(normalized) == len(entries)
    assert [(item.start, item.end) for item in normalized] == bounds


@pytest.mark.parametrize("at", [
    "2026-05-02T18:14:59+02:00", "2026-05-02T18:15:00+02:00",
    "2026-05-02T18:29:59+02:00", "2026-05-02T18:30:00+02:00",
    "2026-05-02T18:44:59+02:00", "2026-05-02T18:45:00+02:00",
    "2026-05-02T23:59:59+02:00", "2026-05-03T00:00:00+02:00",
    "2026-03-29T01:59:59+01:00", "2026-03-29T03:00:00+02:00",
    "2026-10-25T02:15:00+02:00", "2026-10-25T02:15:00+01:00",
])
async def test_current_state_matches_containing_quarter(feed, at):
    _, render = feed
    now, state, entries = render(at, 0)
    current = [entry for entry in entries if utc_bounds(entry)[0] <= now.astimezone(UTC) < utc_bounds(entry)[1]]
    assert len(current) == 1
    assert state == current[0]["price_per_kwh"]
    if now.hour == 18:
        assert 0.415 <= state <= 0.427  # Published/backfill profile, formerly 0.321 in state.


async def test_quarters_vary_with_zero_mean_offsets_and_negative_tomorrow(feed):
    _, render = feed
    now, _, entries = render("2026-05-02T12:00:00+02:00", 0)
    by_hour = defaultdict(list)
    for entry in entries:
        start = datetime.fromisoformat(entry["start_time"]).astimezone(LOCAL)
        by_hour[(start.date(), start.hour)].append(entry["price_per_kwh"])
    for (day, hour), prices in by_hour.items():
        assert len(set(prices)) == 4
        if day == now.date():
            assert sum(prices)/4 == pytest.approx(price_for_hour(0, hour))
        elif hour < 2:
            assert all(price < 0 for price in prices)


@pytest.mark.parametrize("day,hours", [("2026-03-30", 23), ("2026-10-26", 25)])
async def test_historical_dst_day_has_valid_hourly_intervals(feed, day, hours):
    _, render = feed
    now, _, entries = render(f"{day}T12:00:00+00:00", 1)
    history = [entry for entry in entries if datetime.fromisoformat(entry["start_time"]).date() < now.date()]
    assert len(history) == hours
    bounds = [utc_bounds(entry) for entry in history]
    assert all((end-start).total_seconds() == 3600 for start, end in bounds)
    assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))
    assert len({start for start, _ in bounds}) == hours


async def test_default_history_fits_ha_output_limit_and_planner_uses_eight_quarters(feed):
    hass, render = feed
    now, state, entries = render("2026-11-04T12:00:00+01:00")
    assert len(str(entries)) < MAX_TEMPLATE_OUTPUT
    history = [entry for entry in entries if datetime.fromisoformat(entry["start_time"]).date() < now.date()]
    assert len(history) == 30*24+1  # Includes the extra autumn hour.
    for entry in history:
        start = datetime.fromisoformat(entry["start_time"]).astimezone(LOCAL)
        assert (utc_bounds(entry)[1]-utc_bounds(entry)[0]).total_seconds() == 3600
        assert entry["price_per_kwh"] == price_for_hour((start.date()-now.date()).days, start.hour)
    assert all(isfinite(entry["price_per_kwh"]) for entry in entries)
    assert len(normalize_price_intervals({"data": entries})) == len(entries)
    hass.states.async_set("sensor.epex_spot_price", str(state), {"data": entries})
    charge, discharge = calculate_auto_schedule(
        hass, epex_spot_entity="sensor.epex_spot_price", control_mode=MODE_AUTO,
        cheapest_hours=2, expensive_hours=0, charge_price_threshold=100,
        discharge_price_threshold=0, blocked_charging_hours=[],
        blocked_discharging_hours=[], pv_charge_hours=[], now=now,
    )
    assert len(charge) == 8 and discharge == []
    assert all((end-start).total_seconds() == 900 and end > now.astimezone(UTC) for start, end in charge)
    assert sum((end-start).total_seconds() for start, end in charge) == 2*3600
