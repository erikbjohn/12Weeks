# Engagement Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Push notifications (morning brief / dose-night / Sunday recap), recomp scoreboard, protocol calendar, pace-at-HR chart, Sunday recap — plus the I-3/I-4 fixes — in ONE final deploy.

**Architecture:** DB-backed push subscriptions + self-provisioned VAPID (SystemFlag) + a 5-minute scheduler daemon (autosync template) with PushSent idempotency; new read endpoints for calendar/efficiency; scoreboard/recap extend existing served payloads. Client work extends existing idioms (accordions, SVG charts, apiPost).

**Spec:** `docs/superpowers/specs/2026-08-11-engagement-features-design.md` — the authority. Where plan and spec disagree, spec wins.

## Global Constraints

- venv/bin/python ONLY for all test runs. Full suite green before every commit. Baseline: 760 passed / 71 skipped.
- NO deploy until every task + final review is done (single batched deploy). Deploys cost a Garmin login.
- New background work follows the autosync daemon template (app.py `_garmin_autosync_*`): daemon thread, guarded start (RENDER env / GARMIN_AUTOSYNC-style override), first action delayed, per-user try/except, never crashes the loop.
- User-local time via zoneinfo (`utils_time`), never fixed offsets. Idempotency via DB rows, never in-memory (restarts).
- Readability: ≥16px, ≥44px targets. Card boundary: no PROTOCOL_COMPOUNDS mechanism/watch_fors in any payload/UI.
- KNOWN LANDMINE: templates/index.html:77-78 UNREGISTERS all service workers on load (old cache fix). static/sw.js exists. Task 2 must resolve this deliberately (re-register with an update-safe SW), never silently delete the unregister without understanding why it exists (git log it).
- Client renders SERVED values; it computes no health math (Navy BF, pace status, etc. all server-side).
- Tests use the short-lived-context fixture pattern (tests/test_protocol_api.py style).

## Tasks

### Task 1: Push foundation (server)
Files: models.py (+PushSubscription, +PushSent), app.py (vapid helpers, subscribe/unsubscribe/vapid-public-key endpoints, push_to_user), requirements.txt (+py_vapid). Tests: tests/test_push_foundation.py.
Interfaces produced: `PushSubscription(user_id, endpoint unique, keys_json, created_at)`; `PushSent(user_id, kind, local_date; unique (user_id, kind, local_date))`; `_get_or_create_vapid() -> (private_pem, public_key_b64)` stored in SystemFlag keys `vapid_private_pem`/`vapid_public_key`; `push_to_user(user_id, title, body, tag=None) -> int` (subs pushed; 404/410 prune the row; exceptions logged never raised; uses pywebpush with vapid claims sub mailto:erik@placemetry.com); `POST /api/push/subscribe` (upsert by endpoint), `POST /api/push/unsubscribe`, `GET /api/push/vapid-public-key`.
Tests: vapid self-generates once + persists; subscribe upserts; unsubscribe deletes; push_to_user prunes on 410 (monkeypatched webpush), survives exceptions; sent-count returned.

### Task 2: Push client (service worker + settings toggle)
Files: static/sw.js (extend), templates/index.html (resolve the unregister landmine — git log its origin first), static/app.js (Notifications section in Settings: permission request → subscribe → POST; unsubscribe toggle; status display). Tests: tests/test_push_client_payload.py (server-side contracts only) + node --check.
The SW must handle `push` (showNotification with title/body/tag) and `notificationclick` (focus/open '/'). Registration must be update-safe: register with `updateViaCache: 'none'` and keep the old cache-clear behavior for CacheStorage (the unregister was a stale-cache fix — replace with targeted cache clearing, preserving why it existed).

### Task 3: Scheduler daemon + morning/dose-night pushes
Files: app.py (`_push_scheduler_tick()` + loop + guarded start; content builders `_morning_brief_body(uid, local_date)`, `_dose_night_body(uid, local_date)`). Tests: tests/test_push_scheduler.py.
Windows (user-local): morning 06:30–11:00 once/date (kind='morning'); dose-night 21:45–22:30 once/date, ONLY if a dose ≥21:00 that date is still untaken (kind='dose_night'); recap slot at Sunday 19:00–21:00 (kind='recap') calling `_sunday_recap_push(uid, local_date)` which Task 7 fills (stub returns None → no push until then; a None body NEVER writes PushSent — the recap must not burn its idempotency slot on a stub).
Tick: for users WITH subscriptions only; PushSent row check before send; write PushSent only after successful send attempt (sent>=0 ok). Frozen-time tests: fire-once semantics across ticks + restarts (DB), window edges, no-dose-date skips dose-night, timezone honored (America/Los_Angeles user at 06:30 PT fires when UTC is 13:30).

### Task 4: Recomp scoreboard
Files: app.py (extend the block-3 progress payload with `scoreboard`: {curve_target_today, on_curve (pace_status string), current_weight_despiked, lift: {suspected, tonnage_delta_pct, details}, waist: {day0, latest, delta}, bf_estimate_pct (Navy, server-side, needs height from PhysicalAssessment; null if waist/neck/height missing)}), static/app.js (panel at top of Progress rendering ONLY served values). Tests: tests/test_scoreboard.py (payload values hand-computed; Navy formula pinned: 86.010*log10(waist-neck)-70.041*log10(height)+36.76; absent-measurement → nulls not crashes; flag-absent → no scoreboard key).

### Task 5: Protocol calendar
Files: app.py (`GET /api/protocol/calendar`: {days: {iso_date: [{compound, dose_mg, time, taken}]}, escalations: [{date, kind, detail}], next_change: str|null}), static/app.js (grid view from the Protocol accordion: 12 rows × 7 cells, abbreviated compounds, ✓ on taken days, escalation flags, today highlighted, read-only). Tests: tests/test_protocol_calendar.py (292 doses grouped; escalations match protocol.escalation_dates; next_change text for today=Aug 11 is the Aug 24 dose step; no watch_fors/mechanism in payload; ≥16px/44px not testable server-side — node --check + implementer visual check).

### Task 6: Aerobic efficiency chart
Files: app.py (`GET /api/stats/aerobic-efficiency`: weekly calendar buckets (log_date-based, weeks start Monday), easy band avg_hr 118–140 inclusive, per bucket {week_start, pace_sec_per_mi, avg_hr, n_runs, miles}; omit empty buckets; ALL RunLog rows regardless of program week), static/app.js (SVG line chart "Easy pace @ Z2", inverted y (up=faster), best-week reference line computed from data). Tests: tests/test_aerobic_efficiency.py (bucketing spans parked weeks correctly by DATE; band filter excludes HR 141/117; pace math hand-checked; no zero-fill).

### Task 7: Sunday recap (builder + card + push wiring)
Files: weekly_report.py or app.py (`build_sunday_recap(uid, local_date) -> {"text": str, "data": {...}}` from compute_weekly_metrics for the CURRENT block week + dose adherence (taken/scheduled that week; late counts taken)), app.py (fill Task 3's `_sunday_recap_push` stub), static/app.js (recap card atop the Sunday check-in overlay from a small `GET /api/sunday-recap` endpoint serving the same dict). Tests: tests/test_sunday_recap.py (seeded week → exact text; push fires Sunday slot with the text; card endpoint serves identical dict — one-source-of-truth assertion).

### Task 8: I-3 + I-4 fixes
Files: weekly_report.py (I-3: block-3 mode → weight_vs_projected judged via pace_status(despiked, ...) with CURVE_TOLERANCE_LB vs stored curve; legacy path unchanged), cut_guard.py + app.py + transition_block3.py (I-4: per-user SystemFlag keys `projection_mode:<uid>`/`block3_anchor:<uid>`; readers try keyed first then legacy unkeyed fallback; one-shot startup migration renames Erik's unkeyed rows to keyed (guarded by SystemFlag marker per the existing one-shot pattern); transition/rollback write/delete keyed rows). Tests: tests/test_i3_i4_fixes.py (spiked weigh-in → report agrees with badge; keyed/fallback/migration; a second user WITHOUT flags gets legacy behavior even while Erik's flags exist — the actual I-4 bug pinned).

### Task 9: Allowlist + verification prep
Files: app.py (serve-as-user allowlist += /api/protocol/calendar, /api/stats/aerobic-efficiency, /api/run-log, /api/sunday-recap). Tests: extend tests/test_debug_surface.py (new paths 200; boundary rule still holds).

### Task 10 (human-gated): single deploy + prod verification
Push main once. Verify via /api/debug/version. Served checks: scoreboard in progress payload; calendar 292 doses; efficiency buckets present; push subscribe flow live (Erik enables notifications on his phone); recap endpoint; I-4 keyed flags present + legacy renamed. Erik's step: Settings → enable notifications.
