"""Binary sensor platform for OpenDisplay devices."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OpenDisplayConfigEntry
from .entity import OpenDisplayEntity

PARALLEL_UPDATES = 0

_CONNECTIVITY_DESCRIPTION = BinarySensorEntityDescription(
    key="connectivity",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)

_PENDING_UPLOAD_DESCRIPTION = BinarySensorEntityDescription(
    key="pending_upload",
    translation_key="pending_upload",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OpenDisplay binary sensor entities."""
    async_add_entities(
        [
            OpenDisplayConnectivityBinarySensor(
                entry.runtime_data.coordinator, _CONNECTIVITY_DESCRIPTION
            ),
            OpenDisplayPendingUploadBinarySensor(
                entry.runtime_data.coordinator,
                _PENDING_UPLOAD_DESCRIPTION,
            ),
        ]
    )


class OpenDisplayConnectivityBinarySensor(OpenDisplayEntity, BinarySensorEntity):
    """Reports whether the OpenDisplay device is currently advertising over BLE."""

    @property
    @override
    def available(self) -> bool:
        """Connectivity is reported regardless of the device's availability."""
        return True

    @property
    @override
    def is_on(self) -> bool:
        """Return True if the device is currently reachable via BLE."""
        return self.coordinator.available


class OpenDisplayPendingUploadBinarySensor(OpenDisplayEntity, BinarySensorEntity):
    """Reports if there is a pending upload waiting for device wake-up."""

    @property
    def available(self) -> bool:
        """Pending upload state should be visible even while device is sleeping."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True if an upload is currently queued."""
        return self.coordinator.pending_upload
