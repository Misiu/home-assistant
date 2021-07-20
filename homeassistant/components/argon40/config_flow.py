"""Config flow for Argon40 integration."""
from __future__ import annotations

import logging
from typing import Any

from smbus import SMBus
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, I2C_ADDRESS

_LOGGER = logging.getLogger(__name__)

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)

STEP_NUMBERS_DATA_SCHEMA = vol.Schema({vol.Required("a"): int, vol.Required("b"): int})


class PlaceholderHub:
    """Placeholder class to make tests pass."""

    def __init__(self, host: str) -> None:
        """Initialize."""
        self.host = host

    async def authenticate(self, username: str, password: str) -> bool:
        """Test if we can authenticate with the host."""
        return True


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # TODO validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    hub = PlaceholderHub(data["host"])

    if not await hub.authenticate(data["username"], data["password"]):
        raise InvalidAuth

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {"title": "Name of the device"}


async def validate_numbers(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # log the data object
    _LOGGER.debug("Data: %s", data)

    a = data["a"]
    b = data["b"]

    # convert a to int
    a = int(a)
    # convert b to int
    b = int(b)
    # test if a and b are not equal
    if await check_if_numbers_are_equal(a, b):
        return {"title": "Numbers are equal"}
    else:
        raise InvalidNumbers


async def check_if_numbers_are_equal(a: int, b: int) -> bool:
    """Test if the numbers are equal."""
    return a == b


async def check_if_i2c_is_enabled(self) -> bool:
    """Test if I2C is enabled."""
    try:
        bus = SMBus(1)
        bus.write_byte(I2C_ADDRESS, 10)
        return True
    except OSError:
        # log i2c address and error details
        _LOGGER.error("I2C address %s not enabled", I2C_ADDRESS)
        # log error number and error message
        _LOGGER.error("Error number: %s", OSError.errno)
        _LOGGER.error("Error message: %s", OSError.strerror)
        return False
    except Exception as e:
        # log error details
        _LOGGER.error("Some generic error")
        _LOGGER.error("Error: %s", e)
        return False


class Argon40ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Argon40."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        # Set a unique id based on latitude/longitude
        await self.async_set_unique_id("argon40")
        self._abort_if_unique_id_configured()

        # check if user entered some data
        if user_input is not None:

            try:
                info = await validate_input(self.hass, user_input)
                # log info
                _LOGGER.info("User input: %s", info)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return await self.async_step_numbers()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_numbers(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="numbers", data_schema=STEP_NUMBERS_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_numbers(self.hass, user_input)
        except InvalidNumbers:
            errors["base"] = "invalid_numbers"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="numbers", data_schema=STEP_NUMBERS_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class InvalidNumbers(HomeAssistantError):
    """Error to indicate there is invalid auth."""
