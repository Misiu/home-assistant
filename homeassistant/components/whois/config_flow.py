"""Config flow to configure the Whois integration."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
import whoisdomain
from whoisdomain.exceptions import (
    FailedParsingWhoisOutput,
    UnknownDateFormat,
    UnknownTld,
    WhoisCommandFailed,
    WhoisPrivateRegistry,
    WhoisQuotaExceeded,
)

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DOMAIN
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, LOGGER
from .rdap import async_fetch_rdap_data


class WhoisFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Whois."""

    VERSION = 1

    imported_name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            domain = user_input[CONF_DOMAIN].lower()

            await self.async_set_unique_id(domain)
            self._abort_if_unique_id_configured()

            # Error key set when WHOIS fails but we should still try RDAP.
            _rdap_fallback_error: str | None = None

            try:
                await self.hass.async_add_executor_job(whoisdomain.query, domain)
            except UnknownTld:
                _rdap_fallback_error = "unknown_tld"
            except WhoisCommandFailed:
                _rdap_fallback_error = "whois_command_failed"
            except FailedParsingWhoisOutput:
                _rdap_fallback_error = "unexpected_response"
            except UnknownDateFormat:
                _rdap_fallback_error = "unknown_date_format"
            except WhoisPrivateRegistry:
                errors["base"] = "private_registry"
            except WhoisQuotaExceeded:
                errors["base"] = "quota_exceeded"
            except OSError:
                # whois binary not installed (e.g. Windows without whois.exe).
                _rdap_fallback_error = "whois_command_failed"

            if _rdap_fallback_error is not None:
                # WHOIS failed for a recoverable reason — try RDAP before giving up.
                LOGGER.debug(
                    "WHOIS query failed for %s (would show %s), trying RDAP",
                    domain,
                    _rdap_fallback_error,
                )
                try:
                    await async_fetch_rdap_data(
                        async_get_clientsession(self.hass), domain
                    )
                except (aiohttp.ClientError, TimeoutError, ValueError):
                    errors["base"] = _rdap_fallback_error

            if not errors:
                return self.async_create_entry(
                    title=self.imported_name or user_input[CONF_DOMAIN],
                    data={
                        CONF_DOMAIN: domain,
                    },
                )
        else:
            user_input = {}

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DOMAIN, default=user_input.get(CONF_DOMAIN, "")
                    ): str,
                }
            ),
            errors=errors,
        )
