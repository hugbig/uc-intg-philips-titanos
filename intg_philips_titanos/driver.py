"""UC integration driver: one `PhilipsDevice` per configured TV, exposed as a remote entity."""

import logging

from ucapi_framework import BaseIntegrationDriver

from intg_philips_titanos.config import PhilipsConfig
from intg_philips_titanos.device import PhilipsDevice
from intg_philips_titanos.remote import PhilipsRemote

_LOG = logging.getLogger(__name__)

# Pause between two state listens while the Remote sleeps: less traffic, connection kept.
STANDBY_POLL_INTERVAL = 15


class PhilipsDriver(BaseIntegrationDriver[PhilipsDevice, PhilipsConfig]):
    def __init__(self):
        super().__init__(
            device_class=PhilipsDevice,
            # Remote entity only: the TV reports no title, source or volume for a media player.
            entity_classes=[PhilipsRemote],
            driver_id="philips_titanos_ambilight",
        )

    async def on_r2_enter_standby(self) -> None:
        """Remote asleep: keep the TV connection (reconnecting on wake is slow), listen less often.

        The framework default disconnects every device here.
        """
        _LOG.debug("Remote standby: connections kept, listening every %s s", STANDBY_POLL_INTERVAL)
        for device in self._device_instances.values():
            device.set_poll_interval(STANDBY_POLL_INTERVAL)

    async def on_r2_exit_standby(self) -> None:
        """Remote awake: back to the configured pace, without reconnecting."""
        _LOG.debug("Remote awake: configured listening pace restored")
        for device in self._device_instances.values():
            device.set_poll_interval(device._config.poll_interval)
