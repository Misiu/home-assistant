"""Select platform for Thessla Green."""

from dataclasses import dataclass
from enum import IntEnum

from thessla_green_modbus import (
    ComfortMode,
    ErvMode,
    OperatingMode,
    Season,
    SpecialMode,
)

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ThesslaGreenConfigEntry, ThesslaGreenCoordinator
from .entity import ThesslaGreenEntity


@dataclass(frozen=True, kw_only=True)
class ThesslaGreenSelectDescription(SelectEntityDescription):
    """Describe a writable enum value in the device library."""

    component: str
    attribute: str
    enum_type: type[IntEnum]
    values: tuple[IntEnum, ...]


def _options(values: tuple[IntEnum, ...]) -> list[str]:
    return [value.name.lower() for value in values]


OPERATING_MODES = (OperatingMode.AUTOMATIC, OperatingMode.MANUAL)
SPECIAL_MODES = (
    SpecialMode.NONE,
    SpecialMode.FIREPLACE,
    SpecialMode.AIRING,
    SpecialMode.OPEN_WINDOWS,
    SpecialMode.EMPTY_HOUSE,
)

BASE_DESCRIPTIONS: tuple[ThesslaGreenSelectDescription, ...] = (
    ThesslaGreenSelectDescription(
        key="operating_mode",
        translation_key="operating_mode",
        component="controls",
        attribute="operating_mode",
        enum_type=OperatingMode,
        values=OPERATING_MODES,
        options=_options(OPERATING_MODES),
    ),
    ThesslaGreenSelectDescription(
        key="season",
        translation_key="season",
        component="controls",
        attribute="season",
        enum_type=Season,
        values=tuple(Season),
        options=_options(tuple(Season)),
    ),
    ThesslaGreenSelectDescription(
        key="special_mode",
        translation_key="special_mode",
        component="controls",
        attribute="special_mode",
        enum_type=SpecialMode,
        values=SPECIAL_MODES,
        options=_options(SPECIAL_MODES),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThesslaGreenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thessla Green select entities."""
    coordinator = entry.runtime_data
    descriptions = list(BASE_DESCRIPTIONS)
    if coordinator.device.comfort is not None:
        values = tuple(ComfortMode)
        descriptions.append(
            ThesslaGreenSelectDescription(
                key="comfort_mode",
                translation_key="comfort_mode",
                component="comfort",
                attribute="mode",
                enum_type=ComfortMode,
                values=values,
                options=_options(values),
            )
        )
    if coordinator.device.erv is not None:
        values = tuple(ErvMode)
        descriptions.append(
            ThesslaGreenSelectDescription(
                key="erv_mode",
                translation_key="erv_mode",
                component="erv",
                attribute="mode",
                enum_type=ErvMode,
                values=values,
                options=_options(values),
            )
        )
    async_add_entities(
        ThesslaGreenSelect(coordinator, description) for description in descriptions
    )


class ThesslaGreenSelect(ThesslaGreenEntity, SelectEntity):
    """Represent one writable Thessla Green enum setting."""

    entity_description: ThesslaGreenSelectDescription

    def __init__(
        self,
        coordinator: ThesslaGreenCoordinator,
        description: ThesslaGreenSelectDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        value = getattr(component, self.entity_description.attribute)
        if value not in self.entity_description.values:
            return None
        return value.name.lower()

    async def async_select_option(self, option: str) -> None:
        """Write the selected option to the controller."""
        for value in self.entity_description.values:
            if value.name.lower() == option:
                component = getattr(
                    self.coordinator.device, self.entity_description.component
                )
                await self._async_write(
                    component, self.entity_description.attribute, value
                )
                return
        raise ValueError(f"Unsupported option: {option}")
