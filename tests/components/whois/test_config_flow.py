"""Tests for the Whois config flow."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from syrupy.assertion import SnapshotAssertion
from whoisit.errors import ParseError, QueryError, UnsupportedError

from homeassistant.components.whois.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


@pytest.mark.usefixtures("mock_whoisit")
async def test_full_user_flow(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the full user configuration flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DOMAIN: "Example.com"},
    )

    assert result2.get("type") is FlowResultType.CREATE_ENTRY
    assert result2 == snapshot

    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "reason"),
    [
        pytest.param(
            UnsupportedError(), "unknown_tld", id="UnsupportedError-unknown_tld"
        ),
        pytest.param(
            QueryError("test"), "unexpected_response", id="QueryError-unexpected_response"
        ),
        pytest.param(
            ParseError(), "unexpected_response", id="ParseError-unexpected_response"
        ),
    ],
)
async def test_full_flow_with_error(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_whoisit: AsyncMock,
    snapshot: SnapshotAssertion,
    side_effect: Exception,
    reason: str,
) -> None:
    """Test the full user configuration flow with an error.

    Tests a full config flow where an error occurs, allowing the user to
    fix it and try again.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"

    mock_whoisit.side_effect = side_effect
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DOMAIN: "Example.com"},
    )

    assert result2.get("type") is FlowResultType.FORM
    assert result2.get("step_id") == "user"
    assert result2.get("errors") == {"base": reason}

    assert len(mock_setup_entry.mock_calls) == 0
    assert len(mock_whoisit.mock_calls) == 1

    mock_whoisit.side_effect = None
    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        user_input={CONF_DOMAIN: "Example.com"},
    )

    assert result3.get("type") is FlowResultType.CREATE_ENTRY
    assert result3 == snapshot

    assert len(mock_setup_entry.mock_calls) == 1
    assert len(mock_whoisit.mock_calls) == 2


async def test_full_user_flow_polish_domain(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_whoisit: AsyncMock,
) -> None:
    """Test the config flow succeeds for Polish .pl domains via whoisit.

    Polish domains (rdap.dns.pl) omit the 'handle' field and return an
    empty status list.  whoisit handles this correctly when bootstrapped
    with overrides=True.  Test data is based on the real whoisit output
    for google.pl.
    """
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
        "status": [],  # .pl domains return empty status
        "entities": {
            "registrant": [{"name": "Google LLC", "type": "entity"}],
            "registrar": [{"name": "Markmonitor, Inc.", "type": "entity"}],
        },
        "handle": "",  # rdap.dns.pl omits handle; overrides=True handles this
        "name": "google.pl",
        "type": "domain",
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result.get("type") is FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DOMAIN: "google.pl"},
    )

    assert result2.get("type") is FlowResultType.CREATE_ENTRY
    assert result2.get("data") == {CONF_DOMAIN: "google.pl"}
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.usefixtures("mock_whoisit")
async def test_already_configured(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test we abort if already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_DOMAIN: "HOME-Assistant.io"},
    )

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "already_configured"

    assert len(mock_setup_entry.mock_calls) == 0
