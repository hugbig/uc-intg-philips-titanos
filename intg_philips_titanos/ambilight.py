"""Ambilight commands of the 65OLED851 (Titan OS).

Same requests as the Philips Smart TV app (capture of 2026-11-18):
- `POST ambilight/power` (On / Off) ;
- `POST menuitems/settings/update` on node 200 (style), then on the variant's list node;
- brightness and saturation: read the node (`menuitems/settings/current`), then write ±1;
- toggle: read the style (node 200), then switch off, or switch back on in the mode from before
  switch-off (`AmbiMemory`: otherwise the TV returns to "AI" video). The
  `AmbilightOnOff` key is not used: on the 65OLED851 it launches Prime Video.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from intg_philips_titanos.client import PhilipsConnectionError, PhilipsHttpStatusError, PhilipsJointSpaceClient

_LOG = logging.getLogger(__name__)

STYLE_NODE = 200
STYLE_OFF, STYLE_VIDEO, STYLE_AUDIO, STYLE_COLOR, STYLE_APP = 210, 220, 230, 240, 260
VIDEO_NODE, AUDIO_NODE = 220, 230
BRIGHTNESS_NODE, SATURATION_NODE = 271, 272

STRING_IDS = {
    STYLE_NODE: "MAIN_AMBILIGHT_STYLE",
    VIDEO_NODE: "MAIN_FOLLOW_VIDEO",
    AUDIO_NODE: "MAIN_FOLLOW_AUDIO",
    BRIGHTNESS_NODE: "MAIN_AMBILIGHT_BRIGHTNESS",
    SATURATION_NODE: "MAIN_AMBILIGHT_SATURATION",
}


@dataclass(frozen=True)
class AmbiAction:
    power: bool | None = None  # ambilight/power On / Off
    style: int | None = None  # activenode_id of node 200
    variant: tuple[int, int] | None = None  # (list node, selected_item)
    step: tuple[int, int, int, int] | None = None  # (node, delta, min, max)
    toggle: bool = False  # AMBI_OFF if the style is not "off", otherwise AMBI_ON


@dataclass
class AmbiMemory:
    """Ambilight mode from before switch-off, so that the toggle restores it (the TV forgets it)."""

    style: int | None = None
    variant: tuple[int, int] | None = None


def _video(item: int) -> AmbiAction:
    return AmbiAction(True, STYLE_VIDEO, (VIDEO_NODE, item))


def _audio(item: int) -> AmbiAction:
    return AmbiAction(True, STYLE_AUDIO, (AUDIO_NODE, item))


# Order = order of the Ambilight page.
AMBILIGHT_COMMANDS: dict[str, AmbiAction] = {
    "AMBI_ON": AmbiAction(True, STYLE_VIDEO),
    "AMBI_OFF": AmbiAction(False, STYLE_OFF),
    "AMBI_VIDEO_AI": _video(221),
    "AMBI_VIDEO_STD": _video(222),
    "AMBI_SPORT": _video(223),
    "AMBI_CINEMA": _video(224),
    "AMBI_GAME": _video(225),
    "AMBI_LUMINA": _audio(231),
    "AMBI_DISCO": _audio(232),
    "AMBI_RYTHM": _audio(233),
    "AMBI_COLOR": AmbiAction(True, STYLE_COLOR),
    "AMBI_APP": AmbiAction(True, STYLE_APP),
    "AMBI_BRIGHT_DOWN": AmbiAction(step=(BRIGHTNESS_NODE, -1, 0, 10)),
    "AMBI_BRIGHT_UP": AmbiAction(step=(BRIGHTNESS_NODE, 1, 0, 10)),
    "AMBI_SAT_DOWN": AmbiAction(step=(SATURATION_NODE, -1, -2, 2)),
    "AMBI_SAT_UP": AmbiAction(step=(SATURATION_NODE, 1, -2, 2)),
    "AMBILIGHT_TOGGLE": AmbiAction(toggle=True),
}


def settings_value(node_id: int, string_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """`values[]` item of `menuitems/settings/update`, in the Philips app format."""
    return {
        "value": {
            "Nodeid": node_id,
            "Controllable": True,
            "Available": True,
            "string_id": string_id,
            "icon": "null",
            "data": data,
        }
    }


async def _update(client: PhilipsJointSpaceClient, node_id: int, data: dict[str, Any]) -> None:
    await client.post("menuitems/settings/update", {"values": [settings_value(node_id, STRING_IDS[node_id], data)]})


async def _read_value(client: PhilipsJointSpaceClient, node_id: int, key: str = "value") -> int | None:
    answer = await client.post("menuitems/settings/current", {"nodes": [{"nodeid": node_id}]})
    try:
        return int(answer["values"][0]["value"]["data"][key])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def _remember(client: PhilipsJointSpaceClient, memory: AmbiMemory, style: int | None) -> None:
    """Remember the mode from before switch-off (style, and variant for video and audio).

    Optional: a refused or too slow read never prevents the switch-off.
    """
    try:
        if style is None:
            style = await _read_value(client, STYLE_NODE, "activenode_id")
        if style is None or style == STYLE_OFF:
            return
        variant = None
        if style in (VIDEO_NODE, AUDIO_NODE):
            item = await _read_value(client, style, "selected_item")
            if item is not None:
                variant = (style, item)
    except PhilipsConnectionError as err:
        _LOG.info("Ambilight mode not saved before switching off: %s", err)
        return
    memory.style, memory.variant = style, variant


def _restored(memory: AmbiMemory | None) -> AmbiAction | None:
    if memory is None or memory.style is None:
        return None
    return AmbiAction(True, memory.style, memory.variant)


async def apply_ambilight(client: PhilipsJointSpaceClient, command: str, memory: AmbiMemory | None = None) -> bool:
    """Apply an `AMBI_*` command. False if the TV refuses or the setting is unreadable.

    Requests are sent in order (power, style, variant) and stop at the
    first one refused. An unreachable TV raises `PhilipsConnectionError`, as for keys.
    """
    action = AMBILIGHT_COMMANDS[command]
    try:
        style = None
        if action.toggle:
            style = await _read_value(client, STYLE_NODE, "activenode_id")
            if style is None:
                _LOG.warning("Ambilight style unreadable: %s not applied", command)
                return False
            if style == STYLE_OFF:
                action = _restored(memory) or AMBILIGHT_COMMANDS["AMBI_ON"]
            else:
                action = AMBILIGHT_COMMANDS["AMBI_OFF"]
        if memory is not None:
            if action.power is False:
                await _remember(client, memory, style)
            elif action.power and action.style is not None:
                # Mode chosen on the Remote: restore it even after a switch-off done elsewhere.
                memory.style, memory.variant = action.style, action.variant
        if action.power is not None:
            await client.post("ambilight/power", {"power": "On" if action.power else "Off"})
        if action.style is not None:
            await _update(client, STYLE_NODE, {"activenode_id": action.style})
        if action.variant is not None:
            node_id, item = action.variant
            await _update(client, node_id, {"selected_item": item})
        if action.step is not None:
            node_id, delta, low, high = action.step
            current = await _read_value(client, node_id)
            if current is None:
                _LOG.warning("Ambilight setting %s unreadable: %s not applied", node_id, command)
                return False
            target = max(low, min(high, current + delta))
            if target != current:
                await _update(client, node_id, {"value": target})
    except PhilipsHttpStatusError as err:
        _LOG.warning("TV refused Ambilight command %s: %s", command, err)
        return False
    return True
