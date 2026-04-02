# Fix 6 — Backend Changes (AGENT 3)

## Changes Made

### 1. Created `utils_time.py` — timezone helper module
- `to_user_local(utc_dt, user_timezone)` — convert UTC to user local
- `format_user_local(utc_dt, user_timezone, fmt)` — format UTC as local time string
- `hours_ago_local(utc_dt, user_timezone)` — hours elapsed in user's local time
- `user_local_now(user_timezone)` — current time in user's timezone
- Uses `zoneinfo.ZoneInfo` (Python 3.9+) with `pytz` fallback

### 2. Timezone detection endpoint (app.py)
- Added `POST /api/user/timezone` route
- Validates timezone string via `zoneinfo` or `pytz`
- Updates `current_user.timezone` and commits

### 3. Timezone capture on login (app.py)
- Login POST handler now reads `timezone` from form data
- Validates and saves to `user.timezone` before commit

### 4. Browser timezone detection (frontend)
- `login.html`: Added hidden `<input name="timezone" id="tz-field">` with inline script to populate via `Intl.DateTimeFormat().resolvedOptions().timeZone`
- `static/app.js`: Added timezone POST to `/api/user/timezone` in DOMContentLoaded handler after auth check — ensures timezone stays current on every app load

### 5. Fixed all naive `datetime.now()` calls to `datetime.now(timezone.utc)`

**app.py** (5 occurrences + 1 `utcnow`):
- Line 385: `user.last_login_at`
- Line 444: `invite.used_at`
- Line 609: `user.last_login_at` (Google OAuth)
- Line 639: `invite.used_at` (Google OAuth)
- Line 642: `user.last_login_at` (Google OAuth new user)
- Line 1617: `datetime.utcnow().isoformat()` in export

**garmin_client.py** (1 occurrence):
- Line 62: `existing.updated_at`

**compliance.py** (1 occurrence):
- Line 172: `cs.computed_at`

**training_engine.py** (1 occurrence):
- Line 310: `profile.last_updated`

**models.py** (16 occurrences):
- All `default=lambda: datetime.now()` changed to `default=lambda: datetime.now(timezone.utc)`
- `BodyWeight.created_at` changed from `default=datetime.utcnow` to `default=lambda: datetime.now(timezone.utc)`

### Files Modified
- `/Users/erikbjohn/Documents/Github/12Weeks/models.py`
- `/Users/erikbjohn/Documents/Github/12Weeks/app.py`
- `/Users/erikbjohn/Documents/Github/12Weeks/garmin_client.py`
- `/Users/erikbjohn/Documents/Github/12Weeks/compliance.py`
- `/Users/erikbjohn/Documents/Github/12Weeks/training_engine.py`
- `/Users/erikbjohn/Documents/Github/12Weeks/templates/login.html`
- `/Users/erikbjohn/Documents/Github/12Weeks/static/app.js`

### Files Created
- `/Users/erikbjohn/Documents/Github/12Weeks/utils_time.py`
