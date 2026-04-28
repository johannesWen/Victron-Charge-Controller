"""Shared fixtures for Victron Charge Control tests."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch HA modules that may have version-specific imports.
# This allows tests to run even when the installed homeassistant package
# is older than what the integration targets.
# ---------------------------------------------------------------------------

def _ensure_attr(module_path: str, name: str, default=None):
    """Ensure an attribute exists in an already-imported module."""
    mod = sys.modules.get(module_path)
    if mod is not None and not hasattr(mod, name):
        setattr(mod, name, default if default is not None else MagicMock())

def _patch_ha_compat():
    """Patch missing symbols in homeassistant modules for version compatibility."""
    import homeassistant.config_entries
    _ensure_attr("homeassistant.config_entries", "ConfigFlowResult", dict)

    import homeassistant.helpers.device_registry
    _ensure_attr("homeassistant.helpers.device_registry", "DeviceInfo")
    _ensure_attr("homeassistant.helpers.device_registry", "DeviceEntryType", MagicMock())

    # Ensure number module has NumberMode
    try:
        import homeassistant.components.number
        _ensure_attr("homeassistant.components.number", "NumberMode", MagicMock())
    except ImportError:
        pass

    # Make entity description dataclasses frozen-compatible for older HA versions
    _patch_entity_description("homeassistant.components.number", "NumberEntityDescription")
    _patch_entity_description("homeassistant.components.switch", "SwitchEntityDescription")


def _patch_entity_description(module_path: str, class_name: str):
    """Ensure an entity description class is frozen so frozen subclasses can inherit."""
    try:
        mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(mod, class_name, None)
        if cls is None:
            return
        params = getattr(cls, "__dataclass_params__", None)
        if params is not None and not params.frozen:
            from dataclasses import dataclass

            @dataclass(frozen=True, kw_only=True)
            class _Patched:
                key: str = ""
                name: str | None = None
                icon: str | None = None
                translation_key: str | None = None
                native_unit_of_measurement: str | None = None
                entity_category: Any = None

            _Patched.__name__ = class_name
            _Patched.__qualname__ = class_name
            setattr(mod, class_name, _Patched)
    except Exception:
        pass

# Run patches immediately on import (before test collection)
_patch_ha_compat()

# Now safe to import project modules
from custom_components.victron_charge_control.const import (  # noqa: E402
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    DOMAIN,
)
from custom_components.victron_charge_control.coordinator import (  # noqa: E402
    ChargeControlData,
    VictronChargeControlCoordinator,
)

MOCK_ENTRY_ID = "test_entry_id_123"

MOCK_CONFIG_DATA = {
    CONF_BATTERY_SOC_ENTITY: "sensor.battery_soc",
    CONF_GRID_SETPOINT_ENTITY: "number.grid_setpoint",
    CONF_GRID_POWER_ENTITY: "sensor.grid_power",
    CONF_BATTERY_POWER_ENTITY: "sensor.battery_power",
    CONF_EPEX_SPOT_ENTITY: "sensor.epex_spot",
    CONF_MAX_GRID_FEED_IN_ENTITY: "number.max_grid_feed_in",
}


class MockState:
    """Mock Home Assistant entity state."""

    def __init__(self, state: str, attributes: dict[str, Any] | None = None):
        self.state = state
        self.attributes = attributes or {}


class MockConfigEntry:
    """Mock config entry."""

    def __init__(
        self,
        entry_id: str = MOCK_ENTRY_ID,
        data: dict[str, Any] | None = None,
    ):
        self.entry_id = entry_id
        self.data = data or dict(MOCK_CONFIG_DATA)
        self.options = {}
        self._async_on_unload: list = []

    def async_on_unload(self, func):
        """Register a callback to be called when the entry is unloaded."""
        self._async_on_unload.append(func)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry()


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock()
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def coordinator(mock_hass: MagicMock, mock_config_entry: MockConfigEntry) -> VictronChargeControlCoordinator:
    """Create a coordinator with mocked hass and config entry."""
    coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
    coord.data = ChargeControlData()
    # Prevent "coroutine never awaited" warnings from sync methods that
    # schedule a refresh via hass.async_create_task(self.async_request_refresh()).
    coord.async_request_refresh = MagicMock()
    return coord


def make_epex_data(
    prices: list[tuple[int, float]],
    base_date: str = "2026-04-28",
) -> list[dict[str, Any]]:
    """Create EPEX-style price data.

    Args:
        prices: List of (hour, price_ct_per_kwh) tuples.
        base_date: Date string (YYYY-MM-DD) for the entries.

    Returns:
        List of dicts matching EPEX data format.
    """
    data = []
    for hour, price in prices:
        start = datetime(
            int(base_date[:4]),
            int(base_date[5:7]),
            int(base_date[8:10]),
            hour,
            tzinfo=timezone.utc,
        )
        end = start.replace(hour=hour + 1) if hour < 23 else start.replace(day=start.day + 1, hour=0)
        data.append(
            {
                "start_time": start,
                "end_time": end,
                "price_ct_per_kwh": price,
            }
        )
    return data
