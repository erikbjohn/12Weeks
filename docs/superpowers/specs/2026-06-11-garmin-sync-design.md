# Garmin Connect Sync — Design

**Date:** 2026-06-11
**Status:** Approved by Erik (sections 1–3 individually approved in brainstorming)

## Goal

Bidirectional sync between the 12Weeks app and Erik's Garmin watch via Garmin Connect:

1. **Pull:** completed running/HIIT activities flow from Garmin into the app and log themselves (no more manual run entry).
2. **Push:** the coach's planned runs and HIIT sessions land on the watch as structured Garmin workouts (interval beeps, HR targets), scheduled on the correct calendar day.

Strength sessions are **not** pushed (Erik's decision — lifts stay app-guided) and watch-recorded strength activities are **not** pulled (lifts are logged set-by-set in the app).

## Approach decision

Build on the **existing unofficial `garminconnect` library integration** (v0.2.40, already in requirements and production):

- Auth, MFA, DB token persistence (`GarminTokens`), and the CLI token helper (`garmin_token_helper.py`) are already wired and stay unchanged.
- Rejected: official Garmin Developer API (approval takes weeks, aimed at companies); Strava intermediary (cannot push workouts to the watch).
- Known risk: unofficial API → rate limits (429s already handled with 15-min cooldown) and occasional breakage. Acceptable for a personal app.

## What exists today (baseline)

- `garmin_client.py` — `GarminClient`: login/MFA, token save/restore, 15-min cache, wellness pulls (HRV, sleep, body battery, training readiness, training status, stress). **No activity fetching.**
- `app.py:874-882` `_get_garmin()` per-user client cache; `app.py:8073-8176` endpoints: login, status, today, readiness, hrv-trend, save-tokens, logout.
- Coach already consumes wellness data: `coach_assembler.py:144-153` (`@section_builder("garmin")`), `overtraining.py:assess_readiness()`.
- Garmin **UI was removed** (`templates/index.html:71` "Garmin removed", `renderGarminBar()` disabled at `static/app.js:9145`, `garminConnected` hardcoded false at `app.js:168`). Backend endpoints are live.
- `RunLog` (`models.py:194-206`): `distance_miles, avg_hr, elevation_ft, duration_min, notes`, unique on `(user_id, week, day_idx)`. Manual entry only, via 4-field form (`static/app.js:7490-7530`) → POST `/api/run-log` (`app.py:10364-10390`).
- `WeeklyRunPlan` (`models.py:591-603`): `run_type (z2|tempo|hiit|long|easy|min), label, duration (string), detail (prose)`. The coach's structured segments `[{kind, minutes, reps, hr, note}]` (`coach_planning_runs.py:215-248`) are flattened to prose by `_segments_to_detail` and **not persisted**.
- Library capabilities confirmed in installed v0.2.40: `get_activities_by_date()`, `get_activity_splits()`, `upload_workout(workout_json)` → `/workout-service/workout`, `schedule_workout(workout_id, date)` → `/workout-service/schedule/{id}`, `delete` endpoints.

## Section 1 — Pull: activities → RunLog

New module `garmin_sync.py`, function `sync_activities(user_id, days_back=3)`:

- **Fetch** `get_activities_by_date(start, end)` on the user's existing Garmin session. Keep activities whose type is running-family (`running`, `trail_running`, `treadmill_running`, `track_running`) or HIIT/cardio-family (`hiit`, `indoor_cardio`); ignore all others.
- **Match** activity start date → `(week, day_idx)` using the same program-calendar mapping the dashboard uses for "today". An activity dated outside the program calendar is recorded in the audit table with null `(week, day_idx)` and creates no RunLog.
- **Upsert RunLog** with: `distance_miles` (meters→miles), `duration_min`, `avg_hr` (Garmin whole-activity average — matches RunLog's documented whole-run-mean semantics), `elevation_ft` (gain). `notes` never touched.
- **Conflict policy (Erik's decision): never overwrite a manual log.** If a RunLog exists with `source='manual'` (or legacy NULL source), the sync skips that day entirely (the activity is still recorded in the audit table). A RunLog created by sync (`source='garmin'`) may be updated by later syncs.
- **Doubles:** multiple qualifying activities on one day aggregate into the single daily RunLog: summed distance/duration/elevation, duration-weighted average HR.
- **Idempotency + audit:** new table `GarminActivity` — `user_id`, `garmin_activity_id` (unique), `start_time`, `type_key`, summary fields (distance, duration, avg HR, elevation), mapped `(week, day_idx)`, `pulled_at`. Re-syncs never double-count; the table lets us audit what the UI shows against what Garmin sent (no-UI-contradictions goal).
- **Schema changes:** `RunLog.source` column (`'manual'` | `'garmin'`; existing rows backfilled/treated as manual). Manual saves via `/api/run-log` set `source='manual'`.
- **Coach impact:** none required — coach reads RunLog as today; the day's runStatus flips to done automatically when sync fills it.

## Section 2 — Push: planned runs + HIIT → watch

- **Trigger:** automatically after weekly planning saves; re-push a day when its run plan changes mid-week; manual "Push week to watch" button.
- **Mechanism:** per run/HIIT day, build Garmin structured-workout JSON from the coach's segments → `upload_workout()` → `schedule_workout(workout_id, date)` on that day's calendar date. The watch picks up scheduled workouts on its normal sync.
- **Step mapping:** `warmup/work/recovery/cooldown/steady` → Garmin step types with time-based end conditions; segment `hr` targets → heart-rate-range targets; `reps > 1` → Garmin repeat blocks. HIIT days push as work/recovery interval workouts. Workout names like `12W Wk11 Tue — Tempo 45min`.
- **Segments persistence:** new column `WeeklyRunPlan.segments_json`, populated at planning time from the coach's structured segments (before prose flattening). For already-planned weeks (wk11): a deterministic parser inverts the machine-generated `_segments_to_detail` prose. A day that cannot be parsed cleanly pushes as a single timed workout with the correct label and total duration — **the push never invents intervals not in the plan** (no-confabulation rule).
- **Bookkeeping:** new table `GarminWorkoutLink` — `user_id`, `week`, `day_idx`, `garmin_workout_id`, `scheduled_date`, `structure_hash`, `pushed_at`, `status` (`ok`/`failed` + error). Re-push of an unchanged day (same hash) is a no-op. A changed day deletes the stale Garmin workout + schedule entry and uploads fresh — no duplicates accumulating in the Garmin calendar.
- The exact workout-service JSON shape is verified during implementation by fetching an existing workout via `get_workouts()` and mirroring its schema.

## Section 3 — Triggers, UI, failure handling

- **Pull trigger:** on dashboard load, throttled to ≥15 min between syncs (matches existing cache TTL philosophy), plus manual "Sync now". No cron, no new infrastructure.
- **UI:** revive a compact Garmin panel in settings: connection status, Connect/login (existing flow + MFA), Sync now, Push week to watch, last-sync time, and any pull/push errors. Big fonts / high contrast (readability requirement). Day card shows a small "from Garmin" marker on sync-sourced run logs so data provenance is always visible.
- **Failure handling:** graceful degradation exactly like wellness pulls — failures logged and surfaced as a status line in the settings panel; never block the app; 429 cooldown respected. Failed pushes mark the `GarminWorkoutLink` row failed and are visible in the panel with manual retry. No silent failures; no success claimed without verification.

## Testing

- **Unit (pytest):** segments → Garmin workout JSON mapping; prose→segments parser against the actual wk11 detail strings; activity payload → RunLog mapping (incl. doubles aggregation, manual-skip policy, idempotent re-sync) using real captured Garmin API payloads as fixtures.
- **Live end-to-end (with Erik):** push one real workout and verify it appears on the watch; pull one real run and verify the RunLog matches what the UI displays.

## Out of scope

- Pushing strength workouts to the watch; pulling strength activities.
- Pushing body weight / weigh-ins to Garmin.
- Official Garmin API migration, webhooks, multi-user OAuth flows.
- Any change to coach planning logic beyond persisting `segments_json`.
