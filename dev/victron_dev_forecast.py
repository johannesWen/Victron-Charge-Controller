"""Synthetic PV for the devcontainer only; no Solcast API or network access."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta, tzinfo

from custom_components.victron_charge_control.forecast import (
    ForecastInterval,
    ForecastSnapshot,
)

logging.getLogger(__name__).warning(
    "Synthetic development PV forecast enabled; this is test data, not Solcast"
)


def forecast_snapshot(now: datetime, zone: tzinfo) -> ForecastSnapshot:
    """Generate deterministic daylight curves for today and tomorrow on each poll."""
    now = now.astimezone(UTC)
    start = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=2)).astimezone(UTC)
    cursor = start.astimezone(UTC)
    intervals = []
    while cursor < end:
        midpoint = (cursor + timedelta(minutes=15)).astimezone(zone)
        day = midpoint.timetuple().tm_yday
        season = math.sin(2 * math.pi * (day - 80) / 365.25)
        daylight = 12 + 4 * season
        hour = midpoint.hour + midpoint.minute / 60
        phase = (hour - (12.5 - daylight / 2)) / daylight
        cloud = 0.78 + 0.16 * math.sin(day * 1.7)
        power = round(
            6 * (0.8 + 0.2 * season) * cloud * math.sin(math.pi * phase) ** 1.5,
            4,
        ) if 0 < phase < 1 else 0.0
        interval_end = cursor + timedelta(minutes=30)
        intervals.append(ForecastInterval(cursor, interval_end, power, round(power * 0.65, 4)))
        cursor = interval_end
    return ForecastSnapshot(
        intervals=tuple(intervals), source_entry_id="synthetic-development",
        source_updated_at=now, coverage_start=now, coverage_end=end,
        coverage_hours=(end - now).total_seconds() / 3600,
        status="ready", usable=True,
        reason="Synthetic development PV forecast (not Solcast)",
    )
