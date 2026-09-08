"""Tests for the Thessla Green config flow."""

from unittest.mock import AsyncMock, patch

from modbus_connection import ModbusError
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest

from homeassistant.components.thessla_green.config_flow import CannotConnect
from homeassistant.components.thessla_green.const import (
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
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError

from .conftest import DEVICE_FAMILY, HOST, PORT, SERIAL, UNIT_ID

from tests.common import MockConfigEntry

USER_INPUT = {
    CONF_DEVICE_FAMILY: DEVICE_FAMILY,
    CONF_HOST: HOST,
    CONF_PORT: PORT,
    CONF_FRAMER: DEFAULT_FRAMER,
    CONF_UNIT_ID: UNIT_ID,
}
RECONFIGURE_INPUT = {
    CONF_DEVICE_FAMILY: "home_h",
    CONF_HOST: "2.3.4.5",
    CONF_PORT: 1502,
    CONF_FRAMER: "socket",
    CONF_UNIT_ID: UNIT_ID,
}
RELINK_INPUT = {
    **USER_INPUT,
    CONF_FRAMER: "socket",
}
OPTIONS = {
    CONF_CONSTANT_FLOW: True,
    CONF_COMFORT: True,
    CONF_ERV: False,
    CONF_PRESSURE_FILTER_ALARM: True,
}


async def _start_user_flow(hass: HomeAssistant) -> dict:
    """Start the user flow and return its form result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result


async def _start_reconfigure_flow(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Start reconfiguration for an existing entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {}
    return result


async def test_user_form_defaults(hass: HomeAssistant) -> None:
    """Test the initial form exposes conservative connection defaults."""
    result = await _start_user_flow(hass)

    defaults = result["data_schema"]({})
    assert defaults == {
        CONF_DEVICE_FAMILY: DEFAULT_DEVICE_FAMILY,
        CONF_HOST: "",
        CONF_PORT: DEFAULT_PORT,
        CONF_FRAMER: DEFAULT_FRAMER,
        CONF_UNIT_ID: DEFAULT_UNIT_ID,
    }


async def test_user_flow(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Configure a Thessla Green controller after reading its serial."""
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"AirPack⁴ h {SERIAL}"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == SERIAL


async def test_user_flow_cannot_identify_device(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Reject a controller whose serial cannot be identified."""
    for address in range(24, 30):
        mock_modbus_unit.input[address] = 0

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_cannot_read_device(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Handle a Modbus read failure while validating the controller."""
    mock_modbus_unit.fail_requests(ModbusError("read failed"))

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_shared_link_conflict(hass: HomeAssistant) -> None:
    """Treat incompatible settings on an already shared link as a connection error."""
    result = await _start_user_flow(hass)

    with patch(
        "homeassistant.components.thessla_green.config_flow.async_get_temporary_unit",
        side_effect=HomeAssistantError("shared link conflict"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_recovers_from_error(hass: HomeAssistant) -> None:
    """Allow the user to retry the same flow after a transient error."""
    result = await _start_user_flow(hass)

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(side_effect=[CannotConnect(), (SERIAL, "4.85.0")]),
    ) as validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert validate.await_count == 2


async def test_user_flow_recovers_from_unknown_error(hass: HomeAssistant) -> None:
    """Handle an unexpected exception and allow a successful retry."""
    result = await _start_user_flow(hass)

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(side_effect=[RuntimeError("unexpected"), (SERIAL, "4.85.0")]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_device(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Do not allow the same controller serial to be configured twice."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title=f"AirPack⁴ h {SERIAL}",
        unique_id=SERIAL,
        data=USER_INPUT,
    )
    existing.add_to_hass(hass)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_maximum_unit_id(hass: HomeAssistant) -> None:
    """Accept the highest valid Modbus unit address."""
    result = await _start_user_flow(hass)
    user_input = {**USER_INPUT, CONF_UNIT_ID: 247}

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(return_value=(SERIAL, "4.85.0")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_UNIT_ID] == 247


@pytest.mark.parametrize("unit_id", [0, 248])
async def test_unit_id_out_of_range(hass: HomeAssistant, unit_id: int) -> None:
    """Reject Modbus unit addresses outside the standard address range."""
    result = await _start_user_flow(hass)

    with (
        patch(
            "homeassistant.components.thessla_green.config_flow._async_validate",
            AsyncMock(),
        ) as validate,
        pytest.raises(InvalidData),
    ):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_UNIT_ID: unit_id}
        )

    validate.assert_not_awaited()


async def test_options_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Configure optional register groups through the options flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] is None
    assert result["data_schema"]({}) == {
        CONF_CONSTANT_FLOW: False,
        CONF_COMFORT: False,
        CONF_ERV: False,
        CONF_PRESSURE_FILTER_ALARM: False,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=OPTIONS
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == OPTIONS
    assert mock_config_entry.options == OPTIONS


async def test_options_flow_uses_existing_values(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Use existing capability options as defaults when reopening the flow."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options=OPTIONS)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({}) == OPTIONS


async def test_reconfigure_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Update connection settings after verifying the same controller serial."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_reconfigure_flow(hass, mock_config_entry)

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(return_value=(SERIAL, "4.85.0")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == RECONFIGURE_INPUT
    assert mock_config_entry.title == f"AirPack Home h {SERIAL}"


async def test_reconfigure_new_endpoint_does_not_unload_active_link(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Probe a different Modbus endpoint without dropping the working link."""
    result = await _start_reconfigure_flow(hass, setup_integration)

    with (
        patch.object(hass.config_entries, "async_unload", AsyncMock()) as unload,
        patch(
            "homeassistant.components.thessla_green.config_flow._async_validate",
            AsyncMock(return_value=(SERIAL, "4.85.0")),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    unload.assert_not_awaited()


async def test_reconfigure_flow_wrong_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Reject reconfiguration when the new endpoint identifies another controller."""
    mock_config_entry.add_to_hass(hass)
    original_data = dict(mock_config_entry.data)
    result = await _start_reconfigure_flow(hass, mock_config_entry)

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(return_value=("001122334455", "4.85.0")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert mock_config_entry.data == original_data


async def test_reconfigure_flow_recovers_from_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Allow reconfiguration to recover after a transient connection failure."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_reconfigure_flow(hass, mock_config_entry)

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(side_effect=[CannotConnect(), (SERIAL, "4.85.0")]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_flow_recovers_from_unknown_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Handle an unexpected reconfigure exception and allow another attempt."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_reconfigure_flow(hass, mock_config_entry)

    with patch(
        "homeassistant.components.thessla_green.config_flow._async_validate",
        AsyncMock(side_effect=[RuntimeError("unexpected"), (SERIAL, "4.85.0")]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RECONFIGURE_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_loaded_entry_restored_after_error(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Restore a loaded entry when relink validation fails."""
    result = await _start_reconfigure_flow(hass, setup_integration)

    with (
        patch.object(
            hass.config_entries, "async_unload", AsyncMock(return_value=True)
        ) as unload,
        patch.object(
            hass.config_entries, "async_setup", AsyncMock(return_value=True)
        ) as setup,
        patch(
            "homeassistant.components.thessla_green.config_flow._async_validate",
            AsyncMock(side_effect=CannotConnect()),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RELINK_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    unload.assert_awaited_once_with(setup_integration.entry_id)
    setup.assert_awaited_once_with(setup_integration.entry_id)


async def test_reconfigure_relink_wrong_device_restores_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Restore a released link before aborting on a different controller."""
    result = await _start_reconfigure_flow(hass, setup_integration)

    with (
        patch.object(
            hass.config_entries, "async_unload", AsyncMock(return_value=True)
        ),
        patch.object(
            hass.config_entries, "async_setup", AsyncMock(return_value=True)
        ) as setup,
        patch(
            "homeassistant.components.thessla_green.config_flow._async_validate",
            AsyncMock(return_value=("001122334455", "4.85.0")),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RELINK_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    setup.assert_awaited_once_with(setup_integration.entry_id)


async def test_reconfigure_stops_when_unload_fails(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Do not validate new settings if the active link cannot be released."""
    result = await _start_reconfigure_flow(hass, setup_integration)

    with (
        patch.object(
            hass.config_entries, "async_unload", AsyncMock(return_value=False)
        ) as unload,
        patch(
            "homeassistant.components.thessla_green.config_flow._async_validate",
            AsyncMock(),
        ) as validate,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], RELINK_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    unload.assert_awaited_once_with(setup_integration.entry_id)
    validate.assert_not_awaited()
