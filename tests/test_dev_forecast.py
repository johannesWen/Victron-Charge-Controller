"""Dev-only provider selection, calendar coverage and public snapshot contract."""

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.victron_charge_control.const import DOMAIN
from custom_components.victron_charge_control.forecast import SolcastForecastCoordinator
from custom_components.victron_charge_control.websocket_api import websocket_solar_forecast
from dev.victron_dev_forecast import forecast_snapshot

VIENNA = ZoneInfo("Europe/Vienna")
NOW = datetime(2026, 10, 18, 10, 15, tzinfo=UTC)
MODULE = "custom_components.victron_charge_control.forecast"


@pytest.fixture
async def development(mock_hass, mock_config_entry, monkeypatch):
    monkeypatch.setenv("VICTRON_DEV_FORECAST", "1")
    monkeypatch.delenv("SOLCAST_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "dev"))
    mock_hass.loop = asyncio.get_running_loop()
    mock_hass.config.time_zone = "Europe/Vienna"
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    coordinator = SolcastForecastCoordinator(mock_hass, mock_config_entry)
    with (
        patch(f"{MODULE}.dt_util.utcnow", return_value=NOW),
        patch(f"{MODULE}.dt_util.DEFAULT_TIME_ZONE", VIENNA),
    ):
        yield SimpleNamespace(hass=mock_hass, config=mock_config_entry, coordinator=coordinator)
        await coordinator.async_shutdown()


@pytest.mark.parametrize("key", [None, "", "  \t"])
async def test_blank_or_missing_key_uses_synthetic_without_services(development, monkeypatch, key):
    if key is not None:
        monkeypatch.setenv("SOLCAST_API_KEY", key)
    await development.coordinator.async_refresh()
    snapshot = development.coordinator.data
    assert snapshot.usable and snapshot.status == "ready"
    assert "Synthetic" in snapshot.reason
    assert snapshot.source_updated_at == NOW
    assert len(snapshot.intervals) == 96
    development.hass.services.async_call.assert_not_called()
    development.hass.services.has_service.assert_not_called()


@pytest.mark.parametrize("flag,key", [(None, ""), ("0", ""), ("true", ""), ("1", "real-key-never-log")])
async def test_requires_explicit_flag_and_no_key(development, monkeypatch, flag, key, caplog):
    if flag is None:
        monkeypatch.delenv("VICTRON_DEV_FORECAST")
    else:
        monkeypatch.setenv("VICTRON_DEV_FORECAST", flag)
    monkeypatch.setenv("SOLCAST_API_KEY", key)
    await development.coordinator.async_refresh()
    assert development.coordinator.data.status == "not_detected"
    assert not development.coordinator.data.usable
    development.hass.async_add_executor_job.assert_not_called()
    assert "real-key-never-log" not in caplog.text


async def test_disabled_option_prevents_provider_and_discovery(development):
    development.config.options["use_solcast_forecast"] = False
    await development.coordinator.async_refresh()
    assert development.coordinator.data.status == "disabled"
    development.hass.config_entries.async_entries.assert_not_called()
    development.hass.async_add_executor_job.assert_not_called()


@pytest.mark.parametrize("state", [ConfigEntryState.LOADED, ConfigEntryState.NOT_LOADED, ConfigEntryState.SETUP_ERROR])
async def test_any_persisted_real_entry_prevents_synthetic_even_on_failure(development, state):
    entry = SimpleNamespace(entry_id="real-solcast", state=state)
    development.hass.config_entries.async_entries.return_value = [entry]
    development.hass.services.has_service.return_value = True
    development.hass.services.async_call.side_effect = RuntimeError("real-key-never-log")
    with (
        patch(f"{MODULE}.er.async_get"),
        patch(f"{MODULE}.er.async_entries_for_config_entry", return_value=[]),
    ):
        await development.coordinator.async_refresh()
    snapshot = development.coordinator.data
    assert snapshot.status == "unavailable" and not snapshot.usable
    assert snapshot.intervals == ()
    assert snapshot.source_entry_id == "real-solcast"
    assert "real-key-never-log" not in snapshot.reason
    development.hass.async_add_executor_job.assert_not_called()


async def test_missing_dev_mount_does_not_report_fake_success(development):
    development.hass.async_add_executor_job.side_effect = ModuleNotFoundError
    await development.coordinator.async_refresh()
    assert development.coordinator.data.status == "unavailable"
    assert not development.coordinator.data.usable
    assert not development.coordinator.data.intervals


@pytest.mark.parametrize("now,counts", [
    (NOW, [48, 48]),
    (datetime(2026, 3, 29, 8, tzinfo=UTC), [46, 48]),
    (datetime(2026, 10, 25, 8, tzinfo=UTC), [50, 48]),
    (datetime(2026, 3, 28, 8, tzinfo=UTC), [48, 46]),
    (datetime(2026, 10, 24, 8, tzinfo=UTC), [48, 50]),
])
def test_continuous_local_days_dst_and_physical_bounds(now, counts):
    snapshot = forecast_snapshot(now, VIENNA)
    intervals = snapshot.intervals
    day_counts = Counter(interval.start.astimezone(VIENNA).date() for interval in intervals)
    assert list(day_counts.values()) == counts
    assert intervals[0].start.astimezone(VIENNA).hour == 0
    assert intervals[-1].end.astimezone(VIENNA).hour == 0
    assert intervals[-1].end == snapshot.coverage_end
    assert snapshot.coverage_start == now
    assert snapshot.coverage_hours == (snapshot.coverage_end - now).total_seconds() / 3600
    assert all(left.end == right.start for left, right in zip(intervals, intervals[1:]))
    assert all(interval.start.tzinfo is UTC and interval.end - interval.start == timedelta(minutes=30) for interval in intervals)
    assert all(0 <= interval.lower_power_kw <= interval.power_kw <= 6 for interval in intervals)
    assert any(interval.power_kw > 0 for interval in intervals)
    for interval in intervals:
        hour = (interval.start + timedelta(minutes=15)).astimezone(VIENNA).hour
        if hour < 4 or hour >= 21:
            assert interval.power_kw == interval.lower_power_kw == 0
    assert forecast_snapshot(now, VIENNA) == snapshot


def test_midnight_rollover_refreshes_dates_and_source_timestamp():
    before = datetime(2026, 10, 18, 23, 59, tzinfo=VIENNA).astimezone(UTC)
    after = before + timedelta(minutes=2)
    old = forecast_snapshot(before, VIENNA)
    new = forecast_snapshot(after, VIENNA)
    assert new.source_updated_at == after > old.source_updated_at
    assert new.intervals[0].start == old.intervals[48].start
    assert new.intervals[:48] == old.intervals[48:]
    assert new.coverage_end > old.coverage_end


async def test_real_refresh_returns_websocket_ready_synthetic_snapshot(development, coordinator):
    await development.coordinator.async_refresh()
    coordinator.forecast_coordinator = development.coordinator
    development.hass.data[DOMAIN] = {"entry": coordinator}
    connection = MagicMock()
    connection.user.is_active = connection.user.is_admin = True
    with patch("custom_components.victron_charge_control.websocket_api.dt_util.utcnow", return_value=NOW):
        websocket_solar_forecast(development.hass, connection, {"id": 1})
    connection.send_error.assert_not_called()
    payload = json.loads(json.dumps(connection.send_result.call_args.args[1]))
    assert payload["usable"] and payload["status"] == "ready"
    assert "Synthetic" in payload["reason"]
    assert payload["source_updated_at"] == NOW.isoformat()
    assert len(payload["intervals"]) == 96
    assert [day["date"] for day in payload["days"]] == ["2026-10-18", "2026-10-19"]
    assert all(0 <= interval["pv_estimate10"] <= interval["pv_estimate"] for interval in payload["intervals"])
    development.hass.services.async_call.assert_not_called()
