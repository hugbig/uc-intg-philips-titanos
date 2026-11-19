from __future__ import annotations

import asyncio
import contextlib
import logging

from ucapi_framework import PollingDevice

from intg_philips_titanos.ambilight import AMBILIGHT_COMMANDS, AmbiMemory, apply_ambilight
from intg_philips_titanos.client import (
    LISTEN_TIMEOUT,
    UNCHANGED,
    PhilipsConnectionError,
    PhilipsJointSpaceClient,
    TvState,
)
from intg_philips_titanos.commands import (
    DEFAULT_REPEAT_DELAY,
    HOLD_INTERVAL,
    KEY_MAP,
    MAX_REPEAT,
    REPEATABLE_ON_HOLD,
)
from intg_philips_titanos.config import PhilipsConfig

_LOG = logging.getLogger(__name__)

POWER_ON_TIMEOUT = 20.0
POWER_ON_POLL = 1.0
WOL_SCHEDULE = (0.0, 2.0, 5.0)
# After the Standby key, notifychange still reports the old state for ~2 s (capture 2026-11-18):
# during this delay we keep the expected state.
STANDBY_GRACE = 6.0
# A second ON/OFF press this soon after the previous one is a bounce, ignored. Counted from the press:
# the TV may take 2.5 s to accept the key (Remote log of 2026-11-19, 18:16).
BOUNCE_WINDOW = 2.0
# The TV does not like chained on/off cycles (acceptance test 2026-11-18): after a Standby key, a
# new power order waits for the end of this rest (the Remote gets its answer immediately).
POWER_COOLDOWN = 15.0
# After a Standby key, the TV may not answer a listen opened while it boots (Remote log of
# 2026-11-19, 14:29: 26 s without answer while the TV was already on). Until it answers, short
# listens are repeated, and the state targeted by the key is shown, for at most `CONFIRM_WINDOW` s.
CONFIRM_WINDOW = 30.0
CONFIRM_LISTEN_TIMEOUT = 2.5
# Wake-on-LAN as a fallback if the TV is not on this long after the Standby key (deep standby).
WOL_AFTER_KEY = 5.0


class PhilipsDevice(PollingDevice):
    def __init__(self, device_config: PhilipsConfig, *, client: PhilipsJointSpaceClient | None = None, **kwargs):
        super().__init__(device_config, poll_interval=device_config.poll_interval, **kwargs)
        self._config = device_config
        self._client = client or PhilipsJointSpaceClient(
            device_config.host,
            device_config.api_version,
            device_config.username,
            device_config.password,
            verify_tls=False,
            secured_transport=device_config.secured_transport,
        )
        self._state = TvState()
        # Serializes sends: a key repeat or an Ambilight sequence is
        # never cut by another press, and polling does not interleave.
        self._command_lock = asyncio.Lock()
        self._power_lock = asyncio.Lock()
        self._expected_power: str | None = None
        self._last_switch = float("-inf")  # time of the last Standby key
        self._last_press = float("-inf")  # time of the last ON/OFF press acted upon
        self._deferred: asyncio.Task | None = None  # power order deferred after the rest
        # Power-on confirmation in the background: the Remote gets its answer as soon as the order is sent.
        self._power_task: asyncio.Task | None = None
        # Last power state reported by the TV itself (never the state assumed after
        # a key): notifychange answers "nothing new" as long as it does not change.
        self._reported_power: str | None = None
        # One connection at a time: the Remote asks for several at once when reconnecting,
        # and the framework does not protect the wait for the first listen (3 loops → 503 in a row).
        self._connect_lock = asyncio.Lock()
        # Restart of the listen after a Standby key: the listen opened before may never
        # report the change (Remote log of 2026-11-19: power-on seen 40 s later).
        self._relisten = asyncio.Event()
        # Next listen with no known state (the TV answers immediately) until a real answer;
        # `_reported_power` remains the fallback if the TV refuses the listen (503).
        self._listen_fresh = False
        # Ambilight mode from before switch-off, restored by the toggle (lost when the driver restarts).
        self._ambilight_memory = AmbiMemory()

    @property
    def identifier(self):
        return self._config.identifier

    @property
    def name(self):
        return self._config.name

    @property
    def address(self):
        return self._config.host

    @property
    def log_id(self):
        return f"{self.name} ({self.address})"

    @property
    def state(self):
        return self._state

    def set_poll_interval(self, seconds: float) -> None:
        """Pause between two listens (`PollingDevice` reads it before each wait)."""
        self._poll_interval = seconds

    async def connect(self) -> bool:
        async with self._connect_lock:
            return await super().connect()

    async def establish_connection(self):
        await self._client.start()
        await self.poll_device()
        return self._client

    async def disconnect(self):
        self.cancel_power_task()
        self._cancel_deferred()
        await super().disconnect()
        await self._client.close()

    async def poll_device(self):
        """One state listen (long-poll), restarted by the framework's polling loop.

        One listen at a time: the TV refuses the next ones (503) as long as a request stays
        open on its side. Keys are sent during the listen (the client does not serialize it).
        """
        state = None
        while state is None:
            state = await self._listen_once()
        self._state = self._apply_grace(self._merge(state))
        self.push_update()

    async def _listen_once(self) -> TvState | None:
        """One listen; None if it was abandoned for a restart (`_restart_listening`)."""
        self._relisten.clear()
        known = None if self._listen_fresh else self._reported_power
        timeout = CONFIRM_LISTEN_TIMEOUT if self._awaiting_answer() else LISTEN_TIMEOUT
        listen = asyncio.create_task(self._client.listen(known, timeout))
        restart = asyncio.create_task(self._relisten.wait())
        try:
            await asyncio.wait({listen, restart}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            restart.cancel()
            if not listen.done():
                listen.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen
        if listen.cancelled() or self._relisten.is_set():
            # Restart requested, even if the listen answered at the same instant: its answer
            # predates the key.
            _LOG.info("[%s] Listening restarted after a Standby key", self.log_id)
            return None
        state = listen.result()
        if state.online and state.power in ("ON", "STANDBY"):
            self._listen_fresh = False
        return state

    def _restart_listening(self) -> None:
        """After a Standby key: new listen with no known state, to which the TV answers
        immediately with its real state, instead of relying on the listen opened before the key."""
        self._listen_fresh = True
        self._relisten.set()

    # ------------------------------------------------------------------ power
    def _merge(self, state: TvState) -> TvState:
        """"Nothing new" → last state reported by the TV (never the assumed state)."""
        if not state.online:
            self._reported_power = None
            return state
        if state.power == UNCHANGED:
            return TvState(online=True, power=self._reported_power or "UNKNOWN")
        self._reported_power = state.power if state.power in ("ON", "STANDBY") else None
        return state

    def _confirming(self) -> bool:
        return self._power_task is not None and not self._power_task.done()

    def cancel_power_task(self) -> None:
        """Stop the ongoing power-on confirmation (new command or disconnection)."""
        if self._confirming():
            self._power_task.cancel()
        self._power_task = None

    def _cancel_deferred(self) -> None:
        if self._deferred is not None and not self._deferred.done():
            self._deferred.cancel()
        self._deferred = None

    def _since_switch(self) -> float:
        return asyncio.get_running_loop().time() - self._last_switch

    def _switching(self) -> bool:
        """A Standby key was sent less than `STANDBY_GRACE` s ago."""
        return self._since_switch() < STANDBY_GRACE

    def _cooling(self) -> bool:
        return self._since_switch() < POWER_COOLDOWN

    def _awaiting_answer(self) -> bool:
        """A Standby key left and the TV has not answered since (it may be booting silently)."""
        return self._listen_fresh and self._since_switch() < CONFIRM_WINDOW

    def _in_grace(self) -> bool:
        return self._expected_power is not None and (self._switching() or self._awaiting_answer())

    def _apply_grace(self, state: TvState) -> TvState:
        """During the grace period, a read contradicting the last Standby key is stale."""
        if self._in_grace() and state.online and state.power != self._expected_power:
            return TvState(online=True, power=self._expected_power)
        return state

    def _current_power(self) -> str:
        """Target state: the one expected after the last key during the rest, otherwise the known state."""
        if self._cooling() and self._expected_power is not None:
            return self._expected_power
        return self._state.power if self._state.online else "OFFLINE"

    def _defer(self, target: str) -> None:
        """Defer a power order to the end of the rest; replaces the one already deferred."""
        self._cancel_deferred()
        delay = max(0.0, POWER_COOLDOWN - self._since_switch())
        _LOG.info("[%s] Power %s deferred %.0f s (TV still settling)", self.log_id, target, delay)
        self._deferred = asyncio.create_task(self._run_deferred(target, delay))

    async def _run_deferred(self, target: str, delay: float) -> None:
        await asyncio.sleep(delay)
        self._deferred = None  # power_on/power_off cancel the deferred order: not this one
        if target == "ON":
            await self.power_on()
        else:
            await self.power_off()

    async def _send_standby(self, expected: str | None) -> None:
        """Standby key (on ↔ standby toggle); raises PhilipsConnectionError.

        `expected`: state expected after the key, or None if the initial state is unknown.
        """
        async with self._command_lock:
            await self._client.send_key("Standby")
        self._expected_power = expected
        self._last_switch = asyncio.get_running_loop().time()
        self._restart_listening()

    async def _try_standby_key(self) -> bool:
        try:
            await self._send_standby("ON")
        except PhilipsConnectionError as err:
            _LOG.warning("[%s] Standby key failed: %s", self.log_id, err)
            return False
        _LOG.info("[%s] Standby key sent to wake the TV", self.log_id)
        return True

    def _wol_broadcasts(self) -> list[str]:
        subnet = self._config.wol_broadcast or PhilipsJointSpaceClient.subnet_broadcast(self._config.host)
        return ["255.255.255.255", subnet]

    async def _send_wol(self) -> bool:
        if not self._config.mac:
            return False
        try:
            await self._client.wake_on_lan(self._config.mac, self._wol_broadcasts())
        except (OSError, ValueError) as err:
            _LOG.error("[%s] Wake-on-LAN failed: %s", self.log_id, err)
            return False
        _LOG.info("[%s] Wake-on-LAN sent", self.log_id)
        return True

    async def power_on(self, timeout: float = POWER_ON_TIMEOUT) -> bool:
        """Turn the TV on; True as soon as the order is sent, confirmation follows in the background.

        The state comes from the permanent listen:
        - on: nothing to do;
        - standby: a single Standby key (it is a toggle), then Wake-on-LAN as a fallback
          if it is not on `WOL_AFTER_KEY` s later;
        - offline or unknown state: Wake-on-LAN (a Standby key would switch off a TV that is on),
          repeated at 2 and 5 s; if it comes back in standby, a single Standby key.
        During the rest after a Standby key, the order is deferred (or useless).
        False only if no order could be sent. `POST powerstate` is not used.
        """
        self.cancel_power_task()
        if self._cooling():
            if self._current_power() != "ON":
                self._defer("ON")
            else:
                self._cancel_deferred()
            return True
        self._cancel_deferred()
        async with self._power_lock:
            self.cancel_power_task()
            state = self._state
            if state.is_on:
                return True
            if not self._config.mac:
                _LOG.warning("[%s] Wake-on-LAN unavailable: no TV MAC configured", self.log_id)
            key_sent = state.is_standby and await self._try_standby_key()
            if not key_sent and not await self._send_wol():
                _LOG.warning("[%s] Power on impossible: no Standby key nor Wake-on-LAN sent", self.log_id)
                return False
            self._power_task = asyncio.create_task(self._confirm_power_on(timeout, key_sent))
            return True

    async def _confirm_power_on(self, timeout: float, key_sent: bool) -> None:
        """Follow the listened state until power-on; Standby key if the TV returns to standby;
        fallback Wake-on-LAN. Sends no read: the permanent listen takes care of it."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        deadline = start + timeout
        if key_sent:
            wol_at = [WOL_AFTER_KEY + delay for delay in WOL_SCHEDULE]
        else:
            wol_at = [delay for delay in WOL_SCHEDULE if delay > 0]  # the first one is already sent
        while loop.time() < deadline:
            await asyncio.sleep(min(POWER_ON_POLL, max(0.0, deadline - loop.time())))
            online, reported = self._state.online, self._reported_power
            if online and reported == "ON":
                _LOG.info("[%s] TV is on", self.log_id)
                return
            elapsed = loop.time() - start
            if online and reported == "STANDBY" and not key_sent:
                key_sent = await self._try_standby_key()
                if key_sent:
                    wol_at = [elapsed + WOL_AFTER_KEY + delay for delay in WOL_SCHEDULE]
            while wol_at and wol_at[0] <= elapsed:
                wol_at.pop(0)
                await self._send_wol()
        _LOG.warning("[%s] TV did not confirm power on within %.0f s", self.log_id, timeout)
        self._expected_power = None  # stop showing "on" without confirmation
        online = self._state.online
        self._state = TvState(online=online, power=(self._reported_power or "UNKNOWN") if online else "UNKNOWN")
        self.push_update()

    async def power_off(self) -> bool:
        """Put the TV in standby: Standby key only if the TV says it is on."""
        self.cancel_power_task()
        if self._cooling():
            if self._current_power() == "ON":
                self._defer("STANDBY")
            else:
                self._cancel_deferred()
            return True
        self._cancel_deferred()
        async with self._power_lock:
            self.cancel_power_task()
            state = self._state
            if not state.online or state.power == "STANDBY":
                return True
            if state.power != "ON":
                _LOG.warning("[%s] Power state unknown: Standby not sent (it would toggle blindly)", self.log_id)
                return False
            try:
                await self._send_standby("STANDBY")
            except PhilipsConnectionError as err:
                _LOG.error("[%s] Network error sending Standby: %s", self.log_id, err)
                return False
            self._state = TvState(online=True, power="STANDBY")
            self.push_update()
            _LOG.info("[%s] Standby accepted", self.log_id)
            return True

    async def power_toggle(self) -> bool:
        """ON/OFF button, based on the listened state.

        - second press within `BOUNCE_WINDOW` s of the previous one, or while a key is being sent:
          bounce, ignored;
        - during the rest that follows a Standby key: the opposite order is deferred; a new press
          cancels it;
        - known state: off if on, otherwise on;
        - TV reachable but state unreadable: Standby key as is, like the Philips remote.
        """
        now = asyncio.get_running_loop().time()
        if now - self._last_press < BOUNCE_WINDOW or self._power_lock.locked():
            _LOG.info("[%s] Power toggle ignored: TV still switching", self.log_id)
            return True
        self._last_press = now
        if self._cooling():
            if self._deferred is not None and not self._deferred.done():
                self._cancel_deferred()
                _LOG.info("[%s] Deferred power order cancelled", self.log_id)
                return True
            self._defer("STANDBY" if self._current_power() == "ON" else "ON")
            return True
        state = self._state
        if state.is_on:
            return await self.power_off()
        if state.online and not state.is_standby:
            self.cancel_power_task()
            async with self._power_lock:
                await self._send_standby(None)
            _LOG.info("[%s] Power state unknown: Standby key sent as a toggle", self.log_id)
            return True
        return await self.power_on()

    async def send_command(self, command: str, *, repeat: int = 1, delay_ms: int = 0, hold_ms: int = 0) -> bool:
        """Send a Remote command to the TV.

        `repeat`, `delay` (ms) and `hold` (ms) follow the UC doc of `send_cmd`: `hold` is a
        long press; Titan OS has none through the API, so it is only simulated by repetition
        for the keys of `REPEATABLE_ON_HOLD`. Returns False for an unknown command;
        raises `PhilipsConnectionError` if the TV is unreachable.
        """
        if command == "POWER_TOGGLE":
            return await self.power_toggle()
        if command == "POWER_ON":
            return await self.power_on()
        if command == "POWER_OFF":
            return await self.power_off()
        if command in AMBILIGHT_COMMANDS:
            async with self._command_lock:
                return await apply_ambilight(self._client, command, self._ambilight_memory)

        key = KEY_MAP.get(command)
        if key is None:
            _LOG.warning("[%s] Unknown command: %s", self.log_id, command)
            return False

        delay = delay_ms / 1000 if delay_ms > 0 else DEFAULT_REPEAT_DELAY
        if hold_ms > 0 and command in REPEATABLE_ON_HOLD:
            count = round(hold_ms / 1000 / HOLD_INTERVAL)
            delay = HOLD_INTERVAL
        elif hold_ms > 0:
            _LOG.debug("[%s] No long press on Titan OS; sending %s once", self.log_id, command)
            count = 1
        else:
            count = repeat
        count = max(1, min(count, MAX_REPEAT))

        async with self._command_lock:
            for index in range(count):
                if index:
                    await asyncio.sleep(delay)
                await self._client.send_key(key)
        _LOG.info("[%s] Command sent: %s -> %s x%s", self.log_id, command, key, count)
        return True
