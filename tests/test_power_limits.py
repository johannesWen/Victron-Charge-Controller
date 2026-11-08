"""Configurable number ranges are applied before control and enforced by HA."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest
from homeassistant.components.number.services import _async_set_value
from homeassistant.exceptions import ServiceValidationError

from custom_components import victron_charge_control as integration
from custom_components.victron_charge_control.const import (
    CONF_IDLE_SETPOINT_LIMIT,
    CONF_POWER_LIMIT,
    CONF_USE_SOLCAST_FORECAST,
    DOMAIN,
)
from custom_components.victron_charge_control.number import (
    NUMBERS,
    VictronCCNumber,
    async_setup_entry,
)
from tests.conftest import MockConfigEntry, MockState
from tests.slots import utc_slot

# Expected ranges at power=1201 and idle=7, including unchanged native steps.
RANGES = [
    ("charge_power", 0, 1201, 100),
    ("discharge_power", 0, 1201, 100),
    ("min_grid_setpoint", -1201, 0, 100),
    ("max_grid_setpoint", 0, 1201, 100),
    ("default_max_grid_feed_in", 0, 1201, 100),
    ("reduced_max_grid_feed_in", 0, 1201, 100),
    ("idle_setpoint", -7, 7, 10),
]


@pytest.fixture(params=RANGES, ids=lambda row: row[0])
def limited_number(request, coordinator, mock_config_entry):
    key, minimum, maximum, step = request.param
    mock_config_entry.options = {CONF_POWER_LIMIT: 1201, CONF_IDLE_SETPOINT_LIMIT: 7}
    description = next(desc for desc in NUMBERS if desc.key == key)
    number = VictronCCNumber(coordinator, mock_config_entry, description)
    number.hass = coordinator.hass
    number.async_write_ha_state = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.calculate_auto_schedule = MagicMock()
    assert (number.native_min_value, number.native_max_value, number.native_step) == (minimum, maximum, step)
    assert number.unique_id == f"{mock_config_entry.entry_id}_{key}"
    return number


@pytest.mark.parametrize("options,power,idle", [
    ({}, 15000, 500),
    ({CONF_POWER_LIMIT: 27000, CONF_IDLE_SETPOINT_LIMIT: 1700}, 27000, 1700),
    ({CONF_POWER_LIMIT: 1, CONF_IDLE_SETPOINT_LIMIT: 0}, 1, 0),
    ({CONF_POWER_LIMIT: 1, CONF_IDLE_SETPOINT_LIMIT: 2000}, 1, 2000),
])
def test_ranges_defaults_and_shared_descriptions(coordinator, options, power, idle):
    entry = MockConfigEntry()
    entry.options = options
    affected = {row[0] for row in RANGES}
    for desc in NUMBERS:
        number = VictronCCNumber(coordinator, entry, desc)
        if desc.key == "idle_setpoint":
            expected = (-idle, idle)
        elif desc.key == "min_grid_setpoint":
            expected = (-power, 0)
        elif desc.key in affected:
            expected = (0, power)
        else:
            expected = (desc.native_min_value, desc.native_max_value)
        assert (number.native_min_value, number.native_max_value) == expected
        assert number.native_value == min(expected[1], max(expected[0], desc.default_value))
        assert number.native_step == desc.native_step

        # Creating another entry must still use the original descriptions/defaults.
        other = VictronCCNumber(coordinator, MockConfigEntry(), desc)
        assert other.entity_description is desc
        assert (other.native_min_value, other.native_max_value) == (desc.native_min_value, desc.native_max_value)
        assert other.native_value == desc.default_value


@pytest.mark.parametrize("restored", ["-99999", "99999", "0", "3.5", "-3.5"])
async def test_finite_restoration_clamps_to_range(limited_number, restored):
    number = limited_number
    number.async_get_last_state = AsyncMock(return_value=MockState(restored))
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
    assert number.native_value == min(number.native_max_value, max(number.native_min_value, float(restored)))
    number.coordinator.async_request_refresh.assert_not_called()
    number.coordinator.calculate_auto_schedule.assert_not_called()


@pytest.mark.parametrize("restored", [None, "unknown", "unavailable", "nan", "inf", "-inf", "bad"])
async def test_invalid_restoration_keeps_bounded_default(limited_number, restored):
    number = limited_number
    before = number.native_value
    assert number.native_min_value <= before <= number.native_max_value
    number.async_get_last_state = AsyncMock(return_value=MockState(restored) if restored is not None else None)
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
    assert number.native_value == before
    number.coordinator.async_request_refresh.assert_not_called()


@pytest.mark.parametrize("boundary", ["native_min_value", "native_max_value"])
async def test_ha_number_service_accepts_boundaries(limited_number, boundary):
    number = limited_number
    value = getattr(number, boundary)
    await _async_set_value(number, SimpleNamespace(data={"value": float(value)}))
    assert number.native_value == value
    number.coordinator.async_request_refresh.assert_awaited_once()
    number.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize("invalid", ["below", "above", "nan", "inf", "-inf"])
async def test_ha_number_service_rejects_invalid_without_mutation(limited_number, invalid):
    number = limited_number
    value = {"below": number.native_min_value - 1, "above": number.native_max_value + 1}.get(invalid, invalid)
    payload = probatio.Schema({probatio.Required("value"): probatio.Coerce(float)})({"value": value})
    before = number.native_value
    with pytest.raises(ServiceValidationError):
        await _async_set_value(number, SimpleNamespace(data=payload))
    assert number.native_value == before
    number.coordinator.async_request_refresh.assert_not_called()
    number.coordinator.calculate_auto_schedule.assert_not_called()
    number.async_write_ha_state.assert_not_called()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_direct_nonfinite_write_rejected(limited_number, value):
    before = limited_number.native_value
    with pytest.raises(ServiceValidationError):
        await limited_number.async_set_native_value(value)
    assert limited_number.native_value == before
    limited_number.coordinator.async_request_refresh.assert_not_called()


@pytest.mark.parametrize("restored", [None, "99999", "-99999", "nan"])
async def test_setup_bounds_numbers_before_first_control_and_preserves_schedule(
    mock_hass, mock_config_entry, mock_store, restored,
):
    mock_config_entry.options = {
        CONF_POWER_LIMIT: 1201, CONF_IDLE_SETPOINT_LIMIT: 0,
        CONF_USE_SOLCAST_FORECAST: False, "unrelated": "preserved",
    }
    mock_store._data = {
        "charge_hours": [["2026-05-02", 1]],
        "discharge_hours": [["2026-05-02", 20]],
        "blocked_charging_hours": [18],
    }
    stored = deepcopy(mock_store._data)
    numbers = []
    observed = []

    async def setup_platforms(entry, _platforms):
        controller = mock_hass.data[DOMAIN][entry.entry_id]
        await async_setup_entry(mock_hass, entry, numbers.extend)
        for number in numbers:
            number.hass = mock_hass
            number.async_get_last_state = AsyncMock(return_value=MockState(restored) if restored else None)
            await number.async_added_to_hass()

        async def first_control():
            for number in numbers:
                if number.entity_description.key not in {row[0] for row in RANGES}:
                    continue
                assert number.native_min_value <= number.native_value <= number.native_max_value
            assert controller.idle_setpoint == 0
            assert controller.charge_hours == [utc_slot("2026-05-02", 1)]
            assert controller.discharge_hours == [utc_slot("2026-05-02", 20)]
            observed.append(True)
        controller.async_request_refresh = AsyncMock(side_effect=first_control)

    mock_hass.config_entries.async_forward_entry_setups.side_effect = setup_platforms
    with (
        patch("homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass", new=AsyncMock()),
        patch("custom_components.victron_charge_control.coordinator.async_track_state_change_event"),
        patch("custom_components.victron_charge_control.coordinator.async_track_time_change"),
        patch.object(integration, "async_register_commands"),
        patch.object(integration, "async_setup_services", new=AsyncMock()),
        patch.object(integration, "_async_register_card", new=AsyncMock()),
    ):
        assert await integration.async_setup_entry(mock_hass, mock_config_entry)
    assert observed == [True]
    assert mock_store._data == stored
    assert mock_store.save_calls == []
    assert mock_config_entry.options["unrelated"] == "preserved"
    mock_hass.services.async_call.assert_not_called()


async def test_zero_idle_limit_accepts_only_zero(coordinator, mock_config_entry):
    mock_config_entry.options = {CONF_IDLE_SETPOINT_LIMIT: 0}
    number = VictronCCNumber(
        coordinator, mock_config_entry, next(desc for desc in NUMBERS if desc.key == "idle_setpoint"),
    )
    number.hass = coordinator.hass
    number.async_write_ha_state = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    await _async_set_value(number, SimpleNamespace(data={"value": 0.0}))
    for value in (-1, 1):
        with pytest.raises(ServiceValidationError):
            await _async_set_value(number, SimpleNamespace(data={"value": float(value)}))
        assert number.native_value == 0
    coordinator.async_request_refresh.assert_awaited_once()
