"""Tests for Thessla Green setup and entity mapping."""

from modbus_connection.mock import MockModbusUnit
from thessla_green_modbus import DeviceFamily

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN, SERVICE_SET_VALUE
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SERVICE_TURN_OFF
from homeassistant.components.thessla_green.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import SERIAL

from tests.common import MockConfigEntry


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
    assert entity_id is not None
    return entity_id


async def test_setup_creates_device_and_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Set up the controller through the real device library."""
    coordinator = setup_integration.runtime_data
    assert coordinator.last_update_success
    assert coordinator.device.family is DeviceFamily.SERIES_4_H
    assert coordinator.device.info.serial_number == SERIAL
    assert coordinator.device.info.firmware_version == "4.85.0"

    outside = hass.states.get(_entity_id(hass, "sensor", "outside_temperature"))
    assert outside is not None
    assert outside.state == "12.3"

    fan_power = hass.states.get(_entity_id(hass, "binary_sensor", "fans_powered"))
    assert fan_power is not None
    assert fan_power.state == "on"


async def test_controls_write_through_library_validation(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Map Home Assistant controls to the library's validated writes."""
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: _entity_id(hass, NUMBER_DOMAIN, "manual_speed"), "value": 55},
        blocking=True,
    )
    assert mock_modbus_unit.holding[4210] == 55

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: _entity_id(hass, SELECT_DOMAIN, "operating_mode"),
            "option": "manual",
        },
        blocking=True,
    )
    assert mock_modbus_unit.holding[4208] == 1

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: _entity_id(hass, SWITCH_DOMAIN, "automatic_bypass")},
        blocking=True,
    )
    assert mock_modbus_unit.holding[4320] == 1


async def test_unload_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Unload all platforms cleanly."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
