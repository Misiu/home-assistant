"""Base entity for Thessla Green AirPack4."""

from __future__ import annotations

from typing import Any

from modbus_connection import ModbusError
from thessla_green_modbus.components import AirPackComponent

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThesslaGreenCoordinator


class ThesslaGreenEntity(CoordinatorEntity[ThesslaGreenCoordinator]):
    """Common identity and write handling for Thessla Green entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ThesslaGreenCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        serial = (
            coordinator.device.info.serial_number or entry.unique_id or entry.entry_id
        )
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(serial))},
            manufacturer="Thessla Green",
            model="AirPack4",
            name="AirPack4",
            serial_number=coordinator.device.info.serial_number,
            sw_version=coordinator.device.info.firmware_version,
        )

    async def _async_write(
        self, component: AirPackComponent, attribute: str, value: Any
    ) -> None:
        try:
            await component.write(attribute, value)
        except ModbusError as err:
            raise HomeAssistantError(
                f"Failed to write {attribute} to AirPack4"
            ) from err
        await self.coordinator.async_request_refresh()
