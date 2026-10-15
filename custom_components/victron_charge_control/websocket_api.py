"""Read-only WebSocket access to the validated local forecast snapshot."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .forecast import ForecastSnapshot
from .services import _get_coordinator

COMMAND = "victron_charge_control/solar_forecast"


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register once by command name, including after config-entry reloads."""
    websocket_api.async_register_command(
        hass, COMMAND, websocket_solar_forecast,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend({"type": COMMAND}),
    )


@callback
def websocket_solar_forecast(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serialize the cache without refreshing it or exposing source configuration."""
    user = connection.user
    if user is None or not user.is_active:
        connection.send_error(msg["id"], websocket_api.ERR_UNAUTHORIZED, "Authentication required")
        return

    coordinator = _get_coordinator(hass)
    snapshot = (
        coordinator.forecast_coordinator.data if coordinator is not None
        else ForecastSnapshot(status="unavailable", reason="Charge control integration is not loaded")
    )
    if not user.is_admin and not user.permissions.access_all_entities(POLICY_READ):
        # The aggregate contains all sites, so partial entity access is insufficient.
        if not snapshot.discovered_entity_ids or any(
            not user.permissions.check_entity(entity_id, POLICY_READ)
            for entity_id in snapshot.discovered_entity_ids
        ):
            connection.send_error(msg["id"], websocket_api.ERR_UNAUTHORIZED, "Forecast read access required")
            return

    zone = ZoneInfo(hass.config.time_zone)
    today = dt_util.utcnow().astimezone(zone).date()
    bounds = [datetime.combine(today + timedelta(days=i), time.min, zone) for i in range(3)]
    connection.send_result(msg["id"], {
        "status": snapshot.status,
        "usable": snapshot.usable,
        "reason": snapshot.reason,
        "source_updated_at": snapshot.source_updated_at.isoformat() if snapshot.source_updated_at else None,
        "time_zone": hass.config.time_zone,
        "days": [
            {"date": start.date().isoformat(), "start": start.isoformat(), "end": end.isoformat()}
            for start, end in zip(bounds, bounds[1:])
        ],
        "intervals": [
            {
                "start": interval.start.isoformat(), "end": interval.end.isoformat(),
                "pv_estimate": interval.power_kw, "pv_estimate10": interval.lower_power_kw,
            }
            for interval in snapshot.intervals
            if interval.start < bounds[-1] and interval.end > bounds[0]
        ] if snapshot.usable else [],
    })
