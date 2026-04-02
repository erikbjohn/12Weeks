# Agent 4 — Coach LLM Engineer — Changes

## 1. Added `_format_today(ctx)` helper to coach.py (line 234)

New function placed before `_build_system_prompt`. Reads `user_timezone` from the coach context dict, imports `user_local_now` from `utils_time`, and formats the user's local date, time, and timezone into a single string. Falls back to `date.today()` with "(timezone unknown)" if `utils_time` is not yet available.

## 2. Replaced TODAY line in system prompt (coach.py line 533)

**Before:**
```
TODAY: {date.today().strftime('%A, %B %d, %Y')} ({date.today().strftime('%A')} = day {date.today().weekday()} of the training week, Mon=0)
```

**After:**
```
TODAY: {_format_today(ctx)}
```

The LLM now sees the user's local date, time, timezone name, and training-week day index.

## 3. Added `user_timezone` to coach context dict (app.py line 2556)

In `_build_coach_context()`, added:
```python
"user_timezone": current_user.timezone if hasattr(current_user, 'timezone') else 'UTC',
```

Uses `hasattr` guard so it works before and after the User model migration adds the `timezone` column.

## 4. Added ABSOLUTE RULE — TIME REFERENCES guard (coach.py lines 631-636)

Inserted before the Crisis line at the end of the system prompt:
```
ABSOLUTE RULE — TIME REFERENCES:
Never mention UTC, GMT, or server time to the athlete.
Never compute elapsed time yourself from timestamps.
Use ONLY the local time and date shown in the TODAY line above.
If unsure what time it is, say "earlier today" or "this morning" — never invent a specific time.
All pre-computed time values in the context are already in the athlete's local timezone.
```

## Dependencies

- Requires `utils_time.py` with `user_local_now(tz_name)` function (Agent 3 or similar).
- Requires `User.timezone` column on the model (Agent 2 or similar).
- Both dependencies are guarded: `try/except` in `_format_today` and `hasattr` check in `_build_coach_context`. The app will not break before those pieces land.
