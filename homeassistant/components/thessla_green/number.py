"""Number platform for Thessla Green AirPack4."""

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ThesslaGreenConfigEntry, ThesslaGreenCoordinator
from .entity import ThesslaGreenEntity


@dataclass(frozen=True, kw_only=True)
class ThesslaGreenNumberDescription(NumberEntityDescription):
    """Describe a writable numeric value in the device library."""

    component: str
    attribute: str


BASE_DESCRIPTIONS: tuple[ThesslaGreenNumberDescription, ...] = (
    ThesslaGreenNumberDescription(
        key="manual_speed",
        translation_key="manual_speed",
        component="controls",
        attribute="manual_speed",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThesslaGreenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thessla Green number entities."""
    coordinator = entry.runtime_data
    descriptions = list(BASE_DESCRIPTIONS)
    if coordinator.device.comfort is not None:
        descriptions.append(
            ThesslaGreenNumberDescription(
                key="comfort_temperature",
                translation_key="comfort_temperature",
                component="comfort",
                attribute="manual_temperature",
                native_min_value=10,
                native_max_value=45,
                native_step=0.5,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                mode=NumberMode.BOX,
            )
        )
    async_add_entities(
        ThesslaGreenNumber(coordinator, description) for description in descriptions
    )


class ThesslaGreenNumber(ThesslaGreenEntity, NumberEntity):
    """Represent one writable AirPack4 numeric setting."""

    entity_description: ThesslaGreenNumberDescription

    def __init__(
        self,
        coordinator: ThesslaGreenCoordinator,
        description: ThesslaGreenNumberDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the current numeric value."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        value = getattr(component, self.entity_description.attribute)
        return float(value) if isinstance(value, int | float) else None

    async def async_set_native_value(self, value: float) -> None:
        """Write a validated numeric value to the controller."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        await self._async_write(component, self.entity_description.attribute, value)
