# Fix 6 — Timezone Audit

## STEP 1: User Model

**File:** `/Users/erikbjohn/Documents/Github/12Weeks/models.py`
**Table:** `user`

| Column | Type | Default | Timezone-aware? |
|---|---|---|---|
| created_at | DateTime | `lambda: datetime.now()` | NAIVE (no tz) |
| last_login_at | DateTime | nullable | NAIVE (no tz) |

**NO timezone column exists on User.** There is no `timezone`, `tz`, or `time_zone` field anywhere in the codebase. Zero references to `pytz`, `zoneinfo`, or `ZoneInfo` in any `.py` file.

---

## STEP 2: All DateTime/Date/Timestamp Columns

Every DateTime column uses `datetime.now()` (naive, server-local) except one that uses `datetime.utcnow` (also naive, but UTC). Every Date column uses `date.today` (naive, server-local).

### DateTime columns (all NAIVE):

| Model | Table | Column | Default | Naive/Aware |
|---|---|---|---|---|
| User | user | created_at | `lambda: datetime.now()` | NAIVE |
| User | user | last_login_at | nullable, set to `datetime.now()` in code | NAIVE |
| Invite | invite | created_at | `lambda: datetime.now()` | NAIVE |
| Invite | invite | used_at | nullable, set to `datetime.now()` in code | NAIVE |
| CoachMemory | coach_memory | created_at | `lambda: datetime.now()` | NAIVE |
| ComplianceScore | compliance_score | computed_at | `lambda: datetime.now()` | NAIVE |
| MuscleGroupProfile | muscle_group_profile | last_updated | `lambda: datetime.now()` | NAIVE |
| BodyWeight | body_weight | created_at | `datetime.utcnow` | NAIVE (UTC but no tzinfo) |
| ProgressPhoto | progress_photo | created_at | `lambda: datetime.now()` | NAIVE |
| MorningCheckIn | morning_checkin | created_at | `lambda: datetime.now()` | NAIVE |
| PsychIntake | psych_intake | created_at | `lambda: datetime.now()` | NAIVE |
| GarminTokens | garmin_tokens | updated_at | `lambda: datetime.now()` | NAIVE |
| PhysicalAssessment | physical_assessment | created_at | `lambda: datetime.now()` | NAIVE |
| UserEquipment | user_equipment | created_at | `lambda: datetime.now()` | NAIVE |
| UserConstraints | user_constraints | created_at | `lambda: datetime.now()` | NAIVE |
| TrainingGoal | training_goal | created_at | `lambda: datetime.now()` | NAIVE |
| UserFoodSelections | user_food_selections | created_at | `lambda: datetime.now()` | NAIVE |
| WeeklyReport | weekly_report | created_at | `lambda: datetime.now()` | NAIVE |
| ChatMessage | chat_message | created_at | `lambda: datetime.now()` | NAIVE |

### Date columns (all NAIVE, server-local):

| Model | Table | Column | Default |
|---|---|---|---|
| SessionAnalysis | session_analysis | log_date | `date.today` |
| ExerciseLog | exercise_log | logged_date | `date.today` |
| SetLog | set_log | logged_date | `date.today` |
| RunLog | run_log | log_date | `date.today` |
| MealLog | meal_log | log_date | no default (passed in) |
| BodyWeight | body_weight | log_date | no default (passed in) |
| BodyMeasurement | body_measurement | log_date | no default (passed in) |
| ProgressPhoto | progress_photo | log_date | no default (passed in) |
| WeeklyCheckIn | weekly_checkin | check_in_date | `date.today` |
| SupplementLog | supplement_log | log_date | no default (passed in) |
| MorningCheckIn | morning_checkin | log_date | no default (passed in) |
| ChatMessage | chat_message | log_date | `date.today` |
| AppState | app_state | start_date | nullable |
| PsychIntake | psych_intake | locked_until | nullable |
| WeeklyReport | weekly_report | report_date | no default (passed in) |

### INCONSISTENCY FLAG:
`BodyWeight.created_at` uses `datetime.utcnow` (no parentheses -- passed as callable, UTC).
All other `created_at` columns use `lambda: datetime.now()` (server-local time).
These two are in DIFFERENT time bases. If the server runs in UTC, they happen to match. If the server runs in PST (or any other tz), they diverge.

---

## STEP 3: All datetime Usage in Python

### `datetime.now()` calls (all NAIVE -- no tz arg):

| File | Line | Context |
|---|---|---|
| app.py | 384 | `user.last_login_at = datetime.now()` |
| app.py | 443 | `invite.used_at = datetime.now()` |
| app.py | 608 | `user.last_login_at = datetime.now()` |
| app.py | 638 | `invite.used_at = datetime.now()` |
| app.py | 641 | `user.last_login_at = datetime.now()` |
| garmin_client.py | 62 | `existing.updated_at = datetime.now()` |
| compliance.py | 172 | `cs.computed_at = datetime.now()` |
| training_engine.py | 310 | `profile.last_updated = datetime.now()` |
| models.py | (many) | All `default=lambda: datetime.now()` |

**Every single `datetime.now()` call is naive (no timezone argument).** Total: 24+ occurrences.

### `datetime.utcnow()` calls (NAIVE UTC -- no tzinfo attached):

| File | Line | Context |
|---|---|---|
| app.py | 1616 | `"exported_at": datetime.utcnow().isoformat()` |

Only one occurrence. Used in data export. Does NOT attach tzinfo, so it's indistinguishable from a local-time datetime.

### `datetime.today()` calls:
None found.

### `.strftime()` calls:

| File | Line | Context |
|---|---|---|
| app.py | 2171 | `m.created_at.strftime("%I:%M %p")` -- chat history time display |
| app.py | 2240 | `asst_chat.created_at.strftime("%I:%M %p")` -- chat response time display |
| coach.py | 518 | `date.today().strftime('%A, %B %d, %Y')` -- today's date passed to LLM |

**The chat message timestamps displayed to the user come from `created_at.strftime("%I:%M %p")` which uses the server's local time, not the user's timezone.**

### `timedelta` usage:
20 total occurrences across 6 files (app.py, garmin_client.py, compliance.py, coach.py, training_engine.py, weekly_report.py). Used for date arithmetic like "last 14 days", "last 7 days", etc. All operate on `date.today()` which is server-local.

### `date.today()` calls:
~50+ occurrences across app.py, coach.py, compliance.py, garmin_client.py, training_engine.py, weekly_report.py. Every single one returns the server's local date -- not the user's local date.

---

## STEP 4: Coach Message Generation

### Where the LLM is called:

**Primary coach:** `coach.py` lines 188-231 (`get_coach_response`)
- Calls `_build_system_prompt(context)` (line 218)
- Calls `_build_messages(user_message, chat_history)` (line 219)
- Model: `claude-opus-4-20250514`

**System prompt builder:** `coach.py` line 234 (`_build_system_prompt`)

### Time/date context passed to the LLM:

**Line 518 of coach.py:**
```python
TODAY: {date.today().strftime('%A, %B %d, %Y')} ({date.today().strftime('%A')} = day {date.today().weekday()} of the training week, Mon=0)
```

This tells the LLM what day it is. It uses `date.today()` -- the SERVER's local date. If the server is in UTC and the user is in PST, at 9pm PST the coach thinks it's the NEXT DAY.

### Does it reference the user's timezone?
**NO.** There is zero timezone awareness. No timezone is passed in the context dict. No timezone is stored on the user. No timezone conversion happens anywhere.

### Other time references in the system prompt:
- Hardcoded "6am" / "6:00" throughout the prompt template (lines 447-448, 511, 583-585, etc.)
- "Tomorrow, 6am. Legs." is a pattern repeated many times
- The workout timing data in `workout_data.py` hardcodes "6:00" start times

---

## STEP 5: Time-based Coach Messages

### Hardcoded time references in coach.py system prompt:

| Line | Text |
|---|---|
| 447 | `"Tomorrow, 6am. Legs. Be there."` |
| 448 | `"You're up at 6. Warm-up by 6:05."` |
| 511 | `"Tomorrow, 6am. Legs."` |
| 583 | `"Recovery tonight -- stretch, hydrate. Tomorrow, 6am. Legs."` |
| 585 | `"Tomorrow, 6am. We build on it."` |
| 590 | `"Every morning you greet the athlete..."` |
| 614 | `"Tomorrow: legs at 6am. Rest up."` |

### Hardcoded times in workout_data.py:
All workout timing arrays start at `"6:00"`. Every single workout day assumes a 6am start.

### Morning check-in references in app.py:
- Line 2516-2518: Checks if morning check-in was missed today using `date.today()`
- Line 2907: Push notification body: `"Time for your morning check-in!"`

### "Disappeared" / "hours ago" patterns:
No references to "disappeared" or "hours ago" found. The coach does not currently track elapsed time since last interaction.

---

## STEP 6: Session/Food/Workout Timestamp Writes

### Where timestamps are written to DB:

**Chat messages (app.py):**
- Line 2192: `ChatMessage(role="user", ..., log_date=date.today(), ...)` -- server date
- Line 2207: `ChatMessage(role="assistant", ..., log_date=date.today(), ...)` -- server date
- Line 2254: same pattern (streaming endpoint)
- Line 2301: same pattern (streaming save)
- Line 3677-3678: morning briefing saves with `log_date=date.today()`
- `created_at` defaults to `datetime.now()` on the model

**Exercise logs (app.py):**
- Line 1101: `existing.logged_date = date.today()`
- Line 1119: `logged_date=date.today()`
- Line 1157: `existing.logged_date = date.today()`
- Line 1162: `logged_date=date.today()`

**Set logs (app.py):**
- Line 1240: `day_idx = date.today().weekday()` -- used to determine which workout
- Line 1257: `logged_date=date.today()`

**Meal logs (app.py):**
- Lines 1392, 1421, 1472, 1514: `date.fromisoformat(data.get("date", date.today().isoformat()))` -- accepts client date but falls back to server date

**Morning check-ins (app.py):**
- Line 1775: `date.today().isoformat()` for query default
- Line 1797: `date.fromisoformat(data.get("date", date.today().isoformat()))` -- accepts client date

**Supplement logs (app.py):**
- Line 1583, 1593: `date.today()` for query/save defaults

**Body weight (app.py):**
- Line 3008: `BodyWeight(log_date=date.today(), ...)`

**Weekly check-in (app.py):**
- Line 1570: `check_in_date=date.today()`

**Run logs (app.py):**
- Line 3981: `log_date=date.today()`

**Progress photos (app.py):**
- Line 2635: `log_date=date.today()`

**Weekly reports (app.py):**
- Line 3509: `report_date=date.today()`

**Coach context queries also use `date.today()`:**
- Line 2314: `since = date.today() - timedelta(days=14)` for check-ins
- Line 2364: `today_idx = date.today().weekday()` for workout lookup
- Line 2368: supplement query by `log_date=date.today()`
- Line 2476: meal log query by `log_date=date.today()`
- Line 2518: morning check-in query by `log_date=date.today()`

### KEY FINDING:
Some endpoints accept a `date` from the client (meal logs, morning check-ins) but fall back to `date.today()` (server time). Others (exercise logs, chat messages, body weight, etc.) hardcode `date.today()` with no client override.

---

## STEP 7: DB Connection Method

**SQLAlchemy ORM via Flask-SQLAlchemy.**

`models.py` line 7:
```python
db = SQLAlchemy()
```

`models.py` line 4:
```python
from flask_sqlalchemy import SQLAlchemy
```

Standard Flask-SQLAlchemy pattern. All models inherit from `db.Model`.

---

## SUMMARY OF FINDINGS

### Critical Issues:

1. **No timezone column on User model.** The user's timezone is never stored, never asked for, never inferred.

2. **Every `datetime.now()` and `date.today()` is server-local.** If the server runs in UTC (standard for cloud deploys), a user in PST at 9pm sees the coach think it's the next day. At 4pm PST, the coach thinks it's midnight.

3. **The coach LLM is told the wrong day.** `coach.py:518` passes `date.today()` to the system prompt. This is the server's date, not the user's date. The coach may say "Good morning" at 10pm, or schedule tomorrow's workout for what is actually today.

4. **Chat timestamps displayed to users are server time.** `app.py:2171` formats `created_at` with `strftime("%I:%M %p")` -- this is whatever time `datetime.now()` recorded, which is server-local. No conversion to user's timezone.

5. **Workout day lookup uses server date.** `date.today().weekday()` determines which workout to show. If the server is UTC and user is PST, after 4pm PST the app shows tomorrow's workout.

6. **One model uses `datetime.utcnow`**, all others use `datetime.now()`.** `BodyWeight.created_at` (line 218 of models.py) is the outlier. This means timestamps in `body_weight` are in a different time base than every other table if the server is not UTC.

7. **`date.today()` used ~50+ times across the codebase** for queries, writes, and logic. Every instance assumes server time = user time.

8. **Hardcoded "6am" in coach prompts.** The coach always says "6am" regardless of user's actual schedule or timezone.

### What Needs to Happen:

1. Add a `timezone` column to the `User` model (e.g., `America/Los_Angeles`)
2. Collect timezone from the client (JS `Intl.DateTimeFormat().resolvedOptions().timeZone`)
3. Create a helper like `user_now(tz)` that returns timezone-aware datetime
4. Replace every `date.today()` / `datetime.now()` with timezone-aware equivalents
5. Convert stored UTC timestamps to user timezone for display
6. Pass user timezone into coach system prompt
7. Fix the `BodyWeight.created_at` inconsistency (use same convention everywhere)
