import pytest
from titan_explore.session import Step
from titan_explore.steps import s10_picture
from titan_explore.steps.s09_ambilight import step_ambilight
from titan_explore.steps.s10_picture import step_picture

from tests.fake_tv import AMBILIGHT_STYLE_NODE, AMBILIGHT_VIDEO_NODE, PICTURE_STYLE_NODE

# Answers about the LEDs, in the order of the step 9 questions (fake server: only node 200 counts):
# on; power Off alone has no effect; 210 alone turns off; like the app turns off; then back on;
# video variant changed; AmbilightOnOff key has no effect.
AMBILIGHT_ANSWERS = ["y", "n", "y", "y", "y", "y", "n"]


def _finding(session, step, text):
    return next(f for f in session.report.findings_for(step) if text in f.item)


async def test_ambilight_verdicts(make_session, fake_tv):
    _, session = make_session(*AMBILIGHT_ANSWERS)
    await step_ambilight(session)
    assert _finding(session, 9, "ambilight/power Off alone").status == "ignored"
    assert _finding(session, 9, "Style 210").status == "works"
    assert _finding(session, 9, "Turn-off like the app").status == "works"
    assert _finding(session, 9, "Turn-on like the app").status == "works"
    assert _finding(session, 9, "Video variant").status == "works"
    assert _finding(session, 9, "AmbilightOnOff").status == "ignored"


async def test_ambilight_updates_use_app_format(make_session, fake_tv):
    _, session = make_session(*AMBILIGHT_ANSWERS)
    await step_ambilight(session)
    style = next(v for v in fake_tv.settings_updates if v["Nodeid"] == AMBILIGHT_STYLE_NODE)
    assert style["string_id"] == "MAIN_AMBILIGHT_STYLE"
    assert style["Controllable"] is True and style["Available"] is True
    variant = next(v for v in fake_tv.settings_updates if v["Nodeid"] == AMBILIGHT_VIDEO_NODE)
    assert variant["string_id"] == "MAIN_FOLLOW_VIDEO"
    assert "selected_item" in variant["data"]


async def test_ambilight_turned_on_like_app_when_initially_off(make_session, fake_tv):
    fake_tv.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] = 210
    fake_tv.ambilight["power"] = "Off"

    def _check_turned_on_then_answer():
        # Right after turning on, like the app: power On then style 220.
        assert fake_tv.ambilight["power"] == "On"
        assert fake_tv.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] == 220
        assert fake_tv.settings_updates[-1]["data"] == {"activenode_id": 220}
        return "y"

    _, session = make_session("n", _check_turned_on_then_answer, *AMBILIGHT_ANSWERS[1:])
    await step_ambilight(session)
    assert _finding(session, 9, "Style 210").status == "works"


async def test_ambilight_restored_at_end_of_step(make_session, fake_tv):
    fake_tv.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] = 230
    fake_tv.menu_nodes[AMBILIGHT_VIDEO_NODE]["selected_item"] = 225
    fake_tv.ambilight["power"] = "Off"  # the step ends with power On: only the restore brings Off back
    _, session = make_session("run", "y", "n", "y", "y", "y", "n")  # audio style: no video variant
    await session.run([Step(9, "Ambilight", step_ambilight)])
    assert fake_tv.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] == 230
    assert fake_tv.menu_nodes[AMBILIGHT_VIDEO_NODE]["selected_item"] == 225
    assert fake_tv.ambilight["power"] == "Off"
    assert _finding(session, 9, "Video variant").status == "not tested"


async def test_ambilight_restored_after_interrupt(make_session, fake_tv):
    fake_tv.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] = 230

    def _interrupt():
        raise KeyboardInterrupt

    _, session = make_session("run", "y", "n", _interrupt)  # Ctrl+C after switching to 210
    await session.run([Step(9, "Ambilight", step_ambilight)])
    assert fake_tv.menu_nodes[AMBILIGHT_STYLE_NODE]["activenode_id"] == 230
    assert "interrupted" in (session.out_dir / "report.md").read_text()


async def test_structure_read_requires_typed_oui(make_session, fake_tv):
    _, session = make_session("yes", "", "y")
    await step_picture(session)
    assert fake_tv.structure_requests == 0
    assert _finding(session, 10, "Picture mode node").status == "not tested"


async def test_picture_node_found_in_structure(make_session, fake_tv):
    _, session = make_session("YES", "y", "", "y")
    await step_picture(session)
    assert fake_tv.structure_requests == 1
    assert str(PICTURE_STYLE_NODE) in _finding(session, 10, "Picture mode node").value


async def test_picture_mode_restored(make_session, fake_tv):
    initial = fake_tv.menu_nodes[PICTURE_STYLE_NODE]["activenode_id"]
    _, session = make_session("run", "YES", "y", "", "y")
    await session.run([Step(10, "Mode image", step_picture)])
    assert fake_tv.structure_requests == 1
    assert fake_tv.menu_nodes[PICTURE_STYLE_NODE]["activenode_id"] == initial
    assert _finding(session, 10, "Picture mode change").status == "works"
    assert _finding(session, 10, "Picture mode remembered per input").status == "works"


async def test_picture_absent_like_real_tv(make_session, fake_tv):
    """The real 65OLED851 only exposes Ambilight in the settings tree."""
    del fake_tv.menu_nodes[PICTURE_STYLE_NODE]
    _, session = make_session("YES", "", "y")
    await step_picture(session)
    assert _finding(session, 10, "Picture mode node").status == "unknown"


@pytest.mark.parametrize("label", ["MAIN_PICTURE_STYLE", "picture_mode", "org.droidtv.PICTURE_STYLE"])
def test_picture_node_detection(label):
    tree = {"node": {"node_id": 1, "string_id": "Settings", "data": {"nodes": [
        {"node_id": 5, "string_id": "MLM_PHM_KEY_MAIN_AMBILIGHT_STYLE", "data": {}},
        {"node_id": 42, "string_id": label, "data": {"nodes": [{"node_id": 43, "string_id": "Vivid"}]}},
    ]}}}
    found = s10_picture.find_picture_node(tree)
    assert found is not None and found["node_id"] == 42


async def test_refused_restore_is_reported(make_session, fake_tv):
    def _refuse_then_answer():
        fake_tv.refuse_settings_update = True
        return "y"

    _, session = make_session("run", "YES", "y", "", _refuse_then_answer)
    await session.run([Step(10, "Mode image", step_picture)])
    assert any("set it back by hand" in notice for notice in session.report.notices)
