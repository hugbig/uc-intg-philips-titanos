import json

from ucapi_framework import BaseConfigManager

from intg_philips_titanos.config import PhilipsConfig

LEGACY_V0913 = {
    "identifier": "philips_192_168_1_42",
    "name": "Philips TV",
    "host": "192.168.1.42",
    "mac": "AA:BB:CC:DD:EE:FF",
    "api_version": 6,
    "username": "device-id",
    "password": "auth-key",
    "secured_transport": True,
    "poll_interval": 3,
}


def test_legacy_config_loads_with_defaults(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps([LEGACY_V0913]))
    manager = BaseConfigManager(str(tmp_path), config_class=PhilipsConfig)
    config = manager.get("philips_192_168_1_42")
    assert config is not None
    assert config.hdmi2_steps == 6
    assert config.ambilight_styles == []
    assert (config.username, config.password) == ("device-id", "auth-key")


LEGACY_V0100 = {
    **LEGACY_V0913,
    "hdmi1_name": "PS5",
    "hdmi1_steps": 5,
    "wol_broadcast": "",
    "ambilight_styles": [{"id": "x", "label": "X"}],
    "picture_modes": [{"id": "vivid", "label": "Vif"}],
}


def test_v0100_config_loads_in_french_without_hdmi_or_picture(tmp_path, device):
    from intg_philips_titanos.remote import PhilipsRemote

    (tmp_path / "config.json").write_text(json.dumps([LEGACY_V0100]))
    manager = BaseConfigManager(str(tmp_path), config_class=PhilipsConfig)
    config = manager.get("philips_192_168_1_42")
    assert config.ui_language == "fr"
    commands = PhilipsRemote(config, device).options["simple_commands"]
    assert not [c for c in commands if c.startswith(("HDMI_", "PIC_"))]
