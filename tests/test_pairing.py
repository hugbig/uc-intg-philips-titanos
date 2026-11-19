"""JointSpace API 6 pairing: wire format pinned on the fake TV (contract with real TVs)."""

import re

import pytest

from intg_philips_titanos import pairing
from tests.fake_tv import DEV_PIN, expected_signature

TV_IP = "192.168.1.42"
DEVICE = {
    "device_name": "remote3",
    "device_os": "Linux",
    "type": "native",
    "app_id": "unfolded_circle",
    "app_name": "Unfolded Circle Remote 3",
}


@pytest.fixture
async def tv_pairing(fake_tv):
    instance = pairing.TvPairing(TV_IP, transport=fake_tv.transport())
    yield instance
    await instance.aclose()


async def _request_pin(tv_pairing):
    await tv_pairing.request_pin()


def _body(fake_tv, endpoint):
    return next(body for path, body in fake_tv.bodies if path.endswith(endpoint))


def test_reference_signature():
    assert pairing.pairing_signature("1700000000", "1234") == "Up43OnIb8sG9V66+HISRwCPnYns="
    assert expected_signature("1700000000", "1234") == "Up43OnIb8sG9V66+HISRwCPnYns="


async def test_pair_request_payload(tv_pairing, fake_tv):
    await _request_pin(tv_pairing)
    body = _body(fake_tv, "/pair/request")
    featuring = {"systemfeatures": {"secured_transport": "false", "pairing_type": "digest_auth_pairing"}}
    assert body["access"] == {"scope": ["read", "write", "control"], "featuring": featuring}
    device = dict(body["device"])
    assert re.fullmatch(r"[0-9a-f]{32}", device.pop("id"))
    assert device == DEVICE


async def test_pair_grant_payload_and_credentials(tv_pairing, fake_tv):
    await _request_pin(tv_pairing)
    credentials = await tv_pairing.confirm_pin(DEV_PIN)
    request_device = _body(fake_tv, "/pair/request")["device"]
    grant = _body(fake_tv, "/pair/grant")
    timestamp = fake_tv._pair_timestamp
    assert grant == {
        "auth": {
            "auth_appId": "1",
            "auth_timestamp": timestamp,
            "auth_signature": expected_signature(str(timestamp), DEV_PIN),
            "pin": DEV_PIN,
        },
        "device": request_device,
    }
    assert (credentials.username, credentials.password) == (request_device["id"], fake_tv.last_auth_key)
    assert credentials.secured_transport is True  # /system answered over HTTPS


async def test_discovery_falls_back_to_http(tv_pairing, fake_tv):
    fake_tv.system_https_down = True
    await _request_pin(tv_pairing)
    pair_requests = [path for _, method, path in fake_tv.requests if path.endswith("/pair/request")]
    assert pair_requests
    assert tv_pairing.scheme == "http"


async def test_secured_transport_string_true_selects_https(tv_pairing, fake_tv):
    fake_tv.get_overrides["/6/system"] = {"featuring": {"systemfeatures": {"secured_transport": "true"}}}
    await _request_pin(tv_pairing)
    assert tv_pairing.scheme == "https"


async def test_rejected_grant_raises_pairing_error(tv_pairing):
    await _request_pin(tv_pairing)
    with pytest.raises(pairing.PairingError):
        await tv_pairing.confirm_pin("0000")
