"""Constants that don't change often enough to go in Settings."""
from importlib import metadata

ADMIN_OID = "8b8fb95c-e391-43dd-a6f9-1b03574f7c39"
ADMIN_NAME = "RCTab-API"

EXPIRY_ADJUSTMENT_MSG = "Expiry adjustment"
ABOLISHMENT_ADJUSTMENT_MSG = "Abolishment adjustment"
ADJUSTMENT_DELTA = 0.001

# Email types

EMAIL_TYPE_OVERBUDGET = "overbudget"
EMAIL_TYPE_TIMEBASED = "time-based"
EMAIL_TYPE_SUB_APPROVAL = "subscription approval"
EMAIL_TYPE_SUMMARY = "summary"
EMAIL_TYPE_SUB_WELCOME = "subscription welcome"
EMAIL_TYPE_USAGE_ALERT = "usage-alert"

__version__ = metadata.version(__package__)
