"""Step 8: Sources menu — line order, delays, anchoring from the bottom, trial at the macro pace.

Safety (spec §4): never `Confirm` unless the user has confirmed that the highlighted line is the
expected HDMI input and then explicitly accepted the validation; never offer validation on a
"Screen mirroring" line (it would take the TV off the network).
"""

from __future__ import annotations

import asyncio
import time

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import jointspace

STEP = 8
MACRO_INTERVAL = 0.12
EXTRA_DOWN = 2  # extra DOWN presses to be sure of reaching the bottom of the list
MIN_MENU_WAIT = 1.0  # minimum wait after the Source key before navigating
MENU_MARGIN = 0.5


def bottom_steps(lines: list[str]) -> dict[str, int]:
    """Number of UP presses from the last line to reach each HDMI input."""
    return {line: len(lines) - 1 - index for index, line in enumerate(lines) if "hdmi" in line.lower()}


def _top_steps(lines: list[str]) -> dict[str, int]:
    return {line: index for index, line in enumerate(lines) if "hdmi" in line.lower()}


async def _open_menu(session: Session, menu_delay: float) -> None:
    js = jointspace(session)
    await js.key("Source")
    await asyncio.sleep(menu_delay)


async def _go_to(session: Session, lines: list[str], up: int) -> None:
    js = jointspace(session)
    for _ in range(len(lines) + EXTRA_DOWN):
        await js.key("CursorDown")
    for _ in range(up):
        await js.key("CursorUp")


async def step_sources(session: Session) -> None:
    console, report, js = session.console, session.report, jointspace(session)

    console.say(
        "Open the Sources menu with the Philips remote and read the lines FROM TOP TO BOTTOM. "
        "Enter them one by one (empty line to finish)."
    )
    lines: list[str] = []
    while answer := console.ask_text(f"  Line {len(lines) + 1}:", allow_empty=True):
        lines.append(answer)
    console.pause("Close the menu (Back key on the Philips remote).")
    report.add(Finding(STEP, "Sources menu lines", "info", value=" | ".join(lines)))
    targets = bottom_steps(lines)
    if not targets:
        report.add(Finding(STEP, "HDMI inputs in the menu", "unknown", note="no \"HDMI\" line entered"))
        return

    start = time.monotonic()
    await js.key("Source")
    console.pause("I sent the Source key: press Enter as soon as the menu appears.")
    menu_delay = time.monotonic() - start
    report.add(Finding(STEP, "Sources menu display delay (perceived)", "info", value=f"{menu_delay:.1f} s"))
    for _ in range(3):
        await js.key("CursorDown")
    still_open = console.ask_yes_no("After 3 spaced DOWN presses, is the menu still open?")
    report.add(Finding(STEP, "Sources menu stays open at a slow pace", "works" if still_open else "ignored"))
    await js.key("Back")
    wait = max(menu_delay, MIN_MENU_WAIT) + MENU_MARGIN

    choices = [*lines, "other"]
    for hdmi, up in sorted(targets.items(), key=lambda item: item[1]):
        await _open_menu(session, wait)
        await _go_to(session, lines, up)
        seen = console.ask_choice(f"Which line is highlighted? (expected: {hdmi})", choices)
        if seen != hdmi:
            report.add(
                Finding(
                    STEP, f"Anchoring from the bottom — {hdmi}", "unknown", value=f"seen: {seen}", note="not validated"
                )
            )
            await js.key("Back")
            continue
        if "mirroring" in seen.lower() or not console.ask_yes_no(f"Validate \"{hdmi}\" (OK key)?"):
            report.add(Finding(STEP, f"Anchoring from the bottom — {hdmi}", "works", note="right line, not validated"))
            await js.key("Back")
            continue
        await js.key("Confirm")
        switched = console.ask_yes_no(f"Did the TV switch to {hdmi}?")
        report.add(
            Finding(STEP, f"Anchoring from the bottom — {hdmi}", "works" if switched else "ignored", note="validated")
        )

    top = _top_steps(lines)
    report.add(
        Finding(
            STEP,
            "Steps to configure",
            "to configure",
            value=" ; ".join(
                f"{hdmi}: {targets[hdmi]} from the bottom / {top[hdmi]} from the top" for hdmi in sorted(targets)
            ),
            hypothesis="H5",
        )
    )

    if not console.confirm_typed(
        "Trial at the macro pace (0.12 s between keys, without validation). "
        "It loads the TV server more."
    ):
        report.add(Finding(STEP, "Trial at the macro pace", "not tested"))
        return
    for hdmi, up in sorted(targets.items(), key=lambda item: item[1]):
        with js.fast(MACRO_INTERVAL):
            await _open_menu(session, wait)
            await _go_to(session, lines, up)
        ok = console.ask_yes_no(f"Is the \"{hdmi}\" line highlighted?")
        report.add(Finding(STEP, f"Macro pace — {hdmi}", "works" if ok else "ignored"))
        await js.key("Back")
