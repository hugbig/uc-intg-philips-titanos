"""Step 2: JointSpace pairing (and Titan OS MQTT, best effort — next task)."""

from __future__ import annotations

import asyncio
import ssl

import httpx

from intg_philips_titanos.pairing import PairingError, TvPairing
from titan_explore.mqtt import TitanMqtt, TitanMqttError
from titan_explore.record import Finding
from titan_explore.session import Session, TvUnreachable
from titan_explore.steps.common import jointspace, transport

STEP = 2
MAX_PIN_ATTEMPTS = 3


def _version(system: dict) -> str:
    version = system.get("api_version")
    if isinstance(version, dict):
        return ".".join(str(version.get(part, "?")) for part in ("Major", "Minor", "Patch"))
    return str(version or "?")


async def _pair(session: Session) -> None:
    console = session.console
    for attempt in range(1, MAX_PIN_ATTEMPTS + 1):
        client = TvPairing(session.host, transport=transport(session))
        try:
            try:
                await client.request_pin()
            except (PairingError, httpx.HTTPError) as err:
                raise TvUnreachable(f"pairing impossible: {err}") from err
            pin = console.ask_text("Enter the PIN shown on the TV:")
            try:
                credentials = await client.confirm_pin(pin)
            except (PairingError, httpx.HTTPStatusError) as err:
                session.journal.log("pairing", ok=False, attempt=attempt, error=str(err))
                console.say(f"PIN refused ({attempt}/{MAX_PIN_ATTEMPTS}). A new PIN will be displayed.")
                continue
        finally:
            await client.aclose()
        session.credentials["jointspace"] = {
            "username": credentials.username,
            "password": credentials.password,
            "protocol": "https" if credentials.secured_transport else "http",
        }
        session.save_credentials()
        session.journal.log("pairing", ok=True, attempt=attempt)
        session.report.add(Finding(STEP, "JointSpace pairing", "works", value=f"PIN accepted (attempt {attempt})"))
        return
    raise TvUnreachable("PIN refused 3 times")


async def step_pairing_jointspace(session: Session) -> None:
    reused = False
    if session.credentials.get("jointspace"):
        response = await jointspace(session).get("system")
        reused = response.ok
        if not reused:
            session.console.say("The saved credentials are no longer accepted: pairing again.")
            session.context.pop("js", None)
    if reused:
        session.report.add(Finding(STEP, "JointSpace credentials reused", "works"))
    else:
        session.console.say("A PIN will be displayed on the TV.")
        await _pair(session)

    js = jointspace(session)
    refused = {}
    for path in ("applications", "sources"):
        refused[path] = (await js.get(path)).status
    session.report.add(
        Finding(
            STEP,
            "Application and source lists",
            "works" if all(status >= 400 for status in refused.values()) else "info",
            value=", ".join(f"{path} : HTTP {status}" for path, status in refused.items()),
            note="\"works\" = refused as announced",
            hypothesis="H7",
        )
    )
    system = (await js.get("system")).data or {}
    features = system.get("featuring", {}).get("systemfeatures", {})
    session.report.add(
        Finding(
            STEP,
            "System information",
            "info",
            value=f"{system.get('name', '?')} — JointSpace {_version(system)}",
            note=f"os_type={system.get('os_type', '?')} ; secured_transport={features.get('secured_transport', '?')}",
        )
    )


def _mqtt(session: Session, **credentials: str) -> TitanMqtt:
    return TitanMqtt(session.host, client_factory=session.context.get("mqtt_factory"), **credentials)


async def _connect(mqtt: TitanMqtt) -> None:
    await asyncio.to_thread(mqtt.connect)


async def step_pairing_mqtt(session: Session) -> None:
    """Titan OS MQTT broker (H3), best effort: on failure, note it and carry on."""
    console = session.console
    saved = session.credentials.get("mqtt")
    if saved:
        mqtt = _mqtt(session, username=saved["username"], password=saved["password"])
        try:
            await _connect(mqtt)
            session.context["mqtt"] = mqtt
            session.report.add(Finding(STEP, "MQTT credentials reused", "works", hypothesis="H3"))
            return
        except (OSError, ssl.SSLError, TitanMqttError) as err:
            console.say(f"MQTT credentials refused ({err}): pairing again.")

    mqtt = _mqtt(session)
    try:
        await _connect(mqtt)
    except (OSError, ssl.SSLError, TitanMqttError) as err:
        session.journal.log("mqtt", ok=False, error=f"{type(err).__name__}: {err}")
        session.report.add(
            Finding(STEP, "Broker MQTT Titan OS (port 8883)", "unknown", note=f"{type(err).__name__}: {err}",
                    hypothesis="H3")
        )
        console.say("No MQTT broker reachable: the rest will use JointSpace only.")
        return
    session.report.add(Finding(STEP, "Broker MQTT Titan OS (port 8883)", "works", note="TLS verified", hypothesis="H3"))

    info = await asyncio.to_thread(mqtt.wait_retained, "info") or {}
    session.journal.log("mqtt", topic="info", data=info)
    if info:
        session.report.add(
            Finding(
                STEP,
                "MQTT information",
                "info",
                value=f"{info.get('model', '?')} — firmware {info.get('fw_version', '?')}",
                note=f"MQTT {info.get('mqttv_version', '?')} ; Ethernet {info.get('eth_mac_addr', '?')} ; "
                f"Wi-Fi {info.get('wlan_mac_addr', '?')}",
            )
        )
        topics = info.get("mqttv_topics")
        if topics:
            # The TV announces its own MQTT topics: basis for the phase B design.
            session.report.add(
                Finding(STEP, "MQTT topics announced by the TV", "info", value=", ".join(map(str, topics)))
            )
        _propose_mac(session, info)

    try:
        await asyncio.to_thread(mqtt.pair_start)
        pin = console.ask_text("Enter the PIN (4 digits) shown on the TV for the mobile app:")
        username, password = await asyncio.to_thread(mqtt.pair_finish, pin)
    except TitanMqttError as err:
        mqtt.disconnect()
        session.report.add(Finding(STEP, "MQTT pairing", "unknown", note=str(err), hypothesis="H3"))
        return
    mqtt.disconnect()
    session.credentials["mqtt"] = {"username": username, "password": password}
    session.save_credentials()
    session.report.add(Finding(STEP, "MQTT pairing", "works", hypothesis="H3"))
    authenticated = _mqtt(session, username=username, password=password)
    try:
        await _connect(authenticated)
    except (OSError, ssl.SSLError, TitanMqttError) as err:
        note = f"{type(err).__name__}: {err}"
        session.report.add(Finding(STEP, "Authenticated MQTT connection", "unknown", note=note, hypothesis="H3"))
        return
    session.context["mqtt"] = authenticated


def _propose_mac(session: Session, info: dict) -> None:
    eth, wlan = info.get("eth_mac_addr"), info.get("wlan_mac_addr")
    if not eth and not wlan:
        return
    connection = session.context.get("connection")
    hint = f" Declared connection: {connection} → use the {connection} MAC." if connection else ""
    session.console.say(
        f"The TV announces the Ethernet MAC {eth or '?'} and the Wi-Fi MAC {wlan or '?'} "
        f"(MAC entered: {session.mac or 'none'}).{hint}"
    )
    choice = session.console.ask_choice("Which MAC to use for network wake-up?", ["ethernet", "wifi", "keep"])
    if choice == "ethernet" and eth:
        session.mac = eth
    elif choice == "wifi" and wlan:
        session.mac = wlan
    session.report.add(Finding(STEP, "MAC chosen for wake-up", "info", value=session.mac or "none"))


async def step_pairing(session: Session) -> None:
    await step_pairing_jointspace(session)
    await step_pairing_mqtt(session)
