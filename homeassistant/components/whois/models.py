"""Models for the Whois integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WhoisData:
    """Represent parsed domain information returned by whoisit via RDAP.

    Decouples the rest of the integration from the whoisit library so that
    sensors and other consumers work with a stable internal data shape.
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
