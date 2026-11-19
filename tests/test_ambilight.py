"""Ambilight commands: same requests as the Philips Smart TV app (capture of 2026-11-18)."""

from __future__ import annotations

import re

from intg_philips_titanos.ambilight import AMBILIGHT_COMMANDS, AmbiMemory, apply_ambilight
from intg_philips_titanos.commands import static_commands


def _calls(fake_tv) -> list[tuple[str, object]]:
    """Writes received by the TV, in order: ("power", value) or (Nodeid, data)."""
    calls: list[tuple[str, object]] = []
    updates = iter(fake_tv.settings_updates)
    for _, method, path in fake_tv.requests:
        if method != "POST":
            continue
        if path.endswith("/ambilight/power"):
            calls.append(("power", None))
        elif path.endswith("/menuitems/settings/update"):
            value = next(updates)
            calls.append((value["Nodeid"], value["data"]))
    return calls


def test_all_commands_are_uc_valid():
    assert len(AMBILIGHT_COMMANDS) == 17
    for command in AMBILIGHT_COMMANDS:
        assert len(command) <= 20 and re.fullmatch(r"[A-Z0-9_]+", command), command
    assert set(AMBILIGHT_COMMANDS) <= set(static_commands())


async def test_ambi_off_like_app(client, fake_tv):
    assert await apply_ambilight(client, "AMBI_OFF") is True
    assert fake_tv.ambilight["power"] == "Off"
    assert _calls(fake_tv) == [("power", None), (200, {"activenode_id": 210})]
    value = fake_tv.settings_updates[0]
    assert value["string_id"] == "MAIN_AMBILIGHT_STYLE"
    assert value["Controllable"] is True and value["Available"] is True and value["icon"] == "null"


async def test_ambi_on_like_app(client, fake_tv):
    assert await apply_ambilight(client, "AMBI_ON") is True
    assert fake_tv.ambilight["power"] == "On"
    assert _calls(fake_tv) == [("power", None), (200, {"activenode_id": 220})]


async def test_ambi_disco(client, fake_tv):
    assert await apply_ambilight(client, "AMBI_DISCO") is True
    assert _calls(fake_tv) == [("power", None), (200, {"activenode_id": 230}), (230, {"selected_item": 232})]
    assert fake_tv.settings_updates[1]["string_id"] == "MAIN_FOLLOW_AUDIO"
    assert fake_tv.menu_nodes[230]["selected_item"] == 232


async def test_ambi_sport(client, fake_tv):
    assert await apply_ambilight(client, "AMBI_SPORT") is True
    assert _calls(fake_tv)[-1] == (220, {"selected_item": 223})
    assert fake_tv.menu_nodes[220]["selected_item"] == 223


async def test_ambi_color_and_app(client, fake_tv):
    assert await apply_ambilight(client, "AMBI_COLOR") is True
    assert await apply_ambilight(client, "AMBI_APP") is True
    styles = [data for node, data in _calls(fake_tv) if node == 200]
    assert styles == [{"activenode_id": 240}, {"activenode_id": 260}]
    assert all(node in ("power", 200) for node, _ in _calls(fake_tv))


async def test_brightness_up_reads_then_writes(client, fake_tv):
    assert await apply_ambilight(client, "AMBI_BRIGHT_UP") is True
    assert _calls(fake_tv) == [(271, {"value": 6})]
    assert fake_tv.menu_nodes[271]["value"] == 6


async def test_brightness_up_at_max_writes_nothing(client, fake_tv):
    fake_tv.menu_nodes[271]["value"] = 10
    assert await apply_ambilight(client, "AMBI_BRIGHT_UP") is True
    assert fake_tv.settings_updates == []


async def test_saturation_down_at_min_writes_nothing(client, fake_tv):
    fake_tv.menu_nodes[272]["value"] = -2
    assert await apply_ambilight(client, "AMBI_SAT_DOWN") is True
    assert fake_tv.settings_updates == []


async def test_refused_update_fails_and_stops(client, fake_tv):
    fake_tv.refuse_settings_update = True
    assert await apply_ambilight(client, "AMBI_DISCO") is False
    updates = [path for _, method, path in fake_tv.requests if path.endswith("/settings/update")]
    assert len(updates) == 1


async def test_unreadable_node_fails(client, fake_tv):
    del fake_tv.menu_nodes[271]
    assert await apply_ambilight(client, "AMBI_BRIGHT_UP") is False
    assert fake_tv.settings_updates == []


async def test_device_routes_ambilight_commands(device, fake_tv):
    assert await device.send_command("AMBI_GAME") is True
    assert fake_tv.menu_nodes[220]["selected_item"] == 225


async def test_toggle_turns_off_when_on(client, fake_tv):
    fake_tv.menu_nodes[200]["activenode_id"] = 230
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE") is True
    assert _calls(fake_tv) == [("power", None), (200, {"activenode_id": 210})]
    assert fake_tv.keys == []  # the AmbilightOnOff key launches Prime Video on the 65OLED851


async def test_toggle_turns_on_when_off(client, fake_tv):
    fake_tv.menu_nodes[200]["activenode_id"] = 210
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE") is True
    assert _calls(fake_tv) == [("power", None), (200, {"activenode_id": 220})]


async def test_toggle_fails_when_style_unreadable(client, fake_tv):
    del fake_tv.menu_nodes[200]
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE") is False
    assert fake_tv.settings_updates == []


async def test_device_toggle_sends_no_key(device, fake_tv):
    assert await device.send_command("AMBILIGHT_TOGGLE") is True
    assert fake_tv.key_names() == []


async def test_toggle_restores_video_variant(client, fake_tv):
    """The TV returns to "AI" when switched back on: the toggle restores the previous mode (2026-11-18)."""
    memory = AmbiMemory()
    fake_tv.menu_nodes[200]["activenode_id"] = 220
    fake_tv.menu_nodes[220]["selected_item"] = 222  # STANDARD
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", memory) is True  # off
    fake_tv.menu_nodes[220]["selected_item"] = 221  # the TV forgot: AI
    fake_tv.settings_updates.clear()
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", memory) is True  # rallume
    assert [(v["Nodeid"], v["data"]) for v in fake_tv.settings_updates] == [
        (200, {"activenode_id": 220}),
        (220, {"selected_item": 222}),
    ]
    assert fake_tv.menu_nodes[220]["selected_item"] == 222


async def test_toggle_restores_audio_mode(client, fake_tv):
    memory = AmbiMemory()
    assert await apply_ambilight(client, "AMBI_DISCO", memory) is True
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", memory) is True
    assert fake_tv.menu_nodes[200]["activenode_id"] == 210
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", memory) is True
    assert fake_tv.menu_nodes[200]["activenode_id"] == 230
    assert fake_tv.menu_nodes[230]["selected_item"] == 232


async def test_off_button_is_remembered_by_toggle(client, fake_tv):
    memory = AmbiMemory()
    fake_tv.menu_nodes[200]["activenode_id"] = 240  # couleur fixe
    assert await apply_ambilight(client, "AMBI_OFF", memory) is True
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", memory) is True
    assert fake_tv.menu_nodes[200]["activenode_id"] == 240


async def test_toggle_on_without_memory_is_ambi_on(client, fake_tv):
    fake_tv.menu_nodes[200]["activenode_id"] = 210
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", AmbiMemory()) is True
    assert _calls(fake_tv) == [("power", None), (200, {"activenode_id": 220})]


async def test_device_toggle_remembers_mode(device, fake_tv):
    assert await device.send_command("AMBI_SPORT") is True
    assert await device.send_command("AMBILIGHT_TOGGLE") is True
    fake_tv.menu_nodes[220]["selected_item"] = 221
    assert await device.send_command("AMBILIGHT_TOGGLE") is True
    assert fake_tv.menu_nodes[200]["activenode_id"] == 220
    assert fake_tv.menu_nodes[220]["selected_item"] == 223


async def test_off_still_works_when_mode_unreadable(client, fake_tv, monkeypatch):
    real_handle = fake_tv.handle

    def _refuse_reads(method, path, body):
        if path.endswith("/menuitems/settings/current"):
            return 500, None
        return real_handle(method, path, body)

    monkeypatch.setattr(fake_tv, "handle", _refuse_reads)
    assert await apply_ambilight(client, "AMBI_OFF", AmbiMemory()) is True
    assert fake_tv.menu_nodes[200]["activenode_id"] == 210


async def test_mode_chosen_on_remote_is_restored_after_off_elsewhere(client, fake_tv):
    memory = AmbiMemory()
    assert await apply_ambilight(client, "AMBI_VIDEO_STD", memory) is True
    assert await apply_ambilight(client, "AMBI_DISCO", memory) is True
    fake_tv.menu_nodes[200]["activenode_id"] = 210  # switched off with the Philips remote
    assert await apply_ambilight(client, "AMBILIGHT_TOGGLE", memory) is True
    assert fake_tv.menu_nodes[200]["activenode_id"] == 230
    assert fake_tv.menu_nodes[230]["selected_item"] == 232
