import socket
import threading
import types

import pytest
from titan_explore.steps.s03_power import step_power
from titan_explore.steps.s04_input import step_active_input
from titan_explore.steps.s05_cec import step_cec


def _act(action, answer=""):
    def _run():
        action()
        return answer

    return _run


@pytest.fixture
def wol_wakes_tv(monkeypatch, fake_tv):
    """The wake packet turns the fake TV back on 0.5 s later."""

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
            def _wake():
                fake_tv.online, fake_tv.power = True, "On"

            threading.Timer(0.5, _wake).start()

    import intg_philips_titanos.client as client_module

    fake_socket_module = types.SimpleNamespace(
        socket=_Socket,
        AF_INET=socket.AF_INET,
        SOCK_DGRAM=socket.SOCK_DGRAM,
        SOL_SOCKET=socket.SOL_SOCKET,
        SO_BROADCAST=socket.SO_BROADCAST,
    )
    monkeypatch.setattr(client_module, "socket", fake_socket_module)  # not the global module: asyncio needs it


def _standby(fake_tv):
    return _act(lambda: setattr(fake_tv, "power", "Standby"))


def _deep_off(fake_tv):
    return _act(lambda: setattr(fake_tv, "online", False))


async def test_powerstate_lie_detected(make_session, fake_tv):
    fake_tv.powerstate_lies = True
    _, session = make_session("", _standby(fake_tv), "n", _deep_off(fake_tv), mac="")
    await step_power(session)
    h1 = [f for f in session.report.findings_for(3) if f.hypothesis == "H1"]
    assert h1 and h1[0].status == "lies"


async def test_powerstate_truthful(make_session, fake_tv):
    _, session = make_session("", _standby(fake_tv), "n", _deep_off(fake_tv), mac="")
    await step_power(session)
    h1 = [f for f in session.report.findings_for(3) if f.hypothesis == "H1"]
    assert h1[0].status == "works"


async def test_api_wake_answer_recorded(make_session, fake_tv):
    _, session = make_session("", _standby(fake_tv), "y", _deep_off(fake_tv), mac="")
    await step_power(session)
    api = [f for f in session.report.findings_for(3) if "POST powerstate" in f.item]
    assert api[0].status == "works"
    assert any(r[1] == "POST" and r[2].endswith("/powerstate") for r in fake_tv.requests)


async def test_wol_delay_measured(make_session, fake_tv, wol_wakes_tv):
    _, session = make_session("", _standby(fake_tv), "n", _deep_off(fake_tv), "")
    await step_power(session)
    wol = [f for f in session.report.findings_for(3) if f.item == "Network wake (API reachable)"]
    assert wol and wol[0].status == "works"
    delay = float(wol[0].value.split()[0].replace(",", "."))
    assert 0.3 <= delay <= 3.0


async def test_wol_not_tested_without_mac(make_session, fake_tv):
    _, session = make_session("", _standby(fake_tv), "n", _deep_off(fake_tv), mac="")
    await step_power(session)
    assert any(f.status == "not tested" and "Network wake" in f.item for f in session.report.findings_for(3))


def _source(fake_tv, level3):
    def _set():
        fake_tv.context = {"level1": "WatchExtension" if level3 else "NetTv", "level2": "", "level3": level3}

    return _act(_set, "done")


async def test_active_input_distinguishes_hdmi(make_session, fake_tv):
    answers = [_source(fake_tv, "")] + [_source(fake_tv, f"hdmi{n}") for n in range(1, 5)]
    _, session = make_session(*answers)
    await step_active_input(session)
    verdict = [f for f in session.report.findings_for(4) if f.item == "Distinguish HDMI inputs"]
    assert verdict[0].value.startswith("yes")


async def test_active_input_cannot_distinguish(make_session, fake_tv):
    answers = [_source(fake_tv, "")] + [_source(fake_tv, "same") for _ in range(4)]
    _, session = make_session(*answers)
    await step_active_input(session)
    verdict = [f for f in session.report.findings_for(4) if f.item == "Distinguish HDMI inputs"]
    assert verdict[0].value.startswith("no")


async def test_cec_answers_recorded(make_session, fake_tv):
    _, session = make_session("", "y", "", "y", "n")
    await step_cec(session)
    findings = session.report.findings_for(5)
    assert len(findings) >= 3
    assert any(f.status == "works" for f in findings) and any(f.status == "ignored" for f in findings)


async def test_wol_not_tested_when_tv_still_answers(make_session, fake_tv, wol_wakes_tv):
    # the TV stays reachable despite the power-off instruction, then despite the reminder
    _, session = make_session("", _standby(fake_tv), "n", "", "")
    await step_power(session)
    wol = [f for f in session.report.findings_for(3) if "Network wake" in f.item]
    assert wol and wol[0].status == "not tested"
    assert not any("API joignable" in f.item and f.status == "works" for f in session.report.findings_for(3))
