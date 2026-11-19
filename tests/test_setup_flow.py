from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from ucapi import IntegrationSetupError, RequestUserInput, SetupError
from ucapi_framework import BaseConfigManager

from intg_philips_titanos import pairing, setup_flow
from intg_philips_titanos.setup_flow import PhilipsSetupFlow
from tests.fake_tv import DEV_PIN

TV_IP = "192.168.1.42"


@pytest.fixture
def manager(tmp_path):
    return BaseConfigManager(str(tmp_path), config_class=setup_flow.PhilipsConfig)


@pytest.fixture
def flow(manager, fake_tv, monkeypatch):
    fake_tv.offline_hang = 0.01
    created: list = []

    def _factory(host):
        client = pairing.TvPairing(host, transport=fake_tv.transport())
        created.append(client)
        return client

    monkeypatch.setattr(setup_flow, "TvPairing", _factory)
    monkeypatch.setattr(setup_flow, "_source_address", lambda target: "192.168.1.10")
    instance = PhilipsSetupFlow(manager, driver=MagicMock())
    instance.created_pairing_clients = created
    return instance


async def _pair(flow, pin=DEV_PIN, host=TV_IP):
    form = await flow.query_device({"name": "TV salon", "host": host, "mac": "AA:BB:CC:DD:EE:FF"})
    assert isinstance(form, RequestUserInput)
    return await flow.query_device({"pin": pin})


async def test_pairing_against_fake_tv(flow):
    config = await _pair(flow)
    assert config.host == TV_IP
    assert config.username and config.password


def _remote(answer=None, error=None, clients=("ws",)):
    """Simulated UC API: a connected Remote that answers (or not) get_localization_cfg."""
    ask = AsyncMock(return_value=answer, side_effect=error)
    return SimpleNamespace(clients=set(clients), get_localization_cfg=ask)


@pytest.mark.parametrize(
    ("api", "expected"),
    [
        (_remote(clients=()), "en"),
        (_remote(error=TimeoutError()), "en"),
        (_remote(answer=None), "en"),
        (_remote(answer={"language_code": "de_DE"}), "en"),
        (_remote(answer={"language_code": "fr_FR"}), "fr"),
        (_remote(answer={"language_code": "fr"}), "fr"),
    ],
)
async def test_remote_language(flow, api, expected):
    flow.driver.api = api
    assert await flow._remote_language() == expected


async def test_pairing_stores_remote_language(flow):
    flow.driver.api = _remote(answer={"language_code": "fr_FR"})
    config = await _pair(flow)
    assert config.ui_language == "fr"


async def test_reconfigure_rereads_language(flow, manager, tv_config):
    existing = replace(tv_config, host=TV_IP, ui_language="fr")
    manager.add_or_update(existing)
    flow._selected_config_id = existing.identifier
    flow.driver.api = _remote(answer={"language_code": "en_US"})
    result = await flow.query_device({"name": "TV salon", "host": TV_IP, "mac": existing.mac})
    assert result.ui_language == "en"


async def test_setup_has_no_hdmi_screen(flow, tv_config):
    assert await flow.get_additional_configuration_screen(tv_config, {}) is None


async def test_update_keeps_credentials_without_pairing(flow, manager, tv_config):
    existing = replace(tv_config, host=TV_IP, identifier="philips_192_168_1_42")
    manager.add_or_update(existing)
    flow._selected_config_id = existing.identifier

    form = flow.get_manual_entry_form()
    assert {"id": "host", "value": TV_IP} in [
        {"id": s["id"], "value": s["field"]["text"]["value"]} for s in form.settings if "text" in s["field"]
    ]

    result = await flow.query_device({"name": "TV salon", "host": TV_IP, "mac": existing.mac})
    assert flow.created_pairing_clients == []
    assert (result.username, result.password) == (existing.username, existing.password)


async def test_update_with_new_ip_requires_pairing(flow, manager, tv_config):
    manager.add_or_update(tv_config)
    flow._selected_config_id = tv_config.identifier
    result = await flow.query_device({"name": "TV", "host": "192.168.1.99", "mac": tv_config.mac})
    assert isinstance(result, RequestUserInput)
    assert len(flow.created_pairing_clients) == 1


async def test_unreachable_tv_is_connection_refused(flow, fake_tv):
    fake_tv.online = False
    fake_tv.offline_exception = httpx.ConnectError
    result = await flow.query_device({"name": "TV", "host": TV_IP, "mac": ""})
    assert result == SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)


async def test_timeout_is_reported_as_timeout(flow, fake_tv):
    fake_tv.online = False
    fake_tv.offline_exception = httpx.ConnectTimeout
    result = await flow.query_device({"name": "TV", "host": TV_IP, "mac": ""})
    assert result == SetupError(error_type=IntegrationSetupError.TIMEOUT)


async def test_wrong_pin_is_authorization_error(flow):
    result = await _pair(flow, pin="9999")
    assert result == SetupError(error_type=IntegrationSetupError.AUTHORIZATION_ERROR)


async def test_invalid_ip_redisplays_form(flow):
    result = await flow.query_device({"name": "TV", "host": "pas-une-ip", "mac": ""})
    assert isinstance(result, RequestUserInput)
    assert flow.created_pairing_clients == []


async def test_update_with_new_ip_keeps_identifier(flow, manager, tv_config):
    manager.add_or_update(tv_config)
    flow._selected_config_id = tv_config.identifier
    form = await flow.query_device({"name": "TV", "host": "192.168.1.99", "mac": tv_config.mac})
    assert isinstance(form, RequestUserInput)
    config = await flow.query_device({"pin": DEV_PIN})
    assert config.identifier == tv_config.identifier
    assert config.host == "192.168.1.99"
