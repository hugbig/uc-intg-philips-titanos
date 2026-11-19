"""Step 11: `notifychange` — can the TV announce a change instead of being polled?"""

from __future__ import annotations

import asyncio

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import jointspace

STEP = 11
NOTIFY_TIMEOUT = 60.0
SUBSCRIPTION = {
    "notification": {
        "context": {},
        "powerstate": {},
        "audio/volume": {},
        "ambilight/currentconfiguration": {},
        "activities/current": {},
    }
}


async def step_notify(session: Session) -> None:
    js = jointspace(session)
    waiting = asyncio.create_task(
        js.post("notifychange", SUBSCRIPTION, timeout=NOTIFY_TIMEOUT, allow_timeout=True)
    )
    await asyncio.sleep(0)  # let the request go out before handing control back to the user
    # The console blocks: it runs in a thread so the wait carries on in the meantime.
    await asyncio.to_thread(
        session.console.pause,
        f"Listening to the TV (up to {NOTIFY_TIMEOUT:.0f} s). Change the volume with the Philips remote, then",
    )
    response = await waiting
    if response.ok and response.data:
        session.report.add(Finding(STEP, "notifychange", "works", value=str(response.data)[:300]))
    elif response.status == 0:
        note = f"nothing received within {NOTIFY_TIMEOUT:.0f} s"
        session.report.add(Finding(STEP, "notifychange", "ignored", note=note))
    else:
        session.report.add(Finding(STEP, "notifychange", "ignored", value=f"HTTP {response.status}"))
