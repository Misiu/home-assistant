"""Sensor platform for Thessla Green AirPack4."""

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ThesslaGreenConfigEntry, ThesslaGreenCoordinator
from .entity import ThesslaGreenEntity


@dataclass(frozen=True, kw_only=True)
class ThesslaGreenSensorDescription(SensorEntityDescription):
    """Describe one library attribute exposed as a sensor."""

    component: str
    attribute: str


BASE_DESCRIPTIONS: tuple[ThesslaGreenSensorDescription, ...] = (
    ThesslaGreenSensorDescription(
        key="outside_temperature",
        translation_key="outside_temperature",
        component="temperatures",
        attribute="outside",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="supply_temperature",
        translation_key="supply_temperature",
        component="temperatures",
        attribute="supply",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="extract_temperature",
        translation_key="extract_temperature",
        component="temperatures",
        attribute="extract",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="after_fpx_temperature",
        translation_key="after_fpx_temperature",
        component="temperatures",
        attribute="after_fpx",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        component="temperatures",
        attribute="ambient",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="supply_flow",
        translation_key="supply_flow",
        component="ventilation",
        attribute="supply_flow",
        native_unit_of_measurement="m³/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="extract_flow",
        translation_key="extract_flow",
        component="ventilation",
        attribute="extract_flow",
        native_unit_of_measurement="m³/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

CONSTANT_FLOW_DESCRIPTIONS: tuple[ThesslaGreenSensorDescription, ...] = (
    ThesslaGreenSensorDescription(
        key="constant_flow_supply_percentage",
        translation_key="constant_flow_supply_percentage",
        component="constant_flow",
        attribute="supply_percentage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="constant_flow_extract_percentage",
        translation_key="constant_flow_extract_percentage",
        component="constant_flow",
        attribute="extract_percentage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="constant_flow_supply_target",
        translation_key="constant_flow_supply_target",
        component="constant_flow",
        attribute="supply_target_flow",
        native_unit_of_measurement="m³/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ThesslaGreenSensorDescription(
        key="constant_flow_extract_target",
        translation_key="constant_flow_extract_target",
        component="constant_flow",
        attribute="extract_target_flow",
        native_unit_of_measurement="m³/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThesslaGreenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thessla Green sensors."""
    coordinator = entry.runtime_data
    descriptions = list(BASE_DESCRIPTIONS)
    if coordinator.device.constant_flow is not None:
        descriptions.extend(CONSTANT_FLOW_DESCRIPTIONS)
    async_add_entities(
        ThesslaGreenSensor(coordinator, description) for description in descriptions
    )


class ThesslaGreenSensor(ThesslaGreenEntity, SensorEntity):
    """A single read-only AirPack4 value."""

    entity_description: ThesslaGreenSensorDescription

    def __init__(
        self,
        coordinator: ThesslaGreenCoordinator,
        description: ThesslaGreenSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> object:
        """Return the current library value."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        return getattr(component, self.entity_description.attribute)
