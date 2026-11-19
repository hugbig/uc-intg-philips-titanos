"""Step 6: each key of the integration, sent once, effect confirmed by the user.

Excluded here: Standby (power, step 3), Source (step 8), AmbilightOnOff (step 9),
VolumeUp/VolumeDown (step 7). Only one digit is tested, as a stand-in for the numeric keypad.
"""

from __future__ import annotations

import asyncio

from intg_philips_titanos.commands import KEY_MAP
from titan_explore.mqtt import RC_CODES
from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import jointspace

STEP = 6

KEY_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Go to the Titan OS home screen.",
        ["CursorUp", "CursorDown", "CursorLeft", "CursorRight", "Confirm", "Back", "Home", "Options", "Info"],
    ),
    (
        "Tune to a TV channel or an HDMI input with a picture.",
        ["ChannelStepUp", "ChannelStepDown", "WatchTV", "Digit1", "RedColour", "GreenColour", "YellowColour",
         "BlueColour", "Mute"],
    ),
    (
        "Start playing a video (YouTube or another app).",
        ["Pause", "Play", "PlayPause", "Stop", "FastForward", "Rewind", "Next", "Previous", "Record"],
    ),
]

_STATUS = {"yes": "works", "no": "ignored", "other": "info"}

# PlayPause: tested on 2026-11-18, ignored by the 65OLED851, removed from the integration (PLAY_PAUSE → Play).
_RETIRED_KEYS = {"PlayPause"}
assert {key for _, keys in KEY_GROUPS for key in keys} <= set(KEY_MAP.values()) | _RETIRED_KEYS
assert set(RC_CODES) - {"Standby"} <= set(KEY_MAP.values()) | _RETIRED_KEYS, "RC_CODES name missing from KEY_MAP"


async def _ask_effect(session: Session, item: str) -> None:
    answer = session.console.ask_choice(f"  {item}: observed effect?", ["yes", "no", "other"])
    note = session.console.ask_text("  What did you observe?") if answer == "other" else ""
    session.report.add(Finding(STEP, item, _STATUS[answer], note=note))


async def step_keys(session: Session) -> None:
    js = jointspace(session)
    mqtt = session.context.get("mqtt")
    use_mqtt = mqtt is not None and session.console.ask_yes_no(
        "Also test each key via MQTT (twice as many questions)?"
    )
    for instruction, keys in KEY_GROUPS:
        session.console.pause(instruction)
        for key in keys:
            await js.key(key)
            await _ask_effect(session, key)
    if not use_mqtt:
        return
    session.console.say("Same keys, this time sent via MQTT.")
    for instruction, keys in KEY_GROUPS:
        session.console.pause(instruction)
        for key in keys:
            if key not in RC_CODES:  # code not documented by the community source: do not invent one
                session.report.add(Finding(STEP, f"{key} (MQTT)", "not tested", note="unknown rc code"))
                continue
            await asyncio.to_thread(mqtt.rc, RC_CODES[key])
            session.journal.log("mqtt", topic="rc", key=key, code=RC_CODES[key])
            await asyncio.sleep(session.interval)
            await _ask_effect(session, f"{key} (MQTT)")
