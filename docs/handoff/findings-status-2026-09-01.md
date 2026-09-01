# Findings triage — status as of 2026-09-01

Worked in the main loop from `findings-2026-08-29.md` (no workflows, no agents).
Each item was verified against current code before fixing. Suite: **989 passed, 0 failed**
(was red for 11 days). CI + pre-push gate now enforce it.

## CRITICAL — all 5 shipped

| id | what | commit |
|---|---|---|
| S001 | No backup of training history | `scripts/db_backup.py` + launchd daily pg_dump (PG18 client) → `~/12weeks-backups/`, plus `GET /api/admin/export-full` lossless JSON sidecar. First backup taken and verified (53 tables / 47 per-user tables, 8,259 rows). |
| S002 | Gluten spike guard held for ONE day at daily cadence | `cut_guard.detect_water_spike` is a 14-day windowed state carried along the expected-loss curve; clears on return to trend. No false positive on Erik's real series. |
| S003 | ADMIN_API_KEY was the leaked literal | Rotated on Render via API (old → 401, new → 200 verified); `hmac.compare_digest`; leaked/short keys hard-refused; literal scrubbed from RESTART.md + memory. New key in `~/.12weeks_admin_key`. |
| S004 | Invite → admin account takeover in 2 requests | accept_invite POST guard; `/api/invite` refuses existing addresses. Test added. |
| S005 | Non-stream `/api/chat` never codified markers | `_parse_coach_markers` called after save. Endpoint test added. |

## HIGH — shipped (25 of 39, incl. duplicates)

S006 (exact set-key resolution via alias map), S007 (partial: endpoint test), S009/S014 (rejected
set save reverts checkmark; 5xx queued, 4xx toasted), S010/S034/S040 (parked block-1/2 rows never
"recent"), S011/S030 (Cagrilintide escalations), S015 (dead destructive GET routes deleted, cookie
flags, cross-site guard), S016/S035 (coach sees on_curve; linear projection suppressed),
S017 (SDK timeouts + stale job recovery), S018 (un-check reopens auto-completed day;
DayCompletion.source), S021/S022 (no fabricated check-in scores; prod placeholder row nulled),
S031 (rest-day hero renders real run), S032 (CI + pre-push; fixed the date-expired test),
S033 (idempotent toggles), S036 (fixed earlier today — Garmin autofill blocked by blank manual
row), S037 (Garmin dead-token push + macOS notify), S038 (shipped Aug 30), S039 (start_date rail),
S041 (run detail in coach context), S042 (no static phase narrative), S044 (no boot-time DROP TABLE).

## HIGH — remaining 14, shipped later the same day (commits 587ab9a..7b3d6d2)

| id | what shipped |
|---|---|
| S043 | prod deduped (4 prescription, 34 schedule rows); UNIQUE keys on plan tables + weigh-ins; startup index bootstrap; race-tolerant writers; admin replan guard |
| S029 | `CoachMarkerLog`; every handler's failure recorded; one-time ⚠ flag bubble in chat; `<marker_outcomes>` core section |
| S026 | `[NUTRITION: daily_calories]` persists `goal.calorie_override`, regenerates the rest of the week's meal cards, survives recalibration |
| S024/S028 | day-granular plan swap; loud write-block failures; generate-status `partial` + client re-POST fills runs; Sunday button keys on lifts AND runs |
| S020 | `sseReader(res)`: carry buffer in all 14 readers, non-OK → `[ERROR]` frame, 45 s idle guard |
| S013 | tri-state onboarding check; "Couldn't reach the server — Retry" instead of Welcome |
| S007/S008 | served-prompt contract test for every agent; failed builders announced in `<section_errors>` |
| S012 | import-protocol takes `csv_text`, `dry_run`, returns per-row `changes` (new fast path — see memory) |
| S025 | `BodyWeight.event/note`; tool + endpoint + `[SCALE_EVENT]` marker; cut_guard honours a recorded gluten event; one-tap chips on the strip |
| S019 | weigh-in box on today's card |
| S023 | `program_calendar.py` / `programWeekFor` — the only week formula (11 copies removed) |
| S027 | audible timer cues, wall-clock HIIT with catch-up, screen wake lock |

**All 39 highs closed.**

## MEDIUM — 49 of 89 shipped (commits 4d0ab8f..d453bd9)

Security/cost: S133 (read-only SQL route), S091 (key-scraping scripts + dumps removed), S112 (test account
neutralized), S090 (admin allowlist), S089/S127 (paid audit opt-in). UX: S084, S051, S050/S055, S061/S085/S126,
S057/S105, S086/S109, S019-adjacent. Coach: S096/S123 (temperature sent), S062 (INFO logs), S047/S067 (max HR),
S059 (dose taken state), S058/S077 (planners see recovery + commitments), S097/S124 (context once), S125, S116,
S106, S098/S083, S121, S128, S082, S054. Data: S093, S094, S092, S108, S120, S110, S119, S053 (falsy-zero lint),
S107, S088. Already closed by highs: S060, S102, S101, S122.

**Open mediums (40):** S045 render perf, S046 chase push, S048 BW provenance, S049 exception markers, S052,
S056, S063/S065 HIIT parse, S064, S066/S069 escalation inputs, S068 memory dedupe, S070 import cycle, S071 client
consolidation, S072/S073/S103 perf, S074 curve re-anchor, S075 split admin keys, S076, S078, S079, S080, S081,
S087, S095, S099, S100, S104, S111, S113, S114, S115, S117, S118, S129, S130, S131, S132. Lows (32) untouched.
