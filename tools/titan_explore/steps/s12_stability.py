"""Step 13 (risky): at what request rate does the JointSpace server degrade (H2)?

Decreasing interval levels, 10 `powerstate` reads each; stops at the first degraded level
(freeze, or a response more than twice as slow as the first level's reference).
"""

from __future__ import annotations

import statistics

from titan_explore.record import Finding
from titan_explore.session import WEDGE_INSTRUCTIONS, Session, TvWedged
from titan_explore.steps.common import jointspace

STEP = 13
STABILITY_STEPS = (8.0, 4.0, 2.0, 1.0, 0.7, 0.4)
REQUESTS_PER_LEVEL = 10
SLOWDOWN_FACTOR = 2.0
MIN_SLOW_SECONDS = 0.5  # below this, a duration gap is not significant


def _fmt(seconds: float) -> str:
    return f"{seconds:g} s"


async def step_stability(session: Session) -> None:
    console, report, js = session.console, session.report, jointspace(session)
    console.say(
        "This test gradually increases the request rate until the first sign of weakness. "
        "According to other users, the TV server may then freeze: it would have to be "
        f"unplugged for 30 s. Duration: about {sum(STABILITY_STEPS) * REQUESTS_PER_LEVEL / 60:.0f} min."
    )
    if not console.confirm_typed("Run the stability test?"):
        report.add(Finding(STEP, "Safe interval", "not tested", hypothesis="H2"))
        return

    reference: float | None = None
    safe: float | None = None
    degraded: str | None = None
    previous = js.interval
    try:
        for level in STABILITY_STEPS:
            console.say(f"Level: one request every {_fmt(level)}…")
            js.interval = level
            durations = []
            try:
                for _ in range(REQUESTS_PER_LEVEL):
                    durations.append((await js.get("powerstate")).duration)
            except TvWedged as err:
                degraded = f"freeze ({err})"
            median = statistics.median(durations) if durations else 0.0
            if degraded is None and reference is not None:
                slowest = max(durations)
                if slowest > max(SLOWDOWN_FACTOR * reference, MIN_SLOW_SECONDS):
                    degraded = f"slow response ({slowest:.2f} s versus {reference:.2f} s at the first level)"
            if reference is None:
                reference = median
            report.add(
                Finding(
                    STEP,
                    f"Level {_fmt(level)}",
                    "ignored" if degraded else "works",
                    value=f"median {median:.2f} s over {len(durations)} requests",
                    note=degraded or "",
                )
            )
            if degraded:
                break
            safe = level
    finally:
        js.interval = previous

    if degraded is None:
        value = f"no degradation down to {_fmt(STABILITY_STEPS[-1])}"
    else:
        value = f"safe: {_fmt(safe) if safe else 'no level'}; degraded: {_fmt(level)} ({degraded})"
    report.add(Finding(STEP, "Safe interval", "info", value=value, hypothesis="H2"))
    if degraded and degraded.startswith("freeze"):
        report.notices.append(WEDGE_INSTRUCTIONS)
        console.say(f"\n⚠️  {WEDGE_INSTRUCTIONS}")
