"""Timezone utilities for 12 Weeks."""
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as _pytz_tz
    class ZoneInfo:
        def __new__(cls, key):
            return _pytz_tz(key)


def to_user_local(utc_dt, user_timezone):
    """Convert UTC datetime to user's local timezone."""
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(ZoneInfo(user_timezone))


def format_user_local(utc_dt, user_timezone, fmt='%I:%M %p'):
    """Format a UTC datetime as local time string."""
    if utc_dt is None:
        return 'unknown'
    local_dt = to_user_local(utc_dt, user_timezone)
    return local_dt.strftime(fmt).lstrip('0')


def hours_ago_local(utc_dt, user_timezone):
    """How many hours ago in user's local time."""
    if utc_dt is None:
        return None
    local_now = datetime.now(ZoneInfo(user_timezone))
    local_dt = to_user_local(utc_dt, user_timezone)
    delta = local_now - local_dt
    return delta.total_seconds() / 3600


def user_local_now(user_timezone):
    """Get current time in user's timezone."""
    return datetime.now(ZoneInfo(user_timezone or 'UTC'))


def user_local_today(user_timezone='UTC'):
    """Return the user's local date (not the server's UTC date)."""
    return user_local_now(user_timezone).date()
