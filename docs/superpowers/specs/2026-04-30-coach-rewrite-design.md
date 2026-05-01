# Coach Rewrite — Design Spec

**Date:** 2026-04-30
**Author:** Erik + Claude (brainstorm)
**Status:** Awaiting user review before plan write

## Goal

Replace the existing LLM-with-instructions coach with a **hybrid deterministic + LLM** system: a rules engine pre-computes the coach's facts (schedule, directives, current time, refusal triggers); the LLM only authors *voice* on top. Hallucinated runs, "what time are you training?", contradictory protocols, and capitulation phrases become structurally impossible — not "discouraged via prompt."

## Background

Three parallel adversarial agents audited the coach on 2026-04-30 (`docs/superpowers/research/2026-04-30-coach-audit.md`). Ten convergent failure modes:

1. Time grounding gap — current time embedded in prose, no structured field
2. Scheduled-workout-time gap — coach has no evidence Erik trains at 6am
3. Hallucination from empty sections — empty section omitted, LLM invents to fill the void
4. Agent `requires` lists silently exclude data sections (the 15.6-hour fast hallucination)
5. PROTOCOL_MAP literally instructs the LLM to ask questions while CORE_PROMPT bans them
6. No banned-phrase enforcement — capitulation phrases slip through
7. Chat history persists past hallucinations as "established truth"
8. Coach memories never expire — week 2 exception still applies in week 12
9. `weekly_review` temperature 1.0 (vs 0.6 elsewhere)
10. Time captured at prompt-build, stale during long sessions

The bones are sound. The problem is everywhere there's an opportunity to invent, the LLM invents — and the existing prompt-only architecture can't enforce constraints, only request them.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  RULES ENGINE  (new — coach_rules.py)                    │
│  Pure function of (user, now) → CoachRules dataclass     │
│  • current_time_local, current_time_utc                  │
│  • workout_today, workout_tomorrow (resolved + scheduled)│
│  • run_today, run_tomorrow (with type, time, detail)     │
│  • fasting_state (active/inactive, hours, target_break)  │
│  • next_directive (action verb + window + constraints)   │
│  • refusal_required (bool + reason)                      │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│  SECTION BUILDERS  (audited — coach_assembler.py)        │
│  • Empty sections emit sentinels, never omitted          │
│  • Coach memory + recent-events time-windowed            │
│  • Chat history replaced by event timeline (see below)   │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│  PROMPT ASSEMBLER                                        │
│  • CORE_PROMPT (rewritten — citation contract, posture)  │
│  • PROTOCOL (rewritten — directives only, no questions)  │
│  • PRE-FILLED <schedule> + <directive>                   │
│  • <athlete_data> with structured fields                 │
│  • <event_timeline>                                      │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│  LLM CALL                                                │
│  Output contract: emit <schedule>, <directive>,          │
│  <motivation>, [<refusal>] in order, exact tags          │
│  • <schedule> + <directive> echoed byte-identical        │
│  • <motivation> authored fresh (1-3 sentences)           │
│  • <refusal> only if rules.refusal_required              │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│  VALIDATOR                                               │
│  1. Parse sections — must have <schedule> + <directive>  │
│  2. Pre-filled sections byte-identical to input?         │
│  3. <motivation> + <refusal>: banned-phrase scan         │
│  4. <motivation> + <refusal>: question-mark scan         │
│  5. <refusal> contains directive language?               │
│  Failure → retry once with feedback                      │
│  Second failure → deterministic fallback template        │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│  RENDERER                                                │
│  Strip tags, join sections to prose for display          │
└──────────────────────────────────────────────────────────┘
```

## Components

### 1. Rules Engine — `coach_rules.py` (new file)

**Pure function** `compute_coach_rules(user_id, now=None) -> CoachRules` returning a frozen dataclass. No LLM. No I/O beyond DB reads. Deterministic, unit-testable, fast (< 50ms target).

**`CoachRules` dataclass fields:**

```python
@dataclass(frozen=True)
class CoachRules:
    # Time (replaces prose time injection)
    now_utc: datetime              # UTC, tzinfo-aware
    now_local: datetime            # America/Los_Angeles
    local_date_iso: str            # "2026-04-30"
    local_weekday: str             # "Thursday"
    local_time_hhmm: str           # "10:42"

    # Today's plan (resolved through swap pipeline)
    workout_today: WorkoutSummary | None
    workout_today_scheduled_at: time | None  # 06:00 default
    workout_today_status: str  # "not_started" | "in_progress" | "complete" | "rest"

    run_today: RunSummary | None       # type, label, scheduled_at, detail
    run_today_status: str              # "not_started" | "logged" | "skipped" | "rest"

    # Tomorrow's plan
    workout_tomorrow: WorkoutSummary | None
    workout_tomorrow_scheduled_at: time | None
    run_tomorrow: RunSummary | None

    # Fasting (replaces opt-in requires)
    fasting_active: bool
    fasting_hours: float | None        # None if inactive
    fasting_target_hours: float | None # 16 for IF, 40 for weekend
    fasting_break_at: datetime | None  # local time when fast ends

    # Directive (the next concrete action)
    directive: Directive
    # Directive includes: verb, target, window, constraints

    # Refusal (only set when user is asking for capitulation)
    refusal_required: bool
    refusal_reason: str | None         # "future-tense skip request" etc.
```

**Resolution order for `workout_today`:** mirrors `api_workouts` — PHASE_TEMPLATES → WeeklyPrescription override → auto_swap_workout (equipment) → ExerciseSwap (user explicit) → catalog post-processing.

**`directive` computation rules** (deterministic, ordered — first match wins):

| # | Trigger | Directive |
|---|---------|-----------|
| 1 | Refusal triggered (see below) | "Train as planned. {prescribed_action}." |
| 2 | Workout in progress (sets logged today, not all done) | "Continue. {n} sets remaining on {liftName}." |
| 3 | Workout just logged complete (≤30min ago) and run pending | "Run now. {run.label}." |
| 4 | Workout pending, now within ±2h of `workout_today_scheduled_at` | "Lift now. {liftName}." |
| 5 | Workout pending, now before window | "Lift at {time}. {liftName}." |
| 6 | Workout pending, now past window (missed) | "Missed the {time} window. Lift now or move to evening. Log it." |
| 7 | Today is rest, Sunday long run pending | "Sunday long run. {distance}. Fasted." |
| 8 | Today is rest, run pending (non-Sunday) | "Run today. {run.label} at {time}." |
| 9 | Today is rest, run complete | "Done. Tomorrow: {workout_tomorrow.liftName} at {workout_tomorrow_scheduled_at}." |
| 10 | Today is rest, no run | "Recovery day. Eat clean, sleep early." |
| 11 | Workout + run both complete | "Done. Tomorrow: {workout_tomorrow.liftName} at {workout_tomorrow_scheduled_at}." |
| 12 | Weekend fast active (Sat 7pm → Mon 11am) | "Fast holds. Break Monday 11am." |
| 13 | Sunday evening (planning new week) | "Monday: {workout_tomorrow.liftName}. {scheduled_at}. Be on the platform." |
| 14 | New PR / weight bump on last logged set | "PR logged. Weight bumps next session: {next_target}." |
| 15 | Generic chat fallback (no event) | "{phase_summary}. Stay on plan." |

**`refusal_required` triggers:**
- User message contains future-tense skip language ("I'm gonna skip Friday's lift", "rest tomorrow", "take it easy")
- User message contains time-renegotiation ("can I do it later", "what about tonight")
- User asks "should I" about a prescribed item
- Detection runs in the rules engine via regex/keyword scan on the latest user message

### 2. Section Builders — `coach_assembler.py` (audited)

Every section builder is rewritten to emit a sentinel when empty rather than returning empty string:

```python
def _build_runs(user_id):
    runs = RunLog.query.filter_by(...).order_by(...).limit(14).all()
    if not runs:
        return "<recent_runs>NONE — do not reference any run not in this section</recent_runs>"
    # ... format as before
```

Sections updated: `_build_runs`, `_build_exercise_history`, `_build_meals_today`, `_build_garmin`, `_build_coach_memories`, `_build_chat_history` (now `_build_event_timeline` — see §4).

**Agent `requires` lists eliminated.** Every agent gets every section. The `requires` mechanism was the bug source (the 15.6-hour fast). The cost is prompt bloat; the benefit is no more silent omissions. Sections are short when sentinel-only.

**`_build_coach_memories`:** filter by `created_at >= today - 21 days` (configurable). Older memories must be re-affirmed by the coach to persist. Fresh injection model: stale > silent.

### 3. Sectioned Response Contract

The LLM's output is a structured envelope, not free prose:

```
<schedule>
{pre-filled by rules engine — current_time, workout_today, workout_tomorrow}
</schedule>

<directive>
{pre-filled by rules engine — verb + target + window}
</directive>

<motivation>
{LLM authors — 1-3 sentences. Lombardi/Saban tone. Cites athlete_data
fields. No questions. No banned phrases.}
</motivation>

<refusal>
{LLM authors — only present when rules.refusal_required is true.
Echoes the directive. No collaboration phrases.}
</refusal>
```

**Pre-fill mechanism:** the prompt includes the rules engine's pre-filled `<schedule>` and `<directive>` strings verbatim, with the instruction "Echo these tags byte-identical in your response. Add `<motivation>` after, and `<refusal>` if instructed."

**Why this works:**
- LLM cannot invent schedule facts because it's not authoring them
- LLM cannot omit the directive because the validator rejects responses missing it
- Validator can byte-compare pre-filled sections to verify no LLM tampering
- `<motivation>` is the LLM's only fact-free creative space (and it's still constrained by tone rules)

**Renderer:** strip tags, render in display order: schedule → directive → motivation → refusal. Section separator is a blank line.

### 4. Event Timeline — replaces chat history

`_build_chat_history` is removed. Replaced with `_build_event_timeline(user_id, days_back=7)` that emits a structured ledger of *ground-truth events* from canonical tables — no past coach messages.

Event types (one line per event, ordered by timestamp desc):
- `[2026-04-29 06:14] LIFT logged: Front Squat 5x5 @ 175 (target 5x5 @ 175)`
- `[2026-04-29 06:48] RUN logged: Z2 30min, avg HR 142, easy effort`
- `[2026-04-29 11:32] FAST broken: 16.2h IF`
- `[2026-04-29 19:40] WEIGH-IN: 207.4 lb`
- `[2026-04-28 — DEVIATION] Skipped Tuesday HIIT (no log, no message)`

**Why:** past coach hallucinations no longer poison context. The LLM sees what *actually happened*, never what the coach previously *claimed* happened. Erik corrects ground truth via real logs (or admin), not chat.

**Coach's last 3 messages** are still injected as `<recent_coach_directives>` — a tight, time-bounded slice (just 3, just today) — so the coach has continuity but can't reference its own week-old assertions.

**User's last message** is still `<latest_user_message>` — the full text triggers refusal detection in the rules engine.

### 5. Validator — `coach_validator.py` (new file)

```python
def validate_response(raw: str, rules: CoachRules) -> ValidationResult:
    # 1. Parse sections
    sections = _parse_envelope(raw)  # {schedule, directive, motivation, refusal?}
    if "schedule" not in sections or "directive" not in sections:
        return Fail("missing required section")

    # 2. Pre-filled byte equality
    if sections["schedule"].strip() != rules.prefilled_schedule.strip():
        return Fail(f"schedule altered: {diff}")
    if sections["directive"].strip() != rules.prefilled_directive.strip():
        return Fail(f"directive altered: {diff}")

    # 3. Banned phrase scan
    banned = _scan_banned_phrases(sections["motivation"], sections.get("refusal", ""))
    if banned:
        return Fail(f"banned phrase: {banned}")

    # 4. Question-mark scan
    if "?" in sections["motivation"]:
        return Fail("motivation contains a question")
    if "refusal" in sections and "?" in sections["refusal"]:
        return Fail("refusal contains a question")

    # 5. Refusal contract
    if rules.refusal_required and "refusal" not in sections:
        return Fail("refusal required but not provided")
    if rules.refusal_required:
        # Refusal must contain a directive verb
        if not _contains_directive_verb(sections["refusal"]):
            return Fail("refusal lacks directive language")

    return Ok(sections)
```

**Banned phrase list** (Python constant `BANNED_PHRASES`, case-insensitive substring match):

| Category | Phrases |
|----------|---------|
| Capitulation | "your call", "if you feel up to it", "if you want", "feel free to", "no pressure", "up to you", "whatever works", "however you want" |
| Cheerleading | "great job", "amazing work", "you're doing great", "proud of you", "love it", "crushing it", "killing it", "way to go", "fantastic", "incredible" |
| Collaborative questions | "would you like", "do you want", "should we", "ready to", "shall we", "want me to", "how about" |
| Future-tense softening | "we could", "we might", "you might consider", "perhaps", "maybe try" |
| Negotiation | "if that works", "let's see how", "see how you feel", "play it by ear", "if you're up for it" |

**Retry logic:**
1. First call fails validation → re-prompt LLM with the validator feedback ("Your response failed validation: {reason}. Re-emit, fixing the specific issue.")
2. Second call fails → return deterministic fallback template

**Deterministic fallback:**
```
{rules.prefilled_schedule}

{rules.prefilled_directive}

Logged.
```
Austere. Acceptable. Better than capitulation.

### 6. Prompt Assembler — rewritten CORE_PROMPT + PROTOCOL_MAP

**CORE_PROMPT rewrite** (top to bottom):
- Posture: Lombardi/Saban. Coach decides, athlete executes.
- Citation contract: every claim in `<motivation>` must reference a field name from the structured `<athlete_data>` block. Validator does not enforce this in v1 (too risky for false rejections), but the prompt requires it and it's logged for audit.
- Banned phrases listed inline (the validator catches violations; the prompt makes them rare).
- Output envelope contract: explicit instruction with example.
- Rules of engagement on `<refusal>`: when present, echo the directive, name the deviation, no negotiation.

**PROTOCOL_MAP rewrite:**
- Per-event protocols (run_complete, workout_feedback, chat_opened, etc.) become **`<motivation>` style guides only**. They describe *what tone* to bring, not *what to ask*.
- All "Ask the user X" instructions are deleted. Replaced with "State X." or "Acknowledge X."
- Example: `run_complete` old: "Ask ONE question about how it felt." New: "Acknowledge the run with one observation tied to the recent_runs section. State the next directive."

### 7. Temperature

All agents → 0.6. The 1.0 on `weekly_review` was a relic; lower randomness reduces tone deviation. Validator already catches the worst offenders, but lower temperature reduces the retry rate.

## Data Flow

User opens chat / triggers event:
1. Backend resolves user + agent type (e.g., `run_complete`)
2. **Rules engine** runs: `rules = compute_coach_rules(user_id, now)`
3. Rules engine pre-renders `<schedule>` and `<directive>` strings
4. **Section builders** assemble `<athlete_data>`, `<event_timeline>`, `<recent_coach_directives>`, `<latest_user_message>` (each with sentinels for empties)
5. **Prompt assembler** combines: CORE_PROMPT + PROTOCOL[agent] + pre-filled `<schedule>`/`<directive>` + sections
6. **LLM call** at temperature 0.6
7. **Validator** parses, byte-compares pre-filled, scans `<motivation>`/`<refusal>`
8. If valid → render to prose, return to client
9. If invalid → one retry with feedback → if still invalid → deterministic fallback

## Error Handling

- **Rules engine raises:** log + fall back to a "system error, check the platform" stub. Never let the LLM see broken rules.
- **DB unavailable:** rules engine emits sentinel rules (no schedule, generic directive "Train as planned. Log when done."), proceeds with degraded prompt.
- **LLM timeout:** return deterministic fallback (rules engine output already has schedule + directive).
- **LLM returns malformed envelope:** retry once with explicit format reminder, then fallback.
- **Validator regex bug:** unit-tested heavily. Banned-phrase list is a constant, easy to audit.

## Testing Strategy

**Unit tests (`tests/test_coach_rules.py`):**
- `compute_coach_rules` for 20+ scenarios: workout pending, workout in progress, workout complete, rest day, fasting active/inactive, weekend long fast, refusal triggers (skip, renegotiate, "should I"), edge times (just before workout, just after), Sunday long run state.

**Unit tests (`tests/test_coach_validator.py`):**
- Byte-equality check rejects altered pre-filled sections
- Banned-phrase scan catches each entry
- Question-mark scan rejects motivation with "?"
- Refusal contract: missing when required → fail; present without directive verb → fail; banned phrase in refusal → fail
- Happy path: valid response passes

**Integration tests (`tests/test_coach_end_to_end.py`):**
- Mock LLM returning known responses → assert rendered output matches expectation
- Mock LLM returning bad response → assert validator triggers retry → assert second call uses feedback → assert fallback on second failure
- Real fixtures: load known user state, snapshot the assembled prompt, assert structure

**Audit-driven regression tests:**
- "15.6 hour fast hallucination" — assert prompt contains structured fasting field for every agent
- "What time are you training tomorrow" — assert prompt contains workout_tomorrow_scheduled_at field
- "References runs that don't exist" — assert empty runs section shows sentinel, not omission

## Migration / Rollout — Big Bang

Per Q6: ship as a single coordinated PR. No feature flag.

**Order of work (single branch):**
1. `coach_rules.py` + dataclasses + unit tests (most tests-per-LOC, builds confidence first)
2. `coach_validator.py` + banned-phrase list + unit tests
3. `_build_event_timeline` replaces `_build_chat_history`
4. Section builders updated to emit sentinels
5. CORE_PROMPT + PROTOCOL_MAP rewritten
6. Prompt assembler updated to inject pre-filled sections
7. Renderer strips tags
8. End-to-end integration tests
9. Manual smoke against Erik's actual coach context (run before merge)

**Cutover:** single deploy. Old `_build_chat_history` and old prompts deleted in same PR. No coexistence.

**Rollback plan:** revert the merge commit. Coach goes back to previous (broken) state. Acceptable risk because the new system is comprehensively tested and the old system is already failing in production.

## Out of Scope (v1)

- **Citation enforcement** — CORE_PROMPT requires citations; validator doesn't enforce. Too noisy. Logged for v2.
- **Auto-summarization of older events** — event timeline is hard-windowed at 7 days. Beyond that, drop. No summary layer yet.
- **Adaptive temperature per agent** — uniform 0.6 in v1.
- **Validator learning loop** — banned-phrase list is hand-curated; no auto-add from observed slips.
- **Coach memory pruning UI** — memories age out by date; no user-facing "this is stale" flag.

## Open Questions for Plan Phase

1. Where in the request lifecycle does the rules engine run? (Likely: in the existing `chat_with_coach` endpoint, before `assemble_prompt`.)
2. Does the rules engine need its own caching layer, or is it fast enough to run per-request?
3. Specific regex patterns for refusal-trigger detection — needs a small corpus from Erik's chat history to tune.
4. Exact `<motivation>` length cap — 1-3 sentences feels right, but is there a hard token cap?
