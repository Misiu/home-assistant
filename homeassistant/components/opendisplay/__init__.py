"""Integration for OpenDisplay BLE e-paper displays."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
    BLETimeoutError,
    GlobalConfig,
    OpenDisplayDevice,
    OpenDisplayError,
    PowerMode,
)

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

if TYPE_CHECKING:
    from opendisplay.models import FirmwareVersion

from .const import (
    CONF_ENCRYPTION_KEY,
    DOMAIN,
    PENDING_UPLOAD_CLEANUP_INTERVAL,
    PENDING_UPLOAD_TIMEOUT,
)
from .coordinator import OpenDisplayCoordinator
from .queue import OpenDisplayQueue
from .services import async_setup_services
from .uploader import OpenDisplayUploader

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_BASE_PLATFORMS: list[Platform] = []
_FLEX_PLATFORMS = [Platform.EVENT, Platform.SENSOR]


@dataclass
class OpenDisplayRuntimeData:
    """Runtime data for an OpenDisplay config entry."""

    coordinator: OpenDisplayCoordinator
    firmware: FirmwareVersion
    device_config: GlobalConfig
    is_flex: bool
    is_deep_sleep: bool
    queue: OpenDisplayQueue
    uploader: OpenDisplayUploader


type OpenDisplayConfigEntry = ConfigEntry[OpenDisplayRuntimeData]


def _is_deep_sleep_device(device_config: GlobalConfig) -> bool:
    """Return whether the device is configured to deep-sleep between updates.

    USB-powered devices (e.g. an always-on nRF52840 board) and battery
    devices that have no sleep timeout configured stay reachable, so the
    pending-upload queue is unnecessary for them. The queue only kicks in
    when the device tells us — via its own configuration — that it will
    actually deep-sleep.
    """
    power = device_config.power
    if power.power_mode_enum == PowerMode.USB:
        return False
    return power.sleep_timeout_ms > 0 or power.deep_sleep_time_seconds > 0


def _get_encryption_key(entry: OpenDisplayConfigEntry) -> bytes | None:
    """Return the encryption key bytes from entry data, or None."""
    raw = entry.data.get(CONF_ENCRYPTION_KEY)
    if raw is None:
        return None
    if len(raw) != 32:
        raise ConfigEntryAuthFailed(
            "Stored OpenDisplay encryption key is invalid; reauthentication required"
        )
    try:
        return bytes.fromhex(raw)
    except ValueError as err:
        raise ConfigEntryAuthFailed(
            "Stored OpenDisplay encryption key is invalid; reauthentication required"
        ) from err


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the OpenDisplay integration."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenDisplayConfigEntry) -> bool:
    """Set up OpenDisplay from a config entry."""
    address = entry.unique_id
    if TYPE_CHECKING:
        assert address is not None

    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(
            f"Could not find OpenDisplay device with address {address}"
        )

    encryption_key = _get_encryption_key(entry)

    try:
        async with OpenDisplayDevice(
            mac_address=address, ble_device=ble_device, encryption_key=encryption_key
        ) as device:
            fw = await device.read_firmware_version()
            is_flex = device.is_flex
    except (AuthenticationFailedError, AuthenticationRequiredError) as err:
        raise ConfigEntryAuthFailed(
            f"Encryption key rejected by OpenDisplay device: {err}"
        ) from err
    except (BLEConnectionError, BLETimeoutError, OpenDisplayError) as err:
        raise ConfigEntryNotReady(
            f"Failed to connect to OpenDisplay device: {err}"
        ) from err
    device_config = device.config
    if TYPE_CHECKING:
        assert device_config is not None

    coordinator = OpenDisplayCoordinator(hass, address)

    manufacturer = device_config.manufacturer
    display = device_config.displays[0]
    color_scheme_enum = display.color_scheme_enum
    color_scheme = (
        str(color_scheme_enum)
        if isinstance(color_scheme_enum, int)
        else color_scheme_enum.name
    )
    size = (
        f'{display.screen_diagonal_inches:.1f}"'
        if display.screen_diagonal_inches is not None
        else f"{display.pixel_width}x{display.pixel_height}"
    )
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_BLUETOOTH, address)},
        manufacturer=manufacturer.manufacturer_name,
        model=f"{size} {color_scheme}",
        sw_version=f"{fw['major']}.{fw['minor']}",
        hw_version=(
            f"{manufacturer.board_type_name or manufacturer.board_type}"
            f" rev. {manufacturer.board_revision}"
        )
        if is_flex
        else None,
        configuration_url="https://opendisplay.org/firmware/config/"
        if is_flex
        else None,
    )

    is_deep_sleep = _is_deep_sleep_device(device_config)
    queue = OpenDisplayQueue(PENDING_UPLOAD_TIMEOUT)
    uploader = OpenDisplayUploader(
        hass,
        entry,
        queue,
        is_deep_sleep=is_deep_sleep,
    )
    runtime_data = OpenDisplayRuntimeData(
        coordinator=coordinator,
        firmware=fw,
        device_config=device_config,
        is_flex=is_flex,
        is_deep_sleep=is_deep_sleep,
        queue=queue,
        uploader=uploader,
    )
    entry.runtime_data = runtime_data

    # Only deep-sleep devices need the advertisement-driven queue dispatch.
    if runtime_data.is_deep_sleep:
        coordinator.async_set_advertisement_callback(
            uploader.async_handle_advertisement
        )

    await hass.config_entries.async_forward_entry_setups(
        entry, _FLEX_PLATFORMS if is_flex else _BASE_PLATFORMS
    )
    entry.async_on_unload(coordinator.async_start())

    @callback
    def _purge_pending(_now: datetime) -> None:
        uploader.async_purge_expired()

    if runtime_data.is_deep_sleep:
        entry.async_on_unload(
            async_track_time_interval(
                hass,
                _purge_pending,
                PENDING_UPLOAD_CLEANUP_INTERVAL,
                name=f"opendisplay-purge-{address}",
                cancel_on_shutdown=True,
            )
        )

        @callback
        def _clear_advertisement_callback() -> None:
            coordinator.async_set_advertisement_callback(None)

        entry.async_on_unload(_clear_advertisement_callback)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OpenDisplayConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.uploader.async_shutdown()

    return await hass.config_entries.async_unload_platforms(
        entry, _FLEX_PLATFORMS if entry.runtime_data.is_flex else _BASE_PLATFORMS
    )
