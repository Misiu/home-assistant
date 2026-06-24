"""Sensor platform for OpenDisplay devices."""

from collections.abc import Callable
from dataclasses import dataclass
<<<<<<< HEAD
from typing import override
=======
from datetime import datetime
import logging
from typing import cast
>>>>>>> d276142b19e (feat(opendisplay): implement pending upload handling for deep sleep devices)

from opendisplay import voltage_to_percent
from opendisplay.models.enums import CapacityEstimator, PowerMode

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import OpenDisplayConfigEntry
from .coordinator import OpenDisplayUpdate
from .entity import OpenDisplayEntity

PARALLEL_UPDATES = 0
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class OpenDisplaySensorEntityDescription(SensorEntityDescription):
    """Describes an OpenDisplay sensor entity."""

    value_fn: Callable[[OpenDisplayUpdate], float | int | datetime | None]


_TEMPERATURE_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="temperature",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda upd: upd.advertisement.temperature_c,
)

_LAST_SEEN_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="last_seen",
    translation_key="last_seen",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda upd: (
        dt_util.utc_from_timestamp(upd.last_seen) if upd.last_seen is not None else None
    ),
)

_DEEP_SLEEP_TIME_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="deep_sleep_time",
    translation_key="deep_sleep_time",
    device_class=SensorDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda _adv: None,
)

_EXPECTED_WAKEUP_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="expected_wakeup",
    translation_key="expected_wakeup",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda _adv: None,
)

_BATTERY_POWER_MODES = {PowerMode.BATTERY, PowerMode.SOLAR}

_BATTERY_VOLTAGE_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="battery_voltage",
    translation_key="battery_voltage",
    device_class=SensorDeviceClass.VOLTAGE,
    native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda upd: upd.advertisement.battery_mv,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OpenDisplay sensor entities."""
    coordinator = entry.runtime_data.coordinator
    power_config = entry.runtime_data.device_config.power
    descriptions: list[OpenDisplaySensorEntityDescription] = [
        _TEMPERATURE_DESCRIPTION,
        _LAST_SEEN_DESCRIPTION,
        _DEEP_SLEEP_TIME_DESCRIPTION,
        _EXPECTED_WAKEUP_DESCRIPTION,
    ]

    if power_config.power_mode_enum in _BATTERY_POWER_MODES:
        capacity_estimator = power_config.capacity_estimator or CapacityEstimator.LI_ION
        descriptions += [
            _BATTERY_VOLTAGE_DESCRIPTION,
            OpenDisplaySensorEntityDescription(
                key="battery",
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
                value_fn=lambda upd: voltage_to_percent(
                    upd.advertisement.battery_mv, capacity_estimator
                ),
            ),
        ]

    async_add_entities(
        OpenDisplaySensorEntity(coordinator, description)
        for description in descriptions
    )


class OpenDisplaySensorEntity(OpenDisplayEntity, RestoreSensor):
    """A sensor entity for an OpenDisplay device."""

    entity_description: OpenDisplaySensorEntityDescription

    def __init__(
        self,
        coordinator,
        description: OpenDisplaySensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, description)
        self._attr_native_value: float | int | datetime | None = None

    @property
<<<<<<< HEAD
    @override
    def native_value(self) -> float | int | None:
=======
    def available(self) -> bool:
        """Return whether sensor data is available."""
        if self.entity_description.key in ("deep_sleep_time", "expected_wakeup"):
            return True
        return self.coordinator.available

    @property
    def _restore_when_sleeping(self) -> bool:
        """Return whether this sensor can keep restored values while sleeping."""
        return self.coordinator.deep_sleep_time_seconds > 0

    async def async_added_to_hass(self) -> None:
        """Restore last known state for sleeping devices."""
        await super().async_added_to_hass()
        if not self._restore_when_sleeping or self._attr_native_value is not None:
            return

        if (last_sensor_data := await self.async_get_last_sensor_data()) is None:
            return

        self._attr_native_value = cast(
            float | int | datetime | None,
            last_sensor_data.native_value,
        )
        _LOGGER.debug(
            "%s: Restored state for %s = %s",
            self.coordinator.address,
            self.entity_description.key,
            self._attr_native_value,
        )
        if self.entity_description.key == "last_seen":
            self.coordinator.async_restore_last_seen(self._attr_native_value)

    @property
    def native_value(self) -> float | int | datetime | None:
>>>>>>> d276142b19e (feat(opendisplay): implement pending upload handling for deep sleep devices)
        """Return the sensor value."""
        if self.entity_description.key == "deep_sleep_time":
            self._attr_native_value = self.coordinator.deep_sleep_time_seconds
            return self._attr_native_value

        if self.entity_description.key == "expected_wakeup":
            if self.coordinator.expected_wakeup_timestamp is not None:
                self._attr_native_value = self.coordinator.expected_wakeup_timestamp
            return self._attr_native_value

        if self.coordinator.data is not None:
            self._attr_native_value = self.entity_description.value_fn(
                self.coordinator.data
            )
        elif not self._restore_when_sleeping:
            return None

        return self._attr_native_value
