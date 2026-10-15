"""Check that development setup is repeatable and preserves existing state."""

from unittest.mock import Mock, call
from urllib.error import HTTPError

import pytest

from dev import bootstrap_home_assistant as bootstrap


@pytest.fixture(autouse=True)
def no_real_solcast_key(monkeypatch):
    monkeypatch.delenv("SOLCAST_API_KEY", raising=False)


def test_existing_integration_is_not_reconfigured():
    client = Mock()
    client.request.return_value = [{"entry_id": "existing"}]

    bootstrap.configure_integration(client)

    client.request.assert_called_once_with(
        "/api/config/config_entries/entry?domain=victron_charge_control"
    )


def test_new_integration_waits_for_sensors_and_uses_dummy_entities(monkeypatch):
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    client = Mock()
    client.request.side_effect = [
        [],
        [],
        [{"entity_id": entity, "state": "10"} for entity in bootstrap.ENTITIES.values()],
        {"type": "form", "step_id": "user", "flow_id": "new"},
        {"type": "create_entry"},
        {"state": "off"},
        [],
    ]

    bootstrap.configure_integration(client)

    assert call("/api/config/config_entries/flow/new", bootstrap.ENTITIES) in client.request.call_args_list
    client.request.assert_called_with("/api/services/select/select_option", {
        "entity_id": "select.victron_charge_control_control_mode", "option": "auto",
    })


def test_invalid_existing_credentials_do_not_create_or_reset_user():
    client = Mock()
    client.request.side_effect = [
        {"flow_id": "login"}, {"type": "form", "errors": {"base": "invalid_auth"}},
    ]
    with pytest.raises(RuntimeError, match="does not reset accounts"):
        bootstrap.authenticate(client, [], "dev", "incorrect")

    assert all("onboarding/users" not in args.args[0] for args in client.request.call_args_list)


def test_partial_onboarding_only_completes_pending_steps(monkeypatch):
    client = Mock()
    client.request.side_effect = [
        {"name": "Home Assistant"},
        [{"step": "user", "done": True}, {"step": "core_config", "done": True},
         {"step": "analytics", "done": False}, {"step": "integration", "done": False}],
        {}, {}, [{"state": "loaded"}], None,
    ]
    monkeypatch.setattr(bootstrap, "authenticate", Mock(return_value="temporary-refresh-token"))
    monkeypatch.setattr(bootstrap, "configure_integration", Mock())

    bootstrap.bootstrap(client, "dev", "password")

    paths = [args.args[0] for args in client.request.call_args_list]
    assert "/api/onboarding/users" not in paths
    assert "/api/onboarding/core_config" not in paths
    assert "/api/onboarding/analytics" in paths
    assert "/api/onboarding/integration" in paths
    client.request.assert_called_with(
        "/auth/token", {"action": "revoke", "token": "temporary-refresh-token"}, form=True,
    )


def test_completed_onboarding_route_can_be_missing_and_token_is_revoked_on_failure(monkeypatch):
    client = Mock()
    client.request.side_effect = [
        {"name": "Home Assistant"},
        HTTPError("http://localhost/api/onboarding", 404, "Not Found", {}, None),
        None,
    ]
    monkeypatch.setattr(bootstrap, "authenticate", Mock(return_value="temporary-refresh-token"))
    monkeypatch.setattr(bootstrap, "configure_integration", Mock(side_effect=RuntimeError("setup failed")))

    with pytest.raises(RuntimeError, match="setup failed"):
        bootstrap.bootstrap(client, "dev", "password")

    client.request.assert_called_with(
        "/auth/token", {"action": "revoke", "token": "temporary-refresh-token"}, form=True,
    )


def test_readiness_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(bootstrap.time, "monotonic", Mock(side_effect=[0, 0, 181]))
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="Timed out waiting for dummy entities"):
        bootstrap.wait_for(lambda: False, "dummy entities")


def test_readiness_does_not_retry_authentication_errors():
    check = Mock(side_effect=HTTPError("http://localhost", 401, "Unauthorized", {}, None))
    with pytest.raises(HTTPError):
        bootstrap.wait_for(check, "Home Assistant")
    check.assert_called_once()


@pytest.mark.parametrize("api_key", ["", "  "])
def test_solcast_without_key_does_not_call_home_assistant(monkeypatch, api_key):
    monkeypatch.setenv("SOLCAST_API_KEY", api_key)
    client = Mock()

    bootstrap.configure_solcast(client)

    client.request.assert_not_called()


def test_solcast_existing_entry_preserves_key_and_settings(monkeypatch):
    monkeypatch.setenv("SOLCAST_API_KEY", "new-test-key")
    client = Mock()
    client.request.return_value = [{"entry_id": "existing"}]

    bootstrap.configure_solcast(client)

    client.request.assert_called_once_with("/api/config/config_entries/entry?domain=solcast_solar")


def test_solcast_uses_upstream_user_flow_and_daylight_updates(monkeypatch, capsys):
    monkeypatch.setenv("SOLCAST_API_KEY", "test-key-never-log")
    client = Mock()
    client.request.side_effect = [
        [], {"type": "form", "step_id": "user", "flow_id": "solcast"},
        {"type": "create_entry"},
    ]

    bootstrap.configure_solcast(client)

    assert client.request.call_args_list == [
        call("/api/config/config_entries/entry?domain=solcast_solar"),
        call("/api/config/config_entries/flow", {
            "handler": "solcast_solar", "show_advanced_options": False,
        }),
        call("/api/config/config_entries/flow/solcast", {
            "api_key": "test-key-never-log", "api_limit": "10", "auto_update": "1",
        }),
    ]
    output = capsys.readouterr()
    assert "test-key-never-log" not in output.out + output.err


@pytest.mark.parametrize("failure", [
    RuntimeError("test-key-never-log"),
    HTTPError("http://localhost/test-key-never-log", 400, "test-key-never-log", {}, None),
    {"type": "form", "errors": {"base": "test-key-never-log"},
     "description_placeholders": {"error_detail": "test-key-never-log"}},
])
def test_optional_solcast_failure_preserves_victron_and_revokes_token(monkeypatch, capsys, failure):
    monkeypatch.setenv("SOLCAST_API_KEY", "test-key-never-log")
    client = Mock()
    client.request.side_effect = [
        {"name": "Home Assistant"}, [], [{"state": "loaded"}],
        [], {"type": "form", "step_id": "user", "flow_id": "solcast"}, failure,
        None,
    ]
    configure = Mock()
    monkeypatch.setattr(bootstrap, "authenticate", Mock(return_value="temporary-refresh-token"))
    monkeypatch.setattr(bootstrap, "configure_integration", configure)

    bootstrap.bootstrap(client, "dev", "password")

    configure.assert_called_once_with(client)
    client.request.assert_called_with(
        "/auth/token", {"action": "revoke", "token": "temporary-refresh-token"}, form=True,
    )
    output = capsys.readouterr()
    assert "Optional Solcast setup failed" in output.err
    assert "Development dashboard ready" in output.out
    assert "test-key-never-log" not in output.out + output.err


def test_unexpected_solcast_flow_is_nonfatal_and_does_not_send_key(monkeypatch, capsys):
    monkeypatch.setenv("SOLCAST_API_KEY", "test-key-never-log")
    client = Mock()
    client.request.side_effect = [[], {"type": "abort", "reason": "test-key-never-log"}]

    bootstrap.configure_solcast(client)

    assert client.request.call_count == 2
    output = capsys.readouterr()
    assert "test-key-never-log" not in output.out + output.err
