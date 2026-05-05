# Multi-Agent Coach Architecture — Design

**Date:** 2026-05-04
**Status:** Design approved across all sections, ready for implementation plan
**Author:** Erik Johnson + Claude (brainstorming session)

---

## Problem

The current coach is a single LLM call with a ~3500-token mode-specific prompt. It tries to be everything: nutritionist, strength coach, running coach, sports-medicine doctor, behavioral therapist. Symptoms of the "monolithic generalist":

- Generic responses on domain-specific questions ("should I PR Friday after a 40-hr fast?" gets a vague answer instead of a real reasoned call).
- Lost expertise — can't lean on Pfitzinger / Daniels for running, Lyle McDonald for nutrition, RTS / Nuckols for strength because the prompt has to fit all three at once.
- Conflict resolution happens implicitly with no auditable priority, so the same question can yield different answers depending on which domain the model latches onto.
- The audit harness ([2026-05-01-coach-audit-design.md](2026-05-01-coach-audit-design.md)) catches some of this — false-positive flags on accessory hallucination, "tools down" disclaimer reflex on causal questions, etc. — but the deeper issue is that one prompt can't carry the depth of four specialists.

## Goal

Replace the single-coach architecture (for chat-style triggers) with a **Doctor + 3 specialist sub-agents** orchestration. The Doctor is the user-facing chat. The Doctor consults specialists as tools when an athlete question warrants domain expertise; resolves conflicts by goal-aware priority; synthesizes a single-voice response.

## Non-Goals

- Replace ALL 11 trigger-mode agents. Only chat-style modes (conversation, weekly_planning, chat_opened, weekly_review) become multi-agent. Time-based / event-triggered modes (morning_checkin, run_complete, crisis, etc.) stay single-prompt — they're already focused.
- Build a "show 4 separate chats" UI. There is one chat. The 4 agents are behind it.
- Re-do the audit harness. Extend it to cover the new architecture — don't rewrite.
- Fix the misleading file name `coach_agents.py` (those are trigger-mode prompt configs, not agents). Note as future cleanup; not in scope here.

## Approved Architecture (from Q1-Q5 + cost-tier conversation)

| Decision | Choice |
|---|---|
| Q1 — When are specialists invoked? | **Doctor decides 0-3 consults per message** (revised from "always 3" after cost review) |
| Q2 — What context do specialists see? | **Doctor-curated brief** — Doctor parses the question, sends focused asks to each specialist with relevant data slice |
| Q3 — Conflict resolution? | **Goal-aware adaptive priority** — sports-medicine red flags always win, then `TrainingGoal.goal_type` dictates which specialist wins on direct conflict |
| Q4 — User-facing UX? | **Synthesis by default, specialist views on demand** — single Doctor voice unless athlete explicitly asks for the underlying views |
| Q5 — Which trigger modes go multi-agent? | **Chat-style only** — conversation, weekly_planning, chat_opened, weekly_review (revised from "all 11" after cost review) |
| Cost tier | **Tier 2** — Opus 4.7 Doctor + Sonnet 4.6 specialists, ~$60-150/month for heavy use |
| Runtime + build-time? | **Both** — `.claude/agents/*.md` is canonical persona source; runtime Python loads from same files |

---

## 1. Architecture Overview

```
                     ┌─────────────────────────┐
   Athlete msg ────► │   DOCTOR (overseer)     │
                     │   - parses question     │
                     │   - decides 0-3 consults│
                     │   - curates briefs      │
                     │   - resolves conflicts  │
                     │   - synthesizes reply   │
                     └────┬──────┬──────┬──────┘
                          │      │      │       (parallel via asyncio.gather)
              ┌───────────┘      │      └────────────┐
              ▼                  ▼                   ▼
      ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
      │ NUTRITIONIST │   │   STRENGTH   │   │   RUNNING    │
      │  (Lyle/Helms)│   │ (RTS/Nuckols)│   │ (Pfitz/Daniels)│
      └──────────────┘   └──────────────┘   └──────────────┘
              │                  │                   │
              └────────┬─────────┴────────┬──────────┘
                       ▼                  ▼
                  Returns recommendation text
                       │
                       ▼
              Doctor synthesizes → Athlete sees
```

**Per-message flow** (when a chat-style trigger fires):

1. **Doctor receives** the message + chat history + full `athlete_data` block.
2. **Doctor parses** the question, decides which 0-3 specialists to consult, writes a focused brief for each (200-500 tokens covering domain-relevant context + the specific ask).
3. **Specialists run in parallel** via `asyncio.gather()`. Each specialist gets:
   - Its own system prompt (loaded from `.claude/agents/<specialist>.md`)
   - The Doctor's brief
   - Its `athlete_data` slice (per `requires` list — see Section 4)
   - Its tool subset (see Section 2)
4. **Specialists return** tight recommendation text (2-4 sentences, data-cited, no fluff).
5. **Doctor synthesizes** — applies goal-aware priority on conflict, generates single-voice reply. Specialist returns sit in the conversation history as `tool_result` blocks; available for on-demand surfacing.
6. **Athlete sees** the synthesis. If they ask "what did each say?" Doctor surfaces the underlying returns from the prior turn.

**LLM operations per message:** 1 Doctor parse + 0-3 parallel specialist calls + 1 Doctor synthesis = **2-5 LLM calls** depending on how many specialists Doctor invokes. Average is closer to 3.

**Latency budget:** 3-7 seconds wall-clock. UI shows static "Consulting specialists..." indicator during the parse + parallel-consult phase, then streams the synthesis.

---

## 2. Specialist Roles + System Prompt Template

Each specialist gets a focused system prompt (~800-1000 tokens), anchored to canonical sources. Specialists understand they are being **consulted by the Doctor, not chatting with the athlete** — output is a tight recommendation, not conversation.

| Specialist | Anchors | Domain | Tools |
|---|---|---|---|
| **Nutritionist** | Lyle McDonald, Eric Helms, Layne Norton | Macros, deficit math, refeeds, glycogen, fasting protocols, electrolytes, supplement timing | `get_cut_status`, `get_meal_log_today`, `get_meal_plan_week`, `get_body_weight_history`, `get_food_selections`, `compute_deficit` |
| **Strength Coach** | Mike Tuchscherer (RTS), Greg Nuckols, Eric Helms | RPE-based autoregulation, peaking, lift swaps, progression-in-deficit, recovery between sessions | `get_workout`, `get_recent_sets`, `get_e1rm`, `get_today_sets`, `get_session_analysis` |
| **Running Coach** | Pete Pfitzinger, Jack Daniels, Steve Magness, Hadd (50k specialty) | Zone training, ultra periodization, fasted-run feasibility, HR-pace integration, deficit-aware running | `get_run_plan`, `get_recent_runs`, `get_garmin_recovery`, `get_today_status` |
| **Doctor (overseer)** | Andy Galpin, Stuart McGill, Layne Norton | Cross-domain integration, load management, recovery, when-to-push-vs-back-off | All of the above + `consult_nutritionist`, `consult_strength`, `consult_running` |

**Specialist system prompt template** (each filled with their domain anchors):

```
You are the [SPECIALIST_NAME], part of a 4-coach system. The Doctor (overseer)
is consulting you about an athlete question. You are NOT chatting with the
athlete directly — you're returning a tight recommendation to the Doctor.

Your domain expertise is anchored in: [CANONICAL_SOURCES].
Your scope: [DOMAIN_BOUNDARIES].

Priority pyramid (apply in order):
  1. Sports-medicine concerns (injury risk, HRV crashed, sleep <5h, RPE>9)
  2. The athlete's stated goal: {goal_type} (e.g., cut → caloric deficit wins)
  3. Program adherence (the prescribed plan)
  4. Athlete preference

You will receive:
  - The Doctor's brief (the question, focused on your domain)
  - Targeted athlete data slice (only what's relevant to your domain)
  - Tool access to pull additional data if needed

Output format:
  - 2-4 sentences max
  - Cite numbers from the data; never invent
  - Lead with the call. Then the why.
  - Format: "Recommendation: [call]. Reasoning: [data-anchored why].
    Caveat: [risk to flag, if any]."
  - If you need more info that's not in your slice, call your tools — do not
    punt back to the Doctor.

NO sycophancy. NO conversational fluff. NO "I hope this helps." You're a
specialist returning a clinical consult note.
```

**Worked example — Doctor briefs Nutritionist for *"can I PR Friday after a Wed-Thu 40-hour fast?"*:**

```
Brief: Athlete plans a 40-hr fast Wed 6pm → Fri 10am. PR attempt scheduled
Friday on Lower POWER (Front Squat 4×3 max). Athlete is week 6 of 12-wk
cut, current 207 lb, target 185 by week 12. Running aggressive 50% TDEE
deficit. Question: nutritional feasibility of the PR after this fast?

Athlete_data slice: cut_status (pace -3.87 lb/wk), body_weight history,
last 5 days meal_log, fasting_protocol="16_8" baseline.

[Nutritionist returns]: "Recommendation: refeed 30-50g carbs Fri 10am
break-fast (sweet potato + protein), then PR attempt at noon. Reasoning:
40-hr fast empties muscle glycogen; max neural drive on a fully depleted
substrate is biomechanically unsafe and will undercut the lift. Caveat: if
the athlete has done this protocol before with success, defer to their
log; novel attempts on Friday are an N=1 with high-risk asymmetric downside."
```

---

## 3. Doctor's Orchestration Logic

Three phases per message.

### Phase 1 — Parse & Brief (single Doctor LLM turn)

Doctor's system prompt instructs:
> Every athlete message: parse the question into 0-3 specialist briefs.
> For each specialist consulted, write a focused brief that contains:
> (a) the part of the question relevant to that domain
> (b) any cross-cutting context (other domains' constraints)
> (c) what specifically you need them to weigh in on
>
> Decide carefully — most messages don't need all 3 specialists. "I'm tired
> today" probably needs 0 consults. "What's my next bench target?" needs
> 1 (Strength). "Should I PR Friday after a fast?" needs all 3.

Doctor's response: a single assistant message with 0-3 parallel `tool_use` blocks — `consult_nutritionist(brief=...)`, `consult_strength(brief=...)`, `consult_running(brief=...)`. Anthropic's tool-use API supports parallel calls in one turn natively.

### Phase 2 — Specialists Run in Parallel

Each `consult_*` function:
1. Loads specialist's system prompt from `.claude/agents/<specialist>.md`.
2. Pulls the specialist's `athlete_data` slice (per `requires` list).
3. Calls Anthropic with the specialist's tools enabled.
4. Specialist may make 0-3 of its own tool calls before returning.
5. Returns recommendation text to Doctor.

All consult calls dispatched concurrently via `asyncio.gather()` so wall-clock latency is `max(specialist_a, specialist_b, specialist_c)`, not the sum.

### Phase 3 — Synthesize & Resolve (final Doctor LLM turn)

Doctor receives all consult returns as `tool_result` blocks. Continuation prompt:
> You now have N specialist views (where N = 0-3). Apply goal-aware priority:
>   1. Sports-medicine concerns (injury, HRV<X, sleep<5h, RPE>9)
>   2. The athlete's `TrainingGoal.goal_type` (cut → cut goal wins;
>      marathon → running wins; bulk → strength wins)
>   3. Program adherence
>   4. Preference
>
> If they agree: synthesize the unified call.
> If they disagree: identify the conflict, apply priority, name the call,
> name what gets traded off.
> Output is ONE message in your voice. Do NOT enumerate specialist names
> ("Nutritionist says...") unless the athlete explicitly asks for the
> underlying views.

**On-demand specialist surfacing:**
The full consult `tool_use` blocks + returns sit in the conversation history. If the athlete's next message asks *"what did each say?"* or *"show me the disagreement"* or *"why didn't you call X"*, the Doctor naturally has all returns available in context and can quote them directly. No separate caching layer needed.

**Mandatory consult enforcement:** Soft enforcement via system prompt (Doctor's prompt instructs it to consult when the question warrants). Hard enforcement (orchestration-layer check) is a future hardening pass, not v1.

**One implementation note:** Anthropic's tool-use API uses parallel tool calls if the model decides to make them in a single response, but doesn't guarantee parallelism. To get true wall-clock parallelism, the orchestration layer (`coach_multi_agent.py`) detects a multi-tool-use response and dispatches with `asyncio.gather()`. The existing `_run_loop` in `coach_with_tools.py` runs them sequentially today — that's a real change (~30 lines).

---

## 4. Athlete_Data Partitioning

Each specialist's `requires` list maps to existing `coach_assembler.py` section builders. Doctor sees everything; specialists see only their domain.

| Section | Doctor | Nutritionist | Strength | Running |
|---|---|---|---|---|
| `base` (date/week/phase) | ✓ | ✓ | ✓ | ✓ |
| `chat_history` | ✓ | — | — | — |
| `goal` (TrainingGoal) | ✓ | ✓ | ✓ | ✓ |
| `cut_status` (pace, deficit) | ✓ | ✓ | — | — |
| `bodyweight` history | ✓ | ✓ | — | — |
| `meals_today` / `weekly_meals` | ✓ | ✓ | — | — |
| `food_safety` / `food_selections` | ✓ | ✓ | — | — |
| `fasting` state | ✓ | ✓ | ✓ | ✓ |
| `workout_today` / `workout_tomorrow` | ✓ | — | ✓ | ✓ |
| `today_sets` (logged sets today) | ✓ | — | ✓ | — |
| `exercise_history` (SetLog by lift) | ✓ | — | ✓ | — |
| `exercise_analysis` | ✓ | — | ✓ | — |
| `equipment` | ✓ | — | ✓ | — |
| `session_analysis` (last session) | ✓ | — | ✓ | — |
| `runs` (RunLog history) | ✓ | — | — | ✓ |
| `garmin` (HR/sleep/HRV) | ✓ | — | — | ✓ |
| `today_status` (DONE/PENDING) | ✓ | ✓ | ✓ | ✓ |
| `coach_memories` | ✓ | — | — | — |
| `user_rules` | ✓ | — | — | — |

**Key choices:**
- **`chat_history` is Doctor-only.** Specialists get framing via Doctor's brief. Reduces specialist prompt size by ~50% and prevents specialists from drifting into conversational mode.
- **`fasting` state is shared.** All three specialists need to know if the athlete is mid-fast.
- **`today_status` is shared.** All three need to know if the workout/run is already DONE for today.
- **`coach_memories` and `user_rules` are Doctor-only.** Specialists shouldn't apply personalized coaching exceptions — that's Doctor's role.
- **`food_safety` is Nutritionist + Doctor.** Strength/Running don't prescribe food, but Doctor needs it to validate any nutrition recommendation that surfaces in the synthesis.

---

## 5. Conflict Resolution Rules

The Doctor's synthesis prompt encodes priority. Earlier layers override later ones.

```
LAYER 1 — Sports-medicine red flags (ALWAYS top, regardless of goal)
  - HRV >10% below 30-day baseline
  - Sleep <5 hours last night
  - RPE ≥9 on the previous session
  - Injury report from the athlete (acute pain, sharp/sudden)
  - Cumulative training stress flagged by Garmin

  If ANY fire, Doctor's response prioritizes recovery / pulling back,
  regardless of what specialists prescribed for performance.

LAYER 2 — Goal-aware priority (TrainingGoal.goal_type)
  goal_type → which specialist wins on direct conflict:
    "cut"          → Nutritionist (deficit is the program; everything serves it)
    "bulk"         → Strength      (calorie surplus + heavy work)
    "recomp"       → Strength      (slight lean — protein + lifts)
    "marathon"     → Running       (mileage + recovery dictate everything)
    "ultra"        → Running       (long-run is the program)
    "general_health" → Doctor's free judgment

LAYER 3 — Program adherence
  When no conflict and no red flag, defer to the prescribed program.

LAYER 4 — Athlete preference (coach_memories, user_rules)
  Granted exceptions, revealed preferences. Lowest priority — never
  overrides goal or sports-medicine, but tie-breaks otherwise.
```

**Worked example — Erik's case, *"Can I PR Friday after a Wed-Thu 40-hour fast?"*:**

- **Nutritionist (cut focus):** Refeed 30-50g carbs Fri 10am or skip the PR. Empty muscle glycogen + max neural drive = unsafe and undercut.
- **Strength:** Doable but compromised. Top-set RPE will be 9+. Better to hold 90% on a 4×3 single, not a true PR.
- **Running:** Sunday long run is the higher-priority session this week. Friday PR at RPE 9 risks Sunday's session.

Doctor synthesis (cut goal → Nutritionist call wins; Running concern surfaces as caveat):
*"No PR Friday. Hit 4×3 at 90% — that's still progressive overload, doesn't burn Sunday's long run, and respects the fast. Refeed 30g carbs Fri 10am before the lift either way. Real PR attempt comes after a refeed week, not on the back of a 40-hour fast."*

---

## 6. UX Surface

**Default response format:**
Single message in Doctor's voice. No specialist labels. Same tone the current coach has — Lombardi/Saban, terse, data-anchored, no fluff. Lead with the call, brief reasoning, name caveats.

**On-demand specialist surfacing:**
Athlete triggers it explicitly (*"what did each say?"*, *"show me the disagreement"*, *"why didn't you call X"*). Doctor detects these phrases and surfaces the underlying specialist returns from the prior turn.

**Latency budget:**
```
Phase 1 (Doctor parse + tool_use blocks):       ~1-2s
Phase 2 (specialists in parallel):              ~2-3s wall-clock
Phase 3 (Doctor synthesis):                     ~2-3s (streamed)
                                                ─────
                                                ~5-8s total
```

**Loading state:**
During Phases 1-2 (~3-5s of thinking, no text streaming yet): UI shows static *"Consulting specialists..."* indicator. Phase 3 streams normally — synthesis appears word-by-word as the Doctor generates it.

**Streaming continuity:**
Existing `coach_chat_stream` in `coach_with_tools.py` already handles tool-loop-then-stream. Extension: the loop now contains Doctor's parse + tool calls + synthesis, with the final synthesis streaming through to the client. No change to the SSE consumer in `static/app.js`.

---

## 7. Cost Model + Model Selection (Tier 2)

**Per-message token + cost estimate (Tier 2):**

| Phase | Model | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| Doctor parse | Opus 4.7 | ~8K | ~1K | $0.20 |
| Nutritionist (avg ~50% invoked) | Sonnet 4.6 | ~4K | ~500 | $0.020 (× 0.5) |
| Strength (avg ~50% invoked) | Sonnet 4.6 | ~4K | ~500 | $0.020 (× 0.5) |
| Running (avg ~50% invoked) | Sonnet 4.6 | ~4K | ~500 | $0.020 (× 0.5) |
| Doctor synthesis | Opus 4.7 | ~12K | ~1.5K | $0.29 |
| **Per message (avg)** | | | | **~$0.55** |

For heavy use (~10-15 chat messages/day across the 4 multi-agent trigger modes):
- Daily: ~$5-8/day
- Monthly: **~$150-250/month**

**Model strategy:**
- **Doctor: Opus 4.7** — heavy reasoning (parsing + conflict resolution + synthesis).
- **Specialists: Sonnet 4.6** — focused tight returns.
- **Knobs via env vars:**
  - `MULTIAGENT_DOCTOR_MODEL=claude-opus-4-7`
  - `MULTIAGENT_SPECIALIST_MODEL=claude-sonnet-4-6`
  - `MULTIAGENT_ENABLE_CACHE=1`
  - `MULTIAGENT_AGENTS_MULTI=conversation,weekly_planning,chat_opened,weekly_review`

**Optimizations baked in:**
1. **Anthropic prompt caching (5-min TTL).** Mark system prompt + `athlete_data` as `cache_control: ephemeral` on every call. Sequential messages within 5 minutes hit cached input at 1/10th cost. Estimated ~40% input savings.
2. **Specialist returns share with synthesis.** The Doctor's synthesis call sees `athlete_data` + 3 specialist returns. The `athlete_data` is the same as Phase 1 — caching it across Phase 1 → Phase 3 cuts synthesis input cost roughly in half.
3. **Doctor decides 0-3 consults.** Most messages don't trigger all 3 specialists. Average ~1.5 consults/message saves ~50% on specialist cost vs always-3.

---

## 8. Existing AGENTS Map Migration

**Trigger modes (in `coach_agents.py`) — UNCHANGED.** Those are 11 prompt configs for different trigger events. Multi-agent is a different layer.

```
Multi-agent (Doctor + specialists pattern):
  conversation       — every chat message routes through Doctor
  weekly_planning    — Doctor + 3 specialists weigh in on each day's plan
  chat_opened        — opening greeting may need cross-domain context
  weekly_review      — review needs all 3 specialist perspectives

Single-prompt (existing focused agents — unchanged):
  morning_checkin    — fast morning data dump, no specialists needed
  morning_briefing   — terse "here's today's program" — no consult overhead
  workout_feedback   — post-workout, focused on the lift session
  run_complete       — post-run analysis with the run data
  meals_complete     — meal logging response, narrow scope
  end_of_day         — quick recap, narrow scope
  crisis             — must be fast and direct, never delegated
```

**File layout:**
```
.claude/agents/                        # Build-time agents (Claude Code Task tool)
  doctor.md                              ← canonical persona + system prompt + tools
  nutritionist.md                        ←
  strength-coach.md                      ←
  running-coach.md                       ←

coach_specialists/                      # Runtime Python (Flask app)
  __init__.py
  loader.py                              ← parses .claude/agents/*.md frontmatter
  doctor.py                              ← runtime call function (uses loader)
  nutritionist.py
  strength.py
  running.py

coach_multi_agent.py                    # Orchestrator: Doctor → 0-3 parallel
                                          specialists → Doctor synthesis

(unchanged) coach_agents.py             # 11 trigger-mode prompt configs
                                          (mis-named historically; leave for now)
(unchanged) coach_with_tools.py         # Existing single-prompt path used by
                                          the 7 non-multi-agent modes
```

The same `.claude/agents/<specialist>.md` file feeds both runtime and build-time:
- **Runtime:** `coach_specialists.loader.load("nutritionist")` reads the file, returns parsed prompt + tools list.
- **Build-time:** Claude Code's `Task(subagent_type="nutritionist", ...)` discovers the file by name.

One source of truth. No drift between dev-time and runtime personas.

**Migration path (no big-bang):**

1. **Step 1: Add the 4 `.claude/agents/*.md` files** (canonical personas).
2. **Step 2: Add `coach_specialists/`** (loader + 4 runtime modules). Wire each `consult_*` tool to call its module.
3. **Step 3: Add the 3 `consult_*` tools** to `coach_tools.py`.
4. **Step 4: Wire the multi-agent dispatcher** in `coach_multi_agent.py`. Detect when an incoming agent_name is one of the 4 multi-agent trigger modes; route to Doctor instead of the existing single-prompt path. Single-prompt path stays for the other 7 trigger modes.
5. **Step 5: Feature flag** behind `MULTIAGENT_ENABLED=1` env var (and/or `?multiagent=1` query param). Off by default for safety. Erik can toggle on per-message during testing.
6. **Step 6: Audit harness** picks up the new agents (Section 9). Validate quality vs single-coach baseline before flipping the default.
7. **Step 7: Default flip.** When the audit shows multi-agent matches or beats single-coach across all categories, flip the default. Single-prompt path stays available for fallback.

**Rollback:** Each step independently reversible. Worst case, drop `MULTIAGENT_ENABLED`; everyone reverts to current single-coach.

---

## 9. Testing / Audit Harness Extension

The audit harness from `tests/coach_audit/` extends to cover the new architecture.

### 1. Per-specialist test prompts
Add `target_specialist` field to `PromptCase`:
```python
PromptCase(
    id="nut_001", category="nutrition_macros",
    user_message="Should I eat carbs today?",
    target_specialist="nutritionist",  # NEW field
    user_fixture="phase_2_mid_program",
    expected_behavior=["cut", "5g", "deficit"],
    must_not=["carb cycling", "300g carbs"],
    ...
)
```
Harness can target a specialist directly (bypass Doctor; hit `coach_specialists.nutritionist.consult(brief)` with a synthetic brief). Sharp domain-specific signal without orchestration noise.

### 2. Doctor synthesis tests
New category `doctor_synthesis` exercises the FULL multi-agent flow and validates:
- Doctor called the right specialists (capture the consult calls)
- Conflict resolution applied goal-aware priority correctly
- Synthesis matched expected behavior (heuristic + judge)

### 3. Specialist disagreement scenarios
Deliberate-conflict prompts:
```python
PromptCase(
    id="conflict_001", category="doctor_synthesis",
    user_message="I want to PR Friday after a 40-hr fast Wed-Thu",
    user_fixture="phase_2_mid_program",
    target_specialist="doctor",
    expected_behavior=["skip the PR", "no PR Friday", "RPE", "Sunday"],
    must_not=["go for it", "send it"],
    focus_dimensions=["accuracy", "no_hallucination", "follows_must_not"],
)
```

### 4. Audit categories grow
From 12 to 16 categories:
- New: `nutrition_macros`, `nutrition_fasting`, `running_pace_zones`, `doctor_synthesis`

### 5. Cost gate
- 30 per-specialist prompts × ~$0.02 = $0.60 (single Sonnet call each)
- 10 doctor_synthesis prompts × ~$1.80 = $18 (full multi-agent flow)
- Total ~$19/run — comparable to current ~$20/run.

### 6. Regression guarantee
When multi-agent ships, existing 38-prompt audit suite still runs against single-coach path (the 7 trigger modes that stay single-prompt). New multi-agent suite runs against multi-agent path. Both must pass before default flip in Step 7.

---

## Open Questions / Risks

- **Specialist prompt depth.** Anchoring to Pfitzinger / Lyle / Tuchscherer is a goal, but the actual ~1000-token system prompts need to capture their methodology faithfully. First implementation pass may have generic content; iterate via audit harness signal.
- **Mandatory consult enforcement.** v1 uses soft enforcement (system prompt instructs Doctor to consult). If the model under-consults on questions that warrant specialists, hard enforcement (orchestration-layer check) is a future hardening pass.
- **Latency on slow days.** 5-8s wall-clock is real. If Anthropic API is slow or we hit rate limits, latency could climb to 10-15s. Mitigation: timeout per specialist call (e.g., 15s) + Doctor synthesizes from whichever specialists returned.
- **Cost spike from a runaway day.** A heavy chat day ($20+) could surprise. Add a daily cost cap that falls back to single-prompt mode for any messages beyond a threshold (e.g., $30/day).
- **Audit harness false-positives.** The judge sees Doctor's synthesis but not specialist returns. Some "hallucination" flags may actually be Doctor accurately reporting a specialist view that's outside the judge's ground-truth. Mitigation: Doctor synthesis tests pass specialist returns to the judge as additional context.

## Success Criteria

- All 4 multi-agent trigger modes produce coherent single-voice responses.
- On contested calls (e.g., PR-after-fast), Doctor explicitly applies goal-aware priority and the response cites the dominant priority.
- On-demand specialist surfacing works — athlete asking "what did each say?" gets the underlying views from the prior turn.
- Audit harness pass rate ≥ current single-coach baseline (~80%) on pre-existing categories.
- New specialist-targeted categories reach ≥ 90% pass rate after first iteration.
- Average per-message cost stays ≤ $0.60 (per Tier 2 estimate).

## Out of Scope (Future Work)

- Renaming `coach_agents.py` → `coach_trigger_modes.py` for clarity.
- Adding more specialists (Behavioral / Psych Coach for psych_intake_resume; Sports PT for injury management). v1 is 3 specialists + Doctor.
- Speech-to-Doctor pipeline (voice chat with the multi-agent system).
- Multi-tenant cost tracking per athlete.
- Hard enforcement of consult coverage (orchestration-layer checks vs prompt-only).
- Migrating the other 7 trigger modes to multi-agent if the data shows they'd benefit.
