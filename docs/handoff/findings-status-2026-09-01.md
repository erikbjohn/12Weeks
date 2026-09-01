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

## HIGH — still open (14)

| id | what | why not yet |
|---|---|---|
| S043 | Unique constraints on plan/bodyweight tables + dedupe | needs a one-shot prod dedupe first; check for existing duplicates before adding constraints |
| S029 | Marker write failures invisible | needs a CoachMarkerLog model + chat surface (design) |
| S013 | Boot gate → onboarding on any non-401 fetch failure | client init refactor |
| S024 | force_regen deletes days the coach omitted; DB errors discard coach output | generation write path |
| S028 | Worker death mid-generation → half-written week | related to S024 |
| S020 | 14 hand-copied SSE readers, no carry buffer/timeout | client refactor |
| S026 | [NUTRITION] marker updates TrainingGoal only, not served meal cards | marker handler + overlay |
| S023 | Program-week formula copied 7× py / 4× js | refactor |
| S027 | Timers vs iOS (vibrate-only, freezes on screen lock) | client |
| S019 | No weigh-in input on day card after overlay dismissed | UX |
| S025 | Glutening cannot be codified (no marker/note) | product |
| S008 | ALL_SECTIONS pinned at config only | test/architecture |
| S012 | Protocol import dry-run / request-body CSV | admin tooling |
| S007 | Pin marker parsing on EVERY reply-persisting path | partially covered by test_chat_endpoint_codifies |

Medium (89) and low (32) untouched.
