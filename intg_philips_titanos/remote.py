"""Remote entity of the TV.

Conforms to the official UC doc (`doc/entities/entity_remote.md`) :
- commands `on`, `off`, `toggle`, `send_cmd` (parameters `repeat`, `delay` in ms, `hold` in ms)
  and `send_cmd_sequence`;
- HTTP response codes: 400 invalid command, 503 TV unreachable;
- page grid ≤ 8 × 12; pages and mapping are only taken into account when the
  entity is added to the Remote (only `simple_commands` are updated afterwards).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ucapi import StatusCodes
from ucapi.remote import Attributes, Features, Remote, States
from ucapi.ui import Buttons
from ucapi_framework import RemoteEntity

from intg_philips_titanos.client import PhilipsConnectionError
from intg_philips_titanos.commands import DEFAULT_REPEAT_DELAY, POWER_COMMANDS, static_commands
from intg_philips_titanos.config import PhilipsConfig
from intg_philips_titanos.device import PhilipsDevice
from intg_philips_titanos.labels import label

_LOG = logging.getLogger(__name__)

GRID_WIDTH = 4

# Physical buttons → commands. STOP, RECORD and MENU exist in `ucapi.ui.Buttons` but
# the UC doc only lists the Remote Two buttons: to be confirmed for the Remote 3 via
# `GET /api/cfg/device/button_layout` (simulator). PLAY → "Play": "PlayPause"
# did not work on the original author's TV (to be rechecked on the 65OLED851).
BUTTON_MAPPING = [
    ("POWER", "POWER_TOGGLE"),
    ("HOME", "HOME"),
    ("BACK", "BACK"),
    ("DPAD_UP", "CURSOR_UP"),
    ("DPAD_DOWN", "CURSOR_DOWN"),
    ("DPAD_LEFT", "CURSOR_LEFT"),
    ("DPAD_RIGHT", "CURSOR_RIGHT"),
    ("DPAD_MIDDLE", "CURSOR_ENTER"),
    ("VOLUME_UP", "VOLUME_UP"),
    ("VOLUME_DOWN", "VOLUME_DOWN"),
    ("MUTE", "MUTE"),
    ("CHANNEL_UP", "CHANNEL_UP"),
    ("CHANNEL_DOWN", "CHANNEL_DOWN"),
    ("PREV", "PREVIOUS"),
    ("PLAY", "PLAY"),
    ("NEXT", "NEXT"),
    ("STOP", "STOP"),
    ("RECORD", "RECORD"),
    ("MENU", "SETTINGS"),
    ("RED", "RED"),
    ("GREEN", "GREEN"),
    ("YELLOW", "YELLOW"),
    ("BLUE", "BLUE"),
]


def _text(text: str, x: int, y: int, command: str, width: int = 1) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "text", "location": {"x": x, "y": y}, "text": text, "command": {"cmd_id": command}}
    if width != 1:
        item["size"] = {"width": width, "height": 1}
    return item


class PhilipsRemote(RemoteEntity):
    def __init__(self, device_config: PhilipsConfig, device: PhilipsDevice):
        self._device = device
        self._config = device_config
        super().__init__(
            f"remote.{device_config.identifier}",
            device_config.name,
            features=[Features.SEND_CMD, Features.ON_OFF, Features.TOGGLE],
            attributes={Attributes.STATE: States.UNKNOWN},
            simple_commands=static_commands(),
            button_mapping=self._button_mapping(),
            ui_pages=self._ui_pages(),
            icon="custom:titanos_entite.png",
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    # ------------------------------------------------------------------ state
    async def sync_state(self) -> None:
        state = self._device.state
        # The remote entity only has ON / OFF (UC doc): standby or unreachable → OFF.
        self.update({Attributes.STATE: States.ON if state.is_on else States.OFF})

    # ------------------------------------------------------------------ definition
    @staticmethod
    def _button_mapping() -> list[dict[str, Any]]:
        result = []
        for name, command in BUTTON_MAPPING:
            button = getattr(Buttons, name, None)
            if button is not None:
                result.append(
                    {
                        "button": button.value,
                        "short_press": {"cmd_id": "send_cmd", "params": {"command": command}},
                        "long_press": None,
                    }
                )
        return result

    def _ui_pages(self) -> list[dict[str, Any]]:
        lang = self._config.ui_language

        def button(command: str, x: int, y: int, width: int = 1) -> dict[str, Any]:
            return _text(label(command, lang), x, y, command, width)

        def page(page_id: str, height: int, items: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "page_id": page_id,
                "name": label(page_id, lang),
                "grid": {"width": GRID_WIDTH, "height": height},
                "items": items,
            }

        # Red, green, yellow and digits: no effect on the 65OLED851; they remain commands.
        control = [
            button("POWER_TOGGLE", 0, 0),
            button("HOME", 1, 0),
            button("SOURCE", 2, 0),
            button("SETTINGS", 3, 0),
            button("OPTIONS", 0, 1),
            _text("↑", 1, 1, "CURSOR_UP"),
            button("BACK", 3, 1),
            _text("←", 0, 2, "CURSOR_LEFT"),
            _text("OK", 1, 2, "CURSOR_ENTER"),
            _text("→", 2, 2, "CURSOR_RIGHT"),
            button("INFO", 3, 2),
            _text("↓", 1, 3, "CURSOR_DOWN"),
            button("TV_EXIT", 3, 3),
            button("VOLUME_DOWN", 0, 4),
            button("MUTE", 1, 4),
            button("VOLUME_UP", 2, 4),
            button("BLUE", 3, 4),
            button("CHANNEL_DOWN", 0, 5),
            button("CHANNEL_UP", 3, 5),
        ]
        media = [
            button("PREVIOUS", 0, 0),
            button("REWIND", 1, 0),
            button("PLAY", 2, 0),
            button("FAST_FORWARD", 3, 0),
            button("NEXT", 0, 1),
            button("PAUSE", 1, 1),
            button("STOP", 2, 1),
            button("RECORD", 3, 1),
            button("CHANNELS_APP", 1, 2, 2),
        ]
        variants = [
            "AMBI_VIDEO_AI", "AMBI_VIDEO_STD", "AMBI_SPORT", "AMBI_CINEMA",
            "AMBI_GAME", "AMBI_LUMINA", "AMBI_DISCO", "AMBI_RYTHM",
        ]  # fmt: skip
        settings = ["AMBI_BRIGHT_DOWN", "AMBI_BRIGHT_UP", "AMBI_SAT_DOWN", "AMBI_SAT_UP"]
        ambilight = [
            button("AMBI_ON", 0, 0, 2),
            button("AMBI_OFF", 2, 0, 2),
            *[button(command, index % 4, 1 + index // 4) for index, command in enumerate(variants)],
            button("AMBI_COLOR", 0, 3, 2),
            button("AMBI_APP", 2, 3, 2),
            *[button(command, index, 4) for index, command in enumerate(settings)],
            button("AMBILIGHT_TOGGLE", 0, 5, GRID_WIDTH),
        ]
        return [page("control", 6, control), page("media", 3, media), page("ambilight", 6, ambilight)]

    # ------------------------------------------------------------------ commandes
    async def _run(self, command: str, params: dict[str, Any]) -> bool:
        return await self._device.send_command(
            command,
            repeat=int(params.get("repeat") or 1),
            delay_ms=int(params.get("delay") or 0),
            hold_ms=int(params.get("hold") or 0),
        )

    async def _run_sequence(self, params: dict[str, Any]) -> bool:
        sequence = params.get("sequence") or []
        if isinstance(sequence, str):  # the UC doc also shows a form "A,B,C"
            sequence = [item.strip() for item in sequence.split(",") if item.strip()]
        delay = int(params.get("delay") or 0) / 1000 or DEFAULT_REPEAT_DELAY
        for index, command in enumerate(sequence):
            if index:
                await asyncio.sleep(delay)
            if not await self._run(str(command), params):
                return False
        return bool(sequence)

    async def _handle_command(
        self, entity: Remote, cmd_id: str, params: dict[str, Any] | None = None
    ) -> StatusCodes:
        params = params or {}
        try:
            if cmd_id == "on":
                return StatusCodes.OK if await self._device.power_on() else StatusCodes.SERVICE_UNAVAILABLE
            if cmd_id == "off":
                return StatusCodes.OK if await self._device.power_off() else StatusCodes.SERVICE_UNAVAILABLE
            if cmd_id == "toggle":
                return StatusCodes.OK if await self._device.power_toggle() else StatusCodes.SERVICE_UNAVAILABLE
            if cmd_id == "send_cmd_sequence":
                ok = await self._run_sequence(params)
            elif cmd_id == "send_cmd":
                command = str(params.get("command", ""))
                ok = await self._run(command, params)
                if not ok and command in POWER_COMMANDS:
                    # The TV did not confirm or is unreachable: not an invalid command.
                    return StatusCodes.SERVICE_UNAVAILABLE
            else:
                # UI page item: the UC doc allows a simple command as cmd_id.
                ok = await self._run(cmd_id, {})
            return StatusCodes.OK if ok else StatusCodes.BAD_REQUEST
        except PhilipsConnectionError as err:
            _LOG.warning("TV unreachable for %s: %s", cmd_id, err)
            return StatusCodes.SERVICE_UNAVAILABLE
        except Exception:
            _LOG.exception("Philips command failed: %s", cmd_id)
            return StatusCodes.SERVER_ERROR
