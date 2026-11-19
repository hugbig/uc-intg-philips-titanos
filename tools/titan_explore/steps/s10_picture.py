"""Step 10: picture mode — find its setting, change it (then restore it), per-input memory.

No source consulted gives the identifier of the "picture mode" setting on Titan OS: the settings
tree has to be read. On the 65OLED851, the Philips app reads it without trouble (3.8 KB, Ambilight only,
capture of 2026-11-18): picture mode is probably absent there, which the step will confirm.
"""

from __future__ import annotations

from titan_explore.record import Finding
from titan_explore.session import Session
from titan_explore.steps.common import jointspace, read_node, restore_node, set_node

STEP = 10
STRUCTURE_TIMEOUT = 20.0
_KEYWORDS = ("picture", "image", "pict")


def _walk(node: dict):
    yield node
    for child in node.get("data", {}).get("nodes", []) or []:
        yield from _walk(child)


def find_picture_node(structure: dict) -> dict | None:
    """First node whose label identifier suggests the picture style / mode (excluding Ambilight)."""
    root = structure.get("node", structure)
    for node in _walk(root):
        label = str(node.get("string_id", "")).lower()
        if "ambilight" in label:
            continue
        if any(word in label for word in _KEYWORDS) and ("style" in label or "mode" in label):
            return node
    return None


async def step_picture(session: Session) -> None:
    js, console, report = jointspace(session), session.console, session.report

    node = None
    if console.confirm_typed(
        "Read the settings tree to find the picture mode? The Philips app reads it without trouble "
        "(small list); if the TV froze anyway, it would have to be unplugged."
    ):
        response = await js.get("menuitems/settings/structure", timeout=STRUCTURE_TIMEOUT)
        node = find_picture_node(response.data) if response.ok and isinstance(response.data, dict) else None
        if node is None:
            report.add(Finding(STEP, "Picture mode node", "unknown", note="absent from the settings tree"))
    else:
        report.add(Finding(STEP, "Picture mode node", "not tested", note="tree reading declined"))

    if node is not None:
        node_id = int(node["node_id"])
        string_id = str(node.get("string_id", ""))
        children = node.get("data", {}).get("nodes", [])
        choices = {int(child["node_id"]): child.get("string_id", "?") for child in children}
        report.add(
            Finding(
                STEP,
                "Picture mode node",
                "works",
                value=f"{node_id} ({node.get('string_id')})",
                note=", ".join(f"{key} {label}" for key, label in choices.items()),
            )
        )
        initial = await read_node(session, node_id)
        if initial is None:
            report.add(Finding(STEP, "Picture mode change", "unknown", note="current value unreadable"))
        else:
            session.restore.push(
                f"Picture mode (node {node_id})", lambda: restore_node(session, node_id, initial, string_id)
            )
            other = next((key for key in choices if key != initial), None)
            if other is None:
                report.add(Finding(STEP, "Picture mode change", "unknown", note="only one known value"))
            else:
                await set_node(session, node_id, other, string_id)
                changed = console.ask_yes_no(
                    f"I set the picture mode to \"{choices[other]}\": did the picture change?"
                )
                report.add(Finding(STEP, "Picture mode change", "works" if changed else "ignored"))
                await set_node(session, node_id, initial, string_id)

    console.pause(
        "With the Philips remote: set one picture mode on an HDMI input, another mode on a second "
        "input, then switch from one input to the other."
    )
    memorized = console.ask_yes_no("Did the picture mode follow the input (each kept its own)?")
    report.add(Finding(STEP, "Picture mode remembered per input", "works" if memorized else "ignored"))
    console.say("Remember to set these two inputs back to the modes you prefer.")
