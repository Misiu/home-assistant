"""Switch platform for Thessla Green."""

from dataclasses import dataclass
from typing import override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ThesslaGreenConfigEntry, ThesslaGreenCoordinator
from .entity import ThesslaGreenEntity


@dataclass(frozen=True, kw_only=True)
class ThesslaGreenSwitchDescription(SwitchEntityDescription):
    """Describe a writable boolean value in the device library."""

    component: str
    attribute: str
    inverted: bool = False


DESCRIPTIONS: tuple[ThesslaGreenSwitchDescription, ...] = (
    ThesslaGreenSwitchDescription(
        key="enabled",
        translation_key="enabled",
        component="controls",
        attribute="enabled",
    ),
    ThesslaGreenSwitchDescription(
        key="automatic_bypass",
        translation_key="automatic_bypass",
        component="bypass",
        attribute="disabled",
        inverted=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThesslaGreenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thessla Green switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        ThesslaGreenSwitch(coordinator, description) for description in DESCRIPTIONS
    )


class ThesslaGreenSwitch(ThesslaGreenEntity, SwitchEntity):
    """Represent one writable Thessla Green boolean setting."""

    entity_description: ThesslaGreenSwitchDescription

    def __init__(
        self,
        coordinator: ThesslaGreenCoordinator,
        description: ThesslaGreenSwitchDescription,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the current switch state."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        value = getattr(component, self.entity_description.attribute)
        if not isinstance(value, bool):
            return None
        return not value if self.entity_description.inverted else value

    @override
    async def async_turn_on(self, **kwargs: object) -> None:
        """Turn the setting on."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        value = not self.entity_description.inverted
        await self._async_write(component, self.entity_description.attribute, value)

    @override
    async def async_turn_off(self, **kwargs: object) -> None:
        """Turn the setting off."""
        component = getattr(self.coordinator.device, self.entity_description.component)
        value = self.entity_description.inverted
        await self._async_write(component, self.entity_description.attribute, value)
