"""Integration process: logging, manifest, UC API, configured devices."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from ucapi import DeviceStates
from ucapi_framework import BaseConfigManager, get_config_path

from intg_philips_titanos import __version__
from intg_philips_titanos.config import PhilipsConfig
from intg_philips_titanos.driver import PhilipsDriver
from intg_philips_titanos.setup_flow import PhilipsSetupFlow

_LOG = logging.getLogger(__name__)


def manifest_path() -> Path:
    """`driver.json` of the running integration.

    The Remote package is a PyInstaller "onedir" build: `driver` and `driver.json` side by side, the
    Python code under `_internal/`. Frozen, the manifest is therefore next to the executable; from
    source, it is at the root of the repository.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "driver.json"
    return Path(__file__).resolve().parents[1] / "driver.json"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)-24s | %(message)s"
    )
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)  # one line per Remote reconnection


async def main() -> None:
    _configure_logging()
    _LOG.info("Starting Philips Titan OS integration v%s", __version__)
    manifest = manifest_path()
    if not manifest.is_file():
        raise FileNotFoundError(f"Remote 3 manifest not found: {manifest}")
    _LOG.info("Using manifest: %s", manifest)

    driver = PhilipsDriver()
    configs = BaseConfigManager(
        get_config_path(driver.api.config_dir_path or ""),
        add_handler=driver.on_device_added,
        remove_handler=driver.on_device_removed,
        config_class=PhilipsConfig,
    )
    driver.config_manager = configs
    await driver.api.init(str(manifest), PhilipsSetupFlow.create_handler(driver))
    _LOG.info("UC API initialized and setup handler registered")

    # The Remote connects the devices itself (`connect` event) once it is ready.
    await driver.register_all_device_instances(connect=False)
    has_devices = any(True for _ in configs.all())
    await driver.api.set_device_state(DeviceStates.CONNECTED if has_devices else DeviceStates.DISCONNECTED)
    await asyncio.Event().wait()  # serve until the process is stopped
