"""Tests for sensor, number, select, switch, button, and text platforms."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_IDLE,
    CONTROL_MODES,
    DEFAULT_BLOCKED_CHARGING_HOURS,
    DEFAULT_BLOCKED_DISCHARGING_HOURS,
    DEFAULT_CHARGE_POWER,
    DEFAULT_MIN_SOC,
    DOMAIN,
    MODE_AUTO,
    MODE_OFF,
)
from custom_components.victron_charge_control.coordinator import ChargeControlData
from custom_components.victron_charge_control.number import (
    NUMBERS,
    VictronCCNumber,
)
from custom_components.victron_charge_control.select import ControlModeSelect
from custom_components.victron_charge_control.sensor import (
    ChargePlanSensor,
    DesiredActionSensor,
    LastScheduleUpdateSensor,
    ScheduleSensor,
    TargetSetpointSensor,
)
from custom_components.victron_charge_control.switch import (
    SWITCHES,
    VictronCCSwitch,
)
from custom_components.victron_charge_control.button import RecalculateScheduleButton
from custom_components.victron_charge_control.text import (
    BlockedChargingHoursText,
    BlockedDischargingHoursText,
    _parse_hours,
    _format_hours,
)

from .conftest import MockConfigEntry


# ======================================================================
# Sensor entities
# ======================================================================


class TestDesiredActionSensor:
    """Tests for the DesiredActionSensor."""

    def test_native_value_from_data(self, coordinator):
        coordinator.data = ChargeControlData(desired_action=ACTION_CHARGE)
        entry = MockConfigEntry()
        sensor = DesiredActionSensor(coordinator, entry)
        assert sensor.native_value == ACTION_CHARGE

    def test_native_value_no_data(self, coordinator):
        coordinator.data = None
        entry = MockConfigEntry()
        sensor = DesiredActionSensor(coordinator, entry)
        assert sensor.native_value == "idle"

    def test_unique_id(self, coordinator):
        entry = MockConfigEntry()
        sensor = DesiredActionSensor(coordinator, entry)
        assert sensor.unique_id == f"{entry.entry_id}_desired_action"


class TestTargetSetpointSensor:
    """Tests for the TargetSetpointSensor."""

    def test_native_value_from_data(self, coordinator):
        coordinator.data = ChargeControlData(target_setpoint=3000.0)
        entry = MockConfigEntry()
        sensor = TargetSetpointSensor(coordinator, entry)
        assert sensor.native_value == 3000.0

    def test_native_value_no_data(self, coordinator):
        coordinator.data = None
        entry = MockConfigEntry()
        sensor = TargetSetpointSensor(coordinator, entry)
        assert sensor.native_value == 0.0


class TestScheduleSensor:
    """Tests for the ScheduleSensor."""

    def test_charge_hours(self, coordinator):
        coordinator.data = ChargeControlData(
            charge_hours=[{"date": "2026-05-02", "hour": 1}, {"date": "2026-05-02", "hour": 2}, {"date": "2026-05-02", "hour": 3}]
        )
        entry = MockConfigEntry()
        sensor = ScheduleSensor(coordinator, entry, "charge")
        assert sensor.native_value == "2026-05-02:1,2,3"

    def test_discharge_hours(self, coordinator):
        coordinator.data = ChargeControlData(
            discharge_hours=[{"date": "2026-05-02", "hour": 20}, {"date": "2026-05-02", "hour": 21}]
        )
        entry = MockConfigEntry()
        sensor = ScheduleSensor(coordinator, entry, "discharge")
        assert sensor.native_value == "2026-05-02:20,21"

    def test_multi_day_charge_hours(self, coordinator):
        coordinator.data = ChargeControlData(
            charge_hours=[
                {"date": "2026-05-02", "hour": 2}, {"date": "2026-05-02", "hour": 3},
                {"date": "2026-05-03", "hour": 1}, {"date": "2026-05-03", "hour": 4},
            ]
        )
        entry = MockConfigEntry()
        sensor = ScheduleSensor(coordinator, entry, "charge")
        assert sensor.native_value == "2026-05-02:2,3|2026-05-03:1,4"

    def test_blocked_charging_hours(self, coordinator):
        coordinator.data = ChargeControlData(blocked_charging_hours=[18, 19])
        entry = MockConfigEntry()
        sensor = ScheduleSensor(coordinator, entry, "blocked_charging")
        assert sensor.native_value == "18,19"

    def test_empty_schedule(self, coordinator):
        coordinator.data = ChargeControlData()
        entry = MockConfigEntry()
        sensor = ScheduleSensor(coordinator, entry, "charge")
        assert sensor.native_value == ""

    def test_no_data(self, coordinator):
        coordinator.data = None
        entry = MockConfigEntry()
        sensor = ScheduleSensor(coordinator, entry, "charge")
        assert sensor.native_value == ""


class TestChargePlanSensor:
    """Tests for the ChargePlanSensor."""

    def test_native_value_with_data(self, coordinator):
        coordinator.data = ChargeControlData(
            charge_hours=[{"date": "2026-05-02", "hour": 1}, {"date": "2026-05-02", "hour": 2}],
            discharge_hours=[{"date": "2026-05-02", "hour": 20}],
        )
        entry = MockConfigEntry()
        sensor = ChargePlanSensor(coordinator, entry)
        assert sensor.native_value == "2 charge, 1 discharge"

    def test_native_value_no_data(self, coordinator):
        coordinator.data = None
        entry = MockConfigEntry()
        sensor = ChargePlanSensor(coordinator, entry)
        assert sensor.native_value == "unknown"

    @patch("custom_components.victron_charge_control.sensor.dt_util")
    def test_build_plan(self, mock_dt_util, coordinator):
        from datetime import datetime, timezone
        mock_dt_util.now.return_value = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
        coordinator.data = ChargeControlData(
            charge_hours=[{"date": "2026-05-02", "hour": 2}],
            discharge_hours=[{"date": "2026-05-02", "hour": 20}],
            blocked_charging_hours=[5],
            blocked_discharging_hours=[5],
            prices_today=[{"hour": 2, "price": 5.0}, {"hour": 20, "price": 25.0}],
        )
        entry = MockConfigEntry()
        sensor = ChargePlanSensor(coordinator, entry)
        plan = sensor._build_plan(coordinator.data)
        # Plan now covers today (24h) + tomorrow (24h) = 48 entries
        assert len(plan) == 48
        # Find today's entries (first 24)
        today_plan = [p for p in plan if p["date"] == "2026-05-02"]
        assert today_plan[2]["action"] == "charge"
        assert today_plan[2]["price"] == 5.0
        assert today_plan[20]["action"] == "discharge"
        assert today_plan[5]["action"] == "blocked"
        assert today_plan[10]["action"] == "idle"


class TestLastScheduleUpdateSensor:
    """Tests for the LastScheduleUpdateSensor."""

    def test_no_data(self, coordinator):
        coordinator.data = None
        entry = MockConfigEntry()
        sensor = LastScheduleUpdateSensor(coordinator, entry)
        assert sensor.native_value is None


# ======================================================================
# Number entities
# ======================================================================


class TestVictronCCNumber:
    """Tests for the configurable number entities."""

    def test_number_descriptions_count(self):
        assert len(NUMBERS) == 14

    def test_native_value_reads_coordinator(self, coordinator):
        entry = MockConfigEntry()
        desc = NUMBERS[0]  # min_soc
        number = VictronCCNumber(coordinator, entry, desc)
        assert number.native_value == DEFAULT_MIN_SOC

    @pytest.mark.asyncio
    async def test_set_native_value(self, coordinator):
        entry = MockConfigEntry()
        # Find charge_power description
        desc = next(d for d in NUMBERS if d.key == "charge_power")
        number = VictronCCNumber(coordinator, entry, desc)
        coordinator.async_request_refresh = AsyncMock()
        number.async_write_ha_state = MagicMock()

        await number.async_set_native_value(4000.0)

        assert coordinator.charge_power == 4000.0

    @pytest.mark.asyncio
    async def test_set_int_for_hour_counts(self, coordinator):
        entry = MockConfigEntry()
        desc = next(d for d in NUMBERS if d.key == "cheapest_hours")
        number = VictronCCNumber(coordinator, entry, desc)
        coordinator.async_request_refresh = AsyncMock()
        number.async_write_ha_state = MagicMock()

        await number.async_set_native_value(6.0)

        assert coordinator.cheapest_hours == 6
        assert isinstance(coordinator.cheapest_hours, int)

    def test_unique_id(self, coordinator):
        entry = MockConfigEntry()
        desc = NUMBERS[0]
        number = VictronCCNumber(coordinator, entry, desc)
        assert number.unique_id == f"{entry.entry_id}_{desc.key}"


# ======================================================================
# Select entity
# ======================================================================


class TestControlModeSelect:
    """Tests for the ControlModeSelect entity."""

    def test_current_option(self, coordinator):
        entry = MockConfigEntry()
        select = ControlModeSelect(coordinator, entry)
        coordinator.control_mode = MODE_OFF
        assert select.current_option == MODE_OFF

    @pytest.mark.asyncio
    async def test_select_option(self, coordinator):
        entry = MockConfigEntry()
        select = ControlModeSelect(coordinator, entry)
        coordinator.async_request_refresh = AsyncMock()
        select.async_write_ha_state = MagicMock()

        await select.async_select_option(MODE_AUTO)

        assert coordinator.control_mode == MODE_AUTO

    @pytest.mark.asyncio
    async def test_select_invalid_option_ignored(self, coordinator):
        entry = MockConfigEntry()
        select = ControlModeSelect(coordinator, entry)
        coordinator.control_mode = MODE_OFF
        coordinator.async_request_refresh = AsyncMock()

        await select.async_select_option("invalid_mode")

        assert coordinator.control_mode == MODE_OFF

    def test_options_list(self, coordinator):
        entry = MockConfigEntry()
        select = ControlModeSelect(coordinator, entry)
        assert select.options == CONTROL_MODES


# ======================================================================
# Switch entities
# ======================================================================


class TestVictronCCSwitch:
    """Tests for the toggle switch entities."""

    def test_switch_descriptions_count(self):
        assert len(SWITCHES) == 3

    def test_is_on(self, coordinator):
        entry = MockConfigEntry()
        desc = SWITCHES[0]  # charge_allowed
        switch = VictronCCSwitch(coordinator, entry, desc)
        coordinator.charge_allowed = True
        assert switch.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator):
        entry = MockConfigEntry()
        desc = SWITCHES[0]  # charge_allowed
        switch = VictronCCSwitch(coordinator, entry, desc)
        coordinator.charge_allowed = False
        coordinator.async_request_refresh = AsyncMock()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        assert coordinator.charge_allowed is True

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator):
        entry = MockConfigEntry()
        desc = SWITCHES[0]  # charge_allowed
        switch = VictronCCSwitch(coordinator, entry, desc)
        coordinator.charge_allowed = True
        coordinator.async_request_refresh = AsyncMock()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        assert coordinator.charge_allowed is False


# ======================================================================
# Button entity
# ======================================================================


class TestRecalculateScheduleButton:
    """Tests for the RecalculateScheduleButton."""

    @pytest.mark.asyncio
    async def test_press(self, coordinator):
        entry = MockConfigEntry()
        button = RecalculateScheduleButton(coordinator, entry)
        coordinator.async_request_refresh = AsyncMock()
        coordinator.control_mode = MODE_AUTO
        coordinator.hass.states.get.return_value = None  # No EPEX data

        await button.async_press()

        coordinator.async_request_refresh.assert_called_once()

    def test_unique_id(self, coordinator):
        entry = MockConfigEntry()
        button = RecalculateScheduleButton(coordinator, entry)
        assert button.unique_id == f"{entry.entry_id}_recalculate_schedule"


# ======================================================================
# Text entities & helpers
# ======================================================================


class TestParseFormatHours:
    """Tests for _parse_hours and _format_hours helpers."""

    def test_parse_valid(self):
        assert _parse_hours("1, 2, 3") == [1, 2, 3]

    def test_parse_empty(self):
        assert _parse_hours("") == []

    def test_parse_whitespace(self):
        assert _parse_hours("  ") == []

    def test_parse_deduplicates(self):
        assert _parse_hours("5, 5, 5") == [5]

    def test_parse_filters_invalid(self):
        assert _parse_hours("1, abc, 25, 2") == [1, 2]

    def test_parse_sorts(self):
        assert _parse_hours("3, 1, 2") == [1, 2, 3]

    def test_format_hours(self):
        assert _format_hours([3, 1, 2]) == "1, 2, 3"

    def test_format_empty(self):
        assert _format_hours([]) == ""


class TestBlockedChargingHoursText:
    """Tests for BlockedChargingHoursText entity."""

    def test_native_value(self, coordinator):
        entry = MockConfigEntry()
        coordinator._blocked_charging_hours = [18, 19, 20]
        text = BlockedChargingHoursText(coordinator, entry)
        assert text.native_value == "18, 19, 20"

    @pytest.mark.asyncio
    async def test_set_value(self, coordinator):
        entry = MockConfigEntry()
        text = BlockedChargingHoursText(coordinator, entry)
        text.async_write_ha_state = MagicMock()

        await text.async_set_value("10, 11, 12")

        assert coordinator.blocked_charging_hours == [10, 11, 12]


class TestBlockedDischargingHoursText:
    """Tests for BlockedDischargingHoursText entity."""

    def test_native_value(self, coordinator):
        entry = MockConfigEntry()
        coordinator._blocked_discharging_hours = [15, 16]
        text = BlockedDischargingHoursText(coordinator, entry)
        assert text.native_value == "15, 16"

    @pytest.mark.asyncio
    async def test_set_value(self, coordinator):
        entry = MockConfigEntry()
        text = BlockedDischargingHoursText(coordinator, entry)
        text.async_write_ha_state = MagicMock()

        await text.async_set_value("7, 8")

        assert coordinator.blocked_discharging_hours == [7, 8]
