# Restart / Session Handoff — 2026-07-02

## Latest session (2026-07-02) — whole-app audit → 106 fixes → deployed
Merge `90de477` is **live on prod** (`one2weeks-9ewf.onrender.com`, Render
auto-deploys on push to main). Full audit report: `docs/whole-app-audit-2026-07-01.md`.

- Whole-app audit (Fable, 114 agents, adversarially verified) → **106 confirmed findings**, all fixed by theme with **141 new regression tests** + 6 post-review residuals + a coach-error UX pass.
- Suite: **509 pytest passed / 0 failed, 20 vitest passed.**
- Highlights: authenticated all `/api/debug/*` + `/api/test/create-user`; coach markers round-trip (prompt↔parser) and write WeeklyPrescription; ExerciseLog fully dead (SetLog only); canonical name-aware 3-state completion in new `workout_status.py`; generate-first atomic regen + past-week lock; equipment-class swap scaling + budget-fitted macros; Garmin lockout fix (shared client + cooldown gates + capped wellness bursts); `friendlyCoachError()` replaces raw 401/JSON in all 14 coach touchpoints.
- **BREAKING:** `/api/debug/*` and `/api/test/create-user` now require the `X-Admin-Key` header (matching `ADMIN_API_KEY`) or an admin session. The old `?admin_key=` param and hardcoded `swap-cleanup-2026-04-30` token no longer authenticate. Update curl workflows and `scripts/preview_coach_*.py`.
- Walkthrough: onboarding→week-1→weekly-generation driven live with a stubbed coach; end-of-program/new-phase states confirmed. No new product bugs found.

---

# Restart / Session Handoff — 2026-06-09

Everything below is **live on prod** (`one2weeks-9ewf.onrender.com`, commit
`b12410a`) and verified via served data unless noted. Working tree has no
uncommitted code.

## TL;DR — you can pick up clean
- All 5 code fixes committed + deployed; both data fixes applied + verified.
- A few things were verified via the **served payload / code path**, NOT by
  loading your account in a browser. Those are flagged "⏳ confirm on page" — give
  them a glance when you're back.

## What changed this session

### Code (committed + deployed)
| Commit | What | Status |
|---|---|---|
| `132aa10` | **Killed the deterministic output gate** — Opus 4.8 obeys done-lift / fast-day rules on its own | ✅ live, tested |
| `b86e589` | **today_status 3-state** (not_started / in_progress / complete) — coach can't say "you're done lifting" after 1 set | ✅ live, prod-verified (grounding read `in_progress`) |
| `b33cfb9` | **Auto-reconcile prescription UP** when a barbell lift is completed heavier than plan | ✅ live, unit-tested · ⏳ auto-path not yet watched fire live |
| `2f39c2a` | **generate-status DB fallback** — a finished plan can't be hidden by a lost in-process job | ✅ live, unit-tested |
| `b12410a` | **Planning always renders the saved week** after running, even if polling failed | ✅ live · ⏳ full run→show end-to-end not watched live |

Tests: full suite **281 passed / 71 skipped**. New: `tests/test_today_status_partial.py`,
`tests/test_prescription_autoreconcile.py`, `tests/test_generate_status_recovery.py`.
Model: Opus 4.8 (`coach.py` CLAUDE_OPUS, `coach_with_tools.py`).

### Data (direct DB, no deploy — live immediately)
- **Week 11 Monday run added** — was missing (you run every day); inserted Zone 2
  Easy 30 min. ✅ verified served.
- **Week 12 cleared to "unplanned"** — deleted 24 prescriptions + 7 runs + 7 meals
  (zero logged data — checked first). Now shows "⚠ Plan this week". ✅ verified
  served (0 exercises). Re-builds when you run planning for next week.
- (Earlier) **wk10/11 bench reconciled to your real 155** via heal.

## ⏳ Confirm on your rendered page when back
1. Coach chat on a partial/finished day — should NOT say "you're done lifting" mid-session.
2. A lift card where you out-lifted plan — header should match your logged weight (no "145 vs 155" split).
3. **Week 11 Monday** — shows your easy run, no "⚠ Run not planned".

## Open / not done (deliberately)
- **Run engine 7-day rule** — wk11's missing Monday was patched as data, but the
  generator wasn't changed to *guarantee* a run every day on a future program.
- **Permanent "no pre-bake future weeks" rule** — you chose the one-time wk12 clear,
  not the generator change. So the system can still pre-build a week unless changed.
- **Two "is workout done" calculators** (assembler slot-based vs coach_rules
  date-based) still diverge on in_progress vs not_started (neither says DONE).
- **Auto-reconcile + planning-render** fixes are deployed + tested but not yet
  *watched* firing on live prod (need your real interaction).

## Cautions
- **Don't deploy while you're mid-planning** — a restart wipes the generation's
  in-process status (that's what hid wk11 last time). The `2f39c2a` fallback now
  recovers it, but still avoid it.
- **Don't re-run planning just to "see" a saved week** — `force_regen` deletes the
  week first.
- **Don't re-derive/pre-bake a future week you haven't planned** — that's what made
  wk12 weird (a re-derive from a prior session).

## Tools (no browser needed)
- Prod: `https://one2weeks-9ewf.onrender.com` · health: `/api/debug/health`
- Read-only audit (no LLM cost), `?email=erik@placemetry.com`:
  `/api/debug/today-status`, `/api/debug/full-day-state`,
  `/api/debug/api-workouts-as-user`, `/api/debug/show-sets`
- Admin (header `X-Admin-Key: 12weeks-debug-2026`): `/api/admin/debug/sql` (SELECT),
  `/api/admin/debug/exec` (UPDATE/INSERT/DELETE), `/api/admin/heal-prescriptions`
- Your athlete account: `erik@placemetry.com` (user_id 1). Currently **week 11**,
  start_date 2026-03-30.

## Untracked scratch (safe to delete)
`*.png` screenshots, `wk10-*.json`, `ui-render-all-weeks.json`,
`scripts/preview_*.py`, `scripts/repro_planning_yes.py`, `scripts/check_*.py`.
