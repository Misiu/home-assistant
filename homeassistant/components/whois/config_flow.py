"""Config flow to configure the Whois integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
import whoisit
from whoisit.errors import BootstrapError, ParseError, QueryError, UnsupportedError

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DOMAIN

from .const import DOMAIN
from .coordinator import _async_ensure_bootstrap


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

            try:
                await _async_ensure_bootstrap(self.hass)
                await whoisit.domain_async(domain)
            except BootstrapError:
                errors["base"] = "cannot_connect"
            except UnsupportedError:
                errors["base"] = "unknown_tld"
            except (QueryError, ParseError):
                errors["base"] = "unexpected_response"
            else:
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
