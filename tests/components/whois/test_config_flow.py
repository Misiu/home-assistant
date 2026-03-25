"""Tests for the Whois config flow."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion
from whoisdomain.exceptions import (
    FailedParsingWhoisOutput,
    UnknownDateFormat,
    UnknownTld,
    WhoisCommandFailed,
    WhoisPrivateRegistry,
    WhoisQuotaExceeded,
)

from homeassistant.components.whois.const import DOMAIN
from homeassistant.components.whois.models import WhoisData
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


@pytest.mark.usefixtures("mock_whois")
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
    ("throw", "reason"),
    [
        (UnknownTld, "unknown_tld"),
        (FailedParsingWhoisOutput, "unexpected_response"),
        (UnknownDateFormat, "unknown_date_format"),
        (WhoisCommandFailed, "whois_command_failed"),
        (WhoisPrivateRegistry, "private_registry"),
        (WhoisQuotaExceeded, "quota_exceeded"),
    ],
)
async def test_full_flow_with_error(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_whois: MagicMock,
    snapshot: SnapshotAssertion,
    throw: type[Exception],
    reason: str,
) -> None:
    """Test the full user configuration flow with an error.

    This tests tests a full config flow, with an error happening; allowing
    the user to fix the error and try again.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"

    mock_whois.side_effect = throw
    # For exceptions that trigger RDAP fallback, make RDAP also fail so the
    # original error reason is surfaced to the user.
    with patch(
        "homeassistant.components.whois.config_flow.async_fetch_rdap_data",
        side_effect=ValueError("RDAP also failed"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_DOMAIN: "Example.com"},
        )

    assert result2.get("type") is FlowResultType.FORM
    assert result2.get("step_id") == "user"
    assert result2.get("errors") == {"base": reason}

    assert len(mock_setup_entry.mock_calls) == 0
    assert len(mock_whois.mock_calls) == 1

    mock_whois.side_effect = None
    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        user_input={CONF_DOMAIN: "Example.com"},
    )

    assert result3.get("type") is FlowResultType.CREATE_ENTRY
    assert result3 == snapshot

    assert len(mock_setup_entry.mock_calls) == 1
    assert len(mock_whois.mock_calls) == 2


async def test_full_flow_rdap_fallback(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_whois: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the config flow succeeds via RDAP when WHOIS fails (e.g. missing binary)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"

    mock_whois.side_effect = WhoisCommandFailed
    rdap_data = WhoisData(
        expiration_date=datetime(2026, 9, 19, 11, 4, 53, tzinfo=UTC),
        registrar="OVH SAS",
    )

    with patch(
        "homeassistant.components.whois.config_flow.async_fetch_rdap_data",
        return_value=rdap_data,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_DOMAIN: "jagusz.pl"},
        )

    assert result2.get("type") is FlowResultType.CREATE_ENTRY
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.usefixtures("mock_whois")
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
