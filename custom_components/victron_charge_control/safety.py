"""Safety watchdog helpers.

Extracted from ``coordinator.py``. The watchdog checks critical
entities and reports whether the integration should run normally,
tolerate unavailable entities (during the startup grace period), or
trip the OFF safety stop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def check_safety(hass: Any, critical_entities: list[str]) -> bool:
    """Return True when every critical entity reports a real state.

    Returns False as soon as one critical entity is explicitly
    ``"unavailable"`` or ``"unknown"`` — an unconfigured entity
    (state is None) is not treated as unavailable.
    """
    for entity_id in critical_entities:
        state = hass.states.get(entity_id)
        if state is not None and state.state in ("unavailable", "unknown"):
            return False
    return True


def is_in_startup_grace(
    now: datetime,
    safety_startup_deadline: datetime | None,
) -> bool:
    """Return True when the watchdog is still in the startup grace period."""
    return safety_startup_deadline is not None and now < safety_startup_deadline
