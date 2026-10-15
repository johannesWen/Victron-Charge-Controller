"""Exercise the real HA WebSocket dispatcher against the cache-only endpoint."""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components.websocket_api import ActiveConnection

from custom_components.victron_charge_control import async_setup, async_setup_entry, async_unload_entry
from custom_components.victron_charge_control.const import CARD_REGISTERED_KEY, DOMAIN
from custom_components.victron_charge_control.forecast import ForecastInterval, ForecastSnapshot
from custom_components.victron_charge_control.websocket_api import COMMAND, async_register_commands

NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)
MODULE = "custom_components.victron_charge_control.websocket_api"


@pytest.fixture
def endpoint(mock_hass, coordinator):
    """Use HA's schema validation, dispatch, and JSON response serialization."""
    mock_hass.config.time_zone = "Europe/Vienna"
    mock_hass.data[DOMAIN] = {"entry": coordinator, CARD_REGISTERED_KEY: True}
    async_register_commands(mock_hass)
    messages = []
    user = MagicMock(is_admin=False, is_active=True)
    user.permissions.access_all_entities.return_value = True
    connection = ActiveConnection(MagicMock(), mock_hass, messages.append, user, None, None)

    def request(**extra):
        connection.async_handle({"id": connection.last_id + 1, "type": COMMAND, **extra})
        message = messages[-1]
        return json.loads(message) if isinstance(message, (str, bytes)) else message

    with patch(f"{MODULE}.dt_util.utcnow", return_value=NOW):
        yield mock_hass, coordinator, connection, request


def test_serialization_and_cache_only(endpoint):
    hass, coordinator, connection, request = endpoint
    start = NOW.replace(hour=11)
    coordinator.forecast_coordinator.data = ForecastSnapshot(
        intervals=(
            ForecastInterval(start, start + timedelta(minutes=30), 2.5, 1.2, 4.0),
            ForecastInterval(start + timedelta(minutes=30), start + timedelta(hours=1), 3.0),
        ),
        status="ready", usable=True, reason=None, source_updated_at=NOW,
        source_entry_id="private-entry", discovered_entity_ids=("sensor.private_source",),
    )
    coordinator.forecast_coordinator.async_request_refresh = MagicMock(side_effect=AssertionError("refresh"))
    coordinator.forecast_coordinator.async_refresh = MagicMock(side_effect=AssertionError("refresh"))
    result = request()
    assert result["success"] is True
    payload = result["result"]
    assert set(payload) == {"status", "usable", "reason", "source_updated_at", "time_zone", "days", "intervals"}
    assert payload["status"] == "ready"
    assert payload["source_updated_at"] == NOW.isoformat()
    assert payload["intervals"] == [
        {"start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(), "pv_estimate": 2.5, "pv_estimate10": 1.2},
        {"start": (start + timedelta(minutes=30)).isoformat(), "end": (start + timedelta(hours=1)).isoformat(), "pv_estimate": 3.0, "pv_estimate10": None},
    ]
    assert "private" not in json.dumps(payload)
    assert request()["result"] == payload
    hass.services.async_call.assert_not_called()
    assert request()["success"] is True
    coordinator.forecast_coordinator.async_request_refresh.assert_not_called()
    coordinator.forecast_coordinator.async_refresh.assert_not_called()
    connection.user.permissions.access_all_entities.assert_called_with(POLICY_READ)


@pytest.mark.parametrize("status", ["disabled", "not_detected", "stale", "incomplete", "invalid_data", "unavailable"])
def test_unusable_snapshot_never_exposes_intervals(endpoint, status):
    _, coordinator, _, request = endpoint
    coordinator.forecast_coordinator.data = ForecastSnapshot(
        intervals=(ForecastInterval(NOW, NOW + timedelta(minutes=30), 9),),
        status=status, reason="Unavailable forecast",
    )
    payload = request()["result"]
    assert payload["intervals"] == []
    assert payload["usable"] is False
    assert payload["status"] == status
    assert payload["reason"] == "Unavailable forecast"


def test_no_loaded_coordinator(endpoint):
    hass, _, _, request = endpoint
    hass.data[DOMAIN] = {CARD_REGISTERED_KEY: True}
    payload = request()["result"]
    assert payload["status"] == "unavailable"
    assert payload["usable"] is False
    assert payload["reason"]
    assert payload["source_updated_at"] is None
    assert payload["intervals"] == []
    assert len(payload["days"]) == 2


def test_only_intervals_overlapping_local_days_are_returned(endpoint):
    _, coordinator, _, request = endpoint
    start = datetime(2026, 10, 14, 22, tzinfo=UTC)
    end = start + timedelta(days=2)
    coordinator.forecast_coordinator.data = ForecastSnapshot(
        usable=True, status="ready", reason=None,
        intervals=tuple(
            ForecastInterval(timestamp, timestamp + timedelta(minutes=30), power)
            for timestamp, power in (
                (start - timedelta(minutes=30), 1), (start, 2),
                (end - timedelta(minutes=30), 3), (end, 4),
            )
        ),
    )
    payload = request()["result"]
    assert [item["pv_estimate"] for item in payload["intervals"]] == [2, 3]
    with patch(f"{MODULE}.dt_util.utcnow", return_value=datetime(2026, 10, 14, 23, tzinfo=UTC)):
        assert request()["result"]["days"][0]["date"] == "2026-10-15"


@pytest.mark.parametrize(("now", "hours"), [
    (datetime(2026, 3, 29, 10, tzinfo=UTC), 23),
    (datetime(2026, 10, 25, 10, tzinfo=UTC), 25),
])
def test_true_dst_day_bounds(endpoint, now, hours):
    _, _, _, request = endpoint
    with patch(f"{MODULE}.dt_util.utcnow", return_value=now):
        payload = request()["result"]
    today, tomorrow = payload["days"]
    assert payload["time_zone"] == "Europe/Vienna"
    assert today["date"] == now.date().isoformat()
    assert today["end"] == tomorrow["start"]
    assert (datetime.fromisoformat(today["end"]) - datetime.fromisoformat(today["start"])).total_seconds() == hours * 3600
    assert (datetime.fromisoformat(tomorrow["end"]) - datetime.fromisoformat(tomorrow["start"])).total_seconds() == 86400


@pytest.mark.parametrize("inactive", [False, True])
def test_authentication_required(endpoint, inactive):
    _, _, connection, request = endpoint
    if inactive:
        connection.user.is_active = False
    else:
        connection.user = None
    response = request()
    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


def test_restricted_user_requires_all_source_read_permissions(endpoint):
    _, coordinator, connection, request = endpoint
    connection.user.permissions.access_all_entities.return_value = False
    coordinator.forecast_coordinator.data = ForecastSnapshot(
        discovered_entity_ids=("sensor.source_a", "sensor.source_b"),
    )
    connection.user.permissions.check_entity.side_effect = lambda entity, policy: entity == "sensor.source_a"
    assert request()["error"]["code"] == "unauthorized"
    connection.user.permissions.check_entity.side_effect = None
    connection.user.permissions.check_entity.return_value = True
    assert request()["success"] is True
    connection.user.permissions.check_entity.assert_any_call("sensor.source_b", POLICY_READ)
    coordinator.forecast_coordinator.data = ForecastSnapshot()
    assert request()["error"]["code"] == "unauthorized"


def test_extra_arguments_rejected(endpoint):
    _, _, _, request = endpoint
    response = request(api_key="do-not-accept")
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


async def test_registration_survives_setup_unload_reload(mock_hass, mock_config_entry):
    """Keep command state outside entry storage and use the currently loaded cache."""
    mock_config_entry.add_update_listener = MagicMock(return_value=MagicMock())
    coordinator = MagicMock()
    coordinator.async_setup = AsyncMock()
    coordinator.async_shutdown = AsyncMock()
    with (
        patch("custom_components.victron_charge_control._async_register_card", new=AsyncMock()),
        patch("custom_components.victron_charge_control.VictronChargeControlCoordinator", return_value=coordinator),
        patch("custom_components.victron_charge_control.async_setup_services", new=AsyncMock()) as setup_services,
        patch("custom_components.victron_charge_control.async_unload_services", new=AsyncMock()),
    ):
        await async_setup(mock_hass, {})
        handler = mock_hass.data["websocket_api"][COMMAND][0]
        await async_setup_entry(mock_hass, mock_config_entry)
        assert set(mock_hass.data[DOMAIN]) == {mock_config_entry.entry_id}
        setup_services.assert_awaited_once()
        await async_unload_entry(mock_hass, mock_config_entry)
        assert mock_hass.data[DOMAIN] == {}
        assert mock_hass.data["websocket_api"][COMMAND][0] is handler
        await async_setup_entry(mock_hass, mock_config_entry)
        assert mock_hass.data["websocket_api"][COMMAND][0] is handler
        assert setup_services.await_count == 2
