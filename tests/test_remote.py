from unittest.mock import AsyncMock

import pytest
from ucapi import StatusCodes

from intg_philips_titanos.remote import PhilipsRemote


@pytest.fixture
def make_remote(device, tv_config):
    def _make(**config_changes):
        for key, value in config_changes.items():
            setattr(tv_config, key, value)
        return PhilipsRemote(tv_config, device)

    return _make


def _pages(remote):
    return remote.options["user_interface"]["pages"]


def _items(remote, page_id):
    page = next(p for p in _pages(remote) if p["page_id"] == page_id)
    return page["items"]


async def _command(remote, cmd_id, params=None):
    return await remote.command(cmd_id, params, websocket=None)


def _texts(remote, page_id):
    return [(item.get("text"), item["command"]["cmd_id"]) for item in _items(remote, page_id)]


def test_pages_are_control_media_ambilight(make_remote):
    remote = make_remote()
    assert [page["page_id"] for page in _pages(remote)] == ["control", "media", "ambilight"]
    assert [page["name"] for page in _pages(remote)] == ["Commandes", "Médias", "Ambilight"]
    on_screen = {cmd for page in _pages(remote) for _, cmd in _texts(remote, page["page_id"])}
    assert not on_screen & {"RED", "GREEN", "YELLOW", "HDMI_1", "DIGIT_1"}
    assert ("OPTIONS", "OPTIONS") in _texts(remote, "control")
    assert _texts(remote, "control")[0] == ("ON/OFF", "POWER_TOGGLE")  # toggle: neither "ON" nor "OFF"
    assert on_screen <= set(remote.options["simple_commands"])


AMBILIGHT_FR = [
    ("ALLUMER", "AMBI_ON"),
    ("ÉTEINDRE", "AMBI_OFF"),
    ("IA", "AMBI_VIDEO_AI"),
    ("STANDARD", "AMBI_VIDEO_STD"),
    ("SPORT", "AMBI_SPORT"),
    ("CINÉMA", "AMBI_CINEMA"),
    ("JEUX", "AMBI_GAME"),
    ("LUMINA", "AMBI_LUMINA"),
    ("DISCO", "AMBI_DISCO"),
    ("RYTHME", "AMBI_RYTHM"),
    ("COULEUR", "AMBI_COLOR"),
    ("APPLI", "AMBI_APP"),
    ("LUM −", "AMBI_BRIGHT_DOWN"),
    ("LUM +", "AMBI_BRIGHT_UP"),
    ("SAT −", "AMBI_SAT_DOWN"),
    ("SAT +", "AMBI_SAT_UP"),
    ("BASCULE", "AMBILIGHT_TOGGLE"),
]


def test_ambilight_page_layout(make_remote):
    remote = make_remote()
    assert _texts(remote, "ambilight") == AMBILIGHT_FR
    page = next(p for p in _pages(remote) if p["page_id"] == "ambilight")
    assert page["grid"]["width"] == 4
    for item in page["items"]:
        width = item.get("size", {}).get("width", 1)
        assert item["location"]["x"] + width <= 4
        assert item["location"]["y"] < page["grid"]["height"]


def test_pages_in_english(make_remote):
    french = make_remote()
    french_cmds = [cmd for page in _pages(french) for _, cmd in _texts(french, page["page_id"])]
    remote = make_remote(ui_language="en")
    assert [page["name"] for page in _pages(remote)] == ["Controls", "Media", "Ambilight"]
    texts = {text for page in _pages(remote) for text, _ in _texts(remote, page["page_id"])}
    assert {"ON/OFF", "SETTINGS", "GAME", "RHYTHM", "COLOUR", "APP"} <= texts
    assert [cmd for page in _pages(remote) for _, cmd in _texts(remote, page["page_id"])] == french_cmds


def test_every_label_has_fr_and_en():
    from intg_philips_titanos.labels import LABELS

    assert set(LABELS["fr"]) == set(LABELS["en"])


async def test_send_cmd_forwards_repeat_delay_hold(make_remote, device, monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(device, "send_command", send)
    remote = make_remote()
    status = await _command(remote, "send_cmd", {"command": "VOLUME_UP", "repeat": 3, "delay": 100, "hold": 0})
    assert status == StatusCodes.OK
    send.assert_awaited_once_with("VOLUME_UP", repeat=3, delay_ms=100, hold_ms=0)


async def test_unknown_option_returns_bad_request(make_remote):
    remote = make_remote(picture_modes=[{"id": "vivid", "label": "Vif"}])
    assert await _command(remote, "send_cmd", {"command": "AMBI_ABSENT"}) == StatusCodes.BAD_REQUEST
    assert await _command(remote, "send_cmd", {"command": "PIC_VIVID"}) == StatusCodes.BAD_REQUEST


async def test_ambilight_command_reaches_tv(make_remote, fake_tv):
    remote = make_remote()
    assert await _command(remote, "send_cmd", {"command": "AMBI_GAME"}) == StatusCodes.OK
    assert fake_tv.menu_nodes[220]["selected_item"] == 225


async def test_send_cmd_sequence(make_remote, fake_tv):
    remote = make_remote()
    status = await _command(remote, "send_cmd_sequence", {"sequence": ["DIGIT_1", "DIGIT_2"], "delay": 100})
    assert status == StatusCodes.OK
    assert fake_tv.key_names() == ["Digit1", "Digit2"]


async def test_unreachable_tv_returns_503(make_remote, fake_tv):
    fake_tv.online = False
    fake_tv.offline_hang = 0.01
    remote = make_remote()
    assert await _command(remote, "send_cmd", {"command": "CURSOR_UP"}) == StatusCodes.SERVICE_UNAVAILABLE


async def test_ui_item_simple_command(make_remote, fake_tv):
    remote = make_remote()
    assert await _command(remote, "MUTE") == StatusCodes.OK
    assert fake_tv.key_names() == ["Mute"]


@pytest.mark.parametrize("command", ["POWER_ON", "POWER_OFF", "POWER_TOGGLE"])
async def test_power_failure_via_send_cmd_returns_503(make_remote, device, monkeypatch, command):
    for name in ("power_on", "power_off", "power_toggle"):
        monkeypatch.setattr(device, name, AsyncMock(return_value=False))
    remote = make_remote()
    assert await _command(remote, "send_cmd", {"command": command}) == StatusCodes.SERVICE_UNAVAILABLE


def test_driver_registers_only_the_remote(tv_config, device):
    """The media player stayed empty ("Nothing playing"): the TV provides no title, source or volume."""
    from intg_philips_titanos.driver import PhilipsDriver

    entities = PhilipsDriver().create_entities(tv_config, device)
    assert [type(entity) for entity in entities] == [PhilipsRemote]


async def test_state_change_is_published_to_remote(make_remote, device):
    """Regression seen in the simulator on the former media player: the configured entity is the
    same instance, a state change must still be sent to the Remote."""
    import asyncio
    from unittest.mock import MagicMock

    from ucapi.entities import Entities
    from ucapi.remote import Attributes, States

    from intg_philips_titanos.client import TvState

    remote = make_remote()
    configured = Entities("configured", asyncio.get_running_loop())
    configured.add(remote)
    remote._api = MagicMock(configured_entities=configured)
    published: list[dict] = []
    original = configured.update_attributes

    def _spy(entity_id, attributes):
        published.append(dict(attributes))
        return original(entity_id, attributes)

    configured.update_attributes = _spy
    device._state = TvState(online=True, power="ON")
    await remote.sync_state()
    assert any(update.get(Attributes.STATE) == States.ON for update in published), published
