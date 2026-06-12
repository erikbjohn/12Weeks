# Garmin Wellness History + Header Stats Strip — Design

**Date:** 2026-06-12
**Status:** Approved by Erik (layout chosen visually: header strip, option A; capture: piggyback on app-open sync)

## Goal

Erik shouldn't need Garmin Connect to see his stats. Two parts (his words: "1 and 2"):
1. **Persist** daily wellness history (sleep, HRV, body battery, readiness, stress, resting HR, VO2max) in the app DB so trends and comparisons are possible later.
2. **Show** today's numbers in the 12Weeks UI — a four-chip stats strip at the top of the day view.

Explicitly out of scope (Erik chose strip-only, option A): trend charts / a Recovery section in the progress dashboard. History is stored from day one so charts can be added later without data gaps. No tap behavior on the strip in v1. Strength-workout push remains deferred (separate decision).

## Context (verified)

- Garmin auth + activity sync shipped 2026-06-12 ([[project-garmin-sync]]); tokens live in prod (user_id 1). The throttled app-open sync (`/api/garmin/sync-activities`, 15-min server throttle, `force` bypass) is the natural capture point.
- `GarminClient` already pulls wellness live: `_get_hrv/_get_sleep/_get_body_battery/_get_training_readiness/_get_training_status/_get_stress` (garmin_client.py). Resting HR is NOT currently pulled.
- UI slots already exist: `renderGarminBar()` is a disabled stub (app.js ~9248), `.garmin-bar/.garmin-metrics/.garmin-metric` CSS survives (style.css:75-128), `metric(label, value, sub, color)` + `getMetricColor(key, rd)` helpers survive (app.js ~9252-9266). `index.html` has the `<!-- Garmin removed -->` slot (~line 71 area) and a separate dormant `readiness-alert` div (line ~53) which stays dormant — no double banners.
- History-endpoint pattern to mirror: `/api/bodyweight` (app.py:5578) — date series JSON.
- Erik's readability needs: big fonts, high contrast ([[feedback-readability]]).

## Part 1 — Persistence

**New model `GarminWellness`** (models.py, near GarminActivity):
- `user_id` FK indexed non-null; `date` (Date) — `UniqueConstraint(user_id, date)`
- `sleep_seconds` Int, `sleep_score` Int
- `hrv_last_night` Int, `hrv_weekly_avg` Int, `hrv_status` String(20)
- `body_battery` Int (most recent level), `training_readiness` Int, `training_status` String(30), `vo2max` Float
- `stress_overall` Int, `resting_hr` Int
- `raw_json` Text (selected raw fields for audit), `pulled_at` DateTime
- All metric columns nullable — Garmin frequently lacks a metric for a day; NULL means "Garmin had nothing", never 0.

**Capture — `garmin_sync.sync_wellness(gc, user_id, today)`**, called from the existing `/api/garmin/sync-activities` flow after activities (same throttle, same force bypass; failures independent — a wellness failure must not fail the activity sync, and vice versa; each reported in the result dict):
- Upsert TODAY's row every sync (body battery/readiness move during the day).
- Backfill: find missing dates between the last stored row and today, capped at 14 days back (no rows at all → the full 14); fetch per-day via GarminClient per-day getters. Backfill days are written once (skip dates that already have a row).
- New `GarminClient` additions: a `get_wellness_for_day(day_iso)` wrapper aggregating the existing per-day getters + **resting HR** (garminconnect's RHR endpoint; verify the installed 0.2.40 method — `get_rhr_day(date)` — during implementation) — returns None per-metric on failure, never raises; respects the existing 429 cooldown.
- Garmin-call budget: worst-case backfill = 14 days × ~6 calls; acceptable as an occasional cost, throttled like everything else.

**Endpoint `GET /api/garmin/wellness?days=N`** (default 1, max 90): returns `[{date, sleep_hours, sleep_score, hrv, hrv_weekly_avg, body_battery, readiness, resting_hr, stress, vo2max}]` newest-first from the DB only — never triggers a Garmin call.

## Part 2 — Header stats strip

- Re-add `<div id="garmin-bar" class="garmin-bar"></div>` to index.html in the old slot (above the day tabs / near today-nav).
- Rebuild `renderGarminBar()`: four chips from today's `GarminWellness` row —
  - **Sleep**: `😴 {h.h}h · {score}` (score ≥80 green, 60-79 amber, <60 red; no score → neutral color)
  - **HRV**: `HRV {n}` — color vs `hrv_weekly_avg` (≥ avg green; 5-15% below amber; >15% below red)
  - **Body Battery**: `🔋 {n}` (≥60 green, 30-59 amber, <30 red)
  - **Readiness**: `Ready {n}` (≥70 green, 40-69 amber, <40 red)
- Big monospace values (≥16px), reusing/refreshing the existing `.garmin-bar` CSS; verify legibility against Erik's readability bar.
- Data flow: the strip's data rides the page-load fetch batch (call `/api/garmin/wellness?days=1` alongside the run-log fetch); after the fire-and-forget auto-sync resolves, re-fetch + re-render so today's numbers land on first-open-of-the-day without a reload.
- Honesty: per-metric NULL renders a dimmed `—` chip. No `GarminWellness` row for today AND not connected → strip hidden entirely (no empty shell). Stale-day rule: the strip always queries today's date; yesterday's row is never shown as today.
- The separate `readiness-alert` banner stays dormant (not re-enabled) — one Garmin surface, not two.

## Failure handling

Same posture as the rest of the Garmin integration: wellness sync failures are logged, reported in the sync result (`wellness_error` field), and never block activities sync, page load, or the strip (which just shows what the DB has). No silent failures; no invented values.

## Testing

- pytest: `sync_wellness` upsert/backfill (missing-day fill, 14-day cap, today-refresh, skip-existing), NULL-metric handling, endpoint shape/limits — with a fake client returning canned per-day payloads.
- JS: strip rendering covered by the existing vitest setup if a pure formatter is extracted; otherwise verified via local browser smoke (chips render, NULL → dimmed dash, hidden when no data).
- Live: after deploy, Erik's strip shows last night's real sleep/HRV on app open.
