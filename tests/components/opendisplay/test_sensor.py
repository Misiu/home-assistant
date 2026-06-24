"""Test the OpenDisplay sensor platform."""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import time
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from habluetooth import FALLBACK_MAXIMUM_STALE_ADVERTISEMENT_SECONDS
from opendisplay import voltage_to_percent
from opendisplay.models.config import PowerOption
from opendisplay.models.enums import CapacityEstimator, PowerMode
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.bluetooth.const import UNAVAILABLE_TRACK_SECONDS
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import DEVICE_CONFIG, TEST_ADDRESS, VALID_SERVICE_INFO, make_service_info

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform
from tests.components.bluetooth import (
    inject_bluetooth_service_info,
    patch_all_discovered_devices,
    patch_bluetooth_time,
)

pytestmark = pytest.mark.usefixtures("entity_registry_enabled_by_default")


@pytest.fixture
def platforms() -> list[Platform]:
    """Only set up the sensor platform."""
    return [Platform.SENSOR]


async def test_sensors_before_data(
    hass: HomeAssistant,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Test that sensors are created but unavailable before data arrives."""
    await setup_entry()

    # All sensors exist but coordinator has no data yet
    assert hass.states.get("sensor.opendisplay_1234_temperature") is not None
    assert (
        hass.states.get("sensor.opendisplay_1234_temperature").state
        == STATE_UNAVAILABLE
    )


async def test_sensor_entities_usb_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    setup_entry: Callable[[], Awaitable[None]],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test sensor entities for a USB-powered Flex device."""
    freezer.move_to("2026-06-22T08:16:15+00:00")
    await setup_entry()

    inject_bluetooth_service_info(hass, VALID_SERVICE_INFO)
    await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_sensor_entities_battery_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    setup_entry: Callable[[], Awaitable[None]],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test sensor entities for a battery-powered Flex device with LI_ION chemistry."""
    freezer.move_to("2026-06-22T08:16:19+00:00")
    device_config = deepcopy(DEVICE_CONFIG)
    power = device_config.power
    device_config.power = PowerOption(
        power_mode=PowerMode.BATTERY,
        battery_capacity_mah=power.battery_capacity_mah,
        sleep_timeout_ms=power.sleep_timeout_ms,
        tx_power=power.tx_power,
        sleep_flags=power.sleep_flags,
        battery_sense_pin=power.battery_sense_pin,
        battery_sense_enable_pin=power.battery_sense_enable_pin,
        battery_sense_flags=power.battery_sense_flags,
        capacity_estimator=1,  # LI_ION
        voltage_scaling_factor=power.voltage_scaling_factor,
        deep_sleep_current_ua=power.deep_sleep_current_ua,
        deep_sleep_time_seconds=power.deep_sleep_time_seconds,
        reserved=power.reserved,
    )
    mock_opendisplay_device.config = device_config

    await setup_entry()

    inject_bluetooth_service_info(hass, VALID_SERVICE_INFO)
    await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_battery_sensors_not_created_for_usb_devices(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Test battery sensors are not created for USB-powered devices."""
    await setup_entry()

    inject_bluetooth_service_info(hass, VALID_SERVICE_INFO)
    await hass.async_block_till_done()

    assert entity_registry.async_get("sensor.opendisplay_1234_battery") is None
    assert entity_registry.async_get("sensor.opendisplay_1234_battery_voltage") is None


async def test_no_sensors_for_non_flex_devices(
    hass: HomeAssistant,
    mock_opendisplay_device: MagicMock,
    entity_registry: er.EntityRegistry,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Test that no sensor entities are created for non-Flex devices."""
    mock_opendisplay_device.is_flex = False
    await setup_entry()

    assert entity_registry.async_get("sensor.opendisplay_1234_temperature") is None
    assert entity_registry.async_get("sensor.opendisplay_1234_battery") is None
    assert entity_registry.async_get("sensor.opendisplay_1234_battery_voltage") is None


async def test_coordinator_ignores_unknown_manufacturer(
    hass: HomeAssistant,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Test that advertisements from an unknown manufacturer ID are ignored."""
    await setup_entry()

    unknown_service_info = make_service_info(
        address=TEST_ADDRESS,
        manufacturer_data={0x9999: b"\x00" * 14},
    )
    inject_bluetooth_service_info(hass, unknown_service_info)
    await hass.async_block_till_done()

    # Coordinator ignores non-OpenDisplay advertisements; device stays unavailable
    assert (
        hass.states.get("sensor.opendisplay_1234_temperature").state
        == STATE_UNAVAILABLE
    )


async def test_sensor_goes_unavailable_when_device_disappears(
    hass: HomeAssistant,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Test that sensors become unavailable when the device stops advertising."""
    start_monotonic = time.monotonic()
    await setup_entry()

    inject_bluetooth_service_info(hass, VALID_SERVICE_INFO)
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.opendisplay_1234_temperature").state
        != STATE_UNAVAILABLE
    )

    # Must exceed both the non-connectable stale threshold (900s) and the
    # unavailability polling interval (300s) to trigger the callback.
    advance = (
        FALLBACK_MAXIMUM_STALE_ADVERTISEMENT_SECONDS + UNAVAILABLE_TRACK_SECONDS + 1
    )
    monotonic_now = start_monotonic + advance
    with (
        patch_bluetooth_time(monotonic_now),
        patch_all_discovered_devices([]),
    ):
        async_fire_time_changed(
            hass,
            dt_util.utcnow() + timedelta(seconds=advance),
        )
        await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.opendisplay_1234_temperature").state
        == STATE_UNAVAILABLE
    )


async def test_battery_sensor_defaults_to_liion_when_capacity_estimator_unset(
    hass: HomeAssistant,
    mock_opendisplay_device: MagicMock,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Test battery % uses LI_ION when capacity_estimator is 0."""
    device_config = deepcopy(DEVICE_CONFIG)
    power = device_config.power
    device_config.power = PowerOption(
        power_mode=PowerMode.BATTERY,
        battery_capacity_mah=power.battery_capacity_mah,
        sleep_timeout_ms=power.sleep_timeout_ms,
        tx_power=power.tx_power,
        sleep_flags=power.sleep_flags,
        battery_sense_pin=power.battery_sense_pin,
        battery_sense_enable_pin=power.battery_sense_enable_pin,
        battery_sense_flags=power.battery_sense_flags,
        capacity_estimator=0,  # not configured — defaults to LI_ION in sensor.py
        voltage_scaling_factor=power.voltage_scaling_factor,
        deep_sleep_current_ua=power.deep_sleep_current_ua,
        deep_sleep_time_seconds=power.deep_sleep_time_seconds,
        reserved=power.reserved,
    )
    mock_opendisplay_device.config = device_config

    await setup_entry()
    inject_bluetooth_service_info(hass, VALID_SERVICE_INFO)
    await hass.async_block_till_done()

    battery_state = hass.states.get("sensor.opendisplay_1234_battery")
    assert battery_state is not None
    # capacity_estimator=0 should fall back to LI_ION, producing
    # the same value as explicit LI_ION
    expected = voltage_to_percent(3700, CapacityEstimator.LI_ION)
    assert battery_state.state == str(expected)


async def test_deep_sleep_diagnostic_sensors(
    hass: HomeAssistant,
    mock_opendisplay_device: MagicMock,
    setup_entry: Callable[[], Awaitable[None]],
) -> None:
    """Deep sleep diagnostic sensors expose expected values."""
    device_config = deepcopy(DEVICE_CONFIG)
    power = device_config.power
    device_config.power = PowerOption(
        power_mode=power.power_mode_enum,
        battery_capacity_mah=power.battery_capacity_mah,
        sleep_timeout_ms=power.sleep_timeout_ms,
        tx_power=power.tx_power,
        sleep_flags=power.sleep_flags,
        battery_sense_pin=power.battery_sense_pin,
        battery_sense_enable_pin=power.battery_sense_enable_pin,
        battery_sense_flags=power.battery_sense_flags,
        capacity_estimator=power.capacity_estimator,
        voltage_scaling_factor=power.voltage_scaling_factor,
        deep_sleep_current_ua=power.deep_sleep_current_ua,
        deep_sleep_time_seconds=300,
        reserved=power.reserved,
    )
    mock_opendisplay_device.config = device_config

    await setup_entry()

    deep_sleep_time = hass.states.get("sensor.opendisplay_1234_deep_sleep_time")
    assert deep_sleep_time is not None
    assert deep_sleep_time.state == "300"

    expected_wakeup = hass.states.get("sensor.opendisplay_1234_expected_wake_up")
    assert expected_wakeup is not None
    assert expected_wakeup.state == STATE_UNKNOWN


async def test_expected_wakeup_uses_restored_last_seen(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    setup_entry: Callable[[], Awaitable[None]],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Restored last_seen drives expected wakeup when no fresh data is available."""
    device_config = deepcopy(DEVICE_CONFIG)
    power = device_config.power
    device_config.power = PowerOption(
        power_mode=power.power_mode_enum,
        battery_capacity_mah=power.battery_capacity_mah,
        sleep_timeout_ms=power.sleep_timeout_ms,
        tx_power=power.tx_power,
        sleep_flags=power.sleep_flags,
        battery_sense_pin=power.battery_sense_pin,
        battery_sense_enable_pin=power.battery_sense_enable_pin,
        battery_sense_flags=power.battery_sense_flags,
        capacity_estimator=power.capacity_estimator,
        voltage_scaling_factor=power.voltage_scaling_factor,
        deep_sleep_current_ua=power.deep_sleep_current_ua,
        deep_sleep_time_seconds=300,
        reserved=power.reserved,
    )
    mock_opendisplay_device.config = device_config

    await setup_entry()

    freezer.move_to("2026-06-22T10:02:00+00:00")
    restored_last_seen = datetime(2026, 6, 22, 10, 0, tzinfo=UTC)
    mock_config_entry.runtime_data.coordinator.async_restore_last_seen(
        restored_last_seen
    )
    await hass.async_block_till_done()

    expected_wakeup = hass.states.get("sensor.opendisplay_1234_expected_wake_up")
    assert expected_wakeup is not None
    assert expected_wakeup.state == "2026-06-22T10:05:00+00:00"
