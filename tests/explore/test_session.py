import json

import pytest
from titan_explore.record import Finding
from titan_explore.session import Session, Step, TvUnreachable, TvWedged


def test_invalid_answer_is_asked_again(scripted):
    io, console = scripted("maybe", "y")
    assert console.ask_yes_no("Continue?") is True
    assert len(io.prompts) == 2


def test_confirm_typed_requires_exact_word(scripted):
    _, console = scripted("yes")
    assert console.confirm_typed("Type YES") is False
    _, console = scripted("YES")
    assert console.confirm_typed("Type YES") is True


async def test_skip_step_records_not_tested(tmp_path, scripted):
    called = []

    async def run(session):
        called.append(1)

    _, console = scripted("skip")
    session = Session(tmp_path, console)
    await session.run([Step(1, "Preparation", run)])
    assert called == []
    assert [f.status for f in session.report.findings_for(1)] == ["not tested"]


async def test_step_continues_when_tv_drops(tmp_path, scripted):
    ran = []

    async def first(session):
        raise TvUnreachable("TV injoignable")

    async def second(session):
        ran.append(2)

    _, console = scripted("run", "run")
    session = Session(tmp_path, console)
    await session.run([Step(1, "A", first), Step(2, "B", second)])
    assert ran == [2]
    assert [f.status for f in session.report.findings_for(1)] == ["unknown"]


async def test_ctrl_c_restores_and_writes_partial_report(tmp_path, scripted):
    undone = []

    async def risky(session):
        async def undo():
            undone.append("ambilight")

        session.restore.push("Ambilight", undo)
        session.report.add(Finding(1, "avant interruption", "works"))
        raise KeyboardInterrupt

    _, console = scripted("run")
    session = Session(tmp_path, console)
    await session.run([Step(1, "Ambilight", risky)])
    assert undone == ["ambilight"]
    report = (tmp_path / "report.md").read_text()
    assert "avant interruption" in report


async def test_wedge_stops_session_with_instructions(tmp_path, scripted):
    ran = []

    async def wedge(session):
        raise TvWedged("TLS no longer responds")

    async def after(session):
        ran.append(1)

    io, console = scripted("run")
    session = Session(tmp_path, console)
    await session.run([Step(1, "A", wedge), Step(2, "B", after)])
    assert ran == []
    assert "unplug" in "\n".join(io.output).lower()
    assert "unplug" in (tmp_path / "report.md").read_text().lower()


async def test_resume_from_step(tmp_path, scripted):
    async def first(session):
        session.report.add(Finding(1, "result 1", "works"))

    async def second(session):
        session.report.add(Finding(2, "result 2", "works"))

    _, console = scripted("run", "run")
    await Session(tmp_path, console).run([Step(1, "A", first), Step(2, "B", second)])

    _, console = scripted("run")
    session = Session(tmp_path, console)
    await session.run([Step(1, "A", first), Step(2, "B", second)], start_from=2)
    report = (tmp_path / "report.md").read_text()
    assert "result 1" in report and "result 2" in report
    assert len(session.report.findings_for(2)) == 1  # rerun: no duplicate


async def test_report_groups_hypotheses(tmp_path, scripted):
    async def run(session):
        session.report.add(Finding(3, "powerstate en veille", "lies", hypothesis="H1"))
        session.report.add(Finding(9, "ambilight/power", "ignored", hypothesis="H4"))

    _, console = scripted("run")
    await Session(tmp_path, console).run([Step(1, "A", run)])
    report = (tmp_path / "report.md").read_text()
    summary = report.split("## Details")[0]
    assert "H1" in summary and "lies" in summary
    assert "H4" in summary and "ignored" in summary
    state = json.loads((tmp_path / "state.json").read_text())
    assert len(state["findings"]) == 2


async def test_credentials_saved_private(tmp_path, scripted):
    _, console = scripted()
    session = Session(tmp_path, console)
    session.credentials["jointspace"] = {"username": "u", "password": "p"}
    session.save_credentials()
    path = tmp_path / "credentials.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert Session(tmp_path, console).credentials["jointspace"]["username"] == "u"


@pytest.mark.parametrize("answer", ["1", "run"])
def test_choice_by_number_or_text(scripted, answer):
    _, console = scripted(answer)
    assert console.ask_choice("What to do?", ["run", "skip"]) == "run"


async def test_unexpected_error_restores_and_continues(tmp_path, scripted):
    undone, ran = [], []

    async def broken(session):
        async def undo():
            undone.append(1)

        session.restore.push("setting", undo)
        raise ValueError("unexpected response")

    async def after(session):
        ran.append(1)

    _, console = scripted("run", "run")
    session = Session(tmp_path, console)
    await session.run([Step(1, "A", broken), Step(2, "B", after)])
    assert undone == [1] and ran == [1]
    finding = session.report.findings_for(1)[0]
    assert finding.status == "unknown" and "ValueError" in finding.note
    assert (tmp_path / "report.md").exists()


async def test_interrupt_with_pending_cancel_still_restores(tmp_path, scripted):
    """Second Ctrl+C under asyncio.run: KeyboardInterrupt while a cancellation is pending."""
    import asyncio

    undone = []

    async def interrupted(session):
        async def undo():
            await asyncio.sleep(0)
            undone.append(1)

        session.restore.push("setting", undo)
        asyncio.current_task().cancel()
        raise KeyboardInterrupt

    _, console = scripted("run")
    session = Session(tmp_path, console)
    await session.run([Step(1, "A", interrupted)])
    assert undone == [1]
    assert (tmp_path / "report.md").exists()


async def test_skipping_on_resume_keeps_previous_results(tmp_path, scripted):
    async def first(session):
        session.report.add(Finding(1, "result 1", "works"))

    _, console = scripted("run")
    await Session(tmp_path, console).run([Step(1, "A", first)])
    _, console = scripted("skip")
    session = Session(tmp_path, console)
    await session.run([Step(1, "A", first)])
    assert [f.item for f in session.report.findings_for(1)] == ["result 1"]


async def test_notices_survive_resume(tmp_path, scripted):
    _, console = scripted()
    session = Session(tmp_path, console)
    session.report.notices.append("Unplug the TV for 30 s.")
    session.report.save_state()
    reloaded = Session(tmp_path, console)
    reloaded.report.notices.append("Unplug the TV for 30 s.")
    reloaded.report.save_state()
    assert Session(tmp_path, console).report.notices == ["Unplug the TV for 30 s."]


def test_sigint_handler_raises_keyboard_interrupt():
    import signal

    from titan_explore.__main__ import install_sigint_handler

    previous = signal.getsignal(signal.SIGINT)
    try:
        install_sigint_handler()
        handler = signal.getsignal(signal.SIGINT)
        assert handler is not signal.default_int_handler  # so asyncio.run does not install its own
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGINT, None)
    finally:
        signal.signal(signal.SIGINT, previous)


def test_console_has_no_unused_ask_int(scripted):
    _, console = scripted()
    assert not hasattr(console, "ask_int")
