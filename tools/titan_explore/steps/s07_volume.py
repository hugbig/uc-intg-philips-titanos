"""Step 7: volume with the amplifier over ARC — what is audio/volume worth, and do the keys drive the amplifier?"""

from __future__ import annotations

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import jointspace

STEP = 7


async def _volume(session: Session) -> dict:
    response = await jointspace(session).get("audio/volume")
    return response.data if response.ok and isinstance(response.data, dict) else {}


async def step_volume(session: Session) -> None:
    js, console, report = jointspace(session), session.console, session.report
    before = await _volume(session)
    report.add(
        Finding(
            STEP,
            "audio/volume",
            "info",
            value=f"min {before.get('min', '?')} — max {before.get('max', '?')} — current {before.get('current', '?')}",
            note=f"muted={before.get('muted', '?')}",
        )
    )
    console.pause("Play audible sound (video or channel), at the amplifier's usual volume.")
    for _ in range(2):
        await js.key("VolumeUp")
    up = console.ask_yes_no("I sent 2 × Volume +: did the AMPLIFIER volume go up?")
    middle = await _volume(session)
    for _ in range(2):
        await js.key("VolumeDown")
    down = console.ask_yes_no("I sent 2 × Volume −: did it go back down?")
    after = await _volume(session)
    report.add(Finding(STEP, "Volume keys → amplifier (ARC/CEC)", "works" if up and down else "ignored"))
    report.add(
        Finding(
            STEP,
            "audio/volume value during the test",
            "info",
            value=f"{before.get('current', '?')} → {middle.get('current', '?')} → {after.get('current', '?')}",
            note="if the amplifier moves but this value does not, it does not reflect the real volume",
        )
    )
