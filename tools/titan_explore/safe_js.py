"""Cautious JointSpace access for exploration.

- minimum interval between requests (2 s by default, enforced by the client);
- no automatic retries;
- every request is journaled (method, path, status, duration, response excerpt);
- HTTP errors (403, 404…) are answers to record, not exceptions;
- degradation detected (H2) → `TvWedged`: the TV was responding and no longer does, response too slow,
  or 3 consecutive 404 responses on paths that used to answer.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from intg_philips_titanos.client import PhilipsConnectionError, PhilipsJointSpaceClient
from titan_explore.record import Journal
from titan_explore.session import TvUnreachable, TvWedged

EXCERPT_LIMIT = 2000
MAX_CONSECUTIVE_404 = 3


@dataclass
class JsResponse:
    status: int
    data: Any
    duration: float

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class SafeJointSpace:
    def __init__(
        self,
        client: PhilipsJointSpaceClient,
        journal: Journal,
        *,
        interval: float = 2.0,
        slow_threshold: float = 5.0,
    ) -> None:
        self._client = client
        self._client.min_request_interval = 0.0  # spacing is handled here, outside the duration measurement
        self._journal = journal
        self.slow_threshold = slow_threshold
        self.interval = interval
        self._last_call = 0.0
        self._answered = False
        self._ok_paths: set[str] = set()
        self._consecutive_404 = 0

    @contextmanager
    def fast(self, interval: float) -> Iterator[None]:
        """Temporarily lowers the interval (trial at the macro pace), then restores it."""
        previous = self.interval
        self.interval = interval
        try:
            yield
        finally:
            self.interval = previous

    async def get(self, path: str, *, timeout: float | None = None) -> JsResponse:
        return await self._call("GET", path, None, timeout)

    async def post(
        self, path: str, payload: dict[str, Any], *, timeout: float | None = None, allow_timeout: bool = False
    ) -> JsResponse:
        """`allow_timeout`: a timeout is an expected response (long `notifychange` wait)."""
        return await self._call("POST", path, payload, timeout, allow_timeout)

    async def key(self, name: str) -> JsResponse:
        return await self.post("input/key", {"key": name})

    async def reachable(self) -> bool:
        """Does the TV respond? Never raises (used during deliberate state changes)."""
        wait = self._last_call + self.interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        start = time.monotonic()
        try:
            await self._client.get("system", retries=0, timeout=self.slow_threshold)
            ok = True
        except PhilipsConnectionError as err:
            ok = isinstance(err.__cause__, httpx.HTTPStatusError)
        self._last_call = time.monotonic()
        self._journal.log("reachable", ok=ok, duration=round(self._last_call - start, 3))
        if ok:
            self._answered = True
        return ok

    async def wake_on_lan(self, mac: str, broadcasts: list[str]) -> None:
        await self._client.wake_on_lan(mac, broadcasts)
        self._journal.log("wol", mac=mac, broadcasts=broadcasts)

    def forget_answers(self) -> None:
        """Call after a deliberate standby: a lack of response is no longer a freeze."""
        self._answered = False

    async def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        timeout: float | None,
        allow_timeout: bool = False,
    ) -> JsResponse:
        limit = timeout or self.slow_threshold
        wait = self._last_call + self.interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        start = time.monotonic()  # the measured duration only covers the exchange with the TV
        try:
            return await self._exchange(method, path, payload, limit, allow_timeout, start)
        finally:
            self._last_call = time.monotonic()

    async def _exchange(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        limit: float,
        allow_timeout: bool,
        start: float,
    ) -> JsResponse:
        try:
            if method == "GET":
                data = await self._client.get(path, retries=0, timeout=limit)
            else:
                data = await self._client.post(path, payload or {}, retries=0, timeout=limit)
            status = 200
        except PhilipsConnectionError as err:
            duration = time.monotonic() - start
            cause = err.__cause__
            if isinstance(cause, httpx.HTTPStatusError):
                status, data = cause.response.status_code, None
            elif allow_timeout and isinstance(cause, TimeoutError | httpx.TimeoutException):
                self._journal.log("js", method=method, path=path, status=0, duration=round(duration, 3), timeout=True)
                return JsResponse(0, None, duration)
            else:
                self._journal.log(
                    "js", method=method, path=path, status=None, duration=round(duration, 3), error=str(err)
                )
                if self._answered:
                    raise TvWedged(f"{method} {path}: no more response ({type(cause).__name__})") from err
                raise TvUnreachable(f"{method} {path}: no response ({type(cause).__name__})") from err
        duration = time.monotonic() - start
        self._journal.log(
            "js",
            method=method,
            path=path,
            payload=payload,
            status=status,
            duration=round(duration, 3),
            response=_excerpt(data),
        )
        self._answered = True
        self._check_404(path, status)
        return JsResponse(status, data, duration)

    def _check_404(self, path: str, status: int) -> None:
        if status == 404 and path in self._ok_paths:
            self._consecutive_404 += 1
            if self._consecutive_404 >= MAX_CONSECUTIVE_404:
                raise TvWedged(f"{MAX_CONSECUTIVE_404} consecutive 404 responses on paths that used to answer")
            return
        self._consecutive_404 = 0
        if 200 <= status < 300:
            self._ok_paths.add(path)


def _excerpt(data: Any) -> str | None:
    if data is None:
        return None
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return text[:EXCERPT_LIMIT]
