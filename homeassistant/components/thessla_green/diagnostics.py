"""Diagnostics for Thessla Green."""

from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ThesslaGreenConfigEntry

TO_REDACT = {"host"}
_SERIAL_REGISTER_ADDRESSES = range(24, 30)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ThesslaGreenConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without exposing network or controller identifiers."""
    coordinator = entry.runtime_data
    device = coordinator.device
    registers: dict[str, Any] = await device.async_read_raw(notify=False)
    input_registers: dict[int, Any] = dict(registers.get("input", {}))
    for address in _SERIAL_REGISTER_ADDRESSES:
        if address in input_registers:
            input_registers[address] = REDACTED
    registers = {**registers, "input": input_registers}

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "device": {
            "domain": DOMAIN,
            "family": device.family.value,
            "serial_number": REDACTED if device.info.serial_number else None,
            "firmware_version": device.info.firmware_version,
            "last_update_success": coordinator.last_update_success,
        },
        "registers": registers,
    }
