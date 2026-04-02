# Fix 6 — Schema Changes (AGENT 2)

## Changes Made

### 1. User model — new `timezone` column (models.py)
- Added `timezone = db.Column(db.String(64), default='UTC')` to User model
- Placed before `created_at` in column order

### 2. Startup migration (app.py)
- Added `("user", "timezone", "VARCHAR(64) DEFAULT 'UTC'")` to the `_migrations` list
- Existing deployments will get the column via ALTER TABLE on next startup

### 3. DateTime defaults — timezone-aware (models.py)
- Changed import: `from datetime import date, datetime, timezone`
- All `default=lambda: datetime.now()` changed to `default=lambda: datetime.now(timezone.utc)`
- Fixed `BodyWeight.created_at` from `default=datetime.utcnow` to `default=lambda: datetime.now(timezone.utc)`
- All 16 DateTime columns now use consistent UTC-aware defaults
