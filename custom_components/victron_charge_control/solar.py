"""Solar surplus sampling helpers.

Extracted from ``coordinator.py`` to keep that file focused on
orchestration. The sampling logic is a pure function that mutates a
caller-provided ``deque`` of ``(timestamp, value)`` samples and returns
the recomputed 15-minute sliding mean. Negative values are clamped to
zero, unavailable or non-numeric entity states are silently skipped.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any

SOLAR_WINDOW_MINUTES = 15


def sample_solar_surplus(
    hass: Any,
    entity_id: str | None,
    samples: deque[tuple[datetime, float]],
    now: datetime | None = None,
) -> float | None:
    """Append a solar surplus sample and recompute the sliding mean.

    ``samples`` is mutated in place — the new reading is appended and
    entries older than ``SOLAR_WINDOW_MINUTES`` are popped from the
    left. The returned value is the mean of the kept samples, or
    ``None`` if the deque is empty.
    """
    if entity_id is None:
        return _recompute_mean(samples)

    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown"):
        return _recompute_mean(samples)

    try:
        value = float(state.state)
    except (ValueError, TypeError):
        return _recompute_mean(samples)

    if value < 0.0:
        value = 0.0

    current_now = now if now is not None else _now()
    samples.append((current_now, value))

    cutoff = current_now - timedelta(minutes=SOLAR_WINDOW_MINUTES)
    while samples and samples[0][0] < cutoff:
        samples.popleft()

    return _recompute_mean(samples)


def _recompute_mean(samples: deque[tuple[datetime, float]]) -> float | None:
    if not samples:
        return None
    return sum(v for _, v in samples) / len(samples)


def _now() -> datetime:
    from homeassistant.util import dt as dt_util

    return dt_util.now()
