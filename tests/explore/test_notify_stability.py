import asyncio

import pytest
from titan_explore.steps import s12_stability
from titan_explore.steps.s11_notify import step_notify
from titan_explore.steps.s12_stability import step_stability


def _finding(session, step, text):
    return next(f for f in session.report.findings_for(step) if text in f.item)


async def test_notifychange_event_recorded(make_session, fake_tv):
    loop = asyncio.get_running_loop()

    def _change_volume():  # called from the console thread: the user changes the volume
        loop.call_soon_threadsafe(fake_tv.trigger_change, 25)
        return ""

    _, session = make_session(_change_volume)
    await step_notify(session)
    finding = _finding(session, 11, "notifychange")
    assert finding.status == "works" and "25" in finding.value


async def test_notifychange_silence_is_not_a_wedge(make_session, fake_tv, monkeypatch):
    from titan_explore.steps import s11_notify

    monkeypatch.setattr(s11_notify, "NOTIFY_TIMEOUT", 0.3)
    _, session = make_session("")
    await step_notify(session)  # must not raise TvWedged
    assert _finding(session, 11, "notifychange").status == "ignored"


async def test_stability_requires_typed_oui(make_session, fake_tv):
    _, session = make_session("yes")
    await step_stability(session)
    assert fake_tv.requests == []
    assert _finding(session, 13, "Safe interval").status == "not tested"


@pytest.fixture
def fast_levels(monkeypatch):
    monkeypatch.setattr(s12_stability, "STABILITY_STEPS", (0.08, 0.04, 0.02, 0.01, 0.005))
    monkeypatch.setattr(s12_stability, "REQUESTS_PER_LEVEL", 4)


async def test_stability_stops_at_first_degraded_level(make_session, fake_tv, fast_levels):
    fake_tv.wedge_after = 2
    fake_tv.wedge_interval = 0.015  # freezes as soon as requests are spaced less than 15 ms apart
    _, session = make_session("YES")
    await step_stability(session)
    safe = _finding(session, 13, "Safe interval")
    assert safe.status == "info" and "0.02" in safe.value and "0.01" in safe.value
    levels = [f.item for f in session.report.findings_for(13) if f.item.startswith("Palier")]
    assert not any("0.005" in item for item in levels)
    assert any("unplug" in notice.lower() for notice in session.report.notices)


async def test_stability_all_levels_ok(make_session, fake_tv, fast_levels):
    _, session = make_session("YES")
    await step_stability(session)
    assert "no degradation" in _finding(session, 13, "Safe interval").value


async def test_stability_detects_slow_responses(make_session, fake_tv, fast_levels):
    fake_tv.slow_after = 6  # from the 7th request on, each response takes 0.6 s
    fake_tv.slow_delay = 0.6
    _, session = make_session("YES")
    await step_stability(session)
    assert "slow response" in _finding(session, 13, "Safe interval").value
