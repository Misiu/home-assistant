"""Support for Argon40 fan."""
from __future__ import annotations

import logging

from smbus import SMBus

from homeassistant.components.fan import SUPPORT_SET_SPEED, FanEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_ON_PERCENTAGE, DOMAIN, I2C_ADDRESS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Argon40 fan platform."""
    devices = []
    devices.append(Argon40FanEntity())
    async_add_entities(devices)


class Argon40FanEntity(FanEntity):
    """Representation of an Argon40 fan."""

    def __init__(self) -> None:
        """Initialize the fan."""
        self._percentage = 0
        self._bus = SMBus(1)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return "argon40_case"

    @property
    def name(self) -> str:
        """Return the name of the fan."""
        return "Argon40 Case"

    @property
    def should_poll(self) -> bool:
        """No polling needed for a fan."""
        return False

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return SUPPORT_SET_SPEED

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return 100

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        return self._percentage

    @property
    def is_on(self) -> bool:
        """Get if the fan is on."""
        return self._percentage != 0

    @property
    def device_info(self) -> DeviceInfo:
        """Return device specific attributes."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, "Case")},
            ATTR_NAME: "Argon ONE Case for Raspberry Pi 4",
            ATTR_MANUFACTURER: "Argon40",
            ATTR_MODEL: "V2",
        }

    def set_percentage(self, percentage: int):
        """Set the speed percentage."""
        _LOGGER.debug("set_percentage: %s", percentage)
        if percentage is None:
            self._percentage = 0
            return

        percentage = max(0, percentage)
        percentage = min(100, percentage)
        self._percentage = percentage
        # write percentage to smbus
        self._bus.write_byte(I2C_ADDRESS, int(percentage))

        self.async_schedule_update_ha_state()

    def turn_on(
        self,
        speed: str | None = None,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs,
    ):
        """Turn the device on."""
        _LOGGER.debug(
            "turn_on: speed: %s, percentage: %s, preset_mode: %s",
            speed,
            percentage,
            preset_mode,
        )
        if percentage is None:
            percentage = DEFAULT_ON_PERCENTAGE
        self.set_percentage(percentage)

    def turn_off(self, **kwargs):
        """Turn the device off."""
        _LOGGER.debug("turn_off")
        self.set_percentage(0)
