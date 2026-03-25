"""DataUpdateCoordinator for the Whois integration."""

from __future__ import annotations

import whoisit
from whoisit.errors import (
    BootstrapError,
    ParseError,
    QueryError,
    ResourceDoesNotExist,
    UnsupportedError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, SCAN_INTERVAL
from .models import WhoisData

_BOOTSTRAP_CACHE_KEY = f"{DOMAIN}_whoisit_bootstrap"
_BOOTSTRAP_REFRESH_DAYS = 7


async def _async_ensure_bootstrap(hass: HomeAssistant) -> None:
    """Ensure whoisit bootstrap data is loaded and not stale.

    Bootstrap data maps TLD→RDAP-server and is fetched from IANA.  It is
    cached in ``hass.data`` so it survives coordinator restarts within a
    single HA run without re-fetching the five IANA JSON files each time.

    ``overrides=True`` relaxes whoisit's handle-field requirement so that
    ccTLD registries (e.g. NASK's rdap.dns.pl for .pl domains) that do not
    return a ``handle`` in their RDAP responses are still parsed correctly.
    """
    needs_bootstrap = not whoisit.is_bootstrapped()

    if not needs_bootstrap:
        try:
            needs_bootstrap = whoisit.bootstrap_is_older_than(_BOOTSTRAP_REFRESH_DAYS)
        except BootstrapError:
            needs_bootstrap = True

    if not needs_bootstrap:
        return

    # Try restoring from the in-memory cache first.
    cached: str | None = hass.data.get(_BOOTSTRAP_CACHE_KEY)
    if cached:
        try:
            whoisit.clear_bootstrapping()
            whoisit.load_bootstrap_data(cached)
            if not whoisit.bootstrap_is_older_than(_BOOTSTRAP_REFRESH_DAYS):
                LOGGER.debug("Loaded whoisit bootstrap from cache")
                return
            whoisit.clear_bootstrapping()
        except BootstrapError:
            whoisit.clear_bootstrapping()

    LOGGER.debug("Fetching whoisit bootstrap data from IANA")
    await whoisit.bootstrap_async(overrides=True)
    try:
        hass.data[_BOOTSTRAP_CACHE_KEY] = whoisit.save_bootstrap_data()
    except BootstrapError:
        pass


def _whoisit_to_whois_data(result: dict) -> WhoisData:
    """Convert a whoisit domain result dict to a WhoisData dataclass."""
    entities: dict = result.get("entities", {})

    registrar: str | None = None
    for entry in entities.get("registrar", []):
        if name := entry.get("name"):
            registrar = name
            break

    registrant: str | None = None
    for entry in entities.get("registrant", []):
        if name := entry.get("name"):
            registrant = name
            break

    statuses: list[str] = result.get("status", [])
    status: str | None = statuses[0] if statuses else None

    name_servers: list[str] = [
        ns.lower() for ns in result.get("nameservers", []) if ns
    ]

    return WhoisData(
        creation_date=result.get("registration_date"),
        expiration_date=result.get("expiration_date"),
        last_updated=result.get("last_changed_date"),
        registrar=registrar,
        registrant=registrant,
        name_servers=name_servers,
        dnssec=result.get("dnssec"),
        status=status,
        statuses=statuses,
    )


class WhoisCoordinator(DataUpdateCoordinator[WhoisData | None]):
    """Class to manage fetching WHOIS data via RDAP using whoisit."""

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
        """Query RDAP for domain information via whoisit."""
        domain_name = self.config_entry.data[CONF_DOMAIN]

        try:
            await _async_ensure_bootstrap(self.hass)
        except BootstrapError as ex:
            raise UpdateFailed(
                f"Failed to load RDAP bootstrap data: {ex}"
            ) from ex

        try:
            result = await whoisit.domain_async(domain_name)
        except UnsupportedError as ex:
            raise UpdateFailed(
                f"TLD for {domain_name} is not supported by RDAP: {ex}"
            ) from ex
        except ResourceDoesNotExist as ex:
            raise UpdateFailed(
                f"Domain {domain_name} does not exist: {ex}"
            ) from ex
        except (QueryError, ParseError) as ex:
            raise UpdateFailed(
                f"RDAP query failed for {domain_name}: {ex}"
            ) from ex

        return _whoisit_to_whois_data(result)
