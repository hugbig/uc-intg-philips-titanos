"""Step 5: HDMI-CEC — does the TV turn on / switch by itself when a device turns on?"""

from __future__ import annotations

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import describe, observe

STEP = 5


def _status(answer: bool) -> str:
    return "works" if answer else "ignored"


async def step_cec(session: Session) -> None:
    console, report = session.console, session.report

    console.pause(
        "Scenario 1: TV on, on a DIFFERENT input than the console. Turn the console or the Streamer off, "
        "then turn it back on now."
    )
    switched = console.ask_yes_no("Did the TV switch to its input by itself?")
    report.add(Finding(STEP, "CEC: automatic switch (TV on)", _status(switched)))

    console.pause(
        "Scenario 2: put the TV in standby with the Philips remote, then turn on the console or the Streamer."
    )
    woke = console.ask_yes_no("Did the TV turn on by itself?")
    report.add(Finding(STEP, "CEC: automatic TV power-on", _status(woke)))
    switched = console.ask_yes_no("Did it land on the right input?")
    report.add(Finding(STEP, "CEC: right input after power-on", _status(switched)))

    snapshot = await observe(session)
    report.add(Finding(STEP, "Snapshot after CEC power-on", "info", value=describe(snapshot)))
