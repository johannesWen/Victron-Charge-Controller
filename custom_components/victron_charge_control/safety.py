"""Safety watchdog helpers.

Extracted from ``coordinator.py``. The watchdog checks critical
entities and reports whether the integration should run normally,
tolerate unavailable entities (during the startup grace period), or
trip the OFF safety stop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def get_unsafe_entities(hass: Any, critical_entities: list[str]) -> dict[str, str]:
    """Return each critical entity that lacks a real state and its reason."""
    unsafe_entities = {}
    for entity_id in critical_entities:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            unsafe_entities[entity_id] = "missing" if state is None else state.state
    return unsafe_entities


def is_in_startup_grace(
    now: datetime,
    safety_startup_deadline: datetime | None,
) -> bool:
    """Return True when the watchdog is still in the startup grace period."""
    return safety_startup_deadline is not None and now < safety_startup_deadline
