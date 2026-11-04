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


def test_recalculation_keeps_new_base_under_fixed_overlay(controller):
    publish(controller, [price(START + timedelta(minutes=15*i), value=i) for i in range(8)])
    controller.cheapest_hours = .25
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
