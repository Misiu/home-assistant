"""Fixtures for the Thessla Green integration tests."""

from unittest.mock import patch

from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest

from homeassistant.components.thessla_green.const import (
    CONF_DEVICE_FAMILY,
    CONF_FRAMER,
    CONF_UNIT_ID,
    DEFAULT_FRAMER,
    DOMAIN,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

HOST = "1.2.3.4"
PORT = 502
UNIT_ID = 10
SERIAL = "1a2b3c4d5e6f"
DEVICE_FAMILY = "series_4_h"


@pytest.fixture
def mock_modbus_unit(
    mock_modbus_connection: MockModbusConnection,
) -> MockModbusUnit:
    """Return a seeded Thessla Green unit using the real device library."""
    unit = mock_modbus_connection.for_unit(UNIT_ID)

    input_registers = {
        0: 4,
        1: 85,
        4: 0,
        16: 123,
        17: 210,
        18: 225,
        19: 51,
        22: 234,
        24: 0x1A,
        25: 0x2B,
        26: 0x3C,
        27: 0x4D,
        28: 0x5E,
        29: 0x6F,
        271: 1,
        272: 45,
        273: 43,
        274: 300,
        275: 290,
        276: 10,
        277: 100,
    }
    for address, value in input_registers.items():
        unit.input[address] = value

    holding_registers = {
        256: 300,
        257: 290,
        4192: 0,
        4198: 0,
        4208: 0,
        4209: 0,
        4210: 40,
        4211: 40,
        4212: 42,
        4213: 42,
        4224: 0,
        4304: 0,
        4305: 0,
        4320: 0,
        4330: 0,
        4387: 1,
        4704: 0,
        4711: 0,
        8192: 0,
        8193: 0,
        8208: 0,
        8222: 0,
        8223: 0,
        8330: 0,
        8331: 0,
        8334: 0,
        8335: 0,
        8338: 0,
        8339: 0,
        8443: 0,
        8444: 0,
    }
    for address, value in holding_registers.items():
        unit.holding[address] = value

    unit.coils[9] = False
    unit.coils[11] = True
    return unit


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured Thessla Green entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"AirPack⁴ h {SERIAL}",
        unique_id=SERIAL,
        data={
            CONF_DEVICE_FAMILY: DEVICE_FAMILY,
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_FRAMER: DEFAULT_FRAMER,
            CONF_UNIT_ID: UNIT_ID,
        },
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> MockConfigEntry:
    """Set up the integration against the in-memory Modbus transport."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.modbus.connection.ModbusConnection",
        return_value=mock_modbus_connection,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return mock_config_entry
