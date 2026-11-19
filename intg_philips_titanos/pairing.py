"""Pairing with a Philips TV over JointSpace API 6 (digest-auth pairing).

Protocol, as documented by the community (pylips, ha-philipsjs) and observed on Titan OS:

1. `GET /6/system` locates the API: HTTPS on port 1926, otherwise HTTP on port 1925.
   `featuring.systemfeatures.secured_transport` says whether the API must be used over HTTPS.
2. `POST /6/pair/request` with the requested scopes and a description of this device; the TV shows
   a PIN and answers with a `timestamp` and an `auth_key`.
3. `POST /6/pair/grant` with digest auth (device id, `auth_key`) and a signature:
   base64(HMAC-SHA1(shared secret, timestamp + PIN)). On success, (device id, `auth_key`)
   are the credentials for every later request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)

# Shared secret of the JointSpace pairing protocol (public, identical on every Philips TV).
PAIRING_SECRET = base64.b64decode(
    "ZmVay1EQVFOaZhwQ4Kv81ypLAZNczV9sG4KkseXWn1NEk6cXmPKO/MCa9sryslvLCFMnNe4Z4CPXzToowvhHvA=="
)
PORTS = {"https": 1926, "http": 1925}
SCOPES = ["read", "write", "control"]


def pairing_signature(timestamp: str, pin: str) -> str:
    """Signature sent with `pair/grant`."""
    digest = hmac.new(PAIRING_SECRET, f"{timestamp}{pin}".encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


class PairingError(RuntimeError):
    """The TV refused a pairing step or answered something unreadable."""


@dataclass(frozen=True)
class PairingCredentials:
    username: str
    password: str
    secured_transport: bool


def _is_true(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


class TvPairing:
    """One pairing attempt: `request_pin()` makes the TV show a PIN, `confirm_pin()` finishes it."""

    def __init__(self, host: str, *, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None):
        self.host = host
        self.scheme = "https"
        self._http = httpx.AsyncClient(
            verify=False,  # the TV uses a self-signed certificate
            timeout=httpx.Timeout(timeout, connect=5.0),
            follow_redirects=True,
            trust_env=False,
            headers={"Accept": "application/json"},
            transport=transport,
        )
        self._device: dict[str, str] | None = None
        self._timestamp: Any = None
        self._auth_key: str | None = None

    def _url(self, endpoint: str, scheme: str | None = None) -> str:
        scheme = scheme or self.scheme
        return f"{scheme}://{self.host}:{PORTS[scheme]}/6/{endpoint}"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _locate_api(self) -> dict[str, Any]:
        """Read `/system` over HTTPS, then HTTP; select the scheme the API must be used with."""
        failures: list[str] = []
        last_error: Exception | None = None
        for scheme in ("https", "http"):
            try:
                response = await self._http.get(self._url("system", scheme))
                response.raise_for_status()
                system = response.json()
                if not isinstance(system, dict):
                    raise PairingError(f"/system is not an object: {type(system).__name__}")
            except Exception as err:  # noqa: BLE001 - every failure is reported, then the next scheme is tried
                last_error = err
                failures.append(f"{scheme}: {type(err).__name__}: {err}")
                _LOG.warning("Philips /system unreachable over %s: %s", scheme, err)
                continue
            features = (system.get("featuring") or {}).get("systemfeatures") or {}
            self.scheme = "https" if _is_true(features.get("secured_transport")) else scheme
            _LOG.info(
                "Philips TV found: name=%s api=%s pairing=%s scheme=%s",
                system.get("name"), system.get("api_version"), features.get("pairing_type"), self.scheme,
            )
            return system
        raise PairingError("Philips /system unreachable. " + " | ".join(failures)) from last_error

    async def _post(self, endpoint: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        response = await self._http.post(self._url(endpoint), json=payload, **kwargs)
        _LOG.info("Philips %s: HTTP %s", endpoint, response.status_code)
        response.raise_for_status()
        try:
            answer = response.json()
        except ValueError as err:
            raise PairingError(f"{endpoint}: not JSON: {response.text[:300]}") from err
        if not isinstance(answer, dict) or answer.get("error_id") != "SUCCESS":
            raise PairingError(f"{endpoint} refused: {answer}")
        return answer

    async def request_pin(self) -> None:
        """Locate the API and ask the TV to show a PIN."""
        system = await self._locate_api()
        self._device = {
            "device_name": "remote3",
            "device_os": "Linux",
            "type": "native",
            "id": secrets.token_hex(16),
            "app_id": "unfolded_circle",
            "app_name": "Unfolded Circle Remote 3",
        }
        access: dict[str, Any] = {"scope": list(SCOPES)}
        if system.get("featuring"):
            access["featuring"] = system["featuring"]
        answer = await self._post("pair/request", {"access": access, "device": self._device})
        self._timestamp, self._auth_key = answer["timestamp"], str(answer["auth_key"])

    async def confirm_pin(self, pin: str) -> PairingCredentials:
        """Send the PIN typed by the user; return the credentials for the API."""
        if self._device is None or self._auth_key is None:
            raise PairingError("confirm_pin() called before request_pin()")
        username = self._device["id"]
        auth = {
            "auth_appId": "1",
            "auth_timestamp": self._timestamp,
            "auth_signature": pairing_signature(str(self._timestamp), pin),
            "pin": pin,
        }
        await self._post(
            "pair/grant", {"auth": auth, "device": self._device}, auth=httpx.DigestAuth(username, self._auth_key)
        )
        return PairingCredentials(username, self._auth_key, secured_transport=self.scheme == "https")
