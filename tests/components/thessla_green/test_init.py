"""Tests for Thessla Green setup and entity mapping."""

from modbus_connection.mock import MockModbusUnit
from thessla_green_modbus import DeviceFamily

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN, SERVICE_SET_VALUE
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SERVICE_TURN_OFF
from homeassistant.components.thessla_green.const import CONF_COMFORT, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import SERIAL

from tests.common import MockConfigEntry


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
    assert entity_id is not None
    return entity_id


def _replace_serial(mock_modbus_unit: MockModbusUnit) -> None:
    """Make another controller answer at the configured Modbus address."""
    for address, value in enumerate((0x00, 0x11, 0x22, 0x33, 0x44, 0x55), 24):
        mock_modbus_unit.input[address] = value


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


async def test_setup_rejects_different_controller(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Do not load an entry when another controller answers its address."""
    _replace_serial(mock_modbus_unit)
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_runtime_identity_change_makes_entities_unavailable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Stop publishing values when the configured address moves to another unit."""
    outside_entity_id = _entity_id(hass, "sensor", "outside_temperature")
    outside = hass.states.get(outside_entity_id)
    assert outside is not None
    assert outside.state != STATE_UNAVAILABLE

    _replace_serial(mock_modbus_unit)
    coordinator = setup_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    outside = hass.states.get(outside_entity_id)
    assert outside is not None
    assert outside.state == STATE_UNAVAILABLE


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


async def test_comfort_temperature_uses_physical_range(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Expose and write the documented 10-45 °C Comfort range."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_COMFORT: True}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = _entity_id(hass, NUMBER_DOMAIN, "comfort_temperature")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["min"] == 10
    assert state.attributes["max"] == 45
    assert state.attributes["step"] == 0.5
    assert state.attributes["device_class"] == "temperature"

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, "value": 10},
        blocking=True,
    )
    assert mock_modbus_unit.holding[4212] == 20

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, "value": 45},
        blocking=True,
    )
    assert mock_modbus_unit.holding[4212] == 90


async def test_unload_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Unload all platforms cleanly."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
