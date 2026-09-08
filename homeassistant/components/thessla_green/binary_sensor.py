"""Binary sensor platform for Thessla Green."""

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ThesslaGreenConfigEntry, ThesslaGreenCoordinator
from .entity import ThesslaGreenEntity


@dataclass(frozen=True, kw_only=True)
class ThesslaGreenBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a binary value exposed by the device library."""

    component: str
    attribute: str


DESCRIPTIONS: tuple[ThesslaGreenBinarySensorDescription, ...] = (
    ThesslaGreenBinarySensorDescription(
        key="fans_powered",
        translation_key="fans_powered",
        component="ventilation",
        attribute="fans_powered",
    ),
    ThesslaGreenBinarySensorDescription(
        key="bypass_actuator",
        translation_key="bypass_actuator",
        component="bypass",
        attribute="actuator_on",
    ),
    ThesslaGreenBinarySensorDescription(
        key="frost_protection",
        translation_key="frost_protection",
        component="alarms",
        attribute="frost_protection_active",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *(
        ThesslaGreenBinarySensorDescription(
            key=attribute,
            translation_key=attribute,
            component="alarms",
            attribute=attribute,
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for attribute in (
            "warning",
            "error",
            "fpx_thermal_protection",
            "supply_fan_failure",
            "extract_fan_failure",
            "supply_flow_sensor_failure",
            "extract_flow_sensor_failure",
            "supply_filter_missing",
            "extract_filter_missing",
            "supply_filter_due",
            "extract_filter_due",
            "duct_filter_due",
        )
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThesslaGreenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thessla Green binary sensors."""
    coordinator = entry.runtime_data
    descriptions = list(DESCRIPTIONS)
    if coordinator.device.constant_flow is not None:
        descriptions.append(
            ThesslaGreenBinarySensorDescription(
                key="constant_flow_active",
                translation_key="constant_flow_active",
                component="constant_flow",
                attribute="active",
            )
        )
    if coordinator.device.erv is not None:
        descriptions.append(
            ThesslaGreenBinarySensorDescription(
                key="erv_active",
                translation_key="erv_active",
                component="erv",
                attribute="active",
            )
        )
    if coordinator.device.pressure_filter_alarm is not None:
        descriptions.append(
            ThesslaGreenBinarySensorDescription(
                key="pressure_filter_due",
                translation_key="pressure_filter_due",
                component="pressure_filter_alarm",
                attribute="filter_due",
                device_class=BinarySensorDeviceClass.PROBLEM,
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=False,
            )
        )
    async_add_entities(
        ThesslaGreenBinarySensor(coordinator, description)
        for description in descriptions
    )


class ThesslaGreenBinarySensor(ThesslaGreenEntity, BinarySensorEntity):
    """Represent one Thessla Green binary state."""

    entity_description: ThesslaGreenBinarySensorDescription

    def __init__(
        self,
        coordinator: ThesslaGreenCoordinator,
        description: ThesslaGreenBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        value = getattr(component, self.entity_description.attribute)
        return value if isinstance(value, bool) else None
