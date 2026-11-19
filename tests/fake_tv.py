"""Fake JointSpace server (Titan OS) for tests and development.

- `FakeTitanTV.handle()` : pure logic (records requests and keys, updates the state).
- `FakeTitanTV.transport()` : `httpx.MockTransport` adapter for tests, with
  simulation of an unreachable TV, latency and errors.
- `python -m tests.fake_tv --port 1925` : standalone HTTP server (no TLS or Digest),
  used with the Remote simulator. Pairing PIN: 1234.
- `--routes-json FILE`: GET responses forced per path (`{"/6/system": {...}}`), which
  replace or complete the built-in routes; used to imitate a real TV against the Philips
  app (see tests/fixtures/titan_routes.json).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

_LOG = logging.getLogger("fake_tv")

# Public JointSpace pairing secret. The fake TV signs on its own (stdlib), so the tests check the
# integration's signature against an independent implementation.
PAIRING_SECRET = base64.b64decode(
    "ZmVay1EQVFOaZhwQ4Kv81ypLAZNczV9sG4KkseXWn1NEk6cXmPKO/MCa9sryslvLCFMnNe4Z4CPXzToowvhHvA=="
)


def expected_signature(timestamp: str, pin: str) -> str:
    digest = hmac.new(PAIRING_SECRET, (timestamp + pin).encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()

# Ambilight as on a real 65OLED851 (capture of the Philips Smart TV app, 2026-11-18).
AMBILIGHT_STYLE_NODE = 200  # style: activenode_id = 210 off, 220 video, 230 audio, 240 color, 260 app
AMBILIGHT_STYLE_OFF = 210
AMBILIGHT_VIDEO_NODE = 220  # list node: video variant by selected_item (221 to 225)
AMBILIGHT_AUDIO_NODE = 230  # list node: audio variant by selected_item (231 to 233)
AMBILIGHT_BRIGHTNESS_NODE = 271  # brightness: value 0 to 10
AMBILIGHT_SATURATION_NODE = 272  # saturation: value -2 to 2
PICTURE_STYLE_NODE = 2131230900  # fictitious identifier of the fake server

DEV_PIN = "1234"

# Value of a settings node: activenode_id (parent node) or selected_item (list node).
_NODE_VALUE_KEYS = ("activenode_id", "selected_item", "value")


class FakeTitanTV:
    def __init__(self) -> None:
        self.online = True
        self.offline_hang = 10.0  # duration before a request fails when the TV is unreachable
        self.offline_exception: type[httpx.TransportError] = httpx.ConnectTimeout
        self.power = "On"
        self.volume = 10
        self.muted = False
        self.key_delay = 0.0
        self.fail_next_key_with_timeout = False
        self.fail_next_get = False
        self.ambilight: dict[str, Any] = {"power": "Off"}
        self.activity: dict[str, Any] | None = None
        self.keys: list[tuple[float, str]] = []
        self.requests: list[tuple[float, str, str]] = []
        self._pair_timestamp: int | None = None
        # Titan OS (see spec §8.1): context, screen, settings, Ambilight through node 200.
        self.context: dict[str, Any] = {"level1": "NetTv", "level2": "Home", "level3": ""}
        self.screen = "On"
        self.ambilight_config: dict[str, Any] = {
            "styleName": "FOLLOW_VIDEO",
            "isExpert": False,
            "menuSetting": "NATURAL",
        }
        self.menu_nodes: dict[int, dict[str, Any]] = {
            AMBILIGHT_STYLE_NODE: {
                "string_id": "MAIN_AMBILIGHT_STYLE",
                "type": "PARENT_NODE",
                "children": {
                    210: "MAIN_AMBILIGHT_STYLE_OFF",
                    220: "MAIN_FOLLOW_VIDEO",
                    230: "MAIN_FOLLOW_AUDIO",
                    240: "MAIN_FOLLOW_COLOUR",
                    260: "MAIN_FOLLOW_APP",
                },
                "activenode_id": 220,
            },
            AMBILIGHT_VIDEO_NODE: {
                "string_id": "MAIN_FOLLOW_VIDEO",
                "type": "LIST_NODE",
                "children": {
                    221: "MISC_AI",
                    222: "MAIN_AMBILIGHT_STYLE_VIDEO_1_2K20",
                    223: "MAIN_AMBILIGHT_STYLE_VIDEO_3_2K20",
                    224: "MAIN_AMBILIGHT_CINEMA",
                    225: "MAIN_AMBILIGHT_GAME_2K23",
                },
                "selected_item": 222,
            },
            AMBILIGHT_AUDIO_NODE: {
                "string_id": "MAIN_FOLLOW_AUDIO",
                "type": "LIST_NODE",
                "children": {
                    231: "MAIN_AMBILIGHT_STYLE_AUDIO_1_2K20",
                    232: "MAIN_FOLLOW_AUDIO_STYLE_3_2K23",
                    233: "MAIN_AMBILIGHT_STYLE_AUDIO_3_2K20",
                },
                "selected_item": 231,
            },
            AMBILIGHT_BRIGHTNESS_NODE: {
                "string_id": "MAIN_AMBILIGHT_BRIGHTNESS",
                "type": "SLIDER_NODE",
                "children": {},
                "value": 5,
            },
            AMBILIGHT_SATURATION_NODE: {
                "string_id": "MAIN_AMBILIGHT_SATURATION",
                "type": "SLIDER_NODE",
                "children": {},
                "value": 0,
            },
            PICTURE_STYLE_NODE: {
                "string_id": "MAIN_PICTURE_STYLE",
                "type": "PARENT_NODE",
                "children": {1: "Vivid", 2: "Natural", 3: "Movie", 4: "Game"},
                "activenode_id": 2,
            },
        }
        self.structure_requests = 0
        self.settings_updates: list[dict[str, Any]] = []  # values received by settings/update
        # Degradation (H2): after `wedge_after` requests spaced by less than `wedge_interval` s,
        # nothing answers anymore (TLS no longer establishes).
        self.wedge_after: int | None = None
        self.wedge_interval = 1.0
        self.wedged = False
        self._fast_count = 0
        self.answer_404_everywhere = False
        self.powerstate_lies = False
        # Behavior of the real 65OLED851 (exploration of 2026-11-18), enabled by `realistic()`:
        # notifychange answers immediately with the real state, POST powerstate is ignored, and
        # the reported state stays the old one for `power_report_lag` s after the Standby key.
        self.notify_immediate = False
        self.powerstate_post_ignored = False
        self.power_report_lag = 0.0
        self._previous_power = self.power
        self._power_changed_at = float("-inf")
        self.refuse_settings_update = False
        # Real TV on the evening of 2026-11-18: notifychange answers 503 on almost every call (Remote log).
        self.notify_unavailable = False
        # notifychange only answers 200 on a change since its last answer, otherwise 503
        # (Remote log of 2026-11-18: 200 right after each Standby key, 503 afterwards).
        self.notify_changes_only = False
        self._notified_power: str | None = None
        # Listening (long-poll) like the Philips app: the TV keeps the request open as long as
        # the state sent by the client is its own, at most `notify_hold` s, then answers {}.
        self.notify_hold = 2.0
        self.notify_pending = 0  # notifychange requests pending on the TV side
        self.notify_max_pending = 0
        # Real TV on 2026-11-19 (Remote log, 12:11): a listen opened before a Standby key
        # did not report the power-on and held until the client timeout.
        self.notify_misses_switch = False
        # Real TV on 2026-11-19 (Remote log, 14:29): while it boots after a Standby key, a
        # notifychange request opened in the first `boot_silence` s never gets an answer.
        self.boot_silence = 0.0
        self._switch_count = 0
        self.slow_after: int | None = None  # beyond N requests, each answer takes slow_delay s
        self.slow_delay = 0.0
        self._change_event = asyncio.Event()
        self._last_change: dict[str, Any] = {}
        # GET responses forced per path (take priority over the built-in routes).
        self.get_overrides: dict[str, Any] = {}
        self.bodies: list[tuple[str, Any]] = []  # (path, JSON body) of every request with a body
        self.system_https_down = False  # HTTPS refuses connections: discovery must fall back to HTTP
        self.last_auth_key: str | None = None

    @classmethod
    def realistic(cls) -> FakeTitanTV:
        """Fake TV that behaves like the real 65OLED851 (Titan OS)."""
        tv = cls()
        tv.notify_immediate = True
        tv.powerstate_lies = True
        tv.powerstate_post_ignored = True
        return tv

    @property
    def reported_power(self) -> str:
        """Power state as notifychange reports it (with the real TV's lag)."""
        if time.monotonic() - self._power_changed_at < self.power_report_lag:
            return self._previous_power
        return self.power

    # ------------------------------------------------------------------ logique pure
    def handle(self, method: str, path: str, body: Any) -> tuple[int, Any]:
        now = time.monotonic()
        self.requests.append((now, method, path))
        if body is not None:
            self.bodies.append((path, body))
        route = path.split("?", 1)[0].rstrip("/")
        body = body if isinstance(body, dict) else {}
        if self.answer_404_everywhere:
            return 404, None
        if method == "GET" and route in self.get_overrides:
            return 200, self.get_overrides[route]

        if route == "/6/system" and method == "GET":
            return 200, {
                "name": "Fake Titan TV",
                "api_version": {"Major": 6, "Minor": 1, "Patch": 0},
                "featuring": {"systemfeatures": {"secured_transport": "false", "pairing_type": "digest_auth_pairing"}},
            }
        if route == "/6/powerstate":
            if method == "POST":
                if not self.powerstate_post_ignored:
                    self.power = str(body.get("powerstate", self.power))
                return 200, None
            # H1: on Titan OS, powerstate can say "On" while the TV is in standby.
            return 200, {"powerstate": "On" if self.powerstate_lies else self.power}
        if route == "/6/audio/volume":
            if method == "POST":
                self.volume = int(body.get("current", self.volume))
                self.muted = bool(body.get("muted", self.muted))
                return 200, None
            return 200, {"min": 0, "max": 60, "current": self.volume, "muted": self.muted}
        if route == "/6/input/key" and method == "POST":
            key = str(body.get("key", ""))
            self.keys.append((now, key))
            _LOG.info("KEY %s", key)
            if key == "Standby":
                # On ↔ standby toggle; powerstate may keep saying "On" (H1): `power` is the truth.
                self._previous_power = self.reported_power
                self._power_changed_at = now
                self._switch_count += 1
                self.power = "On" if self.power == "Standby" else "Standby"
            return 200, None  # Titan OS answers 200 even for an unknown key
        if route == "/6/ambilight/power":
            if method == "POST":
                self.ambilight["power"] = str(body.get("power", "Off"))
                return 200, None
            return 200, {"power": self.ambilight["power"]}
        if route == "/6/context" and method == "GET":
            return 200, dict(self.context)
        if route == "/6/screenstate" and method == "GET":
            return 200, {"screenstate": self.screen}
        if route == "/6/ambilight/currentconfiguration":
            if method == "POST":
                self.ambilight_config = dict(body)  # accepted but with no effect on the LEDs (H4)
                return 200, None
            return 200, dict(self.ambilight_config)
        if route == "/6/menuitems/settings/current" and method == "POST":
            values = []
            for node in body.get("nodes", []):
                entry = self.menu_nodes.get(int(node.get("nodeid", 0)))
                if entry is not None:
                    values.append(
                        {
                            "value": {
                                "Nodeid": int(node["nodeid"]),
                                "Controllable": True,
                                "Available": True,
                                "string_id": entry["string_id"],
                                "data": {key: entry[key] for key in _NODE_VALUE_KEYS if key in entry},
                            }
                        }
                    )
            return 200, {"version": 0, "values": values}
        if route == "/6/menuitems/settings/update" and method == "POST":
            if self.refuse_settings_update:
                return 403, None
            for item in body.get("values", []):
                value = item.get("value", {})
                self.settings_updates.append(value)
                entry = self.menu_nodes.get(int(value.get("Nodeid", 0)))
                if entry is not None:
                    for key in _NODE_VALUE_KEYS:
                        if key in entry and key in value.get("data", {}):
                            entry[key] = int(value["data"][key])
            return 200, None
        if route == "/6/menuitems/settings/structure" and method == "GET":
            self.structure_requests += 1
            nodes = [
                {
                    "node_id": node_id,
                    "string_id": entry["string_id"],
                    "type": entry["type"],
                    "data": {
                        "nodes": [
                            {"node_id": child, "string_id": label} for child, label in entry["children"].items()
                        ]
                    },
                }
                for node_id, entry in self.menu_nodes.items()
            ]
            return 200, {"node": {"node_id": 1, "string_id": "Settings", "data": {"nodes": nodes}}}
        if route == "/6/notifychange" and method == "POST":
            if self.notify_unavailable:
                return 503, None
            if self.notify_changes_only:
                if self.reported_power == self._notified_power:
                    return 503, None
                self._notified_power = self.reported_power
            if self.notify_immediate:
                return 200, {"context": dict(self.context), "powerstate": {"powerstate": self.reported_power}}
            return 200, dict(self._last_change)
        if route == "/6/activities/current" and method == "GET":
            if self.activity is None:
                return 404, None
            return 200, self.activity
        if route == "/6/pair/request" and method == "POST":
            self._pair_timestamp = int(time.time())
            self.last_auth_key = secrets.token_hex(32)
            return 200, {"error_id": "SUCCESS", "timestamp": self._pair_timestamp, "auth_key": self.last_auth_key}
        if route == "/6/pair/grant" and method == "POST":
            auth = body.get("auth", {})
            expected = expected_signature(str(self._pair_timestamp), DEV_PIN)
            if auth.get("auth_signature") == expected and str(auth.get("pin")) == DEV_PIN:
                return 200, {"error_id": "SUCCESS"}
            return 200, {"error_id": "INVALID_PIN"}
        return 404, None

    @property
    def ambilight_led_on(self) -> bool:
        """What the user "sees": only the style (node 200) drives the LEDs (hypothesis H4)."""
        return self.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] != AMBILIGHT_STYLE_OFF

    def trigger_change(self, volume: int | None = None) -> None:
        if volume is not None:
            self.volume = volume
        self._last_change = {"audio/volume": {"current": self.volume, "muted": self.muted}}
        self._change_event.set()

    def _booting(self) -> bool:
        return self.power == "On" and time.monotonic() - self._power_changed_at < self.boot_silence

    def _notify_holds(self, known: str, switches: int) -> bool:
        """Listen kept open: nothing to report to the client (or missed change, see
        `notify_misses_switch`)."""
        return self.online and (
            self.reported_power == known or (self.notify_misses_switch and self._switch_count != switches)
        )

    def _track_rate(self) -> None:
        now = time.monotonic()
        if self.wedge_after is not None and self.requests and now - self.requests[-1][0] < self.wedge_interval:
            self._fast_count += 1
            if self._fast_count >= self.wedge_after:
                self.wedged = True

    # ------------------------------------------------------------------ adaptateur httpx
    def transport(self) -> httpx.MockTransport:
        async def _handler(request: httpx.Request) -> httpx.Response:
            self._track_rate()
            if self.system_https_down and request.url.scheme == "https":
                raise httpx.ConnectError("fake TV: HTTPS port closed", request=request)
            if self.wedged:
                await asyncio.sleep(self.offline_hang)
                raise httpx.ConnectTimeout("fake TV wedged (TLS handshake never completes)", request=request)
            if request.url.path.endswith("/notifychange") and self._booting():
                await asyncio.sleep(3600)  # no answer: the client gives up
            if request.url.path.endswith("/notifychange") and self.notify_immediate:
                known = json.loads(request.content or b"{}").get("notification", {}).get("powerstate", {})
                known = known.get("powerstate") if isinstance(known, dict) else None
                if known is not None and self.online and not self.notify_unavailable:
                    self.notify_pending += 1
                    self.notify_max_pending = max(self.notify_max_pending, self.notify_pending)
                    switches = self._switch_count
                    try:
                        deadline = time.monotonic() + self.notify_hold
                        while time.monotonic() < deadline and self._notify_holds(known, switches):
                            await asyncio.sleep(0.02)
                    finally:
                        self.notify_pending -= 1
                    if self._notify_holds(known, switches):
                        self.requests.append((time.monotonic(), request.method, request.url.path))
                        return httpx.Response(200, json={}, request=request)
            if request.url.path.endswith("/notifychange") and not self.notify_immediate:
                self._change_event.clear()
                try:
                    await asyncio.wait_for(self._change_event.wait(), 30)
                except TimeoutError:
                    pass
            if self.slow_after is not None and len(self.requests) >= self.slow_after:
                await asyncio.sleep(self.slow_delay)
            if not self.online:
                await asyncio.sleep(self.offline_hang)
                raise self.offline_exception("fake TV unreachable", request=request)
            if request.method == "GET" and self.fail_next_get:
                self.fail_next_get = False
                self.requests.append((time.monotonic(), request.method, request.url.path))
                return httpx.Response(503, request=request)
            body = json.loads(request.content) if request.content else None
            status, payload = self.handle(request.method, request.url.path, body)
            if request.url.path.endswith("/input/key"):
                if self.key_delay:
                    await asyncio.sleep(self.key_delay)
                if self.fail_next_key_with_timeout:
                    self.fail_next_key_with_timeout = False
                    raise httpx.ReadTimeout("fake TV slow to answer", request=request)
            if payload is None:
                return httpx.Response(status, request=request)
            return httpx.Response(status, json=payload, request=request)

        return httpx.MockTransport(_handler)

    def key_names(self) -> list[str]:
        return [key for _, key in self.keys]


# ---------------------------------------------------------------------- standalone server
def load_routes_json(path: Path) -> dict[str, Any]:
    """Read a JSON object `{"/path": response}`; reject any other format."""
    routes = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(routes, dict) or not all(isinstance(k, str) and k.startswith("/") for k in routes):
        raise ValueError(f"{path}: JSON object expected, whose keys are paths starting with /")
    return {key.rstrip("/") or "/": value for key, value in routes.items()}


def serve(port: int = 1925, tv: FakeTitanTV | None = None, routes_json: Path | None = None) -> None:
    tv = tv or FakeTitanTV()
    if routes_json is not None:
        tv.get_overrides = load_routes_json(routes_json)
        _LOG.info("Forced GET responses from %s: %s", routes_json, ", ".join(sorted(tv.get_overrides)))

    class _Handler(BaseHTTPRequestHandler):
        def _respond(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            status, payload = tv.handle(self.command, self.path, body)
            data = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = _respond
        do_POST = _respond

        def log_message(self, fmt: str, *args: Any) -> None:
            _LOG.info("%s %s", self.address_string(), fmt % args)

    _LOG.info("Fake Titan TV listening on :%s (PIN %s)", port, DEV_PIN)
    ThreadingHTTPServer(("0.0.0.0", port), _Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Faux serveur JointSpace Titan OS")
    parser.add_argument("--port", type=int, default=1925)
    parser.add_argument("--routes-json", type=Path, help="GET responses forced per path (JSON object)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    serve(args.port, routes_json=args.routes_json)
