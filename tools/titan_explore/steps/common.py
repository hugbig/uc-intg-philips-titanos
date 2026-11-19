"""Tools shared by the steps: authenticated JointSpace access, constants."""

from __future__ import annotations

import asyncio

import httpx

from intg_philips_titanos.client import PhilipsJointSpaceClient
from titan_explore.safe_js import SafeJointSpace
from titan_explore.session import Session, TvUnreachable, TvWedged


def transport(session: Session) -> httpx.AsyncBaseTransport | None:
    """httpx transport injected by the tests (fake server); None in real conditions."""
    return session.context.get("transport")


def jointspace(session: Session) -> SafeJointSpace:
    """Authenticated JointSpace access, created once per session from the credentials."""
    if "js" not in session.context:
        creds = session.credentials.get("jointspace")
        if not creds:
            raise TvUnreachable("no JointSpace credentials: run the pairing step first")
        client = PhilipsJointSpaceClient(
            session.host,
            6,
            creds["username"],
            creds["password"],
            secured_transport=creds.get("protocol", "https") == "https",
            transport=transport(session),
        )
        session.context["js"] = SafeJointSpace(client, session.journal, interval=session.interval)
    return session.context["js"]


async def observe(session: Session) -> dict:
    """Snapshot of what the TV reports, during a state chosen by the user.

    The TV may disappear from the network during these deliberate state changes: a lack of
    response is an observation, not a freeze.
    """
    js = jointspace(session)
    js.forget_answers()
    snapshot: dict = {"reachable": await js.reachable()}
    if snapshot["reachable"]:
        for path in ("powerstate", "screenstate", "context"):
            try:
                response = await js.get(path)
                snapshot[path] = response.data if response.ok else f"HTTP {response.status}"
            except (TvUnreachable, TvWedged):
                snapshot[path] = "no response"
        js.forget_answers()
    mqtt = session.context.get("mqtt")
    if mqtt is not None:
        try:
            snapshot["mqtt channels/state"] = await asyncio.to_thread(mqtt.wait_retained, "channels/state")
        except Exception as err:  # broker gone with the TV: that is an observation
            snapshot["mqtt channels/state"] = f"unavailable ({type(err).__name__})"
    session.journal.log("observe", **{key: str(value) for key, value in snapshot.items()})
    return snapshot


def describe(snapshot: dict) -> str:
    return " ; ".join(f"{key}={value}" for key, value in snapshot.items())


async def read_node_data(session: Session, node_id: int) -> dict | None:
    """Data of a settings node (e.g. {"activenode_id": 220} or {"selected_item": 222}), or None."""
    response = await jointspace(session).post("menuitems/settings/current", {"nodes": [{"nodeid": node_id}]})
    if not response.ok or not isinstance(response.data, dict):
        return None
    for item in response.data.get("values", []):
        value = item.get("value", {})
        if int(value.get("Nodeid", -1)) == node_id:
            data = value.get("data")
            return data if isinstance(data, dict) else None
    return None


async def read_node(session: Session, node_id: int, key: str = "activenode_id") -> int | None:
    """Active value of a node: activenode_id (parent node) or selected_item (list node)."""
    data = await read_node_data(session, node_id)
    value = data.get(key) if data else None
    return int(value) if value is not None else None


class RestoreFailed(RuntimeError):
    """The TV refused a restore: to be reported so the setting is fixed by hand."""


async def restore_node(session: Session, node_id: int, active: int, string_id: str = "") -> None:
    if not await set_node(session, node_id, active, string_id):
        raise RestoreFailed(f"node {node_id} not set back to {active}")


async def set_node(session: Session, node_id: int, active: int, string_id: str = "") -> bool:
    return await update_node(session, node_id, {"activenode_id": active}, string_id)


async def update_node(session: Session, node_id: int, data: dict, string_id: str = "") -> bool:
    """Changes a setting with a message shaped like the Philips Smart TV app's."""
    value = {
        "Nodeid": node_id,
        "Controllable": True,
        "Available": True,
        "string_id": string_id,
        "icon": "null",
        "data": data,
    }
    response = await jointspace(session).post("menuitems/settings/update", {"values": [{"value": value}]})
    return response.ok
