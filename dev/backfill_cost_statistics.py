#!/usr/bin/env python3
"""Backfill Home Assistant cost/revenue long-term statistics for dev data.

This imports hourly statistics for the dashboard card's cost view:

  sensor.victron_charge_control_grid_energy_cost
  sensor.victron_charge_control_grid_energy_revenue

It uses the same dummy consumption, feed-in, and EPEX price profiles as
dev/configuration.yaml, then calls Home Assistant's recorder/import_statistics
WebSocket command. No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
import struct
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


CONSUMPTION_KWH = [
    0.32, 0.28, 0.25, 0.22, 0.25, 0.42, 0.68, 0.91,
    0.86, 0.72, 0.58, 0.52, 0.49, 0.51, 0.57, 0.76,
    1.02, 1.34, 1.52, 1.21, 0.93, 0.67, 0.49, 0.38,
]

FEED_IN_KWH = [
    0.00, 0.00, 0.00, 0.00, 0.00, 0.02, 0.14, 0.38,
    0.72, 1.05, 1.38, 1.62, 1.78, 1.71, 1.49, 1.12,
    0.74, 0.36, 0.12, 0.02, 0.00, 0.00, 0.00, 0.00,
]

PRICES_TODAY_EUR_PER_KWH = [
    0.032, 0.028, 0.021, 0.015, 0.023, 0.057, 0.084, 0.123,
    0.156, 0.142, 0.118, 0.105, 0.091, 0.087, 0.112, 0.189,
    0.225, 0.283, 0.421, 0.257, 0.194, 0.148, 0.096, 0.052,
]

DEFAULT_PREFIX = "victron_charge_control"
DEFAULT_URL = "http://localhost:8123"
DEFAULT_TZ = "Europe/Berlin"


@dataclass
class HourlyTotals:
    cost: list[dict[str, Any]]
    revenue: list[dict[str, Any]]
    energy_import: list[dict[str, Any]]
    energy_export: list[dict[str, Any]]


@dataclass
class ParsedWsUrl:
    scheme: str
    hostname: str
    port: int
    path: str


class HassWebSocket:
    """Tiny Home Assistant WebSocket client for one-off dev imports."""

    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self.base_url = base_url
        self.token = token
        self.timeout = timeout
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._next_id = 1

    def __enter__(self) -> "HassWebSocket":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._sock is not None:
            try:
                self._send_frame(b"", opcode=0x8)
            finally:
                self._sock.close()

    def connect(self) -> None:
        parsed = _parse_ws_url(self.base_url)
        raw_sock = socket.create_connection((parsed.hostname, parsed.port), self.timeout)
        raw_sock.settimeout(self.timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            self._sock = context.wrap_socket(raw_sock, server_hostname=parsed.hostname)
        else:
            self._sock = raw_sock

        self._handshake(parsed.hostname, parsed.port, parsed.path)
        greeting = self.receive_json()
        if greeting.get("type") != "auth_required":
            raise RuntimeError(f"Expected auth_required, got: {greeting}")

        self.send_json({"type": "auth", "access_token": self.token})
        auth = self.receive_json()
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"Authentication failed: {auth}")

    def command(self, payload: dict[str, Any]) -> Any:
        msg_id = self._next_id
        self._next_id += 1
        self.send_json({"id": msg_id, **payload})

        while True:
            response = self.receive_json()
            if response.get("id") != msg_id:
                continue
            if not response.get("success", False):
                raise RuntimeError(response.get("error", response))
            return response.get("result")

    def send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(json.dumps(payload, separators=(",", ":")).encode())

    def receive_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x1:
                return json.loads(payload.decode())
            if opcode == 0x8:
                raise RuntimeError("WebSocket closed by server")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._write(request.encode())
        response = self._read_until(b"\r\n\r\n")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response.decode(errors="replace"))

        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        ).decode()
        if f"sec-websocket-accept: {expected}".lower().encode() not in response.lower():
            raise RuntimeError("Invalid WebSocket handshake response")

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        mask_key = secrets.token_bytes(4)
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend(struct.pack("!BH", 0x80 | 126, length))
        else:
            header.extend(struct.pack("!BQ", 0x80 | 127, length))
        masked = bytes(byte ^ mask_key[i % 4] for i, byte in enumerate(payload))
        self._write(bytes(header) + mask_key + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        header = self._read_exact(2)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask_key = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if masked:
            payload = bytes(byte ^ mask_key[i % 4] for i, byte in enumerate(payload))
        return opcode, payload

    def _write(self, data: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("WebSocket is not connected")
        self._sock.sendall(data)

    def _read_exact(self, length: int) -> bytes:
        if self._sock is None:
            raise RuntimeError("WebSocket is not connected")
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self._sock.recv(length - len(chunks))
            if not chunk:
                raise RuntimeError("Connection closed while reading")
            chunks.extend(chunk)
        return bytes(chunks)

    def _read_until(self, marker: bytes) -> bytes:
        if self._sock is None:
            raise RuntimeError("WebSocket is not connected")
        chunks = bytearray()
        while marker not in chunks:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("Connection closed while reading")
            chunks.extend(chunk)
        return bytes(chunks)


def _parse_ws_url(base_url: str):
    parsed = urlparse(base_url)
    scheme = parsed.scheme
    if scheme in ("http", "https"):
        scheme = "ws" if scheme == "http" else "wss"
    if scheme not in ("ws", "wss"):
        raise ValueError("URL must start with http://, https://, ws://, or wss://")

    port = parsed.port or (443 if scheme == "wss" else 80)
    if parsed.hostname is None:
        raise ValueError("URL must include a hostname")
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        path = "/api/websocket"
    elif not path.endswith("/api/websocket"):
        path = f"{path}/api/websocket"
    return ParsedWsUrl(scheme=scheme, hostname=parsed.hostname, port=port, path=path)


def price_for_hour(day_offset: int, hour: int) -> float:
    """Return the dummy EPEX price for a historical day/hour."""
    if day_offset < 0:
        day_factor = 1 + ((abs(day_offset) % 5) - 2) * 0.04
        return round(PRICES_TODAY_EUR_PER_KWH[hour] * day_factor, 3)
    return PRICES_TODAY_EUR_PER_KWH[hour]


def build_hourly_totals(
    days: int,
    tz_name: str,
    base_cost: float,
    base_revenue: float,
    base_import: float = 0.0,
    base_export: float = 0.0,
    now: datetime | None = None,
) -> HourlyTotals:
    tz = ZoneInfo(tz_name)
    now = now.astimezone(tz) if now else datetime.now(tz)
    today = datetime.combine(now.date(), time.min, tz)
    first_day = today - timedelta(days=days)
    last_hour = now.replace(minute=0, second=0, microsecond=0)

    cost = base_cost
    revenue = base_revenue
    energy_import = base_import
    energy_export = base_export
    cost_rows = [
        stat_row(first_day - timedelta(hours=1), cost),
    ]
    revenue_rows = [
        stat_row(first_day - timedelta(hours=1), revenue),
    ]
    import_rows = [
        stat_row(first_day - timedelta(hours=1), energy_import),
    ]
    export_rows = [
        stat_row(first_day - timedelta(hours=1), energy_export),
    ]

    current = first_day
    while current <= last_hour:
        day_offset = (current.date() - today.date()).days
        hour = current.hour
        price = price_for_hour(day_offset, hour)
        consumption = CONSUMPTION_KWH[hour]
        feed_in = FEED_IN_KWH[hour]

        if price >= 0:
            cost += consumption * price
            revenue += feed_in * price
        else:
            cost += feed_in * abs(price)
            revenue += consumption * abs(price)

        energy_import += consumption
        energy_export += feed_in

        cost_rows.append(stat_row(current, cost))
        revenue_rows.append(stat_row(current, revenue))
        import_rows.append(stat_row(current, energy_import))
        export_rows.append(stat_row(current, energy_export))
        current += timedelta(hours=1)

    return HourlyTotals(
        cost=cost_rows,
        revenue=revenue_rows,
        energy_import=import_rows,
        energy_export=export_rows,
    )


def stat_row(start: datetime, value: float) -> dict[str, Any]:
    rounded = round(value, 4)
    return {
        "start": start.isoformat(),
        "state": rounded,
        "sum": rounded,
    }


def import_payload(statistic_id: str, rows: list[dict[str, Any]], unit: str = "EUR") -> dict[str, Any]:
    return {
        "type": "recorder/import_statistics",
        "metadata": {
            "has_mean": False,
            "mean_type": 0,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": statistic_id,
            "unit_class": None,
            "unit_of_measurement": unit,
        },
        "stats": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill dev Home Assistant cost/revenue statistics."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"HA URL, default {DEFAULT_URL}")
    parser.add_argument(
        "--token",
        default=os.environ.get("HA_TOKEN") or os.environ.get("HASS_TOKEN"),
        help="Long-lived access token. Defaults to HA_TOKEN or HASS_TOKEN.",
    )
    parser.add_argument("--days", type=int, default=30, help="Days to backfill.")
    parser.add_argument(
        "--timezone", default=DEFAULT_TZ, help=f"IANA timezone, default {DEFAULT_TZ}"
    )
    parser.add_argument(
        "--prefix", default=DEFAULT_PREFIX, help=f"Entity prefix, default {DEFAULT_PREFIX}"
    )
    parser.add_argument("--base-cost", type=float, default=0.0)
    parser.add_argument("--base-revenue", type=float, default=0.0)
    parser.add_argument("--base-import", type=float, default=0.0, help="Base cumulative import kWh.")
    parser.add_argument("--base-export", type=float, default=0.0, help="Base cumulative export kWh.")
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Clear existing statistics for the two cost entities before importing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a summary and sample rows without connecting to Home Assistant.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days < 0:
        print("--days must be >= 0", file=sys.stderr)
        return 2

    cost_id = f"sensor.{args.prefix}_grid_energy_cost"
    revenue_id = f"sensor.{args.prefix}_grid_energy_revenue"
    import_id = f"sensor.{args.prefix}_grid_energy_import"
    export_id = f"sensor.{args.prefix}_grid_energy_export"
    totals = build_hourly_totals(
        days=args.days,
        tz_name=args.timezone,
        base_cost=args.base_cost,
        base_revenue=args.base_revenue,
        base_import=args.base_import,
        base_export=args.base_export,
    )

    print(f"Cost statistic:    {cost_id}")
    print(f"Revenue statistic: {revenue_id}")
    print(f"Import statistic:  {import_id}")
    print(f"Export statistic:  {export_id}")
    print(f"Cost rows:         {len(totals.cost)}")
    print(f"Revenue rows:      {len(totals.revenue)}")
    print(f"Import rows:        {len(totals.energy_import)}")
    print(f"Export rows:        {len(totals.energy_export)}")
    print(f"Range:             {totals.cost[0]['start']} -> {totals.cost[-1]['start']}")
    print(f"Final cost sum:    {totals.cost[-1]['sum']:.4f} EUR")
    print(f"Final revenue sum: {totals.revenue[-1]['sum']:.4f} EUR")
    print(f"Final import sum:  {totals.energy_import[-1]['sum']:.4f} kWh")
    print(f"Final export sum:  {totals.energy_export[-1]['sum']:.4f} kWh")

    if args.dry_run:
        print("\nSample cost rows:")
        print(json.dumps(totals.cost[:2] + totals.cost[-2:], indent=2))
        return 0

    if not args.token:
        print(
            "Missing token. Create a Home Assistant long-lived access token and pass "
            "--token, or set HA_TOKEN/HASS_TOKEN.",
            file=sys.stderr,
        )
        return 2

    with HassWebSocket(args.url, args.token) as hass:
        if args.clear_first:
            print("Clearing existing cost/revenue/energy statistics...")
            hass.command({
                "type": "recorder/clear_statistics",
                "statistic_ids": [cost_id, revenue_id, import_id, export_id],
            })

        print("Importing cost statistics...")
        hass.command(import_payload(cost_id, totals.cost))
        print("Importing revenue statistics...")
        hass.command(import_payload(revenue_id, totals.revenue))
        print("Importing energy import statistics...")
        hass.command(import_payload(import_id, totals.energy_import, unit="kWh"))
        print("Importing energy export statistics...")
        hass.command(import_payload(export_id, totals.energy_export, unit="kWh"))

    print("Done. Refresh the Costs view after Home Assistant finishes recorder writes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
