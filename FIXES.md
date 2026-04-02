# Fix 4 — Adaptive Training Engine

## Phase 4A — Audit

### Current Program Structure
- **Workout data source:** `workout_data.py` — Python dicts with exercises defined per phase
- **3 distinct phases:** Phase 1 (wk 1-4, hypertrophy 4x10-12), Phase 2 (wk 5-8, strength 5x5), Phase 3 (wk 9-12, power 4x3)
- **Exercises change per phase:** Completely different exercises, splits, and rep ranges between phases
- **Deload weeks:** Weeks 4 and 8 have explicit deload programming (60% weight, reduced volume)
- **Week 12:** Test week with 1RM testing

### Audit Answers
- **Prescribed weight per exercise per week?** NO. Weight is computed at runtime by `getSuggestedWeight()` in app.js, not stored in workout data.
- **Do targets change week over week?** Rep ranges change by phase. Within a phase (e.g., weeks 1-3), exercises are the same structure.
- **Deload weeks?** YES — weeks 4 and 8 have explicit reduced programming. Week 12 is test week.
- **Past performance adjusting future targets?** YES (crude). RPE-based: 2 consecutive "too easy" = +5lb, 2 consecutive "too hard" = -5lb. Phase transitions: +20% (P1→P2), +10% (P2→P3).
- **Per-muscle difficulty weighting?** NO before Fix 4. Equipment swaps had muscle group labels but no strength profiling.

### Honest Assessment
The program is NOT the same workout 12 times — it has meaningful phase variation. But progression was primitive: a simple RPE toggle requiring 2 consecutive sessions of the same feedback. No per-set target tracking, no modification detection, no muscle group strength profiling.

---

## Fix 4 Complete — Files Changed

| File | What Changed |
|------|-------------|
| `training_engine.py` | **NEW.** Core brain: `compute_next_targets()` (7-signal progression), `compute_muscle_strength()` (per-muscle scoring), `generate_session_analysis()` (post-session compliance) |
| `models.py` | Added `MuscleGroupProfile` model (strength_score, relative_strength, user_flagged_weak). Added `SessionAnalysis` model (compliance, deviations, progressions, flags) |
| `app.py` | Added 7 SetLog column migrations (target_weight, target_reps, target_rpe, user_modified, modification_direction, set_skipped, exercise_swapped). Wired engine into POST /api/sets (target computation + modification detection), POST /api/completions/day (session analysis + muscle profiling). Added GET /api/targets/\<exercise\>. Seeded shoulders as weak for erikbjohn@gmail.com |
| `static/app.js` | Focus mode shows adjustment_reason with colored indicator (↑/↓/—/○/⚑). Exercise cards show progression arrows. `enterExerciseFocus()` fetches from /api/targets |
| `static/style.css` | Added `.focus-reason`, `.focus-indicator`, `.focus-up/hold/deload/weak/down`, `.ex-prog-indicator` |
| `coach.py` | Session analysis injected into system prompt. Added TRAINING ENGINE authority rule (coach never contradicts engine on weight prescriptions) |
| `equipment_swaps.py` | Muscle group lookup used by training engine (EXERCISE_SWAPS already had muscle_group per exercise) |

## Verification Status

- [x] Shoulder muscle group flagged as weak (startup seed for erikbjohn@gmail.com)
- [x] Shoulder exercises max +2.5lb per session (training_engine.py line 135-143)
- [x] Completing as prescribed → weight increase (standard phase progression, Signal 1)
- [x] Reducing weight → holds progression (Signal 3: "user reduced from target")
- [x] Exceeding rep target → early weight increase (Signal 5: "exceeded rep target")
- [x] Week 4/8 deload: 85% weight, -1 set (Signal 7)
- [x] Focus screen shows adjustment_reason with indicator
- [x] Session analysis generated after day completion
- [x] Coach prompt includes session analysis + training engine rule
- [x] compute_next_targets() returns adjustment_reason for every code path

---

# Fix 6 — Coach Timezone

Fix 6 complete — coach now uses user local timezone for all time references. UTC stored, local displayed. Verified by Agent 5.

## Files Changed

| File | Change |
|------|--------|
| `models.py` | Added `timezone` column to User model. All `datetime.now()` → `datetime.now(timezone.utc)` |
| `utils_time.py` | **NEW.** `to_user_local()`, `format_user_local()`, `hours_ago_local()`, `user_local_now()` |
| `app.py` | Added `/api/user/timezone` endpoint, timezone on login, migration for user.timezone column, all datetime.now() fixed |
| `coach.py` | `_format_today(ctx)` shows local time+timezone in prompt. ABSOLUTE RULE guard prevents LLM from computing times |
| `static/app.js` | Browser timezone detection on every page load via `Intl.DateTimeFormat().resolvedOptions().timeZone` |
| `templates/login.html` | Hidden timezone field auto-populated on login form |
| `garmin_client.py` | `datetime.now()` → `datetime.now(timezone.utc)` |
| `compliance.py` | `datetime.now()` → `datetime.now(timezone.utc)` |
| `training_engine.py` | `datetime.now()` → `datetime.now(timezone.utc)` |

## Verification
- Zero `datetime.now()` or `datetime.utcnow()` calls remain in any .py file
- Browser auto-detects IANA timezone and sends to backend
- Coach prompt shows "Tuesday, April 1 at 7:00 AM (America/Los_Angeles)"
- Guard rule prevents LLM from mentioning UTC or computing elapsed time
