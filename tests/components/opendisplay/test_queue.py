"""Unit tests for the OpenDisplay pending-upload queue."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from PIL import Image as PILImage

from homeassistant.components.opendisplay.queue import OpenDisplayQueue


def _image() -> PILImage.Image:
    """Return a tiny PIL image for tests."""
    return PILImage.new("RGB", (1, 1))


def test_set_pending_overwrites_previous() -> None:
    """A second set_pending replaces the first entry (latest wins)."""
    queue = OpenDisplayQueue(timedelta(minutes=30))

    first = _image()
    second = _image()
    queue.set_pending(first, {"refresh_mode": MagicMock()})
    queue.set_pending(second, {"refresh_mode": MagicMock()})

    pending = queue.pending
    assert pending is not None
    assert pending.image is second
    assert queue.has_pending


def test_take_pending_clears_queue() -> None:
    """take_pending returns the entry and leaves the queue empty."""
    queue = OpenDisplayQueue(timedelta(minutes=30))
    queue.set_pending(_image(), {})

    entry = queue.take_pending()
    assert entry is not None
    assert not queue.has_pending
    assert queue.take_pending() is None


def test_clear_drops_pending() -> None:
    """clear() removes the pending entry."""
    queue = OpenDisplayQueue(timedelta(minutes=30))
    queue.set_pending(_image(), {})
    queue.clear()
    assert not queue.has_pending


def test_restore_increments_failure_count_and_keeps_timestamp(
    freezer: FrozenDateTimeFactory,
) -> None:
    """restore() preserves enqueued_at so the entry still expires on time."""
    queue = OpenDisplayQueue(timedelta(minutes=30))
    queue.set_pending(_image(), {})
    entry = queue.take_pending()
    assert entry is not None
    enqueued_at = entry.enqueued_at

    freezer.tick(timedelta(minutes=10))
    queue.restore(entry)

    pending = queue.pending
    assert pending is entry
    assert pending.failure_count == 1
    assert pending.enqueued_at == enqueued_at


def test_is_expired_honours_timeout(freezer: FrozenDateTimeFactory) -> None:
    """is_expired returns True only after the configured timeout."""
    queue = OpenDisplayQueue(timedelta(minutes=30))
    queue.set_pending(_image(), {})
    entry = queue.pending
    assert entry is not None

    freezer.tick(timedelta(minutes=29, seconds=59))
    assert not queue.is_expired(entry)

    freezer.tick(timedelta(seconds=2))
    assert queue.is_expired(entry)


def test_purge_expired_only_removes_old_entry(
    freezer: FrozenDateTimeFactory,
) -> None:
    """purge_expired drops the entry exactly when it has expired."""
    queue = OpenDisplayQueue(timedelta(minutes=30))
    queue.set_pending(_image(), {})

    freezer.tick(timedelta(minutes=10))
    assert queue.purge_expired() is None
    assert queue.has_pending

    freezer.tick(timedelta(minutes=21))
    expired = queue.purge_expired()
    assert expired is not None
    assert not queue.has_pending


def test_purge_expired_noop_on_empty_queue() -> None:
    """purge_expired is a no-op when there is no pending entry."""
    queue = OpenDisplayQueue(timedelta(minutes=30))
    assert queue.purge_expired() is None
