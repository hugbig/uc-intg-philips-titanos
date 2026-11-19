"""Step 3: power states (H1) and wake-up (H6)."""

from __future__ import annotations

import asyncio
import time

from intg_philips_titanos.client import PhilipsJointSpaceClient
from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import describe, jointspace, observe

STEP = 3
WOL_TIMEOUT = 60.0


def _powerstate(snapshot: dict) -> str:
    value = snapshot.get("powerstate")
    return str(value.get("powerstate", "?")) if isinstance(value, dict) else str(value or "?")


async def step_power(session: Session) -> None:
    console, report = session.console, session.report

    console.pause("1/4 — Turn the TV on (picture visible on the Titan OS home screen).")
    on = await observe(session)
    report.add(Finding(STEP, "TV on", "info", value=describe(on)))

    console.pause("2/4 — Put the TV in standby with a SHORT press on Power on the Philips remote, wait 10 s.")
    standby = await observe(session)
    report.add(Finding(STEP, "TV in quick standby", "info", value=describe(standby)))
    if standby["reachable"]:
        lies = _powerstate(standby).lower() == "on"
        report.add(
            Finding(
                STEP,
                "powerstate in quick standby",
                "lies" if lies else "works",
                value=_powerstate(standby),
                hypothesis="H1",
            )
        )
        await jointspace(session).post("powerstate", {"powerstate": "On"})
        woke = console.ask_yes_no("3/4 — I requested power-on through the API: did the screen turn on?")
        report.add(Finding(STEP, "Power-on via POST powerstate On", "works" if woke else "ignored", hypothesis="H6"))
    else:
        report.add(Finding(STEP, "powerstate in quick standby", "unknown", note="TV unreachable", hypothesis="H1"))
        report.add(Finding(STEP, "Power-on via POST powerstate On", "unknown", note="TV unreachable", hypothesis="H6"))

    console.pause(
        "4/4 — Turn the TV off as completely as possible (LONG press on Power, or the Switch off menu), "
        "wait 1 minute."
    )
    off = await observe(session)
    report.add(Finding(STEP, "TV off / deep standby", "info", value=describe(off)))
    await _wake_on_lan(session)


async def _wake_on_lan(session: Session) -> None:
    console, report = session.console, session.report
    if not session.mac:
        report.add(Finding(STEP, "Network wake", "not tested", note="no MAC address", hypothesis="H6"))
        return
    js = jointspace(session)
    js.forget_answers()
    if await js.reachable():
        console.pause(
            "The TV still responds: it is not completely off. Do a LONG press on Power "
            "(or the Switch off menu), wait 1 minute."
        )
        js.forget_answers()
        if await js.reachable():
            report.add(
                Finding(STEP, "Network wake", "not tested", note="the TV still responded", hypothesis="H6")
            )
            return
    broadcasts = ["255.255.255.255", PhilipsJointSpaceClient.subnet_broadcast(session.host)]
    start = time.monotonic()
    await js.wake_on_lan(session.mac, broadcasts)
    console.say("Wake packet sent, waiting for the TV to respond…")
    period = max(session.interval, 0.5)
    while time.monotonic() - start < WOL_TIMEOUT:
        if await js.reachable():
            delay = time.monotonic() - start
            report.add(
                Finding(STEP, "Network wake (API reachable)", "works", value=f"{delay:.1f} s", hypothesis="H6")
            )
            console.pause("Press Enter as soon as the picture appears.")
            image = time.monotonic() - start
            report.add(Finding(STEP, "Network wake (picture visible)", "info", value=f"{image:.1f} s"))
            return
        await asyncio.sleep(period)
    report.add(
        Finding(STEP, "Network wake (API reachable)", "ignored", note=f"nothing within {WOL_TIMEOUT:.0f} s",
                hypothesis="H6")
    )
