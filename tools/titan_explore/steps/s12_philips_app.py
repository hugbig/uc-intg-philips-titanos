"""Step 12: comparison with the official "Philips Smart TV" app.

This app drives Titan OS TVs through JointSpace (Home Assistant issue #156776): if it can do
something, an API exists; otherwise, JointSpace probably does not expose it on this model.
Questions only, no request to the TV.
"""

from __future__ import annotations

from titan_explore.record import Finding
from titan_explore.session import Session

STEP = 12
CAPABILITIES = [
    "switch HDMI input",
    "change picture mode",
    "change Ambilight style",
    "turn Ambilight off",
    "turn the TV off",
    "turn the TV back on from standby",
    "adjust the volume (amplifier)",
]
_STATUS = {"yes": "works", "no": "ignored", "not found": "unknown"}


async def step_philips_app(session: Session) -> None:
    console, report = session.console, session.report
    if not console.ask_yes_no("Have you installed and paired the \"Philips Smart TV\" app on your phone?"):
        report.add(Finding(STEP, "Philips app", "not tested", note="app not installed"))
        return
    console.say("For each action, try it in the Philips app and say whether it works.")
    for capability in CAPABILITIES:
        answer = console.ask_choice(f"  Can the app {capability}?", ["yes", "no", "not found"])
        report.add(Finding(STEP, f"Philips app: {capability}", _STATUS[answer]))
