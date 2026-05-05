"""Per-device pending-upload queue for the OpenDisplay integration.

A deep-sleep BLE device (e.g. an ESP32 OpenDisplay) only briefly wakes up to
broadcast a manufacturer advertisement and accept a single connection. When
Home Assistant tries to upload an image while the device is asleep the BLE
connection times out. The queue holds the most recent pending image per
device so the uploader can flush it when the device next advertises.

Only one entry is held per device — a newer enqueue replaces the previous
one. The display can only render one image, so a FIFO would just waste
memory and battery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from PIL import Image as PILImage

from homeassistant.util import dt as dt_util


@dataclass(slots=True)
class PendingUpload:
    """A single pending image upload waiting for the device to wake up."""

    image: PILImage.Image
    params: dict[str, Any]
    enqueued_at: datetime
    failure_count: int = 0


class OpenDisplayQueue:
    """Hold at most one pending image upload for a single device."""

    def __init__(self, timeout: timedelta) -> None:
        """Initialize the queue with the given pending-entry timeout."""
        self._timeout = timeout
        self._pending: PendingUpload | None = None

    @property
    def pending(self) -> PendingUpload | None:
        """Return the pending entry, if any."""
        return self._pending

    @property
    def has_pending(self) -> bool:
        """Return whether there is a pending entry."""
        return self._pending is not None

    def set_pending(self, image: PILImage.Image, params: dict[str, Any]) -> None:
        """Store a new pending entry, replacing any previous one.

        The previous entry (and its decoded image) is dropped so memory is
        released as soon as the new one arrives.
        """
        self._pending = PendingUpload(
            image=image,
            params=params,
            enqueued_at=dt_util.utcnow(),
        )

    def take_pending(self) -> PendingUpload | None:
        """Pop and return the pending entry, or None."""
        entry = self._pending
        self._pending = None
        return entry

    def restore(self, entry: PendingUpload) -> None:
        """Put an entry back after a transient failure.

        Preserves the original ``enqueued_at`` so the entry still expires
        relative to its first enqueue time, not the retry time.
        """
        entry.failure_count += 1
        self._pending = entry

    def clear(self) -> None:
        """Drop the pending entry, releasing its image."""
        self._pending = None

    def is_expired(self, entry: PendingUpload, now: datetime | None = None) -> bool:
        """Return whether the entry is older than the configured timeout."""
        if now is None:
            now = dt_util.utcnow()
        return now - entry.enqueued_at >= self._timeout

    def purge_expired(self, now: datetime | None = None) -> PendingUpload | None:
        """Drop the pending entry if it is expired.

        Returns the dropped entry (so the caller can log) or None.
        """
        if self._pending is not None and self.is_expired(self._pending, now):
            entry = self._pending
            self._pending = None
            return entry
        return None
