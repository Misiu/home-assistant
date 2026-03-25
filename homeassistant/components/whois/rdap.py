"""RDAP (Registration Data Access Protocol) helpers for the Whois integration.

RDAP is an HTTP-based protocol that returns structured JSON domain data.
It is used as a fallback when the system whois binary is unavailable
(e.g. on Windows) or when the WHOIS server omits the expiration date
(e.g. whois.dns.pl omits it for individual registrants under GDPR).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import aiohttp

from .const import LOGGER
from .models import WhoisData

# IANA bootstrap file listing authoritative RDAP servers per TLD.
_IANA_RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
# Public RDAP lookup gateway used when the IANA bootstrap fails.
_RDAP_FALLBACK_URL = "https://rdap.org/domain/{domain}"


def _parse_rdap_datetime(date_str: str) -> datetime | None:
    """Parse an RDAP datetime string into a timezone-aware :class:`datetime`."""
    if not date_str:
        return None
    try:
        # Strip any sub-second precision (milliseconds, microseconds, nanoseconds, etc.)
        # that fromisoformat rejects, and normalise the 'Z' UTC designator to '+00:00'.
        normalized = re.sub(r"\.\d+Z$", "Z", date_str)
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_rdap_data(data: dict[str, Any]) -> WhoisData:
    """Parse an RDAP JSON response dict into a :class:`WhoisData` object."""
    creation_date: datetime | None = None
    expiration_date: datetime | None = None
    last_updated: datetime | None = None

    for event in data.get("events", []):
        action = event.get("eventAction", "")
        date = _parse_rdap_datetime(event.get("eventDate", ""))
        if action == "registration":
            creation_date = date
        elif action == "expiration":
            expiration_date = date
        elif action == "last changed":
            last_updated = date

    registrar: str | None = None
    registrant: str | None = None
    for entity in data.get("entities", []):
        roles = entity.get("roles", [])
        vcard = entity.get("vcardArray", [])
        fn: str | None = None
        if len(vcard) >= 2:
            for entry in vcard[1]:
                if (
                    isinstance(entry, list)
                    and len(entry) >= 4
                    and entry[0] == "fn"
                    and entry[3]
                ):
                    fn = str(entry[3])
                    break
        if "registrar" in roles and fn:
            registrar = fn
        elif "registrant" in roles and fn:
            registrant = fn

    name_servers = sorted(
        ns["ldhName"].lower()
        for ns in data.get("nameservers", [])
        if isinstance(ns, dict) and ns.get("ldhName")
    )

    dnssec: bool | None = None
    secure_dns = data.get("secureDNS")
    if isinstance(secure_dns, dict):
        dnssec = secure_dns.get("delegationSigned")

    rdap_statuses: list[str] = data.get("status") or []
    status: str | None = rdap_statuses[0] if rdap_statuses else None

    return WhoisData(
        creation_date=creation_date,
        expiration_date=expiration_date,
        last_updated=last_updated,
        registrar=registrar,
        registrant=registrant,
        name_servers=name_servers,
        dnssec=dnssec,
        status=status,
        statuses=list(rdap_statuses),
    )


async def _async_get_rdap_base_url(
    session: aiohttp.ClientSession, tld: str
) -> str | None:
    """Return the authoritative RDAP base URL for *tld* via the IANA bootstrap.

    Returns ``None`` when the bootstrap file cannot be fetched or the TLD is
    not listed, so the caller can fall back to rdap.org.
    """
    try:
        async with session.get(
            _IANA_RDAP_BOOTSTRAP_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            bootstrap = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        LOGGER.debug(
            "Failed to fetch IANA RDAP bootstrap; will use rdap.org as fallback"
        )
        return None

    tld_lower = tld.lower()
    for entry in bootstrap.get("services", []):
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        tlds, urls = entry[0], entry[1]
        if tld_lower in (t.lower() for t in tlds) and urls:
            return urls[0]
    return None


async def async_fetch_rdap_data(
    session: aiohttp.ClientSession, domain: str
) -> WhoisData:
    """Fetch and parse RDAP data for *domain*.

    Queries the authoritative RDAP server for the domain's TLD (discovered via
    the IANA bootstrap).  Falls back to ``rdap.org`` when the bootstrap lookup
    fails or the TLD is not listed.

    Raises :class:`aiohttp.ClientResponseError` on HTTP errors (e.g. 404 for
    a domain that does not exist) and :class:`Exception` on network failures.
    """
    tld = domain.rsplit(".", 1)[-1]
    base_url = await _async_get_rdap_base_url(session, tld)

    rdap_url = (
        f"{base_url.rstrip('/')}/domain/{domain}"
        if base_url
        else _RDAP_FALLBACK_URL.format(domain=domain)
    )

    LOGGER.debug("Fetching RDAP data for %s from %s", domain, rdap_url)
    async with session.get(
        rdap_url,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)

    return parse_rdap_data(data)
