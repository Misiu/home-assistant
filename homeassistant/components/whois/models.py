"""Models for the Whois integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WhoisData:
    """Represent parsed WHOIS/RDAP domain information.

    Used as the coordinator data type so that both the whoisdomain WHOIS
    library and the RDAP HTTP fallback can produce an identical data shape,
    decoupling the rest of the integration from the whoisdomain library.
    """

    admin: str | None = None
    creation_date: datetime | None = None
    dnssec: bool | None = None
    expiration_date: datetime | None = None
    last_updated: datetime | None = None
    name_servers: list[str] = field(default_factory=list)
    owner: str | None = None
    registrant: str | None = None
    registrar: str | None = None
    reseller: str | None = None
    status: str | None = None
    statuses: list[str] = field(default_factory=list)
