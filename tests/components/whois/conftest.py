"""Fixtures for Whois integration tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components.whois.const import DOMAIN
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from tests.common import MockConfigEntry

# ---------------------------------------------------------------------------
# Realistic whoisit.domain_async() return value used across all tests.
# Mirrors what the library returns for a domain with full RDAP data, based
# on the structure confirmed by the user's real jagusz.pl test run.
# ---------------------------------------------------------------------------
_MOCK_DOMAIN_RESULT: dict = {
    "expiration_date": datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC),
    "registration_date": datetime(2019, 1, 1, 0, 0, 0),
    "last_changed_date": datetime(
        2022, 1, 1, 0, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Amsterdam")
    ),
    "nameservers": ["ns1.example.com", "ns2.example.com"],
    "dnssec": True,
    "status": ["ok"],
    "entities": {
        "registrar": [{"name": "My Registrar", "type": "entity"}],
        "registrant": [{"name": "registrant@example.com", "type": "entity"}],
    },
    "handle": "",
    "name": "home-assistant.io",
    "type": "domain",
}


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the default mocked config entry."""
    return MockConfigEntry(
        title="Home Assistant",
        domain=DOMAIN,
        data={
            CONF_DOMAIN: "home-assistant.io",
        },
        unique_id="home-assistant.io",
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Mock setting up a config entry."""
    with patch(
        "homeassistant.components.whois.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_whoisit() -> Generator[AsyncMock]:
    """Mock whoisit.domain_async used by coordinator and config flow.

    Patches:
    - ``is_bootstrapped`` → True  (skip bootstrap network call in tests)
    - ``bootstrap_async``  → no-op AsyncMock
    - ``domain_async``     → returns _MOCK_DOMAIN_RESULT

    Because coordinator.py and config_flow.py both do ``import whoisit``,
    Python's module cache means they share the same module object.  Patching
    via the coordinator import path therefore covers both modules.
    """
    with (
        patch(
            "homeassistant.components.whois.coordinator.whoisit.is_bootstrapped",
            return_value=True,
        ),
        patch(
            "homeassistant.components.whois.coordinator.whoisit.bootstrap_async",
            new_callable=AsyncMock,
        ),
        patch(
            "homeassistant.components.whois.coordinator.whoisit.domain_async",
            new_callable=AsyncMock,
        ) as domain_mock,
    ):
        domain_mock.return_value = _MOCK_DOMAIN_RESULT
        yield domain_mock


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_whoisit: AsyncMock
) -> MockConfigEntry:
    """Set up the Whois integration for testing."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    return mock_config_entry
