import pytest

from intg_philips_titanos.client import PhilipsJointSpaceClient
from tests.fake_tv import FakeTitanTV

TV_HOST = "192.168.1.42"


@pytest.fixture
def fake_tv() -> FakeTitanTV:
    """Fake TV that behaves like the real 65OLED851 (see `FakeTitanTV.realistic`)."""
    return FakeTitanTV.realistic()


@pytest.fixture
async def client(fake_tv: FakeTitanTV):
    instance = PhilipsJointSpaceClient(TV_HOST, secured_transport=False, transport=fake_tv.transport())
    yield instance
    await instance.close()


@pytest.fixture
def tv_config():
    from intg_philips_titanos.config import PhilipsConfig

    return PhilipsConfig(
        identifier="philips_192_168_1_42",
        name="TV salon",
        host=TV_HOST,
        mac="AA:BB:CC:DD:EE:FF",
        username="user",
        password="secret",
        secured_transport=False,
    )


@pytest.fixture
async def device(tv_config, client):
    from intg_philips_titanos.device import PhilipsDevice

    instance = PhilipsDevice(tv_config, client=client)
    yield instance
    instance.cancel_power_task()


@pytest.fixture
async def tv(tv_config, client, fake_tv):
    """Connected device: it listens to the fake TV continuously, as on the Remote."""
    from intg_philips_titanos.device import PhilipsDevice

    fake_tv.notify_hold = 0.5
    tv_config.poll_interval = 0
    instance = PhilipsDevice(tv_config, client=client)
    assert await instance.connect()
    yield instance
    instance.cancel_power_task()
    await instance.disconnect()
