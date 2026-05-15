"""Diagnostics support for OpenDisplay."""

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import OpenDisplayConfigEntry

TO_REDACT = {"ssid", "password", "server_url"}


def _asdict(obj: Any) -> Any:
    """Recursively convert a dataclass to a dict, encoding bytes as hex strings."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _asdict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, list):
        return [_asdict(item) for item in obj]
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OpenDisplayConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    fw = runtime.firmware

    pending = runtime.queue.pending
    pending_upload: dict[str, Any] = {"queued": pending is not None}
    if pending is not None:
        # Only expose age in seconds — never the image bytes or the (signed)
        # source URL: the queue stores already-decoded PIL images for exactly
        # that reason, but be defensive in case that ever changes.
        pending_upload["age_seconds"] = int(
            (dt_util.utcnow() - pending.enqueued_at).total_seconds()
        )
        pending_upload["failure_count"] = pending.failure_count
    else:
        pending_upload["age_seconds"] = None

    return {
        "firmware": {
            "major": fw["major"],
            "minor": fw["minor"],
            "sha": fw["sha"],
        },
        "is_flex": runtime.is_flex,
        "is_deep_sleep": runtime.is_deep_sleep,
        "device_config": async_redact_data(_asdict(runtime.device_config), TO_REDACT),
        "pending_upload": pending_upload,
    }
