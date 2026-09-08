"""The Thessla Green integration."""

from typing import Literal, cast

from modbus_connection import ModbusTcpParams
from thessla_green_modbus import AirPack4, DeviceOptions

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_COMFORT,
    CONF_CONSTANT_FLOW,
    CONF_ERV,
    CONF_FRAMER,
    CONF_LEGACY_FILTER_ALARM,
    CONF_UNIT_ID,
)
from .coordinator import ThesslaGreenConfigEntry, ThesslaGreenCoordinator

type Framer = Literal["rtu", "socket"]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ThesslaGreenConfigEntry
) -> bool:
    """Set up Thessla Green from a config entry."""
    params = ModbusTcpParams(
        host=entry.data[CONF_HOST],
        port=int(entry.data[CONF_PORT]),
        framer=cast(Framer, entry.data[CONF_FRAMER]),
    )
    unit = async_get_unit(hass, entry, params, int(entry.data[CONF_UNIT_ID]))
    device = AirPack4(
        unit,
        options=DeviceOptions(
            constant_flow=bool(entry.options.get(CONF_CONSTANT_FLOW, False)),
            comfort=bool(entry.options.get(CONF_COMFORT, False)),
            erv=bool(entry.options.get(CONF_ERV, False)),
            legacy_filter_alarm=bool(
                entry.options.get(CONF_LEGACY_FILTER_ALARM, False)
            ),
        ),
    )
    coordinator = ThesslaGreenCoordinator(hass, entry, device)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: ThesslaGreenConfigEntry
) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: ThesslaGreenConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
