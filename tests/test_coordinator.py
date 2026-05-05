"""Tests for the Victron Charge Control coordinator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_BLOCKED,
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    DEFAULT_CHARGE_POWER,
    DEFAULT_DEADBAND,
    DEFAULT_DISCHARGE_POWER,
    DEFAULT_IDLE_SETPOINT,
    DEFAULT_MAX_GRID_SETPOINT,
    DEFAULT_MIN_GRID_SETPOINT,
    MODE_AUTO,
    MODE_FORCE_CHARGE,
    MODE_FORCE_DISCHARGE,
    MODE_MANUAL,
    MODE_OFF,
)
from custom_components.victron_charge_control.coordinator import (
    ChargeControlData,
    ScheduleSlot,
    VictronChargeControlCoordinator,
)

from .conftest import MOCK_CONFIG_DATA, MockConfigEntry, MockState, make_epex_data


# ======================================================================
# ChargeControlData defaults
# ======================================================================


class TestChargeControlData:
    """Tests for the ChargeControlData dataclass."""

    def test_defaults(self):
        data = ChargeControlData()
        assert data.desired_action == ACTION_IDLE
        assert data.target_setpoint == 0.0
        assert data.charge_hours == []
        assert data.discharge_hours == []
        assert data.current_price is None
        assert data.last_schedule_update is None

    def test_custom_values(self):
        data = ChargeControlData(
            desired_action=ACTION_CHARGE,
            target_setpoint=3000.0,
            charge_hours=[{"date": "2026-05-02", "hour": 2}, {"date": "2026-05-02", "hour": 3}],
        )
        assert data.desired_action == ACTION_CHARGE
        assert data.target_setpoint == 3000.0
        assert data.charge_hours == [{"date": "2026-05-02", "hour": 2}, {"date": "2026-05-02", "hour": 3}]


# ======================================================================
# Coordinator initialization
# ======================================================================


class TestCoordinatorInit:
    """Tests for coordinator initialization."""

    def test_entity_references(self, coordinator):
        assert coordinator.battery_soc_entity == "sensor.battery_soc"
        assert coordinator.grid_setpoint_entity == "number.grid_setpoint"
        assert coordinator.epex_spot_entity == "sensor.epex_spot"
        assert coordinator.max_grid_feed_in_entity == "number.max_grid_feed_in"

    def test_default_params(self, coordinator):
        assert coordinator.control_mode == MODE_OFF
        assert coordinator.charge_allowed is True
        assert coordinator.discharge_allowed is True
        assert coordinator.min_soc == 10.0
        assert coordinator.max_soc == 95.0
        assert coordinator.charge_power == 3000.0
        assert coordinator.discharge_power == 3000.0

    def test_update_entity_references(self, coordinator):
        new_data = {
            **MOCK_CONFIG_DATA,
            "battery_soc_entity": "sensor.new_soc",
        }
        coordinator.update_entity_references(new_data)
        assert coordinator.battery_soc_entity == "sensor.new_soc"


# ======================================================================
# Schedule management
# ======================================================================


class TestScheduleManagement:
    """Tests for schedule management methods."""

    def test_set_charge_hours(self, coordinator):
        coordinator.set_charge_hours([("2026-05-02", 3), ("2026-05-02", 1), ("2026-05-02", 2), ("2026-05-02", 2), ("2026-05-02", 25)])
        # Invalid hour 25 filtered, deduped, sorted
        assert coordinator.charge_hours == [("2026-05-02", 1), ("2026-05-02", 2), ("2026-05-02", 3)]

    def test_set_discharge_hours(self, coordinator):
        coordinator.set_discharge_hours([("2026-05-02", 20), ("2026-05-02", 21), ("2026-05-03", 22)])
        assert coordinator.discharge_hours == [("2026-05-02", 20), ("2026-05-02", 21), ("2026-05-03", 22)]

    def test_set_blocked_charging_hours(self, coordinator):
        coordinator.set_blocked_charging_hours([18, 19, 20])
        assert coordinator.blocked_charging_hours == [18, 19, 20]

    def test_set_blocked_discharging_hours(self, coordinator):
        coordinator.set_blocked_discharging_hours([15, 16])
        assert coordinator.blocked_discharging_hours == [15, 16]

    def test_clear_schedule(self, coordinator):
        coordinator._charge_hours = [("2026-05-02", 1), ("2026-05-02", 2)]
        coordinator._discharge_hours = [("2026-05-02", 20)]
        coordinator._blocked_charging_hours = [18]
        coordinator._blocked_discharging_hours = [15]
        coordinator.clear_schedule()
        assert coordinator.charge_hours == []
        assert coordinator.discharge_hours == []
        assert coordinator.blocked_charging_hours == []
        assert coordinator.blocked_discharging_hours == []


class TestToggleHour:
    """Tests for the toggle_hour cycle: idle → charge → discharge → blocked → idle."""

    def test_idle_to_charge(self, coordinator):
        coordinator.toggle_hour(5, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.charge_hours
        assert ("2026-05-02", 5) not in coordinator.discharge_hours

    def test_charge_to_discharge(self, coordinator):
        coordinator._charge_hours = [("2026-05-02", 5)]
        coordinator.toggle_hour(5, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.charge_hours
        assert ("2026-05-02", 5) in coordinator.discharge_hours

    def test_discharge_to_blocked(self, coordinator):
        coordinator._discharge_hours = [("2026-05-02", 5)]
        coordinator.toggle_hour(5, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.discharge_hours
        assert 5 in coordinator.blocked_charging_hours
        assert 5 in coordinator.blocked_discharging_hours

    def test_blocked_to_idle(self, coordinator):
        coordinator._blocked_charging_hours = [5]
        coordinator._blocked_discharging_hours = [5]
        coordinator.toggle_hour(5, "2026-05-02")
        assert 5 not in coordinator.blocked_charging_hours
        assert 5 not in coordinator.blocked_discharging_hours
        assert ("2026-05-02", 5) not in coordinator.charge_hours

    def test_invalid_hour_ignored(self, coordinator):
        coordinator.toggle_hour(-1, "2026-05-02")
        coordinator.toggle_hour(24, "2026-05-02")
        assert coordinator.charge_hours == []


class TestSetHourAction:
    """Tests for set_hour_action."""

    def test_set_charge(self, coordinator):
        coordinator.set_hour_action(5, ACTION_CHARGE, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.charge_hours
        assert ("2026-05-02", 5) not in coordinator.discharge_hours

    def test_set_discharge(self, coordinator):
        coordinator.set_hour_action(5, ACTION_DISCHARGE, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.discharge_hours
        assert ("2026-05-02", 5) not in coordinator.charge_hours

    def test_set_blocked(self, coordinator):
        coordinator.set_hour_action(5, ACTION_BLOCKED, "2026-05-02")
        assert 5 in coordinator.blocked_charging_hours
        assert 5 in coordinator.blocked_discharging_hours

    def test_set_idle(self, coordinator):
        coordinator._charge_hours = [("2026-05-02", 5)]
        coordinator.set_hour_action(5, ACTION_IDLE, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.charge_hours

    def test_replaces_previous_action(self, coordinator):
        coordinator._charge_hours = [("2026-05-02", 5)]
        coordinator.set_hour_action(5, ACTION_DISCHARGE, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.charge_hours
        assert ("2026-05-02", 5) in coordinator.discharge_hours

    def test_invalid_hour(self, coordinator):
        coordinator.set_hour_action(25, ACTION_CHARGE, "2026-05-02")
        assert coordinator.charge_hours == []


# ======================================================================
# EPEX data extraction
# ======================================================================


class TestEpexDataExtraction:
    """Tests for EPEX data parsing helpers."""

    def test_find_epex_data_with_data_attribute(self):
        data = [{"start_time": "2026-01-01T00:00", "price_ct_per_kwh": 5.0}]
        result = VictronChargeControlCoordinator._find_epex_data({"data": data})
        assert result == data

    def test_find_epex_data_fallback_attribute(self):
        data = [{"start_time": "2026-01-01T00:00", "price_ct_per_kwh": 5.0}]
        result = VictronChargeControlCoordinator._find_epex_data({"prices": data})
        assert result == data

    def test_find_epex_data_empty(self):
        result = VictronChargeControlCoordinator._find_epex_data({})
        assert result == []

    def test_find_epex_data_non_list(self):
        result = VictronChargeControlCoordinator._find_epex_data({"data": "not a list"})
        assert result == []

    def test_extract_price_ct_direct(self):
        price = VictronChargeControlCoordinator._extract_price_ct({"price_ct_per_kwh": 12.5})
        assert price == 12.5

    def test_extract_price_ct_from_eur(self):
        price = VictronChargeControlCoordinator._extract_price_ct({"price_per_kwh": 0.125})
        assert price == pytest.approx(12.5)

    def test_extract_price_ct_missing(self):
        price = VictronChargeControlCoordinator._extract_price_ct({})
        assert price is None

    def test_extract_price_ct_invalid(self):
        price = VictronChargeControlCoordinator._extract_price_ct({"price_ct_per_kwh": "abc"})
        assert price is None


# ======================================================================
# Decision engine (_determine_action)
# ======================================================================


class TestDetermineAction:
    """Tests for the decision engine priority stack."""

    def _set_soc(self, coordinator, soc_value):
        """Set up battery SOC mock."""
        coordinator.hass.states.get.side_effect = lambda eid: {
            "sensor.battery_soc": MockState(str(soc_value)),
            "number.grid_setpoint": MockState("0"),
            "sensor.epex_spot": MockState("10"),
        }.get(eid)

    def test_mode_off_returns_idle(self, coordinator):
        coordinator.control_mode = MODE_OFF
        assert coordinator._determine_action() == ACTION_IDLE

    def test_soc_unavailable_returns_idle(self, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.hass.states.get.return_value = MockState("unavailable")
        assert coordinator._determine_action() == ACTION_IDLE

    def test_soc_none_returns_idle(self, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.hass.states.get.return_value = None
        assert coordinator._determine_action() == ACTION_IDLE

    def test_force_charge_allowed(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_CHARGE

    def test_force_charge_at_max_soc(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        self._set_soc(coordinator, 96.0)
        assert coordinator._determine_action() == ACTION_IDLE

    def test_force_charge_not_allowed(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = False
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    def test_force_discharge_allowed(self, coordinator):
        coordinator.control_mode = MODE_FORCE_DISCHARGE
        coordinator.discharge_allowed = True
        coordinator.min_soc = 10.0
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_DISCHARGE

    def test_force_discharge_at_min_soc(self, coordinator):
        coordinator.control_mode = MODE_FORCE_DISCHARGE
        coordinator.discharge_allowed = True
        coordinator.min_soc = 10.0
        self._set_soc(coordinator, 5.0)
        assert coordinator._determine_action() == ACTION_IDLE

    def test_force_discharge_not_allowed(self, coordinator):
        coordinator.control_mode = MODE_FORCE_DISCHARGE
        coordinator.discharge_allowed = False
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_auto_charge_hour(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator._charge_hours = [("2026-04-28", 3)]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_auto_discharge_hour(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.discharge_allowed = True
        coordinator.min_soc = 10.0
        coordinator._discharge_hours = [("2026-04-28", 20)]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 20, 15, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_DISCHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_auto_idle_when_no_schedule(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator._charge_hours = [("2026-04-28", 3)]
        coordinator._discharge_hours = [("2026-04-28", 20)]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_auto_idle_when_wrong_day(self, mock_dt_util, coordinator):
        """Schedule for a different day should not match."""
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator._charge_hours = [("2026-04-29", 3)]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_charging_hour_returns_idle(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator._charge_hours = [("2026-04-28", 3)]
        coordinator._blocked_charging_hours = [3]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_discharging_hour_returns_idle(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.discharge_allowed = True
        coordinator._discharge_hours = [("2026-04-28", 20)]
        coordinator._blocked_discharging_hours = [20]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 20, 15, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_manual_mode_uses_schedule(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_MANUAL
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator._charge_hours = [("2026-04-28", 3)]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_CHARGE


# ======================================================================
# Setpoint computation
# ======================================================================


class TestComputeSetpoint:
    """Tests for _compute_setpoint."""

    def test_charge_setpoint(self, coordinator):
        coordinator.charge_power = 3000.0
        sp = coordinator._compute_setpoint(ACTION_CHARGE)
        assert sp == 3000.0

    def test_discharge_setpoint(self, coordinator):
        coordinator.discharge_power = 3000.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE)
        assert sp == -3000.0

    def test_idle_setpoint(self, coordinator):
        coordinator.idle_setpoint = 50.0
        sp = coordinator._compute_setpoint(ACTION_IDLE)
        assert sp == 50.0

    def test_clamp_to_max(self, coordinator):
        coordinator.charge_power = 20000.0
        coordinator.max_grid_setpoint = 5000.0
        sp = coordinator._compute_setpoint(ACTION_CHARGE)
        assert sp == 5000.0

    def test_clamp_to_min(self, coordinator):
        coordinator.discharge_power = 20000.0
        coordinator.min_grid_setpoint = -5000.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE)
        assert sp == -5000.0


# ======================================================================
# Auto schedule calculation
# ======================================================================


class TestCalculateAutoSchedule:
    """Tests for calculate_auto_schedule."""

    def _setup_epex(self, coordinator, prices):
        """Set up EPEX entity with price data."""
        epex_data = make_epex_data(prices)
        coordinator.hass.states.get.return_value = MockState(
            "10.0",
            {"data": epex_data},
        )

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_basic_auto_schedule(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 2
        coordinator.expensive_hours = 2
        coordinator.charge_price_threshold = 15.0
        coordinator.discharge_price_threshold = 20.0

        # Set up time
        now = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = now
        mock_dt_util.as_local.side_effect = lambda x: x
        mock_dt_util.parse_datetime.side_effect = lambda x: None

        # Prices: hours 0-5 with varied prices
        prices = [
            (0, 5.0),   # cheap
            (1, 8.0),   # cheap
            (2, 12.0),
            (3, 15.0),
            (4, 25.0),  # expensive
            (5, 30.0),  # expensive
        ]
        self._setup_epex(coordinator, prices)

        coordinator.calculate_auto_schedule()

        assert ("2026-04-28", 0) in coordinator.charge_hours
        assert ("2026-04-28", 1) in coordinator.charge_hours
        assert ("2026-04-28", 5) in coordinator.discharge_hours
        assert ("2026-04-28", 4) in coordinator.discharge_hours

    def test_not_auto_mode_does_nothing(self, coordinator):
        coordinator.control_mode = MODE_MANUAL
        coordinator._charge_hours = [("2026-05-02", 1)]
        coordinator.calculate_auto_schedule()
        # Should not change existing schedule
        assert coordinator.charge_hours == [("2026-05-02", 1)]

    def test_missing_epex_entity(self, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.hass.states.get.return_value = None
        coordinator.calculate_auto_schedule()
        assert coordinator.charge_hours == []

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_discharge_wins_conflict(self, mock_dt_util, coordinator):
        """If an hour qualifies for both charge and discharge, discharge wins."""
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 1
        coordinator.expensive_hours = 1
        coordinator.charge_price_threshold = 100.0
        coordinator.discharge_price_threshold = 0.0

        now = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = now
        mock_dt_util.as_local.side_effect = lambda x: x
        mock_dt_util.parse_datetime.side_effect = lambda x: None

        # Only one hour available - qualifies for both
        self._setup_epex(coordinator, [(3, 15.0)])

        coordinator.calculate_auto_schedule()

        # Discharge wins, removed from charge
        assert ("2026-04-28", 3) in coordinator.discharge_hours
        assert ("2026-04-28", 3) not in coordinator.charge_hours

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_hours_excluded_from_auto(self, mock_dt_util, coordinator):
        """Blocked hours should not appear in auto schedule."""
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 2
        coordinator.expensive_hours = 2
        coordinator.charge_price_threshold = 15.0
        coordinator.discharge_price_threshold = 20.0
        coordinator._blocked_charging_hours = [0]
        coordinator._blocked_discharging_hours = [5]

        now = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = now
        mock_dt_util.as_local.side_effect = lambda x: x
        mock_dt_util.parse_datetime.side_effect = lambda x: None

        prices = [
            (0, 2.0),   # cheapest but blocked for charging
            (1, 5.0),
            (2, 8.0),
            (3, 15.0),
            (4, 25.0),
            (5, 30.0),  # most expensive but blocked for discharging
        ]
        self._setup_epex(coordinator, prices)

        coordinator.calculate_auto_schedule()

        assert ("2026-04-28", 0) not in coordinator.charge_hours
        assert ("2026-04-28", 5) not in coordinator.discharge_hours


# ======================================================================
# Safety watchdog
# ======================================================================


class TestSafetyWatchdog:
    """Tests for the safety watchdog."""

    def test_safe_when_entities_available(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("50")
        assert coordinator._check_safety() is True

    def test_unsafe_when_soc_unavailable(self, coordinator):
        def side_effect(entity_id):
            if entity_id == "sensor.battery_soc":
                return MockState("unavailable")
            return MockState("50")

        coordinator.hass.states.get.side_effect = side_effect
        assert coordinator._check_safety() is False

    def test_unsafe_when_setpoint_unknown(self, coordinator):
        def side_effect(entity_id):
            if entity_id == "number.grid_setpoint":
                return MockState("unknown")
            return MockState("50")

        coordinator.hass.states.get.side_effect = side_effect
        assert coordinator._check_safety() is False

    def test_safe_when_entity_missing(self, coordinator):
        """If entity doesn't exist (None), it's not marked unavailable."""
        coordinator.hass.states.get.return_value = None
        assert coordinator._check_safety() is True


# ======================================================================
# Setpoint application
# ======================================================================


class TestApplySetpoint:
    """Tests for _apply_setpoint."""

    @pytest.mark.asyncio
    async def test_apply_setpoint_calls_service(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("0")
        coordinator._last_applied_setpoint = None

        await coordinator._apply_setpoint(3000.0)

        coordinator.hass.services.async_call.assert_called_once_with(
            "number",
            "set_value",
            {"entity_id": "number.grid_setpoint", "value": 3000.0},
            blocking=True,
        )
        assert coordinator._last_applied_setpoint == 3000.0

    @pytest.mark.asyncio
    async def test_apply_setpoint_skips_deadband(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("3000")
        coordinator._last_applied_setpoint = 3000.0

        # Difference is 20W, within 50W deadband
        await coordinator._apply_setpoint(3020.0)

        coordinator.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_setpoint_skips_unavailable(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("unavailable")

        await coordinator._apply_setpoint(3000.0)

        coordinator.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_setpoint_skips_missing_entity(self, coordinator):
        coordinator.hass.states.get.return_value = None

        await coordinator._apply_setpoint(3000.0)

        coordinator.hass.services.async_call.assert_not_called()


# ======================================================================
# Grid feed-in control
# ======================================================================


class TestGridFeedInControl:
    """Tests for _apply_grid_feed_in."""

    @pytest.mark.asyncio
    async def test_disabled_does_nothing(self, coordinator):
        coordinator.grid_feed_in_control_enabled = False
        is_reduced, applied = await coordinator._apply_grid_feed_in(10.0)
        assert is_reduced is False
        assert applied is None

    @pytest.mark.asyncio
    async def test_no_price_skips(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        is_reduced, applied = await coordinator._apply_grid_feed_in(None)
        assert is_reduced is False
        assert applied is None

    @pytest.mark.asyncio
    async def test_below_threshold_reduces(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        coordinator.grid_feed_in_price_threshold = 10.0
        coordinator.reduced_max_grid_feed_in = 0.0
        coordinator.default_max_grid_feed_in = 5000.0
        coordinator._last_applied_feed_in = None
        coordinator.hass.states.get.return_value = MockState("5000")

        is_reduced, applied = await coordinator._apply_grid_feed_in(5.0)

        assert is_reduced is True
        assert applied == 0.0

    @pytest.mark.asyncio
    async def test_above_threshold_default(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        coordinator.grid_feed_in_price_threshold = 10.0
        coordinator.default_max_grid_feed_in = 5000.0
        coordinator._last_applied_feed_in = None
        coordinator.hass.states.get.return_value = MockState("0")

        is_reduced, applied = await coordinator._apply_grid_feed_in(15.0)

        assert is_reduced is False
        assert applied == 5000.0
