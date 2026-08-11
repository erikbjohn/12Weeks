# Engagement Features — Design Spec

**Date:** 2026-08-11
**Status:** Scope approved by Erik ("all 5"); spec pending his review, build proceeds
**Context:** Block 3 day 2. All five features are additive (no schema changes to
existing tables, no behavior changes to existing surfaces except where named).
ONE deploy at the end — deploys cost a Garmin login (2026-08-10 lockout lesson).

## Global constraints (inherited, binding)

- Always codify; no static/silent fallbacks; SetLog/RunLog are truth; falsy-zero
  discipline; user-local dates via zoneinfo only; no-UI-contradictions (served
  surfaces agree); readability (≥16px text, ≥44px targets, high contrast).
- Design-from-artifact rule: the user must be able to SEE everything he gave us.
- Deploys batched: this whole spec ships as one deploy. The autosync daemon
  pattern (daemon thread, first action delayed, cooldown-aware) is the template
  for any new background work.
- Garmin quiet rule: nothing new may touch Garmin AUTH; new reads are DB-only.

## F1. Web push notifications (foundation + three notifications)

**Foundation:**
- New model `PushSubscription`: id, user_id (FK, indexed), endpoint (Text,
  unique), keys_json (Text: p256dh/auth), created_at. DB-backed — the current
  in-memory `_push_subscriptions` dict dies on every restart and is replaced.
- VAPID keypair: self-generated on first need and stored in SystemFlag rows
  (`vapid_private_pem`, `vapid_public_key`) — zero dashboard steps, survives
  restarts. `py_vapid`/`cryptography` generate; pywebpush consumes. Add
  `py_vapid` to requirements if not present.
- Endpoints: `POST /api/push/subscribe` (login; body = browser PushSubscription
  JSON; upsert by endpoint), `POST /api/push/unsubscribe`,
  `GET /api/push/vapid-public-key` (login; returns the public key).
- Client: extend the EXISTING service worker (the PWA has one — extend, never
  replace; if none exists for push, add `push` + `notificationclick` handlers).
  Settings gains a "Notifications" toggle: requests permission, subscribes,
  POSTs. Notification clicks open/focus the app.
- Send helper: `push_to_user(user_id, title, body, tag)` — sends to all of the
  user's subscriptions, prunes dead ones (410/404 responses delete the row).
  Failures logged, never raised.

**Scheduler:** a second daemon loop (autosync template): tick every 5 minutes;
for each user with subscriptions, fire windows in USER-LOCAL time (zoneinfo):
- **Morning brief** at 06:30 (fire once per local date; window 06:30–11:00 so
  late server starts still deliver; skip entirely if already fired): title
  "12 Weeks" body assembled from: weigh-in done? today's dose count, workout
  headline (lift name or Rest), run label. E.g. "Weigh in · 5 doses · Lower
  Hypertrophy · Z2 40min".
- **Dose-night reminder** at 21:45 local, ONLY on dates with a scheduled dose
  at/after 21:00 (PeptideDose-derived, never hardcoded) that is still
  untaken: "Tesamorelin at 10:00 PM — fasted 2h? Take it, check it off."
- **Sunday recap** at 19:00 local Sundays (see F5 for content).
Idempotency: `PushSent` table (user_id, kind, local_date, unique together) —
a fired window writes a row; ticks check before sending. No duplicate pushes
across restarts.

## F2. Recomp scoreboard (dashboard panel)

One panel at the TOP of the Progress view ("Block 3 Scoreboard"):
- **Scale line**: the piecewise curve (already served as linear_plan in block-3
  mode) with actual weigh-in dots; current weight vs curve_target_today, badge
  on_pace/ahead/behind (SAME pace_status the server serves — client renders
  served values only, computes nothing).
- **Lift line**: lift_decline_suspected → red "lifts sliding" w/ the tripped
  numbers; else green "lifts holding/climbing" with weekly tonnage.
- **Tape line**: latest waist vs day-0 42.0 (delta), plus Navy body-fat
  estimate (server-computed from latest BodyMeasurement waist+neck+height;
  new field in the progress payload — client never computes it).
- Served by extending the existing progress/dashboard payload with a
  `scoreboard` object (server-side, one source of truth; the debug serve-as-user
  path `/api/progress` must include it for verification).

## F3. Protocol calendar

- New client view (accordion or tab from the Protocol section): a 12-week grid,
  one row per week, one cell per day; each cell lists that day's compounds
  (abbreviated: E, BPC, KPV, Reta 2mg, TB, GHK, Tesa) from a new
  `GET /api/protocol/calendar` (login): all PeptideDose rows grouped by date +
  `escalations` (protocol.escalation_dates with kind/detail) + `next_change`
  (first escalation > today, human text e.g. "Aug 24: retatrutide 2mg → 3mg").
- Escalation dates visually flagged in the grid; taken days show ✓ marks.
- Today highlighted. Read-only (check-offs stay on the daily card).
- Card boundary rule holds: no mechanism/watch_fors text.

## F4. Pace-at-HR chart (aerobic efficiency)

- Server: `GET /api/stats/aerobic-efficiency` (login): weekly buckets over ALL
  RunLog rows with distance+duration+avg_hr; per week: easy-run pace where
  avg_hr in [118, 140] (the Z2 band), reported as {week_start_date, pace_sec_per_mi,
  avg_hr, n_runs, miles}. Buckets by log_date (calendar weeks), NOT program
  week (parked-block week numbers must not scramble the timeline). Weeks with
  no qualifying runs are omitted (never zero-filled).
- Client: line chart in the Progress view ("Easy pace @ Z2") — x calendar
  weeks, y pace (inverted axis so up = faster), dots labeled with avg HR;
  reference line at the June best (computed from data, not hardcoded).
- Uses the existing chart idioms (_pdWeightChart SVG style), theme-aware.

## F5. Sunday recap

- Content builder (server, shared by push + card): from compute_weekly_metrics
  (already carries wellness + lift_trend + weight_vs_projected): "Wk N: 220→218.9
  (curve 218.75) · lifts +2 · 27 mi · doses 34/35 · sleep 7.9h avg". One
  compact string + a structured dict.
- Delivery: (a) the 19:00 Sunday push (F1 scheduler); (b) a recap card at the
  top of the Sunday check-in overlay (before measurements), rendered from the
  same served dict — one source of truth.
- Dose adherence for the week = taken/scheduled from PeptideDose (is_late
  ignored here; late counts as taken).

## F6. Queued fixes riding along (from the block-3 final review)

- **I-3**: weekly_report.weight_vs_projected → judge with pace_status on the
  DESPIKED weight vs the stored curve week value with CURVE_TOLERANCE_LB
  (replaces raw ±1.0) in block-3 mode; legacy behavior unchanged without the
  flag. The weekly report can no longer contradict the dashboard badge.
- **I-4**: per-user flag scoping: `projection_mode` and `block3_anchor`
  SystemFlag KEYS become `projection_mode:<user_id>` / `block3_anchor:<user_id>`
  with fallback reads of the legacy unkeyed names (Erik's existing rows keep
  working; a one-shot migration in the deploy renames his rows to the keyed
  form). cut_guard helpers gain the user_id they already receive.

## Testing

Per-feature unit tests (TDD, venv only): push subscribe/unsubscribe/prune +
VAPID self-generation + scheduler window logic (frozen local times, idempotency
across ticks/restarts, dose-night gating incl. no-dose dates); scoreboard
payload (served values match pace_status/lift_trend/Navy formula hand-computed);
calendar payload (292 doses grouped, escalations, next_change, no watch_fors
leak); aerobic-efficiency buckets (calendar-week bucketing incl. parked weeks,
HR band filter, empty-week omission); recap string/dict (seeded week); I-3
agreement test (spiked weigh-in: report matches badge); I-4 fallback + migration
test. Full suite green before the ONE deploy; served verification after via
serve-as-user (+ new paths added to the allowlist: /api/protocol/calendar,
/api/stats/aerobic-efficiency, /api/run-log).

## Out of scope

- Native/mobile-OS push (web push only). Email delivery of the recap.
- Any Garmin API surface changes. Any coach prompt changes.
