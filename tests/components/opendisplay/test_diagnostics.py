"""Test the OpenDisplay diagnostics."""

from unittest.mock import MagicMock

from PIL import Image as PILImage
from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test diagnostics output matches snapshot."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )
    assert result == snapshot


async def test_diagnostics_with_pending_upload(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
) -> None:
    """Diagnostics report a queued upload without leaking image data."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_config_entry.runtime_data.queue.set_pending(
        PILImage.new("RGB", (1, 1)), {"refresh_mode": MagicMock()}
    )

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    pending = result["pending_upload"]
    assert pending["queued"] is True
    assert isinstance(pending["age_seconds"], int)
    assert pending["age_seconds"] >= 0
    assert pending["failure_count"] == 0
    # Defensive: nothing image-shaped should leak.
    assert "image" not in pending
    assert "params" not in pending
    assert "url" not in pending
