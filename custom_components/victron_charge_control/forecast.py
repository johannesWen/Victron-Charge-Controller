"""Optional, cache-only Solcast forecast ingestion, independent of battery control."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)
_SOLCAST_DOMAIN = "solcast_solar"
_HALF_HOUR = timedelta(minutes=30)
_MAX_AGE = timedelta(hours=36)


@dataclass(frozen=True)
class ForecastInterval:
    """Average power in kW over one UTC half-hour interval."""

    start: datetime
    end: datetime
    power_kw: float
    lower_power_kw: float | None = None
    upper_power_kw: float | None = None

    @property
    def energy_kwh(self) -> float:
        """Return central energy, preserving the source's dampening and limits."""
        return self.power_kw * (self.end - self.start).total_seconds() / 3600


@dataclass(frozen=True)
class ForecastSnapshot:
    """Forecast diagnostics and validated intervals; unusable snapshots have none."""

    intervals: tuple[ForecastInterval, ...] = ()
    source_entry_id: str | None = None
    discovered_entity_ids: tuple[str, ...] = ()
    source_updated_at: datetime | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_hours: float = 0.0
    status: str = "not_detected"
    usable: bool = False
    reason: str | None = "Solcast discovery has not run"


def _utc_timestamp(value: Any) -> datetime:
    """Validate a source timestamp without assuming a timezone for naive values."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as err:
            raise ValueError("timestamp is not a valid datetime") from err
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _power(value: Any) -> float:
    """Validate a required numeric power estimate at the source boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("power estimate must be numeric")
    try:
        value = float(value)
    except OverflowError as err:
        raise ValueError("power estimate must be finite and nonnegative") from err
    if not math.isfinite(value) or value < 0:
        raise ValueError("power estimate must be finite and nonnegative")
    return value


def _parse_intervals(response: Any) -> tuple[ForecastInterval, ...]:
    """Read the public query action's period_start/pv_estimate cache contract."""
    if not isinstance(response, Mapping) or not isinstance(
        response.get("data"), (list, tuple)
    ):
        raise ValueError("response must contain a data list")
    by_start: dict[datetime, ForecastInterval] = {}
    for record in response["data"]:
        if not isinstance(record, Mapping):
            raise ValueError("forecast interval must be an object")
        start = _utc_timestamp(record.get("period_start"))
        interval = ForecastInterval(
            start=start,
            end=start + _HALF_HOUR,
            power_kw=_power(record.get("pv_estimate")),
            lower_power_kw=(
                _power(record["pv_estimate10"])
                if record.get("pv_estimate10") is not None else None
            ),
            upper_power_kw=(
                _power(record["pv_estimate90"])
                if record.get("pv_estimate90") is not None else None
            ),
        )
        if start in by_start and by_start[start] != interval:
            raise ValueError("conflicting duplicate forecast intervals")
        by_start[start] = interval
    intervals = tuple(by_start[start] for start in sorted(by_start))
    if any(right.start < left.end for left, right in zip(intervals, intervals[1:])):
        raise ValueError("forecast intervals overlap")
    return intervals


class SolcastForecastCoordinator(DataUpdateCoordinator[ForecastSnapshot]):
    """Read only Solcast's local cache, with its own five-minute lifecycle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize diagnostics immediately, before any optional source work."""
        super().__init__(
            hass, _LOGGER, config_entry=entry, name="Solcast forecast",
            update_interval=timedelta(minutes=5),
        )
        self._entry = entry
        self.data = ForecastSnapshot()
        if not entry.options.get("use_solcast_forecast", True):
            self.data = replace(self.data, status="disabled", reason="Solcast forecast is disabled")
        self._startup_task: asyncio.Task | None = None
        self._refresh_tasks: set[asyncio.Task] = set()
        self._unsub_polling: Callable[[], None] | None = None
        self._stopping = False

    async def async_setup(self) -> None:
        """Start polling and a background first refresh without delaying control."""
        if self._unsub_polling is not None or self._stopping:
            return
        # Keep polling even when all diagnostic entities are disabled.
        self._unsub_polling = self.async_add_listener(lambda: None)
        self._startup_task = self.hass.async_create_background_task(
            self.async_refresh(), "Solcast forecast startup"
        )

    async def async_shutdown(self) -> None:
        """Cancel polling and await cancellation of startup and active queries."""
        self._stopping = True
        if self._unsub_polling is not None:
            self._unsub_polling()
            self._unsub_polling = None
        tasks = self._refresh_tasks.copy()
        if self._startup_task is not None:
            tasks.add(self._startup_task)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._startup_task = None
        # In-flight DUC refreshes can reschedule themselves in their finally block.
        await super().async_shutdown()

    async def _async_update_data(self) -> ForecastSnapshot:
        """Translate optional-source failures into readable, cleared diagnostics."""
        if self._stopping:
            return replace(self.data, intervals=(), usable=False)
        task = asyncio.current_task()
        self._refresh_tasks.add(task)
        try:
            return await self._async_read_forecast()
        except Exception:
            # Optional integration internals must never retain usable old forecasts.
            return replace(
                self.data, intervals=(), usable=False, coverage_start=None,
                coverage_end=None, coverage_hours=0.0, status="unavailable",
                reason="Solcast forecast refresh failed",
            )
        finally:
            self._refresh_tasks.discard(task)

    async def _async_read_forecast(self) -> ForecastSnapshot:
        """Rediscover ownership, query the cache, and assess the local horizon."""
        snapshot = ForecastSnapshot(source_updated_at=self.data.source_updated_at)
        if not self._entry.options.get("use_solcast_forecast", True):
            return replace(snapshot, status="disabled", reason="Solcast forecast is disabled")

        entries = sorted(
            self.hass.config_entries.async_entries(_SOLCAST_DOMAIN),
            key=lambda entry: entry.entry_id,
        )
        if not entries:
            return replace(snapshot, reason="Solcast integration is not installed")
        registry = er.async_get(self.hass)
        entities = [
            entity for entry in entries
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
            if entity.platform == _SOLCAST_DOMAIN
        ]
        loaded = [entry for entry in entries if entry.state is ConfigEntryState.LOADED]
        source = loaded[0] if loaded else entries[0]
        snapshot = replace(
            snapshot, source_entry_id=source.entry_id,
            discovered_entity_ids=tuple(sorted(entity.entity_id for entity in entities)),
        )
        if source.entry_id != self.data.source_entry_id:
            snapshot = replace(snapshot, source_updated_at=None)
        if len(loaded) != 1:
            return replace(
                snapshot, status="unavailable",
                reason=("Solcast integration is not loaded" if not loaded
                        else "Multiple loaded Solcast entries make the cached source ambiguous"),
            )

        updated_at = None
        for entity in entities:
            if (entity.config_entry_id != source.entry_id
                    or entity.unique_id not in ("lastupdated", "last_updated")
                    or entity.disabled_by is not None):
                continue
            state = self.hass.states.get(entity.entity_id)
            if state is not None:
                try:
                    timestamp = _utc_timestamp(state.state)
                except (ValueError, OverflowError):
                    continue
                updated_at = max(updated_at, timestamp) if updated_at else timestamp
        if updated_at is not None:
            snapshot = replace(snapshot, source_updated_at=updated_at)

        if not self.hass.services.has_service(_SOLCAST_DOMAIN, "query_forecast_data"):
            return replace(snapshot, status="unavailable", reason="Solcast cached forecast action is unavailable")

        now = dt_util.utcnow()
        local_now = dt_util.as_local(now)
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=2)
        try:
            async with asyncio.timeout(30):
                response = await self.hass.services.async_call(
                    _SOLCAST_DOMAIN, "query_forecast_data",
                    {"start_date_time": start, "end_date_time": end,
                     "site": "all", "undampened": False},
                    blocking=True, return_response=True,
                )
        except Exception:
            return replace(snapshot, status="unavailable", reason="Solcast cached forecast query failed")
        try:
            intervals = _parse_intervals(response)
        except (ValueError, OverflowError):
            return replace(snapshot, status="invalid_data", reason="Solcast returned invalid forecast intervals")

        horizon = end.astimezone(UTC)
        cursor = now
        for interval in intervals:
            if interval.end <= cursor:
                continue
            if interval.start > cursor or cursor >= horizon:
                break
            cursor = min(interval.end, horizon)
        if cursor > now:
            snapshot = replace(
                snapshot, coverage_start=now, coverage_end=cursor,
                coverage_hours=(cursor - now).total_seconds() / 3600,
            )
        if updated_at is None:
            return replace(snapshot, status="unavailable", reason="Solcast source update timestamp is unavailable")
        if updated_at > now:
            return replace(snapshot, status="invalid_data", reason="Solcast source update timestamp is in the future")
        if now - updated_at > _MAX_AGE:
            return replace(snapshot, status="stale", reason="Solcast source update is older than 36 hours")
        if cursor < horizon:
            return replace(snapshot, status="incomplete", reason="Forecast does not continuously cover now through tomorrow")
        return replace(
            snapshot, intervals=tuple(
                interval for interval in intervals
                if interval.start < horizon and interval.end > start.astimezone(UTC)
            ),
            status="ready", usable=True, reason=None,
        )
