# Systematic Coach Audit & Permanent Regression Suite — Design

**Date:** 2026-05-01
**Status:** Design approved, ready for implementation plan
**Author:** Erik Johnson + Claude (brainstorming session)

---

## Problem

The coach (Anthropic Opus 4.7 with tool use, full-week program injection, banned-phrase validator) has been patched reactively for ~2 weeks. Each user-reported failure has been fixed in isolation:

- `<schedule>` block leaking into chat
- "What's on your mind" soft questions
- Cross-day hallucinations (Monday → Friday Back Squat 4×5)
- Repetitive `Done. Tomorrow:` prefix
- `Speak.` style robotic endings
- Week-drift between AppState and calendar
- "Lift now" after session done
- Missing tempo run from UI
- Deprecated `temperature` kwarg

We have no systematic way to find the failure modes that *haven't* been reported yet, no way to prevent regressions on the ones we've fixed, and no quantitative measure of coach quality. The user wants to find and fix the rest in an organized way.

## Goal

Build a **dual-purpose** test harness:

1. **Audit mode** — one-shot scan of 100+ prompts across 12 categories to surface unknown failure modes, generate a ranked report of issues to fix.
2. **Permanent regression suite** — same harness runs in CI / pre-deploy to prevent regressions on fixed bugs and on whatever new bugs the audit surfaces.

## Non-Goals

- Not a unit test suite for individual functions (those exist).
- Not a real-time monitor of production coach output (separate concern).
- Not a way to fine-tune the model (we're using Anthropic's hosted API).
- Not generating training data.

---

## Design

### 1. Architecture

**Module:** `tests/test_coach_audit.py` — pytest module, parametrized over prompt cases.

**Subpackage:** `tests/coach_audit/`
- `prompts.py` — 100+ `PromptCase` definitions, organized into 12 categories
- `users.py` — synthetic user fixtures (4 archetypes) + optional real-Erik fixture
- `judge.py` — Opus 4.7 LLM-as-judge invocation + structured JSON output schema
- `runner.py` — wires prompt + user fixture → coach call → heuristic check → judge → save findings
- `report.py` — aggregates findings into markdown report; clusters failure patterns via final Opus call

**Execution:**
- pytest with `pytest-xdist` for parallel execution (`pytest -n 8`)
- Each prompt is one parametrized test case
- `--audit-mode=full` flag enables real-Erik fixture (gated by `@pytest.mark.real_data` for opt-in)
- Default mode (no flag) runs synthetic users only — safe for CI

**Cost ceiling:**
- ~100 prompts × (1 coach call + 1 judge call) ≈ 200 Opus calls per run
- Estimated ~$50/run at current pricing (Opus 4.7, ~2K tokens average per call)
- Final clustering call: ~$0.15
- Acceptable for audit mode (run on demand). For CI, gate on `[audit]` commit tag or weekly cron.

**Tech stack:**
- pytest, pytest-xdist (parallel)
- anthropic Python SDK (already in repo)
- Existing `coach_with_tools.py` and `coach_assembler.py` invoked directly — no monkey-patching of production code
- SQLAlchemy fixtures bind to a test database via `DATABASE_URL` env override (sqlite file under `/tmp/coach_audit_<run_id>.db` is fine — the synthetic fixtures only need ~10 rows per table). A `conftest.py` flips the env before importing `app`.

**Run identification:**
- `run_id` = ISO-ish timestamp `YYYYMMDD-HHMMSS` set once at session start. Used for both findings dir and report filename so a run is self-contained on disk.

### 2. Per-Prompt Flow

Each prompt case is a `PromptCase`:

```python
@dataclass
class PromptCase:
    id: str                          # "cross_day_001"
    category: str                    # "cross_day_hallucination"
    user_message: str                # "What's on Monday?"
    user_fixture: str                # "phase_2_mid_program"
    expected_behavior: list[str]     # ["cites Front Squat", "mentions 4x3"]
    must_not: list[str]              # ["Back Squat 4x5", "schedule block"]
    focus_dimensions: list[str]      # judge weights these higher; e.g. ["accuracy", "no_hallucination"]
                                     # all four scores still emitted on every case
```

**Flow per test:**

1. **Setup** — load synthetic user into test DB (or use real Erik if `--audit-mode=full`). Fixture seeds `User`, `UserEquipment`, `PhysicalAssessment`, `AppState`, `WeeklyPrescription`, `WeeklyRunPlan`, `SetLog` history as needed for the archetype.
2. **Coach call** — invoke `coach_chat(user_id, system_prompt, [{"role": "user", "content": prompt.user_message}])`. Captures actual coach response.
3. **Heuristic check** — fast string-based asserts:
   - For each `expected_behavior` substring/regex: must appear (lowercase normalized, `×` → `x`)
   - For each `must_not` substring/regex: must NOT appear
   - Banned phrases from CORE_PROMPT must NOT appear
4. **Judge call** — Opus 4.7 with structured JSON output. Judge receives: the user message, the coach's response, the `expected_behavior` and `must_not` lists, the user's archetype description (so it knows what the ground-truth program is for that fixture), and the `focus_dimensions` to weight. Judge does NOT see the system prompt or tool results — that would let the judge "cheat" by reading what the coach was told instead of evaluating what the coach said. Returns:
   ```json
   {
     "pass": true|false,
     "scores": {
       "accuracy": 0-10,
       "tone": 0-10,
       "no_hallucination": 0-10,
       "follows_must_not": 0-10
     },
     "violations": ["specific issue 1", "specific issue 2"],
     "evidence": "quoted snippets from response"
   }
   ```
5. **Save finding** — write JSON record to `tests/coach_audit/findings/<run_id>/<prompt_id>.json` with: prompt, response, heuristic_result, judge_result, timestamp.
6. **Assert** — fail the test if heuristic OR judge fails. Test failure message includes judge's `violations` list so pytest output is actionable.

### 3. Synthetic Users + Real Erik

**Synthetic fixtures** (deterministic, fast, safe for CI):

| Fixture | Profile | Why this archetype |
|---------|---------|---------------------|
| `phase_1_newbie` | Week 2, no history, just onboarded, gym + barbell | Coach must lean on `lifting_agent` for starting weights, no extrapolation |
| `phase_2_mid_program` | Week 6, full SetLog history through week 5, gym, currently cutting | Most common state — coach must cite real numbers, progression logic |
| `phase_3_cut` | Week 9, has hit progression plateau on bench, ahead on weight loss | Tests adaptive coaching, plateau handling |
| `no_gym_bw` | Week 3, no gym, bodyweight only, kettlebells only | Coach must NOT prescribe barbell lifts, must adapt to equipment |

Each fixture is a Python factory that seeds the test DB with realistic but fake data: e.g., `phase_2_mid_program` writes 5 weeks of `SetLog` rows with progressive overload pattern, current `WeeklyPrescription` for week 6, recent `BodyWeight` entries showing -0.5 lb/wk trend.

**Real Erik fixture** (`real_erik`):
- Pulls live state from production via diagnostic endpoint (already exists: `/api/admin/debug/sql` with `ADMIN_API_KEY` from env). Hits prod read-only via SELECT statements, then mirrors the relevant rows into the local test DB so `coach_chat` can run against a normal SQLAlchemy session.
- Never writes to production DB.
- Gated by `--audit-mode=full` CLI flag and `@pytest.mark.real_data`
- Default skipped in CI; runs explicitly when Erik wants real-state audit
- Useful for catching bugs that only trigger on his actual data shape

### 4. Output Report

After all parametrized tests run, `report.py` aggregates findings into `tests/coach_audit/reports/<run_id>.md`:

**Sections:**

1. **Summary stats** — total prompts, pass rate overall, run duration, cost estimate
2. **Pass rate by category** — table sorted by failure rate (worst first):
   ```
   | Category                  | Pass | Fail | Rate  |
   | cross_day_hallucination   |   8  |   4  | 67%   |
   | banned_phrases            |  12  |   0  | 100%  |
   | ...
   ```
3. **Top failure patterns** — final Opus 4.7 call clusters all failures into themes (~$0.15). Output:
   ```
   ## Pattern: "Coach pads response with motivational fluff" (8 occurrences)
   - Affected prompts: tone_003, tone_007, tone_011, ...
   - Example: "Great work showing up. Let's get after it. ..."
   - Recommended fix: tighten BANNED_PHRASES in CORE_PROMPT
   ```
4. **Heuristic vs judge breakdown** — where heuristic passed but judge failed (subtle issues), where judge passed but heuristic failed (false positives in our checks)
5. **Judge dimension fails** — bar chart in markdown showing average scores per dimension, flagging dimensions with <7 average
6. **Recommended fixes** — ranked by `(failure_count × severity)`:
   ```
   1. [HIGH] Add `<schedule>` to render exclusion list (24 prompts affected)
   2. [MED]  Tighten progression citation in get_workout tool result (12 prompts)
   3. [LOW]  Add hint about run pacing zones in athlete_data block (3 prompts)
   ```
7. **Raw findings** — link to `findings/<run_id>/` directory for drill-down

**Permanent regression suite usage:**
- Same harness, same prompts. Audit mode = run all + generate report. CI mode = run all + fail PR if any case fails. New failures found in audit get added as new `PromptCase` entries with their `must_not` constraints, so the regression for that bug is captured forever.

---

## Categories (12 total)

These are the prompt categories that drive `PromptCase` count to 100+. Each category has 8-12 prompts at minimum.

**Incremental ramp:** the harness ships and is useful with a smaller corpus. First implementation seeds 3-5 prompts per category (~36-60 total) so the scaffolding can be verified end-to-end. Erik (or future audits) grow the corpus by appending to `prompts.py` — no harness changes needed.

1. **cross_day_hallucination** — "What's on Monday?", "What's tomorrow's lift?", asked while coach is biased toward the wrong day
2. **banned_phrases** — prompts that historically triggered "Speak.", "Done. Tomorrow:", "Let's get after it", "What's on your mind"
3. **schedule_leak** — prompts that triggered the `<schedule>` block leak in past
4. **week_drift** — prompts where AppState.current_week != actual user activity week
5. **session_status** — "should I lift now?" before/during/after session, "what's left today?"
6. **swap_logic** — "I don't have a barbell today", "the bench is taken", "swap front squat for X"
7. **progression_citation** — "what should I lift today?" — must cite real recent numbers, not invent
8. **run_pacing** — long runs, tempo runs, fasted runs — must overlay user's WeeklyRunPlan
9. **deload_handling** — week 4, week 8, week 12 deload weeks — coach must not push progression
10. **psych_intake_resume** — partial intake state, returning user, life stress acknowledgment
11. **boundary_pushback** — user tries to skip session, negotiate down a lift, request soft validation
12. **edge_cases** — empty history, missing equipment, ambiguous timezones, multi-week-old logs

---

## Open Questions / Risks

- **Judge bias:** Opus judging Opus may be soft on its own outputs. Mitigation: heuristic checks catch the strict violations (banned phrases, must-nots); judge handles nuance.
- **Cost drift:** if prompts grow to 200+, cost could double. Mitigation: report shows cost per run; can downgrade judge to Sonnet 4.6 if needed.
- **Flake from non-determinism:** coach output varies across runs. Mitigation: judge is asked to be lenient on phrasing variations, strict only on `must_not` violations and accuracy.
- **Test DB drift from production schema:** synthetic fixtures may not match prod schema if migrations diverge. Mitigation: fixtures use the same SQLAlchemy models — schema match is automatic.

---

## Success Criteria

- Harness runs end-to-end on `pytest tests/test_coach_audit.py -n 8` with synthetic users
- Generates markdown report with ranked failure list
- First audit run surfaces ≥3 previously-unknown failure modes
- Each fixed failure becomes a permanent `PromptCase` with `must_not` constraint
- CI integration: harness runs on push, fails build if regression detected on previously-fixed prompts

## Out of Scope (Future Work)

- Live production replay (capturing real user interactions and re-running them as test cases)
- Multi-turn conversation testing (current harness is single-turn)
- A/B comparison of model variants (Opus vs Sonnet vs prompt variants)
- Automatic prompt-fix loop (LLM rewrites the prompt, re-runs harness, compares)
