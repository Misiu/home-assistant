"""DataUpdateCoordinator for the Whois integration."""

from __future__ import annotations

import dataclasses

import aiohttp
from whoisdomain import Domain, query as whoisdomain_query
from whoisdomain.exceptions import (
    FailedParsingWhoisOutput,
    UnknownDateFormat,
    UnknownTld,
    WhoisCommandFailed,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, SCAN_INTERVAL
from .models import WhoisData
from .rdap import async_fetch_rdap_data


def _whois_domain_to_whois_data(domain: Domain) -> WhoisData:
    """Convert a whoisdomain Domain object to a WhoisData dataclass."""
    return WhoisData(
        admin=getattr(domain, "admin", None),
        creation_date=domain.creation_date,
        dnssec=getattr(domain, "dnssec", None),
        expiration_date=domain.expiration_date,
        last_updated=domain.last_updated,
        name_servers=list(domain.name_servers or []),
        owner=getattr(domain, "owner", None),
        registrant=getattr(domain, "registrant", None),
        registrar=domain.registrar or None,
        reseller=getattr(domain, "reseller", None),
        status=domain.status or None,
        statuses=list(getattr(domain, "statuses", None) or []),
    )


class WhoisCoordinator(DataUpdateCoordinator[WhoisData | None]):
    """Class to manage fetching WHOIS data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> WhoisData | None:
        """Query WHOIS for domain information, with RDAP as fallback.

        Some WHOIS servers omit the expiration date for privacy-protected
        individual registrants (e.g. whois.dns.pl under GDPR), in which case
        the coordinator retries the lookup using RDAP so that all sensors —
        especially ``days_until_expiration`` — remain accurate.

        RDAP is also used as the primary source when the system ``whois``
        binary is unavailable (e.g. on Windows without whois.exe installed),
        which would otherwise raise an :class:`OSError`.
        """
        domain_name = self.config_entry.data[CONF_DOMAIN]
        whois_data: WhoisData | None = None
        needs_rdap = False

        try:
            result = await self.hass.async_add_executor_job(
                whoisdomain_query, domain_name
            )
        except UnknownTld:
            LOGGER.debug(
                "TLD not in whoisdomain for %s, trying RDAP fallback", domain_name
            )
            needs_rdap = True
        except (
            FailedParsingWhoisOutput,
            WhoisCommandFailed,
            UnknownDateFormat,
            OSError,
        ) as ex:
            LOGGER.debug(
                "WHOIS lookup failed for %s (%s), trying RDAP fallback",
                domain_name,
                ex,
            )
            needs_rdap = True
        else:
            if result is None:
                return None
            whois_data = _whois_domain_to_whois_data(result)
            # RDAP fallback needed when expiration_date is missing — this happens
            # when the WHOIS server omits renewal/expiry data for GDPR-redacted
            # individual registrants (e.g. whois.dns.pl for .pl domains).
            if whois_data.expiration_date is None:
                LOGGER.debug(
                    "WHOIS returned no expiration date for %s, trying RDAP fallback",
                    domain_name,
                )
                needs_rdap = True

        if not needs_rdap:
            return whois_data

        # RDAP fallback
        try:
            session = async_get_clientsession(self.hass)
            rdap_data = await async_fetch_rdap_data(session, domain_name)
        except aiohttp.ClientResponseError as ex:
            if whois_data is not None:
                # Return partial WHOIS data — expiration sensor will be unavailable
                # but other sensors (registrar, creation date, etc.) remain useful.
                LOGGER.warning(
                    "RDAP fallback failed for %s (HTTP %s); "
                    "expiration date will be unavailable",
                    domain_name,
                    ex.status,
                )
                return whois_data
            raise UpdateFailed(
                f"RDAP lookup failed with HTTP {ex.status} for {domain_name}"
            ) from ex
        except (aiohttp.ClientError, TimeoutError, ValueError) as ex:
            if whois_data is not None:
                LOGGER.warning(
                    "RDAP fallback failed for %s (%s); "
                    "expiration date will be unavailable",
                    domain_name,
                    ex,
                )
                return whois_data
            raise UpdateFailed(
                f"An error occurred during WHOIS/RDAP lookup for {domain_name}: {ex}"
            ) from ex

        if whois_data is not None:
            # Merge: keep all WHOIS fields, fill in missing expiration from RDAP.
            return dataclasses.replace(
                whois_data, expiration_date=rdap_data.expiration_date
            )

        return rdap_data

