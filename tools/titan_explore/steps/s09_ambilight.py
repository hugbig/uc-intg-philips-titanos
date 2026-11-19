"""Step 9: Ambilight (H4) — which message really drives the LEDs? Original state restored.

Settings seen in the Philips Smart TV app traffic (65OLED851, 2026-11-18):
node 200 = style (210 off, 220 video, 230 audio, 240 color, 260 app); node 220 = video variant
(list node, selected_item 221 to 225). The app turns off with `ambilight/power` Off + style 210,
and turns on with `ambilight/power` On + style 220. Each means is tried alone to find which one suffices.
"""

from __future__ import annotations

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import RestoreFailed, jointspace, read_node, set_node, update_node

STEP = 9
STYLE_NODE = 200
STYLE_STRING = "MAIN_AMBILIGHT_STYLE"
STYLE_OFF = 210
STYLE_FOLLOW_VIDEO = 220
KNOWN_STYLES = {
    210: "Off",
    220: "Follow video",
    230: "Follow audio",
    240: "Fixed color",
    260: "Follow app",
}
VIDEO_NODE = 220
VIDEO_STRING = "MAIN_FOLLOW_VIDEO"
VIDEO_VARIANTS = {221: "AI", 222: "Standard", 223: "Natural", 224: "Cinema", 225: "Game"}


async def step_ambilight(session: Session) -> None:
    js, console, report = jointspace(session), session.console, session.report

    initial_style = await read_node(session, STYLE_NODE)
    initial_variant = await read_node(session, VIDEO_NODE, "selected_item")
    power = await js.get("ambilight/power")
    initial_power = power.data.get("power") if power.ok and isinstance(power.data, dict) else None
    report.add(
        Finding(
            STEP,
            "Initial state",
            "info",
            value=f"node 200 = {initial_style} ({KNOWN_STYLES.get(initial_style or 0, '?')})",
            note=f"video variant (node 220) = {initial_variant}; ambilight/power = {initial_power}",
        )
    )
    if initial_style is None:
        report.add(Finding(STEP, "Style via node 200", "unknown", note="node 200 unreadable", hypothesis="H4"))
        return

    async def _restore() -> None:
        failures = []
        if initial_power is not None and not (await js.post("ambilight/power", {"power": initial_power})).ok:
            failures.append("ambilight/power")
        if not await set_node(session, STYLE_NODE, initial_style, STYLE_STRING):
            failures.append("node 200")
        if initial_variant is not None and not await update_node(
            session, VIDEO_NODE, {"selected_item": initial_variant}, VIDEO_STRING
        ):
            failures.append("node 220")
        if failures:
            raise RestoreFailed(", ".join(failures))

    session.restore.push("Ambilight (on/off, style and video variant)", _restore)

    on_style = initial_style if initial_style != STYLE_OFF else STYLE_FOLLOW_VIDEO

    async def _turn_on() -> None:
        """Like the app: power On, then the on style."""
        await js.post("ambilight/power", {"power": "On"})
        await set_node(session, STYLE_NODE, on_style, STYLE_STRING)

    async def _try(item: str, question: str, *, expect_off: bool = True) -> bool:
        worked = console.ask_yes_no(question)
        report.add(Finding(STEP, item, "works" if worked else "ignored", hypothesis="H4"))
        if expect_off:
            await _turn_on()
        return worked

    if not console.ask_yes_no("Look at the Ambilight LEDs behind the TV: are they on?"):
        await _turn_on()
        if not console.ask_yes_no("I turned them on like the app: are they on now?"):
            report.add(Finding(STEP, "Ambilight can be turned on", "unknown", note="LEDs never seen on"))
            return

    await js.post("ambilight/power", {"power": "Off"})
    await _try("ambilight/power Off alone", "I sent only ambilight/power Off: are the LEDs off?")

    await set_node(session, STYLE_NODE, STYLE_OFF, STYLE_STRING)
    await _try("Style 210 (Off) alone", "I set only the style to \"Off\" (210): LEDs off?")

    await js.post("ambilight/power", {"power": "Off"})
    await set_node(session, STYLE_NODE, STYLE_OFF, STYLE_STRING)
    await _try("Turn-off like the app", "I turned off like the app (power Off + style 210): LEDs off?")
    await _try(
        "Turn-on like the app",
        "I turned them back on like the app (power On + style): are the LEDs on?",
        expect_off=False,
    )

    current_style = await read_node(session, STYLE_NODE)
    if current_style == STYLE_FOLLOW_VIDEO and initial_variant is not None:
        other = 224 if initial_variant != 224 else 225
        await update_node(session, VIDEO_NODE, {"selected_item": other}, VIDEO_STRING)
        await _try(
            "Video variant (node 220)",
            f"I set the video variant to \"{VIDEO_VARIANTS[other]}\": did the LED rendering change "
            "(colors, reaction speed)?",
            expect_off=False,
        )
        await update_node(session, VIDEO_NODE, {"selected_item": initial_variant}, VIDEO_STRING)
    else:
        report.add(Finding(STEP, "Video variant (node 220)", "not tested", note=f"current style = {current_style}"))

    await js.key("AmbilightOnOff")
    changed = console.ask_yes_no("I sent the AmbilightOnOff key: did the LEDs change?")
    report.add(Finding(STEP, "AmbilightOnOff key", "works" if changed else "ignored", hypothesis="H4"))
    if changed:
        await js.key("AmbilightOnOff")
