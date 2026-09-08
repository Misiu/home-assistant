"""Diagnostics for Thessla Green."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ThesslaGreenConfigEntry

TO_REDACT = {"host"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ThesslaGreenConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry without exposing the gateway host."""
    coordinator = entry.runtime_data
    device = coordinator.device
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "device": {
            "domain": DOMAIN,
            "family": device.family.value,
            "serial_number": device.info.serial_number,
            "firmware_version": device.info.firmware_version,
            "last_update_success": coordinator.last_update_success,
        },
        "registers": await device.async_read_raw(notify=False),
    }
