from titan_explore.mqtt import TitanMqtt
from titan_explore.steps.s06_keys import KEY_GROUPS, step_keys
from titan_explore.steps.s07_volume import step_volume

from tests.explore.fake_mqtt import FakeTitanBroker


def _answers(per_key="yes"):
    answers = []
    for _, keys in KEY_GROUPS:
        answers.append("")  # context instruction
        answers += [per_key] * len(keys)
    return answers


async def test_each_key_sent_once_with_answer(make_session, fake_tv):
    _, session = make_session(*_answers())
    await step_keys(session)
    expected = [key for _, keys in KEY_GROUPS for key in keys]
    assert fake_tv.key_names() == expected
    assert "Standby" not in fake_tv.key_names() and "Source" not in fake_tv.key_names()
    assert len([f for f in session.report.findings_for(6) if f.status == "works"]) == len(expected)


async def test_other_effect_asks_note(make_session, fake_tv):
    groups = _answers()
    groups[1] = "other"
    groups.insert(2, "opens the guide")
    _, session = make_session(*groups)
    await step_keys(session)
    first_key = KEY_GROUPS[0][1][0]
    finding = next(f for f in session.report.findings_for(6) if f.item == first_key)
    assert finding.status == "info" and finding.note == "opens the guide"


async def test_mqtt_keys_compared_when_available(make_session, fake_tv):
    broker = FakeTitanBroker()
    mqtt = TitanMqtt("192.168.1.42", username="u", password="p", client_factory=broker.factory)
    mqtt.connect()
    from titan_explore.mqtt import RC_CODES

    mqtt_answers = []
    for _, keys in KEY_GROUPS:
        mqtt_answers.append("")
        mqtt_answers += ["yes"] * len([k for k in keys if k in RC_CODES])
    _, session = make_session("y", *_answers(), *mqtt_answers)
    session.context["mqtt"] = mqtt
    await step_keys(session)
    items = {f.item for f in session.report.findings_for(6)}
    first_key = KEY_GROUPS[0][1][0]
    assert first_key in items and f"{first_key} (MQTT)" in items
    assert any(topic == "rc" for topic, _, _ in broker.published)


async def test_volume_range_reported(make_session, fake_tv):
    _, session = make_session("", "y", "y")
    await step_volume(session)
    findings = session.report.findings_for(7)
    assert any("0" in f.value and "60" in f.value for f in findings)
    assert fake_tv.key_names() == ["VolumeUp", "VolumeUp", "VolumeDown", "VolumeDown"]
    assert any(f.item == "Volume keys → amplifier (ARC/CEC)" and f.status == "works" for f in findings)


async def test_mqtt_unknown_codes_not_invented(make_session, fake_tv):
    from titan_explore.mqtt import RC_CODES

    broker = FakeTitanBroker()
    mqtt = TitanMqtt("192.168.1.42", username="u", password="p", client_factory=broker.factory)
    mqtt.connect()
    mqtt_answers = []
    for _, keys in KEY_GROUPS:
        mqtt_answers.append("")
        mqtt_answers += ["yes"] * len([k for k in keys if k in RC_CODES])
    _, session = make_session("y", *_answers(), *mqtt_answers)
    session.context["mqtt"] = mqtt
    await step_keys(session)
    digit = next(f for f in session.report.findings_for(6) if f.item == "Digit1 (MQTT)")
    assert digit.status == "not tested"
