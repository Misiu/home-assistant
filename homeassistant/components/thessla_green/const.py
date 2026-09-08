"""Constants for the Thessla Green integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "thessla_green"

CONF_DEVICE_FAMILY: Final = "device_family"
CONF_FRAMER: Final = "framer"
CONF_UNIT_ID: Final = "unit_id"

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 10
DEFAULT_FRAMER: Final = "rtu"
DEFAULT_DEVICE_FAMILY: Final = "unknown"

FRAMERS: Final = ("rtu", "socket")
DEVICE_FAMILY_NAMES: Final = {
    "unknown": "Thessla Green",
    "home_h": "AirPack Home h",
    "home_v": "AirPack Home v",
    "home_f": "AirPack Home f",
    "series_4_h": "AirPack4 h",
    "series_4_v": "AirPack4 v",
    "airpack_f": "AirPack f",
}
SCAN_INTERVAL: Final = timedelta(seconds=30)

CONF_CONSTANT_FLOW: Final = "constant_flow"
CONF_COMFORT: Final = "comfort"
CONF_ERV: Final = "erv"
CONF_PRESSURE_FILTER_ALARM: Final = "pressure_filter_alarm"
