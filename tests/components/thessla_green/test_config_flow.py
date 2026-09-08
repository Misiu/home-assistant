"""Tests for the Thessla Green config flow."""

from unittest.mock import patch

from modbus_connection.mock import MockModbusConnection, MockModbusUnit

from homeassistant import config_entries
from homeassistant.components.thessla_green.const import (
    CONF_FRAMER,
    CONF_UNIT_ID,
    DEFAULT_FRAMER,
    DOMAIN,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import HOST, PORT, SERIAL, UNIT_ID


async def test_user_flow(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Configure an AirPack4 after reading its controller serial."""
    with patch(
        "homeassistant.components.modbus.connection.ModbusConnection",
        return_value=mock_modbus_connection,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_PORT: PORT,
                CONF_FRAMER: DEFAULT_FRAMER,
                CONF_UNIT_ID: UNIT_ID,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"AirPack4 {SERIAL}"
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_PORT: PORT,
        CONF_FRAMER: DEFAULT_FRAMER,
        CONF_UNIT_ID: UNIT_ID,
    }
    assert result["result"].unique_id == SERIAL


async def test_user_flow_cannot_identify_device(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Reject a controller whose serial cannot be identified."""
    for address in range(24, 30):
        mock_modbus_unit.input[address] = 0

    with patch(
        "homeassistant.components.modbus.connection.ModbusConnection",
        return_value=mock_modbus_connection,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_PORT: PORT,
                CONF_FRAMER: DEFAULT_FRAMER,
                CONF_UNIT_ID: UNIT_ID,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
