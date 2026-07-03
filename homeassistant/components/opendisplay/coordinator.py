"""Passive BLE coordinator for OpenDisplay devices."""

from dataclasses import dataclass, field
from datetime import datetime
import logging
import math
from typing import override

from opendisplay import MANUFACTURER_ID, AdvertisementTracker, parse_advertisement
from opendisplay.models.advertisement import AdvertisementData, ButtonChangeEvent

from homeassistant.components.bluetooth import (
    MONOTONIC_TIME,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
    DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES,
    SIGNAL_DEVICE_SEEN,
)
from .deep_sleep import (
    availability_window_seconds,
    deep_sleep_timeout_margin_minutes as normalize_timeout_margin_minutes,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def _utc_timestamp() -> float:
    """Return UTC timestamp for state calculations."""
    return dt_util.utcnow().timestamp()


@dataclass
class OpenDisplayUpdate:
    """Parsed advertisement data for one OpenDisplay device."""

    address: str
    advertisement: AdvertisementData
    last_seen: float | None = None
    button_events: list[ButtonChangeEvent] = field(default_factory=list)


class OpenDisplayCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """Coordinator for passive BLE advertisement updates from an OpenDisplay device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        deep_sleep_time_seconds: int = 0,
        deep_sleep_timeout_margin_minutes: int = (
            DEFAULT_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES
        ),
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            address,
            BluetoothScanningMode.PASSIVE,
            connectable=False,
        )
        self.data: OpenDisplayUpdate | None = None
        self._tracker: AdvertisementTracker = AdvertisementTracker()
        self.deep_sleep_time_seconds = max(0, int(deep_sleep_time_seconds))
        self.deep_sleep_timeout_margin_minutes = normalize_timeout_margin_minutes(
            {
                CONF_DEEP_SLEEP_TIMEOUT_MARGIN_MINUTES: (
                    deep_sleep_timeout_margin_minutes
                )
            }
        )
        self._restored_last_seen: float | None = None
        self._started_ble_time = MONOTONIC_TIME()
        self._deep_sleep_deadline_unsub: CALLBACK_TYPE | None = None
        self._pending_upload = False

    @callback
    @override
    def async_start(self) -> CALLBACK_TYPE:
        """Start coordinator callbacks and deep sleep deadline watcher."""
        parent_unsub = super().async_start()
        self._async_schedule_deep_sleep_deadline()

        @callback
        def _async_stop() -> None:
            self._async_cancel_deep_sleep_deadline()
            parent_unsub()

        return _async_stop

    @property
    def deep_sleep_availability_window_seconds(self) -> int:
        """Return deep sleep availability window in seconds."""
        return availability_window_seconds(
            self.deep_sleep_time_seconds,
            self.deep_sleep_timeout_margin_minutes,
        )

    @property
    def _sleep_reference_timestamp(self) -> float | None:
        """Return timestamp used as reference for sleep window calculations."""
        if self.data is not None and self.data.last_seen is not None:
            return self.data.last_seen
        return self._restored_last_seen

    @property
    def expected_wakeup_timestamp(self) -> datetime | None:
        """Return expected wake-up timestamp from the sleep reference."""
        if self.deep_sleep_time_seconds <= 0:
            return None
        if (reference_ts := self._sleep_reference_timestamp) is None:
            return None
        return dt_util.utc_from_timestamp(reference_ts + self.deep_sleep_time_seconds)

    @property
    def deep_sleep_availability_deadline_timestamp(self) -> datetime | None:
        """Return current deadline for deep sleep availability window."""
        if self.deep_sleep_time_seconds <= 0:
            return None
        if (reference_ts := self._sleep_reference_timestamp) is None:
            return None
        return dt_util.utc_from_timestamp(
            reference_ts + self.deep_sleep_availability_window_seconds
        )

    @callback
    def async_restore_last_seen(self, value: datetime | float | None) -> None:
        """Restore last seen from persisted state."""
        if value is None:
            return
        timestamp: float
        if isinstance(value, datetime):
            timestamp = value.timestamp()
        else:
            try:
                timestamp = float(value)
            except TypeError, ValueError:
                return
        if timestamp <= 0:
            return

        if self.deep_sleep_time_seconds > 0:
            # Align old timestamps to current cycle so startup does not instantly expire.
            now = _utc_timestamp()
            if now > timestamp:
                cycle = max(
                    1, math.ceil((now - timestamp) / self.deep_sleep_time_seconds)
                )
                timestamp += (cycle - 1) * self.deep_sleep_time_seconds

        self._restored_last_seen = timestamp
        self._async_schedule_deep_sleep_deadline()
        self.async_update_listeners()

    @property
    @override
    def available(self) -> bool:
        """Return availability with deep sleep grace semantics."""
        if self.deep_sleep_time_seconds <= 0:
            return super().available

        if (reference_ts := self._sleep_reference_timestamp) is not None:
            return (
                _utc_timestamp() - reference_ts
            ) < self.deep_sleep_availability_window_seconds

        return super().available

    @property
    def pending_upload(self) -> bool:
        """Return whether this device currently has a pending upload."""
        return self._pending_upload

    @callback
    def async_set_pending_upload(self, value: bool) -> None:
        """Set pending upload state used by diagnostic entities."""
        self._pending_upload = value
        self.async_update_listeners()

    def _is_expected_sleep(self) -> bool:
        """Return True if unavailability is expected due to deep sleep."""
        if self.deep_sleep_time_seconds <= 0:
            return False
        if (reference_ts := self._sleep_reference_timestamp) is None:
            return False
        return (
            _utc_timestamp() - reference_ts
        ) < self.deep_sleep_availability_window_seconds

    @callback
    def _async_cancel_deep_sleep_deadline(self) -> None:
        """Cancel pending deep sleep deadline callback."""
        if self._deep_sleep_deadline_unsub is None:
            return
        self._deep_sleep_deadline_unsub()
        self._deep_sleep_deadline_unsub = None

    @callback
    def _async_schedule_deep_sleep_deadline(self) -> None:
        """Schedule callback when deep sleep availability window expires."""
        self._async_cancel_deep_sleep_deadline()
        if (deadline := self.deep_sleep_availability_deadline_timestamp) is None:
            return
        if deadline.timestamp() <= _utc_timestamp():
            return

        self._deep_sleep_deadline_unsub = async_track_point_in_utc_time(
            self.hass,
            self._async_deep_sleep_deadline_reached,
            deadline,
        )

    @callback
    def _async_deep_sleep_deadline_reached(self, _now: datetime) -> None:
        """Mark device unavailable once deep sleep window is over."""
        self._deep_sleep_deadline_unsub = None
        self._available = False
        self.async_update_listeners()

    @callback
    @override
    def _async_handle_unavailable(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Handle the device going unavailable."""
        if self._is_expected_sleep():
            return
        if self._available:
            _LOGGER.info("%s: Device is unavailable", service_info.address)
        super()._async_handle_unavailable(service_info)

    @callback
    @override
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Handle a Bluetooth advertisement event."""
        if (
            getattr(service_info, "time", self._started_ble_time)
            < self._started_ble_time
        ):
            return

        parsed: OpenDisplayUpdate | None = None

        if not self._available:
            _LOGGER.info("%s: Device is available again", service_info.address)

        if MANUFACTURER_ID not in service_info.manufacturer_data:
            return

        try:
            advertisement = parse_advertisement(
                service_info.manufacturer_data[MANUFACTURER_ID]
            )
        except ValueError as err:
            _LOGGER.debug(
                "%s: Failed to parse advertisement data: %s",
                service_info.address,
                err,
                exc_info=True,
            )
        else:
            button_events = self._tracker.update(service_info.address, advertisement)
            parsed = OpenDisplayUpdate(
                address=service_info.address,
                advertisement=advertisement,
                last_seen=_utc_timestamp(),
                button_events=button_events,
            )
            self.data = parsed
            self._restored_last_seen = None
            async_dispatcher_send(
                self.hass,
                f"{SIGNAL_DEVICE_SEEN}_{service_info.address}",
            )

        super()._async_handle_bluetooth_event(service_info, change)
        if parsed is not None:
            self.data = parsed
            self._async_schedule_deep_sleep_deadline()
            self.async_update_listeners()
