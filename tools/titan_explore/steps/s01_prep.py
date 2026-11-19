"""Step 1: checklist and TV identification."""

from __future__ import annotations

import ipaddress

from intg_philips_titanos.setup_flow import MAC_RE  # same rule as the integration's configuration
from titan_explore.record import Finding
from titan_explore.session import Session

STEP = 1

CHECKLIST = [
    ("Fixed IP reserved for the TV on the router", "Reserve a fixed IP: otherwise the integration will lose the TV."),
    (
        "MAC address of the interface in use (Ethernet or Wi-Fi) known",
        "It is used for network wake-up; step 2 can read it from the TV if MQTT answers.",
    ),
]
# Wake-up setting specific to each connection type (TV network settings).
WAKE_SETTINGS = {
    "ethernet": (
        "Wake-on-LAN (Ethernet) enabled",
        "Enable \"Wake on LAN\" in the TV network settings, otherwise network wake-up will not work.",
    ),
    "wifi": (
        "WoWLAN \"Switch on with Wi-Fi\" enabled",
        "Enable \"Switch on with Wi-Fi\" (WoWLAN) in the TV network settings, otherwise network "
        "wake-up will not work. Over Wi-Fi, wake-up is often less reliable: prefer Ethernet if possible.",
    ),
}
USB_ITEM = (
    "No USB stick plugged into the TV",
    "A USB stick adds a line to the Sources menu and skews the calibration.",
)


async def step_prep(session: Session) -> None:
    console = session.console
    console.say("Let's first check a few settings.")
    connection = console.ask_choice("How is the TV connected", ["ethernet", "wifi"])
    session.context["connection"] = connection
    session.report.add(
        Finding(STEP, "TV network connection", "info", value=connection,
                note="network wake-up must target the MAC of this interface")
    )

    def _check(item: str, advice: str, needed: bool = True) -> None:
        if console.ask_yes_no(f"{item} ?"):
            session.report.add(Finding(STEP, item, "works"))
        elif needed:
            console.say(f"  → {advice}")
            session.report.add(Finding(STEP, item, "unknown", note=advice))
        else:
            session.report.add(Finding(STEP, item, "info", note=f"not needed on {connection}"))

    for item, advice in CHECKLIST:
        _check(item, advice)
    for kind, (item, advice) in WAKE_SETTINGS.items():
        _check(item, advice, needed=kind == connection)
    _check(*USB_ITEM)

    while not session.host:
        answer = console.ask_text("TV IP address:")
        try:
            ipaddress.ip_address(answer)
            session.host = answer
        except ValueError:
            console.say("That is not a valid IP address (example: 192.168.1.42).")
    session.report.add(Finding(STEP, "TV IP address", "info", value=session.host))

    while not session.mac:
        label = "Ethernet" if connection == "ethernet" else "Wi-Fi"
        answer = console.ask_text(f"TV {label} MAC address (Enter if unknown):", allow_empty=True)
        if not answer:
            break
        if MAC_RE.fullmatch(answer):
            session.mac = answer
        else:
            console.say("Expected format: AA:BB:CC:DD:EE:FF.")
    session.report.add(Finding(STEP, "MAC address", "info" if session.mac else "unknown", value=session.mac))
