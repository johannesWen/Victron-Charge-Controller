#!/usr/bin/env python3
"""Initialize the local dev Home Assistant through its onboarding/config APIs."""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DOMAIN = "victron_charge_control"
CLIENT_ID = "http://localhost:8123/"
ENTITIES = {
    "battery_soc_entity": "sensor.battery_soc",
    "grid_setpoint_entity": "number.grid_setpoint",
    "epex_spot_entity": "sensor.epex_spot_price",
    "max_grid_feed_in_entity": "number.max_grid_feed_in",
    "grid_consumption_entity": "sensor.grid_consumption_energy",
    "grid_feed_in_energy_entity": "sensor.grid_feed_in_energy",
    "solar_surplus_entity": "sensor.solar_surplus",
}


class Client:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.token = None

    def request(self, path: str, data=None, *, form=False):
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if data is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
            body = (urlencode(data) if form else json.dumps(data)).encode()
        with urlopen(Request(self.url + path, body, headers), timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else None


def wait_for(check, description: str):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if result := check():
                return result
        except HTTPError as error:
            if error.code not in (404, 502, 503):
                raise
        except (URLError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {description}")


def authenticate(client: Client, steps: list, username: str, password: str):
    if any(step["step"] == "user" and not step["done"] for step in steps):
        result = client.request("/api/onboarding/users", {
            "name": "Victron Developer", "username": username,
            "password": password, "client_id": CLIENT_ID, "language": "en",
        })
        code = result["auth_code"]
    else:
        flow = client.request("/auth/login_flow", {
            "client_id": CLIENT_ID, "handler": ["homeassistant", None],
            "redirect_uri": CLIENT_ID,
        })
        result = client.request(f"/auth/login_flow/{flow['flow_id']}", {
            "client_id": CLIENT_ID, "username": username, "password": password,
        })
        if result.get("type") != "create_entry":
            raise RuntimeError(
                "Login failed. Set HA_DEV_USERNAME and HA_DEV_PASSWORD to an existing "
                "administrator account; the bootstrap does not reset accounts."
            )
        code = result["result"]
    tokens = client.request("/auth/token", {
        "grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID,
    }, form=True)
    client.token = tokens["access_token"]
    return tokens["refresh_token"]


def configure_integration(client: Client) -> None:
    entries = client.request(f"/api/config/config_entries/entry?domain={DOMAIN}")
    if entries:
        print("Charge Control is already configured; preserving its settings.")
        return
    wait_for(
        lambda: set(ENTITIES.values()) <= {
            state["entity_id"] for state in client.request("/api/states")
            if state["state"] not in ("unknown", "unavailable")
        },
        "dummy entities",
    )
    flow = client.request("/api/config/config_entries/flow", {
        "handler": DOMAIN, "show_advanced_options": False,
    })
    if flow.get("type") != "form" or flow.get("step_id") != "user":
        raise RuntimeError(f"Unexpected integration setup response: {flow.get('type')}")
    result = client.request(f"/api/config/config_entries/flow/{flow['flow_id']}", ENTITIES)
    if result.get("type") != "create_entry":
        raise RuntimeError(f"Integration setup failed: {result.get('errors', result.get('reason'))}")
    mode = f"select.{DOMAIN}_control_mode"
    wait_for(
        lambda: client.request(f"/api/states/{mode}").get("state")
        not in (None, "unknown", "unavailable"),
        "Charge Control entities",
    )
    client.request("/api/services/select/select_option", {"entity_id": mode, "option": "auto"})
    print("Charge Control configured with dummy entities in Auto mode.")


def bootstrap(client: Client, username: str, password: str) -> None:
    wait_for(lambda: client.request("/manifest.json"), "Home Assistant")
    try:
        steps = client.request("/api/onboarding")
    except HTTPError as error:
        if error.code != 404:
            raise
        steps = []  # Home Assistant removes onboarding routes after a restart.
    refresh_token = authenticate(client, steps, username, password)
    try:
        for step in steps:
            if step["done"] or step["step"] == "user":
                continue
            data = {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID} if step["step"] == "integration" else {}
            client.request(f"/api/onboarding/{step['step']}", data)
        configure_integration(client)
        wait_for(
            lambda: any(entry["state"] == "loaded" for entry in client.request(
                f"/api/config/config_entries/entry?domain={DOMAIN}"
            )),
            "Charge Control to load",
        )
        print("Development dashboard ready: http://localhost:8123/victron-dev/settings")
    finally:
        client.request("/auth/token", {"action": "revoke", "token": refresh_token}, form=True)


if __name__ == "__main__":
    try:
        bootstrap(
            Client(os.environ.get("HA_DEV_URL", "http://homeassistant:8123")),
            os.environ.get("HA_DEV_USERNAME", "dev"),
            os.environ.get("HA_DEV_PASSWORD", "victron-dev"),
        )
    except HTTPError as error:
        print(f"Home Assistant bootstrap failed: {error.url}: HTTP {error.code}", file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, URLError, TimeoutError) as error:
        print(f"Home Assistant bootstrap failed: {error}", file=sys.stderr)
        sys.exit(1)
