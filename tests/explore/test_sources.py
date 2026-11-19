import pytest
from titan_explore.steps import s08_sources
from titan_explore.steps.s08_sources import bottom_steps, step_sources

LINES = [
    "Satellite", "Antenna", "Streaming", "Screen mirroring", "USB", "Network", "HDMI 1", "HDMI 2", "HDMI 3", "HDMI 4",
]
HDMI_BOTTOM_UP = ["HDMI 4", "HDMI 3", "HDMI 2", "HDMI 1"]


@pytest.fixture(autouse=True)
def no_menu_wait(monkeypatch):
    monkeypatch.setattr(s08_sources, "MIN_MENU_WAIT", 0.0)
    monkeypatch.setattr(s08_sources, "MENU_MARGIN", 0.0)
    monkeypatch.setattr(s08_sources, "MACRO_INTERVAL", 0.01)


def _intro():
    return [*LINES, "", "", "", "y"]  # lines + end, close the menu, menu displayed, still open


def test_bottom_steps():
    assert bottom_steps(LINES) == {"HDMI 4": 0, "HDMI 3": 1, "HDMI 2": 2, "HDMI 1": 3}


async def test_no_confirm_without_explicit_yes(make_session, fake_tv):
    answers = _intro()
    for hdmi in HDMI_BOTTOM_UP:
        answers += [hdmi, "n"]  # right line highlighted, but we decline to validate
    answers += ["no"]  # no fast trial
    _, session = make_session(*answers)
    await step_sources(session)
    assert "Confirm" not in fake_tv.key_names()


async def test_wrong_highlight_never_validates(make_session, fake_tv):
    answers = _intro()
    for _ in HDMI_BOTTOM_UP:
        answers += ["Screen mirroring"]  # mauvaise ligne : aucune question de validation
    answers += ["no"]
    _, session = make_session(*answers)
    await step_sources(session)
    assert "Confirm" not in fake_tv.key_names()
    findings = [f for f in session.report.findings_for(8) if f.item.startswith("Anchoring from the bottom")]
    assert all(f.status == "unknown" for f in findings)


async def test_validated_input_reported(make_session, fake_tv):
    answers = _intro()
    answers += ["HDMI 4", "y", "y"]  # right line, validate, the TV did switch
    for hdmi in HDMI_BOTTOM_UP[1:]:
        answers += [hdmi, "n"]
    answers += ["no"]
    _, session = make_session(*answers)
    await step_sources(session)
    assert fake_tv.key_names().count("Confirm") == 1
    calibration = next(f for f in session.report.findings_for(8) if f.item == "Steps to configure")
    assert "HDMI 1: 3 from the bottom" in calibration.value and "6 from the top" in calibration.value


async def test_macro_speed_requires_typed_oui(make_session, fake_tv):
    answers = _intro()
    for hdmi in HDMI_BOTTOM_UP:
        answers += [hdmi, "n"]
    answers += ["yes"]  # lowercase: not a valid confirmation
    _, session = make_session(*answers)
    await step_sources(session)
    fast = next(f for f in session.report.findings_for(8) if f.item == "Trial at the macro pace")
    assert fast.status == "not tested"


async def test_macro_speed_restores_interval(make_session, fake_tv):
    answers = _intro()
    for hdmi in HDMI_BOTTOM_UP:
        answers += [hdmi, "n"]
    answers += ["YES", "y", "y", "y", "y"]
    _, session = make_session(*answers)
    session.interval = 0.0
    from titan_explore.steps.common import jointspace

    jointspace(session).interval = 0.05
    await step_sources(session)
    assert jointspace(session).interval == 0.05
    fast = [f for f in session.report.findings_for(8) if f.item.startswith("Macro pace")]
    assert len(fast) == 4 and all(f.status == "works" for f in fast)
    assert "Confirm" not in fake_tv.key_names()
