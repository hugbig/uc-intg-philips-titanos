"""Setup flow of the integration.

Conforms to the official UC doc (`doc/integration-driver/driver-setup.md`, AsyncAPI) :
failures are reported with a precise `IntegrationSetupError` code (CONNECTION_REFUSED,
TIMEOUT, AUTHORIZATION_ERROR) instead of an exception the framework would reduce to
NOT_FOUND; invalid input redisplays the form with a message.
"""

from __future__ import annotations

import asyncio
import dataclasses
import ipaddress
import logging
import re
import socket
from typing import Any

import httpx
from ucapi import IntegrationSetupError, RequestUserInput, SetupError
from ucapi_framework import BaseSetupFlow

from intg_philips_titanos.config import PhilipsConfig
from intg_philips_titanos.labels import ui_language
from intg_philips_titanos.pairing import PairingError, TvPairing

_LOG = logging.getLogger(__name__)

MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")


def _source_address(target: str) -> str | None:
    """Local IPv4 address the system would use to reach `target` (no packet is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((target, 9))  # UDP: only selects the route
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


@dataclasses.dataclass
class _PendingPairing:
    """Pairing started on the first screen, waiting for the PIN typed on the second one."""

    host: str
    mac: str
    name: str
    pairing: TvPairing


def _text_field(field_id: str, en: str, fr: str, value: str) -> dict[str, Any]:
    return {"id": field_id, "label": {"en": en, "fr": fr}, "field": {"text": {"value": value}}}


def _error_label(message: dict[str, str]) -> dict[str, Any]:
    return {"id": "error", "label": {"en": "Error", "fr": "Erreur"}, "field": {"label": {"value": message}}}


def _network_error(err: BaseException) -> SetupError:
    """UC code for a network error, walking up the chain of causes."""
    current: BaseException | None = err
    while current is not None:
        if isinstance(current, httpx.TimeoutException | asyncio.TimeoutError):
            return SetupError(error_type=IntegrationSetupError.TIMEOUT)
        if isinstance(current, httpx.TransportError | OSError):
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
        current = current.__cause__
    return SetupError(error_type=IntegrationSetupError.OTHER)


class PhilipsSetupFlow(BaseSetupFlow[PhilipsConfig]):
    """UC setup flow with add/update/remove/reset/backup/restore support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending: _PendingPairing | None = None

    # ------------------------------------------------------------------ formulaires
    def get_manual_entry_form(
        self, values: dict[str, str] | None = None, error: dict[str, str] | None = None
    ) -> RequestUserInput:
        existing = self.selected_config_entry
        defaults = {
            "name": existing.name if existing else "Philips TV",
            "host": existing.host if existing else "",
            "mac": existing.mac if existing else "",
        }
        defaults.update(values or {})
        settings = [_error_label(error)] if error else []
        settings += [
            _text_field("name", "Device Name", "Nom de l'appareil", defaults["name"]),
            _text_field("host", "TV IP Address", "Adresse IP de la TV", defaults["host"]),
            _text_field("mac", "TV MAC Address", "Adresse MAC de la TV", defaults["mac"]),
        ]
        return RequestUserInput({"en": "Philips TV Setup", "fr": "Configuration de la TV Philips"}, settings)

    def _pin_form(self, error: dict[str, str] | None = None) -> RequestUserInput:
        settings = [_error_label(error)] if error else []
        settings.append(_text_field("pin", "PIN shown on TV", "PIN affiché sur la TV", ""))
        return RequestUserInput({"en": "Enter PIN from Philips TV", "fr": "Saisir le PIN affiché sur la TV"}, settings)

    # ------------------------------------------------------------------ steps
    async def query_device(self, input_values: dict[str, Any]) -> PhilipsConfig | RequestUserInput | SetupError:
        if "pin" not in input_values:
            return await self._request_pairing(input_values)
        if self._pending is None:
            return SetupError(error_type=IntegrationSetupError.OTHER)
        return await self._verify_pin(input_values)

    async def _request_pairing(self, input_values: dict[str, Any]) -> PhilipsConfig | RequestUserInput | SetupError:
        host = str(input_values.get("host", "")).strip()
        mac = str(input_values.get("mac", "")).strip()
        name = str(input_values.get("name", "Philips TV")).strip() or "Philips TV"
        values = {"name": name, "host": host, "mac": mac}

        try:
            ipaddress.ip_address(host)
        except ValueError:
            return self.get_manual_entry_form(
                values, {"en": "Enter a valid TV IP address.", "fr": "Saisissez une adresse IP valide."}
            )
        if mac and not MAC_RE.fullmatch(mac):
            return self.get_manual_entry_form(
                values, {"en": "Enter a valid TV MAC address.", "fr": "Saisissez une adresse MAC valide."}
            )
        local_ip = _source_address(host)
        if local_ip == host:
            return self.get_manual_entry_form(
                values,
                {
                    "en": f"{host} is this device's own address. Enter the TV IP address.",
                    "fr": f"{host} est l'adresse de la Remote. Saisissez l'adresse IP de la TV.",
                },
            )

        existing = self.selected_config_entry
        if existing is not None and existing.host == host and existing.username:
            _LOG.info("Reconfiguring %s without re-pairing (same host)", host)
            return dataclasses.replace(existing, name=name, mac=mac, ui_language=await self._remote_language())

        await self._drop_pending()
        pending = _PendingPairing(host, mac, name, TvPairing(host))
        _LOG.info("Pairing with the TV %s from %s", host, local_ip)
        try:
            await pending.pairing.request_pin()
        except Exception as err:
            _LOG.exception("Pairing request to %s failed", host)
            await pending.pairing.aclose()
            return _network_error(err)
        self._pending = pending
        _LOG.info("PIN shown on the TV %s", host)
        return self._pin_form()

    async def _verify_pin(self, input_values: dict[str, Any]) -> PhilipsConfig | RequestUserInput | SetupError:
        pin = str(input_values.get("pin", "")).strip()
        if not pin.isdigit():
            return self._pin_form(
                {"en": "The PIN must contain digits only.", "fr": "Le PIN ne contient que des chiffres."}
            )

        pending = self._pending
        assert pending is not None
        try:
            credentials = await pending.pairing.confirm_pin(pin)
        except (PairingError, httpx.HTTPStatusError) as err:
            _LOG.warning("PIN refused by the TV %s: %s", pending.host, err)
            await self._drop_pending()
            return SetupError(error_type=IntegrationSetupError.AUTHORIZATION_ERROR)
        except Exception as err:
            _LOG.exception("PIN confirmation with %s failed", pending.host)
            await self._drop_pending()
            return _network_error(err)

        config = PhilipsConfig(
            identifier=f"philips_{pending.host.replace('.', '_')}",
            name=pending.name,
            host=pending.host,
            mac=pending.mac,
            api_version=6,
            username=credentials.username,
            password=credentials.password,
            secured_transport=credentials.secured_transport,
            poll_interval=3,
            ui_language=await self._remote_language(),
        )
        existing = self.selected_config_entry
        if existing is not None:
            # Reconfiguration with a new IP: keep the identifier (hence the entities and the
            # activities that use them) and the Wake-on-LAN broadcast address.
            config.identifier = existing.identifier
            config.wol_broadcast = existing.wol_broadcast
        _LOG.info("Paired with the TV %s (HTTPS: %s)", pending.host, credentials.secured_transport)
        await self._drop_pending()
        return config

    async def _remote_language(self) -> str:
        """Language of the pages (`fr` or `en`) from the connected Remote; English if unreadable.

        `get_localization_cfg` message of the UC Integration API (`language_code` field, e.g. `fr_FR`).
        """
        for websocket in self.driver.api.clients:
            try:
                settings = await self.driver.api.get_localization_cfg(websocket, timeout=3.0)
            except Exception:
                _LOG.debug("Remote localization unavailable", exc_info=True)
                continue
            if isinstance(settings, dict) and settings.get("language_code"):
                return ui_language(settings["language_code"])
        return "en"

    async def get_additional_configuration_screen(
        self, device_config: PhilipsConfig, previous_input: dict[str, Any]
    ) -> RequestUserInput | None:
        """No extra screen: the HDMI configuration disappeared with v0.11.0."""
        return None

    async def _drop_pending(self) -> None:
        """Forget the pairing in progress and close its connection."""
        pending, self._pending = self._pending, None
        if pending is None:
            return
        try:
            await pending.pairing.aclose()
        except Exception:
            _LOG.debug("Closing the pairing connection failed", exc_info=True)
