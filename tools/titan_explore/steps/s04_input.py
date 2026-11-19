"""Step 4: can we read the active input (and so verify the HDMI macro)?"""

from __future__ import annotations

import json

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import describe, jointspace, observe

STEP = 4
SOURCES = ["Titan OS home", "HDMI 1", "HDMI 2", "HDMI 3", "HDMI 4"]


async def step_active_input(session: Session) -> None:
    console, report = session.console, session.report
    signatures: dict[str, str] = {}
    for source in SOURCES:
        choice = console.ask_choice(f"Switch the TV to \"{source}\" with the Philips remote", ["done", "skip"])
        if choice == "skip":
            continue
        snapshot = await observe(session)
        activity = await jointspace(session).get("activities/current")
        snapshot["activities/current"] = activity.data if activity.ok else f"HTTP {activity.status}"
        signature = json.dumps(
            {key: snapshot.get(key) for key in ("context", "activities/current", "mqtt channels/state")},
            sort_keys=True,
            default=str,
        )
        signatures[source] = signature
        report.add(Finding(STEP, f"Snapshot on {source}", "info", value=describe(snapshot)))

    hdmi = {source: sig for source, sig in signatures.items() if source.startswith("HDMI")}
    distinct = len(set(hdmi.values()))
    if len(hdmi) < 2:
        verdict, status = "unknown (fewer than two HDMI inputs recorded)", "unknown"
    elif distinct == len(hdmi):
        verdict, status = "yes — each HDMI has its own signature", "works"
    elif distinct == 1:
        verdict, status = "no — all HDMI inputs look alike", "info"
    else:
        verdict, status = f"partial — {distinct} signatures for {len(hdmi)} HDMI inputs", "info"
    report.add(Finding(STEP, "Distinguish HDMI inputs", status, value=verdict))
