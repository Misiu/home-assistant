"""Tests for the Whois integration."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from whoisdomain.exceptions import (
    FailedParsingWhoisOutput,
    UnknownDateFormat,
    UnknownTld,
    WhoisCommandFailed,
)

from homeassistant.components.whois.const import DOMAIN
from homeassistant.components.whois.models import WhoisData
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


async def test_load_unload_config_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test the Whois configuration entry loading/unloading."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(mock_whois.mock_calls) == 1

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.data.get(DOMAIN)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    "side_effect",
    [
        FailedParsingWhoisOutput,
        UnknownDateFormat,
        UnknownTld,
        WhoisCommandFailed,
        OSError,
    ],
)
async def test_error_handling(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
    side_effect: type[Exception],
) -> None:
    """Test the Whois threw an error and RDAP also fails → SETUP_RETRY."""
    mock_config_entry.add_to_hass(hass)
    mock_whois.side_effect = side_effect

    # Both WHOIS and RDAP fail → the integration should retry setup.
    with patch(
        "homeassistant.components.whois.coordinator.async_fetch_rdap_data",
        side_effect=ValueError("RDAP also failed"),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert len(mock_whois.mock_calls) == 1


async def test_rdap_fallback_on_whois_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test that RDAP is used when WHOIS completely fails (e.g. missing binary)."""
    mock_config_entry.add_to_hass(hass)
    mock_whois.side_effect = WhoisCommandFailed

    rdap_data = WhoisData(
        creation_date=datetime(2011, 9, 19, 11, 4, 53, tzinfo=UTC),
        expiration_date=datetime(2026, 9, 19, 11, 4, 53, tzinfo=UTC),
        registrar="OVH SAS",
        dnssec=True,
        name_servers=["dns102.ovh.net", "ns102.ovh.net"],
    )

    with patch(
        "homeassistant.components.whois.coordinator.async_fetch_rdap_data",
        return_value=rdap_data,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_rdap_fallback_on_missing_expiration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test RDAP is used to fill in expiration when WHOIS omits it (e.g. .pl GDPR)."""
    mock_config_entry.add_to_hass(hass)
    # WHOIS succeeds but returns no expiration date (GDPR-redacted .pl domain)
    mock_whois.return_value.expiration_date = None

    rdap_data = WhoisData(
        expiration_date=datetime(2026, 9, 19, 11, 4, 53, tzinfo=UTC),
    )

    with patch(
        "homeassistant.components.whois.coordinator.async_fetch_rdap_data",
        return_value=rdap_data,
    ) as mock_rdap:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_rdap.call_count == 1
    # Verify the expiration date was filled in from RDAP
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert coordinator.data is not None
    assert coordinator.data.expiration_date == datetime(
        2026, 9, 19, 11, 4, 53, tzinfo=UTC
    )

