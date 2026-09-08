"""Constants for the Thessla Green integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "thessla_green"

CONF_FRAMER: Final = "framer"
CONF_UNIT_ID: Final = "unit_id"

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 10
DEFAULT_FRAMER: Final = "rtu"

FRAMERS: Final = ("rtu", "socket")
SCAN_INTERVAL: Final = timedelta(seconds=30)

CONF_CONSTANT_FLOW: Final = "constant_flow"
CONF_COMFORT: Final = "comfort"
CONF_ERV: Final = "erv"
CONF_LEGACY_FILTER_ALARM: Final = "legacy_filter_alarm"
