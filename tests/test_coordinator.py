"""Tests for the Victron Charge Control coordinator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_BLOCKED,
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    CONF_DC_COUPLED_PV_FEED_IN_ENTITY,
    CONF_SAFETY_STARTUP_GRACE_SECONDS,
    CONF_SOLAR_SURPLUS_ENTITY,
    DEFAULT_CHARGE_POWER,
    DEFAULT_DEADBAND,
    DEFAULT_DISCHARGE_POWER,
    DEFAULT_IDLE_SETPOINT,
    DEFAULT_MAX_GRID_SETPOINT,
    DEFAULT_MIN_GRID_SETPOINT,
    DEFAULT_PV_CHARGE_SHARE,
    DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
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

from .conftest import (
    MOCK_CONFIG_DATA,
    MOCK_CONFIG_DATA_WITH_COST,
    MOCK_CONFIG_DATA_WITH_DC_FEED_IN,
    MOCK_CONFIG_DATA_WITH_SOLAR,
    MockConfigEntry,
    MockState,
    make_epex_data,
)


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
        assert coordinator.grid_consumption_entity is None
        assert coordinator.grid_feed_in_energy_entity is None

    def test_default_params(self, coordinator):
        assert coordinator.control_mode == MODE_OFF
        assert coordinator.charge_allowed is True
        assert coordinator.discharge_allowed is True
        assert coordinator.min_soc == 10.0
        assert coordinator.max_soc == 95.0
        assert coordinator.soc_hysteresis == 2.0
        assert coordinator.charge_power == 3000.0
        assert coordinator.discharge_power == 3000.0

    def test_update_entity_references(self, coordinator):
        new_data = {
            **MOCK_CONFIG_DATA,
            "battery_soc_entity": "sensor.new_soc",
        }
        coordinator.update_entity_references(new_data)
        assert coordinator.battery_soc_entity == "sensor.new_soc"

    def test_optional_cost_entity_references(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_COST)),
        )
        assert coord.grid_consumption_entity == "sensor.grid_consumption_kwh"
        assert coord.grid_feed_in_energy_entity == "sensor.grid_feed_in_kwh"

    def test_dc_feed_in_entity_references(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_DC_FEED_IN)),
        )
        assert coord.dc_coupled_pv_feed_in_entity == "switch.dc_pv_feed_in"
        assert coord.control_dc_coupled_feed_in is False
        assert coord._last_applied_dc_feed_in_state is None

    def test_dc_feed_in_entity_absent_by_default(self, coordinator):
        assert coordinator.dc_coupled_pv_feed_in_entity is None


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

    def test_replan_hours_default(self, coordinator):
        from custom_components.victron_charge_control.const import DEFAULT_REPLAN_HOURS
        assert coordinator.replan_hours == list(DEFAULT_REPLAN_HOURS)
        assert coordinator.replan_hours == [18]

    def test_clear_schedule(self, coordinator):
        coordinator._charge_hours = [("2026-05-02", 1), ("2026-05-02", 2)]
        coordinator._discharge_hours = [("2026-05-02", 20)]
        coordinator._pv_charge_hours = [("2026-05-02", 12)]
        coordinator._blocked_charging_hours = [18]
        coordinator._blocked_discharging_hours = [15]
        coordinator.clear_schedule()
        assert coordinator.charge_hours == []
        assert coordinator.discharge_hours == []
        assert coordinator.pv_charge_hours == []
        assert coordinator.blocked_charging_hours == []
        assert coordinator.blocked_discharging_hours == []


class TestToggleHour:
    """Tests for the toggle_hour cycle: idle → charge → pv_charge → discharge → blocked → idle."""

    def test_idle_to_charge(self, coordinator):
        coordinator.toggle_hour(5, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.charge_hours
        assert ("2026-05-02", 5) not in coordinator.discharge_hours
        assert ("2026-05-02", 5) not in coordinator.pv_charge_hours

    def test_charge_to_pv_charge(self, coordinator):
        coordinator._charge_hours = [("2026-05-02", 5)]
        coordinator.toggle_hour(5, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.charge_hours
        assert ("2026-05-02", 5) in coordinator.pv_charge_hours
        assert ("2026-05-02", 5) not in coordinator.discharge_hours

    def test_pv_charge_to_discharge(self, coordinator):
        coordinator._pv_charge_hours = [("2026-05-02", 5)]
        coordinator.toggle_hour(5, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.pv_charge_hours
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
        assert ("2026-05-02", 5) not in coordinator.pv_charge_hours

    def test_invalid_hour_ignored(self, coordinator):
        coordinator.toggle_hour(-1, "2026-05-02")
        coordinator.toggle_hour(24, "2026-05-02")
        assert coordinator.charge_hours == []
        assert coordinator.pv_charge_hours == []


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

    def test_set_pv_charge(self, coordinator):
        coordinator.set_hour_action(5, ACTION_PV_CHARGE, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.pv_charge_hours
        assert ("2026-05-02", 5) not in coordinator.charge_hours
        assert ("2026-05-02", 5) not in coordinator.discharge_hours

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

    def test_replaces_pv_charge_with_charge(self, coordinator):
        coordinator._pv_charge_hours = [("2026-05-02", 5)]
        coordinator.set_hour_action(5, ACTION_CHARGE, "2026-05-02")
        assert ("2026-05-02", 5) not in coordinator.pv_charge_hours
        assert ("2026-05-02", 5) in coordinator.charge_hours

    def test_invalid_hour(self, coordinator):
        coordinator.set_hour_action(25, ACTION_CHARGE, "2026-05-02")
        assert coordinator.charge_hours == []

    def test_set_charge_preserves_blocked_lists(self, coordinator):
        # Setting a non-blocked action must not remove the hour from the
        # recurring blocked lists — only ACTION_BLOCKED does that.
        coordinator._blocked_charging_hours = [5]
        coordinator._blocked_discharging_hours = [5]
        coordinator.set_hour_action(5, ACTION_CHARGE, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.charge_hours
        assert 5 in coordinator.blocked_charging_hours
        assert 5 in coordinator.blocked_discharging_hours

    def test_set_discharge_preserves_blocked_lists(self, coordinator):
        coordinator._blocked_charging_hours = [5]
        coordinator._blocked_discharging_hours = [5]
        coordinator.set_hour_action(5, ACTION_DISCHARGE, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.discharge_hours
        assert 5 in coordinator.blocked_charging_hours
        assert 5 in coordinator.blocked_discharging_hours

    def test_set_pv_charge_preserves_blocked_lists(self, coordinator):
        coordinator._blocked_charging_hours = [5]
        coordinator._blocked_discharging_hours = [5]
        coordinator.set_hour_action(5, ACTION_PV_CHARGE, "2026-05-02")
        assert ("2026-05-02", 5) in coordinator.pv_charge_hours
        assert 5 in coordinator.blocked_charging_hours
        assert 5 in coordinator.blocked_discharging_hours

    def test_set_idle_preserves_blocked_lists(self, coordinator):
        coordinator._blocked_charging_hours = [5]
        coordinator._blocked_discharging_hours = [5]
        coordinator.set_hour_action(5, ACTION_IDLE, "2026-05-02")
        assert 5 in coordinator.blocked_charging_hours
        assert 5 in coordinator.blocked_discharging_hours

    def test_set_blocked_is_idempotent(self, coordinator):
        # Re-blocking an already-blocked hour must not duplicate entries.
        coordinator._blocked_charging_hours = [5]
        coordinator._blocked_discharging_hours = [5]
        coordinator.set_hour_action(5, ACTION_BLOCKED, "2026-05-02")
        assert coordinator.blocked_charging_hours == [5]
        assert coordinator.blocked_discharging_hours == [5]


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
# Cost tracking
# ======================================================================


class TestCostTracking:
    """Tests for cumulative grid cost/revenue accounting."""

    def _make_cost_coordinator(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_COST)),
        )
        coord.data = ChargeControlData()
        return coord

    def test_normalize_price_eur_unit(self):
        result = VictronChargeControlCoordinator._normalize_price_eur_per_kwh(
            "0.25",
            {"unit_of_measurement": "€/kWh"},
        )
        assert result == pytest.approx(0.25)

    def test_normalize_price_ct_unit(self):
        result = VictronChargeControlCoordinator._normalize_price_eur_per_kwh(
            "25",
            {"unit_of_measurement": "ct/kWh"},
        )
        assert result == pytest.approx(0.25)

    def test_normalize_price_invalid(self):
        result = VictronChargeControlCoordinator._normalize_price_eur_per_kwh(
            "not-a-number",
            {"unit_of_measurement": "€/kWh"},
        )
        assert result is None

    def test_initial_readings_establish_baselines(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("100"),
            "sensor.grid_feed_in_kwh": MockState("20"),
        }.get(eid)

        coord._update_cost_tracking(0.25)

        assert coord.last_grid_consumption_kwh == 100
        assert coord.last_grid_feed_in_kwh == 20
        assert coord.grid_energy_cost == 0.0
        assert coord.grid_energy_revenue == 0.0

    def test_positive_deltas_add_cost_and_revenue(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord._last_grid_consumption_kwh = 100
        coord._last_grid_feed_in_kwh = 20
        coord._grid_energy_cost = 1.0
        coord._grid_energy_revenue = 2.0
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("102"),
            "sensor.grid_feed_in_kwh": MockState("21.5"),
        }.get(eid)

        coord._update_cost_tracking(0.20)

        assert coord.grid_energy_cost == pytest.approx(1.4)
        assert coord.grid_energy_revenue == pytest.approx(2.3)
        assert coord.last_grid_consumption_kwh == 102
        assert coord.last_grid_feed_in_kwh == 21.5

    def test_negative_consumption_delta_adds_revenue(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord._last_grid_consumption_kwh = 100
        coord._grid_energy_revenue = 1.0
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("101"),
            "sensor.grid_feed_in_kwh": MockState("unknown"),
        }.get(eid)

        coord._update_cost_tracking(-0.10)

        assert coord.grid_energy_cost == pytest.approx(0.0)
        assert coord.grid_energy_revenue == pytest.approx(1.1)

    def test_signed_prices_apply_to_consumption_and_feed_in(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord._last_grid_consumption_kwh = 100
        coord._last_grid_feed_in_kwh = 20
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("101"),
            "sensor.grid_feed_in_kwh": MockState("21"),
        }.get(eid)

        coord._update_cost_tracking(0.20)

        assert coord.grid_energy_cost == pytest.approx(0.20)
        assert coord.grid_energy_revenue == pytest.approx(0.20)

        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("102"),
            "sensor.grid_feed_in_kwh": MockState("22"),
        }.get(eid)

        coord._update_cost_tracking(-0.10)

        assert coord.grid_energy_cost == pytest.approx(0.30)
        assert coord.grid_energy_revenue == pytest.approx(0.30)

    def test_negative_delta_rebaselines_without_cost(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord._last_grid_consumption_kwh = 100
        coord._grid_energy_cost = 5.0
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("2"),
            "sensor.grid_feed_in_kwh": MockState("unknown"),
        }.get(eid)

        coord._update_cost_tracking(0.30)

        assert coord.grid_energy_cost == 5.0
        assert coord.last_grid_consumption_kwh == 2

    def test_missing_price_still_tracks_energy(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord._last_grid_consumption_kwh = 100
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("101"),
            "sensor.grid_feed_in_kwh": MockState("unknown"),
        }.get(eid)

        coord._update_cost_tracking(None)

        assert coord.grid_energy_cost == 0.0
        assert coord.grid_energy_import == pytest.approx(1.0)
        assert coord.last_grid_consumption_kwh == 101

    def test_invalid_meter_state_skips_cost_tracking(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        coord._last_grid_consumption_kwh = 100
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.grid_consumption_kwh": MockState("abc"),
            "sensor.grid_feed_in_kwh": MockState("unknown"),
        }.get(eid)

        coord._update_cost_tracking(0.30)

        assert coord.grid_energy_cost == 0.0
        assert coord.last_grid_consumption_kwh == 100

    def test_restore_cost_state(self, mock_hass):
        coord = self._make_cost_coordinator(mock_hass)
        restored_at = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

        coord.restore_cost_state(
            "grid_cost",
            12.5,
            restored_at,
            last_grid_consumption_kwh=200.0,
        )
        coord.restore_cost_state(
            "grid_revenue",
            3.75,
            restored_at,
            last_grid_feed_in_kwh=50.0,
        )

        assert coord.grid_energy_cost == 12.5
        assert coord.grid_energy_revenue == 3.75
        assert coord.last_grid_consumption_kwh == 200.0
        assert coord.last_grid_feed_in_kwh == 50.0
        assert coord.last_cost_update == restored_at


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
    def test_blocked_charging_hour_without_override_returns_idle(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator._blocked_charging_hours = [3]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_discharging_hour_without_override_returns_idle(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.discharge_allowed = True
        coordinator._blocked_discharging_hours = [20]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 20, 15, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_charging_hour_with_charge_override_returns_charge(self, mock_dt_util, coordinator):
        """A per-day charge slot for a blocked hour is a user override and
        must be honored by the decision engine."""
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator._charge_hours = [("2026-04-28", 3)]
        coordinator._blocked_charging_hours = [3]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_discharging_hour_with_discharge_override_returns_discharge(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.discharge_allowed = True
        coordinator.min_soc = 10.0
        coordinator._discharge_hours = [("2026-04-28", 20)]
        coordinator._blocked_discharging_hours = [20]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 20, 15, tzinfo=timezone.utc)
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_DISCHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_blocked_both_hours_with_no_override_returns_idle(self, mock_dt_util, coordinator):
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator.discharge_allowed = True
        coordinator._blocked_charging_hours = [10]
        coordinator._blocked_discharging_hours = [10]
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)
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
# SOC Hysteresis
# ======================================================================


class TestSOCHysteresis:
    """Tests for SOC hysteresis behavior."""

    def _set_soc(self, coordinator, soc):
        state = MockState(str(soc))
        coordinator.hass.states.get.return_value = state

    def test_charge_blocked_after_hitting_max_soc(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator.soc_hysteresis = 2.0
        self._set_soc(coordinator, 95.0)
        assert coordinator._determine_action() == ACTION_IDLE
        assert coordinator._charge_blocked_by_soc is True

    def test_charge_resumes_after_soc_drops_below_hysteresis(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator.soc_hysteresis = 2.0
        self._set_soc(coordinator, 95.0)
        coordinator._determine_action()
        assert coordinator._charge_blocked_by_soc is True
        self._set_soc(coordinator, 93.0)
        assert coordinator._determine_action() == ACTION_IDLE
        assert coordinator._charge_blocked_by_soc is True
        self._set_soc(coordinator, 92.9)
        assert coordinator._determine_action() == ACTION_CHARGE
        assert coordinator._charge_blocked_by_soc is False

    def test_discharge_blocked_after_hitting_min_soc(self, coordinator):
        coordinator.control_mode = MODE_FORCE_DISCHARGE
        coordinator.discharge_allowed = True
        coordinator.min_soc = 10.0
        coordinator.soc_hysteresis = 2.0
        self._set_soc(coordinator, 10.0)
        assert coordinator._determine_action() == ACTION_IDLE
        assert coordinator._discharge_blocked_by_soc is True

    def test_discharge_resumes_after_soc_rises_above_hysteresis(self, coordinator):
        coordinator.control_mode = MODE_FORCE_DISCHARGE
        coordinator.discharge_allowed = True
        coordinator.min_soc = 10.0
        coordinator.soc_hysteresis = 2.0
        self._set_soc(coordinator, 10.0)
        coordinator._determine_action()
        assert coordinator._discharge_blocked_by_soc is True
        self._set_soc(coordinator, 12.0)
        assert coordinator._determine_action() == ACTION_IDLE
        assert coordinator._discharge_blocked_by_soc is True
        self._set_soc(coordinator, 12.1)
        assert coordinator._determine_action() == ACTION_DISCHARGE
        assert coordinator._discharge_blocked_by_soc is False

    def test_hysteresis_zero_behaves_like_before(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator.soc_hysteresis = 0.0
        self._set_soc(coordinator, 95.0)
        assert coordinator._determine_action() == ACTION_IDLE
        self._set_soc(coordinator, 94.9)
        assert coordinator._determine_action() == ACTION_CHARGE

    def test_no_hysteresis_when_soc_never_hits_limit(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator.soc_hysteresis = 2.0
        self._set_soc(coordinator, 50.0)
        assert coordinator._determine_action() == ACTION_CHARGE
        assert coordinator._charge_blocked_by_soc is False


# ======================================================================
# Action-change debounce (_resolve_published_action)
# ======================================================================


class TestActionDebounce:
    """Tests for the action-change confirmation timer.

    The decision engine is re-evaluated on every coordinator tick (~60s)
    and on every relevant entity change. A single noisy SOC reading can
    briefly flip the live action, which would otherwise cause the grid
    setpoint and the dashboard's desired_action badge to flap in
    lock-step with the sensor jitter.

    ``_resolve_published_action`` is the debounce: a new live action must
    persist for ``action_confirm_seconds`` before it is published. The
    helper is called only from the publish path, so the underlying
    ``_determine_action`` semantics are unchanged for callers that want
    the unfiltered result.
    """

    def _set_soc(self, coordinator, soc):
        coordinator.hass.states.get.return_value = MockState(str(soc))

    def test_first_call_publishes_immediately(self, coordinator):
        """The very first action must not be delayed by the debounce."""
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        self._set_soc(coordinator, 50.0)
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE

    def test_steady_action_keeps_returning_same(self, coordinator):
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        self._set_soc(coordinator, 50.0)
        # First call publishes immediately
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE
        # Subsequent identical calls keep returning the same action with no
        # pending state
        for _ in range(5):
            assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE
        assert coordinator._pending_action is None
        assert coordinator._pending_action_since is None

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_transient_flip_does_not_publish(self, mock_dt_util, coordinator):
        """A brief flip to a different action that reverts must not publish.

        This is the core user-visible scenario: SOC jitters between 94
        and 95, so the live action briefly flips to idle and back to
        charge. The debounce must suppress the idle publication.
        """
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.action_confirm_seconds = 30.0

        t0 = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = t0

        # Establish the steady state: charge is published
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE
        assert coordinator._last_published_action == ACTION_CHARGE

        # Tick +5s: live action flips to idle (e.g. SOC 95 triggered max)
        mock_dt_util.now.return_value = t0 + timedelta(seconds=5)
        assert coordinator._resolve_published_action(ACTION_IDLE) == ACTION_CHARGE
        # Pending candidate recorded, but idle is NOT yet published
        assert coordinator._pending_action == ACTION_IDLE
        assert coordinator._last_published_action == ACTION_CHARGE

        # Tick +10s: live action flips back to charge (SOC dipped to 94)
        mock_dt_util.now.return_value = t0 + timedelta(seconds=10)
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE
        # Pending state was cleared — charge is still the published action
        assert coordinator._pending_action is None
        assert coordinator._last_published_action == ACTION_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_persistent_flip_publishes_after_confirm_window(self, mock_dt_util, coordinator):
        """A new action that persists for the full confirm window is published."""
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.action_confirm_seconds = 30.0

        t0 = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = t0
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE

        # Flip to idle at t=5s
        mock_dt_util.now.return_value = t0 + timedelta(seconds=5)
        assert coordinator._resolve_published_action(ACTION_IDLE) == ACTION_CHARGE

        # 20s later (t=25s, 20s since flip) — still not confirmed
        mock_dt_util.now.return_value = t0 + timedelta(seconds=25)
        assert coordinator._resolve_published_action(ACTION_IDLE) == ACTION_CHARGE

        # 30s after the flip (t=35s) — confirmed, published
        mock_dt_util.now.return_value = t0 + timedelta(seconds=35)
        assert coordinator._resolve_published_action(ACTION_IDLE) == ACTION_IDLE
        assert coordinator._last_published_action == ACTION_IDLE
        assert coordinator._pending_action is None

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_published_action_drives_setpoint(self, mock_dt_util, coordinator):
        """_compute_setpoint called from the publish path sees the debounced action.

        The setpoint written to the grid entity must follow the debounced
        action, not the live one — otherwise the setpoint flaps even
        though the published desired_action does not.
        """
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.action_confirm_seconds = 30.0
        coordinator.charge_power = 3000.0

        t0 = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = t0
        # Publish charge
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE

        # Live flips to idle, but debounce holds the line: setpoint
        # remains the charge setpoint, not the idle setpoint.
        mock_dt_util.now.return_value = t0 + timedelta(seconds=5)
        published = coordinator._resolve_published_action(ACTION_IDLE)
        sp = coordinator._compute_setpoint(published)
        assert published == ACTION_CHARGE
        assert sp == 3000.0  # charge_power, NOT idle_setpoint

    def test_mode_off_bypasses_debounce(self, coordinator):
        """Switching to MODE_OFF must force ACTION_IDLE immediately, no debounce.

        Safety > smoothing: a user turning the system off must not be
        delayed by action-change confirmation.
        """
        coordinator.control_mode = MODE_OFF
        coordinator.action_confirm_seconds = 30.0
        # Pretend charge is currently published
        coordinator._last_published_action = ACTION_CHARGE
        coordinator._pending_action = ACTION_CHARGE
        coordinator._pending_action_since = datetime.now(tz=timezone.utc)
        # MODE_OFF -> idle now, pending state cleared
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_IDLE
        assert coordinator._last_published_action == ACTION_IDLE
        assert coordinator._pending_action is None
        assert coordinator._pending_action_since is None

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_rapid_flap_does_not_reset_confirm_timer(self, mock_dt_util, coordinator):
        """Multiple 1-tick blips to the candidate action must not reset the timer.

        Guards against a degenerate case: if a noisy sensor produces the
        candidate action for one tick, then a different value, then the
        candidate again, the original timestamp must be preserved so the
        debounce still fires.
        """
        coordinator.control_mode = MODE_FORCE_CHARGE
        coordinator.charge_allowed = True
        coordinator.action_confirm_seconds = 30.0

        t0 = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = t0
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE

        # t=5s: live action = idle (pending starts)
        mock_dt_util.now.return_value = t0 + timedelta(seconds=5)
        assert coordinator._resolve_published_action(ACTION_IDLE) == ACTION_CHARGE
        first_pending_since = coordinator._pending_action_since

        # t=10s: brief blip back to charge (resets the timer candidate,
        # but pending is cleared because live matches published)
        mock_dt_util.now.return_value = t0 + timedelta(seconds=10)
        assert coordinator._resolve_published_action(ACTION_CHARGE) == ACTION_CHARGE
        assert coordinator._pending_action is None

        # t=20s: back to idle — a fresh pending entry is created. Since
        # the previous candidate cleared, the timer restarts. This is
        # the documented behaviour: a brief blip to the prior state does
        # not count as continuous presence of the new candidate.
        mock_dt_util.now.return_value = t0 + timedelta(seconds=20)
        assert coordinator._resolve_published_action(ACTION_IDLE) == ACTION_CHARGE
        second_pending_since = coordinator._pending_action_since
        assert second_pending_since is not None
        assert second_pending_since > first_pending_since


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

    # --- Reduced-mode clamping --------------------------------------

    def test_discharge_clamped_to_reduced_zero(self, coordinator):
        """Discharge with reduced feed-in = 0W must not export at all."""
        coordinator.discharge_power = 3000.0
        coordinator._solar_surplus_mean = None
        coordinator.reduced_max_grid_feed_in = 0.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE, is_reduced=True)
        assert sp == 0.0  # not -3000

    def test_discharge_clamped_to_reduced_limit(self, coordinator):
        """Discharge export is capped at -reduced_max_grid_feed_in."""
        coordinator.discharge_power = 3000.0
        coordinator._solar_surplus_mean = None
        coordinator.reduced_max_grid_feed_in = 500.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE, is_reduced=True)
        assert sp == -500.0

    def test_discharge_clamped_to_reduced_with_solar(self, coordinator):
        """Discharge with solar surplus is still clamped to the reduced limit."""
        coordinator.discharge_power = 3000.0
        coordinator._solar_surplus_mean = 2000.0  # raw = -(3000 + 2000) = -5000
        coordinator.reduced_max_grid_feed_in = 1000.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE, is_reduced=True)
        assert sp == -1000.0

    def test_discharge_solar_only_clamped(self, coordinator):
        """Solar-only discharge is also clamped to the reduced limit."""
        coordinator.discharge_power = 3000.0
        coordinator._solar_surplus_mean = 2000.0
        coordinator._discharge_solar_only = True
        coordinator.reduced_max_grid_feed_in = 500.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE, is_reduced=True)
        assert sp == -500.0

    def test_discharge_unclamped_when_not_reduced(self, coordinator):
        """Default mode keeps the existing Discharge setpoint behavior."""
        coordinator.discharge_power = 3000.0
        coordinator._solar_surplus_mean = None
        coordinator.reduced_max_grid_feed_in = 0.0
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE, is_reduced=False)
        assert sp == -3000.0

    def test_charge_ignores_reduced_flag(self, coordinator):
        """Reduced mode only affects export-direction setpoints; Charge is import."""
        coordinator.charge_power = 3000.0
        coordinator.reduced_max_grid_feed_in = 0.0
        sp = coordinator._compute_setpoint(ACTION_CHARGE, is_reduced=True)
        assert sp == 3000.0

    def test_idle_ignores_reduced_flag(self, coordinator):
        """Idle setpoint is independent of reduced mode."""
        coordinator.idle_setpoint = 50.0
        coordinator.reduced_max_grid_feed_in = 0.0
        sp = coordinator._compute_setpoint(ACTION_IDLE, is_reduced=True)
        assert sp == 50.0


# ======================================================================
# Solar surplus (optional) — sampling, mean, and discharge setpoint
# ======================================================================


class TestSolarSurplus:
    """Tests for the optional solar surplus sensor and 15-min mean."""

    def test_entity_absent_skips_sampling(self, coordinator):
        """No solar entity configured → no samples, no mean."""
        assert coordinator.solar_surplus_entity is None
        coordinator._sample_solar_surplus()
        assert coordinator._solar_surplus_mean is None
        assert len(coordinator._solar_samples) == 0

    def test_solar_surplus_entity_round_trip(self, mock_hass):
        """Entity from config is exposed and updated via update_entity_references."""
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        assert coord.solar_surplus_entity == "sensor.solar_surplus"
        coord.update_entity_references({**MOCK_CONFIG_DATA, CONF_SOLAR_SURPLUS_ENTITY: ""})
        assert coord.solar_surplus_entity is None

    def test_sample_appends_and_computes_mean(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.hass.states.get.return_value = MockState("2000")

        for _ in range(5):
            coord._sample_solar_surplus()

        assert len(coord._solar_samples) == 5
        assert coord._solar_surplus_mean == 2000.0

    def test_unavailable_state_skipped(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.hass.states.get.return_value = MockState("unavailable")
        coord._sample_solar_surplus()
        assert coord._solar_surplus_mean is None

    def test_invalid_state_skipped(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.hass.states.get.return_value = MockState("not-a-number")
        coord._sample_solar_surplus()
        assert coord._solar_surplus_mean is None

    def test_negative_solar_clamped_to_zero(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.hass.states.get.return_value = MockState("-500")
        coord._sample_solar_surplus()
        assert coord._solar_surplus_mean == 0.0

    def test_old_samples_trimmed(self, mock_hass):
        from datetime import datetime, timedelta, timezone

        from custom_components.victron_charge_control.coordinator import dt_util

        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.hass.states.get.return_value = MockState("1000")

        # 5 old samples (>15 min ago) plus 3 fresh
        now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
        for offset_min in (20, 19, 18, 17, 16):
            coord._solar_samples.append((now - timedelta(minutes=offset_min), 100.0))
        with patch.object(dt_util, "now", return_value=now):
            coord._sample_solar_surplus()
            coord._sample_solar_surplus()
            coord._sample_solar_surplus()

        # Only the 3 fresh samples should remain
        assert len(coord._solar_samples) == 3
        # Mean of three 1000W samples
        assert coord._solar_surplus_mean == 1000.0

    def test_discharge_setpoint_with_solar_surplus(self, mock_hass):
        """Discharge = -(discharge_power + solar_surplus_mean)."""
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.discharge_power = 3000.0
        coord.min_grid_setpoint = -10000.0
        coord._discharge_solar_only = False
        coord._solar_surplus_mean = 2000.0
        sp = coord._compute_setpoint(ACTION_DISCHARGE)
        assert sp == -5000.0

    def test_discharge_setpoint_without_solar_surplus(self, coordinator):
        """Solar mean None → discharge setpoint ignores solar (legacy behavior)."""
        coordinator.discharge_power = 3000.0
        coordinator._solar_surplus_mean = None
        coordinator._discharge_solar_only = False
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE)
        assert sp == -3000.0

    def test_discharge_setpoint_clamped_by_min(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.discharge_power = 3000.0
        coord.min_grid_setpoint = -5000.0
        coord._discharge_solar_only = False
        coord._solar_surplus_mean = 5000.0  # would push raw to -8000
        sp = coord._compute_setpoint(ACTION_DISCHARGE)
        assert sp == -5000.0

    def test_discharge_solar_only_uses_only_solar(self, mock_hass):
        """When SOC is near min_soc, discharge setpoint uses only solar surplus."""
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.discharge_power = 3000.0
        coord.min_grid_setpoint = -10000.0
        coord._discharge_solar_only = True
        coord._solar_surplus_mean = 1500.0
        sp = coord._compute_setpoint(ACTION_DISCHARGE)
        assert sp == -1500.0

    def test_discharge_solar_only_with_no_samples(self, coordinator):
        coordinator.discharge_power = 3000.0
        coordinator._discharge_solar_only = True
        coordinator._solar_surplus_mean = None
        sp = coordinator._compute_setpoint(ACTION_DISCHARGE)
        assert sp == 0.0  # idle via surplus-only mode

    def test_soc_hysteresis_sets_solar_only(self, coordinator):
        """soc <= min_soc + hysteresis triggers solar-only mode (latched)."""
        coordinator.min_soc = 10.0
        coordinator.soc_hysteresis = 2.0
        coordinator._update_soc_hysteresis(12.0)  # exactly at threshold
        assert coordinator._discharge_solar_only is True

        # Latched: a 0.1% rise above min_soc + hysteresis must NOT release.
        # Without the latch this would oscillate as the SOC jitters across
        # the threshold — same root cause as the charge/discharge flaps
        # the wider Schmitt-trigger patch is fixing.
        coordinator._update_soc_hysteresis(12.1)
        assert coordinator._discharge_solar_only is True

        # Re-engages when SOC dips back below the threshold.
        coordinator._update_soc_hysteresis(11.5)
        assert coordinator._discharge_solar_only is True

        # Releases only after a full hysteresis margin above the threshold
        # (min_soc + 2*hysteresis = 14.0).
        coordinator._update_soc_hysteresis(14.1)
        assert coordinator._discharge_solar_only is False

    def test_soc_hysteresis_clears_solar_only_above_threshold(self, coordinator):
        coordinator.min_soc = 10.0
        coordinator.soc_hysteresis = 2.0
        coordinator._update_soc_hysteresis(50.0)
        assert coordinator._discharge_solar_only is False

    def test_solar_only_does_not_release_within_hysteresis_band(self, coordinator):
        """A 0.1% rise above min_soc + hysteresis must not release solar-only.

        Regression test: previously the flag was assigned unconditionally
        on every cycle (`soc <= min_soc + hysteresis`), so a SOC reading
        that alternated between 11.9 and 12.1 would toggle the flag (and
        therefore the discharge setpoint math) on every coordinator tick.
        """
        coordinator.min_soc = 10.0
        coordinator.soc_hysteresis = 2.0
        # Drive into solar-only
        coordinator._update_soc_hysteresis(12.0)
        assert coordinator._discharge_solar_only is True
        # Tiny rise — must stay latched
        coordinator._update_soc_hysteresis(12.1)
        assert coordinator._discharge_solar_only is True
        coordinator._update_soc_hysteresis(12.5)
        assert coordinator._discharge_solar_only is True
        # Drop back below threshold — still latched (re-engages)
        coordinator._update_soc_hysteresis(11.5)
        assert coordinator._discharge_solar_only is True

    def test_solar_only_releases_after_full_hysteresis_margin(self, coordinator):
        coordinator.min_soc = 10.0
        coordinator.soc_hysteresis = 2.0
        coordinator._update_soc_hysteresis(12.0)
        assert coordinator._discharge_solar_only is True
        # Release point is min_soc + 2*hysteresis = 14.0 (strictly above)
        coordinator._update_soc_hysteresis(14.0)
        assert coordinator._discharge_solar_only is True
        coordinator._update_soc_hysteresis(14.1)
        assert coordinator._discharge_solar_only is False


# ======================================================================
# PV Charging (solar-surplus split between battery and grid)
# ======================================================================


class TestPVCharging:
    """Tests for the PV Charging plan state and setpoint math."""

    def _make_solar_coordinator(self, mock_hass):
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_SOLAR)),
        )
        coord.data = ChargeControlData()
        coord.async_request_refresh = MagicMock()
        return coord

    def _set_soc_and_time(self, coord, soc_value, mock_dt_util, when):
        coord.hass.states.get.side_effect = lambda eid: {
            "sensor.battery_soc": MockState(str(soc_value)),
            "number.grid_setpoint": MockState("0"),
            "sensor.epex_spot": MockState("10"),
            "sensor.solar_surplus": MockState("2000"),
        }.get(eid)
        mock_dt_util.now.return_value = when
        mock_dt_util.as_local.side_effect = lambda x: x

    def test_default_share(self, coordinator):
        assert coordinator.pv_charge_share == DEFAULT_PV_CHARGE_SHARE

    def test_pv_charge_hours_property(self, coordinator):
        coordinator._pv_charge_hours = [("2026-05-02", 12), ("2026-05-02", 13)]
        assert coordinator.pv_charge_hours == [("2026-05-02", 12), ("2026-05-02", 13)]

    def test_setpoint_0_percent_exports_all_surplus(self, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == -2000.0

    def test_setpoint_100_percent_uses_idle_setpoint(self, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 100.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == 0.0

    def test_setpoint_50_percent_splits(self, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 50.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == -1000.0

    def test_setpoint_with_nonzero_idle_setpoint(self, mock_hass):
        """f=1 -> idle_setpoint; f=0 -> -surplus; linear in between."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 100.0
        coord.pv_charge_share = 50.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        # (1-0.5)*(-2000) + 0.5*100 = -1000 + 50 = -950
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == pytest.approx(-950.0)

    def test_setpoint_clamped_to_min(self, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord.min_grid_setpoint = -5000.0
        coord._solar_surplus_mean = 8000.0  # would push raw to -8000
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == -5000.0

    def test_setpoint_no_surplus(self, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord._solar_surplus_mean = None
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == 0.0

    def test_setpoint_battery_full_falls_back_to_idle(self, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = True
        sp = coord._compute_setpoint(ACTION_PV_CHARGE)
        assert sp == 0.0  # idle_setpoint, not -surplus

    # --- Reduced-mode clamping --------------------------------------

    def test_setpoint_clamped_to_reduced_zero(self, mock_hass):
        """PV Charge with reduced feed-in = 0W must not export at all."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord.reduced_max_grid_feed_in = 0.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE, is_reduced=True)
        assert sp == 0.0  # not -2000

    def test_setpoint_clamped_to_reduced_limit(self, mock_hass):
        """PV Charge export is capped at -reduced_max_grid_feed_in."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord.reduced_max_grid_feed_in = 500.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE, is_reduced=True)
        assert sp == -500.0

    def test_setpoint_unclamped_when_not_reduced(self, mock_hass):
        """Default mode keeps the existing PV Charge setpoint behavior."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord.reduced_max_grid_feed_in = 0.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE, is_reduced=False)
        assert sp == -2000.0

    def test_setpoint_idle_inside_reduced(self, mock_hass):
        """When the raw setpoint is already inside the reduced limit, leave it alone."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 90.0  # raw ≈ -200W, inside the 500W limit
        coord.reduced_max_grid_feed_in = 500.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE, is_reduced=True)
        # (1-0.9)*(-2000) + 0.9*0 = -200 — already > -500, no clamp needed
        assert sp == pytest.approx(-200.0)

    def test_setpoint_soc_block_inside_reduced(self, mock_hass):
        """When SOC is full the PV setpoint falls back to idle, regardless of reduced."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 0.0
        coord.reduced_max_grid_feed_in = 0.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = True
        sp = coord._compute_setpoint(ACTION_PV_CHARGE, is_reduced=True)
        assert sp == 0.0  # idle_setpoint, not -surplus

    def test_setpoint_above_reduced_limit_unchanged(self, mock_hass):
        """An exporting setpoint shallower than the reduced limit is unchanged."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.idle_setpoint = 0.0
        coord.pv_charge_share = 100.0  # raw = idle_setpoint = 0 (no export)
        coord.reduced_max_grid_feed_in = 0.0
        coord._solar_surplus_mean = 2000.0
        coord._charge_blocked_by_soc = False
        sp = coord._compute_setpoint(ACTION_PV_CHARGE, is_reduced=True)
        assert sp == 0.0

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_active(self, mock_dt_util, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = True
        coord.max_soc = 95.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 50.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_PV_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_works_when_grid_charge_disallowed(self, mock_dt_util, mock_hass):
        """PV charging is independent of charge_allowed — it never uses grid power."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = False
        coord.max_soc = 95.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 50.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_PV_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_soc_full(self, mock_dt_util, mock_hass):
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = True
        coord.max_soc = 95.0
        coord.soc_hysteresis = 2.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 96.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_no_solar_entity(self, mock_dt_util, coordinator):
        """Without a solar surplus sensor configured, pv_charge falls back to idle."""
        coordinator.control_mode = MODE_AUTO
        coordinator.charge_allowed = True
        coordinator.max_soc = 95.0
        coordinator._pv_charge_hours = [("2026-04-28", 12)]
        coordinator.hass.states.get.side_effect = lambda eid: {
            "sensor.battery_soc": MockState("50"),
            "number.grid_setpoint": MockState("0"),
            "sensor.epex_spot": MockState("10"),
        }.get(eid)
        mock_dt_util.now.return_value = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        mock_dt_util.as_local.side_effect = lambda x: x
        assert coordinator.solar_surplus_entity is None
        assert coordinator._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_ignores_blocked_charging_hours(self, mock_dt_util, mock_hass):
        """PV charging ignores blocked_charging_hours — it never draws from the grid."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = True
        coord.max_soc = 95.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        coord._blocked_charging_hours = [12]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 50.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_PV_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_pv_charge_takes_precedence_over_charge(self, mock_dt_util, mock_hass):
        """When both a pv_charge and a charge slot match, pv_charge wins."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = True
        coord.max_soc = 95.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        coord._charge_hours = [("2026-04-28", 12)]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 50.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_PV_CHARGE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_blocked_by_soc(self, mock_dt_util, mock_hass):
        """SOC-full still suppresses PV charging — battery can't absorb surplus."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = True
        coord.max_soc = 95.0
        coord.soc_hysteresis = 2.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 96.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_IDLE

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_determine_action_pv_charge_blocked_hour_and_charge_not_allowed(self, mock_dt_util, mock_hass):
        """PV charging fires even when both charge_allowed=False and hour is blocked."""
        coord = self._make_solar_coordinator(mock_hass)
        coord.control_mode = MODE_AUTO
        coord.charge_allowed = False
        coord.max_soc = 95.0
        coord._pv_charge_hours = [("2026-04-28", 12)]
        coord._blocked_charging_hours = [12]
        when = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        self._set_soc_and_time(coord, 50.0, mock_dt_util, when)
        assert coord._determine_action() == ACTION_PV_CHARGE

    def test_clean_expired_slots_trims_pv_charge(self, mock_hass):
        from custom_components.victron_charge_control.coordinator import dt_util
        coord = self._make_solar_coordinator(mock_hass)
        coord._pv_charge_hours = [("2026-04-28", 12)]
        with patch.object(dt_util, "now", return_value=datetime(2026, 4, 28, 13, 0, tzinfo=timezone.utc)):
            coord._clean_expired_slots()
        assert coord.pv_charge_hours == []


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

    @patch("custom_components.victron_charge_control.coordinator.dt_util")
    def test_pv_charge_slots_excluded_from_auto(self, mock_dt_util, coordinator):
        """Manually-set PV charging slots should not be overwritten by auto schedule."""
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 2
        coordinator.expensive_hours = 2
        coordinator.charge_price_threshold = 15.0
        coordinator.discharge_price_threshold = 20.0
        # Hour 0 would be the cheapest charge candidate; pre-mark it as pv_charge.
        coordinator._pv_charge_hours = [("2026-04-28", 0)]

        now = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
        mock_dt_util.now.return_value = now
        mock_dt_util.as_local.side_effect = lambda x: x
        mock_dt_util.parse_datetime.side_effect = lambda x: None

        prices = [
            (0, 2.0),   # cheapest but already pv_charge
            (1, 5.0),
            (2, 8.0),
            (3, 15.0),
            (4, 25.0),
            (5, 30.0),
        ]
        self._setup_epex(coordinator, prices)

        coordinator.calculate_auto_schedule()

        # pv_charge slot preserved and not co-opted into charge/discharge
        assert ("2026-04-28", 0) in coordinator.pv_charge_hours
        assert ("2026-04-28", 0) not in coordinator.charge_hours
        assert ("2026-04-28", 0) not in coordinator.discharge_hours
        # Auto picks the next-cheapest hour for charge instead
        assert ("2026-04-28", 1) in coordinator.charge_hours


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


class TestSafetyStartupGrace:
    """Tests for the safety watchdog startup grace period.

    Covers the bug where the watchdog would spuriously switch the system
    to OFF on every Home Assistant restart because the first coordinator
    refresh typically runs before upstream Victron / EPEX integrations
    have published a real state.
    """

    @pytest.mark.asyncio
    async def test_grace_period_initialised_in_constructor(self, mock_hass, mock_config_entry):
        """Coordinator starts with a future grace deadline equal to grace_seconds."""
        mock_config_entry.options = {CONF_SAFETY_STARTUP_GRACE_SECONDS: 60}
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.async_request_refresh = MagicMock()

        assert coord.safety_startup_grace_seconds == 60
        assert coord._safety_startup_deadline is not None

        from custom_components.victron_charge_control.coordinator import dt_util
        remaining = (coord._safety_startup_deadline - dt_util.now()).total_seconds()
        assert 55 <= remaining <= 61

    @pytest.mark.asyncio
    async def test_grace_period_default_when_option_missing(self, mock_hass, mock_config_entry):
        mock_config_entry.options = {}
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)

        assert coord.safety_startup_grace_seconds == DEFAULT_SAFETY_STARTUP_GRACE_SECONDS

    @pytest.mark.asyncio
    async def test_grace_period_zero_disables_grace(self, mock_hass, mock_config_entry):
        mock_config_entry.options = {CONF_SAFETY_STARTUP_GRACE_SECONDS: 0}
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)

        assert coord.safety_startup_grace_seconds == 0
        assert coord._safety_startup_deadline is None

    @pytest.mark.asyncio
    async def test_first_safe_tick_clears_grace_deadline(self, coordinator):
        """A safe tick exits the grace period early."""
        from custom_components.victron_charge_control.coordinator import dt_util
        coordinator._safety_startup_deadline = dt_util.now() + timedelta(seconds=60)
        coordinator.hass.states.get.return_value = MockState("50")
        coordinator.control_mode = MODE_AUTO
        coordinator.async_request_refresh = MagicMock()
        coordinator.hass.services.async_call = AsyncMock()

        await coordinator._async_update_data()

        assert coordinator._safety_startup_deadline is None
        assert coordinator.control_mode == MODE_AUTO
        # No persistent notification was raised
        notification_calls = [
            c
            for c in coordinator.hass.services.async_call.call_args_list
            if c.args and c.args[0] == "persistent_notification"
        ]
        assert notification_calls == []

    @pytest.mark.asyncio
    async def test_unavailable_during_grace_does_not_switch_off(self, coordinator):
        """Unavailable critical entities are tolerated while the grace is active."""
        from custom_components.victron_charge_control.coordinator import dt_util
        coordinator._safety_startup_deadline = dt_util.now() + timedelta(seconds=60)
        coordinator.control_mode = MODE_AUTO

        def side_effect(entity_id):
            if entity_id == "sensor.battery_soc":
                return MockState("unavailable")
            return MockState("50")

        coordinator.hass.states.get.side_effect = side_effect
        coordinator.async_request_refresh = MagicMock()
        coordinator.hass.services.async_call = AsyncMock()

        await coordinator._async_update_data()

        assert coordinator.control_mode == MODE_AUTO
        # Grace deadline was NOT cleared, so the watchdog stays in grace
        assert coordinator._safety_startup_deadline is not None
        # No persistent notification was raised
        notification_calls = [
            c
            for c in coordinator.hass.services.async_call.call_args_list
            if c.args and c.args[0] == "persistent_notification"
        ]
        assert notification_calls == []

    @pytest.mark.asyncio
    async def test_unavailable_after_grace_still_switches_off(self, coordinator):
        """Once the grace period has elapsed, unavailable entities trip the watchdog."""
        from custom_components.victron_charge_control.coordinator import dt_util
        coordinator._safety_startup_deadline = dt_util.now() - timedelta(seconds=1)
        coordinator.control_mode = MODE_AUTO

        def side_effect(entity_id):
            if entity_id == "sensor.battery_soc":
                return MockState("unavailable")
            return MockState("50")

        coordinator.hass.states.get.side_effect = side_effect
        coordinator.async_request_refresh = MagicMock()
        coordinator.hass.services.async_call = AsyncMock()

        await coordinator._async_update_data()

        assert coordinator.control_mode == MODE_OFF
        # Grace deadline was cleared by the OFF switch
        assert coordinator._safety_startup_deadline is None
        # Persistent notification was created
        notification_calls = [
            c
            for c in coordinator.hass.services.async_call.call_args_list
            if c.args and c.args[0] == "persistent_notification"
        ]
        assert len(notification_calls) == 1

    @pytest.mark.asyncio
    async def test_grace_zero_trips_watchdog_immediately(self, coordinator):
        """A configured grace of 0 disables the grace window entirely."""
        from custom_components.victron_charge_control.coordinator import dt_util
        coordinator._safety_startup_deadline = None
        coordinator.control_mode = MODE_AUTO

        def side_effect(entity_id):
            if entity_id == "sensor.battery_soc":
                return MockState("unavailable")
            return MockState("50")

        coordinator.hass.states.get.side_effect = side_effect
        coordinator.async_request_refresh = MagicMock()
        coordinator.hass.services.async_call = AsyncMock()

        await coordinator._async_update_data()

        assert coordinator.control_mode == MODE_OFF

    @pytest.mark.asyncio
    async def test_shutdown_clears_grace_deadline(self, coordinator):
        coordinator._safety_startup_deadline = MagicMock()  # non-None placeholder

        await coordinator.async_shutdown()

        assert coordinator._safety_startup_deadline is None


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

        # Difference is 20W, within the 150W deadband
        await coordinator._apply_setpoint(3020.0)

        coordinator.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_setpoint_skips_within_150w_deadband(self, coordinator):
        """100W diff is still skipped (below the new 150W default)."""
        coordinator.hass.states.get.return_value = MockState("3000")
        coordinator._last_applied_setpoint = 3000.0
        await coordinator._apply_setpoint(3100.0)
        coordinator.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_setpoint_applies_above_200w_deadband(self, coordinator):
        """300W diff exceeds the 200W deadband and triggers a service call."""
        coordinator.hass.states.get.return_value = MockState("3000")
        coordinator._last_applied_setpoint = 3000.0
        await coordinator._apply_setpoint(3300.0)
        coordinator.hass.services.async_call.assert_called_once()

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

    @pytest.mark.asyncio
    async def test_apply_setpoint_bypasses_deadband_on_idle(self, coordinator):
        """Transitioning to idle must always write the idle setpoint.

        Regression: previously, a transition from PV-Charging (or any
        other state) to Idle could leave the entity holding the old
        setpoint whenever the difference fell within ``setpoint_deadband``.
        With ``action=ACTION_IDLE`` the deadband is bypassed and the
        idle setpoint is always written.
        """
        coordinator.hass.states.get.return_value = MockState("-1500")
        coordinator._last_applied_setpoint = -1500.0
        coordinator.idle_setpoint = 0.0

        # Sanity check: without the action override, the 1500W diff
        # exceeds the deadband so the write would still happen.
        # The interesting case is the small residual (e.g. -50W)
        # which the deadband would otherwise skip.
        coordinator.hass.states.get.return_value = MockState("-50")
        coordinator._last_applied_setpoint = -50.0

        # No action override: deadband blocks the small residual.
        await coordinator._apply_setpoint(0.0)
        coordinator.hass.services.async_call.assert_not_called()

        # With ACTION_IDLE the deadband is bypassed and the write fires.
        await coordinator._apply_setpoint(0.0, action=ACTION_IDLE)
        coordinator.hass.services.async_call.assert_called_once_with(
            "number",
            "set_value",
            {"entity_id": "number.grid_setpoint", "value": 0.0},
            blocking=True,
        )
        assert coordinator._last_applied_setpoint == 0.0

    @pytest.mark.asyncio
    async def test_apply_setpoint_respects_deadband_when_charging(self, coordinator):
        """Non-idle actions must still honour the deadband (regression guard)."""
        coordinator.hass.states.get.return_value = MockState("3000")
        coordinator._last_applied_setpoint = 3000.0

        # 100W diff is within the default 200W deadband: must be skipped
        # for non-idle actions.
        await coordinator._apply_setpoint(3100.0, action=ACTION_CHARGE)
        coordinator.hass.services.async_call.assert_not_called()

        # And still applied above the deadband.
        await coordinator._apply_setpoint(3300.0, action=ACTION_CHARGE)
        coordinator.hass.services.async_call.assert_called_once()


# ======================================================================
# Grid feed-in control
# ======================================================================


class TestIsReducedFeedInMode:
    """Tests for the _is_reduced_feed_in_mode helper."""

    def test_disabled_returns_false(self, coordinator):
        coordinator.grid_feed_in_control_enabled = False
        coordinator.grid_feed_in_price_threshold = 10.0
        assert coordinator._is_reduced_feed_in_mode(5.0) is False

    def test_no_price_returns_false(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        coordinator.grid_feed_in_price_threshold = 10.0
        assert coordinator._is_reduced_feed_in_mode(None) is False

    def test_below_threshold_returns_true(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        coordinator.grid_feed_in_price_threshold = 10.0
        assert coordinator._is_reduced_feed_in_mode(5.0) is True

    def test_at_threshold_returns_false(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        coordinator.grid_feed_in_price_threshold = 10.0
        assert coordinator._is_reduced_feed_in_mode(10.0) is False

    def test_above_threshold_returns_false(self, coordinator):
        coordinator.grid_feed_in_control_enabled = True
        coordinator.grid_feed_in_price_threshold = 10.0
        assert coordinator._is_reduced_feed_in_mode(15.0) is False

    def test_negative_price_with_disabled_returns_false(self, coordinator):
        coordinator.grid_feed_in_control_enabled = False
        coordinator.grid_feed_in_price_threshold = 10.0
        assert coordinator._is_reduced_feed_in_mode(-50.0) is False


class TestGetCurrentPriceCt:
    """Tests for the _get_current_price_ct helper."""

    def test_returns_none_when_unavailable(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("unavailable")
        assert coordinator._get_current_price_ct() is None

    def test_returns_none_when_unknown(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("unknown")
        assert coordinator._get_current_price_ct() is None

    def test_returns_none_when_state_missing(self, coordinator):
        coordinator.hass.states.get.return_value = None
        assert coordinator._get_current_price_ct() is None

    def test_returns_none_for_unparseable_state(self, coordinator):
        coordinator.hass.states.get.return_value = MockState("not-a-number")
        assert coordinator._get_current_price_ct() is None

    def test_ct_unit_passes_through(self, coordinator):
        coordinator.hass.states.get.return_value = MockState(
            "12.5", {"unit_of_measurement": "ct/kWh"}
        )
        assert coordinator._get_current_price_ct() == 12.5

    def test_eur_unit_converted_to_ct(self, coordinator):
        coordinator.hass.states.get.return_value = MockState(
            "0.125", {"unit_of_measurement": "EUR/kWh"}
        )
        assert coordinator._get_current_price_ct() == pytest.approx(12.5)


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


# ======================================================================
# DC coupled PV feed-in control
# ======================================================================


class TestDcCoupledFeedInControl:
    """Tests for the linked DC-coupled PV feed-in switch actuation."""

    @pytest.fixture
    def dc_coord(self, mock_hass):
        """Coordinator with the DC feed-in entity configured."""
        coord = VictronChargeControlCoordinator(
            mock_hass,
            MockConfigEntry(data=dict(MOCK_CONFIG_DATA_WITH_DC_FEED_IN)),
        )
        coord.data = ChargeControlData()
        coord.async_request_refresh = MagicMock()
        return coord

    @pytest.mark.asyncio
    async def test_inert_when_feature_off(self, dc_coord):
        """No switch call when control_dc_coupled_feed_in is False."""
        dc_coord.control_dc_coupled_feed_in = False
        dc_coord.grid_feed_in_control_enabled = True
        dc_coord.control_mode = MODE_AUTO
        await dc_coord._apply_dc_coupled_feed_in(is_reduced=True)
        dc_coord.hass.services.async_call.assert_not_called()
        assert dc_coord._last_applied_dc_feed_in_state is None

    @pytest.mark.asyncio
    async def test_inert_when_grid_feed_in_control_off(self, dc_coord):
        """No switch call when grid_feed_in_control_enabled is False."""
        dc_coord.control_dc_coupled_feed_in = True
        dc_coord.grid_feed_in_control_enabled = False
        dc_coord.control_mode = MODE_AUTO
        await dc_coord._apply_dc_coupled_feed_in(is_reduced=True)
        dc_coord.hass.services.async_call.assert_not_called()
        assert dc_coord._last_applied_dc_feed_in_state is None

    @pytest.mark.asyncio
    async def test_inert_when_mode_off(self, dc_coord):
        """No switch call when control_mode is OFF."""
        dc_coord.control_dc_coupled_feed_in = True
        dc_coord.grid_feed_in_control_enabled = True
        dc_coord.control_mode = MODE_OFF
        await dc_coord._apply_dc_coupled_feed_in(is_reduced=True)
        dc_coord.hass.services.async_call.assert_not_called()
        assert dc_coord._last_applied_dc_feed_in_state is None

    @pytest.mark.asyncio
    async def test_inert_when_no_linked_entity(self, coordinator):
        """No switch call when no linked entity is configured."""
        coordinator.control_dc_coupled_feed_in = True
        coordinator.grid_feed_in_control_enabled = True
        coordinator.control_mode = MODE_AUTO
        assert coordinator.dc_coupled_pv_feed_in_entity is None
        await coordinator._apply_dc_coupled_feed_in(is_reduced=True)
        coordinator.hass.services.async_call.assert_not_called()
        assert coordinator._last_applied_dc_feed_in_state is None

    @pytest.mark.asyncio
    async def test_reduced_turns_off(self, dc_coord):
        """Reduced mode → switch.turn_off called once."""
        dc_coord.control_dc_coupled_feed_in = True
        dc_coord.grid_feed_in_control_enabled = True
        dc_coord.control_mode = MODE_AUTO
        dc_coord._last_applied_dc_feed_in_state = None
        dc_coord.hass.states.get.return_value = MockState("on")

        await dc_coord._apply_dc_coupled_feed_in(is_reduced=True)

        dc_coord.hass.services.async_call.assert_called_once_with(
            "switch",
            "turn_off",
            {"entity_id": "switch.dc_pv_feed_in"},
            blocking=True,
        )
        assert dc_coord._last_applied_dc_feed_in_state is False

    @pytest.mark.asyncio
    async def test_normal_turns_on(self, dc_coord):
        """Normal mode → switch.turn_on called once."""
        dc_coord.control_dc_coupled_feed_in = True
        dc_coord.grid_feed_in_control_enabled = True
        dc_coord.control_mode = MODE_AUTO
        dc_coord._last_applied_dc_feed_in_state = None
        dc_coord.hass.states.get.return_value = MockState("off")

        await dc_coord._apply_dc_coupled_feed_in(is_reduced=False)

        dc_coord.hass.services.async_call.assert_called_once_with(
            "switch",
            "turn_on",
            {"entity_id": "switch.dc_pv_feed_in"},
            blocking=True,
        )
        assert dc_coord._last_applied_dc_feed_in_state is True

    @pytest.mark.asyncio
    async def test_dedup_skips_redundant_call(self, dc_coord):
        """Same desired state as last applied → no service call."""
        dc_coord.control_dc_coupled_feed_in = True
        dc_coord.grid_feed_in_control_enabled = True
        dc_coord.control_mode = MODE_AUTO
        dc_coord._last_applied_dc_feed_in_state = False
        dc_coord.hass.states.get.return_value = MockState("off")

        await dc_coord._apply_dc_coupled_feed_in(is_reduced=True)

        dc_coord.hass.services.async_call.assert_not_called()
        assert dc_coord._last_applied_dc_feed_in_state is False

    @pytest.mark.asyncio
    async def test_unavailable_entity_skipped(self, dc_coord):
        """Unavailable linked entity → warn + skip, state unchanged."""
        dc_coord.control_dc_coupled_feed_in = True
        dc_coord.grid_feed_in_control_enabled = True
        dc_coord.control_mode = MODE_AUTO
        dc_coord._last_applied_dc_feed_in_state = None
        dc_coord.hass.states.get.return_value = MockState("unavailable")

        await dc_coord._apply_dc_coupled_feed_in(is_reduced=True)

        dc_coord.hass.services.async_call.assert_not_called()
        assert dc_coord._last_applied_dc_feed_in_state is None


# ======================================================================
# Replan hours
# ======================================================================


class TestReplanHours:
    """Tests for the user-configurable replan hours."""

    def test_set_replan_hours_normalizes(self, coordinator):
        """set_replan_hours sorts, dedupes, and clamps to 0..23."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ) as track:
            track.side_effect = lambda *a, **kw: MagicMock()
            coordinator.set_replan_hours([20, 3, 3, 25, -1, 18])
        assert coordinator.replan_hours == [3, 18, 20]

    def test_set_replan_hours_empty_disables_listener(self, coordinator):
        """Setting an empty list clears any installed listener."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ) as track:
            track.side_effect = lambda *a, **kw: MagicMock()
            coordinator.set_replan_hours([3, 20])
            assert coordinator._replan_unsub is not None
            unsub = coordinator._replan_unsub
            coordinator.set_replan_hours([])
        assert coordinator.replan_hours == []
        unsub.assert_called_once()
        assert coordinator._replan_unsub is None

    def test_set_replan_hours_resubscribes(self, coordinator):
        """Changing the hours re-installs the listener."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ) as track:
            track.side_effect = lambda *a, **kw: MagicMock()
            coordinator.set_replan_hours([3])
            first = coordinator._replan_unsub
            coordinator.set_replan_hours([3, 20])
            second = coordinator._replan_unsub
        assert first is not second
        first.assert_called_once()
        assert coordinator.replan_hours == [3, 20]

    def test_set_replan_hours_noop_on_same_value(self, coordinator):
        """Setting the same hours does not re-subscribe."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ) as track:
            track.side_effect = lambda *a, **kw: MagicMock()
            coordinator.set_replan_hours([3])
            unsub = coordinator._replan_unsub
            coordinator.set_replan_hours([3])
        assert coordinator._replan_unsub is unsub
        unsub.assert_not_called()

    def test_set_replan_hours_passes_top_of_hour(self, coordinator):
        """The installed listener fires at HH:00:00 for each hour."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ) as track:
            track.side_effect = lambda *a, **kw: MagicMock()
            coordinator.set_replan_hours([3, 18, 20])
            kwargs = track.call_args.kwargs
        assert kwargs["hour"] == (3, 18, 20)
        assert kwargs["minute"] == 0
        assert kwargs["second"] == 0

    def test_replan_callback_auto_mode_recalculates(self, coordinator):
        """The replan callback runs calculate_auto_schedule in auto mode."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            coordinator.set_replan_hours([3])
        coordinator.control_mode = MODE_AUTO
        coordinator._clean_expired_slots = MagicMock()
        coordinator.calculate_auto_schedule = MagicMock()
        coordinator.async_request_refresh = MagicMock()

        coordinator._run_replan()

        coordinator._clean_expired_slots.assert_called_once()
        coordinator.calculate_auto_schedule.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    def test_replan_callback_manual_mode_resets(self, coordinator):
        """The replan callback clears manual hours in manual mode."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            coordinator.set_replan_hours([3])
        coordinator.control_mode = MODE_MANUAL
        coordinator._clean_expired_slots = MagicMock()
        coordinator._charge_hours = [("2026-05-02", 1)]
        coordinator._discharge_hours = [("2026-05-02", 20)]
        coordinator.async_request_refresh = MagicMock()

        coordinator._run_replan()

        assert coordinator._charge_hours == []
        assert coordinator._discharge_hours == []
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_shutdown_unsubs_replan(self, coordinator):
        """async_shutdown unsubs the replan listener."""
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ) as track:
            track.side_effect = lambda *a, **kw: MagicMock()
            coordinator.set_replan_hours([3])
            unsub = coordinator._replan_unsub
        await coordinator.async_shutdown()
        unsub.assert_called_once()
        assert coordinator._replan_unsub is None


# ======================================================================
# Plan persistence (Store)
# ======================================================================


class TestPlanPersistenceSave:
    """The Store is written on every plan mutation."""

    @pytest.mark.asyncio
    async def test_set_charge_hours_writes_store(self, coordinator, mock_store):
        coordinator.set_charge_hours([("2026-05-02", 3), ("2026-05-02", 1)])
        # The fire-and-forget save is scheduled via hass.async_create_task.
        # In sync test contexts the helper returns a MagicMock and the
        # coroutine is never awaited, so we drive the save directly.
        await coordinator._async_save_schedule()
        assert len(mock_store.save_calls) == 1
        payload = mock_store.save_calls[-1]
        assert payload["charge_hours"] == [["2026-05-02", 1], ["2026-05-02", 3]]
        assert payload["discharge_hours"] == []
        assert payload["pv_charge_hours"] == []
        assert payload["blocked_charging_hours"] == []
        assert payload["blocked_discharging_hours"] == []
        assert payload["last_schedule_update"] is not None

    @pytest.mark.asyncio
    async def test_set_discharge_hours_writes_store(self, coordinator, mock_store):
        coordinator.set_discharge_hours([("2026-05-02", 20)])
        await coordinator._async_save_schedule()
        assert len(mock_store.save_calls) == 1
        payload = mock_store.save_calls[-1]
        assert payload["discharge_hours"] == [["2026-05-02", 20]]

    @pytest.mark.asyncio
    async def test_set_blocked_charging_hours_writes_store(self, coordinator, mock_store):
        coordinator.set_blocked_charging_hours([18, 19, 20])
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["blocked_charging_hours"] == [18, 19, 20]
        assert payload["blocked_discharging_hours"] == []

    @pytest.mark.asyncio
    async def test_set_blocked_discharging_hours_writes_store(self, coordinator, mock_store):
        coordinator.set_blocked_discharging_hours([15, 16])
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["blocked_discharging_hours"] == [15, 16]

    @pytest.mark.asyncio
    async def test_toggle_hour_writes_store(self, coordinator, mock_store):
        coordinator.toggle_hour(5, "2026-05-02")
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["charge_hours"] == [["2026-05-02", 5]]

    @pytest.mark.asyncio
    async def test_set_hour_action_pv_charge_writes_store(self, coordinator, mock_store):
        coordinator.set_hour_action(7, ACTION_PV_CHARGE, "2026-05-02")
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["pv_charge_hours"] == [["2026-05-02", 7]]

    @pytest.mark.asyncio
    async def test_set_hour_action_blocked_writes_store(self, coordinator, mock_store):
        coordinator.set_hour_action(8, ACTION_BLOCKED, "2026-05-02")
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["blocked_charging_hours"] == [8]
        assert payload["blocked_discharging_hours"] == [8]

    @pytest.mark.asyncio
    async def test_clear_schedule_writes_empty_store(self, coordinator, mock_store):
        coordinator._charge_hours = [("2026-05-02", 1)]
        coordinator._discharge_hours = [("2026-05-02", 20)]
        coordinator._pv_charge_hours = [("2026-05-02", 12)]
        coordinator._blocked_charging_hours = [18]
        coordinator._blocked_discharging_hours = [15]
        coordinator.clear_schedule()
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["charge_hours"] == []
        assert payload["discharge_hours"] == []
        assert payload["pv_charge_hours"] == []
        assert payload["blocked_charging_hours"] == []
        assert payload["blocked_discharging_hours"] == []

    @pytest.mark.asyncio
    async def test_calculate_auto_schedule_writes_store(
        self, coordinator, mock_store, mock_hass
    ):
        """The auto scheduler also persists its result."""
        from custom_components.victron_charge_control.coordinator import (
            dt_util,
        )

        # Mock the current time so the test EPEX data is in the future.
        # Without this, real ``dt_util.now()`` is later than the
        # ``base_date`` used by ``make_epex_data`` and the auto-scheduler
        # filters out everything as "in the past".
        with patch(
            "custom_components.victron_charge_control.coordinator.dt_util"
        ) as mock_dt_util:
            now = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
            mock_dt_util.now.return_value = now
            mock_dt_util.as_local.side_effect = lambda x: x
            mock_dt_util.parse_datetime.side_effect = lambda x: None

            # Mock EPEX state
            epex_state = MockState("5.0", {"data": make_epex_data(
                [(0, 1.0), (1, 2.0), (2, 30.0), (3, 31.0), (4, 5.0)]
            )})

            def states_get(entity_id):
                if entity_id == coordinator._epex_spot_entity:
                    return epex_state
                return MockState("50")  # battery SOC

            mock_hass.states.get.side_effect = states_get
            coordinator.control_mode = MODE_AUTO
            coordinator.cheapest_hours = 2
            coordinator.expensive_hours = 2
            coordinator.charge_price_threshold = 10.0
            coordinator.discharge_price_threshold = 20.0

            coordinator.calculate_auto_schedule()

        await coordinator._async_save_schedule()

        assert len(mock_store.save_calls) == 1
        payload = mock_store.save_calls[-1]
        # Cheapest 2 hours: 0 and 1
        assert ["2026-04-28", 0] in payload["charge_hours"]
        assert ["2026-04-28", 1] in payload["charge_hours"]
        # Most expensive 2 hours: 3 and 2
        assert ["2026-04-28", 2] in payload["discharge_hours"]
        assert ["2026-04-28", 3] in payload["discharge_hours"]

    @pytest.mark.asyncio
    async def test_save_failure_does_not_raise(self, coordinator, mock_store):
        """A failing Store must not propagate to the caller."""
        async def boom(_data):
            raise OSError("disk full")
        mock_store.async_save = boom
        # _async_save_schedule swallows exceptions and only logs a warning.
        await coordinator._async_save_schedule()  # must not raise

    @pytest.mark.asyncio
    async def test_save_serializes_timestamp_as_iso(
        self, coordinator, mock_store
    ):
        from custom_components.victron_charge_control.coordinator import (
            dt_util,
        )

        coordinator._last_schedule_update = dt_util.now()
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert isinstance(payload["last_schedule_update"], str)
        # ISO 8601 with timezone offset
        assert "T" in payload["last_schedule_update"]

    @pytest.mark.asyncio
    async def test_save_serializes_none_timestamp(self, coordinator, mock_store):
        coordinator._last_schedule_update = None
        await coordinator._async_save_schedule()
        payload = mock_store.save_calls[-1]
        assert payload["last_schedule_update"] is None


class TestPlanPersistenceLoad:
    """The Store is read on startup and applied to the coordinator."""

    @pytest.mark.asyncio
    async def test_empty_store_leaves_state_untouched(self, coordinator, mock_store):
        """An empty Store must not wipe or auto-replan the coordinator."""
        from custom_components.victron_charge_control.coordinator import (
            dt_util,
        )

        mock_store.async_load = AsyncMock(return_value=None)
        coordinator._charge_hours = [("2026-05-02", 1)]
        coordinator._discharge_hours = [("2026-05-02", 20)]
        coordinator._blocked_charging_hours = [18]
        coordinator._blocked_discharging_hours = [15]
        coordinator._pv_charge_hours = [("2026-05-02", 12)]

        await coordinator._async_load_schedule()

        # State must be preserved, not wiped
        assert coordinator._charge_hours == [("2026-05-02", 1)]
        assert coordinator._discharge_hours == [("2026-05-02", 20)]
        assert coordinator._pv_charge_hours == [("2026-05-02", 12)]
        assert coordinator._blocked_charging_hours == [18]
        assert coordinator._blocked_discharging_hours == [15]
        # Flag stays false because nothing was actually applied
        assert coordinator._schedule_loaded_from_store is False

    @pytest.mark.asyncio
    async def test_loaded_store_restores_slots(self, coordinator, mock_store):
        mock_store.async_load = AsyncMock(return_value={
            "charge_hours": [["2026-05-02", 1], ["2026-05-02", 3]],
            "discharge_hours": [["2026-05-02", 20]],
            "pv_charge_hours": [["2026-05-02", 12]],
            "blocked_charging_hours": [18, 19, 20],
            "blocked_discharging_hours": [15, 16],
            "last_schedule_update": "2026-05-02T10:30:00+00:00",
        })

        await coordinator._async_load_schedule()

        assert coordinator._charge_hours == [
            ("2026-05-02", 1),
            ("2026-05-02", 3),
        ]
        assert coordinator._discharge_hours == [("2026-05-02", 20)]
        assert coordinator._pv_charge_hours == [("2026-05-02", 12)]
        assert coordinator._blocked_charging_hours == [18, 19, 20]
        assert coordinator._blocked_discharging_hours == [15, 16]
        assert coordinator._last_schedule_update is not None
        assert coordinator._last_schedule_update.year == 2026
        assert coordinator._schedule_loaded_from_store is True

    @pytest.mark.asyncio
    async def test_load_drops_malformed_slots(self, coordinator, mock_store):
        """Invalid slot entries must be silently dropped, not crash."""
        mock_store.async_load = AsyncMock(return_value={
            "charge_hours": [
                ["2026-05-02", 1],          # valid
                ["not-a-date", 5],           # bad date
                ["2026-05-02", 25],          # bad hour
                ["2026-05-02", "3"],         # hour not int
                "not a list",                # not a list
                ["2026-05-02", 2, "extra"],  # too many fields
            ],
            "discharge_hours": [],
            "pv_charge_hours": [],
            "blocked_charging_hours": [50, -1, 5, "5", 3],
            "blocked_discharging_hours": [],
            "last_schedule_update": None,
        })

        await coordinator._async_load_schedule()

        # Only the valid slot survived
        assert coordinator._charge_hours == [("2026-05-02", 1)]
        # Hours: 50 and -1 dropped, "5" dropped, duplicates deduped -> 3, 5
        assert coordinator._blocked_charging_hours == [3, 5]
        # _last_schedule_update untouched (None in payload)
        assert coordinator._last_schedule_update is None

    @pytest.mark.asyncio
    async def test_load_with_non_dict_payload(self, coordinator, mock_store):
        """A list or string payload must be treated like an empty Store."""
        mock_store.async_load = AsyncMock(return_value=["unexpected", "list"])
        coordinator._charge_hours = [("2026-05-02", 1)]

        await coordinator._async_load_schedule()

        # State preserved, no crash
        assert coordinator._charge_hours == [("2026-05-02", 1)]
        assert coordinator._schedule_loaded_from_store is False

    @pytest.mark.asyncio
    async def test_load_handles_store_read_error(self, coordinator, mock_store):
        """A failing Store.async_load must not crash the integration."""
        mock_store.async_load = AsyncMock(side_effect=OSError("disk full"))
        coordinator._charge_hours = [("2026-05-02", 1)]

        # Must not raise
        await coordinator._async_load_schedule()

        # State preserved
        assert coordinator._charge_hours == [("2026-05-02", 1)]
        assert coordinator._schedule_loaded_from_store is False


class TestAsyncSetupNoReplan:
    """async_setup must NOT auto-replan on restart."""

    @pytest.mark.asyncio
    async def test_setup_does_not_replan_in_auto_mode(
        self, mock_hass, mock_config_entry, mock_store
    ):
        """The previous auto-replan block must be gone: a restart in
        auto mode does not call calculate_auto_schedule, and the
        previous plan from the Store is restored as-is.
        """
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        # Pre-populate the Store with a real plan
        mock_store.async_load = AsyncMock(return_value={
            "charge_hours": [["2026-05-02", 1], ["2026-05-02", 2]],
            "discharge_hours": [["2026-05-02", 20]],
            "pv_charge_hours": [],
            "blocked_charging_hours": [18],
            "blocked_discharging_hours": [15],
            "last_schedule_update": None,
        })

        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.control_mode = MODE_AUTO  # restored by RestoreEntity
        coord.calculate_auto_schedule = MagicMock()
        coord.async_request_refresh = AsyncMock()

        # Stub the time/state listeners so async_setup can run cleanly
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        # The auto-replan must NOT have been called
        coord.calculate_auto_schedule.assert_not_called()

        # The Store was loaded and applied
        mock_store.async_load.assert_awaited()
        assert coord._charge_hours == [("2026-05-02", 1), ("2026-05-02", 2)]
        assert coord._discharge_hours == [("2026-05-02", 20)]
        assert coord._blocked_charging_hours == [18]
        assert coord._blocked_discharging_hours == [15]
        assert coord._schedule_loaded_from_store is True

        # First refresh was triggered so entities pick up the restored state
        coord.async_request_refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_setup_with_empty_store_keeps_state_and_does_not_replan(
        self, mock_hass, mock_config_entry, mock_store
    ):
        """A fresh install (empty Store) must not auto-replan either."""
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        mock_store.async_load = AsyncMock(return_value=None)
        # Simulate RestoreEntity having restored blocked hours
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.control_mode = MODE_AUTO
        coord._blocked_charging_hours = [18, 19]
        coord._blocked_discharging_hours = [15]
        coord.calculate_auto_schedule = MagicMock()
        coord.async_request_refresh = AsyncMock()

        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        coord.calculate_auto_schedule.assert_not_called()
        # RestoreEntity-restored state must be preserved
        assert coord._blocked_charging_hours == [18, 19]
        assert coord._blocked_discharging_hours == [15]
        # No actual load happened
        assert coord._schedule_loaded_from_store is False
        coord.async_request_refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_setup_does_not_replan_in_off_mode(
        self, mock_hass, mock_config_entry, mock_store
    ):
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        mock_store.async_load = AsyncMock(return_value=None)
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.calculate_auto_schedule = MagicMock()
        coord.async_request_refresh = AsyncMock()

        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        coord.calculate_auto_schedule.assert_not_called()


class TestAsyncSetupPersistsAfterRestoreEntity:
    """Migration path: RestoreEntity sets state, then any mutation saves."""

    @pytest.mark.asyncio
    async def test_legacy_blocked_hours_preserved_when_store_empty(
        self, mock_hass, mock_config_entry, mock_store
    ):
        """If RestoreEntity populated blocked hours but the Store is
        empty (pre-persistence migration), the load must not overwrite
        the restored state.
        """
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        mock_store.async_load = AsyncMock(return_value=None)
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        # RestoreEntity restored these in text.py's async_added_to_hass
        coord._blocked_charging_hours = [18, 19, 20]
        coord._blocked_discharging_hours = [15, 16]
        coord._replan_hours = [3, 20]
        coord.control_mode = MODE_AUTO
        coord.async_request_refresh = AsyncMock()

        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        # RestoreEntity-restored state is untouched
        assert coord._blocked_charging_hours == [18, 19, 20]
        assert coord._blocked_discharging_hours == [15, 16]
        assert coord._replan_hours == [3, 20]

    @pytest.mark.asyncio
    async def test_next_mutation_writes_store_after_migration(
        self, mock_hass, mock_config_entry, mock_store
    ):
        """After a fresh restart on a migrated install, the very first
        user action (e.g. changing blocked hours) writes the Store, so
        the next restart goes through the normal load path.
        """
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        mock_store._data = None
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord._blocked_charging_hours = [18]
        coord.async_request_refresh = AsyncMock()

        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        # First mutation. The save is fire-and-forget; in async test
        # contexts ``hass.async_create_task`` schedules the coroutine on
        # the loop and the test must drive it to completion
        # deterministically.
        coord.set_blocked_charging_hours([18, 19, 20, 21])
        await coord._async_save_schedule()

        assert len(mock_store.save_calls) == 1
        payload = mock_store.save_calls[-1]
        assert payload["blocked_charging_hours"] == [18, 19, 20, 21]


class TestSetupRaceWithTextEntityRestore:
    """Reproduces the bug where the text entities' ``async_added_to_hass``
    call setters that trigger Store saves, and those saves run before
    ``async_setup`` ever loads from the Store — wiping the persisted
    plan with empty charge/discharge slots.

    Real flow on HA restart:
      1. Coordinator is created (in-memory state empty).
      2. ``forward_entry_setups`` runs — for each ``TextEntity`` HA calls
         ``async_added_to_hass``, which calls e.g.
         ``coordinator.set_blocked_charging_hours(...)``.
      3. That setter schedules a fire-and-forget save via
         ``hass.async_create_task(self._async_save_schedule())``.
      4. ``async_setup`` runs and ``await``s
         ``_async_load_schedule()``. The very first ``await`` in
         ``async_setup`` lets the event loop run the pending save
         coroutine, which writes the (empty charge_hours + restored
         blocked_hours) state to the Store.
      5. ``_async_load_schedule`` then reads the Store and gets the
         empty plan that the text-entity save just wrote.

    The fix is to suspend saves during setup so step 3 is a no-op.
    """

    @pytest.mark.asyncio
    async def test_text_entity_setter_during_setup_does_not_clobber_store(
        self, mock_hass, mock_config_entry, mock_store
    ):
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        # Pre-populated Store with a real plan that must survive restart
        mock_store._data = {
            "charge_hours": [["2026-05-02", 1], ["2026-05-02", 2]],
            "discharge_hours": [["2026-05-02", 20]],
            "pv_charge_hours": [["2026-05-02", 12]],
            "blocked_charging_hours": [18, 19, 20],
            "blocked_discharging_hours": [15, 16],
            "last_schedule_update": None,
        }

        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.async_request_refresh = AsyncMock()

        # Simulate the three text entities restoring their values via
        # setters — this is exactly what happens during
        # ``forward_entry_setups`` in real HA. Each setter schedules a
        # fire-and-forget save (which the conftest records so we can
        # drain it and observe the result).
        coord.set_blocked_charging_hours([18, 19, 20])
        coord.set_blocked_discharging_hours([15, 16])
        coord.set_replan_hours([18])

        # Drain the scheduled saves to faithfully reproduce the in-HA
        # event-loop yield between ``forward_entry_setups`` and
        # ``async_setup`` — in real HA the pending save coroutines run
        # here, and without the fix they write the (still empty)
        # charge/discharge/pv_charge slots to the Store, clobbering
        # the persisted plan.
        if mock_hass._scheduled_tasks:
            await asyncio.gather(*mock_hass._scheduled_tasks, return_exceptions=True)

        # With the fix in place, the suppression means the saves were
        # never scheduled and the Store still has the pre-populated
        # plan. Without the fix, the Store was just overwritten with
        # empty slots — which is exactly the bug.
        assert mock_store._data["charge_hours"] == [
            ["2026-05-02", 1],
            ["2026-05-02", 2],
        ], (
            "Text-entity restore clobbered the persisted plan with "
            "empty charge_hours — the suspension is not in place."
        )
        assert mock_store._data["discharge_hours"] == [["2026-05-02", 20]]
        assert mock_store._data["pv_charge_hours"] == [["2026-05-02", 12]]

        # Now run async_setup — this loads the plan from the Store and
        # must restore every slot exactly.
        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        assert coord._charge_hours == [("2026-05-02", 1), ("2026-05-02", 2)]
        assert coord._discharge_hours == [("2026-05-02", 20)]
        assert coord._pv_charge_hours == [("2026-05-02", 12)]
        assert coord._blocked_charging_hours == [18, 19, 20]
        assert coord._blocked_discharging_hours == [15, 16]
        assert coord._schedule_loaded_from_store is True

    @pytest.mark.asyncio
    async def test_saves_are_re_enabled_after_setup(
        self, mock_hass, mock_config_entry, mock_store
    ):
        """The suppression must be cleared by the end of ``async_setup``,
        so the first real user mutation after startup is persisted.
        """
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        mock_store._data = None
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.async_request_refresh = AsyncMock()

        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        assert coord._suspend_save is False

        # First real user action. The save is fire-and-forget; in
        # async test contexts ``hass.async_create_task`` schedules the
        # coroutine on the loop and the test must yield once for it to
        # run.
        coord.set_charge_hours([("2026-05-02", 5)])
        # Drive the save synchronously so the assertion is
        # deterministic without depending on event-loop scheduling.
        await coord._async_save_schedule()
        assert len(mock_store.save_calls) == 1
        assert mock_store.save_calls[-1]["charge_hours"] == [["2026-05-02", 5]]

    @pytest.mark.asyncio
    async def test_saves_suspended_during_setup_no_user_path(
        self, mock_hass, mock_config_entry, mock_store
    ):
        """End-to-end: nothing written to the Store while setup runs,
        even if every text entity fires its restore setter. The test
        drains the scheduled save coroutines so the assertion actually
        observes what would happen in real HA.
        """
        from custom_components.victron_charge_control.coordinator import (
            VictronChargeControlCoordinator,
        )

        mock_store._data = None
        coord = VictronChargeControlCoordinator(mock_hass, mock_config_entry)
        coord.async_request_refresh = AsyncMock()

        # Simulate text entities' restore
        coord.set_blocked_charging_hours([18, 19, 20, 21, 22, 23])
        coord.set_blocked_discharging_hours([15, 16, 17])
        coord.set_replan_hours([18])
        # Drain pending saves so we can assert on the actual outcome
        # (without the fix the Store would be written to here).
        if mock_hass._scheduled_tasks:
            await asyncio.gather(
                *mock_hass._scheduled_tasks, return_exceptions=True
            )
        # No save may have happened — all those calls are suppressed.
        assert len(mock_store.save_calls) == 0

        with patch(
            "custom_components.victron_charge_control.coordinator.async_track_state_change_event"
        ), patch(
            "custom_components.victron_charge_control.coordinator.async_track_time_change"
        ):
            await coord.async_setup()

        # Still no save during setup itself
        assert len(mock_store.save_calls) == 0
