"""Base entity for Thessla Green."""

from typing import Any

from modbus_connection import ModbusError
from thessla_green_modbus import ThesslaGreenComponent

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_FAMILY_NAMES, DOMAIN
from .coordinator import ThesslaGreenCoordinator


class ThesslaGreenEntity(CoordinatorEntity[ThesslaGreenCoordinator]):
    """Common identity and write handling for Thessla Green entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ThesslaGreenCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device = coordinator.device
        serial = device.info.serial_number or entry.unique_id or entry.entry_id
        family_name = DEVICE_FAMILY_NAMES[device.family.value]
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(serial))},
            manufacturer="Thessla Green",
            model=family_name,
            name=entry.title,
            serial_number=device.info.serial_number,
            sw_version=device.info.firmware_version,
        )

    async def _async_write(
        self, component: ThesslaGreenComponent, attribute: str, value: Any
    ) -> None:
        """Write through the library and refresh only after a successful write."""
        try:
            await component.write(attribute, value)
        except ModbusError as err:
            raise HomeAssistantError(
                f"Failed to write {attribute} to Thessla Green"
            ) from err
        await self.coordinator.async_request_refresh()
