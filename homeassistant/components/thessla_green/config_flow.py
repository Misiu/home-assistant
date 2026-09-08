"""Config flow for Thessla Green ventilation units."""

import logging
from typing import Any, Literal, cast, override

from modbus_connection import ModbusError, ModbusTcpParams
from thessla_green_modbus import DeviceFamily, ThesslaGreenDevice
import voluptuous as vol

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_COMFORT,
    CONF_CONSTANT_FLOW,
    CONF_DEVICE_FAMILY,
    CONF_ERV,
    CONF_FRAMER,
    CONF_PRESSURE_FILTER_ALARM,
    CONF_UNIT_ID,
    DEFAULT_DEVICE_FAMILY,
    DEFAULT_FRAMER,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DEVICE_FAMILY_NAMES,
    DOMAIN,
    FRAMERS,
)

_LOGGER = logging.getLogger(__name__)

type Framer = Literal["rtu", "socket"]


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the connection schema with optional suggested defaults."""
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_FAMILY,
                default=values.get(CONF_DEVICE_FAMILY, DEFAULT_DEVICE_FAMILY),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[family.value for family in DeviceFamily],
                    translation_key="device_family",
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_HOST, default=values.get(CONF_HOST, "")): TextSelector(),
            vol.Required(
                CONF_PORT, default=values.get(CONF_PORT, DEFAULT_PORT)
            ): vol.All(
                NumberSelector(
                    NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
                ),
                vol.Coerce(int),
            ),
            vol.Required(
                CONF_FRAMER, default=values.get(CONF_FRAMER, DEFAULT_FRAMER)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(FRAMERS),
                    translation_key="framer",
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_UNIT_ID, default=values.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ): vol.All(
                NumberSelector(
                    NumberSelectorConfig(min=1, max=247, mode=NumberSelectorMode.BOX)
                ),
                vol.Coerce(int),
            ),
        }
    )


def _params(data: dict[str, Any]) -> ModbusTcpParams:
    """Build the shared Home Assistant Modbus connection parameters."""
    return ModbusTcpParams(
        host=data[CONF_HOST],
        port=int(data[CONF_PORT]),
        framer=cast(Framer, data[CONF_FRAMER]),
    )


def _family(data: dict[str, Any]) -> DeviceFamily:
    """Return the selected product family."""
    return DeviceFamily(str(data[CONF_DEVICE_FAMILY]))


def _entry_title(family: DeviceFamily, serial: str) -> str:
    """Build a useful config-entry title without assuming one product model."""
    return f"{DEVICE_FAMILY_NAMES[family.value]} {serial}"


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> tuple[str, str]:
    """Connect and identify a controller using only the conservative info map."""
    try:
        async with async_get_temporary_unit(
            hass, _params(data), int(data[CONF_UNIT_ID])
        ) as unit:
            device = ThesslaGreenDevice(unit, family=_family(data))
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
        """Return the options flow."""
        return ThesslaGreenOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Thessla Green controller."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, _firmware = await _async_validate(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception(
                    "Unexpected exception while connecting to Thessla Green"
                )
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                family = _family(user_input)
                return self.async_create_entry(
                    title=_entry_title(family, serial), data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(), errors=errors
        )

    @override
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure connection settings or product-family metadata."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            entry_was_loaded = entry.state is ConfigEntryState.LOADED
            if entry_was_loaded and not await self.hass.config_entries.async_unload(
                entry.entry_id
            ):
                errors["base"] = "unknown"
            else:
                try:
                    serial, _firmware = await _async_validate(self.hass, user_input)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception(
                        "Unexpected exception while reconnecting to Thessla Green"
                    )
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(serial)
                    self._abort_if_unique_id_mismatch()
                    family = _family(user_input)
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=user_input,
                        title=_entry_title(family, serial),
                    )

                if entry_was_loaded:
                    await self.hass.config_entries.async_setup(entry.entry_id)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(dict(entry.data)),
            errors=errors,
        )


class ThesslaGreenOptionsFlow(OptionsFlow):
    """Configure optional capabilities without probing reserved registers."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure explicit hardware and firmware capabilities."""
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
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_COMFORT,
                        default=self.config_entry.options.get(CONF_COMFORT, False),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ERV, default=self.config_entry.options.get(CONF_ERV, False)
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_PRESSURE_FILTER_ALARM,
                        default=self.config_entry.options.get(
                            CONF_PRESSURE_FILTER_ALARM, False
                        ),
                    ): BooleanSelector(),
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate that the controller cannot be reached or identified."""
