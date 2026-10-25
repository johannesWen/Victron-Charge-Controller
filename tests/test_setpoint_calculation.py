"""Signed setpoint contributions share the actuation arithmetic."""

import pytest

from custom_components.victron_charge_control.const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
)
from custom_components.victron_charge_control.decision import compute_setpoint


@pytest.mark.parametrize(
    ("action", "options", "expected", "target"),
    [
        (ACTION_CHARGE, {}, (3000, 0, 0, 250, 0), 3250),
        (ACTION_IDLE, {}, (50, 0, 0, 250, 0), 300),
        (ACTION_DISCHARGE, {}, (-3000, 0, -2000, 250, 0), -4750),
        (ACTION_DISCHARGE, {"discharge_solar_only": True}, (0, 0, -2000, 250, 0), -1750),
        (ACTION_DISCHARGE, {"solar_surplus_mean": None}, (-3000, 0, 0, 250, 0), -2750),
        (ACTION_PV_CHARGE, {}, (25, 1000, -2000, 250, 0), -725),
        (ACTION_PV_CHARGE, {"charge_blocked_by_soc": True}, (50, 0, 0, 250, 0), 300),
        (ACTION_PV_CHARGE, {"solar_surplus_mean": None}, (25, 0, 0, 250, 0), 275),
        (ACTION_PV_CHARGE, {"pv_charge_share": -10}, (0, 0, -2000, 250, 0), -1750),
        (ACTION_PV_CHARGE, {"pv_charge_share": 110}, (50, 2000, -2000, 250, 0), 300),
        (ACTION_PV_CHARGE, {"pv_charge_share": 33.3}, (16.65, 666, -2000, 250, 0), -1067.35),
        (ACTION_CHARGE, {"max_grid_setpoint": 3100}, (3000, 0, 0, 250, -150), 3100),
        (ACTION_DISCHARGE, {"min_grid_setpoint": -1000}, (-3000, 0, -2000, 250, 3750), -1000),
        (ACTION_DISCHARGE, {"is_reduced": True}, (-3000, 0, -2000, 250, 4250), -500),
        (ACTION_DISCHARGE, {"is_reduced": True, "min_grid_setpoint": -100}, (-3000, 0, -2000, 250, 4650), -100),
        (ACTION_PV_CHARGE, {"is_reduced": True}, (25, 1000, -2000, 250, 225), -500),
    ],
)
def test_contributions_match_target_without_changing_compute_behavior(action, options, expected, target):
    settings = {
        "charge_power": 3000,
        "discharge_power": 3000,
        "idle_setpoint": 50,
        "min_grid_setpoint": -10000,
        "max_grid_setpoint": 10000,
        "charge_blocked_by_soc": False,
        "discharge_solar_only": False,
        "solar_surplus_mean": 2000,
        "pv_charge_share": 50,
        "reduced_max_grid_feed_in": 500,
        "grid_consumer_offset": 250,
        **options,
    }
    calculation = {}
    result = compute_setpoint(action, **settings, calculation=calculation)
    assert result == compute_setpoint(action, **settings)
    assert result == pytest.approx(target)
    assert calculation == pytest.approx(dict(zip(
        ("setting_w", "pv_charge_w", "surplus_w", "grid_consumer_w", "limits_w"),
        expected,
        strict=True,
    )))
    assert sum(calculation.values()) == pytest.approx(result)
