"""Services for Victron Charge Control."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ACTION_BLOCKED,
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    ACTION_PV_CHARGE,
    DOMAIN,
    MAX_FIXED_PLANS,
)
from .coordinator import VictronChargeControlCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_TOGGLE_HOUR = "toggle_hour"
SERVICE_SET_HOUR_ACTION = "set_hour_action"
SERVICE_SET_BLOCKED_CHARGING_HOURS = "set_blocked_charging_hours"
SERVICE_SET_BLOCKED_DISCHARGING_HOURS = "set_blocked_discharging_hours"
SERVICE_SET_FIXED_PLAN_HOUR = "set_fixed_plan_hour"
SERVICE_SET_FIXED_PLAN_NAME = "set_fixed_plan_name"
SERVICE_ADD_FIXED_PLAN = "add_fixed_plan"
SERVICE_REMOVE_FIXED_PLAN = "remove_fixed_plan"
SERVICE_CALCULATE_SCHEDULE = "calculate_schedule"
SERVICE_CLEAR_SCHEDULE = "clear_schedule"

SCHEMA_TOGGLE_HOUR = vol.Schema(
    {
        vol.Required("hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Optional("date"): cv.string,
    }
)

SCHEMA_SET_HOUR_ACTION = vol.Schema(
    {
        vol.Required("hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required("action"): vol.In([ACTION_IDLE, ACTION_CHARGE, ACTION_PV_CHARGE, ACTION_DISCHARGE, ACTION_BLOCKED]),
        vol.Optional("date"): cv.string,
    }
)

SCHEMA_SET_BLOCKED_CHARGING_HOURS = vol.Schema(
    {
        vol.Required("hours"): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=23))]
        ),
    }
)

SCHEMA_SET_BLOCKED_DISCHARGING_HOURS = vol.Schema(
    {
        vol.Required("hours"): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=23))]
        ),
    }
)

SCHEMA_SET_FIXED_PLAN_HOUR = vol.Schema(
    {
        vol.Required("plan"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_FIXED_PLANS)),
        vol.Required("hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required("action"): vol.In([ACTION_IDLE, ACTION_CHARGE, ACTION_PV_CHARGE, ACTION_DISCHARGE]),
    }
)

SCHEMA_SET_FIXED_PLAN_NAME = vol.Schema(
    {
        vol.Required("plan"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_FIXED_PLANS)),
        vol.Required("name"): vol.All(str, lambda v: v.strip()),
    }
)

SCHEMA_REMOVE_FIXED_PLAN = vol.Schema(
    {
        vol.Required("plan"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_FIXED_PLANS)),
    }
)


def _get_coordinator(hass: HomeAssistant) -> VictronChargeControlCoordinator | None:
    """Get the first (and only) coordinator instance."""
    entries = hass.data.get(DOMAIN, {})
    for coordinator in entries.values():
        if isinstance(coordinator, VictronChargeControlCoordinator):
            return coordinator
    return None


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def handle_toggle_hour(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.toggle_hour(call.data["hour"], call.data.get("date"))

    async def handle_set_hour_action(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.set_hour_action(call.data["hour"], call.data["action"], call.data.get("date"))

    async def handle_set_blocked_charging_hours(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.set_blocked_charging_hours(call.data["hours"])

    async def handle_set_blocked_discharging_hours(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.set_blocked_discharging_hours(call.data["hours"])

    async def handle_set_fixed_plan_hour(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.set_fixed_plan_hour(
            call.data["plan"], call.data["hour"], call.data["action"]
        )

    async def handle_set_fixed_plan_name(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.set_fixed_plan_name(call.data["plan"], call.data["name"])

    async def handle_add_fixed_plan(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.add_fixed_plan()

    async def handle_remove_fixed_plan(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.remove_fixed_plan(call.data["plan"])

    async def handle_calculate_schedule(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.calculate_auto_schedule()
        await coordinator.async_request_refresh()

    async def handle_clear_schedule(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.error("No Victron Charge Control instance found")
            return
        coordinator.clear_schedule()

    hass.services.async_register(
        DOMAIN, SERVICE_TOGGLE_HOUR, handle_toggle_hour, schema=SCHEMA_TOGGLE_HOUR
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_HOUR_ACTION,
        handle_set_hour_action,
        schema=SCHEMA_SET_HOUR_ACTION,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BLOCKED_CHARGING_HOURS,
        handle_set_blocked_charging_hours,
        schema=SCHEMA_SET_BLOCKED_CHARGING_HOURS,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BLOCKED_DISCHARGING_HOURS,
        handle_set_blocked_discharging_hours,
        schema=SCHEMA_SET_BLOCKED_DISCHARGING_HOURS,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FIXED_PLAN_HOUR,
        handle_set_fixed_plan_hour,
        schema=SCHEMA_SET_FIXED_PLAN_HOUR,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FIXED_PLAN_NAME,
        handle_set_fixed_plan_name,
        schema=SCHEMA_SET_FIXED_PLAN_NAME,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_FIXED_PLAN, handle_add_fixed_plan
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_FIXED_PLAN,
        handle_remove_fixed_plan,
        schema=SCHEMA_REMOVE_FIXED_PLAN,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALCULATE_SCHEDULE, handle_calculate_schedule
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_SCHEDULE, handle_clear_schedule
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services."""
    hass.services.async_remove(DOMAIN, SERVICE_TOGGLE_HOUR)
    hass.services.async_remove(DOMAIN, SERVICE_SET_HOUR_ACTION)
    hass.services.async_remove(DOMAIN, SERVICE_SET_BLOCKED_CHARGING_HOURS)
    hass.services.async_remove(DOMAIN, SERVICE_SET_BLOCKED_DISCHARGING_HOURS)
    hass.services.async_remove(DOMAIN, SERVICE_SET_FIXED_PLAN_HOUR)
    hass.services.async_remove(DOMAIN, SERVICE_SET_FIXED_PLAN_NAME)
    hass.services.async_remove(DOMAIN, SERVICE_ADD_FIXED_PLAN)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE_FIXED_PLAN)
    hass.services.async_remove(DOMAIN, SERVICE_CALCULATE_SCHEDULE)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_SCHEDULE)
