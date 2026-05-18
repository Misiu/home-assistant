"""Test the OpenDisplay upload_image service."""

import asyncio
from collections.abc import Generator
from datetime import timedelta
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
    OpenDisplayError,
)
from PIL import Image as PILImage
import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.opendisplay.const import (
    CONF_ENCRYPTION_KEY,
    DOMAIN,
    PENDING_UPLOAD_CLEANUP_INTERVAL,
    PENDING_UPLOAD_TIMEOUT,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from . import DEEP_SLEEP_DEVICE_CONFIG, ENCRYPTION_KEY, make_v1_service_info

from tests.common import MockConfigEntry, async_fire_time_changed
from tests.components.bluetooth import inject_bluetooth_service_info
from tests.test_util.aiohttp import AiohttpClientMocker


@pytest.fixture(autouse=True)
async def setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    request: pytest.FixtureRequest,
) -> None:
    """Set up the config entry for service tests.

    Tests marked with ``@pytest.mark.deep_sleep_device`` get a battery
    device config so the integration enables the offline-upload queue.
    """
    if request.node.get_closest_marker("deep_sleep_device"):
        mock_opendisplay_device.config = DEEP_SLEEP_DEVICE_CONFIG
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def mock_upload_device(mock_opendisplay_device: MagicMock) -> MagicMock:
    """Return the mock OpenDisplayDevice for upload service tests."""
    return mock_opendisplay_device


@pytest.fixture
def mock_resolve_media(tmp_path: Path) -> Generator[MagicMock]:
    """Mock async_resolve_media to return a local test image."""
    image_path = tmp_path / "test.png"
    PILImage.new("RGB", (10, 10)).save(image_path)
    mock_media = MagicMock()
    mock_media.path = image_path
    with patch(
        "homeassistant.components.opendisplay.services.async_resolve_media",
        return_value=mock_media,
    ):
        yield mock_media


def _device_id(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> str:
    """Return the device registry ID for the config entry."""
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
    assert devices
    return devices[0].id


async def test_upload_image_local_file(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Test successful upload from a local file with tone compression."""
    device_id = _device_id(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {
            "device_id": device_id,
            "image": {
                "media_content_id": "media-source://local/test.png",
                "media_content_type": "image/png",
            },
            "tone_compression": 50,
        },
        blocking=True,
    )

    mock_upload_device.upload_image.assert_called_once()


async def test_upload_image_remote_url(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test successful upload from a remote URL."""
    device_id = _device_id(hass, mock_config_entry)

    image = PILImage.new("RGB", (10, 10))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    aioclient_mock.get("http://example.com/image.png", content=buf.getvalue())

    mock_media = MagicMock()
    mock_media.path = None
    mock_media.url = "http://example.com/image.png"

    with patch(
        "homeassistant.components.opendisplay.services.async_resolve_media",
        return_value=mock_media,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    mock_upload_device.upload_image.assert_called_once()


async def test_upload_image_invalid_device_id(
    hass: HomeAssistant,
) -> None:
    """Test that an invalid device_id raises ServiceValidationError."""
    with pytest.raises(ServiceValidationError, match="not a valid OpenDisplay device"):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": "not-a-real-device-id",
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )


async def test_upload_image_device_not_in_range_raises_for_always_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_resolve_media: MagicMock,
) -> None:
    """An always-on device that is out of BLE range surfaces an error."""
    device_id = _device_id(hass, mock_config_entry)

    with (
        patch(
            "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
            return_value=None,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )


@pytest.mark.deep_sleep_device
async def test_upload_image_device_not_in_range_queues_for_deep_sleep(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """A deep-sleep device that is out of range queues the image silently."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    mock_upload_device.upload_image.assert_not_called()
    assert mock_config_entry.runtime_data.queue.has_pending


@pytest.mark.deep_sleep_device
async def test_upload_image_stale_connectable_failure_queues_for_deep_sleep(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """A stale connectable BLE cache queues the image for a deep-sleep device."""
    device_id = _device_id(hass, mock_config_entry)

    mock_opendisplay_device.__aenter__.side_effect = BLEConnectionError("asleep")

    await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {
            "device_id": device_id,
            "image": {
                "media_content_id": "media-source://local/test.png",
                "media_content_type": "image/png",
            },
        },
        blocking=True,
    )

    mock_upload_device.upload_image.assert_not_called()
    assert mock_config_entry.runtime_data.queue.has_pending

    mock_opendisplay_device.__aenter__.side_effect = None
    mock_opendisplay_device.__aenter__.return_value = mock_opendisplay_device

    inject_bluetooth_service_info(hass, make_v1_service_info())
    await hass.async_block_till_done()

    mock_upload_device.upload_image.assert_called_once()
    assert not mock_config_entry.runtime_data.queue.has_pending


@pytest.mark.deep_sleep_device
async def test_upload_image_non_transient_error_raises_for_deep_sleep(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """A non-transient upload error is not hidden by the deep-sleep queue."""
    device_id = _device_id(hass, mock_config_entry)

    mock_opendisplay_device.__aenter__.side_effect = OpenDisplayError("bad image")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    assert not mock_config_entry.runtime_data.queue.has_pending


async def test_upload_image_ble_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Test that HomeAssistantError is raised on BLE upload failure."""
    device_id = _device_id(hass, mock_config_entry)

    mock_opendisplay_device.__aenter__.side_effect = BLEConnectionError(
        "connection lost"
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )


async def test_upload_image_download_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test that HomeAssistantError is raised on media download failure."""
    device_id = _device_id(hass, mock_config_entry)

    aioclient_mock.get(
        "http://example.com/image.png",
        exc=aiohttp.ClientError("connection refused"),
    )

    mock_media = MagicMock()
    mock_media.path = None
    mock_media.url = "http://example.com/image.png"

    with (
        patch(
            "homeassistant.components.opendisplay.services.async_resolve_media",
            return_value=mock_media,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )


@pytest.mark.parametrize(
    "field",
    ["dither_mode", "fit_mode", "refresh_mode"],
)
async def test_upload_image_invalid_mode(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    field: str,
) -> None:
    """Test that invalid mode strings are rejected by the schema."""
    device_id = _device_id(hass, mock_config_entry)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
                field: "not_a_valid_value",
            },
            blocking=True,
        )


@pytest.mark.deep_sleep_device
async def test_upload_image_queues_when_busy(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Test that a new upload while another is in flight is queued, not cancelled.

    Interrupting a BLE transfer mid-frame can leave the e-paper panel in a
    partially-written state, so the in-flight upload must complete before the
    new image is sent.
    """
    device_id = _device_id(hass, mock_config_entry)

    first_upload_started = asyncio.Event()
    release_first_upload = asyncio.Event()

    async def _slow_upload(*_args: object, **_kwargs: object) -> None:
        first_upload_started.set()
        await release_first_upload.wait()

    mock_upload_device.upload_image.side_effect = _slow_upload

    first_call = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )
    )
    await first_upload_started.wait()

    # Second call arrives while the first is still uploading. The queue
    # should hold it without cancelling the first upload.
    await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {
            "device_id": device_id,
            "image": {
                "media_content_id": "media-source://local/test.png",
                "media_content_type": "image/png",
            },
        },
        blocking=True,
    )
    assert mock_config_entry.runtime_data.queue.has_pending
    assert not first_call.done()

    # Allow the first upload to complete; the queued image should then be
    # uploaded automatically.
    mock_upload_device.upload_image.side_effect = None
    release_first_upload.set()
    await first_call
    await hass.async_block_till_done()

    assert mock_upload_device.upload_image.call_count == 2
    assert not mock_config_entry.runtime_data.queue.has_pending


async def test_upload_image_with_encryption_key(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device_class: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Test that upload_image passes the encryption key to OpenDisplayDevice."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_ENCRYPTION_KEY: ENCRYPTION_KEY},
    )

    device_id = _device_id(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {
            "device_id": device_id,
            "image": {
                "media_content_id": "media-source://local/test.png",
                "media_content_type": "image/png",
            },
        },
        blocking=True,
    )

    assert mock_opendisplay_device_class.call_args.kwargs[
        "encryption_key"
    ] == bytes.fromhex(ENCRYPTION_KEY)


@pytest.mark.parametrize(
    "exception",
    [
        AuthenticationFailedError("wrong key"),
        AuthenticationRequiredError("auth required"),
    ],
)
async def test_upload_image_auth_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_resolve_media: MagicMock,
    exception: Exception,
) -> None:
    """Test that auth errors during upload trigger a reauth flow."""
    device_id = _device_id(hass, mock_config_entry)

    mock_opendisplay_device.__aenter__.side_effect = exception

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


async def test_upload_image_invalid_encryption_key_format(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_resolve_media: MagicMock,
) -> None:
    """Test that a malformed stored encryption key triggers reauth and raises an error."""
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_ENCRYPTION_KEY: "not-valid-hex!"},
    )
    device_id = _device_id(hass, mock_config_entry)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


@pytest.mark.deep_sleep_device
async def test_upload_queued_when_offline_then_flushed_on_advertisement(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Image is queued when device is asleep and uploaded on next advertisement."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    mock_upload_device.upload_image.assert_not_called()
    assert mock_config_entry.runtime_data.queue.has_pending

    # Device wakes up and starts advertising.
    inject_bluetooth_service_info(hass, make_v1_service_info())
    await hass.async_block_till_done()

    mock_upload_device.upload_image.assert_called_once()
    assert not mock_config_entry.runtime_data.queue.has_pending


@pytest.mark.deep_sleep_device
async def test_upload_offline_replaces_pending_image(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    tmp_path: Path,
) -> None:
    """A second offline upload replaces the first queued image (latest wins)."""
    device_id = _device_id(hass, mock_config_entry)

    images: list[PILImage.Image] = []

    def _make_image(_path: str) -> PILImage.Image:
        img = PILImage.new("RGB", (1, 1))
        images.append(img)
        return img

    fake_path = tmp_path / "a.png"
    fake_path.touch()

    with (
        patch(
            "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
            return_value=None,
        ),
        patch(
            "homeassistant.components.opendisplay.services._load_image",
            side_effect=_make_image,
        ),
        patch(
            "homeassistant.components.opendisplay.services.async_resolve_media",
            return_value=MagicMock(path=fake_path),
        ),
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/a.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/b.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    assert len(images) == 2
    pending = mock_config_entry.runtime_data.queue.pending
    assert pending is not None
    assert pending.image is images[1]
    mock_upload_device.upload_image.assert_not_called()


@pytest.mark.deep_sleep_device
async def test_upload_image_immediate_upload_replaces_existing_pending_image(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """An immediate upload drops an older queued image."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/a.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    assert mock_config_entry.runtime_data.queue.has_pending

    await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {
            "device_id": device_id,
            "image": {
                "media_content_id": "media-source://local/b.png",
                "media_content_type": "image/png",
            },
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    mock_upload_device.upload_image.assert_called_once()
    assert not mock_config_entry.runtime_data.queue.has_pending


@pytest.mark.deep_sleep_device
async def test_upload_image_immediate_failure_keeps_newer_pending_image(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    tmp_path: Path,
) -> None:
    """A failed immediate upload does not overwrite a newer queued image."""
    device_id = _device_id(hass, mock_config_entry)
    upload_started = asyncio.Event()
    fail_upload = asyncio.Event()
    images: list[PILImage.Image] = []

    def _make_image(_path: str) -> PILImage.Image:
        image = PILImage.new("RGB", (1, 1))
        images.append(image)
        return image

    async def _failing_upload(*_args: object, **_kwargs: object) -> None:
        upload_started.set()
        await fail_upload.wait()
        raise BLEConnectionError("flaky")

    fake_path = tmp_path / "test.png"
    fake_path.touch()
    mock_upload_device.upload_image.side_effect = _failing_upload

    with (
        patch(
            "homeassistant.components.opendisplay.services._load_image",
            side_effect=_make_image,
        ),
        patch(
            "homeassistant.components.opendisplay.services.async_resolve_media",
            return_value=MagicMock(path=fake_path),
        ),
    ):
        first_call = hass.async_create_task(
            hass.services.async_call(
                DOMAIN,
                "upload_image",
                {
                    "device_id": device_id,
                    "image": {
                        "media_content_id": "media-source://local/a.png",
                        "media_content_type": "image/png",
                    },
                },
                blocking=True,
            )
        )
        await upload_started.wait()

        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/b.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    fail_upload.set()
    await first_call

    assert len(images) == 2
    pending = mock_config_entry.runtime_data.queue.pending
    assert pending is not None
    assert pending.image is images[1]
    assert pending.failure_count == 0


@pytest.mark.deep_sleep_device
async def test_queued_upload_expires_after_timeout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Queued image is dropped after PENDING_UPLOAD_TIMEOUT and not uploaded."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    assert mock_config_entry.runtime_data.queue.has_pending

    # Advance past the timeout, then fire the periodic purge.
    freezer.tick(PENDING_UPLOAD_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    # Ensure the periodic interval task actually runs by ticking forward by
    # one cleanup interval too.
    freezer.tick(PENDING_UPLOAD_CLEANUP_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert not mock_config_entry.runtime_data.queue.has_pending

    # A late advertisement must NOT cause the dropped image to be uploaded.
    inject_bluetooth_service_info(hass, make_v1_service_info())
    await hass.async_block_till_done()
    mock_upload_device.upload_image.assert_not_called()


@pytest.mark.deep_sleep_device
async def test_queued_upload_auth_error_dropped_and_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Auth error during a queued dispatch drops the entry and starts reauth."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    mock_opendisplay_device.__aenter__.side_effect = AuthenticationFailedError("bad")

    inject_bluetooth_service_info(hass, make_v1_service_info())
    await hass.async_block_till_done()

    assert not mock_config_entry.runtime_data.queue.has_pending
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


@pytest.mark.deep_sleep_device
async def test_queued_upload_transient_error_retains_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """A transient BLE error keeps the queued entry for the next advertisement."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    mock_opendisplay_device.__aenter__.side_effect = BLEConnectionError("flaky")
    # Distinct payloads are required so the bluetooth manager does not dedup
    # the two advertisements (a real deep-sleep device increments its loop
    # counter on every broadcast).
    inject_bluetooth_service_info(hass, make_v1_service_info(b"\x00" * 11))
    await hass.async_block_till_done()

    pending = mock_config_entry.runtime_data.queue.pending
    assert pending is not None
    assert pending.failure_count == 1

    # Recover and try again — entry must flush.
    mock_opendisplay_device.__aenter__.side_effect = None
    mock_opendisplay_device.__aenter__.return_value = mock_opendisplay_device
    inject_bluetooth_service_info(hass, make_v1_service_info(b"\x01" + b"\x00" * 10))
    await hass.async_block_till_done()

    mock_opendisplay_device.upload_image.assert_called_once()
    assert not mock_config_entry.runtime_data.queue.has_pending


@pytest.mark.deep_sleep_device
async def test_queued_upload_failure_does_not_replace_newer_pending_image(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
    tmp_path: Path,
) -> None:
    """A failed in-flight queued upload does not overwrite a newer queued image."""
    device_id = _device_id(hass, mock_config_entry)
    upload_started = asyncio.Event()
    fail_upload = asyncio.Event()
    images: list[PILImage.Image] = []

    def _make_image(_path: str) -> PILImage.Image:
        image = PILImage.new("RGB", (1, 1))
        images.append(image)
        return image

    async def _failing_upload(*_args: object, **_kwargs: object) -> None:
        upload_started.set()
        await fail_upload.wait()
        raise BLEConnectionError("flaky")

    fake_path = tmp_path / "test.png"
    fake_path.touch()

    with (
        patch(
            "homeassistant.components.opendisplay.services._load_image",
            side_effect=_make_image,
        ),
        patch(
            "homeassistant.components.opendisplay.services.async_resolve_media",
            return_value=MagicMock(path=fake_path),
        ),
    ):
        with patch(
            "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
            return_value=None,
        ):
            await hass.services.async_call(
                DOMAIN,
                "upload_image",
                {
                    "device_id": device_id,
                    "image": {
                        "media_content_id": "media-source://local/a.png",
                        "media_content_type": "image/png",
                    },
                },
                blocking=True,
            )

        mock_upload_device.upload_image.side_effect = _failing_upload
        inject_bluetooth_service_info(hass, make_v1_service_info(b"\x00" * 11))
        await upload_started.wait()

        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/b.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    fail_upload.set()
    await hass.async_block_till_done()

    assert len(images) == 2
    pending = mock_config_entry.runtime_data.queue.pending
    assert pending is not None
    assert pending.image is images[1]
    assert pending.failure_count == 0


@pytest.mark.deep_sleep_device
async def test_queued_upload_non_transient_error_drops_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """A non-transient queued upload error drops the queued image."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    mock_opendisplay_device.__aenter__.side_effect = OpenDisplayError("bad image")

    inject_bluetooth_service_info(hass, make_v1_service_info())
    await hass.async_block_till_done()

    assert not mock_config_entry.runtime_data.queue.has_pending


@pytest.mark.deep_sleep_device
async def test_queued_upload_transient_error_waits_for_next_advertisement(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Duplicate dispatch triggers do not immediately retry after a transient error."""
    device_id = _device_id(hass, mock_config_entry)
    first_upload_started = asyncio.Event()
    release_first_upload = asyncio.Event()

    async def _first_upload() -> None:
        first_upload_started.set()
        await release_first_upload.wait()

    async def _transient_upload() -> None:
        raise BLEConnectionError("flaky")

    upload_side_effects = [_first_upload, *([_transient_upload] * 6)]

    async def _upload(*_args: object, **_kwargs: object) -> None:
        await upload_side_effects.pop(0)()

    mock_upload_device.upload_image.side_effect = _upload

    first_call = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )
    )
    await first_upload_started.wait()

    await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {
            "device_id": device_id,
            "image": {
                "media_content_id": "media-source://local/test.png",
                "media_content_type": "image/png",
            },
        },
        blocking=True,
    )

    uploader = mock_config_entry.runtime_data.uploader
    uploader.async_handle_advertisement()
    uploader.async_handle_advertisement()

    release_first_upload.set()
    await first_call
    await hass.async_block_till_done()

    pending = mock_config_entry.runtime_data.queue.pending
    assert pending is not None
    assert pending.failure_count == 1
    assert mock_upload_device.upload_image.call_count == 2


@pytest.mark.deep_sleep_device
async def test_unload_clears_queue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_resolve_media: MagicMock,
) -> None:
    """Unloading the entry drops any queued image and shuts the uploader down."""
    device_id = _device_id(hass, mock_config_entry)

    with patch(
        "homeassistant.components.opendisplay.uploader.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {
                "device_id": device_id,
                "image": {
                    "media_content_id": "media-source://local/test.png",
                    "media_content_type": "image/png",
                },
            },
            blocking=True,
        )

    queue = mock_config_entry.runtime_data.queue
    assert queue.has_pending

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not queue.has_pending
