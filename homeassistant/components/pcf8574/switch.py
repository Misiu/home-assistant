"""Support for switch sensor using I2C PCF8574 chip."""
import logging

import voluptuous as vol

from i2crelay import I2CRelayBoard  # pylint: disable=import-error

from homeassistant.components.switch import PLATFORM_SCHEMA
from homeassistant.const import DEVICE_DEFAULT_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import ToggleEntity

_LOGGER = logging.getLogger(__name__)

CONF_INVERT_LOGIC = "invert_logic"
CONF_I2C_ADDRESS = "i2c_address"
CONF_PINS = "pins"
CONF_PULL_MODE = "pull_mode"

DEFAULT_INVERT_LOGIC = False
DEFAULT_I2C_ADDRESS = 0x20

_SWITCHES_SCHEMA = vol.Schema({cv.positive_int: cv.string})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_PINS): _SWITCHES_SCHEMA,
        vol.Optional(CONF_INVERT_LOGIC, default=DEFAULT_INVERT_LOGIC): cv.boolean,
        vol.Optional(CONF_I2C_ADDRESS, default=DEFAULT_I2C_ADDRESS): vol.Coerce(int),
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the PCF8574 devices."""
    invert_logic = config.get(CONF_INVERT_LOGIC)
    i2c_address = config.get(CONF_I2C_ADDRESS)

    # i2c = busio.I2C(board.SCL, board.SDA)
    pcf = I2CRelayBoard(1, address=i2c_address)

    switches = []
    pins = config.get(CONF_PINS)
    for pin_num, pin_name in pins.items():
        switches.append(PCF8574Switch(pcf, pin_name, pin_num, invert_logic))
    add_entities(switches)


class PCF8574Switch(ToggleEntity):
    """Representation of a  PCF8574 output pin."""

    def __init__(self, pcf, name, pin, invert_logic):
        """Initialize the pin."""
        self._pcf = pcf
        self._name = name or DEVICE_DEFAULT_NAME
        self._pin = pin
        self._invert_logic = invert_logic
        self._state = False

        if self._invert_logic:
            self._pcf.switch_on(self._pin)
        else:
            self._pcf.switch_off(self._pin)

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._state

    @property
    def assumed_state(self):
        """Return true if optimistic updates are used."""
        return True

    def turn_on(self, **kwargs):
        """Turn the device on."""
        if self._invert_logic:
            self._pcf.switch_off(self._pin)
        else:
            self._pcf.switch_on(self._pin)

        self._state = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        if self._invert_logic:
            self._pcf.switch_on(self._pin)
        else:
            self._pcf.switch_off(self._pin)
        self._state = False
        self.schedule_update_ha_state()
