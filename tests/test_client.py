import socket
import time

import httpx
import pytest

from intg_philips_titanos.client import (
    UNCHANGED,
    PhilipsConnectionError,
    PhilipsJointSpaceClient,
    TvState,
)


async def test_send_key_is_not_retried(client, fake_tv):
    fake_tv.fail_next_key_with_timeout = True
    with pytest.raises(PhilipsConnectionError):
        await client.send_key("CursorDown")
    assert fake_tv.key_names() == ["CursorDown"]


async def test_get_is_retried(client, fake_tv):
    fake_tv.fail_next_get = True
    assert await client.get("powerstate") == {"powerstate": "On"}


async def test_min_interval_between_requests(client, fake_tv):
    for _ in range(5):
        await client.send_key("CursorDown")
    times = [t for t, _, _ in fake_tv.requests]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert len(gaps) == 4
    assert all(gap >= 0.11 for gap in gaps), gaps


async def test_listen_offline_is_fast(client, fake_tv):
    # httpx bounds the connection to 2 s: the fake TV therefore fails fast, like a real refused connection.
    fake_tv.online, fake_tv.offline_hang = False, 0.05
    start = time.monotonic()
    state = await client.listen(None)
    assert time.monotonic() - start < 2.5
    assert state.online is False


def _state_requests(fake_tv):
    return [(method, path) for _, method, path in fake_tv.requests]


@pytest.mark.parametrize(("power", "expected"), [("On", "ON"), ("Standby", "STANDBY")])
async def test_listen_from_notifychange(client, fake_tv, power, expected):
    fake_tv.power = power
    state = await client.listen(None)
    assert state == TvState(online=True, power=expected)
    assert _state_requests(fake_tv) == [("POST", "/6/notifychange")]


async def test_listen_offline(client, fake_tv):
    fake_tv.online, fake_tv.offline_hang, fake_tv.offline_exception = False, 0.05, httpx.ConnectError
    state = await client.listen(None)
    assert state.online is False


@pytest.mark.parametrize("answer", [(200, {}), (200, {"context": {"level1": "NA"}}), (200, None)])
async def test_listen_answer_without_powerstate_is_unchanged(client, fake_tv, monkeypatch, answer):
    """notifychange only returns what changed: without `powerstate`, power has not moved."""
    monkeypatch.setattr(fake_tv, "handle", lambda method, path, body: answer)
    assert await client.listen(None) == TvState(online=True, power=UNCHANGED)


@pytest.mark.parametrize(
    "answer",
    [
        (200, {"powerstate": {}}),
        (200, {"powerstate": {"powerstate": "Bizarre"}}),
        (200, {"powerstate": {"powerstate": {}}}),
        (200, {"powerstate": {"powerstate": ["On"]}}),
    ],
)
async def test_listen_odd_answers_are_unknown(client, fake_tv, monkeypatch, answer):
    monkeypatch.setattr(fake_tv, "handle", lambda method, path, body: answer)
    state = await client.listen(None)
    assert state == TvState(online=True, power="UNKNOWN")


@pytest.mark.parametrize("status", [401, 500])
async def test_listen_http_error_is_unknown_not_offline(client, fake_tv, monkeypatch, status):
    monkeypatch.setattr(fake_tv, "handle", lambda method, path, body: (status, None))
    state = await client.listen(None)
    assert state == TvState(online=True, power="UNKNOWN")


def test_subnet_broadcast():
    assert PhilipsJointSpaceClient.subnet_broadcast("192.168.1.42") == "192.168.1.255"
    assert PhilipsJointSpaceClient.subnet_broadcast("10.0.5.7", 16) == "10.0.255.255"


async def test_wol_sends_to_all_broadcasts(client, monkeypatch):
    sent: list[tuple[bytes, tuple[str, int]]] = []

    class _FakeSocket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def setsockopt(self, *args):
            pass

        def sendto(self, packet, address):
            sent.append((packet, address))

    monkeypatch.setattr(socket, "socket", _FakeSocket)
    await client.wake_on_lan("AA:BB:CC:DD:EE:FF", ["255.255.255.255", "192.168.1.255"])

    expected_packet = bytes.fromhex("FF" * 6 + "AABBCCDDEEFF" * 16)
    assert sorted(address for _, address in sent) == [("192.168.1.255", 9), ("255.255.255.255", 9)]
    assert all(packet == expected_packet for packet, _ in sent)


@pytest.mark.parametrize(
    ("state", "is_on", "is_standby"),
    [
        (TvState(online=True, power="ON"), True, False),
        (TvState(online=True, power="STANDBY"), False, True),
        (TvState(online=True, power="OFF"), False, False),
        (TvState(online=False, power="ON"), False, False),
        (TvState(online=True, power="UNKNOWN"), False, False),
    ],
)
def test_tv_state_power_rule(state, is_on, is_standby):
    assert state.is_on is is_on
    assert state.is_standby is is_standby


async def test_listen_without_known_state_answers_at_once(client, fake_tv):
    fake_tv.power = "Standby"
    state = await client.listen(None)
    assert state == TvState(online=True, power="STANDBY")


async def test_listen_waits_while_state_is_unchanged(client, fake_tv):
    fake_tv.notify_hold = 0.3
    start = time.monotonic()
    state = await client.listen("ON")
    assert time.monotonic() - start >= 0.25  # the TV kept the request open
    assert state == TvState(online=True, power=UNCHANGED)


async def test_listen_answers_as_soon_as_power_changes(client, fake_tv):
    import asyncio

    async def _switch_off():
        await asyncio.sleep(0.2)
        fake_tv.power = "Standby"

    switch = asyncio.create_task(_switch_off())
    start = time.monotonic()
    state = await client.listen("ON")
    await switch
    assert time.monotonic() - start < 1.0
    assert state == TvState(online=True, power="STANDBY")


async def test_listen_does_not_block_keys(client, fake_tv):
    """The listen stays open for a long time: keys must go out in the meantime."""
    import asyncio

    listening = asyncio.create_task(client.listen("ON"))
    await asyncio.sleep(0.1)
    start = time.monotonic()
    await client.send_key("CursorDown")
    assert time.monotonic() - start < 0.5
    listening.cancel()


async def test_listen_503_is_unchanged(client, fake_tv, monkeypatch):
    monkeypatch.setattr(fake_tv, "handle", lambda method, path, body: (503, None))
    assert await client.listen("ON") == TvState(online=True, power=UNCHANGED)
