"""The 13 steps chained against the fake JointSpace server and the fake MQTT broker."""

import asyncio
import json
import socket
import threading
import types

import pytest
from titan_explore.steps import STEPS, s08_sources, s11_notify, s12_stability
from titan_explore.steps.s06_keys import KEY_GROUPS

from tests.explore.fake_mqtt import DEV_MQTT_PIN, FakeTitanBroker
from tests.explore.test_sources import HDMI_BOTTOM_UP, LINES
from tests.fake_tv import DEV_PIN


@pytest.fixture
def fast_tv(monkeypatch, fake_tv):
    monkeypatch.setattr(s08_sources, "MIN_MENU_WAIT", 0.0)
    monkeypatch.setattr(s08_sources, "MENU_MARGIN", 0.0)
    monkeypatch.setattr(s08_sources, "MACRO_INTERVAL", 0.01)
    monkeypatch.setattr(s11_notify, "NOTIFY_TIMEOUT", 2.0)
    monkeypatch.setattr(s12_stability, "STABILITY_STEPS", (0.02, 0.01))
    monkeypatch.setattr(s12_stability, "REQUESTS_PER_LEVEL", 3)

    class _Socket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def setsockopt(self, *args):
            pass

        def sendto(self, packet, address):
            threading.Timer(0.3, lambda: setattr(fake_tv, "online", True)).start()

    import intg_philips_titanos.client as client_module

    monkeypatch.setattr(
        client_module,
        "socket",
        types.SimpleNamespace(
            socket=_Socket,
            AF_INET=socket.AF_INET,
            SOCK_DGRAM=socket.SOCK_DGRAM,
            SOL_SOCKET=socket.SOL_SOCKET,
            SO_BROADCAST=socket.SO_BROADCAST,
        ),
    )


def _do(action, answer=""):
    def _run():
        action()
        return answer

    return _run


def _answers(fake_tv, loop):
    a = []
    a += ["run", "ethernet", "y", "y", "y", "y", "y"]  # 1 preparation
    a += ["run", DEV_PIN, "keep", DEV_MQTT_PIN]  # 2 JointSpace + MQTT pairing
    a += ["run", "", _do(lambda: setattr(fake_tv, "power", "Standby")), "n",
          _do(lambda: setattr(fake_tv, "online", False)), ""]  # 3 power + wake-up
    a += ["run"] + [
        _do(lambda level3=level3: setattr(fake_tv, "context", {"level1": "x", "level2": "", "level3": level3}), "done")
        for level3 in ("", "h1", "h2", "h3", "h4")
    ]  # 4 active input
    a += ["run", "", "y", "", "y", "n"]  # 5 CEC
    a += ["run", "n"]  # 6 keys (without MQTT)
    for _, keys in KEY_GROUPS:
        a += [""] + ["yes"] * len(keys)
    a += ["run", "", "y", "y"]  # 7 volume
    a += ["run", *LINES, "", "", "", "y"]  # 8 Sources menu
    for hdmi in HDMI_BOTTOM_UP:
        a += [hdmi, "n"]
    a += ["no"]
    a += ["run", "y", "n", "y", "y", "y", "y", "n"]  # 9 Ambilight
    a += ["run", "YES", "y", "", "y"]  # 10 picture mode
    a += ["run", _do(lambda: loop.call_soon_threadsafe(fake_tv.trigger_change, 30))]  # 11 notifychange
    a += ["run", "y"] + ["yes"] * 7  # 12 Philips app
    a += ["run", "YES"]  # 13 stability
    return a


async def test_full_session_against_fake_tv(make_session, fake_tv, fast_tv, tmp_path):
    loop = asyncio.get_running_loop()
    broker = FakeTitanBroker()
    io, session = make_session(*_answers(fake_tv, loop), paired=False)
    session.context["mqtt_factory"] = broker.factory
    await session.run(STEPS)

    assert io.answers == []  # all the planned answers were consumed
    report = (tmp_path / "report.md").read_text()
    for step in STEPS:
        assert f"### Step {step.number} — {step.title}" in report
    summary = report.split("## Details")[0]
    for hypothesis in ("H1", "H2", "H3", "H4", "H5", "H6"):
        assert f"| {hypothesis} |" in summary
    assert "## Takeaways for the integration" in report
    assert "Steps to configure" in report.split("## Takeaways for the integration")[1]

    journal = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert any(entry["kind"] == "js" for entry in journal)
    assert oct((tmp_path / "credentials.json").stat().st_mode & 0o777) == "0o600"
    assert fake_tv.key_names().count("Confirm") == 1  # only the explicit trial of the OK key (step 6)
