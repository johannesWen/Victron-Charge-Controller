"""Cache contract, discovery, temporal validation and optional-source lifecycle."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.victron_charge_control.forecast import (
    ForecastInterval,
    SolcastForecastCoordinator,
)

NOW = datetime(2026, 10, 15, 10, 15, tzinfo=UTC)
VIENNA = ZoneInfo("Europe/Vienna")
MODULE = "custom_components.victron_charge_control.forecast"


def forecast_response(now: datetime = NOW, power: float = 2.0) -> dict:
    """Build the upstream cache response across two local calendar days."""
    start = now.astimezone(VIENNA).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=2)).astimezone(UTC)
    cursor = start.astimezone(UTC)
    records = []
    while cursor < end:
        records.append({
            "period_start": cursor.astimezone(VIENNA).isoformat(),
            "pv_estimate": power, "pv_estimate10": 1.0, "pv_estimate90": 3.0,
        })
        cursor += timedelta(minutes=30)
    return {"data": records}


@pytest.fixture
async def source(mock_hass, mock_config_entry):
    """Supply registry ownership and real asyncio scheduling around mocked HA."""
    mock_hass.loop = asyncio.get_running_loop()
    mock_hass.is_stopping = False
    mock_config_entry.pref_disable_polling = False
    entry = SimpleNamespace(entry_id="solcast-entry", state=ConfigEntryState.LOADED)
    entities = [
        SimpleNamespace(
            entity_id="sensor.renamed_solcast_timestamp", unique_id="lastupdated",
            platform="solcast_solar", config_entry_id=entry.entry_id, disabled_by=None,
        ),
        SimpleNamespace(
            entity_id="sensor.disabled_details", unique_id="total_kwh_forecast_today",
            platform="solcast_solar", config_entry_id=entry.entry_id, disabled_by="user",
        ),
        SimpleNamespace(
            entity_id="sensor.unrelated", unique_id="last_updated",
            platform="other_integration", config_entry_id=entry.entry_id, disabled_by=None,
        ),
    ]
    mock_hass.config_entries.async_entries.return_value = [entry]
    mock_hass.services.has_service.return_value = True
    mock_hass.services.async_call.return_value = forecast_response()
    states = {"sensor.renamed_solcast_timestamp": SimpleNamespace(state=(NOW - timedelta(hours=1)).isoformat())}
    mock_hass.states.get.side_effect = states.get
    tasks = []

    def background(coro, name):
        task = asyncio.create_task(coro, name=name)
        tasks.append(task)
        return task

    mock_hass.async_create_background_task.side_effect = background
    mock_config_entry.title = "Victron"
    mock_config_entry.async_create_background_task = lambda hass, coro, **kwargs: background(coro, kwargs["name"])
    coord = SolcastForecastCoordinator(mock_hass, mock_config_entry)
    with (
        patch(f"{MODULE}.er.async_get", return_value=MagicMock()),
        patch(f"{MODULE}.er.async_entries_for_config_entry", side_effect=lambda registry, entry_id: [entity for entity in entities if entity.config_entry_id == entry_id]),
        patch(f"{MODULE}.dt_util.utcnow", return_value=NOW) as clock,
        patch(f"{MODULE}.dt_util.as_local", side_effect=lambda value: value.astimezone(VIENNA)),
    ):
        yield SimpleNamespace(
            coordinator=coord, hass=mock_hass, config=mock_config_entry,
            entry=entry, entities=entities, states=states, clock=clock, tasks=tasks,
        )
        await coord.async_shutdown()


async def refresh(source):
    """Run the public coordinator refresh and require readable diagnostics."""
    await source.coordinator.async_refresh()
    assert source.coordinator.last_update_success
    return source.coordinator.data


async def test_initialized_snapshot_and_disabled_default(source):
    assert source.coordinator.data.status == "not_detected"
    assert source.coordinator.data.intervals == ()
    assert not source.coordinator.data.usable
    source.config.options["use_solcast_forecast"] = False
    snapshot = await refresh(source)
    assert snapshot.status == "disabled"
    source.hass.services.async_call.assert_not_called()
    source.hass.config_entries.async_entries.assert_not_called()


async def test_disabled_snapshot_initialized_without_refresh(source):
    source.config.options["use_solcast_forecast"] = False
    coord = SolcastForecastCoordinator(source.hass, source.config)
    assert coord.data.status == "disabled"
    await coord.async_shutdown()


async def test_cached_action_discovery_and_energy(source):
    snapshot = await refresh(source)
    assert snapshot.status == "ready"
    assert snapshot.usable
    assert snapshot.reason is None
    assert snapshot.source_entry_id == source.entry.entry_id
    assert snapshot.discovered_entity_ids == ("sensor.disabled_details", "sensor.renamed_solcast_timestamp")
    assert snapshot.source_updated_at == NOW - timedelta(hours=1)
    assert snapshot.coverage_start == NOW
    assert snapshot.coverage_end == datetime(2026, 10, 16, 22, tzinfo=UTC)
    assert snapshot.coverage_hours == 35.75
    interval = snapshot.intervals[0]
    assert interval.start.tzinfo is UTC
    assert interval.end - interval.start == timedelta(minutes=30)
    assert interval.power_kw == 2.0
    assert interval.lower_power_kw == 1.0
    assert interval.upper_power_kw == 3.0
    assert interval.energy_kwh == 1.0
    assert interval.start == datetime(2026, 10, 14, 22, tzinfo=UTC)
    assert len(snapshot.intervals) == 96
    source.hass.services.async_call.assert_awaited_once_with(
        "solcast_solar", "query_forecast_data",
        {"start_date_time": datetime(2026, 10, 15, tzinfo=VIENNA),
         "end_date_time": datetime(2026, 10, 17, tzinfo=VIENNA),
         "site": "all", "undampened": False},
        blocking=True, return_response=True,
    )
    assert source.entities[1].disabled_by == "user"


async def test_representative_upstream_fixture(source):
    """Fixture follows actions.py/get_forecast_list at upstream 638375cd4c4d."""
    response = json.loads((Path(__file__).parent / "fixtures/solcast_query_forecast.json").read_text())
    source.hass.services.async_call.return_value = response
    snapshot = await refresh(source)
    assert snapshot.status == "ready"
    assert snapshot.intervals[24].power_kw == 4.6812
    assert snapshot.intervals[-1].power_kw == 0.0
    # HA's internal service response contains datetime values and a tuple, too.
    response["data"] = tuple({**row, "period_start": datetime.fromisoformat(row["period_start"])} for row in response["data"])
    assert (await refresh(source)).status == "ready"


async def test_install_delayed_load_rename_removal_and_recovery(source):
    source.hass.config_entries.async_entries.return_value = []
    assert (await refresh(source)).status == "not_detected"
    source.hass.config_entries.async_entries.return_value = [source.entry]
    source.entry.state = ConfigEntryState.SETUP_IN_PROGRESS
    assert (await refresh(source)).status == "unavailable"
    source.entry.state = ConfigEntryState.LOADED
    assert (await refresh(source)).status == "ready"
    source.entities[0].entity_id = "sensor.freshness_renamed_again"
    source.states[source.entities[0].entity_id] = source.states.pop("sensor.renamed_solcast_timestamp")
    snapshot = await refresh(source)
    assert snapshot.status == "ready"
    assert "sensor.freshness_renamed_again" in snapshot.discovered_entity_ids
    source.hass.config_entries.async_entries.return_value = []
    snapshot = await refresh(source)
    assert snapshot.status == "not_detected"
    assert not snapshot.usable and snapshot.intervals == ()
    assert snapshot.source_updated_at is not None
    source.hass.config_entries.async_entries.return_value = [source.entry]
    source.entry.state = ConfigEntryState.NOT_LOADED
    assert (await refresh(source)).status == "unavailable"
    source.entry.state = ConfigEntryState.LOADED
    assert (await refresh(source)).status == "ready"


async def test_multiple_loaded_sources_are_ambiguous(source):
    source.hass.config_entries.async_entries.return_value.append(
        SimpleNamespace(entry_id="another-solcast", state=ConfigEntryState.LOADED)
    )
    snapshot = await refresh(source)
    assert snapshot.status == "unavailable"
    assert "ambiguous" in snapshot.reason
    source.hass.services.async_call.assert_not_called()


async def test_changed_source_does_not_inherit_previous_timestamp(source):
    assert (await refresh(source)).source_updated_at is not None
    source.entry.entry_id = "replacement-solcast"
    source.entities.clear()
    snapshot = await refresh(source)
    assert snapshot.source_entry_id == "replacement-solcast"
    assert snapshot.status == "unavailable"
    assert snapshot.source_updated_at is None


@pytest.mark.parametrize("failure", ["service_missing", "service_error", "unexpected_error"])
async def test_failure_clears_previous_forecast_and_recovers(source, failure):
    valid = await refresh(source)
    if failure == "service_missing":
        source.hass.services.has_service.return_value = False
    elif failure == "service_error":
        source.hass.services.async_call.side_effect = RuntimeError("secret API credential must not be exposed")
    else:
        source.hass.config_entries.async_entries.side_effect = RuntimeError("registry failure")
    snapshot = await refresh(source)
    assert snapshot.status == "unavailable"
    assert not snapshot.usable and snapshot.intervals == ()
    assert snapshot.source_updated_at == valid.source_updated_at
    assert "secret" not in snapshot.reason
    source.hass.services.has_service.return_value = True
    source.hass.services.async_call.side_effect = None
    source.hass.config_entries.async_entries.side_effect = None
    assert (await refresh(source)).status == "ready"


@pytest.mark.parametrize("value", [None, "unknown", "unavailable", "2026-10-15T09:00:00", "not-a-date"])
async def test_missing_freshness_does_not_reuse_diagnostic_timestamp(source, value):
    previous = await refresh(source)
    if value is None:
        source.states.clear()
    else:
        state = source.states[source.entities[0].entity_id]
        state.state = value
        state.last_changed = NOW
        state.last_updated = NOW
    snapshot = await refresh(source)
    assert snapshot.status == "unavailable"
    assert snapshot.source_updated_at == previous.source_updated_at
    assert not snapshot.usable and not snapshot.intervals


@pytest.mark.parametrize("unique_id", ["lastupdated", "last_updated"])
async def test_freshness_uses_owned_unique_id(source, unique_id):
    source.entities[0].unique_id = unique_id
    assert (await refresh(source)).status == "ready"
    source.entities[0].unique_id = "unrelated_lastupdated"
    assert (await refresh(source)).status == "unavailable"
    source.entities[0].unique_id = unique_id
    source.entities[0].disabled_by = "user"
    assert (await refresh(source)).status == "unavailable"


@pytest.mark.parametrize("age,status", [(36, "ready"), (36.001, "stale"), (-0.1, "invalid_data")])
async def test_freshness_boundary(source, age, status):
    source.states[source.entities[0].entity_id].state = (NOW - timedelta(hours=age)).isoformat()
    snapshot = await refresh(source)
    assert snapshot.status == status
    assert snapshot.usable == (status == "ready")
    if not snapshot.usable:
        assert snapshot.intervals == ()


@pytest.mark.parametrize("response", [None, [], {}, {"data": None}, {"data": {}}, {"data": "bad"}, {"data": [None]}])
async def test_malformed_response(source, response):
    source.hass.services.async_call.return_value = response
    snapshot = await refresh(source)
    assert snapshot.status == "invalid_data"
    assert not snapshot.usable and snapshot.intervals == ()


@pytest.mark.parametrize("key,value", [
    ("period_start", None), ("period_start", "invalid"),
    ("period_start", "2026-10-15T10:00:00"), ("period_start", 1792058400),
    ("pv_estimate", None), ("pv_estimate", "2.0"), ("pv_estimate", True),
    ("pv_estimate", -1), ("pv_estimate", float("nan")),
    ("pv_estimate", float("inf")), ("pv_estimate", 10**400),
    ("pv_estimate10", -1), ("pv_estimate90", float("inf")),
])
async def test_invalid_interval_values(source, key, value):
    source.hass.services.async_call.return_value["data"][25][key] = value
    snapshot = await refresh(source)
    assert snapshot.status == "invalid_data"
    assert snapshot.intervals == ()


async def test_optional_estimates_and_nighttime_zero_are_valid(source):
    response = forecast_response(power=0.0)
    for row in response["data"]:
        row.pop("pv_estimate10")
        row["pv_estimate90"] = None
    source.hass.services.async_call.return_value = response
    snapshot = await refresh(source)
    assert snapshot.status == "ready"
    assert all(interval.power_kw == 0 for interval in snapshot.intervals)
    assert all(interval.lower_power_kw is None and interval.upper_power_kw is None for interval in snapshot.intervals)


@pytest.mark.parametrize("conflict", [False, True])
async def test_sort_and_duplicate_handling(source, conflict):
    records = source.hass.services.async_call.return_value["data"]
    duplicate = copy.deepcopy(records[25])
    if conflict:
        duplicate["pv_estimate90"] = 4.0
    records.append(duplicate)
    records.reverse()
    snapshot = await refresh(source)
    assert snapshot.status == ("invalid_data" if conflict else "ready")
    if not conflict:
        assert len({interval.start for interval in snapshot.intervals}) == len(snapshot.intervals)
        assert list(snapshot.intervals) == sorted(snapshot.intervals, key=lambda interval: interval.start)


async def test_overlapping_intervals_rejected(source):
    row = copy.deepcopy(source.hass.services.async_call.return_value["data"][25])
    row["period_start"] = (datetime.fromisoformat(row["period_start"]) + timedelta(minutes=5)).isoformat()
    source.hass.services.async_call.return_value["data"].append(row)
    assert (await refresh(source)).status == "invalid_data"


@pytest.mark.parametrize("gap", ["current", "future", "empty", "past_only"])
async def test_gaps_clear_intervals_but_keep_continuous_coverage(source, gap):
    records = source.hass.services.async_call.return_value["data"]
    current = next(index for index, row in enumerate(records) if datetime.fromisoformat(row["period_start"]).astimezone(UTC) == NOW.replace(minute=0))
    if gap == "current":
        records.pop(current)
    elif gap == "future":
        records.pop(current + 2)
    elif gap == "empty":
        records.clear()
    else:
        del records[current:]
    snapshot = await refresh(source)
    assert snapshot.status == "incomplete"
    assert snapshot.intervals == ()
    assert not snapshot.usable
    if gap == "future":
        assert snapshot.coverage_hours == 0.75
        assert snapshot.coverage_start == NOW
    else:
        assert snapshot.coverage_hours == 0
        assert snapshot.coverage_start is None and snapshot.coverage_end is None


@pytest.mark.parametrize("now,count,hours", [
    (datetime(2026, 3, 28, 23, tzinfo=UTC), 94, 47),
    (datetime(2026, 10, 24, 22, tzinfo=UTC), 98, 49),
])
async def test_vienna_dst_horizons_and_energy(source, now, count, hours):
    source.clock.return_value = now
    source.states[source.entities[0].entity_id].state = (now - timedelta(hours=1)).isoformat()
    source.hass.services.async_call.return_value = forecast_response(now)
    snapshot = await refresh(source)
    assert snapshot.status == "ready"
    assert len(snapshot.intervals) == count
    assert snapshot.coverage_hours == hours
    assert sum(interval.energy_kwh for interval in snapshot.intervals) == hours * 2
    params = source.hass.services.async_call.call_args.args[2]
    assert params["start_date_time"].hour == params["end_date_time"].hour == 0
    assert params["start_date_time"].utcoffset() != params["end_date_time"].utcoffset()


async def test_coverage_caps_at_tomorrows_end(source):
    response = source.hass.services.async_call.return_value
    end = datetime.fromisoformat(response["data"][-1]["period_start"]) + timedelta(minutes=30)
    response["data"].append({"period_start": end, "pv_estimate": 2})
    snapshot = await refresh(source)
    assert snapshot.coverage_hours == 35.75
    assert snapshot.intervals[-1].end == snapshot.coverage_end


async def test_background_startup_does_not_block_and_shutdown_cancels_query(source):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_query(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    source.hass.services.async_call.side_effect = slow_query
    await asyncio.wait_for(source.coordinator.async_setup(), timeout=0.1)
    await asyncio.wait_for(entered.wait(), timeout=0.1)
    assert source.coordinator.update_interval == timedelta(minutes=5)
    assert source.coordinator.data.status == "not_detected"
    await source.coordinator.async_setup()
    assert source.hass.async_create_background_task.call_count == 1
    await source.coordinator.async_shutdown()
    assert cancelled.is_set()
    assert all(task.done() for task in source.tasks)
    assert not source.coordinator._refresh_tasks
    assert source.coordinator._unsub_refresh is None
    await source.coordinator.async_shutdown()


async def test_shutdown_cancels_later_refresh_with_diagnostic_listener(source):
    await source.coordinator.async_setup()
    await source.tasks[0]
    assert source.coordinator._unsub_refresh is not None
    remove_listener = source.coordinator.async_add_listener(lambda: None)
    entered = asyncio.Event()

    async def slow_query(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    source.hass.services.async_call.side_effect = slow_query
    task = asyncio.create_task(source.coordinator.async_refresh())
    await entered.wait()
    await source.coordinator.async_shutdown()
    assert task.cancelled()
    assert source.coordinator._unsub_refresh is None
    remove_listener()
    source.hass.services.async_call.reset_mock()
    await source.coordinator.async_refresh()
    source.hass.services.async_call.assert_not_called()


async def test_shutdown_before_startup_prevents_new_tasks(source):
    await source.coordinator.async_shutdown()
    await source.coordinator.async_setup()
    source.hass.async_create_background_task.assert_not_called()


async def test_duc_timer_refreshes_and_rearms_without_diagnostic_entities(source):
    await source.coordinator.async_setup()
    await source.tasks[0]
    timer = source.coordinator._unsub_refresh.__self__
    assert 298 < timer.when() - source.hass.loop.time() < 301
    callback, args = timer._callback, timer._args
    timer.cancel()
    callback(*args)
    await source.tasks[-1]
    assert source.hass.services.async_call.await_count == 2
    assert source.coordinator._unsub_refresh is not None
    assert source.coordinator.data.status == "ready"
    await source.coordinator.async_shutdown()
    assert source.coordinator._unsub_refresh is None


def test_interval_energy_uses_actual_duration():
    interval = ForecastInterval(NOW, NOW + timedelta(minutes=30), 2.0)
    assert interval.energy_kwh == 1.0
