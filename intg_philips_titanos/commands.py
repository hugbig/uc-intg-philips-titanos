"""Commands exposed to the Remote and the matching JointSpace keys.

Naming rules (official Unfolded Circle doc, core-api `entity_remote.md` /
`entity_media_player.md`): 20 characters maximum, no spaces, uppercase,
characters `A-Z 0-9 - / _ . : + # * ° @ % ( ) ?`.

Titan OS answers 200 even for an unknown key: a single key per command,
no fallback list.
"""

from __future__ import annotations

from intg_philips_titanos.ambilight import AMBILIGHT_COMMANDS

KEY_MAP: dict[str, str] = {
    "BACK": "Back",
    "HOME": "Home",
    "SETTINGS": "QuickMenu",  # quick settings, like the Philips app button
    "OPTIONS": "Options",
    "INFO": "Info",
    "TV_EXIT": "WatchTV",
    "SOURCE": "Source",
    "CURSOR_UP": "CursorUp",
    "CURSOR_DOWN": "CursorDown",
    "CURSOR_LEFT": "CursorLeft",
    "CURSOR_RIGHT": "CursorRight",
    "CURSOR_ENTER": "Confirm",
    "VOLUME_UP": "VolumeUp",
    "VOLUME_DOWN": "VolumeDown",
    "MUTE": "Mute",
    "CHANNEL_UP": "ChannelStepUp",
    "CHANNEL_DOWN": "ChannelStepDown",
    "RED": "RedColour",
    "GREEN": "GreenColour",
    "YELLOW": "YellowColour",
    "BLUE": "BlueColour",
    "PLAY_PAUSE": "Play",  # PlayPause is ignored by the 65OLED851 (exploration 2026-11-18)
    "PLAY": "Play",
    "PAUSE": "Pause",
    "STOP": "Stop",
    "REWIND": "Rewind",
    "FAST_FORWARD": "FastForward",
    "RECORD": "Record",
    "NEXT": "Next",
    "PREVIOUS": "Previous",
    **{f"DIGIT_{digit}": f"Digit{digit}" for digit in range(10)},
    "CHANNELS_APP": "WatchTV",
}

POWER_COMMANDS = ("POWER_TOGGLE", "POWER_ON", "POWER_OFF")

# Keys that a held press (`hold`) repeats. For the others, `hold` (long press in the
# UC doc sense) sends once: Titan OS has no long press through the API, and
# repeating a confirmation would trigger several actions.
REPEATABLE_ON_HOLD = frozenset(
    {
        "VOLUME_UP",
        "VOLUME_DOWN",
        "CURSOR_UP",
        "CURSOR_DOWN",
        "CURSOR_LEFT",
        "CURSOR_RIGHT",
        "CHANNEL_UP",
        "CHANNEL_DOWN",
    }
)

MAX_REPEAT = 20
HOLD_INTERVAL = 0.2
DEFAULT_REPEAT_DELAY = 0.15

def static_commands() -> list[str]:
    return [*KEY_MAP, *POWER_COMMANDS, *AMBILIGHT_COMMANDS]
