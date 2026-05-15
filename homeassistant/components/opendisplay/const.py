"""Constants for the OpenDisplay integration."""

from datetime import timedelta

DOMAIN = "opendisplay"
CONF_ENCRYPTION_KEY = "encryption_key"

# How long an image stays in the per-device pending-upload queue while waiting
# for a deep-sleep device to advertise. After this, the entry is dropped to
# release memory.
PENDING_UPLOAD_TIMEOUT = timedelta(minutes=30)

# How often the periodic timer wakes up to purge expired pending uploads even
# when the device never advertises again.
PENDING_UPLOAD_CLEANUP_INTERVAL = timedelta(minutes=5)
