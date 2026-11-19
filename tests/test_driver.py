"""Remote standby: the connection to the TV is kept, only the listening pace slows down."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def driver_with_device(device, monkeypatch):
    from intg_philips_titanos.driver import PhilipsDriver

    driver = PhilipsDriver()
    driver._device_instances[device.identifier] = device
    monkeypatch.setattr(device, "disconnect", AsyncMock())
    return driver, device


async def test_enter_standby_slows_polling_without_disconnect(driver_with_device):
    driver, device = driver_with_device
    await driver.on_r2_enter_standby()
    assert device._poll_interval == 15
    device.disconnect.assert_not_awaited()


async def test_exit_standby_restores_polling(driver_with_device):
    driver, device = driver_with_device
    await driver.on_r2_enter_standby()
    await driver.on_r2_exit_standby()
    assert device._poll_interval == 3
    device.disconnect.assert_not_awaited()


def test_set_poll_interval(device):
    device.set_poll_interval(15)
    assert device._poll_interval == 15
