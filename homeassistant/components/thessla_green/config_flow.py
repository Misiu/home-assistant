"""Config flow for Thessla Green AirPack4."""

import logging
from typing import Any, Literal, cast, override

from modbus_connection import ModbusError, ModbusTcpParams
from thessla_green_modbus import AirPack4
import voluptuous as vol

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_COMFORT,
    CONF_CONSTANT_FLOW,
    CONF_ERV,
    CONF_FRAMER,
    CONF_LEGACY_FILTER_ALARM,
    CONF_UNIT_ID,
    DEFAULT_FRAMER,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    FRAMERS,
)

_LOGGER = logging.getLogger(__name__)

type Framer = Literal["rtu", "socket"]


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=values.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_PORT, default=values.get(CONF_PORT, DEFAULT_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(
                CONF_FRAMER, default=values.get(CONF_FRAMER, DEFAULT_FRAMER)
            ): vol.In(FRAMERS),
            vol.Required(
                CONF_UNIT_ID, default=values.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
        }
    )


def _params(data: dict[str, Any]) -> ModbusTcpParams:
    return ModbusTcpParams(
        host=data[CONF_HOST],
        port=int(data[CONF_PORT]),
        framer=cast(Framer, data[CONF_FRAMER]),
    )


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> tuple[str, str]:
    try:
        async with async_get_temporary_unit(
            hass, _params(data), int(data[CONF_UNIT_ID])
        ) as unit:
            device = AirPack4(unit)
            await device.info.async_update()
    except (ModbusError, OSError, ValueError, HomeAssistantError) as err:
        raise CannotConnect from err

    serial = device.info.serial_number
    if serial is None:
        raise CannotConnect
    return serial, device.info.firmware_version or "unknown"


class ThesslaGreenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thessla Green."""

    VERSION = 1

    @staticmethod
    @override
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return ThesslaGreenOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, _firmware = await _async_validate(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception while connecting to AirPack4")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"AirPack4 {serial}", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(), errors=errors
        )

    @override
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, _firmware = await _async_validate(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception while reconnecting to AirPack4")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(dict(entry.data)),
            errors=errors,
        )


class ThesslaGreenOptionsFlow(OptionsFlow):
    """Configure optional AirPack4 capabilities without probing reserved registers."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONSTANT_FLOW,
                        default=self.config_entry.options.get(
                            CONF_CONSTANT_FLOW, False
                        ),
                    ): bool,
                    vol.Required(
                        CONF_COMFORT,
                        default=self.config_entry.options.get(CONF_COMFORT, False),
                    ): bool,
                    vol.Required(
                        CONF_ERV, default=self.config_entry.options.get(CONF_ERV, False)
                    ): bool,
                    vol.Required(
                        CONF_LEGACY_FILTER_ALARM,
                        default=self.config_entry.options.get(
                            CONF_LEGACY_FILTER_ALARM, False
                        ),
                    ): bool,
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate that the AirPack4 cannot be reached or identified."""
