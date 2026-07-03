"""Service registration for the OpenDisplay integration."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
import io
from typing import TYPE_CHECKING, NotRequired, TypedDict, TypeVar, cast

import aiohttp
from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
    BLETimeoutError,
    DitherMode,
    FitMode,
    OpenDisplayDevice,
    OpenDisplayError,
    RefreshMode,
    Rotation,
)
from PIL import Image as PILImage, ImageOps
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothReachabilityIntent,
    async_address_reachability_diagnostics,
    async_ble_device_from_address,
)
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_source import async_resolve_media
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.network import get_url
from homeassistant.helpers.selector import MediaSelector, MediaSelectorConfig
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from . import OpenDisplayConfigEntry

from .const import (
    CONF_ENCRYPTION_KEY,
    DOMAIN,
    SIGNAL_DEVICE_SEEN,
    SIGNAL_PENDING_UPLOAD,
)
from .deep_sleep import (
    availability_window_seconds,
    deep_sleep_enabled,
    deep_sleep_seconds,
    deep_sleep_timeout_margin_minutes,
)

ATTR_IMAGE = "image"
ATTR_ROTATION = "rotation"
ATTR_DITHER_MODE = "dither_mode"
ATTR_REFRESH_MODE = "refresh_mode"
ATTR_FIT_MODE = "fit_mode"
ATTR_TONE_COMPRESSION = "tone_compression"
_PENDING_UPLOAD_WAKE_SETTLE_DELAY_SECONDS = 3
_EnumT = TypeVar("_EnumT", bound=IntEnum)


class _ImageSelectorPayload(TypedDict):
    """Shape returned by the media selector in service data."""

    media_content_id: str
    media_content_type: NotRequired[str]


class _DeferredPendingUploadError(HomeAssistantError):
    """Raised when an upload should be retried on the next wake-up."""


@dataclass(slots=True)
class PendingDisplayUpload:
    """Image payload waiting for the next wake-up window."""

    image: PILImage.Image
    dither_mode: DitherMode
    refresh_mode: RefreshMode
    fit: FitMode = FitMode.CONTAIN
    tone: float | str = "auto"
    rotate: Rotation = Rotation.ROTATE_0
    created_at: datetime = field(default_factory=dt_util.utcnow)
    expires_at: datetime | None = None


def _str_to_int_enum(enum_class: type[_EnumT]) -> Callable[[str], _EnumT]:
    """Convert a lowercase enum name string to an enum member."""
    members = {m.name.lower(): m for m in enum_class}

    def validate(value: str) -> _EnumT:
        if (result := members.get(value)) is None:
            raise vol.Invalid(f"Invalid value: {value}")
        return result

    return validate


SCHEMA_UPLOAD_IMAGE = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_IMAGE): MediaSelector(
            MediaSelectorConfig(accept=["image/*"])
        ),
        vol.Optional(ATTR_ROTATION, default=Rotation.ROTATE_0): vol.All(
            vol.Coerce(int), vol.Coerce(Rotation)
        ),
        vol.Optional(ATTR_DITHER_MODE, default="burkes"): _str_to_int_enum(DitherMode),
        vol.Optional(ATTR_REFRESH_MODE, default="full"): _str_to_int_enum(RefreshMode),
        vol.Optional(ATTR_FIT_MODE, default="contain"): _str_to_int_enum(FitMode),
        vol.Optional(ATTR_TONE_COMPRESSION): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
    }
)


def _get_entry_for_device(call: ServiceCall) -> OpenDisplayConfigEntry:
    """Return the config entry for the device targeted by a service call."""
    device_id: str = call.data[ATTR_DEVICE_ID]
    device_registry = dr.async_get(call.hass)

    if (device := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )

    mac_address = next(
        (conn[1] for conn in device.connections if conn[0] == CONNECTION_BLUETOOTH),
        None,
    )
    if mac_address is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )

    entry = call.hass.config_entries.async_entry_for_domain_unique_id(
        DOMAIN, mac_address
    )
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="config_entry_not_found",
            translation_placeholders={"address": mac_address},
        )

    return entry


def _load_image(path: str) -> PILImage.Image:
    """Load an image from disk and apply EXIF orientation."""
    image = PILImage.open(path)
    image.load()
    return ImageOps.exif_transpose(image)


def _load_image_from_bytes(data: bytes) -> PILImage.Image:
    """Load an image from bytes and apply EXIF orientation."""
    image = PILImage.open(io.BytesIO(data))
    image.load()
    return ImageOps.exif_transpose(image)


async def _async_download_image(hass: HomeAssistant, url: str) -> PILImage.Image:
    """Download an image from a URL and return a PIL Image."""
    if not url.startswith(("http://", "https://")):
        url = get_url(hass) + async_sign_path(
            hass, url, timedelta(minutes=5), use_content_user=True
        )
    session = async_get_clientsession(hass)
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except aiohttp.ClientError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="media_download_error",
            translation_placeholders={"error": str(err)},
        ) from err

    return await hass.async_add_executor_job(_load_image_from_bytes, data)


def _pending_upload_timeout_seconds(entry: OpenDisplayConfigEntry) -> int:
    """Return time a pending upload may wait for a sleeping device."""
    availability_window = int(
        getattr(
            entry.runtime_data.coordinator,
            "deep_sleep_availability_window_seconds",
            0,
        )
        or 0
    )
    if availability_window > 0:
        return availability_window

    return availability_window_seconds(
        deep_sleep_seconds(entry.runtime_data.device_config),
        deep_sleep_timeout_margin_minutes(entry.options),
    )


def _cancel_pending_upload_expiry(entry: OpenDisplayConfigEntry) -> None:
    """Cancel pending upload expiry callback if present."""
    if (unsub := entry.runtime_data.pending_upload_expiry_unsub) is None:
        return
    unsub()
    entry.runtime_data.pending_upload_expiry_unsub = None


def _cancel_pending_upload_task(entry: OpenDisplayConfigEntry) -> None:
    """Cancel in-flight pending upload task if present."""
    task = entry.runtime_data.pending_upload_task
    if task is None or task.done():
        return
    task.cancel()
    entry.runtime_data.pending_upload_task = None


def _clear_pending_upload(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    *,
    cancel_task: bool,
) -> None:
    """Clear pending upload state and notify entities."""
    if cancel_task:
        _cancel_pending_upload_task(entry)
    _cancel_pending_upload_expiry(entry)
    entry.runtime_data.pending_upload = None
    entry.runtime_data.coordinator.async_set_pending_upload(False)
    async_dispatcher_send(hass, f"{SIGNAL_PENDING_UPLOAD}_{entry.unique_id}")


def _schedule_pending_upload_expiry(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    pending: PendingDisplayUpload,
) -> int:
    """Schedule pending upload expiry and return timeout in seconds."""
    timeout_seconds = _pending_upload_timeout_seconds(entry)
    pending.expires_at = dt_util.utcnow() + timedelta(seconds=timeout_seconds)
    _cancel_pending_upload_expiry(entry)

    @callback
    def _expire_pending_upload(_now: datetime) -> None:
        if entry.runtime_data.pending_upload is not pending:
            return
        _clear_pending_upload(hass, entry, cancel_task=True)

    entry.runtime_data.pending_upload_expiry_unsub = async_call_later(
        hass,
        timeout_seconds,
        _expire_pending_upload,
    )
    return timeout_seconds


def _replace_pending_upload(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    pending: PendingDisplayUpload,
) -> int:
    """Replace queued upload with a new one (single-slot queue per device)."""
    _clear_pending_upload(hass, entry, cancel_task=True)
    entry.runtime_data.pending_upload = pending
    timeout_seconds = _schedule_pending_upload_expiry(hass, entry, pending)
    entry.runtime_data.coordinator.async_set_pending_upload(True)
    async_dispatcher_send(hass, f"{SIGNAL_PENDING_UPLOAD}_{entry.unique_id}")
    return timeout_seconds


async def _async_send_image_now(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    pending: PendingDisplayUpload,
) -> None:
    """Send image to device immediately."""
    address = entry.unique_id
    assert address is not None

    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise _DeferredPendingUploadError(
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

    raw_key = entry.data.get(CONF_ENCRYPTION_KEY)
    if raw_key is not None and len(raw_key) != 32:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        )
    try:
        encryption_key = bytes.fromhex(raw_key) if raw_key is not None else None
    except ValueError as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        ) from err

    try:
        async with OpenDisplayDevice(
            mac_address=address,
            ble_device=ble_device,
            config=entry.runtime_data.device_config,
            encryption_key=encryption_key,
        ) as device:
            await device.upload_image(
                pending.image,
                refresh_mode=pending.refresh_mode,
                dither_mode=pending.dither_mode,
                tone=pending.tone,
                fit=pending.fit,
                rotate=pending.rotate,
            )
    except (BLEConnectionError, BLETimeoutError) as err:
        raise _DeferredPendingUploadError(
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
        ) from err
    except (AuthenticationFailedError, AuthenticationRequiredError) as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        ) from err
    except OpenDisplayError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="upload_error"
        ) from err


async def _async_queue_or_send_image(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    pending: PendingDisplayUpload,
) -> None:
    """Send immediately when awake, otherwise keep one pending upload."""
    is_deep_sleep = deep_sleep_enabled(entry.runtime_data.device_config)
    coordinator = entry.runtime_data.coordinator

    if not is_deep_sleep:
        _clear_pending_upload(hass, entry, cancel_task=True)
        await _async_send_image_now(hass, entry, pending)
        return

    address = entry.unique_id
    assert address is not None

    if (
        coordinator.available
        and async_ble_device_from_address(hass, address, connectable=True) is not None
    ):
        try:
            await _async_send_image_now(hass, entry, pending)
        except _DeferredPendingUploadError:
            _replace_pending_upload(hass, entry, pending)
            return
        _clear_pending_upload(hass, entry, cancel_task=True)
        return

    _replace_pending_upload(hass, entry, pending)


async def _async_try_pending_upload(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
) -> None:
    """Try to flush queued upload when a new advertisement arrives."""
    pending = entry.runtime_data.pending_upload
    if pending is None:
        _clear_pending_upload(hass, entry, cancel_task=False)
        return

    address = entry.unique_id
    assert address is not None

    if pending.expires_at is not None and dt_util.utcnow() >= pending.expires_at:
        _clear_pending_upload(hass, entry, cancel_task=True)
        return

    if async_ble_device_from_address(hass, address, connectable=True) is None:
        return

    if (task := entry.runtime_data.pending_upload_task) is not None and not task.done():
        return

    async def _runner() -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(_PENDING_UPLOAD_WAKE_SETTLE_DELAY_SECONDS)
            if entry.runtime_data.pending_upload is not pending:
                return
            await _async_send_image_now(hass, entry, pending)
            if entry.runtime_data.pending_upload is pending:
                _clear_pending_upload(hass, entry, cancel_task=False)
        except HomeAssistantError:
            # Keep queued upload for the next wake-up until expiry window.
            return
        finally:
            if entry.runtime_data.pending_upload_task is current_task:
                entry.runtime_data.pending_upload_task = None

    entry.runtime_data.pending_upload_task = hass.async_create_task(
        _runner(),
        name=f"opendisplay_pending_upload_{address}",
    )


def async_register_pending_upload_listener(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
) -> Callable[[], None]:
    """Register listener that tries pending upload on device-seen signal."""
    address = entry.unique_id
    assert address is not None

    @callback
    def _schedule_try_pending_upload() -> None:
        if entry.runtime_data.pending_upload is None:
            return
        hass.async_create_task(
            _async_try_pending_upload(hass, entry),
            name=f"opendisplay_try_pending_{address}",
        )

    return async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_SEEN}_{address}",
        _schedule_try_pending_upload,
    )


async def _async_upload_image(call: ServiceCall) -> None:
    """Handle the upload_image service call."""
    entry = _get_entry_for_device(call)
    image_data = cast(_ImageSelectorPayload, call.data[ATTR_IMAGE])
    rotation: Rotation = call.data[ATTR_ROTATION]
    dither_mode: DitherMode = call.data[ATTR_DITHER_MODE]
    refresh_mode: RefreshMode = call.data[ATTR_REFRESH_MODE]
    fit_mode: FitMode = call.data[ATTR_FIT_MODE]
    tone_compression_pct = cast(float | None, call.data.get(ATTR_TONE_COMPRESSION))
    tone_compression: float | str = (
        tone_compression_pct / 100.0 if tone_compression_pct is not None else "auto"
    )

    # For non-deep-sleep devices, fail early if the device is not reachable so
    # we avoid fetching media unnecessarily.
    address = entry.unique_id
    assert address is not None
    if not deep_sleep_enabled(entry.runtime_data.device_config):
        if async_ble_device_from_address(call.hass, address, connectable=True) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={
                    "address": address,
                    "reason": async_address_reachability_diagnostics(
                        call.hass,
                        address.upper(),
                        BluetoothReachabilityIntent.CONNECTION,
                    ),
                },
            )

    current = asyncio.current_task()
    if (prev := entry.runtime_data.upload_task) is not None and not prev.done():
        prev.cancel()
        await asyncio.wait({prev})
    entry.runtime_data.upload_task = current

    try:
        media = await async_resolve_media(
            call.hass, image_data["media_content_id"], None
        )

        if media.path is not None:
            pil_image = await call.hass.async_add_executor_job(
                _load_image, str(media.path)
            )
        else:
            pil_image = await _async_download_image(call.hass, media.url)

        await _async_queue_or_send_image(
            call.hass,
            entry,
            PendingDisplayUpload(
                image=pil_image,
                dither_mode=dither_mode,
                refresh_mode=refresh_mode,
                fit=fit_mode,
                tone=tone_compression,
                rotate=rotation,
            ),
        )
    except asyncio.CancelledError:
        return
    finally:
        if entry.runtime_data.upload_task is current:
            entry.runtime_data.upload_task = None


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register OpenDisplay services."""
    hass.services.async_register(
        DOMAIN,
        "upload_image",
        _async_upload_image,
        schema=SCHEMA_UPLOAD_IMAGE,
    )
