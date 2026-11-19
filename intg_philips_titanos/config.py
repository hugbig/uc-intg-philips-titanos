from dataclasses import dataclass, field

# No `from __future__ import annotations`: ucapi-framework reads the field types
# to deserialize the configuration.


@dataclass
class PhilipsConfig:
    identifier: str
    name: str
    host: str
    mac: str
    api_version: int = 6
    username: str = ""
    password: str = ""
    secured_transport: bool = True
    poll_interval: int = 3
    # Wake-on-LAN broadcast address; empty = /24 computed from the TV IP.
    wol_broadcast: str = ""
    # Language of the Remote pages (`fr` or `en`), read from the Remote at setup.
    # A configuration from before v0.11.0 lacks this field: French, as before.
    ui_language: str = "fr"
    # Obsolete, ignored since v0.11.0 (HDMI macro and discovered options removed):
    # kept so that saved configurations still load.
    hdmi1_name: str = "HDMI 1"
    hdmi2_name: str = "HDMI 2"
    hdmi3_name: str = "HDMI 3"
    hdmi4_name: str = "HDMI 4"
    hdmi1_steps: int = 7
    hdmi2_steps: int = 6
    hdmi3_steps: int = 8
    hdmi4_steps: int = 9
    ambilight_styles: list[dict[str, str]] = field(default_factory=list)
    picture_modes: list[dict[str, str]] = field(default_factory=list)
