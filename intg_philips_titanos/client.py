"""JointSpace API 6 HTTP client for Philips Titan OS TVs.

Reliability rules:
- a key (`POST input/key`) is never resent automatically: a retry after a
  timeout can produce a double press if the TV had received the first one;
- all requests are serialized and spaced by at least `min_request_interval`
  seconds (the Titan OS HTTPS server can hang if requests are chained);
- each request has a bounded total duration, including when the TV stops answering.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)

# Connection bounded shorter than the request: an unreachable TV fails at connection (offline),
# a slow TV times out once connected (unknown state).
CONNECT_TIMEOUT = 2.0
_POWER_VALUES = {"On": "ON", "Standby": "STANDBY"}
# notifychange with no power news: to be replaced by the last reported state (device).
UNCHANGED = "UNCHANGED"
# Listening (long-poll) like the Philips app: the TV keeps notifychange open as long as the state sent
# is its own. Only one listen at a time: an abandoned request stays pending on the TV side and the
# next ones get 503 (Remote log of 2026-11-18).
LISTEN_TIMEOUT = 40.0
_TV_POWER = {"ON": "On", "STANDBY": "Standby"}
_TIMEOUT_ERRORS = (TimeoutError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)


@dataclass(slots=True)
class TvState:
    online: bool = False
    power: str = "UNKNOWN"  # ON, STANDBY or UNKNOWN
    source: str | None = None
    channel: str | None = None
    channel_name: str | None = None
    app: str | None = None

    @property
    def is_on(self) -> bool:
        """TV reachable and on according to the TV itself (single rule for the entities and the toggle)."""
        return self.online and self.power == "ON"

    @property
    def is_standby(self) -> bool:
        """TV reachable but in standby (UC doc media_player STANDBY state)."""
        return self.online and self.power == "STANDBY"


class PhilipsConnectionError(RuntimeError):
    pass


class PhilipsTimeoutError(PhilipsConnectionError):
    """The TV accepted the connection but did not answer in time."""


class PhilipsHttpStatusError(PhilipsConnectionError):
    """The TV answered, but with an HTTP error status (4xx/5xx)."""


class PhilipsJointSpaceClient:
    def __init__(
        self,
        host: str,
        api_version: int = 6,
        username: str = "",
        password: str = "",
        verify_tls: bool = False,
        timeout: float = 5.0,
        secured_transport: bool = True,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        min_request_interval: float = 0.12,
    ) -> None:
        self.host, self.api_version = host, api_version
        self.username, self.password = username, password
        self.verify_tls, self.timeout = verify_tls, timeout
        self.secured_transport = secured_transport
        self.min_request_interval = min_request_interval
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._io_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._rebuild_base()

    def _rebuild_base(self) -> None:
        protocol = "https" if self.secured_transport else "http"
        port = 1926 if self.secured_transport else 1925
        self.base = f"{protocol}://{self.host}:{port}/{self.api_version}"

    async def start(self) -> None:
        if self._client is not None:
            return
        auth = httpx.DigestAuth(self.username, self.password) if self.username else None
        self._client = httpx.AsyncClient(
            auth=auth,
            verify=self.verify_tls,
            timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, CONNECT_TIMEOUT)),
            follow_redirects=True,
            trust_env=False,
            transport=self._transport,
        )
        _LOG.info(
            "Philips HTTP client created: base=%s secured=%s auth=%s", self.base, self.secured_transport, bool(auth)
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _send_once(
        self, method: str, url: str, payload: dict[str, Any] | None, timeout: float, *, exclusive: bool = True
    ) -> Any:
        """One request, spaced from the others by `min_request_interval`.

        `exclusive=False` (listen): the request only waits for its start turn and does not block
        keys while the TV keeps it open.
        """
        assert self._client is not None
        request_timeout = httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT))
        if exclusive:
            async with self._io_lock:
                await self._space_requests()
                try:
                    response = await asyncio.wait_for(
                        self._client.request(method, url, json=payload, timeout=request_timeout), timeout
                    )
                finally:
                    self._last_request_at = time.monotonic()
        else:
            async with self._io_lock:
                await self._space_requests()
                self._last_request_at = time.monotonic()
            response = await asyncio.wait_for(
                self._client.request(method, url, json=payload, timeout=request_timeout), timeout
            )
        response.raise_for_status()
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    async def _space_requests(self) -> None:
        wait = self._last_request_at + self.min_request_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        retries: int,
        timeout: float | None = None,
        exclusive: bool = True,
    ) -> Any:
        await self.start()
        url = f"{self.base}/{endpoint.lstrip('/')}"
        total_timeout = timeout or self.timeout
        last_error: Exception | None = None
        for attempt in range(1, retries + 2):
            try:
                _LOG.debug("Philips request attempt=%s method=%s url=%s", attempt, method, url)
                return await self._send_once(method, url, payload, total_timeout, exclusive=exclusive)
            except (TimeoutError, httpx.HTTPError, OSError) as err:
                last_error = err
                _LOG.debug(
                    "Philips request failed attempt=%s/%s type=%s url=%s error=%s",
                    attempt, retries + 1, type(err).__name__, url, err,
                )
                if attempt <= retries:
                    await asyncio.sleep(0.4 * attempt)
        error: type[PhilipsConnectionError] = PhilipsConnectionError
        if isinstance(last_error, _TIMEOUT_ERRORS):
            error = PhilipsTimeoutError
        elif isinstance(last_error, httpx.HTTPStatusError):
            error = PhilipsHttpStatusError
        raise error(
            f"{method} {url} failed after {retries + 1} attempts: {type(last_error).__name__}: {last_error}"
        ) from last_error

    async def get(self, endpoint: str, *, retries: int = 2, timeout: float | None = None) -> Any:
        return await self._request("GET", endpoint, retries=retries, timeout=timeout)

    async def post(
        self, endpoint: str, payload: dict[str, Any], *, retries: int = 0, timeout: float | None = None
    ) -> Any:
        return await self._request("POST", endpoint, payload, retries=retries, timeout=timeout)

    async def send_key(self, key: str) -> None:
        await self.post("input/key", {"key": key}, retries=0)

    @staticmethod
    def subnet_broadcast(host: str, prefix: int = 24) -> str:
        return str(ipaddress.ip_network(f"{host}/{prefix}", strict=False).broadcast_address)

    async def wake_on_lan(self, mac: str, broadcasts: list[str]) -> None:
        clean = mac.replace(":", "").replace("-", "")
        if len(clean) != 12:
            raise ValueError("Invalid MAC address")
        packet = bytes.fromhex("FF" * 6 + clean * 16)

        def _send() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                for address in dict.fromkeys(broadcasts):
                    sock.sendto(packet, (address, 9))

        await asyncio.to_thread(_send)

    async def listen(self, known_power: str | None, timeout: float = LISTEN_TIMEOUT) -> TvState:
        """Listen to the power state like the Philips app (`notifychange` long-poll).

        `known_power` (ON/STANDBY) is sent to the TV: it answers as soon as its state differs,
        otherwise it keeps the request open. With no known state, it answers immediately.
        - answer with `powerstate`: new state;
        - no answer within `LISTEN_TIMEOUT`, answer without `powerstate`, or 503: `UNCHANGED`;
        - other HTTP error: online, unknown state; TV unreachable: offline.
        """
        tv_power = _TV_POWER.get(known_power or "")
        body = {"notification": {"powerstate": {"powerstate": tv_power} if tv_power else {}}}
        start = time.monotonic()
        try:
            answer = await self._request(
                "POST", "notifychange", body, retries=0, timeout=timeout, exclusive=False
            )
        except PhilipsTimeoutError:
            _LOG.info("notifychange: no change in %.0f s", time.monotonic() - start)
            return TvState(online=True, power=UNCHANGED)
        except PhilipsHttpStatusError as err:
            cause = err.__cause__
            status = cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else None
            _LOG.info("notifychange: HTTP %s after %.1f s", status, time.monotonic() - start)
            return TvState(online=True, power=UNCHANGED if status == 503 else "UNKNOWN")
        except PhilipsConnectionError as err:
            _LOG.info("notifychange: TV unreachable (%s)", type(err.__cause__).__name__)
            return TvState()
        elapsed = time.monotonic() - start
        if not isinstance(answer, dict) or "powerstate" not in answer:
            keys = sorted(answer) if isinstance(answer, dict) else type(answer).__name__
            _LOG.info("notifychange: answer after %.1f s without powerstate (%s)", elapsed, keys)
            return TvState(online=True, power=UNCHANGED)
        power = answer.get("powerstate")
        value = power.get("powerstate") if isinstance(power, dict) else None
        power_value = _POWER_VALUES.get(value, "UNKNOWN") if isinstance(value, str) else "UNKNOWN"
        _LOG.info("notifychange: powerstate=%s after %.1f s (known %s)", value, elapsed, tv_power)
        return TvState(online=True, power=power_value)
