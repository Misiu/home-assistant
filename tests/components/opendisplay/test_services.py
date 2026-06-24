"""Test the OpenDisplay upload_image service."""

import asyncio
from collections.abc import Generator
from copy import deepcopy
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiohttp
from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
)
from opendisplay.models.config import PowerOption
from PIL import Image as PILImage
import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.opendisplay.const import CONF_ENCRYPTION_KEY, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from . import ENCRYPTION_KEY, VALID_SERVICE_INFO

from tests.common import MockConfigEntry
from tests.components.bluetooth import inject_bluetooth_service_info
from tests.test_util.aiohttp import AiohttpClientMocker


@pytest.fixture(autouse=True)
async def setup_entry(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Set up the config entry for service tests."""
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


async def test_upload_image_device_not_in_range(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that HomeAssistantError is raised if device is out of BLE range."""
    device_id = _device_id(hass, mock_config_entry)

    with (
        patch(
            "homeassistant.components.opendisplay.services.async_ble_device_from_address",
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


async def test_upload_image_cancels_previous_task(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Test that starting a new upload cancels an in-progress upload task."""
    device_id = _device_id(hass, mock_config_entry)

    prev_task = hass.async_create_task(asyncio.sleep(3600))
    mock_config_entry.runtime_data.upload_task = prev_task

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
    await hass.async_block_till_done()

    assert prev_task.cancelled()


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
    """Test malformed encryption key triggers reauth and error."""
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


async def test_upload_image_is_queued_when_deep_sleep_device_is_asleep(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Upload request is queued (not sent immediately) for sleeping deep-sleep devices."""
    device_config = deepcopy(mock_opendisplay_device.config)
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
    mock_config_entry.runtime_data.device_config = device_config

    device_id = _device_id(hass, mock_config_entry)
    assert not mock_config_entry.runtime_data.coordinator.available

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
    await hass.async_block_till_done()

    assert mock_upload_device.upload_image.call_count == 0
    assert mock_config_entry.runtime_data.pending_upload is not None
    assert mock_config_entry.runtime_data.coordinator.pending_upload is True


async def test_queued_upload_is_flushed_after_device_seen(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_upload_device: MagicMock,
    mock_resolve_media: MagicMock,
) -> None:
    """Queued upload is sent when a new OpenDisplay advertisement is received."""
    device_config = deepcopy(mock_opendisplay_device.config)
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
    mock_config_entry.runtime_data.device_config = device_config

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
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.pending_upload is not None
    assert mock_upload_device.upload_image.call_count == 0

    with patch(
        "homeassistant.components.opendisplay.services.asyncio.sleep",
        return_value=None,
    ):
        inject_bluetooth_service_info(hass, VALID_SERVICE_INFO)
        await hass.async_block_till_done()

    assert mock_upload_device.upload_image.call_count == 1
    assert mock_config_entry.runtime_data.pending_upload is None
    assert mock_config_entry.runtime_data.coordinator.pending_upload is False
