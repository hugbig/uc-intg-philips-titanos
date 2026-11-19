import hashlib
import hmac

import pytest
from titan_explore.mqtt import RC_CODES, TitanMqtt, challenge_result
from titan_explore.steps.s02_pairing import step_pairing_mqtt

from tests.explore.fake_mqtt import DEV_MQTT_PIN, FakeTitanBroker


@pytest.fixture
def broker():
    return FakeTitanBroker()


def test_challenge_result_hmac():
    expected = hmac.new(b"1234", b"abc", hashlib.sha256).hexdigest()
    assert challenge_result("1234", "abc") == expected


def test_rc_codes_cover_navigation():
    assert RC_CODES["Confirm"] == 352
    assert RC_CODES["Source"] == 394
    assert RC_CODES["Back"] == 158


def test_request_uses_response_topic(broker):
    mqtt = TitanMqtt("192.168.1.42", client_factory=broker.factory)
    mqtt.connect()
    data = mqtt.request("pairing/start", {"type": "mobile"})
    assert data["challenge"] == "challenge-xyz"
    topic, body, props = broker.published[-1]
    assert topic == "pairing/start"
    assert props.ResponseTopic.startswith("pairing/start/")
    assert broker.connections[-1]["port"] == 8883
    assert broker.connections[-1]["id"].startswith("eos-")


def test_pair_finish_returns_credentials(broker):
    mqtt = TitanMqtt("192.168.1.42", client_factory=broker.factory)
    mqtt.connect()
    mqtt.pair_start()
    username, password = mqtt.pair_finish(DEV_MQTT_PIN)
    assert username and password == "secret-password"


async def test_pairing_flow_saves_mqtt_credentials(make_session, broker):
    _, session = make_session("keep", DEV_MQTT_PIN)
    session.context["mqtt_factory"] = broker.factory
    await step_pairing_mqtt(session)
    assert session.credentials["mqtt"]["password"] == "secret-password"
    assert any(f.hypothesis == "H3" and f.status == "works" for f in session.report.findings_for(2))
    models = " ".join(f.value for f in session.report.findings_for(2))
    assert "FAKE-TV/12" in models


async def test_mac_from_tv_can_replace_typed_one(make_session, broker):
    _, session = make_session("ethernet", DEV_MQTT_PIN)
    session.context["mqtt_factory"] = broker.factory
    await step_pairing_mqtt(session)
    assert session.mac == "02:00:00:00:00:01"


async def test_mqtt_step_skipped_when_port_closed(make_session, broker):
    broker.refuse = True
    _, session = make_session()
    session.context["mqtt_factory"] = broker.factory
    await step_pairing_mqtt(session)
    findings = session.report.findings_for(2)
    assert any(f.hypothesis == "H3" and f.status == "unknown" for f in findings)
    assert "mqtt" not in session.credentials


async def test_mqtt_credentials_reused(make_session, broker):
    _, session = make_session("keep", DEV_MQTT_PIN)
    session.context["mqtt_factory"] = broker.factory
    await step_pairing_mqtt(session)
    session.context.pop("mqtt", None)
    await step_pairing_mqtt(session)  # no scripted answer left: no PIN asked again
    assert broker.connections[-1]["user"] == session.credentials["mqtt"]["username"]


async def test_mqtt_reconnect_failure_does_not_crash(make_session, broker):
    broker.refuse_authenticated = True
    _, session = make_session("keep", DEV_MQTT_PIN)
    session.context["mqtt_factory"] = broker.factory
    await step_pairing_mqtt(session)
    assert "mqtt" not in session.context
    findings = session.report.findings_for(2)
    assert any(f.item == "Authenticated MQTT connection" and f.status == "unknown" for f in findings)


def test_rc_codes_names_exist_in_key_map():
    from intg_philips_titanos.commands import KEY_MAP

    retired = {"PlayPause"}  # ignored by the 65OLED851, removed from the integration (PLAY_PAUSE → Play)
    assert set(RC_CODES) - {"Standby"} <= set(KEY_MAP.values()) | retired


async def test_mqtt_topics_listed_in_report(make_session, broker):
    _, session = make_session("keep", DEV_MQTT_PIN)
    session.context["mqtt_factory"] = broker.factory
    await step_pairing_mqtt(session)
    topics = next(f for f in session.report.findings_for(2) if f.item == "MQTT topics announced by the TV")
    assert "channels/state" in topics.value and "settings" in topics.value
