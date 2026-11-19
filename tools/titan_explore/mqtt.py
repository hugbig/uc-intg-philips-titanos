"""Client for the MQTT broker built into Titan OS TVs (port 8883), used by the official mobile app.

Protocol taken from https://github.com/bedirhanyildirim/philips-titan-os-55pml9019-remote
(docs/TITAN_OS_API.md, philipstv/titan.py), Copyright (c) 2026 Bedirhan Yıldırım, MIT license.
Not documented by Philips/Titan: best-effort use for exploration.

- MQTT v5 over TLS, certificate verified against the "Titanos Root CA" root (titan_ca.crt);
  only the hostname check is disabled (connection by IP address).
- Request/response: publish with ResponseTopic/CorrelationData = `<topic>/<uuid>`.
- Pairing: `pairing/start {"type": "mobile"}` → challenge; PIN displayed on the TV;
  `pairing/finish {"username", "challenge_result": HMAC-SHA256(key=PIN, message=challenge)}`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import paho.mqtt.client as paho
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

CA_FILE = Path(__file__).with_name("titan_ca.crt")
PORT = 8883

# Linux key codes expected by the `rc` topic, indexed by the JointSpace names from KEY_MAP.
RC_CODES: dict[str, int] = {
    "Confirm": 352,
    "Back": 158,
    "Home": 102,
    "CursorUp": 103,
    "CursorDown": 108,
    "CursorLeft": 105,
    "CursorRight": 106,
    "VolumeUp": 115,
    "VolumeDown": 114,
    "Mute": 113,
    "Standby": 116,
    "Play": 207,
    "Pause": 119,
    "PlayPause": 164,
    "Stop": 128,
    "Options": 357,
    "Source": 394,
    "ChannelStepUp": 402,
    "ChannelStepDown": 403,
    "RedColour": 398,
    "GreenColour": 399,
    "YellowColour": 400,
    "BlueColour": 401,
    "WatchTV": 377,
    "Next": 163,
    "Previous": 165,
    "FastForward": 208,
    "Rewind": 168,
    "Info": 358,
}


class TitanMqttError(Exception):
    pass


def challenge_result(pin: str, challenge: str) -> str:
    return hmac.new(pin.encode(), challenge.encode(), hashlib.sha256).hexdigest()


def _default_factory(client_id: str) -> Any:
    return paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=paho.MQTTv5)


class TitanMqtt:
    def __init__(
        self,
        host: str,
        *,
        username: str | None = None,
        password: str | None = None,
        client_factory: Callable[..., Any] | None = None,
        ca_file: Path = CA_FILE,
        port: int = PORT,
    ) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self._factory = client_factory
        self._ca_file = ca_file
        self._client: Any = None
        self._connected = threading.Event()
        self._waiters: dict[str, tuple[threading.Event, list[dict]]] = {}
        self._challenge: str | None = None

    # ------------------------------------------------------------------ connection
    def connect(self, timeout: float = 8.0) -> None:
        client_id = f"eos-{self.username}" if self.username else f"eos-{uuid.uuid4().hex}"
        if self._factory is not None:
            client = self._factory(paho.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=paho.MQTTv5)
        else:
            client = _default_factory(client_id)
        context = ssl.create_default_context(cafile=str(self._ca_file))
        context.check_hostname = False  # connecting by IP; the certificate chain is still verified
        client.tls_set_context(context)
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self._client = client
        client.connect(self.host, self.port, keepalive=30)
        client.loop_start()
        if not self._connected.wait(timeout):
            self.disconnect()
            raise TitanMqttError("MQTT connection: timed out")

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
                self._client.loop_stop()
            finally:
                self._client = None
                self._connected.clear()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        # paho v2: ReasonCode (is_failure); the tests' fake client passes 0.
        if not getattr(reason_code, "is_failure", bool(reason_code)):
            self._connected.set()

    def _on_message(self, client, userdata, message) -> None:
        waiter = self._waiters.get(message.topic)
        if waiter is None:
            return
        event, box = waiter
        try:
            box.append(json.loads(message.payload))
        except (ValueError, TypeError):
            box.append({"raw": message.payload.decode(errors="replace")})
        event.set()

    # ------------------------------------------------------------------ exchanges
    def _wait(self, topic: str, timeout: float, action: Callable[[], None]) -> dict | None:
        event, box = threading.Event(), []
        self._waiters[topic] = (event, box)
        try:
            self._client.subscribe(topic, qos=0)
            action()
            event.wait(timeout)
            return box[0] if box else None
        finally:
            self._waiters.pop(topic, None)

    def request(self, topic: str, payload: dict, timeout: float = 6.0) -> dict:
        reply_topic = f"{topic}/{uuid.uuid4()}"
        properties = Properties(PacketTypes.PUBLISH)
        properties.ResponseTopic = reply_topic
        properties.CorrelationData = reply_topic.encode()

        def _publish() -> None:
            time.sleep(0.3)  # let the SUBACK arrive before publishing
            self._client.publish(topic, json.dumps(payload), qos=0, properties=properties)

        response = self._wait(reply_topic, timeout, _publish)
        if response is None:
            raise TitanMqttError(f"{topic}: no response")
        if "error" in response:
            raise TitanMqttError(f"{topic}: {response['error']}")
        return response.get("data", response)

    def wait_retained(self, topic: str, timeout: float = 3.0) -> dict | None:
        return self._wait(topic, timeout, lambda: None)

    def pair_start(self) -> dict:
        data = self.request("pairing/start", {"type": "mobile"})
        self._challenge = str(data["challenge"])
        return data

    def pair_finish(self, pin: str) -> tuple[str, str]:
        if self._challenge is None:
            raise TitanMqttError("pair_start must come before pair_finish")
        username = str(uuid.uuid4())
        data = self.request(
            "pairing/finish", {"username": username, "challenge_result": challenge_result(pin, self._challenge)}
        )
        return str(data.get("username", username)), str(data["password"])

    def rc(self, key_code: int) -> None:
        self._client.publish("rc", json.dumps({"key_code": key_code}), qos=0)
