"""Power: state listened to continuously (notifychange long-poll), Standby key, Wake-on-LAN,
rest time between two changes."""

import asyncio
import socket

import pytest

from intg_philips_titanos.client import TvState

WOL_PORT = 9


@pytest.fixture
def wol_packets(monkeypatch):
    sent: list[tuple[str, int]] = []

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
            sent.append(address)

    real_socket = socket.socket

    def _factory(*args, **kwargs):
        if len(args) >= 4 or "fileno" in kwargs:  # sockets internes d'asyncio (socketpair)
            return real_socket(*args, **kwargs)
        return _FakeSocket()

    monkeypatch.setattr(socket, "socket", _factory)
    return sent


@pytest.fixture(autouse=True)
def fast_timings(fake_tv, monkeypatch):
    from intg_philips_titanos import device as device_module

    fake_tv.offline_hang = 0.05
    monkeypatch.setattr(device_module, "POWER_ON_POLL", 0.1)
    monkeypatch.setattr(device_module, "CONFIRM_LISTEN_TIMEOUT", 0.5)


async def _until(condition, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "condition never met"
        await asyncio.sleep(0.02)


async def _timed(coro):
    loop = asyncio.get_running_loop()
    start = loop.time()
    result = await coro
    return result, loop.time() - start


async def _settle(device):
    task = device._power_task
    if task is not None:
        await task


def _short_cooldown(monkeypatch, grace=0.2, cooldown=0.8):
    from intg_philips_titanos import device as device_module

    monkeypatch.setattr(device_module, "STANDBY_GRACE", grace)
    monkeypatch.setattr(device_module, "BOUNCE_WINDOW", grace)
    monkeypatch.setattr(device_module, "POWER_COOLDOWN", cooldown)


# ------------------------------------------------------------------ state listening
async def test_state_follows_tv(tv, fake_tv):
    assert tv.state.power == "ON"
    fake_tv.power = "Standby"  # switched off with the Philips remote
    await _until(lambda: tv.state.power == "STANDBY")
    fake_tv.power = "On"
    await _until(lambda: tv.state.power == "ON")


async def test_one_listen_at_a_time(tv, fake_tv):
    await asyncio.sleep(1.2)
    assert fake_tv.notify_max_pending == 1  # never two listens open on the TV side


async def test_concurrent_connects_start_one_listener(tv_config, client, fake_tv):
    """The Remote asks for several connections at once when reconnecting (log 2026-11-19 12:22)."""
    from intg_philips_titanos.device import PhilipsDevice

    fake_tv.notify_hold = 0.5
    tv_config.poll_interval = 0
    device = PhilipsDevice(tv_config, client=client)
    try:
        assert await asyncio.gather(device.connect(), device.connect(), device.connect()) == [True] * 3
        await asyncio.sleep(1.2)
        assert fake_tv.notify_max_pending == 1  # three parallel listens → 503 on the real TV
    finally:
        await device.disconnect()


async def test_state_kept_while_tv_is_quiet(tv, fake_tv):
    await asyncio.sleep(1.2)  # several listens with no change
    assert tv.state.power == "ON"


async def test_unreadable_state_is_unknown(tv_config, client, fake_tv):
    from intg_philips_titanos.device import PhilipsDevice

    fake_tv.notify_unavailable = True
    device = PhilipsDevice(tv_config, client=client)
    await device.poll_device()
    assert device.state == TvState(online=True, power="UNKNOWN")


# ------------------------------------------------------------------ switch-off
async def test_power_off_when_on_sends_standby(tv, fake_tv):
    assert await tv.power_off() is True
    assert fake_tv.key_names() == ["Standby"]
    assert tv.state.power == "STANDBY"


async def test_power_off_when_standby_sends_nothing(tv, fake_tv):
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    assert await tv.power_off() is True
    assert fake_tv.key_names() == []


async def test_power_off_when_offline_succeeds(tv, fake_tv):
    fake_tv.online = False
    await _until(lambda: not tv.state.online)
    assert await tv.power_off() is True
    assert fake_tv.key_names() == []


async def test_power_off_when_unknown_fails(tv_config, client, fake_tv):
    from intg_philips_titanos.device import PhilipsDevice

    fake_tv.notify_unavailable = True
    device = PhilipsDevice(tv_config, client=client)
    await device.poll_device()
    assert await device.power_off() is False
    assert fake_tv.key_names() == []


async def test_expected_state_shown_during_report_lag(tv, fake_tv, monkeypatch):
    _short_cooldown(monkeypatch, grace=0.6, cooldown=0.6)
    fake_tv.power_report_lag = 0.4
    assert await tv.power_off() is True
    await asyncio.sleep(0.2)  # the TV still reports "On"
    assert tv.state.power == "STANDBY"


async def test_ignored_key_state_corrected_after_grace(tv, fake_tv, monkeypatch):
    _short_cooldown(monkeypatch, grace=0.3, cooldown=0.3)
    real_handle = fake_tv.handle

    def _ignored_key(method, path, body):
        if path.endswith("/input/key"):
            return 200, None  # the key arrives but the TV does not change
        return real_handle(method, path, body)

    monkeypatch.setattr(fake_tv, "handle", _ignored_key)
    assert await tv.power_off() is True
    assert tv.state.power == "STANDBY"
    await _until(lambda: tv.state.power == "ON")


# ------------------------------------------------------------------ allumage
async def test_power_on_when_on_sends_nothing(tv, fake_tv, wol_packets):
    assert await tv.power_on() is True
    assert fake_tv.key_names() == []
    assert wol_packets == []


async def test_power_on_from_standby_answers_at_once(tv, fake_tv, wol_packets):
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    fake_tv.power_report_lag = 1.0
    ok, elapsed = await _timed(tv.power_on())
    assert ok is True
    assert elapsed < 0.5  # the Remote does not wait for the confirmation
    await _settle(tv)
    assert fake_tv.key_names() == ["Standby"]
    assert tv.state.power == "ON"
    assert wol_packets == []


async def test_power_on_confirmed_when_open_listen_misses_switch(tv, fake_tv, wol_packets):
    """The listen opened before the key does not report the power-on (log 2026-11-19 12:11)."""
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    fake_tv.notify_hold = 5.0
    fake_tv.notify_misses_switch = True
    await asyncio.sleep(0.7)  # a 5 s listen is now open
    assert await tv.power_on(timeout=1.5) is True
    await _settle(tv)
    assert tv.state.power == "ON"
    assert wol_packets == []


async def test_power_off_confirmed_when_open_listen_misses_switch(tv, fake_tv, monkeypatch):
    _short_cooldown(monkeypatch)
    fake_tv.notify_hold = 5.0
    fake_tv.notify_misses_switch = True
    await asyncio.sleep(0.7)
    assert await tv.power_off() is True
    await asyncio.sleep(0.5)  # standby effective, grace period elapsed
    fake_tv.power = "On"  # switched back on with the Philips remote: the entity must see it
    await _until(lambda: tv.state.power == "ON", timeout=2.0)


async def test_power_on_confirmed_when_tv_silent_while_booting(tv, fake_tv, wol_packets):
    """The TV boots fast but does not answer a listen opened during its boot (log 2026-11-19 14:29)."""
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    fake_tv.notify_hold = 30.0
    fake_tv.boot_silence = 0.5
    assert await tv.power_on(timeout=4.0) is True
    await _until(lambda: tv._reported_power == "ON", timeout=3.0)  # the TV itself confirms
    await _settle(tv)
    assert wol_packets == []


async def test_power_off_right_after_power_on_while_tv_silent(tv, fake_tv, monkeypatch, wol_packets):
    """OFF pressed while the TV boots silently: the Standby key must leave (it turns the TV off)."""
    _short_cooldown(monkeypatch)
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    fake_tv.notify_hold = 30.0
    fake_tv.boot_silence = 3.0
    assert await tv.power_on(timeout=4.0) is True
    await asyncio.sleep(1.0)  # cooldown over, the TV still silent
    assert tv.state.power == "ON"  # target state shown while the TV has not answered
    assert await tv.power_off() is True
    assert fake_tv.key_names() == ["Standby", "Standby"]


async def test_restart_keeps_last_state_when_tv_refuses(tv, fake_tv, monkeypatch):
    """A 503 right after the key must not make the state unknown (power_off would refuse)."""
    _short_cooldown(monkeypatch)
    real_send_key = tv._client.send_key

    async def _key_then_busy(key):
        await real_send_key(key)
        fake_tv.notify_unavailable = True  # the TV refuses listens right after the key

    monkeypatch.setattr(tv._client, "send_key", _key_then_busy)
    assert await tv.power_off() is True
    await asyncio.sleep(0.5)  # grace period elapsed, the TV still answers 503
    assert tv.state.power != "UNKNOWN"
    fake_tv.notify_unavailable = False
    await _until(lambda: tv.state.power == "STANDBY")  # true state as soon as the TV answers


async def test_restart_requested_while_listen_answers_is_not_lost(device, monkeypatch):
    """Standby key at the same instant as the answer: the earlier answer is ignored."""

    async def _answer_as_key_is_sent(known, timeout=None):
        device._restart_listening()
        return TvState(online=True, power="STANDBY")

    monkeypatch.setattr(device._client, "listen", _answer_as_key_is_sent)
    assert await device._listen_once() is None


async def test_power_on_offline_answers_at_once_then_gives_up(tv, fake_tv, wol_packets):
    fake_tv.online = False
    await _until(lambda: not tv.state.online)
    ok, elapsed = await _timed(tv.power_on(timeout=1.0))
    assert ok is True
    assert elapsed < 0.5
    assert ("255.255.255.255", WOL_PORT) in wol_packets
    assert ("192.168.1.255", WOL_PORT) in wol_packets
    await _settle(tv)
    assert tv.state.power != "ON"


async def test_power_on_offline_without_mac_fails(tv, fake_tv, tv_config, wol_packets):
    tv_config.mac = ""
    fake_tv.online = False
    await _until(lambda: not tv.state.online)
    assert await tv.power_on(timeout=1.0) is False
    assert wol_packets == []


async def test_power_on_succeeds_after_wol(tv, fake_tv, wol_packets):
    fake_tv.online = False
    await _until(lambda: not tv.state.online)

    async def _wake_up():
        while not wol_packets:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
        fake_tv.online, fake_tv.power = True, "On"

    waker = asyncio.create_task(_wake_up())
    assert await tv.power_on(timeout=5.0) is True
    await _settle(tv)
    await waker
    assert tv.state.power == "ON"


async def test_power_on_offline_then_standby_sends_single_key(tv, fake_tv, wol_packets):
    fake_tv.online, fake_tv.power = False, "Standby"
    await _until(lambda: not tv.state.online)

    async def _network_up():
        while not wol_packets:
            await asyncio.sleep(0.01)
        fake_tv.online = True

    waker = asyncio.create_task(_network_up())
    assert await tv.power_on(timeout=5.0) is True
    await _settle(tv)
    await waker
    assert fake_tv.key_names() == ["Standby"]
    assert tv.state.power == "ON"


async def test_power_on_wol_when_key_does_not_wake(tv, fake_tv, wol_packets, monkeypatch):
    from intg_philips_titanos import device as device_module

    monkeypatch.setattr(device_module, "WOL_AFTER_KEY", 0.3)
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    real_handle = fake_tv.handle

    def _deep_sleep(method, path, body):
        if path.endswith("/input/key"):
            fake_tv.keys.append((0.0, body["key"]))  # the key arrives but does not wake the TV
            return 200, None
        return real_handle(method, path, body)

    monkeypatch.setattr(fake_tv, "handle", _deep_sleep)
    assert await tv.power_on(timeout=1.5) is True
    await _settle(tv)
    assert fake_tv.key_names() == ["Standby"]
    assert ("255.255.255.255", WOL_PORT) in wol_packets


async def test_power_on_unknown_state_sends_wol_not_key(tv_config, client, fake_tv, wol_packets):
    from intg_philips_titanos.device import PhilipsDevice

    fake_tv.notify_unavailable = True
    device = PhilipsDevice(tv_config, client=client)
    await device.poll_device()
    ok, elapsed = await _timed(device.power_on(timeout=0.5))
    assert ok is True
    assert elapsed < 0.5
    assert fake_tv.key_names() == []  # a Standby key would switch off a TV that is on
    assert ("255.255.255.255", WOL_PORT) in wol_packets
    device.cancel_power_task()


# ------------------------------------------------------------------ ON/OFF and rest time
async def test_toggle_on_tv_switches_off(tv, fake_tv):
    assert await tv.power_toggle() is True
    assert fake_tv.key_names() == ["Standby"]
    await _until(lambda: tv.state.power == "STANDBY")


async def test_toggle_unknown_state_sends_standby_key(tv_config, client, fake_tv, wol_packets):
    from intg_philips_titanos.device import PhilipsDevice

    fake_tv.notify_unavailable = True
    device = PhilipsDevice(tv_config, client=client)
    await device.poll_device()
    ok, elapsed = await _timed(device.power_toggle())
    assert ok is True
    assert elapsed < 0.5
    assert fake_tv.key_names() == ["Standby"]  # like the Philips remote button
    assert wol_packets == []


async def test_toggle_twice_quickly_sends_one_key(tv, fake_tv):
    fake_tv.power_report_lag = 1.0
    assert await tv.power_toggle() is True
    assert await tv.power_toggle() is True
    assert fake_tv.key_names() == ["Standby"]


async def test_toggle_concurrent_presses_send_one_key(tv, fake_tv):
    results = await asyncio.gather(tv.power_toggle(), tv.power_toggle())
    assert results == [True, True]
    assert fake_tv.key_names() == ["Standby"]


async def test_toggle_during_cooldown_is_deferred(tv, fake_tv, monkeypatch):
    """The TV does not like chained on/off cycles (acceptance test 2026-11-18): the second order waits."""
    _short_cooldown(monkeypatch)
    assert await tv.power_toggle() is True  # off
    await asyncio.sleep(0.3)  # after the bounce, during the rest
    ok, elapsed = await _timed(tv.power_toggle())
    assert ok is True and elapsed < 0.2  # the Remote gets its answer immediately
    assert fake_tv.key_names() == ["Standby"]  # not sent yet
    await _until(lambda: fake_tv.key_names() == ["Standby", "Standby"])  # sent after the rest
    await _until(lambda: tv.state.power == "ON")


async def test_toggle_after_slow_key_is_deferred_not_ignored(tv, fake_tv, monkeypatch):
    """Real TV 2026-11-19 18:16: the key took 2.5 s to leave, OFF pressed 8.5 s after ON was dropped
    as a bounce because the bounce was counted from the key, not from the press."""
    from intg_philips_titanos import device as device_module

    _short_cooldown(monkeypatch, grace=0.6, cooldown=1.5)
    monkeypatch.setattr(device_module, "BOUNCE_WINDOW", 0.2)  # shorter than the grace
    fake_tv.key_delay = 0.5
    assert await tv.power_toggle() is True  # off, the key leaves 0.5 s after the press
    await asyncio.sleep(0.3)  # 0.8 s after the press, 0.3 s after the key
    assert await tv.power_toggle() is True
    await _until(lambda: fake_tv.key_names() == ["Standby", "Standby"], timeout=4.0)


async def test_second_toggle_cancels_deferred_one(tv, fake_tv, monkeypatch):
    _short_cooldown(monkeypatch, cooldown=1.5)
    assert await tv.power_toggle() is True
    await asyncio.sleep(0.3)
    assert await tv.power_toggle() is True  # deferred
    await asyncio.sleep(0.3)  # past the bounce window
    assert await tv.power_toggle() is True  # cancels the deferred order
    await asyncio.sleep(1.5)
    assert fake_tv.key_names() == ["Standby"]


async def test_power_on_during_cooldown_after_power_on_does_nothing(tv, fake_tv, monkeypatch, wol_packets):
    _short_cooldown(monkeypatch)
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    assert await tv.power_on() is True
    await asyncio.sleep(0.3)
    assert await tv.power_on() is True
    await asyncio.sleep(0.8)
    assert fake_tv.key_names() == ["Standby"]


async def test_power_off_during_power_on_waits_and_cancels_confirmation(tv, fake_tv, monkeypatch, wol_packets):
    _short_cooldown(monkeypatch)
    fake_tv.power = "Standby"
    await _until(lambda: tv.state.power == "STANDBY")
    assert await tv.power_on(timeout=5.0) is True
    assert await tv.power_off() is True
    assert not tv._confirming()  # otherwise its fallback Wake-on-LAN would turn the TV back on
    await _until(lambda: fake_tv.key_names() == ["Standby", "Standby"])
    await _until(lambda: tv.state.power == "STANDBY")


# ------------------------------------------------------------------ touches
async def test_command_during_repeat_is_queued_after(device, fake_tv):
    repeat = asyncio.create_task(device.send_command("CURSOR_DOWN", repeat=5))
    await asyncio.sleep(0.2)
    await device.send_command("BACK")
    await repeat
    assert fake_tv.key_names() == ["CursorDown"] * 5 + ["Back"]


async def test_keys_not_delayed_by_listening(tv, fake_tv):
    await asyncio.sleep(0.2)  # a listen is open
    ok, elapsed = await _timed(tv.send_command("CURSOR_DOWN"))
    assert ok is True and elapsed < 0.3
