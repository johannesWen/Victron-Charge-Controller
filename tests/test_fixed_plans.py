"""Tests for fixed plans (recurring user-defined hour patterns).

Covers the pure merge helper, persistence round-trips, the coordinator
mutators/apply-retract logic, the new services, and the new entities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    DOMAIN,
    MODE_AUTO,
    MODE_MANUAL,
    STORAGE_VERSION,
)
from custom_components.victron_charge_control.coordinator import (
    ChargeControlData,
)
from custom_components.victron_charge_control.persistence import (
    apply_loaded_plan,
    build_plan_payload,
    deserialize_active_fixed_plan,
    deserialize_fixed_plans,
    serialize_fixed_plans,
)
from custom_components.victron_charge_control.schedule import (
    MAX_FIXED_PLAN_NAME_LENGTH,
    apply_fixed_plan,
    normalize_fixed_plan,
    normalize_fixed_plan_name,
)
from custom_components.victron_charge_control.select import ActiveFixedPlanSelect
from custom_components.victron_charge_control.sensor import FixedPlansSensor
from custom_components.victron_charge_control.services import (
    SERVICE_ADD_FIXED_PLAN,
    SERVICE_REMOVE_FIXED_PLAN,
    SERVICE_SET_FIXED_PLAN_HOUR,
    SERVICE_SET_FIXED_PLAN_NAME,
    async_setup_services,
)
from tests.conftest import MockState, make_epex_data

TODAY = "2026-04-28"
TOMORROW = "2026-04-29"


def _mock_now():
    return datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)


def _mock_dt_util(mock_dt_util):
    """Configure the patched coordinator dt_util for deterministic dates."""
    now = _mock_now()
    mock_dt_util.now.return_value = now
    mock_dt_util.as_local.side_effect = lambda x: x
    mock_dt_util.parse_datetime.side_effect = lambda x: None
    return now


DT_UTIL_PATCH = "custom_components.victron_charge_control.coordinator.dt_util"


# ======================================================================
# Pure merge logic (schedule.apply_fixed_plan)
# ======================================================================


class TestApplyFixedPlan:
    def test_empty_plan_returns_inputs(self):
        charge = [("2026-04-28", 2)]
        result = apply_fixed_plan(charge, [], [], {"charge_hours": [], "discharge_hours": [], "pv_charge_hours": []}, [TODAY])
        assert result[0] == charge
        assert result[1] == []
        assert result[2] == []
        assert result[3] == []

    def test_none_plan_returns_inputs(self):
        charge = [(TODAY, 2)]
        result = apply_fixed_plan(charge, [], [], None, [TODAY])
        assert result[0] == charge
        assert result[3] == []

    def test_charge_hours_added_for_each_date(self):
        charge, discharge, pv, applied = apply_fixed_plan(
            [], [], [], {"charge_hours": [2, 3], "discharge_hours": [], "pv_charge_hours": []},
            [TODAY, TOMORROW],
        )
        assert (TODAY, 2) in charge
        assert (TOMORROW, 3) in charge
        assert applied == [(TODAY, 2), (TODAY, 3), (TOMORROW, 2), (TOMORROW, 3)]

    def test_fixed_extends_auto_hours(self):
        charge, _, _, _ = apply_fixed_plan(
            [(TODAY, 0)], [], [], {"charge_hours": [5], "discharge_hours": [], "pv_charge_hours": []},
            [TODAY],
        )
        assert charge == [(TODAY, 0), (TODAY, 5)]

    def test_fixed_wins_over_auto_charge(self):
        """A fixed discharge hour removes the auto charge hour in the same slot."""
        charge, discharge, pv, _ = apply_fixed_plan(
            [(TODAY, 5)], [], [], {"charge_hours": [], "discharge_hours": [5], "pv_charge_hours": []},
            [TODAY],
        )
        assert charge == []
        assert discharge == [(TODAY, 5)]

    def test_fixed_wins_over_auto_pv(self):
        charge, discharge, pv, _ = apply_fixed_plan(
            [], [(TODAY, 5)], [(TODAY, 5)], {"charge_hours": [], "discharge_hours": [5], "pv_charge_hours": []},
            [TODAY],
        )
        assert pv == []
        assert discharge == [(TODAY, 5)]
        assert charge == []

    def test_pv_precedence_within_plan(self):
        """When the same hour is in several buckets, pv_charge wins."""
        charge, discharge, pv, _ = apply_fixed_plan(
            [], [], [], {"charge_hours": [5], "discharge_hours": [5], "pv_charge_hours": [5]},
            [TODAY],
        )
        assert pv == [(TODAY, 5)]
        assert charge == []
        assert discharge == []

    def test_other_dates_untouched(self):
        charge, _, _, applied = apply_fixed_plan(
            [("2026-05-01", 2)], [], [], {"charge_hours": [2], "discharge_hours": [], "pv_charge_hours": []},
            [TODAY],
        )
        assert charge == [(TODAY, 2), ("2026-05-01", 2)]
        assert applied == [(TODAY, 2)]

    def test_invalid_hours_filtered(self):
        charge, _, _, applied = apply_fixed_plan(
            [], [], [], {"charge_hours": [24, -1, 5], "discharge_hours": [], "pv_charge_hours": []},
            [TODAY],
        )
        assert charge == [(TODAY, 5)]
        assert applied == [(TODAY, 5)]


class TestNormalizeFixedPlanName:
    def test_strips_and_truncates(self):
        assert normalize_fixed_plan_name("  Weekend  ") == "Weekend"
        assert normalize_fixed_plan_name("0123456789AB") == "0123456789"
        assert normalize_fixed_plan_name("") == ""

    def test_non_string_dropped(self):
        assert normalize_fixed_plan_name(None) == ""
        assert normalize_fixed_plan_name(42) == ""

    def test_max_length_constant(self):
        assert MAX_FIXED_PLAN_NAME_LENGTH == 10


class TestNormalizeFixedPlan:
    def test_missing_keys_default_empty(self):
        plan = normalize_fixed_plan({"charge_hours": [1]})
        assert plan == {"charge_hours": [1], "discharge_hours": [], "pv_charge_hours": [], "name": ""}

    def test_non_dict_returns_empty(self):
        assert normalize_fixed_plan(None) == {"charge_hours": [], "discharge_hours": [], "pv_charge_hours": [], "name": ""}

    def test_invalid_bucket_types_dropped(self):
        plan = normalize_fixed_plan({"charge_hours": "5", "pv_charge_hours": [3, "x", 30]})
        assert plan["charge_hours"] == []
        assert plan["pv_charge_hours"] == [3]


# ======================================================================
# Persistence
# ======================================================================


class TestFixedPlanPersistence:
    def test_serialize_stringifies_and_sorts_keys(self):
        result = serialize_fixed_plans({2: {"charge_hours": [1]}, 1: {"pv_charge_hours": [3]}})
        assert list(result.keys()) == ["1", "2"]
        assert result["2"]["charge_hours"] == [1]
        assert result["1"]["pv_charge_hours"] == [3]

    def test_deserialize_drops_invalid(self):
        result = deserialize_fixed_plans({"1": {"charge_hours": [5, 99]}, "x": {}, "-2": {}, "3": "bad"})
        assert list(result.keys()) == [1]
        assert result[1]["charge_hours"] == [5]

    def test_deserialize_non_dict(self):
        assert deserialize_fixed_plans(None) == {}

    def test_deserialize_active_plan(self):
        plans = {1: {}, 2: {}}
        assert deserialize_active_fixed_plan(2, plans) == 2
        assert deserialize_active_fixed_plan("1", plans) == 1
        assert deserialize_active_fixed_plan(9, plans) is None
        assert deserialize_active_fixed_plan(None, plans) is None
        assert deserialize_active_fixed_plan(True, plans) is None

    def test_payload_roundtrip(self):
        payload = build_plan_payload(
            charge_hours=[(TODAY, 1)],
            discharge_hours=[],
            pv_charge_hours=[],
            blocked_charging_hours=[],
            blocked_discharging_hours=[],
            fixed_plans={1: {"charge_hours": [4], "discharge_hours": [5], "pv_charge_hours": []}},
            active_fixed_plan=1,
            last_schedule_update=None,
        )
        assert payload["fixed_plans"] == {"1": {"charge_hours": [4], "discharge_hours": [5], "pv_charge_hours": [], "name": ""}}
        assert payload["active_fixed_plan"] == 1
        applied = apply_loaded_plan(payload)
        assert applied["fixed_plans"] == {1: {"charge_hours": [4], "discharge_hours": [5], "pv_charge_hours": [], "name": ""}}
        assert applied["active_fixed_plan"] == 1

    def test_v1_store_without_fixed_plans_loads(self):
        payload = {
            "charge_hours": [[TODAY, 1]],
            "discharge_hours": [],
            "pv_charge_hours": [],
            "blocked_charging_hours": [],
            "blocked_discharging_hours": [],
            "last_schedule_update": None,
        }
        applied = apply_loaded_plan(payload)
        assert applied["fixed_plans"] == {}
        assert applied["active_fixed_plan"] is None
        assert applied["charge_hours"] == [(TODAY, 1)]

    def test_storage_version_unchanged_additive_keys(self):
        """Fixed plans are additive keys on a v1 payload.

        Bumping the version would make Home Assistant's Store call the
        unimplemented migrate function and drop existing plans, so the
        load path must tolerate absent keys instead.
        """
        assert STORAGE_VERSION == 1

    def test_coordinator_save_and_load_roundtrip(self, coordinator, mock_store):
        import asyncio

        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        asyncio.run(coordinator._async_save_schedule())

        assert mock_store._data["fixed_plans"]["1"]["charge_hours"] == [4]
        assert mock_store._data["active_fixed_plan"] == 1

        # Wipe in-memory state and restore from the store.
        coordinator._fixed_plans = {}
        coordinator._active_fixed_plan = None
        asyncio.run(coordinator._async_load_schedule())

        assert coordinator.fixed_plans == {1: {"charge_hours": [4], "discharge_hours": [], "pv_charge_hours": [], "name": ""}}
        assert coordinator.active_fixed_plan == 1


# ======================================================================
# Refresh debouncer (responsive card edits)
# ======================================================================


class TestRefreshDebouncer:
    def test_short_cooldown_for_service_triggered_refreshes(self, coordinator):
        """Dashboard edits must confirm within ~1s, not HA's default 10s."""
        assert coordinator._debounced_refresh.cooldown == 1
        assert coordinator._debounced_refresh.immediate is True


# ======================================================================
# Coordinator: fixed plan management
# ======================================================================


class TestSetFixedPlanHour:
    def test_creates_plan_and_sets_hour(self, coordinator):
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        assert coordinator.fixed_plans == {1: {"charge_hours": [4], "discharge_hours": [], "pv_charge_hours": [], "name": ""}}

    def test_action_cycles_clear_other_buckets(self, coordinator):
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_PV_CHARGE)
        assert coordinator.fixed_plans[1]["charge_hours"] == []
        assert coordinator.fixed_plans[1]["pv_charge_hours"] == [4]
        coordinator.set_fixed_plan_hour(1, 4, ACTION_IDLE)
        assert coordinator.fixed_plans[1]["pv_charge_hours"] == []

    def test_inactive_plan_does_not_touch_schedule(self, coordinator):
        coordinator._charge_hours = [(TODAY, 2)]
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        assert coordinator._charge_hours == [(TODAY, 2)]
        assert coordinator.active_fixed_plan is None

    @patch(DT_UTIL_PATCH)
    def test_editing_active_plan_does_not_replan(self, mock_dt_util, coordinator):
        """Editing a plan must not re-plan; changes apply at the next replan."""
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        assert (TODAY, 4) in coordinator._charge_hours
        coordinator.set_fixed_plan_hour(1, 4, ACTION_IDLE)
        # The previously applied hour stays until the next replan hour or
        # Recalculate click re-applies the plan.
        assert (TODAY, 4) in coordinator._charge_hours
        assert coordinator.fixed_plans[1]["charge_hours"] == []

    def test_invalid_plan_ignored(self, coordinator):
        coordinator.set_fixed_plan_hour(0, 4, ACTION_CHARGE)
        coordinator.set_fixed_plan_hour(9, 4, ACTION_CHARGE)
        assert coordinator.fixed_plans == {}

    def test_invalid_hour_ignored(self, coordinator):
        coordinator.set_fixed_plan_hour(1, 24, ACTION_CHARGE)
        assert coordinator.fixed_plans == {}

    def test_invalid_action_ignored(self, coordinator):
        coordinator.set_fixed_plan_hour(1, 4, "blocked")
        assert coordinator.fixed_plans == {}


class TestFixedPlanNaming:
    @patch(DT_UTIL_PATCH)
    def test_set_and_clear_name(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_fixed_plan_name(1, "Weekend")
        assert coordinator.fixed_plans[1]["name"] == "Weekend"
        coordinator.set_fixed_plan_name(1, "   ")
        assert coordinator.fixed_plans[1]["name"] == ""

    @patch(DT_UTIL_PATCH)
    def test_name_truncated_to_10_chars(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_name(1, "0123456789AB")
        assert coordinator.fixed_plans[1]["name"] == "0123456789"

    @patch(DT_UTIL_PATCH)
    def test_name_keeps_hours_and_does_not_replan(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        coordinator.set_fixed_plan_name(1, "Daily")
        assert (TODAY, 4) in coordinator._charge_hours
        assert coordinator.fixed_plans[1] == {
            "charge_hours": [4],
            "discharge_hours": [],
            "pv_charge_hours": [],
            "name": "Daily",
        }

    @patch(DT_UTIL_PATCH)
    def test_name_auto_creates_plan(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_name(3, "Sunday")
        assert coordinator.fixed_plans == {3: {"charge_hours": [], "discharge_hours": [], "pv_charge_hours": [], "name": "Sunday"}}

    def test_invalid_plan_ignored(self, coordinator):
        coordinator.set_fixed_plan_name(0, "x")
        coordinator.set_fixed_plan_name(9, "x")
        assert coordinator.fixed_plans == {}

    @patch(DT_UTIL_PATCH)
    def test_name_survives_persistence_roundtrip(self, mock_dt_util, coordinator, mock_store):
        import asyncio

        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_name(1, "Weekend")
        asyncio.run(coordinator._async_save_schedule())
        coordinator._fixed_plans = {}
        asyncio.run(coordinator._async_load_schedule())
        assert coordinator.fixed_plans[1]["name"] == "Weekend"

    @patch(DT_UTIL_PATCH)
    def test_snapshot_exposes_name(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_name(2, "Nightly")
        snapshot = coordinator._build_snapshot(
            action=ACTION_IDLE,
            setpoint=0.0,
            price_view=TestFixedPlanSnapshot._price_view(),
            feed_in_active=False,
            applied_feed_in=None,
        )
        assert snapshot.fixed_plans[2]["name"] == "Nightly"

    @patch(DT_UTIL_PATCH)
    def test_sensor_attributes_expose_name(self, mock_dt_util, coordinator, mock_config_entry):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_name(1, "Weekend")
        coordinator.data = coordinator._build_snapshot(
            action=ACTION_IDLE,
            setpoint=0.0,
            price_view=TestFixedPlanSnapshot._price_view(),
            feed_in_active=False,
            applied_feed_in=None,
        )
        sensor = FixedPlansSensor(coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes
        assert attrs["plans"]["1"]["name"] == "Weekend"


class TestAddRemoveFixedPlan:
    def test_add_returns_sequential_numbers(self, coordinator):
        assert coordinator.add_fixed_plan() == 1
        assert coordinator.add_fixed_plan() == 2
        assert sorted(coordinator.fixed_plans.keys()) == [1, 2]

    def test_add_refills_lowest_free_number(self, coordinator):
        coordinator.add_fixed_plan()
        coordinator.add_fixed_plan()
        coordinator.remove_fixed_plan(1)
        assert coordinator.add_fixed_plan() == 1

    def test_add_respects_cap(self, coordinator):
        from custom_components.victron_charge_control.const import MAX_FIXED_PLANS

        for _ in range(MAX_FIXED_PLANS):
            coordinator.add_fixed_plan()
        assert coordinator.add_fixed_plan() is None
        assert len(coordinator.fixed_plans) == MAX_FIXED_PLANS

    def test_remove_unknown_plan_noop(self, coordinator):
        coordinator.remove_fixed_plan(3)
        assert coordinator.fixed_plans == {}

    @patch(DT_UTIL_PATCH)
    def test_remove_active_plan_deactivates(self, mock_dt_util, coordinator, mock_hass):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        coordinator.hass.states.get.return_value = None
        coordinator.control_mode = MODE_MANUAL
        coordinator.remove_fixed_plan(1)
        assert coordinator.fixed_plans == {}
        assert coordinator.active_fixed_plan is None
        # The merged hour is retracted on removal.
        assert (TODAY, 4) not in coordinator._charge_hours


class TestFixedPlanActivation:
    @patch(DT_UTIL_PATCH)
    def test_activate_applies_to_today_and_tomorrow(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_fixed_plan_hour(1, 22, ACTION_DISCHARGE)
        coordinator.set_active_fixed_plan(1)
        assert (TODAY, 4) in coordinator._charge_hours
        assert (TOMORROW, 4) in coordinator._charge_hours
        assert (TODAY, 22) in coordinator._discharge_hours
        assert (TOMORROW, 22) in coordinator._discharge_hours
        assert coordinator.active_fixed_plan == 1

    def test_activate_unknown_plan_rejected(self, coordinator):
        coordinator.set_active_fixed_plan(5)
        assert coordinator.active_fixed_plan is None

    def test_activate_same_plan_noop(self, coordinator):
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        coordinator.set_active_fixed_plan(1)
        assert coordinator.active_fixed_plan == 1

    @patch(DT_UTIL_PATCH)
    def test_deactivate_restores_base(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator._charge_hours = [(TODAY, 2)]
        coordinator._pv_charge_hours = [(TODAY, 6)]
        coordinator.set_fixed_plan_hour(1, 2, ACTION_DISCHARGE)
        coordinator.set_active_fixed_plan(1)
        # Fixed wins over the auto charge slot at hour 2.
        assert (TODAY, 2) in coordinator._discharge_hours
        assert (TODAY, 2) not in coordinator._charge_hours

        coordinator.set_active_fixed_plan(None)
        # Base restored: auto charge back, fixed discharge gone.
        assert (TODAY, 2) in coordinator._charge_hours
        assert (TODAY, 2) not in coordinator._discharge_hours
        assert (TODAY, 6) in coordinator._pv_charge_hours
        assert coordinator.active_fixed_plan is None

    def test_deactivate_without_snapshot_keeps_existing_slots(self, coordinator):
        # Post-restart state: no applied-slot tracking yet (it is
        # in-memory only), so previously merged hours cannot be
        # identified and stay until the next replan/recalc cleans them.
        coordinator._fixed_plans = {1: {"charge_hours": [4], "discharge_hours": [], "pv_charge_hours": []}}
        coordinator._active_fixed_plan = 1
        coordinator._charge_hours = [(TODAY, 4)]
        coordinator.set_active_fixed_plan(None)
        assert coordinator.active_fixed_plan is None
        assert coordinator._fixed_plan_applied_slots == []
        assert (TODAY, 4) in coordinator._charge_hours

    @patch(DT_UTIL_PATCH)
    def test_switch_plan_replaces_hours(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_fixed_plan_hour(2, 4, ACTION_DISCHARGE)
        coordinator.set_fixed_plan_hour(2, 8, ACTION_PV_CHARGE)
        coordinator.set_active_fixed_plan(1)
        assert (TODAY, 4) in coordinator._charge_hours

        coordinator.set_active_fixed_plan(2)
        assert coordinator.active_fixed_plan == 2
        assert (TODAY, 4) not in coordinator._charge_hours
        assert (TODAY, 4) in coordinator._discharge_hours
        assert (TODAY, 8) in coordinator._pv_charge_hours

    @patch(DT_UTIL_PATCH)
    def test_deactivate_in_auto_mode_recalculates(self, mock_dt_util, coordinator, mock_hass):
        _mock_dt_util(mock_dt_util)
        coordinator.control_mode = MODE_AUTO
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        # No EPEX entity: recalc is a no-op but must not crash.
        mock_hass.states.get.return_value = None
        coordinator.set_active_fixed_plan(None)
        assert coordinator.active_fixed_plan is None


# ======================================================================
# Coordinator: integration with planning steps
# ======================================================================


class TestFixedPlanWithAutoSchedule:
    def _setup_epex(self, coordinator, prices):
        coordinator.hass.states.get.return_value = MockState("10.0", {"data": make_epex_data(prices)})

    @patch(DT_UTIL_PATCH)
    def test_auto_schedule_extends_fixed_plan(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 2
        coordinator.expensive_hours = 2
        coordinator.charge_price_threshold = 15.0
        coordinator.discharge_price_threshold = 20.0
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)

        prices = [(0, 5.0), (1, 8.0), (2, 12.0), (3, 15.0), (4, 25.0), (5, 30.0)]
        self._setup_epex(coordinator, prices)

        coordinator.calculate_auto_schedule()

        # Auto picks hours 0/1 for charge, 4/5 for discharge.
        assert (TODAY, 0) in coordinator._charge_hours
        assert (TODAY, 1) in coordinator._charge_hours
        assert (TODAY, 5) in coordinator._discharge_hours
        # Fixed charge hour 4 is added and wins over auto discharge.
        assert (TODAY, 4) in coordinator._charge_hours
        assert (TODAY, 4) not in coordinator._discharge_hours

    @patch(DT_UTIL_PATCH)
    def test_fixed_hours_applied_to_tomorrow_too(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 1
        coordinator.expensive_hours = 1
        coordinator.charge_price_threshold = 15.0
        coordinator.discharge_price_threshold = 20.0
        coordinator.set_fixed_plan_hour(1, 7, ACTION_PV_CHARGE)
        coordinator.set_active_fixed_plan(1)

        self._setup_epex(coordinator, [(0, 5.0), (5, 30.0)])

        coordinator.calculate_auto_schedule()

        assert (TODAY, 7) in coordinator._pv_charge_hours
        assert (TOMORROW, 7) in coordinator._pv_charge_hours

    @patch(DT_UTIL_PATCH)
    def test_replan_auto_mode_reapplies_fixed(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.control_mode = MODE_AUTO
        coordinator.cheapest_hours = 1
        coordinator.expensive_hours = 1
        coordinator.charge_price_threshold = 15.0
        coordinator.discharge_price_threshold = 20.0
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)

        self._setup_epex(coordinator, [(0, 5.0), (1, 8.0)])

        coordinator._run_replan(_mock_now())

        assert (TODAY, 0) in coordinator._charge_hours
        assert (TODAY, 4) in coordinator._charge_hours
        assert (TOMORROW, 4) in coordinator._charge_hours

    @patch(DT_UTIL_PATCH)
    def test_replan_manual_mode_clears_and_reapplies(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.control_mode = MODE_MANUAL
        coordinator._charge_hours = [("2026-05-01", 3)]
        coordinator._discharge_hours = [(TOMORROW, 9)]
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)

        coordinator._run_replan(_mock_now())

        # Manual hours cleared, fixed plan hours re-applied.
        assert coordinator._charge_hours == [(TODAY, 4), (TOMORROW, 4)]
        assert coordinator._discharge_hours == []

    @patch(DT_UTIL_PATCH)
    def test_clear_schedule_reapplies_active_plan(self, mock_dt_util, coordinator):
        _mock_dt_util(mock_dt_util)
        coordinator.control_mode = MODE_MANUAL
        coordinator._charge_hours = [("2026-05-01", 3)]
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        coordinator.clear_schedule()
        assert coordinator._charge_hours == [(TODAY, 4), (TOMORROW, 4)]
        assert coordinator._discharge_hours == []
        assert coordinator._pv_charge_hours == []

    def test_no_active_plan_auto_unchanged(self, coordinator):
        coordinator.control_mode = MODE_MANUAL
        coordinator._charge_hours = [(TODAY, 2)]
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.calculate_auto_schedule()
        assert coordinator._charge_hours == [(TODAY, 2)]


# ======================================================================
# Snapshot
# ======================================================================


class TestFixedPlanSnapshot:
    @staticmethod
    def _price_view():
        from custom_components.victron_charge_control.coordinator import EpexPriceView

        return EpexPriceView(
            current_price=10.0,
            eur_per_kwh=0.10,
            attributes={},
            prices_today=[],
            prices_tomorrow=[],
        )

    def test_snapshot_exposes_plans_and_active(self, coordinator):
        coordinator.set_fixed_plan_hour(1, 4, ACTION_CHARGE)
        coordinator.set_active_fixed_plan(1)
        snapshot = coordinator._build_snapshot(
            action=ACTION_IDLE,
            setpoint=0.0,
            price_view=self._price_view(),
            feed_in_active=False,
            applied_feed_in=None,
        )
        assert snapshot.fixed_plans == {1: {"charge_hours": [4], "discharge_hours": [], "pv_charge_hours": [], "name": ""}}
        assert snapshot.active_fixed_plan == 1

    def test_snapshot_empty_defaults(self, coordinator):
        coordinator.data = ChargeControlData()
        snapshot = coordinator._build_snapshot(
            action=ACTION_IDLE,
            setpoint=0.0,
            price_view=self._price_view(),
            feed_in_active=False,
            applied_feed_in=None,
        )
        assert snapshot.fixed_plans == {}
        assert snapshot.active_fixed_plan is None


# ======================================================================
# Services
# ======================================================================


class TestFixedPlanServices:
    @pytest.mark.asyncio
    async def test_set_fixed_plan_hour_handler(self, mock_hass, coordinator):
        from unittest.mock import MagicMock

        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_SET_FIXED_PLAN_HOUR:
                handler = call.args[2]
                break

        assert handler is not None

        service_call = MagicMock()
        service_call.data = {"plan": 2, "hour": 5, "action": ACTION_CHARGE}
        await handler(service_call)

        assert coordinator.fixed_plans == {2: {"charge_hours": [5], "discharge_hours": [], "pv_charge_hours": [], "name": ""}}

    @pytest.mark.asyncio
    async def test_add_fixed_plan_handler(self, mock_hass, coordinator):
        from unittest.mock import MagicMock

        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_ADD_FIXED_PLAN:
                handler = call.args[2]
                break

        service_call = MagicMock()
        await handler(service_call)

        assert list(coordinator.fixed_plans.keys()) == [1]

    @pytest.mark.asyncio
    async def test_remove_fixed_plan_handler(self, mock_hass, coordinator):
        from unittest.mock import MagicMock

        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        coordinator.add_fixed_plan()
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_REMOVE_FIXED_PLAN:
                handler = call.args[2]
                break

        service_call = MagicMock()
        service_call.data = {"plan": 1}
        await handler(service_call)

        assert coordinator.fixed_plans == {}

    @pytest.mark.asyncio
    async def test_set_fixed_plan_name_handler(self, mock_hass, coordinator):
        from unittest.mock import MagicMock

        mock_hass.data[DOMAIN] = {"entry1": coordinator}
        await async_setup_services(mock_hass)

        handler = None
        for call in mock_hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_SET_FIXED_PLAN_NAME:
                handler = call.args[2]
                break

        assert handler is not None

        service_call = MagicMock()
        service_call.data = {"plan": 1, "name": "  Weekend  "}
        await handler(service_call)

        assert coordinator.fixed_plans[1]["name"] == "Weekend"

    def test_set_fixed_plan_name_schema_coerces_and_strips(self):
        from custom_components.victron_charge_control.services import SCHEMA_SET_FIXED_PLAN_NAME

        data = SCHEMA_SET_FIXED_PLAN_NAME({"plan": "2", "name": " My Plan "})
        assert data == {"plan": 2, "name": "My Plan"}
        with pytest.raises(Exception):
            SCHEMA_SET_FIXED_PLAN_NAME({"plan": 1})
        with pytest.raises(Exception):
            SCHEMA_SET_FIXED_PLAN_NAME({"plan": 1, "name": 5})

    def test_set_fixed_plan_hour_schema_rejects_bad_action(self):
        from custom_components.victron_charge_control.services import SCHEMA_SET_FIXED_PLAN_HOUR

        with pytest.raises(Exception):
            SCHEMA_SET_FIXED_PLAN_HOUR({"plan": 1, "hour": 5, "action": "blocked"})

    def test_remove_fixed_plan_schema_bounds(self):
        from custom_components.victron_charge_control.services import SCHEMA_REMOVE_FIXED_PLAN

        with pytest.raises(Exception):
            SCHEMA_REMOVE_FIXED_PLAN({"plan": 0})
        with pytest.raises(Exception):
            SCHEMA_REMOVE_FIXED_PLAN({"plan": 99})
        assert SCHEMA_REMOVE_FIXED_PLAN({"plan": 8}) == {"plan": 8}

    def test_services_registered_names(self, mock_hass):
        import asyncio

        asyncio.run(async_setup_services(mock_hass))
        names = [call.args[1] for call in mock_hass.services.async_register.call_args_list]
        assert SERVICE_SET_FIXED_PLAN_HOUR in names
        assert SERVICE_ADD_FIXED_PLAN in names
        assert SERVICE_REMOVE_FIXED_PLAN in names


# ======================================================================
# Entities
# ======================================================================


class TestActiveFixedPlanSelect:
    def _make_select(self, coordinator, mock_config_entry):
        return ActiveFixedPlanSelect(coordinator, mock_config_entry)

    def _make_refresh_async(self, coordinator):
        from unittest.mock import AsyncMock

        coordinator.async_request_refresh = AsyncMock()
        return coordinator

    def test_options_off_when_no_plans(self, coordinator, mock_config_entry):
        select = self._make_select(coordinator, mock_config_entry)
        assert select.options == ["off"]
        assert select.current_option == "off"

    def test_options_sorted_with_off_first(self, coordinator, mock_config_entry):
        coordinator.add_fixed_plan()
        coordinator.add_fixed_plan()
        select = self._make_select(coordinator, mock_config_entry)
        assert select.options == ["off", "1", "2"]
        assert select.unique_id == f"{mock_config_entry.entry_id}_active_fixed_plan"

    def test_current_option_active(self, coordinator, mock_config_entry):
        coordinator.add_fixed_plan()
        coordinator._active_fixed_plan = 1
        select = self._make_select(coordinator, mock_config_entry)
        assert select.current_option == "1"

    @pytest.mark.asyncio
    async def test_select_option_activates(self, coordinator, mock_config_entry):
        self._make_refresh_async(coordinator)
        coordinator.add_fixed_plan()
        select = self._make_select(coordinator, mock_config_entry)
        select.async_write_ha_state = lambda: None
        await select.async_select_option("1")
        assert coordinator.active_fixed_plan == 1

    @pytest.mark.asyncio
    async def test_select_option_off_deactivates(self, coordinator, mock_config_entry):
        self._make_refresh_async(coordinator)
        coordinator.add_fixed_plan()
        coordinator._active_fixed_plan = 1
        select = self._make_select(coordinator, mock_config_entry)
        select.async_write_ha_state = lambda: None
        await select.async_select_option("off")
        assert coordinator.active_fixed_plan is None

    @pytest.mark.asyncio
    async def test_select_option_invalid_ignored(self, coordinator, mock_config_entry):
        self._make_refresh_async(coordinator)
        coordinator.add_fixed_plan()
        select = self._make_select(coordinator, mock_config_entry)
        select.async_write_ha_state = lambda: None
        await select.async_select_option("9")
        await select.async_select_option("bogus")
        assert coordinator.active_fixed_plan is None


class TestFixedPlansSensor:
    def _make_sensor(self, coordinator, mock_config_entry):
        return FixedPlansSensor(coordinator, mock_config_entry)

    def test_state_is_plan_count(self, coordinator, mock_config_entry):
        coordinator.data = ChargeControlData(
            fixed_plans={1: {"charge_hours": [], "discharge_hours": [], "pv_charge_hours": []},
                         2: {"charge_hours": [], "discharge_hours": [], "pv_charge_hours": []}},
            active_fixed_plan=None,
        )
        sensor = self._make_sensor(coordinator, mock_config_entry)
        assert sensor.native_value == 2
        assert sensor.unique_id == f"{mock_config_entry.entry_id}_fixed_plans"

    def test_attributes_expose_plans_and_active(self, coordinator, mock_config_entry):
        coordinator.data = ChargeControlData(
            fixed_plans={2: {"charge_hours": [4], "discharge_hours": [], "pv_charge_hours": [6]}},
            active_fixed_plan=2,
        )
        sensor = self._make_sensor(coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes
        assert attrs["active"] == 2
        assert attrs["plans"] == {"2": {"charge_hours": [4], "discharge_hours": [], "pv_charge_hours": [6]}}

    def test_no_data_state(self, coordinator, mock_config_entry):
        coordinator.data = None
        sensor = self._make_sensor(coordinator, mock_config_entry)
        assert sensor.native_value == "unknown"
        assert sensor.extra_state_attributes == {"plans": {}, "active": None}
