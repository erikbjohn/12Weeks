# Bug Analysis: Coach Says "No Workouts" Despite User Training

**Date:** 2026-03-30
**Status:** Root causes identified -- multiple compounding issues

---

## Summary

The coach claims "you've disappeared for two days -- no workouts, no check-ins" even though the user IS training and logging sets. The root cause is a **stale `current_week` on the server** combined with **week-scoped queries** for today's sets and completed days. The exercise history query is fine (it uses date, not week), but the two most visible signals the coach relies on -- `completed_days_this_week` and `today_sets` -- are both silently returning empty data.

---

## Bug 1 (PRIMARY): Server `current_week` is stale -- all week-scoped queries return wrong data

**File:** `static/app.js` lines 3737-3750 vs `app.py` line 2582

**What happens:**
- The CLIENT auto-calculates the week from `start_date`:
  ```js
  // app.js line 3738-3748
  if (_stateCache.start_date) {
    const start = new Date(_stateCache.start_date + 'T00:00:00');
    const diffDays = Math.floor((now - start) / (1000 * 60 * 60 * 24));
    const week = Math.min(12, Math.max(1, Math.floor(diffDays / 7) + 1));
    currentWeek = week;  // e.g., week 5
  }
  ```
- But `saveState()` is NEVER called after this auto-advance. It's only called in `setPhase()` and `setWeek()` (manual UI actions).
- The SERVER reads `current_week` from the DB via `_get_state()`:
  ```python
  # app.py line 2582
  s = _get_state()
  week = s.current_week  # Still 1 (or whatever was last manually saved)
  ```

**Impact on coach context:**
1. `today_sets` query (line 2650-2652) filters `SetLog.week == stale_week`. User's sets are saved with the correct week (from JS `currentWeek`), but the server queries with the stale week. **Result: empty set data.**
2. `completed_days_this_week` query (line 2721-2724) filters `DayCompletion.week == stale_week`. **Result: empty completed days list.**
3. `workout_today` (line 2588-2591) uses `get_workouts(stale_week)`. **Result: shows wrong workout plan.**

**What the coach system prompt receives:**
```
Days completed this week: None yet
TODAY'S SETS (per-set detail):         <-- empty
```
The coach sees "None yet" for completed days and no set data, so it concludes the user hasn't trained.

---

## Bug 2 (SECONDARY): `DayCompletion` unique constraint missing `user_id`

**File:** `models.py` line 187

```python
class DayCompletion(db.Model):
    __table_args__ = (db.UniqueConstraint("week", "day_idx"),)  # NO user_id!
```

The unique constraint is `(week, day_idx)` without `user_id`. This means:
- If two users are on the same week, only ONE can have a `DayCompletion` for a given day.
- The second user's insert will either fail silently or hit a conflict.
- This is a multi-tenant data corruption bug, though for a single-user deployment it won't trigger.

Compare with `ExerciseCompletion` which has the same problem:
```python
__table_args__ = (db.UniqueConstraint("week", "day_idx", "exercise_idx"),)  # Also missing user_id
```

---

## Bug 3 (CONTRIBUTING): Exercise history is fine, but alone is not enough

**File:** `app.py` lines 2629-2646, `coach.py` line 28-42

The `ExerciseLog` query does NOT filter by week -- it uses `logged_date.desc()` and returns the last 200 entries. This means `_format_exercise_history()` DOES return data correctly:
```
EXERCISE HISTORY (last 3 sessions per exercise -- shows progression):
  Barbell Bench Press: wk4:135lbx10 -> wk5:140lbx10
```

However, the RPE feedback (`submitRPE`) which writes `ExerciseLog` only fires when the user explicitly rates an exercise (Too Easy / Just Right / Too Hard). If the user completes sets but skips RPE rating, no `ExerciseLog` is written for that session. The per-set data is in `SetLog`, but the coach only sees it via the week-scoped `today_sets` query (which is broken per Bug 1).

So the coach might see exercise history from previous weeks, but nothing from the current session unless (a) the `today_sets` query works (broken) or (b) the user rated RPE.

---

## Bug 4 (CONTRIBUTING): Compliance score degrades from stale week data

**File:** `compliance.py` lines 54-64

The compliance engine converts `DayCompletion(week, day_idx)` to actual dates using:
```python
d = state.start_date + timedelta(days=(dc.week - 1) * 7 + dc.day_idx)
```

This conversion is correct IF `DayCompletion.week` was saved with the right week number. Since the JS client sends the correct `currentWeek` when toggling day completion, the compliance calculation should work for days the user actually marked complete.

BUT: the compliance engine counts EVERY non-Sunday as a required workout day:
```python
# Line 168-176
if not is_sunday:
    day_max += 10
    workout_max += 10
    if d in completed_days:
        day_points += 10
    elif d < today:
        day_points -= 20  # -20 for missed workout
```

This means rest days (e.g., Wednesday, Saturday rest days in the program) are counted as missed workouts (-20 points each). Over a few weeks, this tanks the compliance score to D/F territory, which triggers the angry coach tone:

```python
# coach.py line 429-430
else:  # F
    tone = "TONE: The athlete has effectively checked out. You are furious..."
```

---

## Bug 5 (EDGE CASE): Morning popup auto-creates a "[MISSED]" morning check-in

**File:** `static/app.js` lines 5727-5741

If the user opens the app after noon (e.g., they trained in the morning but didn't open the app until 1pm), the morning popup auto-fires a `[MISSED]` check-in:
```js
if (hour >= 12 && !hasPopupFired('morning') && !_morningCheckinDone) {
    apiPost('/api/morning-checkin', {
        notes: '[MISSED] Morning check-in not completed before noon',
        missed: true,
    });
}
```

This creates a MorningCheckIn with all-zero values (sleep=0, stress=0, mood=0) and the `[MISSED]` flag. The coach context then sees:
```python
# app.py line 2744-2746
if mc_today and mc_today.notes and '[MISSED]' in (mc_today.notes or ''):
    missed_today = True
```

Which injects into the system prompt:
```
ALERT: The user MISSED their morning check-in today. Reference this directly -- they skipped accountability.
```

Combined with an F compliance grade, this guarantees the coach opens with an aggressive "you disappeared" message.

---

## The Full Cascade

1. Server `current_week` = 1 (stale, never synced from client's auto-advance)
2. `today_sets` query returns empty (wrong week filter)
3. `completed_days_this_week` returns empty (wrong week filter)
4. `workout_today` shows wrong workout
5. Compliance score is D/F because rest days count as missed workouts
6. Morning checkin marked `[MISSED]` because user opened app after noon
7. Coach tone = "furious" (F grade)
8. Coach system prompt says: `Days completed this week: None yet`, no set data, missed checkin alert
9. Coach concludes: "You've disappeared for two days"

Meanwhile the user's `ExerciseLog` and `SetLog` tables have all their real training data, correctly saved with the right week numbers by the JS client. The server just can't find it because it's looking in the wrong week.

---

## Fixes Required

### Fix 1 (Critical): Sync `current_week` on the server
In `_build_coach_context()` (and anywhere `_get_state().current_week` is used for queries), compute the week from `start_date` server-side instead of trusting the DB value:

```python
# In _build_coach_context(), replace:
s = _get_state()
week = s.current_week

# With:
s = _get_state()
if s.start_date:
    days_elapsed = (date.today() - s.start_date).days
    week = min(12, max(1, days_elapsed // 7 + 1))
else:
    week = s.current_week
```

### Fix 2 (Critical): Add `user_id` to `DayCompletion` unique constraint
```python
__table_args__ = (db.UniqueConstraint("week", "day_idx", "user_id"),)
```
Same for `ExerciseCompletion`.

### Fix 3 (Important): Don't count rest days as missed workouts in compliance
The compliance engine should check whether a day was actually a scheduled training day before penalizing it as missed.

### Fix 4 (Important): Auto-complete day when all exercises are done
Currently the user must manually toggle the day-complete checkmark. If they complete all sets + RPE for all exercises but forget to toggle the checkmark, `DayCompletion` is never created.

### Fix 5 (Minor): Don't auto-mark morning checkin as missed for afternoon users
Either extend the cutoff or check if the user has logged any sets today before marking as missed.
