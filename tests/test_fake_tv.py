"""Overridden GET responses of the fake TV (--routes-json option), for capturing the Philips app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fake_tv import FakeTitanTV, load_routes_json

TEMPLATE = Path(__file__).parent / "fixtures" / "titan_routes.json"


def test_get_override_replaces_builtin_route() -> None:
    tv = FakeTitanTV()
    tv.get_overrides = {"/6/system": {"name": "Philips OLED", "os_type": "Titan"}}

    assert tv.handle("GET", "/6/system", None) == (200, {"name": "Philips OLED", "os_type": "Titan"})


def test_get_override_adds_unknown_route_and_ignores_query_string() -> None:
    tv = FakeTitanTV()
    tv.get_overrides = {"/system/serialnumber_encrypted": {"serialnumber_encrypted": "abc"}}

    assert tv.handle("GET", "/system/serialnumber_encrypted?x=1", None) == (200, {"serialnumber_encrypted": "abc"})


def test_get_override_does_not_change_other_methods() -> None:
    tv = FakeTitanTV()
    tv.get_overrides = {"/6/pair/request": {"error_id": "OVERRIDDEN"}}

    status, payload = tv.handle("POST", "/6/pair/request", {})

    assert status == 200 and payload["error_id"] == "SUCCESS"


def test_load_routes_json_reads_mapping(tmp_path: Path) -> None:
    path = tmp_path / "routes.json"
    path.write_text(json.dumps({"/6/system": {"name": "TV"}}), encoding="utf-8")

    assert load_routes_json(path) == {"/6/system": {"name": "TV"}}


@pytest.mark.parametrize("content", ['["/6/system"]', '{"6/system": {}}'])
def test_load_routes_json_rejects_invalid_mapping(tmp_path: Path, content: str) -> None:
    path = tmp_path / "routes.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_routes_json(path)


def test_template_announces_secured_transport() -> None:
    routes = load_routes_json(TEMPLATE)

    features = routes["/6/system"]["featuring"]["systemfeatures"]
    assert features["secured_transport"] is True  # boolean on the real 65OLED851
    assert "/system/serialnumber_encrypted" in routes


# ---------------------------------------------------------------------- real behavior (Phase B)
import asyncio  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402

from tests.fake_tv import (  # noqa: E402
    AMBILIGHT_AUDIO_NODE,
    AMBILIGHT_BRIGHTNESS_NODE,
)


async def _post(tv: FakeTitanTV, path: str, body: dict, timeout: float = 2.0) -> httpx.Response:
    async with httpx.AsyncClient(transport=tv.transport(), base_url="http://tv") as http:
        return await asyncio.wait_for(http.post(path, json=body), timeout)


def test_realistic_powerstate_get_always_on() -> None:
    tv = FakeTitanTV.realistic()
    tv.power = "Standby"

    assert tv.handle("GET", "/6/powerstate", None) == (200, {"powerstate": "On"})


async def test_realistic_notifychange_reports_real_power_immediately() -> None:
    tv = FakeTitanTV.realistic()
    tv.power = "Standby"

    start = time.monotonic()
    response = await _post(tv, "/6/notifychange", {"notification": {"powerstate": {}}})

    assert time.monotonic() - start < 0.5
    assert response.json()["powerstate"] == {"powerstate": "Standby"}


def test_realistic_post_powerstate_ignored() -> None:
    tv = FakeTitanTV.realistic()
    tv.power = "Standby"

    status, _ = tv.handle("POST", "/6/powerstate", {"powerstate": "On"})

    assert status == 200 and tv.power == "Standby"


def test_standby_key_toggles() -> None:
    tv = FakeTitanTV.realistic()
    tv.handle("POST", "/6/input/key", {"key": "Standby"})
    assert tv.power == "Standby"
    tv.handle("POST", "/6/input/key", {"key": "Standby"})
    assert tv.power == "On"


async def test_power_report_lag() -> None:
    tv = FakeTitanTV.realistic()
    tv.power_report_lag = 0.3
    tv.handle("POST", "/6/input/key", {"key": "Standby"})

    early = await _post(tv, "/6/notifychange", {"notification": {"powerstate": {}}})
    await asyncio.sleep(0.4)
    late = await _post(tv, "/6/notifychange", {"notification": {"powerstate": {}}})

    assert early.json()["powerstate"] == {"powerstate": "On"}
    assert late.json()["powerstate"] == {"powerstate": "Standby"}


def _update(tv: FakeTitanTV, node: int, data: dict) -> None:
    tv.handle("POST", "/6/menuitems/settings/update", {"values": [{"value": {"Nodeid": node, "data": data}}]})


def _current(tv: FakeTitanTV, node: int) -> dict:
    _, payload = tv.handle("POST", "/6/menuitems/settings/current", {"nodes": [{"nodeid": node}]})
    return payload["values"][0]["value"]["data"]


def test_audio_and_brightness_nodes_roundtrip() -> None:
    tv = FakeTitanTV.realistic()
    _update(tv, AMBILIGHT_AUDIO_NODE, {"selected_item": 232})
    _update(tv, AMBILIGHT_BRIGHTNESS_NODE, {"value": 7})

    assert _current(tv, AMBILIGHT_AUDIO_NODE) == {"selected_item": 232}
    assert _current(tv, AMBILIGHT_BRIGHTNESS_NODE) == {"value": 7}


async def test_default_notifychange_still_long_polls() -> None:
    tv = FakeTitanTV()

    with pytest.raises(TimeoutError):
        await _post(tv, "/6/notifychange", {"notification": {"powerstate": {}}}, timeout=0.3)
