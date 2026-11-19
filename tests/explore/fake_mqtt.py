"""Fake paho-mqtt client (API v2) wired to a fake Titan OS broker, for the tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

DEV_MQTT_PIN = "4321"


class FakeTitanBroker:
    def __init__(self) -> None:
        self.refuse = False
        self.refuse_authenticated = False
        self.challenge = "challenge-xyz"
        self.info = {
            "mqttv_version": "v2.11.3",
            "mqttv_topics": ["rc", "keyboard", "deeplink", "channels/state", "settings", "pairing/start"],
            "model": "FAKE-TV/12",
            "fw_version": "000.000.000.001",
            "eth_mac_addr": "02:00:00:00:00:01",
            "wlan_mac_addr": "02:00:00:00:00:02",
        }
        self.channels_state = {"state": "launcher"}
        self.published: list[tuple[str, dict, object]] = []
        self.issued: dict[str, str] = {}
        self.connections: list[dict] = []

    def factory(self, *args, **kwargs):
        return FakePahoClient(self, kwargs.get("client_id", ""))

    def respond(self, topic: str, payload: dict) -> dict | None:
        if topic == "pairing/start":
            if payload != {"type": "mobile"}:
                return {"error": {"code": 10, "message": "Invalid message format"}}
            return {"data": {"challenge": self.challenge, "timeout": 60, "attempts": 3}}
        if topic == "pairing/finish":
            import hashlib
            import hmac

            expected = hmac.new(DEV_MQTT_PIN.encode(), self.challenge.encode(), hashlib.sha256).hexdigest()
            if payload.get("challenge_result") != expected:
                return {"error": {"code": 3, "message": "Wrong challenge result"}}
            self.issued[payload["username"]] = "secret-password"
            return {"data": {"username": payload["username"], "password": "secret-password"}}
        return None


class FakePahoClient:
    def __init__(self, broker: FakeTitanBroker, client_id: str) -> None:
        self.broker = broker
        self.client_id = client_id
        self.on_connect = None
        self.on_message = None
        self.username = None
        self.password = None
        self.tls = False

    def tls_set_context(self, context) -> None:
        self.tls = True

    def username_pw_set(self, username, password=None) -> None:
        self.username, self.password = username, password

    def connect(self, host, port=1883, keepalive=60) -> None:
        if self.broker.refuse or (self.broker.refuse_authenticated and self.username):
            raise ConnectionRefusedError("port closed")
        self.broker.connections.append({"host": host, "port": port, "user": self.username, "id": self.client_id})

    def loop_start(self) -> None:
        if self.on_connect:
            self.on_connect(self, None, {}, 0, None)

    def loop_stop(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def _deliver(self, topic: str, payload: dict) -> None:
        if self.on_message:
            self.on_message(self, None, SimpleNamespace(topic=topic, payload=json.dumps(payload).encode()))

    def subscribe(self, topic, qos=0):
        if topic == "info":
            self._deliver("info", self.broker.info)
        if topic == "channels/state":
            self._deliver("channels/state", self.broker.channels_state)
        return (0, 1)

    def publish(self, topic, payload=None, qos=0, retain=False, properties=None):
        body = json.loads(payload) if payload else {}
        self.broker.published.append((topic, body, properties))
        response = self.broker.respond(topic, body)
        reply_topic = getattr(properties, "ResponseTopic", None)
        if response is not None and reply_topic:
            self._deliver(reply_topic, response)
        return SimpleNamespace(rc=0)
