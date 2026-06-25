"""Deep sleep helper functions for OpenDisplay devices."""

from collections.abc import Mapping

from opendisplay.models.config import GlobalConfig

from homeassistant.util.json import JsonValueType

from .const import (
    CONF_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
    DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
    MAX_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
    MIN_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
)


def deep_sleep_seconds(device_config: GlobalConfig) -> int:
    """Return configured deep sleep duration in seconds."""
    value = device_config.power.deep_sleep_time_seconds
    try:
        return max(0, int(value))
    except TypeError, ValueError:
        return 0


def deep_sleep_enabled(device_config: GlobalConfig) -> bool:
    """Return True when deep sleep is configured on the device."""
    return deep_sleep_seconds(device_config) > 0


def deep_sleep_timeout_margin_minutes(
    options: Mapping[str, JsonValueType] | None,
) -> int:
    """Return normalized deep sleep timeout margin in minutes."""
    raw_value = (
        options.get(CONF_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES)
        if options is not None
        else None
    )
    if raw_value is None:
        return DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES
    if not isinstance(raw_value, str | int | float):
        return DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES

    try:
        margin = int(raw_value)
    except TypeError, ValueError:
        return DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES

    return min(
        MAX_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
        max(MIN_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES, margin),
    )


def availability_window_seconds(
    sleep_seconds: int,
    timeout_margin_minutes: int = DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
) -> int:
    """Return time window where sleeping device may still be considered available."""
    try:
        normalized_sleep_seconds = max(0, int(sleep_seconds))
    except TypeError, ValueError:
        return 0

    if normalized_sleep_seconds <= 0:
        return 0

    normalized_margin = deep_sleep_timeout_margin_minutes(
        {CONF_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES: timeout_margin_minutes}
    )
    return normalized_sleep_seconds + (normalized_margin * 60)
