"""DataUpdateCoordinator for Thessla Green AirPack4."""

import logging

from modbus_connection import ModbusError
from thessla_green_modbus import AirPack4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ThesslaGreenConfigEntry = ConfigEntry[ThesslaGreenCoordinator]


class ThesslaGreenCoordinator(DataUpdateCoordinator[AirPack4]):
    """Poll the complete AirPack4 model on one shared Modbus unit."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ThesslaGreenConfigEntry,
        device: AirPack4,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.device = device

    async def _async_update_data(self) -> AirPack4:
        try:
            await self.device.async_update()
        except ModbusError as err:
            raise UpdateFailed(f"Error communicating with AirPack4: {err}") from err
        return self.device
