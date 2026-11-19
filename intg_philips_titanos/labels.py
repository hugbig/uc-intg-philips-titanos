"""Labels shown on the Remote pages, in French or English.

The UC API only accepts plain text for pages and their buttons: the language is read from
the Remote at setup (`PhilipsConfig.ui_language`). Command names, on the other hand, never
change (activities rely on them).
"""

from __future__ import annotations

LABELS: dict[str, dict[str, str]] = {
    "fr": {
        # pages
        "control": "Commandes",
        "media": "Médias",
        "ambilight": "Ambilight",
        # Commands
        "POWER_TOGGLE": "ON/OFF",
        "HOME": "ACCUEIL",
        "SOURCE": "SOURCE",
        "SETTINGS": "RÉGLAGES",
        "OPTIONS": "OPTIONS",
        "BACK": "RETOUR",
        "INFO": "INFO",
        "TV_EXIT": "TV",
        "VOLUME_DOWN": "VOL −",
        "MUTE": "MUET",
        "VOLUME_UP": "VOL +",
        "CHANNEL_DOWN": "CH −",
        "CHANNEL_UP": "CH +",
        "BLUE": "🔵",
        # Media
        "PREVIOUS": "PRÉC.",
        "REWIND": "RETOUR R.",
        "PLAY": "LECTURE",
        "FAST_FORWARD": "AVANCE R.",
        "NEXT": "SUIV.",
        "PAUSE": "PAUSE",
        "STOP": "STOP",
        "RECORD": "ENREG.",
        "CHANNELS_APP": "CHAÎNES",
        # Ambilight (names read from the TV menu)
        "AMBI_ON": "ALLUMER",
        "AMBI_OFF": "ÉTEINDRE",
        "AMBI_VIDEO_AI": "IA",
        "AMBI_VIDEO_STD": "STANDARD",
        "AMBI_SPORT": "SPORT",
        "AMBI_CINEMA": "CINÉMA",
        "AMBI_GAME": "JEUX",
        "AMBI_LUMINA": "LUMINA",
        "AMBI_DISCO": "DISCO",
        "AMBI_RYTHM": "RYTHME",
        "AMBI_COLOR": "COULEUR",
        "AMBI_APP": "APPLI",
        "AMBI_BRIGHT_DOWN": "LUM −",
        "AMBI_BRIGHT_UP": "LUM +",
        "AMBI_SAT_DOWN": "SAT −",
        "AMBI_SAT_UP": "SAT +",
        "AMBILIGHT_TOGGLE": "BASCULE",
    },
    "en": {
        "control": "Controls",
        "media": "Media",
        "ambilight": "Ambilight",
        "POWER_TOGGLE": "ON/OFF",
        "HOME": "HOME",
        "SOURCE": "SOURCE",
        "SETTINGS": "SETTINGS",
        "OPTIONS": "OPTIONS",
        "BACK": "BACK",
        "INFO": "INFO",
        "TV_EXIT": "TV",
        "VOLUME_DOWN": "VOL −",
        "MUTE": "MUTE",
        "VOLUME_UP": "VOL +",
        "CHANNEL_DOWN": "CH −",
        "CHANNEL_UP": "CH +",
        "BLUE": "🔵",
        "PREVIOUS": "PREV",
        "REWIND": "REWIND",
        "PLAY": "PLAY",
        "FAST_FORWARD": "FORWARD",
        "NEXT": "NEXT",
        "PAUSE": "PAUSE",
        "STOP": "STOP",
        "RECORD": "REC",
        "CHANNELS_APP": "CHANNELS",
        "AMBI_ON": "ON",
        "AMBI_OFF": "OFF",
        "AMBI_VIDEO_AI": "AI",
        "AMBI_VIDEO_STD": "STANDARD",
        "AMBI_SPORT": "SPORT",
        "AMBI_CINEMA": "CINEMA",
        "AMBI_GAME": "GAME",
        "AMBI_LUMINA": "LUMINA",
        "AMBI_DISCO": "DISCO",
        "AMBI_RYTHM": "RHYTHM",
        "AMBI_COLOR": "COLOUR",
        "AMBI_APP": "APP",
        "AMBI_BRIGHT_DOWN": "BRIGHT −",
        "AMBI_BRIGHT_UP": "BRIGHT +",
        "AMBI_SAT_DOWN": "SAT −",
        "AMBI_SAT_UP": "SAT +",
        "AMBILIGHT_TOGGLE": "TOGGLE",
    },
}


def ui_language(language_code: str | None) -> str:
    """Page language for a UC language code (`fr_FR`, `en_US`…): `fr` or `en`."""
    return "fr" if str(language_code or "").lower().startswith("fr") else "en"


def label(key: str, lang: str) -> str:
    """Label of a command or a page; English if the language is unknown."""
    return LABELS.get(lang, LABELS["en"])[key]
