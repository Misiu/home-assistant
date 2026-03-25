"""Tests for the Whois integration."""

from unittest.mock import AsyncMock

import pytest
from whoisit.errors import BootstrapError, ParseError, QueryError, UnsupportedError

from homeassistant.components.whois.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


async def test_load_unload_config_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whoisit: AsyncMock,
) -> None:
    """Test the Whois configuration entry loading/unloading."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(mock_whoisit.mock_calls) == 1

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.data.get(DOMAIN)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    "side_effect",
    [
        BootstrapError(),
        UnsupportedError(),
        QueryError("test"),
        ParseError(),
    ],
)
async def test_error_handling(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whoisit: AsyncMock,
    side_effect: Exception,
) -> None:
    """Test that RDAP errors cause SETUP_RETRY."""
    mock_config_entry.add_to_hass(hass)
    mock_whoisit.side_effect = side_effect

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert len(mock_whoisit.mock_calls) == 1


async def test_polish_domain(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whoisit: AsyncMock,
) -> None:
    """Test that Polish .pl domains load correctly via whoisit with overrides=True.

    Polish domains from rdap.dns.pl omit the 'handle' field and return an
    empty status list — both handled by whoisit when bootstrapped with
    overrides=True.  Test data is based on the real whoisit output for
    google.pl.
    """
    from datetime import UTC, datetime

    mock_config_entry.add_to_hass(hass)
    mock_whoisit.return_value = {
        "expiration_date": datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        "registration_date": datetime(2002, 9, 19, 11, 0, tzinfo=UTC),
        "last_changed_date": datetime(2025, 8, 17, 10, 16, 24, tzinfo=UTC),
        "nameservers": [
            "ns1.google.com",
            "ns2.google.com",
            "ns3.google.com",
            "ns4.google.com",
        ],
        "dnssec": False,
        "status": [],  # .pl domains return an empty status list
        "entities": {
            "registrant": [{"name": "Google LLC", "type": "entity"}],
            "registrar": [{"name": "Markmonitor, Inc.", "type": "entity"}],
        },
        "handle": "",  # rdap.dns.pl omits handle; overrides=True handles this
        "name": "google.pl",
        "type": "domain",
    }

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    data = coordinator.data
    assert data is not None
    assert data.expiration_date == datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert data.registrar == "Markmonitor, Inc."
    assert data.registrant == "Google LLC"
    assert data.dnssec is False
    assert data.status is None  # empty list → None
    assert data.statuses == []
    assert "ns1.google.com" in data.name_servers
