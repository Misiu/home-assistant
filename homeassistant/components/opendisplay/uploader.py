"""Upload dispatcher for the OpenDisplay integration.

Owns the per-device asyncio lock that serialises BLE uploads, drives the
``OpenDisplayQueue``, and is invoked by the coordinator whenever the device
is seen advertising again.

When a new image arrives while another upload is in progress it is *not*
cancelled — interrupting a BLE transfer mid-frame can leave some e-paper
panels in a partially-written state. Instead, the new image goes into the
queue and is sent immediately after the current upload completes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
    BLETimeoutError,
    OpenDisplayDevice,
    OpenDisplayError,
)
from PIL import Image as PILImage

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_ENCRYPTION_KEY, DOMAIN
from .queue import OpenDisplayQueue, PendingUpload

if TYPE_CHECKING:
    from . import OpenDisplayConfigEntry

_LOGGER = logging.getLogger(__name__)


class OpenDisplayUploader:
    """Dispatch image uploads to a single OpenDisplay device.

    The uploader serialises every BLE upload behind a single ``asyncio.Lock``
    so the in-flight upload is never preempted. New images that arrive while
    an upload is running, or while the device is asleep, are placed in a
    single-slot queue (latest wins) and flushed automatically when the lock
    is released or when the coordinator reports a new advertisement.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OpenDisplayConfigEntry,
        queue: OpenDisplayQueue,
        *,
        is_deep_sleep: bool,
    ) -> None:
        """Initialize the uploader for the given config entry.

        ``is_deep_sleep`` is taken from the device's reported power
        configuration. When ``False`` (always-on devices like a USB-powered
        nRF52840 board) the uploader bypasses the queue entirely and behaves
        exactly like the original synchronous upload path: any error is
        surfaced immediately to the service caller.
        """
        self.hass = hass
        self.entry = entry
        self.queue = queue
        self.is_deep_sleep = is_deep_sleep
        self._lock = asyncio.Lock()
        self._upload_task: asyncio.Task[Any] | None = None
        self._dispatch_task: asyncio.Task[Any] | None = None
        self._defer_dispatch_until_advertisement = False
        self._shutdown = False

    @property
    def address(self) -> str:
        """Return the BLE address of the device."""
        address = self.entry.unique_id
        if TYPE_CHECKING:
            assert address is not None
        return address

    def _resolve_encryption_key(self) -> bytes | None:
        """Return the encryption key bytes, starting reauth if it is invalid."""
        raw_key: str | None = self.entry.data.get(CONF_ENCRYPTION_KEY)
        if raw_key is None:
            return None
        if len(raw_key) != 32:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="authentication_error"
            )
        try:
            return bytes.fromhex(raw_key)
        except ValueError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="authentication_error"
            ) from err

    async def _async_perform_upload(
        self, image: PILImage.Image, params: dict[str, Any]
    ) -> None:
        """Open a BLE connection and push the image to the device.

        Raises ``HomeAssistantError`` (with a translated key) on auth or BLE
        errors, matching the pre-existing service contract. The caller owns
        the per-device lock for the duration of this call.
        """
        address = self.address
        ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
        if ble_device is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"address": address},
            )

        encryption_key = self._resolve_encryption_key()

        try:
            async with OpenDisplayDevice(
                mac_address=address,
                ble_device=ble_device,
                config=self.entry.runtime_data.device_config,
                encryption_key=encryption_key,
            ) as device:
                await device.upload_image(image, **params)
        except (AuthenticationFailedError, AuthenticationRequiredError) as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="authentication_error"
            ) from err
        except (BLEConnectionError, BLETimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="ble_error"
            ) from err
        except OpenDisplayError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="upload_error"
            ) from err

    def _device_connectable(self) -> bool:
        """Return whether the device has a connectable BLE adapter right now."""
        return (
            async_ble_device_from_address(self.hass, self.address, connectable=True)
            is not None
        )

    @staticmethod
    def _is_auth_error(err: HomeAssistantError) -> bool:
        """Return whether an upload error is authentication-related."""
        return err.translation_key == "authentication_error"

    @staticmethod
    def _is_transient_error(err: HomeAssistantError) -> bool:
        """Return whether an upload error can be retried on the next advertisement."""
        return err.translation_key in ("device_not_found", "ble_error")

    def _queue_upload(self, image: PILImage.Image, params: dict[str, Any]) -> None:
        """Queue an upload for the next advertisement."""
        self.queue.set_pending(image, params)
        _LOGGER.info(
            "Image queued for OpenDisplay device %s; will upload when ready",
            self.address,
        )

    def _keep_newer_pending_upload(self) -> bool:
        """Return whether a newer pending upload should win over the current one."""
        if not self.queue.has_pending:
            return False
        _LOGGER.info(
            (
                "Not restoring failed OpenDisplay upload for device %s because a"
                " newer image is queued"
            ),
            self.address,
        )
        return True

    async def async_enqueue(
        self, image: PILImage.Image, params: dict[str, Any]
    ) -> None:
        """Upload the image now if the device is awake, otherwise queue it.

        - Always-on device (``is_deep_sleep=False``) → upload immediately and
          surface any error to the caller; the queue is never used.
        - Deep-sleep device, connectable, and idle → upload immediately.
          Authentication and non-retryable upload errors still surface to the
          caller; transient BLE failures queue the image for the next
          advertisement because the Bluetooth cache can outlive the wake window.
        - Deep-sleep device but an upload is in flight → queue and return;
          the running upload will pick up the new image when it finishes.
        - Deep-sleep device not connectable (asleep or out of range) → queue
          and return; the coordinator will trigger us when the device next
          advertises.
        """
        if self._shutdown:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"address": self.address},
            )

        if not self.is_deep_sleep:
            # Always-on devices: behave like the pre-queue implementation —
            # block on the lock if needed and propagate any failure.
            await self._run_immediate_upload(image, params)
            return

        if not self._lock.locked() and self._device_connectable():
            self.queue.clear()
            try:
                await self._run_immediate_upload(
                    image, params, defer_dispatch_on_transient_error=True
                )
            except HomeAssistantError as err:
                if self._is_auth_error(err):
                    self.queue.clear()
                    raise
                if not self._is_transient_error(err):
                    raise
                if self._keep_newer_pending_upload():
                    return
                self._queue_upload(image, params)
            return

        # Either asleep, not connectable, or another upload is running.
        # Replace any existing pending entry — the latest image wins.
        self._queue_upload(image, params)

        # If an upload is currently running on a connectable device, schedule
        # a dispatch so the queued image is sent as soon as the lock frees.
        if self._device_connectable():
            self._schedule_dispatch()

    async def _run_immediate_upload(
        self,
        image: PILImage.Image,
        params: dict[str, Any],
        *,
        defer_dispatch_on_transient_error: bool = False,
    ) -> None:
        """Run a synchronous (caller-awaited) upload while holding the lock."""
        async with self._lock:
            current = asyncio.current_task()
            self._upload_task = current
            try:
                await self._async_perform_upload(image, params)
                self._defer_dispatch_until_advertisement = False
            except HomeAssistantError as err:
                if defer_dispatch_on_transient_error and self._is_transient_error(err):
                    self._defer_dispatch_until_advertisement = True
                raise
            finally:
                if self._upload_task is current:
                    self._upload_task = None

        # Even if the explicit upload succeeded, a queued entry may have been
        # added concurrently — flush it on the next event-loop tick.
        if self.queue.has_pending and not self._shutdown:
            self._schedule_dispatch()

    def _schedule_dispatch(self) -> None:
        """Schedule a background dispatch attempt."""
        if self._shutdown or self._defer_dispatch_until_advertisement:
            return
        if (task := self._dispatch_task) is not None and not task.done():
            return
        task = self.entry.async_create_task(
            self.hass,
            self._async_dispatch_pending(),
            name=f"opendisplay-dispatch-{self.address}",
            eager_start=True,
        )
        self._dispatch_task = task
        if task.done():
            self._dispatch_task = None
            return
        task.add_done_callback(self._clear_dispatch_task)

    def _clear_dispatch_task(self, task: asyncio.Future[Any]) -> None:
        """Clear the tracked dispatch task when it finishes."""
        if self._dispatch_task is task:
            self._dispatch_task = None

    async def _async_dispatch_pending(self) -> None:
        """Try to flush the queued image to the device."""
        if (
            self._shutdown
            or self._defer_dispatch_until_advertisement
            or not self.queue.has_pending
        ):
            return

        # Drop expired entries opportunistically.
        if self.queue.purge_expired() is not None:
            _LOGGER.info(
                "Dropping queued image for OpenDisplay device %s (older than timeout)",
                self.address,
            )
            return

        if not self._device_connectable():
            # Advertisement seen on a non-connectable adapter — leave queued.
            return

        async with self._lock:
            # Re-check inside the lock — another task may have flushed it.
            if (
                self._shutdown
                or self._defer_dispatch_until_advertisement
                or not self.queue.has_pending
            ):
                return
            if self.queue.purge_expired() is not None:
                _LOGGER.info(
                    (
                        "Dropping queued image for OpenDisplay device %s"
                        " (older than timeout)"
                    ),
                    self.address,
                )
                return

            entry = self.queue.take_pending()
            if entry is None:
                return

            current = asyncio.current_task()
            self._upload_task = current
            failed = False
            try:
                await self._async_perform_upload(entry.image, entry.params)
            except HomeAssistantError as err:
                failed = True
                self._handle_dispatch_failure(entry, err)
            finally:
                if self._upload_task is current:
                    self._upload_task = None

        # If a newer image was queued while we were uploading, flush it too.
        # After a transient failure the same entry is restored to the queue;
        # don't immediately retry — wait for the next advertisement so we
        # don't tight-loop while the device is unreachable.
        if not failed and self.queue.has_pending and not self._shutdown:
            if self._dispatch_task is asyncio.current_task():
                self._dispatch_task = None
            self._schedule_dispatch()

    def _handle_dispatch_failure(
        self, entry: PendingUpload, err: HomeAssistantError
    ) -> None:
        """React to an upload failure during a queue dispatch."""
        if self._is_auth_error(err):
            # Bad key — retrying would loop forever. Drop the entry; the
            # reauth flow has already been kicked off by _async_perform_upload.
            # Any newer queued image would use the same bad key, so drop it too.
            self.queue.clear()
            _LOGGER.warning(
                (
                    "Authentication failed while uploading queued image to"
                    " OpenDisplay device %s; dropping queued image"
                ),
                self.address,
            )
            return

        if self._keep_newer_pending_upload():
            return

        if not self._is_transient_error(err):
            _LOGGER.warning(
                (
                    "Non-retryable error while uploading queued image to"
                    " OpenDisplay device %s; dropping queued image: %s"
                ),
                self.address,
                err,
            )
            return

        # Transient failure. Restore the entry so the next advertisement
        # retries (subject to the timeout).
        self.queue.restore(entry)
        if entry.failure_count == 1:
            _LOGGER.info(
                (
                    "Failed to upload queued image to OpenDisplay device %s,"
                    " will retry on next advertisement: %s"
                ),
                self.address,
                err,
            )
        else:
            _LOGGER.debug(
                (
                    "Failed to upload queued image to OpenDisplay device %s"
                    " (attempt %d): %s"
                ),
                self.address,
                entry.failure_count,
                err,
            )

    def async_handle_advertisement(self) -> None:
        """Coordinator callback: device just advertised — try to flush queue."""
        if self._shutdown:
            return
        # Reset the defer flag unconditionally so that a future upload that
        # arrives after the queue has been purged is not blocked.
        self._defer_dispatch_until_advertisement = False
        if not self.queue.has_pending:
            return
        self._schedule_dispatch()

    def async_purge_expired(self) -> None:
        """Periodic callback: drop the pending entry if it has expired."""
        if self.queue.purge_expired() is not None:
            _LOGGER.info(
                "Dropping queued image for OpenDisplay device %s (older than timeout)",
                self.address,
            )

    async def async_shutdown(self) -> None:
        """Cancel any in-flight upload and drop the queue."""
        self._shutdown = True
        self.queue.clear()
        self._defer_dispatch_until_advertisement = False
        current_task = asyncio.current_task()
        tasks = {
            task
            for task in (self._upload_task, self._dispatch_task)
            if task is not None and task is not current_task and not task.done()
        }
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._upload_task = None
        self._dispatch_task = None


__all__ = ["OpenDisplayUploader", "PendingUpload"]
