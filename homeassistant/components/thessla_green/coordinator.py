"""DataUpdateCoordinator for Thessla Green."""

import logging
from typing import override

from modbus_connection import ModbusError
from thessla_green_modbus import ThesslaGreenDevice

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ThesslaGreenConfigEntry = ConfigEntry[ThesslaGreenCoordinator]


class ThesslaGreenCoordinator(DataUpdateCoordinator[ThesslaGreenDevice]):
    """Poll one Thessla Green controller through one shared Modbus unit."""

    config_entry: ThesslaGreenConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ThesslaGreenConfigEntry,
        device: ThesslaGreenDevice,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.device = device

    @override
    async def _async_update_data(self) -> ThesslaGreenDevice:
        """Poll all enabled components and verify the configured controller."""
        try:
            await self.device.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                f"Error communicating with Thessla Green: {err}"
            ) from err

        if self.device.info.serial_number != self.config_entry.unique_id:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="wrong_device",
            )

        return self.device
