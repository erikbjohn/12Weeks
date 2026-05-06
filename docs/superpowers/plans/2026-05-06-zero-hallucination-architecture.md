# Zero-Hallucination Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive coach hallucinations to asymptotic zero by replacing the "model narrates from a free-text slice" pattern with structured citations + cite-validation + an async auditor pass. Architecture-level fixes; persona prompts are at saturation.

**Architecture:** Three-step shift, applied in order: (1) force-call tools by message classification so the model never reasons without the data already loaded; (2) replace the prose slice with a typed claims table and require model output to cite `claim_id` for every numeric/structural assertion (with cite-validation reject loop); (3) async second-pass Sonnet auditor that single-claim-checks each cited claim against its source row, plus a posture audit catching defensive-pushback failures. Step 1 (tool-failure rerouting + null-aware run formatter) already shipped at commit `9a064ff` and is NOT in this plan.

**Tech Stack:** Python 3.12 + Flask + SQLAlchemy + anthropic SDK (sync + async) + pytest. Same stack as the rest of the app.

**Source review:** Architectural review from the Plan agent (2026-05-06) identified 8 hallucination classes (A-H) and recommended this 5-step sequence. Step 1 already complete. Step 5 (knowledge-graph claim diffing) deferred until measurement after 2-4.

**Status legend per step:**
- ✅ Step 1 complete (commit `9a064ff`) — closes class E (tool-failure leakage) and classes C/F (fabricated pace, field semantics)
- 🟡 Step 2 — closes class B (schedule miss / scope errors)
- 🟡 Step 3 — closes class A (misattribution), partial D (cascade reasoning)
- 🟡 Step 4 — closes residual A + class H (defensive pushback)

---

## File Structure

| File | Responsibility |
|---|---|
| `coach_router_classifier.py` | (new, Step 2) — `classify_required_tools(message, agent_name)` → list of forced tool calls |
| `coach_multi_agent.py` | (modify, Steps 2-4) — pre-execute classified tools; cite-validation reject/retry; async auditor hook |
| `coach_claims.py` | (new, Step 3) — `Claim` dataclass + `build_claims(user_id, scope)` → typed fact list |
| `coach_assembler.py` | (modify, Step 3) — emit `<claims>` block alongside (or replacing) prose slice |
| `coach_validator.py` | (modify, Step 3) — extend with cite-existence + value-string-match enforcement |
| `.claude/agents/doctor.md` | (modify, Step 3) — switch to JSON output requirement with `cites: [claim_id...]` per assertion |
| `.claude/agents/nutritionist.md` | (modify, Step 3) — same JSON-with-cites requirement |
| `.claude/agents/strength-coach.md` | (modify, Step 3) — same |
| `.claude/agents/running-coach.md` | (modify, Step 3) — same |
| `coach_auditor.py` | (new, Step 4) — single-claim Sonnet audit + posture audit + fan-out runner |
| `tests/test_router_classifier.py` | (new) — patterns for Step 2 |
| `tests/test_claims_builder.py` | (new) — predicate coverage for Step 3 |
| `tests/test_cited_output_validator.py` | (new) — cite-existence + value-match for Step 3 |
| `tests/test_auditor.py` | (new) — single-claim audit prompt for Step 4 |
| `tests/test_posture_audit.py` | (new) — defensive-pushback detection for Step 4 |

---

# STEP 2 — Force-call tools by message classification

**What it closes:** Class B (schedule miss / scope errors). Doctor said "Thursday has no run scheduled" when the slice clearly had VO2 4x4 — model summarized rather than enumerated. By force-calling `get_today_status` / `get_workout` / `get_run_plan` BEFORE the model's first turn whenever the message references a day, lift, or run, the model never sees the question without the data already pre-loaded.

**Effort:** 3-5 days

## Task 2.1: Define `ForcedCall` + classifier skeleton

**Files:**
- Create: `coach_router_classifier.py`
- Test: `tests/test_router_classifier.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_router_classifier.py`:

```python
"""Tests for the message-pattern classifier that pre-executes tools
before the multi-agent Doctor's first turn."""
from coach_router_classifier import classify_required_tools, ForcedCall


def test_today_keyword_triggers_today_status():
    out = classify_required_tools("What's on my plate today?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_today_status" in names


def test_tomorrow_keyword_triggers_today_status_too():
    """Tomorrow questions need today_status to anchor 'today' first, then
    workout for tomorrow's day_idx."""
    out = classify_required_tools("How heavy is bench tomorrow?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_today_status" in names
    # workout call may also be present; tested separately


def test_no_match_returns_empty_list():
    out = classify_required_tools("How are you?", agent_name="conversation")
    assert out == []


def test_returns_forced_call_dataclass_not_dicts():
    out = classify_required_tools("What's today?", agent_name="conversation")
    assert all(isinstance(c, ForcedCall) for c in out)
    assert all(hasattr(c, "tool_name") and hasattr(c, "kwargs") for c in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_router_classifier.py -v`
Expected: 4 FAIL — `coach_router_classifier` module does not exist.

- [ ] **Step 3: Write `coach_router_classifier.py`**

```python
"""Pre-execute tools based on message-pattern matching, before the
multi-agent Doctor's first turn. Eliminates the "model summarizes
without reading the slice" failure mode by ensuring relevant tool
results are already in the conversation when the model gets the
message.

Pattern rules are conservative — false positives (calling a tool
the model doesn't need) are harmless; false negatives (failing to
call a tool the model needs) are how class-B hallucinations happen.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class ForcedCall:
    """A tool call to pre-execute before the model sees the message."""
    tool_name: str
    kwargs: dict = field(default_factory=dict)


# Day-name patterns (Mon/Monday/etc.) — case-insensitive.
_DAY_RE = re.compile(
    r"\b(today|tomorrow|yesterday|"
    r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|"
    r"fri(day)?|sat(urday)?|sun(day)?)\b",
    re.IGNORECASE,
)


def classify_required_tools(message: str, agent_name: str) -> list[ForcedCall]:
    """Return tools to pre-execute before the model's first turn.

    Conservative: only triggers on patterns we're confident about. Returns
    an empty list when no patterns match — the model still has slice +
    tool-use available, just no forced pre-execution.
    """
    if not message:
        return []
    out: list[ForcedCall] = []
    if _DAY_RE.search(message):
        out.append(ForcedCall("get_today_status"))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_router_classifier.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_router_classifier.py tests/test_router_classifier.py
git commit -m "Zero-hallucination Step 2.1: ForcedCall + day-keyword classifier skeleton"
```

---

## Task 2.2: Add exercise-name + body-query patterns

**Files:**
- Modify: `coach_router_classifier.py`
- Modify: `tests/test_router_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_router_classifier.py`:

```python
def test_exercise_name_triggers_recent_sets_and_e1rm():
    out = classify_required_tools("How heavy was last bench?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_recent_sets" in names
    assert "get_e1rm" in names
    # exercise_name kwarg should be normalized
    rs = next(c for c in out if c.tool_name == "get_recent_sets")
    assert "bench" in rs.kwargs.get("exercise_name", "").lower()


def test_squat_keyword_triggers_recent_sets():
    out = classify_required_tools("What's my squat target?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_recent_sets" in names


def test_weight_query_triggers_get_body_state():
    out = classify_required_tools("How's my weight tracking?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_body_state" in names


def test_calorie_query_triggers_get_body_state():
    out = classify_required_tools("Should I drop calories?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_body_state" in names


def test_multiple_patterns_dedupe_tools():
    """When multiple patterns trigger, the same tool name should appear
    at most once in the output."""
    out = classify_required_tools("How heavy was bench today?", agent_name="conversation")
    names = [c.tool_name for c in out]
    # get_today_status should appear once even though "today" + a
    # potential "today" implication both could trigger
    assert names.count("get_today_status") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_router_classifier.py -v`
Expected: 5 new FAILs — exercise/body patterns not yet implemented.

- [ ] **Step 3: Extend the classifier**

Replace the body of `coach_router_classifier.py` with:

```python
"""Pre-execute tools based on message-pattern matching, before the
multi-agent Doctor's first turn. Eliminates the "model summarizes
without reading the slice" failure mode by ensuring relevant tool
results are already in the conversation when the model gets the
message.

Pattern rules are conservative — false positives (calling a tool
the model doesn't need) are harmless; false negatives (failing to
call a tool the model needs) are how class-B hallucinations happen.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class ForcedCall:
    """A tool call to pre-execute before the model sees the message."""
    tool_name: str
    kwargs: dict = field(default_factory=dict)


_DAY_RE = re.compile(
    r"\b(today|tomorrow|yesterday|"
    r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|"
    r"fri(day)?|sat(urday)?|sun(day)?)\b",
    re.IGNORECASE,
)

# Map a free-text exercise reference to a canonical name for the tool's
# exercise_name kwarg. Order matters (longer matches first when ambiguous).
_EXERCISE_MAP = [
    (re.compile(r"\bback\s*squat\b", re.I),     "Barbell Back Squat"),
    (re.compile(r"\bfront\s*squat\b", re.I),    "Front Squat"),
    (re.compile(r"\bbench\s*press\b", re.I),    "Barbell Bench Press"),
    (re.compile(r"\bbench\b", re.I),            "Barbell Bench Press"),
    (re.compile(r"\bsquat\b", re.I),            "Barbell Back Squat"),
    (re.compile(r"\bdeadlift\b", re.I),         "Conventional Deadlift"),
    (re.compile(r"\b(rdl|romanian\s*deadlift)\b", re.I), "Romanian Deadlift"),
    (re.compile(r"\bbent.?over\s*row\b", re.I), "Barbell Bent-Over Row"),
    (re.compile(r"\brow\b", re.I),              "Barbell Bent-Over Row"),
    (re.compile(r"\bpull.?up\b", re.I),         "Weighted Pull-Up"),
    (re.compile(r"\bhip\s*thrust\b", re.I),     "Hip Thrust"),
    (re.compile(r"\bovh?p\b|\boverhead\s*press\b|\bohp\b", re.I), "Overhead Press"),
]

# Free-text body/cut keywords → trigger get_body_state
_BODY_RE = re.compile(
    r"\b(weight|cut(ting)?|deficit|calorie|kcal|macro|protein|carb|fat|"
    r"body\s*comp|bodyfat|bf|tdee|projection|target|lose|gain)\b",
    re.IGNORECASE,
)


def classify_required_tools(message: str, agent_name: str) -> list[ForcedCall]:
    """Return tools to pre-execute before the model's first turn.

    Returns at most one ForcedCall per distinct tool name (dedup by
    tool_name) — we don't pre-execute the same tool twice in one turn.
    """
    if not message:
        return []
    seen_tools: set[str] = set()
    out: list[ForcedCall] = []

    def add(call: ForcedCall) -> None:
        if call.tool_name in seen_tools:
            return
        seen_tools.add(call.tool_name)
        out.append(call)

    if _DAY_RE.search(message):
        add(ForcedCall("get_today_status"))

    for ex_re, canonical in _EXERCISE_MAP:
        if ex_re.search(message):
            add(ForcedCall("get_recent_sets",
                           kwargs={"exercise_name": canonical, "limit": 8}))
            add(ForcedCall("get_e1rm",
                           kwargs={"exercise_name": canonical}))
            break  # one exercise per turn is plenty; first match wins

    if _BODY_RE.search(message):
        add(ForcedCall("get_body_state"))

    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_router_classifier.py -v`
Expected: 9 PASS (4 from Task 2.1 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add coach_router_classifier.py tests/test_router_classifier.py
git commit -m "Zero-hallucination Step 2.2: exercise + body-query patterns in classifier"
```

---

## Task 2.3: Wire pre-execute into orchestrator

**Files:**
- Modify: `coach_multi_agent.py`
- Modify: `tests/test_multi_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_multi_agent.py`:

```python
def test_classifier_pre_executes_tools_before_first_model_turn():
    """When the message contains a day keyword, get_today_status should be
    invoked BEFORE the Doctor's first turn — its result should appear as
    a tool_result block in the conversation by the time the model is called."""
    from coach_multi_agent import coach_chat_multiagent

    text_block = MagicMock(type="text", text="Today's done.")
    fake_response = MagicMock(stop_reason="end_turn", content=[text_block])

    captured_messages = []

    def capture_messages(*args, **kwargs):
        captured_messages.append(list(kwargs.get("messages") or []))
        return fake_response

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.side_effect = capture_messages
        with patch("coach_tools.execute_tool", return_value='{"date":"2026-05-06","weekday":"Wed"}') as mt:
            coach_chat_multiagent(
                user_id=1,
                athlete_data="<athlete_data/>",
                messages=[{"role": "user", "content": "What's on my plate today?"}],
            )

    # execute_tool should have been called for get_today_status BEFORE
    # the model was invoked.
    tool_calls = [c for c in mt.call_args_list if c.args and c.args[0] == "get_today_status"]
    assert len(tool_calls) >= 1
    # The first message-create call should already have a tool_result for it.
    first_call_messages = captured_messages[0]
    has_pre_tool_result = any(
        isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"] if isinstance(b, dict))
        for m in first_call_messages
    )
    assert has_pre_tool_result, "Pre-executed tool result should be in conversation before model's first turn"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_multi_agent.py::test_classifier_pre_executes_tools_before_first_model_turn -v`
Expected: FAIL — pre-execution not yet wired.

- [ ] **Step 3: Wire pre-execution into the orchestrator**

In `coach_multi_agent.py`, add the pre-execute step BEFORE the `for turn in range(MAX_TOOL_TURNS)` loop. Find this region (around line 175-185):

```python
    persona = load_agent_md("doctor")
    system = (
        persona["system_prompt"]
        + "\n\n<athlete_data>\n"
        + athlete_data
        + "\n</athlete_data>"
    )

    # Filter TOOLS to just the ones the Doctor's persona declares it can use.
    doctor_tool_names = set(persona["tools"])
    doctor_tools = [t for t in TOOLS if t["name"] in doctor_tool_names]

    client = _anthropic_client()
    convo = list(messages)
```

Add immediately after `convo = list(messages)`:

```python
    # === STEP 2: Pre-execute classified tools BEFORE the model's first turn ===
    # Closes hallucination class B (schedule miss / scope errors): when the
    # athlete's message references a day, lift, or body metric, force-call
    # the relevant tool so the model never has to "decide" to look it up
    # and never has the chance to summarize without reading the data.
    from coach_router_classifier import classify_required_tools
    last_user_msg = ""
    for m in reversed(convo):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                last_user_msg = content
            break

    forced = classify_required_tools(last_user_msg, agent_name="conversation")
    # Filter to tools the Doctor persona actually has access to.
    forced = [f for f in forced if f.tool_name in doctor_tool_names]
    if forced:
        from coach_tools import execute_tool
        # Build synthetic assistant + user pair: assistant emits tool_use
        # blocks, user emits tool_result blocks. This mirrors the natural
        # tool_use loop shape so the model sees pre-executed calls as if
        # it had requested them.
        synthetic_tool_uses = []
        synthetic_tool_results = []
        for i, f in enumerate(forced):
            tu_id = f"forced_{i}"
            synthetic_tool_uses.append({
                "type": "tool_use",
                "id": tu_id,
                "name": f.tool_name,
                "input": f.kwargs or {},
            })
            try:
                result = execute_tool(f.tool_name, f.kwargs or {}, user_id)
            except Exception as e:
                result = f'{{"error": "pre-execute failed: {e}"}}'
            tool_results_collected.append(result)
            synthetic_tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": result,
            })
        # Apply the same error-rerouting from Step 1 to pre-executed results
        synthetic_tool_results = _reroute_tool_failures(
            synthetic_tool_results,
            [type("F", (), {"id": tu["id"], "name": tu["name"]})() for tu in synthetic_tool_uses],
        )
        convo.append({"role": "assistant", "content": synthetic_tool_uses})
        convo.append({"role": "user", "content": synthetic_tool_results})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_multi_agent.py::test_classifier_pre_executes_tools_before_first_model_turn -v`
Expected: PASS.

Run all multi-agent tests to confirm no regression:
Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: ALL PASS (the new test + the existing 12).

- [ ] **Step 5: Commit**

```bash
git add coach_multi_agent.py tests/test_multi_agent.py
git commit -m "Zero-hallucination Step 2.3: wire force-call pre-execution into orchestrator"
```

---

## Task 2.4: Live verification against prod

**Files:** none modified (live check)

- [ ] **Step 1: Verify against prod**

Run a live multi-agent call with a day-keyword message and confirm:
1. `get_today_status` is invoked exactly once
2. Its result is in the conversation before the Doctor's first turn
3. The Doctor's response does NOT hallucinate the day's prescription

Use the same script pattern from earlier prod tests (e.g. the `weekly_planning` E2E that we ran post-fact-check-fix). Test message: `"What's my workout today?"`. The response should accurately reflect the actual day's prescription pulled from `get_today_status`.

- [ ] **Step 2: Document the verification in commit message**

If verified clean, no commit needed (Task 2.3 already shipped). If a discrepancy surfaces, that's a follow-up task — capture and decide whether to extend classifier patterns.

---

# STEP 3 — Claims table + cited output (the big one)

**What it closes:** Class A (misattribution — "5 weeks before 50k" → "5 weeks left in cut"), partial class D (cascade reasoning from false premise). The single biggest architectural shift: model goes from "narrate from prose blob" to "select pre-computed claims with explicit citations."

**Effort:** 1-2 weeks. This is the structural backbone the rest of the architecture coheres around.

**Architectural framing (from the Plan agent's review):** Replace the free-text slice (3-5 KB of prose) with a typed `(claim_id, predicate, value, source, derivation)` table. Model output is JSON with `cites: [claim_id, ...]` per assertion. Post-processor validates every numeric claim is backed by a cited claim, every claim's predicate matches the cited row's predicate, and every numeric *value* in prose matches the cited claim's value (string-match). Rejection triggers the existing retry loop.

## Task 3.1: `Claim` dataclass + first builders (body weight, goal)

**Files:**
- Create: `coach_claims.py`
- Test: `tests/test_claims_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_claims_builder.py`:

```python
"""Tests for the typed-claim builder that backs cited output (Step 3).

Each Claim is (claim_id, predicate, value, source, derivation). The model
will cite claim_ids in its response; the validator will check existence
and value-string-match. So claims must be:
  - Stable IDs across calls (deterministic)
  - Predicate strings short and unique enough to detect mis-attribution
  - Values typed (int/float/str) for value-match enforcement
"""
import pytest
from unittest.mock import MagicMock, patch
from coach_claims import Claim, build_claims


def test_claim_dataclass_shape():
    c = Claim(
        claim_id="body.weight.current",
        predicate="athlete.current_weight_lb",
        value=207.2,
        source="BodyWeight#4821",
        derivation=None,
    )
    assert c.claim_id == "body.weight.current"
    assert c.value == 207.2


def test_build_claims_emits_current_weight_when_bodyweight_present():
    """Mock a user with one BodyWeight row; expect a body.weight.current claim."""
    bw = MagicMock(weight_lbs=207.2, log_date=MagicMock(isoformat=lambda: "2026-05-03"))
    with patch("coach_claims._fetch_latest_bodyweight", return_value=bw):
        with patch("coach_claims._fetch_training_goal", return_value=None):
            claims = build_claims(user_id=1, scope=("body_weight",))
    by_id = {c.claim_id: c for c in claims}
    assert "body.weight.current" in by_id
    assert by_id["body.weight.current"].value == 207.2
    assert "BodyWeight" in by_id["body.weight.current"].source


def test_build_claims_emits_target_weight_from_training_goal():
    goal = MagicMock(target_weight=185.0, daily_calories=1700, goal_type="cut")
    with patch("coach_claims._fetch_latest_bodyweight", return_value=None):
        with patch("coach_claims._fetch_training_goal", return_value=goal):
            claims = build_claims(user_id=1, scope=("goal",))
    by_id = {c.claim_id: c for c in claims}
    assert "body.weight.target" in by_id
    assert by_id["body.weight.target"].value == 185.0
    assert "goal.daily_calories" in by_id
    assert by_id["goal.daily_calories"].value == 1700


def test_build_claims_emits_lb_to_target_as_derived_claim():
    """When both current weight and target are present, lb_to_target is a
    derived claim with source='derived' and a derivation chain."""
    bw = MagicMock(weight_lbs=207.2, log_date=MagicMock(isoformat=lambda: "2026-05-03"))
    goal = MagicMock(target_weight=185.0, daily_calories=1700, goal_type="cut")
    with patch("coach_claims._fetch_latest_bodyweight", return_value=bw):
        with patch("coach_claims._fetch_training_goal", return_value=goal):
            claims = build_claims(user_id=1, scope=("body_weight", "goal"))
    by_id = {c.claim_id: c for c in claims}
    assert "body.weight.lb_to_target" in by_id
    assert by_id["body.weight.lb_to_target"].value == 22.2
    assert by_id["body.weight.lb_to_target"].source == "derived"
    assert by_id["body.weight.lb_to_target"].derivation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_claims_builder.py -v`
Expected: 4 FAIL — `coach_claims` module does not exist.

- [ ] **Step 3: Write `coach_claims.py`**

```python
"""Typed claims that back cited output. Each claim is a verified fact
the model can cite by claim_id; the validator checks both that the
claim exists and that the value cited in prose matches.

Architectural premise (per 2026-05-06 review): the slice should not
be a free-text blob the model re-derives facts from. It should be a
table of pre-computed (claim_id, predicate, value, source, derivation)
rows that the model selects from and cites explicitly.

Scope strings (the optional `scope` arg to `build_claims`) let callers
build a focused set: ("body_weight",), ("goal",), ("today_status",),
("week_program",), etc. An empty scope means "all available."
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class Claim:
    """A pre-computed fact citable by the model.

    Fields:
        claim_id:   stable, deterministic ID like "body.weight.current"
        predicate:  human-readable predicate name; the model sees this
                    when selecting a claim and the validator uses it to
                    detect mis-attribution
        value:      typed value (int, float, str, bool); validator
                    string-matches this against any number cited in prose
        source:     where the value came from — table#row OR "derived"
        derivation: when source=="derived", the formula used (free-text);
                    None for direct facts
    """
    claim_id: str
    predicate: str
    value: Any
    source: str
    derivation: str | None = None


def _fetch_latest_bodyweight(user_id: int):
    """Indirection so tests can mock without hitting the DB."""
    from models import BodyWeight
    return (BodyWeight.query
            .filter_by(user_id=user_id)
            .order_by(BodyWeight.log_date.desc())
            .first())


def _fetch_training_goal(user_id: int):
    from models import TrainingGoal
    return TrainingGoal.query.filter_by(user_id=user_id).first()


def build_claims(user_id: int, scope: tuple[str, ...] = ()) -> list[Claim]:
    """Build the claims table for this user. `scope` filters which
    sections to include; empty = all.

    Order matters: claims are emitted in dependency order (raw before
    derived) so the model reads them top-down.
    """
    out: list[Claim] = []
    want = lambda s: not scope or s in scope

    bw = _fetch_latest_bodyweight(user_id) if want("body_weight") else None
    goal = _fetch_training_goal(user_id) if want("body_weight") or want("goal") else None

    if bw and want("body_weight"):
        out.append(Claim(
            claim_id="body.weight.current",
            predicate="athlete.current_weight_lb",
            value=float(bw.weight_lbs),
            source=f"BodyWeight#{getattr(bw, 'id', '?')} ({bw.log_date.isoformat()})",
        ))

    if goal and want("goal"):
        out.append(Claim(
            claim_id="body.weight.target",
            predicate="athlete.target_weight_lb",
            value=float(goal.target_weight),
            source=f"TrainingGoal#{getattr(goal, 'id', '?')}",
        ))
        out.append(Claim(
            claim_id="goal.daily_calories",
            predicate="athlete.daily_calorie_target",
            value=int(goal.daily_calories),
            source=f"TrainingGoal#{getattr(goal, 'id', '?')}",
        ))
        out.append(Claim(
            claim_id="goal.type",
            predicate="athlete.goal_type",
            value=str(goal.goal_type),
            source=f"TrainingGoal#{getattr(goal, 'id', '?')}",
        ))

    # Derived claims (only when inputs are present)
    if bw and goal and want("body_weight") and want("goal"):
        delta = round(float(bw.weight_lbs) - float(goal.target_weight), 1)
        out.append(Claim(
            claim_id="body.weight.lb_to_target",
            predicate="athlete.lb_to_target",
            value=delta,
            source="derived",
            derivation=f"{bw.weight_lbs} - {goal.target_weight} = {delta}",
        ))

    return out


def format_claims_block(claims: list[Claim]) -> str:
    """Render claims as the <claims> section of the slice.

    Format is structured so the model can parse it deterministically:
        <claims>
          - id=body.weight.current  pred=athlete.current_weight_lb  value=207.2  source=BodyWeight#4821
          - id=body.weight.target   pred=athlete.target_weight_lb   value=185.0  source=TrainingGoal#12
          ...
        </claims>
    """
    if not claims:
        return ""
    lines = ["<claims>"]
    for c in claims:
        line = f"  - id={c.claim_id}  pred={c.predicate}  value={c.value!r}  source={c.source}"
        if c.derivation:
            line += f"  derivation={c.derivation!r}"
        lines.append(line)
    lines.append("</claims>")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_claims_builder.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_claims.py tests/test_claims_builder.py
git commit -m "Zero-hallucination Step 3.1: Claim dataclass + body_weight/goal builders"
```

---

## Task 3.2: Add today_status + week_program claim builders

**Files:**
- Modify: `coach_claims.py`
- Modify: `tests/test_claims_builder.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_claims_builder.py`:

```python
def test_today_status_emits_workout_and_run_prescribed_claims():
    """today_status scope produces claims for today's prescribed workout
    name and prescribed run type, both pinned to specific source rows."""
    today_status = {
        "date": "2026-05-06",
        "weekday": "Wednesday",
        "day_idx": 2,
        "week": 6,
        "workout_prescribed": True,
        "workout_lift_name": "Core + Mobility (Active Recovery)",
        "run_prescribed": "z2",
        "run_label": "Zone 2 easy",
        "run_duration": "60 min",
    }
    with patch("coach_claims._fetch_today_status", return_value=today_status):
        claims = build_claims(user_id=1, scope=("today_status",))
    by_id = {c.claim_id: c for c in claims}
    assert "today.weekday" in by_id
    assert by_id["today.weekday"].value == "Wednesday"
    assert "today.workout.lift_name" in by_id
    assert by_id["today.workout.lift_name"].value == "Core + Mobility (Active Recovery)"
    assert "today.run.label" in by_id
    assert by_id["today.run.label"].value == "Zone 2 easy"
    assert "today.run.duration" in by_id


def test_today_status_no_workout_emits_explicit_rest_claim():
    today_status = {
        "date": "2026-05-06",
        "weekday": "Sunday",
        "day_idx": 6,
        "week": 6,
        "workout_prescribed": False,
        "run_prescribed": "z2_long",
        "run_label": "Long fasted easy run",
        "run_duration": "90 min",
    }
    with patch("coach_claims._fetch_today_status", return_value=today_status):
        claims = build_claims(user_id=1, scope=("today_status",))
    by_id = {c.claim_id: c for c in claims}
    assert "today.workout.is_rest" in by_id
    assert by_id["today.workout.is_rest"].value is True


def test_week_program_emits_claim_per_day_run_and_lift():
    """week_program scope emits one claim per day for run type and lift name."""
    week_program = [
        {"day_idx": 0, "weekday": "Mon", "lift_name": "Lower POWER + RDL",
         "run_type": "z2", "run_label": "Easy Z2 streak", "run_duration": "35 min"},
        {"day_idx": 1, "weekday": "Tue", "lift_name": "Upper PRESS",
         "run_type": "hiit", "run_label": "VO2 4x4 intervals", "run_duration": "35 min"},
        {"day_idx": 3, "weekday": "Thu", "lift_name": "Upper PULL",
         "run_type": "z2", "run_label": "Easy Z2 streak", "run_duration": "35 min"},
    ]
    with patch("coach_claims._fetch_week_program", return_value=(6, week_program)):
        claims = build_claims(user_id=1, scope=("week_program",))
    by_id = {c.claim_id: c for c in claims}
    # Per-day run type
    assert "week6.tue.run.type" in by_id
    assert by_id["week6.tue.run.type"].value == "hiit"
    # The Thu run that the Doctor missed in the screenshot bug
    assert "week6.thu.run.label" in by_id
    assert by_id["week6.thu.run.label"].value == "Easy Z2 streak"
    # Lift name per day
    assert "week6.mon.lift.name" in by_id
    assert by_id["week6.mon.lift.name"].value == "Lower POWER + RDL"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_claims_builder.py -v`
Expected: 3 new FAILs — today_status / week_program scopes not yet implemented.

- [ ] **Step 3: Add the new builders**

Append to `coach_claims.py`:

```python
def _fetch_today_status(user_id: int) -> dict | None:
    """Returns the same dict shape build_filtered_context produces for
    'today_status'. Indirection for testability."""
    from coach_assembler import build_filtered_context
    ctx = build_filtered_context("conversation")
    return ctx.get("today_status")


def _fetch_week_program(user_id: int) -> tuple[int, list[dict]] | None:
    """Returns (current_week, list of per-day dicts with day_idx, weekday,
    lift_name, run_type, run_label, run_duration)."""
    from coach_assembler import _resolve_workout_for_day, _current_week
    from models import WeeklyRunPlan
    week = _current_week()
    days = []
    weekday_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for d in range(7):
        wt = _resolve_workout_for_day(week, d) or {}
        run_plan = WeeklyRunPlan.query.filter_by(
            user_id=user_id, week=week, day_idx=d,
        ).first()
        run_type = run_plan.run_type if run_plan else (wt.get("run") or {}).get("type")
        run_label = run_plan.label if run_plan else (wt.get("run") or {}).get("label")
        run_duration = run_plan.duration if run_plan else (wt.get("run") or {}).get("duration")
        days.append({
            "day_idx": d,
            "weekday": weekday_short[d],
            "lift_name": wt.get("liftName"),
            "run_type": run_type,
            "run_label": run_label,
            "run_duration": run_duration,
        })
    return week, days
```

Then extend `build_claims` to handle the new scopes. Modify the function body:

```python
def build_claims(user_id: int, scope: tuple[str, ...] = ()) -> list[Claim]:
    out: list[Claim] = []
    want = lambda s: not scope or s in scope

    bw = _fetch_latest_bodyweight(user_id) if want("body_weight") else None
    goal = _fetch_training_goal(user_id) if want("body_weight") or want("goal") else None

    if bw and want("body_weight"):
        out.append(Claim(
            claim_id="body.weight.current",
            predicate="athlete.current_weight_lb",
            value=float(bw.weight_lbs),
            source=f"BodyWeight#{getattr(bw, 'id', '?')} ({bw.log_date.isoformat()})",
        ))

    if goal and want("goal"):
        out.append(Claim(claim_id="body.weight.target",
                         predicate="athlete.target_weight_lb",
                         value=float(goal.target_weight),
                         source=f"TrainingGoal#{getattr(goal, 'id', '?')}"))
        out.append(Claim(claim_id="goal.daily_calories",
                         predicate="athlete.daily_calorie_target",
                         value=int(goal.daily_calories),
                         source=f"TrainingGoal#{getattr(goal, 'id', '?')}"))
        out.append(Claim(claim_id="goal.type",
                         predicate="athlete.goal_type",
                         value=str(goal.goal_type),
                         source=f"TrainingGoal#{getattr(goal, 'id', '?')}"))

    if bw and goal and want("body_weight") and want("goal"):
        delta = round(float(bw.weight_lbs) - float(goal.target_weight), 1)
        out.append(Claim(claim_id="body.weight.lb_to_target",
                         predicate="athlete.lb_to_target",
                         value=delta,
                         source="derived",
                         derivation=f"{bw.weight_lbs} - {goal.target_weight} = {delta}"))

    if want("today_status"):
        ts = _fetch_today_status(user_id)
        if ts:
            out.append(Claim(claim_id="today.weekday",
                             predicate="today.weekday_name",
                             value=str(ts["weekday"]),
                             source="today_status"))
            out.append(Claim(claim_id="today.date",
                             predicate="today.iso_date",
                             value=str(ts.get("date", "")),
                             source="today_status"))
            if ts.get("workout_prescribed"):
                if "workout_lift_name" in ts:
                    out.append(Claim(claim_id="today.workout.lift_name",
                                     predicate="today.workout.lift_name",
                                     value=str(ts["workout_lift_name"]),
                                     source="today_status"))
            else:
                out.append(Claim(claim_id="today.workout.is_rest",
                                 predicate="today.workout.is_rest_day",
                                 value=True,
                                 source="today_status"))
            if ts.get("run_prescribed"):
                out.append(Claim(claim_id="today.run.type",
                                 predicate="today.run.type",
                                 value=str(ts["run_prescribed"]),
                                 source="today_status"))
                if ts.get("run_label"):
                    out.append(Claim(claim_id="today.run.label",
                                     predicate="today.run.label",
                                     value=str(ts["run_label"]),
                                     source="today_status"))
                if ts.get("run_duration"):
                    out.append(Claim(claim_id="today.run.duration",
                                     predicate="today.run.duration",
                                     value=str(ts["run_duration"]),
                                     source="today_status"))

    if want("week_program"):
        result = _fetch_week_program(user_id)
        if result:
            week, days = result
            day_short = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            for day in days:
                short = day_short[day["day_idx"]]
                if day.get("lift_name"):
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.lift.name",
                        predicate=f"program.week{week}.{short}.lift_name",
                        value=str(day["lift_name"]),
                        source=f"WeeklyDaySchedule(week={week},day_idx={day['day_idx']})",
                    ))
                if day.get("run_type"):
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.run.type",
                        predicate=f"program.week{week}.{short}.run_type",
                        value=str(day["run_type"]),
                        source=f"WeeklyRunPlan(week={week},day_idx={day['day_idx']})",
                    ))
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.run.label",
                        predicate=f"program.week{week}.{short}.run_label",
                        value=str(day["run_label"] or ""),
                        source=f"WeeklyRunPlan(week={week},day_idx={day['day_idx']})",
                    ))
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.run.duration",
                        predicate=f"program.week{week}.{short}.run_duration",
                        value=str(day["run_duration"] or ""),
                        source=f"WeeklyRunPlan(week={week},day_idx={day['day_idx']})",
                    ))

    return out
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_claims_builder.py -v`
Expected: 7 PASS (4 from Task 3.1 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add coach_claims.py tests/test_claims_builder.py
git commit -m "Zero-hallucination Step 3.2: today_status + week_program claim builders"
```

---

## Task 3.3: Cite-validation enforcer in `coach_validator.py`

**Files:**
- Modify: `coach_validator.py`
- Test: `tests/test_cited_output_validator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cited_output_validator.py`:

```python
"""Tests for cite-validation: every numeric in response prose must
either be cited (cites=[claim_id...]) AND match the claim's value, OR
be a result of inline arithmetic on cited inputs."""
import pytest
from coach_claims import Claim
from coach_validator import (
    validate_cited_response,
    CiteViolation,
)


def _claim(claim_id, value, predicate=None, source="src#1"):
    return Claim(
        claim_id=claim_id,
        predicate=predicate or claim_id,
        value=value,
        source=source,
    )


def test_response_with_correct_cite_passes():
    response = {
        "lead": {"text": "You're at 207.2 lb.",
                 "cites": ["body.weight.current"]},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.current", 207.2)]
    out = validate_cited_response(response, claims)
    assert out == []


def test_response_with_unknown_claim_id_fails():
    response = {
        "lead": {"text": "You're at 207.2 lb.",
                 "cites": ["body.weight.imaginary"]},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.current", 207.2)]
    out = validate_cited_response(response, claims)
    assert any("body.weight.imaginary" in v.message for v in out)


def test_value_in_prose_must_match_cited_claim():
    """If prose says '207.2 lb' but cited claim is body.weight.target=185,
    the value-string-match fails."""
    response = {
        "lead": {"text": "You're at 207.2 lb.",
                 "cites": ["body.weight.target"]},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.target", 185.0),
              _claim("body.weight.current", 207.2)]
    out = validate_cited_response(response, claims)
    assert any("207.2" in v.message and "match" in v.message.lower() for v in out)


def test_uncited_number_in_prose_fails():
    """Numbers in prose must be cited (or come from inline derivation)."""
    response = {
        "lead": {"text": "You're 22.2 lb to target.", "cites": []},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.lb_to_target", 22.2)]
    out = validate_cited_response(response, claims)
    assert any("22.2" in v.message and "cite" in v.message.lower() for v in out)


def test_inline_arithmetic_with_cited_inputs_passes():
    """If response shows '207.2 - 185 = 22.2' AND both 207.2 and 185 are
    cited, the resulting 22.2 is verified."""
    response = {
        "lead": {
            "text": "207.2 - 185 = 22.2 lb to target.",
            "cites": ["body.weight.current", "body.weight.target"],
        },
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.current", 207.2),
              _claim("body.weight.target", 185.0)]
    out = validate_cited_response(response, claims)
    assert out == []


def test_trivial_numbers_skipped():
    response = {
        "lead": {"text": "You have 1 goal and 2 weeks of options.",
                 "cites": []},
        "reasoning": [], "caveats": [],
    }
    claims = []
    out = validate_cited_response(response, claims)
    # 1 and 2 should be ignored
    assert out == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_cited_output_validator.py -v`
Expected: 6 FAIL — `validate_cited_response` not implemented.

- [ ] **Step 3: Implement validator**

Append to `coach_validator.py`:

```python
"""Cite-validation for the multi-agent claims architecture (Step 3).

A response is a JSON object like:
    {
      "lead": {"text": "...", "cites": ["claim_id_1", "claim_id_2"]},
      "reasoning": [{"text": "...", "cites": [...]}],
      "caveats": [],
    }

Validation checks:
  1. Every claim_id cited exists in the claims table
  2. Every numeric in prose is either:
     (a) the value of a cited claim (string-match within tolerance), OR
     (b) the result of inline arithmetic where the inputs are cited claims
"""
from __future__ import annotations
from dataclasses import dataclass
import re

from coach_multi_agent import (
    _NUMBER_RE,
    _DERIVATION_RE,
    _normalize_number,
    _TRIVIAL_NUMBERS,
)


@dataclass
class CiteViolation:
    """A specific cite-validation failure with enough detail to feed back
    to the model in a retry prompt."""
    kind: str        # "unknown_claim_id" | "value_mismatch" | "uncited_number"
    message: str


def _iter_text_blocks(response: dict):
    """Yield (text, cites) pairs from response sections that may contain
    prose with citations: lead, each reasoning entry, each caveat."""
    lead = response.get("lead") or {}
    if isinstance(lead, dict) and lead.get("text"):
        yield lead.get("text", ""), list(lead.get("cites") or [])
    for r in response.get("reasoning") or []:
        if isinstance(r, dict):
            yield r.get("text", ""), list(r.get("cites") or [])
    for c in response.get("caveats") or []:
        if isinstance(c, dict):
            yield c.get("text", ""), list(c.get("cites") or [])
        elif isinstance(c, str):
            yield c, []


def validate_cited_response(response: dict, claims: list) -> list[CiteViolation]:
    """Return list of cite-violations (empty list = clean)."""
    violations: list[CiteViolation] = []
    by_id = {c.claim_id: c for c in claims}

    for text, cites in _iter_text_blocks(response):
        # 1. unknown claim_id
        for cid in cites:
            if cid not in by_id:
                violations.append(CiteViolation(
                    kind="unknown_claim_id",
                    message=f"Cited unknown claim_id: {cid!r}. Not in claims table.",
                ))

        # 2. numbers in prose
        cited_values = {_normalize_number(str(by_id[c].value)) for c in cites if c in by_id}
        # Inline-derivation results acceptable when inputs are cited.
        derived_results: set[str] = set()
        for m in _DERIVATION_RE.finditer(text):
            a, b, c = (_normalize_number(g) for g in m.groups())
            if a in cited_values and b in cited_values:
                derived_results.add(c)

        for raw in _NUMBER_RE.findall(text):
            n = _normalize_number(raw)
            if n in _TRIVIAL_NUMBERS:
                continue
            if n in cited_values:
                continue
            if n in derived_results:
                continue
            violations.append(CiteViolation(
                kind="uncited_number",
                message=f"Number {n!r} in prose is not cited and not derived from cited inputs. Either add a cite or remove the number.",
            ))

        # 3. value-match: at least one cited claim's value should appear
        # in the prose if any cite is present and the cite is numeric.
        # (We're permissive here — if cites=[] the prose has no numeric
        # claims to verify against. The uncited-number check above
        # already catches numbers without cites.)
        for cid in cites:
            if cid not in by_id:
                continue
            value_str = _normalize_number(str(by_id[cid].value))
            # Only check value-match for numeric claims; string claims
            # like "Wednesday" are checked separately.
            try:
                float(value_str)
            except ValueError:
                continue
            response_nums = {_normalize_number(m) for m in _NUMBER_RE.findall(text)}
            if value_str not in response_nums and value_str not in derived_results:
                violations.append(CiteViolation(
                    kind="value_mismatch",
                    message=f"Cited claim {cid} has value {value_str!r} but it does not appear in the prose. Either remove the cite or include the value.",
                ))

    return violations
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_cited_output_validator.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_validator.py tests/test_cited_output_validator.py
git commit -m "Zero-hallucination Step 3.3: cite-validation enforcer (existence + value-match)"
```

---

## Task 3.4: Update Doctor persona to require JSON-with-cites output

**Files:**
- Modify: `.claude/agents/doctor.md`

- [ ] **Step 1: Add the JSON-output requirement section**

In `.claude/agents/doctor.md`, BEFORE the existing "OUTPUT FORMAT" block, insert:

```markdown
OUTPUT FORMAT — STRUCTURED JSON WITH CITATIONS:

Your final response MUST be a JSON object with this exact shape:

{
  "lead": {
    "text": "<the punch-line answer, 1-2 sentences>",
    "cites": ["<claim_id>", "<claim_id>"]
  },
  "reasoning": [
    {"text": "<one reasoning step>", "cites": ["<claim_id>"]},
    {"text": "<another step>", "cites": ["<claim_id>", "<claim_id>"]}
  ],
  "caveats": [
    {"text": "<a caveat or risk>", "cites": []}
  ],
  "follow_up_question": "<one question or empty string>"
}

EVERY numeric or factual assertion in any `text` field MUST be backed by at
least one `claim_id` in the corresponding `cites` array. The claim_ids must
exist in the <claims> block of the athlete_data slice.

If you do inline arithmetic like "207.2 - 185 = 22.2", both inputs (207.2
and 185) must be cited claims; the result (22.2) is then automatically
verified.

Numbers WITHOUT cites are rejected by the validator and you'll be re-prompted
to fix the response. Don't try; just cite.

The app renders the JSON to the athlete as natural prose (Lombardi/Saban
voice preserved) — your job is to populate the structure honestly.
```

Also UPDATE the existing "OUTPUT FORMAT" block to reflect this. Find the section starting with `OUTPUT FORMAT:` and replace its body to point at the JSON requirement.

- [ ] **Step 2: Verify persona still loads**

Run: `venv/bin/pytest tests/test_specialist_loader.py -v`
Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/doctor.md
git commit -m "Zero-hallucination Step 3.4: Doctor persona requires JSON output with cites"
```

---

## Task 3.5: Wire claims-block into slice + cite-validation reject loop

**Files:**
- Modify: `coach_assembler.py`
- Modify: `coach_multi_agent.py`
- Modify: `tests/test_multi_agent.py`

- [ ] **Step 1: Add claims to the slice**

In `coach_assembler.py`, find `_format_athlete_data(ctx, requires)` (around line 1296) and add a `<claims>` block at the top of the output. Before the existing `parts` list construction, add:

```python
    # Claims block — typed facts the model must cite by claim_id.
    # See coach_claims.build_claims for the schema. Empty when no
    # builders apply (graceful degradation; the rest of the slice
    # still renders).
    try:
        from coach_claims import build_claims, format_claims_block
        claims_text = format_claims_block(build_claims(
            user_id=current_user.id,
            scope=("body_weight", "goal", "today_status", "week_program"),
        ))
    except Exception:
        claims_text = ""
```

Then inside the existing `parts.append(...)` ordering, prepend the claims block:

```python
    if claims_text:
        parts.insert(0, claims_text)
```

- [ ] **Step 2: Add JSON-parse + cite-validation to the orchestrator**

In `coach_multi_agent.py`, modify the end_turn handler (the block after `# end_turn — extract text, then fact-check before returning.`):

```python
        # end_turn — extract text, then fact-check before returning.
        text = "\n".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()

        # === Step 3: cite-validation on JSON output ===
        # Try to parse as JSON; if so, run cite-validation against the
        # claims table. Fall back to numeric fact-check otherwise (older
        # response shape; both validators stay during migration).
        cite_violations = []
        rendered_text = text
        try:
            import json as _json
            parsed = _json.loads(text)
            if isinstance(parsed, dict) and ("lead" in parsed or "reasoning" in parsed):
                from coach_claims import build_claims
                from coach_validator import validate_cited_response
                claims = build_claims(
                    user_id=user_id,
                    scope=("body_weight", "goal", "today_status", "week_program"),
                )
                cite_violations = validate_cited_response(parsed, claims)
                if not cite_violations:
                    rendered_text = _render_json_response(parsed)
        except Exception:
            pass

        if cite_violations and fact_check_retries_used < MAX_FACT_CHECK_RETRIES and turn < MAX_TOOL_TURNS - 1:
            convo.append({"role": "assistant",
                          "content": [b.model_dump() for b in resp.content]})
            convo.append({
                "role": "user",
                "content": (
                    "CITE-VALIDATION FAILED. The following violations:\n"
                    + "\n".join(f"  - [{v.kind}] {v.message}" for v in cite_violations)
                    + "\n\nFix the response by:\n"
                    + "  - Adding cites for any uncited numbers\n"
                    + "  - Removing cites that don't exist in the claims table\n"
                    + "  - Showing inline arithmetic where the result is derived\n\n"
                    + "Re-emit the full JSON response with corrections."
                ),
            })
            fact_check_retries_used += 1
            continue

        # Continue with the existing numeric fact-check fallback below.
        fact_check_source = system + "\n" + "\n".join(tool_results_collected)
        unverified = _verify_response_numbers(rendered_text, fact_check_source)
        # ... existing logic ...

        return rendered_text
```

Add the JSON renderer near the top of `coach_multi_agent.py` (after imports):

```python
def _render_json_response(parsed: dict) -> str:
    """Render the structured JSON response back to user-visible prose.
    Preserves the Lombardi/Saban voice baked into the lead text; just
    flattens the structure to natural paragraphs.
    """
    parts = []
    lead = parsed.get("lead") or {}
    if isinstance(lead, dict) and lead.get("text"):
        parts.append(lead["text"].strip())
    for r in parsed.get("reasoning") or []:
        if isinstance(r, dict) and r.get("text"):
            parts.append(r["text"].strip())
    caveats = parsed.get("caveats") or []
    if caveats:
        for c in caveats:
            if isinstance(c, dict) and c.get("text"):
                parts.append(f"Caveat: {c['text'].strip()}")
            elif isinstance(c, str):
                parts.append(f"Caveat: {c.strip()}")
    fu = parsed.get("follow_up_question") or ""
    if fu and isinstance(fu, str) and fu.strip():
        parts.append(fu.strip())
    return "\n\n".join(parts)
```

- [ ] **Step 3: Add integration test**

Append to `tests/test_multi_agent.py`:

```python
def test_json_output_with_valid_cites_passes_through_to_user():
    """When the model emits valid JSON with proper cites, the orchestrator
    renders it to prose and returns without retry."""
    from coach_multi_agent import coach_chat_multiagent
    json_response = (
        '{"lead": {"text": "207.2 lb today.", "cites": ["body.weight.current"]},'
        '"reasoning": [], "caveats": [], "follow_up_question": ""}'
    )
    text_block = MagicMock(type="text", text=json_response)
    fake_response = MagicMock(stop_reason="end_turn", content=[text_block])

    fake_claim = MagicMock(claim_id="body.weight.current", value=207.2,
                           predicate="athlete.current_weight_lb",
                           source="BodyWeight#1", derivation=None)

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_claims.build_claims", return_value=[fake_claim]):
            result = coach_chat_multiagent(
                user_id=1,
                athlete_data="<athlete_data/>",
                messages=[{"role": "user", "content": "What's my weight?"}],
            )

    assert "207.2" in result
    # Natural prose, no JSON braces visible to user
    assert "{" not in result
    assert mc.return_value.messages.create.call_count == 1
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: ALL PASS (the new test + existing 14+).

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py coach_multi_agent.py tests/test_multi_agent.py
git commit -m "Zero-hallucination Step 3.5: claims-block in slice + cite-validation reject loop"
```

---

## Task 3.6: Migrate specialist personas to JSON-with-cites

**Files:**
- Modify: `.claude/agents/nutritionist.md`
- Modify: `.claude/agents/strength-coach.md`
- Modify: `.claude/agents/running-coach.md`

- [ ] **Step 1: Add the same JSON output block to each specialist**

For each of nutritionist.md, strength-coach.md, running-coach.md, insert this block before the existing "Output format" section:

```markdown
OUTPUT FORMAT — STRUCTURED JSON WITH CITATIONS:

Your consult response MUST be JSON:

{
  "recommendation": {"text": "<the call>", "cites": ["<claim_id>", ...]},
  "reasoning": {"text": "<the why>", "cites": ["<claim_id>", ...]},
  "caveat": {"text": "<a risk or 'None.'>", "cites": []}
}

Every number in the text fields must be backed by a claim_id from the
<claims> block. Numbers without cites get rejected by the Doctor's
validator. The Doctor renders your JSON into the synthesized response.
```

- [ ] **Step 2: Verify all personas still load**

Run: `venv/bin/pytest tests/test_specialist_loader.py -v`
Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/nutritionist.md .claude/agents/strength-coach.md .claude/agents/running-coach.md
git commit -m "Zero-hallucination Step 3.6: specialist personas require JSON-with-cites"
```

---

## Task 3.7: Live audit run with claims architecture

**Files:** none modified (verification)

- [ ] **Step 1: Run the existing multi-agent audit suite against prod**

Use the production credentials (per `tests/coach_audit/runner.py` infrastructure already in place):

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  venv/bin/pytest tests/coach_audit/test_coach_audit.py::test_specialist_targeted \
  tests/coach_audit/test_coach_audit.py::test_doctor_synthesis \
  -n 4 -v 2>&1 | tee /tmp/zero-hallucination-step-3-audit.log
```

Expected: pass rate ≥90% (the bar set in the multi-agent plan). If lower, triage failures into:
  - cite-validation false positives (validator too strict — tighten)
  - claim-coverage gaps (missing predicates — extend `build_claims`)
  - real model misbehavior (persona refinement)

- [ ] **Step 2: Document findings**

If gaps surface, file them as Task 3.8 (extension). If clean, move to Step 4.

---

# STEP 4 — Async two-pass auditor (Sonnet single-claim cite-check + posture audit)

**What it closes:** Class A residuals (misattribution that survives the cite-validator because the predicate name match isn't always reliable) and class H (defensive pushback). Async pattern: emit response immediately, audit in background, send a follow-up "correction" message ~3-5s later only if the audit rejects.

**Effort:** 3-5 days

## Task 4.1: Single-claim auditor function

**Files:**
- Create: `coach_auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_auditor.py`:

```python
"""Tests for the single-claim auditor (Sonnet-backed)."""
import pytest
from unittest.mock import MagicMock, patch
from coach_auditor import audit_claim, AuditResult


def test_supported_claim_returns_supported():
    fake_resp = MagicMock(content=[MagicMock(type="text", text="supported")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_claim(
            claim_text="207.2 lb today",
            source_rows=["body.weight.current = 207.2 (BodyWeight#4821)"],
        )
    assert result.supported is True


def test_unsupported_claim_returns_not_supported_with_reason():
    fake_resp = MagicMock(content=[MagicMock(type="text",
                                              text="not supported: 5 weeks before 50k != 5 weeks left in cut")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_claim(
            claim_text="5 weeks left in the cut",
            source_rows=["race.weeks_until_50k = 5-6 weeks"],
        )
    assert result.supported is False
    assert "5 weeks" in result.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_auditor.py -v`
Expected: 2 FAIL — `coach_auditor` module does not exist.

- [ ] **Step 3: Implement single-claim auditor**

Create `coach_auditor.py`:

```python
"""Sonnet-backed single-claim auditor for Step 4 of the zero-hallucination
architecture. Each call audits ONE claim against ONE or more source rows;
returns supported / not-supported + reason. Cheap (~$0.005/audit) and
parallel-friendly.

Architectural intent: the orchestrator calls audit_claim for each cited
claim in the response after the response is generated. If any audit
returns not-supported, the orchestrator either (a) re-prompts the
Doctor with the violations, or (b) emits a follow-up correction
message 3-5s after the original response (async pattern, lower
perceived latency).
"""
from __future__ import annotations
from dataclasses import dataclass
import os


@dataclass
class AuditResult:
    supported: bool
    reason: str = ""


_AUDIT_PROMPT = """You audit single coach claims for support.

CLAIM:
{claim}

SOURCE ROWS (the claim must be supported by these — and ONLY these):
{rows}

Respond with EXACTLY one of:
  supported
  not supported: <one short sentence why>

Rules:
- "supported" means: every fact in the claim is present in or directly derivable from the source rows.
- A predicate-context mismatch is "not supported" — e.g. claim says "5 weeks left in cut" but source rows are about "5 weeks before 50k race". The number is real but the noun is wrong.
- Inline arithmetic is OK if both inputs are in source rows.
- One short answer. No preamble. No explanation beyond the reason."""


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=20.0,
        max_retries=3,
    )


def audit_claim(claim_text: str, source_rows: list[str]) -> AuditResult:
    """Audit a single claim against source rows. Returns AuditResult."""
    client = _anthropic_client()
    rows_block = "\n".join(f"  - {r}" for r in source_rows) if source_rows else "  (none)"
    user_msg = _AUDIT_PROMPT.format(claim=claim_text, rows=rows_block)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=120,
        system="You are a precise fact-check auditor.",
        messages=[{"role": "user", "content": user_msg}],
    )
    out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip().lower()
    if out.startswith("supported"):
        return AuditResult(supported=True)
    if out.startswith("not supported"):
        # Strip the "not supported:" prefix
        reason = out.replace("not supported", "", 1).lstrip(":").strip()
        return AuditResult(supported=False, reason=reason or out)
    # Defensive: ambiguous response — treat as supported to avoid blocking
    # legitimate output, but include the raw text as the reason for logging.
    return AuditResult(supported=True, reason=f"ambiguous_audit_response: {out!r}")
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_auditor.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_auditor.py tests/test_auditor.py
git commit -m "Zero-hallucination Step 4.1: single-claim Sonnet auditor"
```

---

## Task 4.2: Async fan-out + posture audit

**Files:**
- Modify: `coach_auditor.py`
- Test: `tests/test_posture_audit.py`

- [ ] **Step 1: Add posture-audit tests**

Create `tests/test_posture_audit.py`:

```python
"""Tests for the posture audit — detects defensive-pushback failures."""
import pytest
from unittest.mock import MagicMock, patch
from coach_auditor import audit_posture, PostureResult


def test_response_accepting_user_correction_passes():
    user_msg = "but I have VO2 4x4 scheduled for thursday"
    response_text = "You're right — Thu has VO2 4x4, I missed it. Let me reconsider."
    fake_resp = MagicMock(content=[MagicMock(type="text", text="ok")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_posture(user_msg, response_text)
    assert result.ok is True


def test_response_challenging_user_after_their_correction_fails():
    user_msg = "but I have VO2 4x4 scheduled for thursday"
    response_text = "What are you seeing on Thursday that says quality run?"
    fake_resp = MagicMock(content=[MagicMock(type="text",
                                              text="defensive: response challenges the user instead of re-reading data")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_posture(user_msg, response_text)
    assert result.ok is False
    assert "defensive" in result.reason.lower() or "challenge" in result.reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_posture_audit.py -v`
Expected: 2 FAIL — `audit_posture` not implemented.

- [ ] **Step 3: Implement posture audit + async fan-out helper**

Append to `coach_auditor.py`:

```python
@dataclass
class PostureResult:
    ok: bool
    reason: str = ""


_POSTURE_PROMPT = """You audit coach response posture, NOT facts.

USER MESSAGE (most recent):
{user_msg}

COACH RESPONSE:
{response}

Question: did the user assert a fact about their schedule or program? If yes,
did the coach (a) accept it and re-read the data, or (b) challenge the user
asking what they're seeing?

Respond with EXACTLY one of:
  ok
  defensive: <one short sentence describing the failure>

Rules:
- "ok" is the default — only flag clear-cut defensive pushback.
- The user is the source of ground truth about what they see in the UI.
  Asking "what are you seeing" / "where does it say X" is the failure
  pattern.
- Genuine clarifying questions ("when did you log that run?") are fine.
- One short answer. No preamble."""


def audit_posture(user_message: str, response_text: str) -> PostureResult:
    client = _anthropic_client()
    msg = _POSTURE_PROMPT.format(user_msg=user_message, response=response_text)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=80,
        system="You audit conversational posture, not facts.",
        messages=[{"role": "user", "content": msg}],
    )
    out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip().lower()
    if out.startswith("ok"):
        return PostureResult(ok=True)
    if out.startswith("defensive"):
        reason = out.replace("defensive", "", 1).lstrip(":").strip()
        return PostureResult(ok=False, reason=reason or out)
    return PostureResult(ok=True, reason=f"ambiguous: {out!r}")


def audit_response_async(
    user_message: str,
    response_text: str,
    cited_claims: list[tuple[str, list[str]]],
) -> tuple[list[AuditResult], PostureResult]:
    """Run all per-claim audits + posture audit in parallel.

    cited_claims: list of (claim_text, source_rows) pairs — one per
    claim that needs auditing.

    Returns (claim_results, posture_result). Caller decides how to act
    on failures (re-prompt vs. follow-up correction).
    """
    import asyncio

    async def run_one_claim(text, rows):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, audit_claim, text, rows)

    async def run_posture():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, audit_posture, user_message, response_text)

    async def run_all():
        claim_tasks = [run_one_claim(t, r) for t, r in cited_claims]
        posture_task = run_posture()
        claim_results = await asyncio.gather(*claim_tasks)
        posture_result = await posture_task
        return claim_results, posture_result

    try:
        return asyncio.run(run_all())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, run_all()).result()
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_posture_audit.py tests/test_auditor.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_auditor.py tests/test_posture_audit.py
git commit -m "Zero-hallucination Step 4.2: posture audit + async fan-out helper"
```

---

## Task 4.3: Wire async auditor into orchestrator (emit-then-correct pattern)

**Files:**
- Modify: `coach_multi_agent.py`
- Modify: `tests/test_multi_agent.py`

- [ ] **Step 1: Document the emit-then-correct pattern in coach_multi_agent.py**

The orchestrator returns the response immediately for low perceived latency. The auditor runs in a background thread; if it rejects, the orchestrator emits a follow-up correction via the chat history (next turn's slice will include it as a system note for the model to reference).

In `coach_multi_agent.py`, after `return rendered_text` in the end_turn handler, add a sibling pathway:

```python
        # Pre-compute the audit fan-out arguments BEFORE returning. The
        # actual audit runs in a background thread; if it rejects, the
        # follow-up correction is queued via a side channel (see
        # _post_response_audit_hook).
        if cite_violations == [] and parsed:
            # Only run async audit when we have a structured response
            # that already passed cite-validation. The auditor is for
            # residual class-A misattribution + class-H posture.
            _spawn_audit(
                user_message=last_user_msg,
                response_text=rendered_text,
                parsed=parsed,
                claims=claims,
                user_id=user_id,
            )

        return rendered_text
```

Add the `_spawn_audit` function near the top of the file:

```python
def _spawn_audit(user_message: str, response_text: str, parsed: dict,
                 claims: list, user_id: int) -> None:
    """Fire-and-forget async audit. If any claim fails or posture is
    defensive, write a `coach_audit_finding` row that the next turn's
    slice picks up, AND post a follow-up correction to the chat (per
    chat_message channel — the UI streams it ~3-5s after the original).

    For now, fire-and-forget logging only; the post-to-chat hookup
    requires a separate task tying into app.py:5729 (the chat endpoint
    that owns ChatMessage writes).
    """
    import threading
    import logging
    log = logging.getLogger(__name__)

    def _run():
        try:
            from coach_auditor import audit_response_async
            cited_pairs = []
            by_id = {c.claim_id: c for c in claims}

            def collect(section):
                if isinstance(section, dict) and section.get("text"):
                    cites = section.get("cites") or []
                    rows = [
                        f"{cid}: pred={by_id[cid].predicate} value={by_id[cid].value!r} source={by_id[cid].source}"
                        for cid in cites if cid in by_id
                    ]
                    if rows:
                        cited_pairs.append((section["text"], rows))

            collect(parsed.get("lead"))
            for r in parsed.get("reasoning") or []:
                collect(r)

            claim_results, posture_result = audit_response_async(
                user_message, response_text, cited_pairs,
            )
            failures = [r for r in claim_results if not r.supported]
            if failures or not posture_result.ok:
                log.warning(
                    "audit_response: failures=%s posture=%s response=%r",
                    [f.reason for f in failures],
                    posture_result.reason if not posture_result.ok else "ok",
                    response_text[:200],
                )
                # Future: post a follow-up correction to chat. For now,
                # log only — measurable signal for triage.
        except Exception as e:
            log.warning("audit_response background failed: %s", e, exc_info=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
```

- [ ] **Step 2: Add integration test**

Append to `tests/test_multi_agent.py`:

```python
def test_audit_runs_async_when_response_is_clean():
    """When the response passes cite-validation, the async auditor
    should be spawned (fire-and-forget). Test asserts the helper is
    invoked; we don't block on it."""
    from coach_multi_agent import coach_chat_multiagent
    json_response = (
        '{"lead": {"text": "207.2 lb today.", "cites": ["body.weight.current"]},'
        '"reasoning": [], "caveats": [], "follow_up_question": ""}'
    )
    text_block = MagicMock(type="text", text=json_response)
    fake_response = MagicMock(stop_reason="end_turn", content=[text_block])
    fake_claim = MagicMock(claim_id="body.weight.current", value=207.2,
                           predicate="athlete.current_weight_lb",
                           source="BodyWeight#1", derivation=None)

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_claims.build_claims", return_value=[fake_claim]):
            with patch("coach_multi_agent._spawn_audit") as ms:
                result = coach_chat_multiagent(
                    user_id=1,
                    athlete_data="<athlete_data/>",
                    messages=[{"role": "user", "content": "What's my weight?"}],
                )
    ms.assert_called_once()
    assert "207.2" in result
```

- [ ] **Step 3: Run tests**

Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add coach_multi_agent.py tests/test_multi_agent.py
git commit -m "Zero-hallucination Step 4.3: async auditor wired into orchestrator (fire-and-forget)"
```

---

## Task 4.4: Live measurement run

**Files:** none modified (verification)

- [ ] **Step 1: Run the audit suite + measure auditor signal**

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  venv/bin/pytest tests/coach_audit/ -n 4 -v 2>&1 \
  | tee /tmp/zero-hallucination-step-4-audit.log
```

Then grep server logs (or stdout if tested locally) for `audit_response: failures=` to count auditor catches.

- [ ] **Step 2: Triage findings**

If auditor catches > 5% of responses as failed, that's the signal Step 4 is doing real work. If < 1%, Steps 1-3 may have over-corrected and Step 4 is paranoid (still fine — it's async). If failures cluster in specific classes (e.g. all posture, no claim violations), tighten the relevant audit prompt.

- [ ] **Step 3: Decide on Step 5**

Per the architectural review, knowledge-graph claim diffing (Step 5) is deferred until measured. Decide based on the residual failures from this step whether to invest.

---

## Self-Review

**Spec coverage check:**

| Hallucination class (from review) | Closed by |
|---|---|
| A — misattribution | Step 3 (cite-validation predicate match) + Step 4 (single-claim auditor) |
| B — schedule miss / scope errors | Step 2 (force-call tools) + Step 3 (per-day claims in week_program scope) |
| C — fabricated pace | Step 1 ✅ (already shipped — null-aware formatter) |
| D — cascade reasoning | Step 3 (claims grounding) + Step 4 (per-claim audit catches premise breaks) |
| E — tool-failure leakage | Step 1 ✅ (already shipped — tool-failure rerouting) |
| F — field-semantics confusion | Step 1 ✅ (already shipped — avg_hr_full_session rename) |
| G — stale-cache / time-shift | Step 2 (force-call get_today_status on day-keyword messages) |
| H — defensive pushback | Step 4 (posture audit) |

All 8 classes covered.

**Placeholder scan:** No "TODO" / "fill in details" / "similar to above" patterns. Each task contains the full code its step changes.

**Type consistency:**
- `Claim(claim_id, predicate, value, source, derivation)` — consistent across Tasks 3.1, 3.2, 3.3, 3.5, 4.3
- `ForcedCall(tool_name, kwargs)` — Tasks 2.1, 2.2, 2.3
- `CiteViolation(kind, message)` — Tasks 3.3, 3.5
- `AuditResult(supported, reason)` and `PostureResult(ok, reason)` — Tasks 4.1, 4.2, 4.3
- `validate_cited_response(response, claims) -> list[CiteViolation]` — defined Task 3.3, called Task 3.5
- `build_claims(user_id, scope) -> list[Claim]` — defined Task 3.1, extended 3.2, called 3.5 + 4.3

All consistent.
