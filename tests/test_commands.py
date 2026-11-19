import re

from intg_philips_titanos.commands import KEY_MAP, static_commands

UC_COMMAND = re.compile(r"^[A-Z0-9/_.:+#*°@%()?-]{1,20}$")
RESERVED = {"on", "off", "toggle", "send_cmd", "send_cmd_sequence"}


def _gaps(times):
    return [b - a for a, b in zip(times, times[1:], strict=False)]


def test_no_discovery_command():
    assert "HDMI_DISCOVERY" not in static_commands()


def test_all_commands_match_uc_rules():
    for command in static_commands():
        assert UC_COMMAND.match(command), command
        assert command not in RESERVED


async def test_repeat_sends_n_keys(device, fake_tv):
    assert await device.send_command("VOLUME_UP", repeat=3, delay_ms=50) is True
    assert fake_tv.key_names() == ["VolumeUp"] * 3
    assert all(gap >= 0.05 for gap in _gaps([t for t, _ in fake_tv.keys]))


async def test_repeat_is_capped(device, fake_tv):
    await device.send_command("VOLUME_UP", repeat=500)
    assert fake_tv.key_names() == ["VolumeUp"] * 20


async def test_hold_repeats_repeatable_keys(device, fake_tv):
    await device.send_command("VOLUME_UP", hold_ms=1000)
    assert 4 <= len(fake_tv.key_names()) <= 6
    assert set(fake_tv.key_names()) == {"VolumeUp"}


async def test_hold_sends_once_for_other_keys(device, fake_tv):
    await device.send_command("CURSOR_ENTER", hold_ms=800)
    assert fake_tv.key_names() == ["Confirm"]


async def test_unknown_command_returns_false(device, fake_tv):
    assert await device.send_command("FOO") is False
    assert fake_tv.keys == []


def test_no_hdmi_or_picture_commands():
    assert not [c for c in static_commands() if c.startswith(("HDMI_", "PIC_"))]


def test_settings_is_quickmenu_and_options_key():
    assert KEY_MAP["SETTINGS"] == "QuickMenu"
    assert KEY_MAP["OPTIONS"] == "Options"


async def test_play_pause_sends_play(device, fake_tv):
    assert await device.send_command("PLAY_PAUSE") is True
    assert fake_tv.key_names() == ["Play"]
