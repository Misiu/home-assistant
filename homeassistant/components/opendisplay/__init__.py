"""Integration for OpenDisplay BLE e-paper displays."""

import asyncio
from collections.abc import Mapping
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, cast

from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
    BLETimeoutError,
    GlobalConfig,
    OpenDisplayDevice,
    OpenDisplayError,
)
from opendisplay.models import FirmwareVersion

from homeassistant.components.bluetooth import (
    BluetoothReachabilityIntent,
    async_address_reachability_diagnostics,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.json import JsonObjectType, JsonValueType

if TYPE_CHECKING:
    from .services import PendingDisplayUpload

from .cache import deserialize_device_config, serialize_device_config
from .const import CONF_ENCRYPTION_KEY, DOMAIN
from .coordinator import OpenDisplayCoordinator
from .deep_sleep import deep_sleep_seconds, deep_sleep_timeout_margin_minutes
from .services import async_register_pending_upload_listener, async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

BASE_PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]
FLEX_PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]

STORAGE_VERSION = 1


@dataclass(frozen=True)
class OpenDisplayStoredData:
    """Stored device metadata used to survive sleeping-device restarts."""

    firmware: FirmwareVersion
    device_config: GlobalConfig
    is_flex: bool


class OpenDisplayStoredDataDict(TypedDict):
    """Serialized metadata shape stored in config entry data."""

    version: int
    firmware: JsonObjectType
    device_config: JsonObjectType
    is_flex: bool


@dataclass
class OpenDisplayRuntimeData:
    """Runtime data for an OpenDisplay config entry."""

    coordinator: OpenDisplayCoordinator
    firmware: FirmwareVersion
    device_config: GlobalConfig
    is_flex: bool
    upload_task: asyncio.Task[None] | None = None
    pending_upload: PendingDisplayUpload | None = None
    pending_upload_task: asyncio.Task[None] | None = None
    pending_upload_expiry_unsub: CALLBACK_TYPE | None = None


def _serialize_stored_data(
    stored_data: OpenDisplayStoredData,
) -> OpenDisplayStoredDataDict:
    """Serialize stored device metadata for config entry storage."""
    firmware_data: JsonObjectType = {
        "major": cast(JsonValueType, stored_data.firmware["major"]),
        "minor": cast(JsonValueType, stored_data.firmware["minor"]),
        "sha": cast(JsonValueType, stored_data.firmware["sha"]),
    }
    return {
        "version": STORAGE_VERSION,
        "firmware": firmware_data,
        "device_config": serialize_device_config(stored_data.device_config),
        "is_flex": stored_data.is_flex,
    }


def _deserialize_stored_data(
    data: Mapping[str, JsonValueType] | None,
) -> OpenDisplayStoredData | None:
    """Deserialize stored device metadata from config entry storage."""
    if data is None:
        return None

    if data.get("version") != STORAGE_VERSION:
        return None

    firmware = data.get("firmware")
    device_config_data = data.get("device_config")
    is_flex = data.get("is_flex")
    if (
        not isinstance(firmware, dict)
        or not isinstance(device_config_data, dict)
        or not isinstance(is_flex, bool)
    ):
        return None

    try:
        device_config = deserialize_device_config(device_config_data)
    except TypeError, ValueError:
        return None

    return OpenDisplayStoredData(
        firmware=cast(FirmwareVersion, firmware),
        device_config=device_config,
        is_flex=is_flex,
    )


def _store_entry_metadata(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    firmware: FirmwareVersion,
    device_config: GlobalConfig,
    is_flex: bool,
) -> None:
    """Persist device metadata needed to restore sleeping devices after restart."""
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "stored_data": _serialize_stored_data(
                OpenDisplayStoredData(
                    firmware=firmware,
                    device_config=device_config,
                    is_flex=is_flex,
                )
            ),
        },
    )


type OpenDisplayConfigEntry = ConfigEntry[OpenDisplayRuntimeData]


def _get_encryption_key(entry: OpenDisplayConfigEntry) -> bytes | None:
    """Return the encryption key bytes from entry data, or None."""
    raw = entry.data.get(CONF_ENCRYPTION_KEY)
    if raw is None:
        return None
    if len(raw) != 32:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_error",
        )
    try:
        return bytes.fromhex(raw)
    except ValueError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_error",
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
    encryption_key = _get_encryption_key(entry)

    fw: FirmwareVersion
    device_config: GlobalConfig
    is_flex: bool
    if ble_device is None:
        stored = _deserialize_stored_data(entry.data.get("stored_data", {}))
        if stored is None:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={
                    "address": address,
                    "reason": async_address_reachability_diagnostics(
                        hass,
                        address.upper(),
                        BluetoothReachabilityIntent.CONNECTION,
                    ),
                },
            )
        fw = stored.firmware
        device_config = stored.device_config
        is_flex = stored.is_flex
        if deep_sleep_seconds(device_config) <= 0:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={
                    "address": address,
                    "reason": async_address_reachability_diagnostics(
                        hass,
                        address.upper(),
                        BluetoothReachabilityIntent.CONNECTION,
                    ),
                },
            )
    else:
        try:
            async with OpenDisplayDevice(
                mac_address=address,
                ble_device=ble_device,
                encryption_key=encryption_key,
            ) as device:
                fw = await device.read_firmware_version()
                is_flex = device.is_flex
                loaded_device_config = device.config
        except (AuthenticationFailedError, AuthenticationRequiredError) as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_error",
            ) from err
        except (BLEConnectionError, BLETimeoutError, OpenDisplayError) as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="setup_connection_error",
            ) from err
        if loaded_device_config is None:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="setup_connection_error",
            )
        device_config = loaded_device_config
        _store_entry_metadata(hass, entry, fw, device_config, is_flex)

    coordinator = OpenDisplayCoordinator(
        hass,
        address,
        deep_sleep_time_seconds=deep_sleep_seconds(device_config),
        deep_sleep_timeout_margin_minutes=deep_sleep_timeout_margin_minutes(
            entry.options
        ),
    )

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

    entry.runtime_data = OpenDisplayRuntimeData(
        coordinator=coordinator,
        firmware=fw,
        device_config=device_config,
        is_flex=is_flex,
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, FLEX_PLATFORMS if is_flex else BASE_PLATFORMS
    )
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(async_register_pending_upload_listener(hass, entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OpenDisplayConfigEntry
) -> bool:
    """Unload a config entry."""
    if (task := entry.runtime_data.upload_task) and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    if (task := entry.runtime_data.pending_upload_task) and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    entry.runtime_data.pending_upload_task = None
    entry.runtime_data.pending_upload = None
    if (unsub := entry.runtime_data.pending_upload_expiry_unsub) is not None:
        unsub()
        entry.runtime_data.pending_upload_expiry_unsub = None

    return await hass.config_entries.async_unload_platforms(
        entry, FLEX_PLATFORMS if entry.runtime_data.is_flex else BASE_PLATFORMS
    )
