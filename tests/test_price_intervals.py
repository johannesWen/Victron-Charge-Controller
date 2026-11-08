"""Source interval identity, duration budgets, public plans and durable schedules."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.victron_charge_control.const import DOMAIN, MODE_AUTO, MODE_MANUAL
from custom_components.victron_charge_control.coordinator import ChargeControlData, VictronChargeControlCoordinator
from custom_components.victron_charge_control.epex import normalize_price_intervals, price_timeline
from custom_components.victron_charge_control.number import NUMBERS, VictronCCNumber
from custom_components.victron_charge_control.persistence import ScheduleStore, deserialize_slots, serialize_slots
from custom_components.victron_charge_control.schedule import active_slot, local_hour_slots, slot_attributes
from custom_components.victron_charge_control.sensor import ChargePlanSensor, ScheduleSensor
from custom_components.victron_charge_control.services import SCHEMA_SET_SLOT_ACTION, async_setup_services
from tests.conftest import MockConfigEntry, MockState
from tests.slots import utc_slot

DAY = "2026-05-02"
START = datetime(2026, 5, 2, 10, tzinfo=timezone.utc)


def price(start=START, minutes=15, value=5, *, end=True):
    entry = {"start_time": start.isoformat(), "price_ct_per_kwh": value}
    if end:
        entry["end_time"] = (start + timedelta(minutes=minutes)).isoformat()
    return entry


def normalized(entries):
    return normalize_price_intervals({"data": entries})


@pytest.fixture
def controller(coordinator, monkeypatch):
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: START + timedelta(minutes=5))
    coordinator.hass.config.time_zone = "UTC"
    coordinator.control_mode = MODE_AUTO
    coordinator.cheapest_hours = 1
    coordinator.expensive_hours = 0
    coordinator.charge_price_threshold = 100
    coordinator.hass.states.get.return_value = MockState("50")
    return coordinator


def publish(controller, entries, state="5"):
    source = MockState(state, {"data": entries})
    controller.hass.states.get.side_effect = lambda entity: source if entity == controller.epex_spot_entity else MockState("50")
    view = controller._step_load_epex_view()
    controller.data = controller._build_snapshot(action="idle", setpoint=0, price_view=view,
                                                 feed_in_active=False, applied_feed_in=None)
    return controller.data


def test_missing_ends_quarter_cadence_never_fill_missing_records():
    entries = [price(START, end=False), price(START + timedelta(minutes=15), end=False),
               price(START + timedelta(minutes=75), end=False)]
    periods = normalized(entries)
    assert [item.end - item.start for item in periods] == [timedelta(minutes=15)] * 3
    timeline = price_timeline(periods, DAY)
    gap = [item for item in timeline if item["hour"] == 10 and item["minute"] in (30, 45)]
    assert len(gap) == 2 and all("price" not in item for item in gap)


def test_legacy_hourly_and_explicit_mixed_intervals():
    hourly = normalized([price(START, minutes=60, end=False), price(START + timedelta(hours=2), end=False)])
    assert [item.end - item.start for item in hourly] == [timedelta(hours=1)] * 2
    mixed = normalized([price(START, minutes=60), price(START + timedelta(hours=1)),
                        price(START + timedelta(minutes=75), value=7)])
    assert [item.end - item.start for item in mixed] == [timedelta(hours=1), timedelta(minutes=15), timedelta(minutes=15)]
    timeline = price_timeline(mixed, DAY)
    assert [item["price"] for item in timeline if "price" in item] == [5, 5, 7]
    assert len([item for item in timeline if item["hour"] == 10]) == 1


@pytest.mark.parametrize("bad", [None, [], "bad", {}, {"start_time": "bad", "price_ct_per_kwh": 5},
    {"start_time": "2026-05-02T10:00:00", "price_ct_per_kwh": 5},
    price(value="bad"), price(value=float("nan")), price(value=float("inf")), price(value="-inf"),
    price(minutes=0), price(minutes=30), price(minutes=-15),
    {**price(), "end_time": "garbage"}, price(START + timedelta(minutes=1))])
def test_malformed_periods_rejected(bad):
    assert normalized([bad]) == []


def test_duplicate_conflicts_and_overlap_reject_all_ambiguous_periods():
    assert len(normalized([price(), price()])) == 1
    assert normalized([price(value=5), price(value=6)]) == []
    assert normalized([price(minutes=60), price(START + timedelta(minutes=15))]) == []
    entries = [price(minutes=60), price(START + timedelta(minutes=15)), price(START + timedelta(hours=1))]
    assert [item.start for item in normalized(entries)] == [START + timedelta(hours=1)]


def test_eur_conversion_and_invalid_record_do_not_extend_previous_interval():
    entries = [price(end=False), {"start_time": (START + timedelta(minutes=15)).isoformat(), "price_per_kwh": "0.123"},
               price(START + timedelta(minutes=30), value=None, end=False)]
    periods = normalized(entries)
    assert [item.price for item in periods] == [5, 12.3]
    assert periods[-1].end == START + timedelta(minutes=30)


@pytest.mark.parametrize("hours,count", [(0.25, 1), (1.25, 5), (2, 8)])
def test_duration_budget_selects_distinct_quarters_including_current(controller, hours, count):
    entries = [price(START + timedelta(minutes=15 * i), value=i) for i in range(12)]
    publish(controller, entries)
    controller.cheapest_hours = hours
    controller.calculate_auto_schedule()
    assert controller.charge_hours == [(START + timedelta(minutes=15*i), START + timedelta(minutes=15*(i+1))) for i in range(count)]
    assert sum((end-start).total_seconds() for start, end in controller.charge_hours) == hours * 3600


@pytest.mark.parametrize("hours,count", [(0.25, 0), (1.25, 1), (2, 2)])
def test_hourly_budget_never_selects_fraction_of_source(controller, hours, count):
    publish(controller, [price(START + timedelta(hours=i), minutes=60, value=i) for i in range(3)])
    controller.cheapest_hours = hours
    controller.calculate_auto_schedule()
    assert len(controller.charge_hours) == count


def test_selection_thresholds_blocks_pv_conflicts_and_ties(controller):
    entries = [price(START + timedelta(minutes=15*i), value=5) for i in range(12)]
    publish(controller, entries)
    controller._blocked_charging_hours = [11]
    controller._pv_charge_hours = [utc_slot(DAY, 10, 0, 15)]
    controller.cheapest_hours = 1.25
    controller.expensive_hours = .25
    controller.discharge_price_threshold = 5
    controller.calculate_auto_schedule()
    assert controller.discharge_hours == [utc_slot(DAY, 10, 15, 15)]
    assert controller.charge_hours == [utc_slot(DAY, 10, 30, 15), utc_slot(DAY, 10, 45, 15),
                                       utc_slot(DAY, 12, 0, 15), utc_slot(DAY, 12, 15, 15)]
    controller.charge_price_threshold = 4.9
    controller.discharge_price_threshold = 5.1
    controller.calculate_auto_schedule()
    assert controller.charge_hours == controller.discharge_hours == []


@pytest.mark.parametrize("minutes", [15, 60])
@pytest.mark.parametrize("values,charge_delta,discharge_delta,charge,discharge", [
    ([0, 5, 10, 15, 20], 5, 5, [0, 1, 2, 3], [4]),
    ([0, 5, 10, 15, 20], 20, 20, [0], [4]),
    ([0, 5, 10, 15, 20], 21, 21, [], []),
    ([0, 5, 10], 0, 0, [0, 1, 2], []),
    ([0, 5, 10], -5, 5, [0, 1, 2], []),
    ([0, 5, 10], 11, -5, [], [0, 1, 2]),
    ([-20, -15, -10], 5, 5, [0, 1], [2]),
    ([7, 7, 7], 0, 0, [0, 1, 2], []),
    ([7, 7, 7], 1, 1, [], []),
    ([3.6, 4.1], .5, 0, [0], [1]),
    ([.1, .3], 1, .2, [], [1]),
    ([3.6 + 2e-9, 4.1], .5, 0, [], [0, 1]),
    ([.1, .3 - 2e-9], 1, .2, [], []),
])
def test_relative_selection(controller, minutes, values, charge_delta, discharge_delta, charge, discharge):
    entries = [price(START + timedelta(minutes=minutes*i), minutes, value) for i, value in enumerate(values)]
    publish(controller, entries)
    controller.relative_auto_mode = True
    controller.charge_price_threshold = charge_delta
    controller.discharge_price_threshold = discharge_delta
    controller.cheapest_hours = controller.expensive_hours = 0
    controller._blocked_charging_hours = controller._blocked_discharging_hours = []
    controller.calculate_auto_schedule()
    slots = [item.slot for item in normalized(entries)]
    assert controller.charge_hours == [slots[i] for i in charge]
    assert controller.discharge_hours == [slots[i] for i in discharge]


def test_absolute_thresholds_do_not_use_relative_equality_tolerance(controller):
    publish(controller, [price(value=3.6 + 5e-10),
                         price(START + timedelta(minutes=15), value=4.1 - 5e-10)])
    controller.charge_price_threshold = 3.6
    controller.discharge_price_threshold = 4.1
    controller.cheapest_hours = controller.expensive_hours = 1
    controller.calculate_auto_schedule()
    assert controller.charge_hours == controller.discharge_hours == []


@pytest.mark.parametrize("duration", [0, -1, None, "bad", float("nan"), float("inf"), .1])
def test_relative_ignores_invalid_duration_budgets(controller, duration):
    publish(controller, [price(value=0), price(START + timedelta(minutes=15), value=10)])
    controller.relative_auto_mode = True
    controller.cheapest_hours = controller.expensive_hours = duration
    controller.charge_price_threshold = controller.discharge_price_threshold = 10
    controller.calculate_auto_schedule()
    assert controller.charge_hours == [utc_slot(DAY, 10, 0, 15)]
    assert controller.discharge_hours == [utc_slot(DAY, 10, 15, 15)]


def test_relative_extrema_include_current_tomorrow_and_later_before_exclusions(controller):
    entries = [price(START - timedelta(minutes=30), value=-1000),
               price(START - timedelta(minutes=15), value=1000),
               price(value=2), price(START + timedelta(minutes=15), value=5),
               price(START + timedelta(days=1), value=-10),
               price(START + timedelta(days=2, hours=1), value=30),
               price(START + timedelta(days=3), value="nan")]
    data = publish(controller, entries)
    controller.relative_auto_mode = True
    controller.charge_price_threshold = controller.discharge_price_threshold = 25
    controller._pv_charge_hours = [utc_slot("2026-05-03", 10, 0, 15)]
    controller._blocked_discharging_hours = [11]
    controller.calculate_auto_schedule()
    assert (data.price_reference_min, data.price_reference_max) == (-10, 30)
    assert controller.charge_hours == [utc_slot(DAY, 10, 0, 15), utc_slot(DAY, 10, 15, 15)]
    assert controller.discharge_hours == []
    # A charge exclusion still permits discharge of an overlapping candidate.
    controller._blocked_charging_hours = [10]
    controller.discharge_price_threshold = 10
    controller.calculate_auto_schedule()
    assert controller.charge_hours == []
    assert controller.discharge_hours == [utc_slot(DAY, 10, 0, 15), utc_slot(DAY, 10, 15, 15)]


@pytest.mark.parametrize("date,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_relative_dst_slots_and_blocked_local_hours(controller, monkeypatch, date, hours):
    zone = ZoneInfo("Europe/Vienna")
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", zone)
    start = datetime.fromisoformat(date).replace(tzinfo=zone).astimezone(timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: start + timedelta(minutes=5))
    entries = [price(start + timedelta(minutes=15*i), value=5) for i in range(hours*4)]
    publish(controller, entries)
    controller.relative_auto_mode = True
    controller.charge_price_threshold = controller.discharge_price_threshold = 0
    controller._blocked_charging_hours = controller._blocked_discharging_hours = [2]
    controller.calculate_auto_schedule()
    expected = [item.slot for item in normalized(entries) if item.start.astimezone(zone).hour != 2]
    assert controller.charge_hours == expected
    assert len(expected) == 92
    assert controller.discharge_hours == []


@pytest.mark.parametrize("state,entries", [
    (None, [price()]), ("unavailable", [price()]), ("unknown", [price()]),
    ("5", []), ("5", [price(value="nan")]),
    ("5", [price(START-timedelta(minutes=15))]),
])
def test_relative_missing_eligible_data_preserves_plan_and_clears_references(controller, state, entries):
    controller.relative_auto_mode = True
    controller._charge_hours = [utc_slot(DAY, 12)]
    controller._discharge_hours = [utc_slot(DAY, 13)]
    controller._last_schedule_update = START
    if state is None:
        controller.hass.states.get.return_value = None
    else:
        publish(controller, entries, state=state)
    view = controller._step_load_epex_view()
    controller.calculate_auto_schedule()
    assert (view.price_reference_min, view.price_reference_max) == (None, None)
    assert controller.charge_hours == [utc_slot(DAY, 12)]
    assert controller.discharge_hours == [utc_slot(DAY, 13)]
    assert controller._last_schedule_update == START


@pytest.mark.parametrize("mode", ["auto", "manual", "off", "force_charge", "force_discharge"])
async def test_reference_attributes_refresh_without_replanning(controller, monkeypatch, mode):
    controller.control_mode = mode
    controller._charge_hours = [utc_slot(DAY, 12)]
    publish(controller, [price(value=1), price(START+timedelta(minutes=15), value=10)])
    controller.calculate_auto_schedule = MagicMock()
    sensor = ChargePlanSensor(controller, MockConfigEntry())
    sensor.async_write_ha_state = MagicMock()
    for now, expected in [(START+timedelta(minutes=5), (1, 10)),
                          (START+timedelta(minutes=15), (10, 10)),
                          (START+timedelta(minutes=30), (None, None))]:
        monkeypatch.setattr(dt_util, "now", lambda: now)
        controller.data = await controller._async_update_data()
        sensor._handle_coordinator_update()
        assert (sensor.extra_state_attributes["price_reference_min"],
                sensor.extra_state_attributes["price_reference_max"]) == expected
        assert controller.charge_hours == [utc_slot(DAY, 12)]
    controller.calculate_auto_schedule.assert_not_called()
    controller.data = None
    sensor._handle_coordinator_update()
    assert sensor.extra_state_attributes["price_reference_min"] is None
    assert sensor.extra_state_attributes["price_reference_max"] is None


def test_unavailable_source_does_not_replan(controller):
    controller._charge_hours = [utc_slot(DAY, 12)]
    data = publish(controller, [price()], state="unavailable")
    controller.calculate_auto_schedule()
    assert controller.charge_hours == [utc_slot(DAY, 12)]
    assert len(data.prices_today) == 24
    assert all("price" not in item for item in data.prices_today)


def test_quarter_transition_and_midnight_expiry(controller, monkeypatch):
    controller.control_mode = MODE_MANUAL
    controller._charge_hours = [utc_slot(DAY, 23, 45, 15)]
    controller._discharge_hours = [utc_slot("2026-05-03", 0, 0, 15)]
    for instant, action in [(datetime(2026,5,2,23,59,59,tzinfo=timezone.utc), "charge"),
                            (datetime(2026,5,3,0,0,tzinfo=timezone.utc), "discharge"),
                            (datetime(2026,5,3,0,15,tzinfo=timezone.utc), "idle")]:
        monkeypatch.setattr(dt_util, "now", lambda: instant)
        assert controller._determine_action() == action
        controller._clean_expired_slots()
    assert controller.charge_hours == controller.discharge_hours == []


@pytest.mark.parametrize("date,hours", [("2026-03-29",23), ("2026-10-25",25)])
def test_dst_complete_timeline_and_distinct_repeated_instants(monkeypatch, date, hours):
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Vienna"))
    day = datetime.fromisoformat(date).replace(tzinfo=dt_util.DEFAULT_TIME_ZONE).astimezone(timezone.utc)
    entries = [price(day + timedelta(minutes=15*i), value=i) for i in range(hours*4)]
    timeline = price_timeline(normalized(entries), date)
    assert len(timeline) == hours*4
    assert len({item["start_time"] for item in timeline}) == hours*4
    assert {item["date"] for item in timeline} == {date}
    assert sum(item["hour"] == 2 for item in timeline) == (8 if hours == 25 else 0)
    local_hours = local_hour_slots(date, 2)
    assert len(local_hours) == (2 if hours == 25 else 0)
    if hours == 25:
        assert not active_slot([local_hours[0]], local_hours[1][0])
        assert active_slot([local_hours[1]], local_hours[1][0])


async def test_real_store_v1_migration_retains_recovery_and_expands_dst(tmp_path, monkeypatch):
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Vienna"))
    hass = HomeAssistant(str(tmp_path))
    old = {"charge_hours": [["2026-10-25",2], ["2026-03-29",2]],
           "discharge_hours": [["2026-10-25",3]], "pv_charge_hours": [],
           "blocked_charging_hours": [4], "last_schedule_update": "2026-03-01T12:00:00+00:00",
           "fixed_plans": {"1": {"charge_hours": [2], "name": "Winter"}}, "active_fixed_plan": 1,
           "discharge_release_entity": "number.old_limit", "future_payload": {"keep": True}}
    await Store(hass, 1, "test.schedule").async_save(old)
    migrated = await ScheduleStore(hass, 2, "test.schedule").async_load()
    assert migrated["charge_hours"] == [["2026-10-25T00:00:00+00:00", "2026-10-25T01:00:00+00:00"],
                                        ["2026-10-25T01:00:00+00:00", "2026-10-25T02:00:00+00:00"]]
    for key in old.keys() - {"charge_hours", "discharge_hours", "pv_charge_hours"}:
        assert migrated[key] == old[key]
    assert await ScheduleStore(hass, 2, "test.schedule").async_load() == migrated
    await hass.async_stop()


async def test_v2_restart_and_fixed_overlay_retraction(controller, mock_store):
    publish(controller, [price(START + timedelta(minutes=15*i), value=i) for i in range(8)])
    controller._charge_hours = [utc_slot(DAY, 10, 15, 15)]
    controller._discharge_release_entity = "number.old_limit"
    controller.set_fixed_plan_hour(1, 10, "discharge")
    controller.set_active_fixed_plan(1)
    assert len([slot for slot in controller.discharge_hours if slot[0].date().isoformat() == DAY]) == 4
    await controller._async_save_schedule()
    restarted = VictronChargeControlCoordinator(controller.hass, MockConfigEntry())
    restarted.async_request_refresh = MagicMock()
    restarted.calculate_auto_schedule = MagicMock()
    await restarted._async_load_schedule()
    assert restarted.discharge_hours == controller.discharge_hours
    assert restarted._discharge_release_pending
    restarted.calculate_auto_schedule.assert_not_called()
    restarted.set_active_fixed_plan(None)
    assert restarted.charge_hours == [utc_slot(DAY, 10, 15, 15)]
    assert restarted.discharge_hours == []
    assert deserialize_slots(serialize_slots(restarted.charge_hours)) == restarted.charge_hours


def test_exact_slot_edit_and_whole_hour_service_override(controller):
    data = publish(controller, [price(START + timedelta(minutes=15*i), value=i) for i in range(4)])
    controller._charge_hours = [utc_slot(DAY, 10)]  # A migrated hourly schedule.
    controller.set_slot_action("2026-05-02T12:15:00+02:00", "pv_charge")
    assert controller.pv_charge_hours == [utc_slot(DAY, 10, 15, 15)]
    assert not active_slot(controller.charge_hours, START + timedelta(minutes=15))
    assert active_slot(controller.charge_hours, START + timedelta(minutes=30))
    controller.set_hour_action(10, "discharge", DAY)
    assert len(controller.discharge_hours) == 4
    assert controller.charge_hours == controller.pv_charge_hours == []
    controller.set_slot_action(data.prices_today[40]["start_time"], "idle")
    assert len(controller.discharge_hours) == 3


@pytest.mark.parametrize("start,action", [("bad","charge"), ("2026-05-02T10:15:00","charge"),
    ("2026-05-02T10:05:00+00:00","charge"), ("2026-05-02T10:30:00+00:00","charge"),
    ("2026-05-02T09:45:00+00:00","charge"), ("2026-05-02T10:00:00+00:00","blocked")])
def test_exact_slot_rejection_has_no_mutation(controller, mock_store, start, action):
    publish(controller, [price(START-timedelta(minutes=15)), price(), price(START+timedelta(minutes=15))])
    controller._charge_hours = [utc_slot(DAY, 10)]
    before = (deepcopy(controller.charge_hours), controller._last_schedule_update, len(mock_store.save_calls))
    controller.hass.async_create_task.reset_mock()
    with pytest.raises(ServiceValidationError):
        controller.set_slot_action(start, action)
    assert (controller.charge_hours, controller._last_schedule_update, len(mock_store.save_calls)) == before
    controller.hass.async_create_task.assert_not_called()


def test_exact_slot_rejects_unpublished_and_stale_source(controller):
    publish(controller, [price()])
    controller.data.prices_today = []
    with pytest.raises(ServiceValidationError):
        controller.set_slot_action(START.isoformat(), "charge")
    publish(controller, [price()])
    controller.hass.states.get.side_effect = None
    controller.hass.states.get.return_value = MockState("unavailable")
    with pytest.raises(ServiceValidationError):
        controller.set_slot_action(START.isoformat(), "charge")


def test_hour_compatibility_changes_both_fallback_occurrences(controller, monkeypatch):
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Vienna"))
    start = datetime(2026,10,25,0,tzinfo=timezone.utc)
    publish(controller, [price(start + timedelta(minutes=15*i)) for i in range(8)])
    controller._pv_charge_hours = [(start, start+timedelta(minutes=15))]
    controller.set_hour_action(2,"charge","2026-10-25")
    assert len(controller.charge_hours) == 8
    assert controller.pv_charge_hours == []
    controller.toggle_hour(2,"2026-10-25")
    assert len(controller.pv_charge_hours) == 8
    assert controller.charge_hours == []


def test_plan_preserves_every_price_and_action_and_short_state(controller):
    entries = [price(START + timedelta(minutes=15*i), value=i) for i in range(4)]
    publish(controller, entries)
    controller.set_slot_action(START.isoformat(), "charge")
    controller.set_slot_action((START+timedelta(minutes=15)).isoformat(), "discharge")
    data = publish(controller, entries)
    sensor = ChargePlanSensor(controller, MockConfigEntry())
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_coordinator_update()
    plan = sensor.extra_state_attributes["plan"]
    assert sensor.extra_state_attributes["time_zone"] == "UTC"
    assert len(plan) == 192
    priced = [item for item in plan if "price" in item]
    assert [item["price"] for item in priced] == [0,1,2,3]
    assert [item["action"] for item in priced] == ["charge","discharge","idle","idle"]
    assert set(data.charge_hours[0]) == {"start_time","end_time","date","hour","minute"}
    assert len(ScheduleSensor._format_slots(plan)) <= 255
    assert ScheduleSensor._format_slots(plan) == "48 h scheduled"


@pytest.mark.parametrize("key", ["cheapest_hours", "expensive_hours"])
async def test_duration_entity_restores_fraction_without_replanning(controller, key):
    description = next(item for item in NUMBERS if item.key == key)
    number = VictronCCNumber(controller, MockConfigEntry(), description)
    number.hass = controller.hass
    number.async_get_last_state = AsyncMock(return_value=MockState("1.25"))
    controller.calculate_auto_schedule = MagicMock()
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
    assert getattr(controller, key) == 1.25
    assert description.native_step == .25
    controller.calculate_auto_schedule.assert_not_called()


async def test_registered_exact_service_routes_without_loss(controller):
    publish(controller, [price()])
    controller.hass.data[DOMAIN] = {"entry": controller}
    await async_setup_services(controller.hass)
    call = next(call for call in controller.hass.services.async_register.call_args_list if call.args[1] == "set_slot_action")
    payload = SCHEMA_SET_SLOT_ACTION({"start_time": START.isoformat(), "action": "charge"})
    await call.args[2](MagicMock(data=payload))
    assert controller.charge_hours == [(START, START+timedelta(minutes=15))]


@pytest.mark.parametrize("relative", [False, True])
def test_recalculation_keeps_new_base_under_fixed_overlay(controller, relative):
    publish(controller, [price(START + timedelta(minutes=15*i), value=i) for i in range(8)])
    controller.cheapest_hours = .25
    controller.relative_auto_mode = relative
    if relative:
        controller.charge_price_threshold = 7
        controller.discharge_price_threshold = 8
    controller.calculate_auto_schedule()
    assert controller.charge_hours == [utc_slot(DAY, 10, 0, 15)]
    controller.set_fixed_plan_hour(1, 10, "pv_charge")
    controller.set_active_fixed_plan(1)
    controller.calculate_auto_schedule()
    controller.set_active_fixed_plan(None)
    assert controller.charge_hours == [utc_slot(DAY, 10, 0, 15)]
    assert controller.pv_charge_hours == []


def test_exact_fallback_occurrences_are_independently_editable(controller, monkeypatch):
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Vienna"))
    start = datetime(2026,10,25,0,tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: start)
    publish(controller, [price(start+timedelta(minutes=15*i), value=i) for i in range(8)])
    controller.set_slot_action("2026-10-25T02:15:00+02:00", "charge")
    controller.set_slot_action("2026-10-25T02:15:00+01:00", "discharge")
    assert controller.charge_hours == [utc_slot("2026-10-25", 0, 15, 15)]
    assert controller.discharge_hours == [utc_slot("2026-10-25", 1, 15, 15)]
    data = publish(controller, [price(start+timedelta(minutes=15*i), value=i) for i in range(8)])
    plan = ChargePlanSensor(controller, MockConfigEntry())._build_plan(data)
    repeated = [item for item in plan if item["hour"] == 2 and item["minute"] == 15 and item["date"] == "2026-10-25"]
    assert [item["action"] for item in repeated] == ["charge", "discharge"]


def test_public_legacy_hour_setter_expands_to_utc(controller):
    controller.set_charge_hours([(DAY,10), (DAY,11), (DAY,11), (DAY,24)])
    assert controller.charge_hours == [utc_slot(DAY,10), utc_slot(DAY,11)]


def test_mixed_duration_budget_and_price_gap(controller):
    publish(controller, [price(minutes=60,value=1), price(START+timedelta(hours=1),value=2),
                         price(START+timedelta(minutes=90),value=3)])
    controller.cheapest_hours = 1.25
    controller.calculate_auto_schedule()
    assert controller.charge_hours == [utc_slot(DAY,10), utc_slot(DAY,11,0,15)]
    assert not active_slot(controller.charge_hours, START+timedelta(minutes=75))


def test_unpriced_plan_preserves_restored_quarter_actions(controller):
    controller._charge_hours = [utc_slot(DAY, 10, 15, 15)]
    data = publish(controller, [], state="unavailable")
    plan = ChargePlanSensor(controller, MockConfigEntry())._build_plan(data)
    morning = [item for item in plan if item["date"] == DAY and item["hour"] == 10]
    assert [(item["minute"], item["action"]) for item in morning] == [(0,"idle"), (15,"charge"), (30,"idle")]
    assert all("price" not in item for item in morning)


@pytest.mark.parametrize("entry", [price(value=True), {**price(), "price_ct_per_kwh": None, "price_per_kwh": False},
    {"start_time": "9999-12-31T23:00:00+00:00", "price_ct_per_kwh": 1}])
def test_invalid_numeric_or_out_of_range_period_is_ignored(entry):
    assert normalized([entry]) == []


@pytest.mark.parametrize("blocked,excluded", [([10],True),([11],True),([12],False)])
@pytest.mark.parametrize("action", ["charge", "discharge"])
def test_native_period_excluded_when_any_touched_hour_is_blocked(controller, blocked, excluded, action):
    start = START + timedelta(minutes=45)
    publish(controller, [price(start, minutes=60)])
    controller.cheapest_hours = 1 if action == "charge" else 0
    controller.expensive_hours = 1 if action == "discharge" else 0
    controller.discharge_price_threshold = 0
    setattr(controller, f"_blocked_{'charging' if action == 'charge' else 'discharging'}_hours", blocked)
    controller.calculate_auto_schedule()
    assert getattr(controller, f"{action}_hours") == ([] if excluded else [(start, start+timedelta(hours=1))])


def test_priced_display_splits_at_retained_action_boundaries_and_edits_exact_segment(controller):
    controller._charge_hours = [utc_slot(DAY, 10, 15, 15)]
    data = publish(controller, [price(minutes=60)])
    plan = ChargePlanSensor(controller, MockConfigEntry())._build_plan(data)
    priced = [item for item in plan if "price" in item]
    assert [(item["minute"], item["action"], item["price"]) for item in priced] == [
        (0,"idle",5),(15,"charge",5),(30,"idle",5)]
    assert [item["end_time"] for item in priced] == [
        (START+timedelta(minutes=minutes)).isoformat() for minutes in (15,30,60)]
    assert [{key:value for key,value in item.items() if key != "action"} for item in priced] == [
        item for item in data.prices_today if "price" in item]
    controller.set_slot_action(priced[1]["start_time"], "discharge")
    assert controller.charge_hours == []
    assert controller.discharge_hours == [utc_slot(DAY,10,15,15)]
    controller.cheapest_hours = .25
    controller.calculate_auto_schedule()
    assert controller.charge_hours == []  # Native hourly source remains indivisible.


@pytest.mark.parametrize("zone", ["UTC", "Europe/Vienna"])
def test_midnight_source_is_clipped_published_and_editable(controller, monkeypatch, zone):
    local_zone = ZoneInfo(zone)
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", local_zone)
    midnight = datetime(2026,5,3,tzinfo=local_zone).astimezone(timezone.utc)
    source = midnight-timedelta(minutes=15)
    monkeypatch.setattr(dt_util, "now", lambda: dt_util.as_local(midnight+timedelta(minutes=5)))
    data = publish(controller, [price(source, minutes=60)])
    first = data.prices_today[0]
    assert first == {"date":"2026-05-03", "hour":0, "minute":0,
                     "start_time":midnight.isoformat(), "end_time":(midnight+timedelta(minutes=45)).isoformat(), "price":5}
    controller.set_slot_action(first["start_time"], "charge")
    assert controller.charge_hours == [(midnight, midnight+timedelta(minutes=45))]
    with pytest.raises(ServiceValidationError):
        controller.set_slot_action(source.isoformat(), "charge")  # No longer a displayed segment today.
    previous = price_timeline(normalized([price(source, minutes=60)]), "2026-05-02")[-1]
    assert previous["start_time"] == source.isoformat()
    assert previous["end_time"] == midnight.isoformat()
    assert previous["date"] == "2026-05-02" and previous["price"] == 5


def test_split_display_cannot_be_edited_after_source_loses_coverage(controller):
    controller._charge_hours = [utc_slot(DAY,10,15,15)]
    publish(controller, [price(minutes=60)])
    before = deepcopy(controller.charge_hours)
    controller.hass.states.get.side_effect = lambda _: MockState("5", {"data":[price()]})
    with pytest.raises(ServiceValidationError):
        controller.set_slot_action((START+timedelta(minutes=15)).isoformat(), "discharge")
    assert controller.charge_hours == before


@pytest.mark.parametrize("value", ["nan","inf","-inf","-0.25","12.25","1.1"])
@pytest.mark.parametrize("key", ["cheapest_hours","expensive_hours"])
async def test_invalid_duration_restore_keeps_current_safe_budget(controller, key, value):
    description = next(item for item in NUMBERS if item.key == key)
    number = VictronCCNumber(controller, MockConfigEntry(), description)
    number.hass = controller.hass
    number.async_get_last_state = AsyncMock(return_value=MockState(value))
    setattr(controller, key, 1.25)
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
    assert getattr(controller,key) == 1.25


@pytest.mark.parametrize("value", [float("nan"),float("inf"),float("-inf"),-.25,12.25,1.1,None,"bad"])
@pytest.mark.parametrize("key", ["cheapest_hours","expensive_hours"])
def test_invalid_planner_budget_selects_nothing(controller, key, value):
    publish(controller, [price(START+timedelta(minutes=15*i)) for i in range(8)])
    setattr(controller,key,value)
    controller.calculate_auto_schedule()
    assert getattr(controller,"charge_hours" if key == "cheapest_hours" else "discharge_hours") == []


@pytest.mark.parametrize("value", ["nan","inf","-inf","-0.25","12.25","1.1"])
@pytest.mark.parametrize("key", ["cheapest_hours","expensive_hours"])
async def test_invalid_duration_rejected_by_real_ha_number_service_without_mutation(controller, key, value):
    import probatio
    from types import SimpleNamespace
    from homeassistant.components.number.services import _async_set_value

    description = next(item for item in NUMBERS if item.key == key)
    number = VictronCCNumber(controller, MockConfigEntry(), description)
    number.hass = controller.hass
    number.async_write_ha_state = MagicMock()
    controller.async_request_refresh = AsyncMock()
    controller.calculate_auto_schedule = MagicMock()
    before = getattr(controller,key)
    payload = probatio.Schema({probatio.Required("value"):probatio.Coerce(float)})({"value":value})
    with pytest.raises(ServiceValidationError):
        await _async_set_value(number, SimpleNamespace(data=payload))
    assert getattr(controller,key) == before
    controller.calculate_auto_schedule.assert_not_called()
    controller.async_request_refresh.assert_not_called()
    number.async_write_ha_state.assert_not_called()


@pytest.mark.parametrize("edit", ["exact","hour","toggle"])
async def test_manual_pv_outside_fixed_overlay_survives_replan_restart_retraction(controller, edit):
    publish(controller, [price(START+timedelta(minutes=15*i),value=10-i) for i in range(8)])
    controller.set_fixed_plan_hour(1,11,"discharge")
    controller.set_active_fixed_plan(1)
    if edit == "exact":
        controller.set_slot_action((START+timedelta(minutes=45)).isoformat(),"pv_charge")
    elif edit == "hour":
        controller.set_hour_action(10,"pv_charge",DAY)
    else:
        controller.toggle_hour(10,DAY)
        controller.toggle_hour(10,DAY)
    expected = list(controller.pv_charge_hours)
    controller.cheapest_hours = .25
    controller.calculate_auto_schedule()
    assert controller.pv_charge_hours == expected
    assert not any(active_slot(controller.charge_hours, start) for start,_ in expected)
    await controller._async_save_schedule()
    restarted = VictronChargeControlCoordinator(controller.hass,MockConfigEntry())
    restarted.async_request_refresh = MagicMock()
    restarted.control_mode = MODE_MANUAL
    await restarted._async_load_schedule()
    restarted.set_active_fixed_plan(None)
    assert restarted.pv_charge_hours == expected
    assert restarted.discharge_hours == []


@pytest.mark.parametrize("edit", ["exact","hour","charge_list","discharge_list"])
async def test_edits_take_effect_before_fixed_reapplication_and_retraction_restores_base(controller, edit):
    publish(controller, [price(START+timedelta(minutes=15*i)) for i in range(4)])
    controller.control_mode = MODE_MANUAL
    controller.set_fixed_plan_hour(1,10,"pv_charge")
    controller.set_active_fixed_plan(1)
    action = "discharge" if edit == "discharge_list" else "charge"
    if edit == "exact":
        controller.set_slot_action(START.isoformat(),action)
        expected = [utc_slot(DAY,10,0,15)]
    elif edit == "hour":
        controller.set_hour_action(10,action,DAY)
        expected = [utc_slot(DAY,10,minute,15) for minute in (0,15,30,45)]
    else:
        expected = [utc_slot(DAY,10)]
        getattr(controller,f"set_{action}_hours")([(DAY,10)])
    assert active_slot(getattr(controller,f"{action}_hours"), START)
    if edit in ("exact", "hour"):
        assert not active_slot(controller.pv_charge_hours, START)
    else:
        # Bucket setters retain the other buckets, matching their original behavior.
        assert active_slot(controller.pv_charge_hours, START)
    controller._apply_fixed_plan()
    assert active_slot(controller.pv_charge_hours, START)
    assert not active_slot(getattr(controller,f"{action}_hours"), START)
    await controller._async_save_schedule()
    restarted = VictronChargeControlCoordinator(controller.hass,MockConfigEntry())
    restarted.async_request_refresh = MagicMock()
    restarted.control_mode = MODE_MANUAL
    await restarted._async_load_schedule()
    restarted.set_active_fixed_plan(None)
    assert getattr(restarted,f"{action}_hours") == expected
    assert restarted.pv_charge_hours == []


def test_public_schedule_uses_display_segments_but_planner_keeps_native_period(controller, monkeypatch):
    midnight = START.replace(hour=0)+timedelta(days=1)
    source = midnight-timedelta(minutes=15)
    monkeypatch.setattr(dt_util,"now",lambda:midnight+timedelta(minutes=5))
    publish(controller,[price(source,minutes=60)])
    controller.cheapest_hours = .25
    controller.calculate_auto_schedule()
    assert controller.charge_hours == []
    controller.cheapest_hours = 1
    controller.calculate_auto_schedule()
    assert controller.charge_hours == [(source,midnight+timedelta(minutes=45))]
    data = publish(controller,[price(source,minutes=60)])
    priced = data.prices_today[0]
    assert data.charge_hours == [
        slot_attributes((source,midnight)),
        {key:value for key,value in priced.items() if key != "price"},
    ]
    controller.set_slot_action(priced["start_time"],"idle")
    assert controller.charge_hours == [(source,midnight)]
    controller._clean_expired_slots()
    assert controller.charge_hours == []


@pytest.mark.parametrize("date,blocked,excluded", [
    ("2026-03-29",2,False), ("2026-03-29",3,True),
    ("2026-10-25",2,True), ("2026-10-25",3,False),
])
def test_crossing_source_blocks_follow_actual_dst_hours(controller,monkeypatch,date,blocked,excluded):
    monkeypatch.setattr(dt_util,"DEFAULT_TIME_ZONE",ZoneInfo("Europe/Vienna"))
    start = datetime.fromisoformat(date).replace(hour=0,minute=45,tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util,"now",lambda:dt_util.as_local(start))
    publish(controller,[price(start,minutes=60)])
    controller._blocked_charging_hours = [blocked]
    controller.calculate_auto_schedule()
    assert controller.charge_hours == ([] if excluded else [(start,start+timedelta(hours=1))])


@pytest.mark.parametrize("edit", ["exact", "hour"])
@pytest.mark.parametrize("action", ["charge", "pv_charge", "discharge", "idle"])
def test_daily_edits_override_fixed_plan_immediately_in_schedule_and_display(controller, edit, action):
    controller.control_mode = MODE_MANUAL
    entries = [price(START + timedelta(minutes=15*i)) for i in range(4)]
    publish(controller, entries)
    fixed = "discharge" if action == "charge" else "charge"
    controller.set_fixed_plan_hour(1, 10, fixed)
    controller.set_active_fixed_plan(1)
    target = START + timedelta(minutes=15)
    if edit == "exact":
        controller.set_slot_action(target.isoformat(), action)
    else:
        controller.set_hour_action(10, action, DAY)
    for bucket in ("charge", "pv_charge", "discharge"):
        assert active_slot(getattr(controller, f"{bucket}_hours"), target) == (action == bucket)
    data = publish(controller, entries)
    plan = ChargePlanSensor(controller, MockConfigEntry())._build_plan(data)
    assert next(item for item in plan if item["start_time"] == target.isoformat())["action"] == action
    controller._apply_fixed_plan()
    assert active_slot(getattr(controller, f"{fixed}_hours"), target)
    controller.set_active_fixed_plan(None)
    for bucket in ("charge", "pv_charge", "discharge"):
        assert active_slot(getattr(controller, f"{bucket}_hours"), target) == (action == bucket)


def test_full_toggle_cycle_uses_last_daily_edit_with_active_fixed_plan(controller):
    controller.control_mode = MODE_MANUAL
    publish(controller, [price(START+timedelta(minutes=15*i)) for i in range(4)])
    controller.set_fixed_plan_hour(1,10,"charge")
    controller.set_active_fixed_plan(1)
    for action in ("pv_charge", "discharge", "blocked", "idle", "charge", "pv_charge", "discharge"):
        controller.toggle_hour(10,DAY)
        for bucket in ("charge", "pv_charge", "discharge"):
            assert active_slot(getattr(controller, f"{bucket}_hours"), START) == (action == bucket)
        assert (10 in controller.blocked_charging_hours) == (action == "blocked")
        assert (10 in controller.blocked_discharging_hours) == (action == "blocked")
    controller.set_active_fixed_plan(None)
    assert controller.discharge_hours == [utc_slot(DAY,10,minute,15) for minute in (0,15,30,45)]
    assert controller.charge_hours == controller.pv_charge_hours == []


@pytest.mark.parametrize("reset_before_restart", [False, True])
async def test_manual_reset_preserves_manual_pv_base_without_fixed_only_pv(controller, reset_before_restart):
    controller.control_mode = MODE_MANUAL
    publish(controller, [price(START+timedelta(minutes=15*i)) for i in range(8)])
    controller._pv_charge_hours = [utc_slot(DAY,9,45,15)]  # Expired PV must not be restored by retraction.
    controller.set_fixed_plan_hour(1,10,"discharge")
    controller.set_fixed_plan_hour(1,11,"pv_charge")
    controller.set_active_fixed_plan(1)
    manual_pv = utc_slot(DAY,10,15,15)
    controller.set_slot_action(manual_pv[0].isoformat(),"pv_charge")
    controller.set_hour_action(12,"charge",DAY)
    controller.set_hour_action(13,"discharge",DAY)
    assert active_slot(controller.pv_charge_hours, manual_pv[0])
    if reset_before_restart:
        controller._run_replan()
        assert controller._fixed_plan_base_snapshot == ([], [], [manual_pv])
    await controller._async_save_schedule()
    restarted = VictronChargeControlCoordinator(controller.hass, MockConfigEntry())
    restarted.async_request_refresh = MagicMock()
    restarted.control_mode = MODE_MANUAL
    await restarted._async_load_schedule()
    restarted._run_replan()
    assert restarted._fixed_plan_base_snapshot == ([], [], [manual_pv])
    assert active_slot(restarted.discharge_hours, manual_pv[0])  # Reset explicitly reapplies fixed plan.
    assert active_slot(restarted.pv_charge_hours, START+timedelta(hours=1))
    restarted.set_active_fixed_plan(None)
    assert restarted.pv_charge_hours == [manual_pv]
    assert restarted.charge_hours == restarted.discharge_hours == []


@pytest.mark.parametrize("action", ["charge", "discharge"])
async def test_bucket_setter_replaces_effective_and_base_bucket_without_reapplying(controller, action):
    controller.control_mode = MODE_MANUAL
    publish(controller, [price(START+timedelta(minutes=15*i)) for i in range(8)])
    controller._pv_charge_hours = [utc_slot(DAY,12)]
    controller.set_fixed_plan_hour(1,10,action)
    controller.set_active_fixed_plan(1)
    getattr(controller,f"set_{action}_hours")([(DAY,11)])
    assert getattr(controller,f"{action}_hours") == [utc_slot(DAY,11)]
    assert controller.pv_charge_hours == [utc_slot(DAY,12)]
    await controller._async_save_schedule()
    restarted = VictronChargeControlCoordinator(controller.hass,MockConfigEntry())
    restarted.async_request_refresh = MagicMock()
    restarted.control_mode = MODE_MANUAL
    await restarted._async_load_schedule()
    assert getattr(restarted,f"{action}_hours") == [utc_slot(DAY,11)]
    restarted.set_active_fixed_plan(None)
    assert getattr(restarted,f"{action}_hours") == [utc_slot(DAY,11)]
    assert restarted.pv_charge_hours == [utc_slot(DAY,12)]
