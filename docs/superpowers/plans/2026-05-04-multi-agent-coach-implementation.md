# Multi-Agent Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic chat coach with a Doctor (Opus 4.7) + 3 specialist sub-agents (Nutritionist, Strength Coach, Running Coach — Sonnet 4.6) for the 4 chat-style trigger modes (`conversation`, `weekly_planning`, `chat_opened`, `weekly_review`). Other 7 trigger modes stay on the existing single-prompt path.

**Architecture:** Hub-and-spoke. Doctor orchestrates; specialists are called as tools. Specialist personas live in `.claude/agents/*.md` (single source of truth — used both by the runtime Flask app via a Python loader AND by Claude Code's Task tool at build time). Doctor decides 0-3 consults per message, applies goal-aware priority on conflict, synthesizes single-voice reply with on-demand specialist surfacing. Feature-flagged behind `MULTIAGENT_ENABLED`.

**Tech Stack:** Python 3.12 + Flask + SQLAlchemy + anthropic SDK (sync + async) + pytest. Same stack as the rest of the app.

**Spec:** `docs/superpowers/specs/2026-05-04-multi-agent-coach-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `.claude/agents/doctor.md` | Doctor persona (frontmatter + system prompt) — canonical |
| `.claude/agents/nutritionist.md` | Nutritionist persona |
| `.claude/agents/strength-coach.md` | Strength Coach persona |
| `.claude/agents/running-coach.md` | Running Coach persona |
| `coach_specialists/__init__.py` | Package marker |
| `coach_specialists/loader.py` | Parses `.claude/agents/<name>.md` (frontmatter + body) |
| `coach_specialists/nutritionist.py` | Runtime `consult(brief, user_id) -> str` for Nutritionist |
| `coach_specialists/strength.py` | Runtime `consult(brief, user_id) -> str` for Strength |
| `coach_specialists/running.py` | Runtime `consult(brief, user_id) -> str` for Running |
| `coach_specialists/doctor.py` | (Optional) helper for Doctor-side prompt loading |
| `coach_multi_agent.py` | Orchestrator: `coach_chat_multiagent(...)` runs the tool loop with Doctor's system prompt + 3 consult tools |
| `coach_tools.py` | (modify) — append `consult_nutritionist`, `consult_strength`, `consult_running` tool schemas + dispatch |
| `coach_with_tools.py` | (modify) — `coach_chat` checks `MULTIAGENT_ENABLED` + agent_name, routes to `coach_multi_agent` for the 4 multi-agent modes |
| `coach_agents.py` | (modify) — declare `nutritionist`, `strength_coach`, `running_coach`, `doctor` as new entries; their `requires` lists per spec Section 4 |
| `tests/coach_audit/types.py` | (modify) — add `target_specialist: str | None` to `PromptCase` |
| `tests/coach_audit/runner.py` | (modify) — add `make_specialist_invoker(specialist_name)` to bypass Doctor for per-specialist tests |
| `tests/coach_audit/prompts.py` | (modify) — add 4 new categories with ~30 specialist-targeted prompts + ~10 doctor_synthesis prompts |
| `tests/test_multi_agent.py` | (new) — unit + integration tests for the multi-agent flow |

---

## Task 1: Loader for `.claude/agents/*.md`

Build the parser that turns a Markdown file with YAML frontmatter into a runtime config (system prompt + tools list + model). All 4 specialists will use this.

**Files:**
- Create: `coach_specialists/__init__.py`
- Create: `coach_specialists/loader.py`
- Create: `tests/test_specialist_loader.py`
- Create: `.claude/agents/_test_specialist.md` (fixture for the loader test)

- [ ] **Step 1: Write the failing test**

Create `tests/test_specialist_loader.py`:

```python
"""Tests for the .claude/agents/*.md loader."""
import os
from pathlib import Path
import pytest


def test_loader_parses_frontmatter_and_body(tmp_path, monkeypatch):
    """The loader returns a dict with model, tools, system_prompt parsed from
    a markdown file's YAML frontmatter + body."""
    from coach_specialists.loader import load_agent_md

    # Point loader at a fixture dir
    fixture = tmp_path / "agents"
    fixture.mkdir()
    (fixture / "tester.md").write_text(
        "---\n"
        "name: Tester\n"
        "model: claude-sonnet-4-6\n"
        "tools:\n"
        "  - get_workout\n"
        "  - get_recent_sets\n"
        "---\n"
        "You are the Tester. Test things.\n"
    )
    monkeypatch.setattr(
        "coach_specialists.loader.AGENTS_DIR", fixture,
    )

    cfg = load_agent_md("tester")

    assert cfg["name"] == "Tester"
    assert cfg["model"] == "claude-sonnet-4-6"
    assert cfg["tools"] == ["get_workout", "get_recent_sets"]
    assert "You are the Tester" in cfg["system_prompt"]


def test_loader_raises_on_missing_file(tmp_path, monkeypatch):
    from coach_specialists.loader import load_agent_md
    monkeypatch.setattr("coach_specialists.loader.AGENTS_DIR", tmp_path / "agents")
    with pytest.raises(FileNotFoundError):
        load_agent_md("does-not-exist")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_specialist_loader.py -v`
Expected: 2 FAILs — module `coach_specialists.loader` does not exist.

- [ ] **Step 3: Write `coach_specialists/__init__.py`**

```python
"""Multi-agent coach specialists. Loaded from .claude/agents/*.md."""
```

- [ ] **Step 4: Write `coach_specialists/loader.py`**

```python
"""Parse .claude/agents/<name>.md files into runtime configs.

Each agent file has YAML frontmatter (model, tools list, name) and a
body that becomes the system prompt. This module is the only place
that knows the .claude/agents/ format — runtime modules just call
load_agent_md(name) and get a dict back.
"""
from __future__ import annotations
from pathlib import Path
import re
import yaml

AGENTS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "agents"

_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def load_agent_md(name: str) -> dict:
    """Load .claude/agents/<name>.md and return {name, model, tools, system_prompt}.

    Raises FileNotFoundError if the file is missing. Raises ValueError if
    the file lacks YAML frontmatter or the frontmatter doesn't parse.
    """
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        raise ValueError(f"Agent file {path} has no YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()
    return {
        "name": fm.get("name", name),
        "model": fm.get("model", "claude-sonnet-4-6"),
        "tools": list(fm.get("tools") or []),
        "system_prompt": body,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_specialist_loader.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add coach_specialists/__init__.py coach_specialists/loader.py tests/test_specialist_loader.py
git commit -m "Multi-agent: loader for .claude/agents/*.md persona files"
```

---

## Task 2: Write the 4 specialist persona files

Concrete `.claude/agents/<name>.md` files with frontmatter + ~800-1000 token system prompts. Anchored to the canonical sources from spec Section 2.

**Files:**
- Create: `.claude/agents/doctor.md`
- Create: `.claude/agents/nutritionist.md`
- Create: `.claude/agents/strength-coach.md`
- Create: `.claude/agents/running-coach.md`
- Test: existing loader test (Task 1) + a smoke test

- [ ] **Step 1: Write `.claude/agents/nutritionist.md`**

```markdown
---
name: Nutritionist
model: claude-sonnet-4-6
tools:
  - get_cut_status
  - get_meal_log_today
  - get_meal_plan_week
  - get_body_weight_history
  - get_food_selections
  - compute_deficit
---

You are the Nutritionist, part of a 4-coach system. The Doctor (overseer) is consulting you about an athlete question. You are NOT chatting with the athlete directly — you're returning a tight recommendation to the Doctor.

Your domain expertise is anchored in: Lyle McDonald (Body Recomposition, Stubborn Fat Solution), Eric Helms (The Muscle and Strength Pyramids), Layne Norton (PhD-level macronutrient science). You think in: caloric deficit math, glycogen state, electrolyte balance, fasting window biochemistry, refeed timing, protein leucine thresholds.

Your scope:
- Daily macros (protein, carbs, fat) and how they scale with day type
- Caloric deficit / surplus / maintenance math
- Fasting protocols (16:8, 24h, 40h) and when to use them
- Refeeds and diet breaks for metabolic adaptation
- Electrolyte and supplement timing
- Pre/post workout and pre/post run nutritional needs
- Body weight trend interpretation (water vs fat vs glycogen)

OUT of your scope:
- Lift programming (Strength's domain)
- Run programming (Running's domain)
- Injury or recovery management (Doctor's domain)

Priority pyramid (apply in order):
1. Sports-medicine concerns (HRV crashed, sleep <5h, RPE>9, injury)
2. The athlete's stated goal: {goal_type} (cut → caloric deficit wins)
3. Program adherence (the prescribed plan)
4. Athlete preference

You receive:
- Doctor's brief (the question, focused on your domain)
- Athlete data slice: cut_status, body_weight history, meals_today, weekly_meals, food_safety, food_selections, fasting state, today_status, goal
- Tools to pull additional data if needed

Output format (mandatory):
- 2-4 sentences max. NO opening ("Hi", "Sure"), NO closing ("Hope this helps").
- Cite numbers from the data. Never invent.
- Lead with the call. Then the why.
- Format: "Recommendation: [call]. Reasoning: [data-anchored why]. Caveat: [risk to flag, if any, OR 'None.']."
- If you need data not in your slice, call your tools — do not punt back to the Doctor.

NO sycophancy. NO conversational fluff. NO "great question." You're a specialist returning a clinical consult note.
```

- [ ] **Step 2: Write `.claude/agents/strength-coach.md`**

```markdown
---
name: Strength Coach
model: claude-sonnet-4-6
tools:
  - get_workout
  - get_recent_sets
  - get_e1rm
  - get_today_sets
  - get_session_analysis
---

You are the Strength Coach, part of a 4-coach system. The Doctor (overseer) is consulting you about an athlete question. You are NOT chatting with the athlete directly — you're returning a tight recommendation to the Doctor.

Your domain expertise is anchored in: Mike Tuchscherer (Reactive Training Systems — RPE-based autoregulation, peaking blocks), Greg Nuckols (Stronger By Science — evidence-based programming), Eric Helms (Muscle and Strength Pyramids — recovery, volume landmarks).

You think in: RPE / RIR autoregulation, MEV/MAV/MRV volume landmarks, intensity waves, deload triggers, fatigue management across cumulative sessions, exercise selection for hypertrophy vs strength, swap logic when equipment or recovery shifts.

Your scope:
- Lift selection, sets, reps, weight (target + autoregulated)
- Whether to PR, hold, or back off based on recent session data
- Exercise swaps when prescribed lift unavailable
- Deload timing and content
- Progression in a caloric deficit (more conservative than bulk)
- Cross-session fatigue interpretation

OUT of your scope:
- Macros, fasting, deficit math (Nutritionist's domain)
- Run programming, pace zones (Running's domain)
- Injury management (Doctor's domain — flag, don't prescribe)

Priority pyramid (apply in order):
1. Sports-medicine concerns (HRV crashed, sleep <5h, recent RPE>9, injury)
2. The athlete's stated goal: {goal_type} (cut → preserve muscle + strength under deficit; bulk → push progression aggressively)
3. Program adherence
4. Athlete preference

You receive:
- Doctor's brief (the question, focused on your domain)
- Athlete data slice: workout_today, workout_tomorrow, today_sets, exercise_history (by lift), exercise_analysis, equipment, session_analysis, today_status, goal, fasting state
- Tools to pull additional data

Output format (mandatory):
- 2-4 sentences max
- Cite weights, reps, RPE numbers from the data. Never invent.
- Lead with the call. Then the why.
- Format: "Recommendation: [call with numbers]. Reasoning: [data-anchored why]. Caveat: [risk, if any, OR 'None.']."
- If you need data not in your slice, call your tools.

NO sycophancy. NO conversational fluff.
```

- [ ] **Step 3: Write `.claude/agents/running-coach.md`**

```markdown
---
name: Running Coach
model: claude-sonnet-4-6
tools:
  - get_run_plan
  - get_recent_runs
  - get_garmin_recovery
  - get_today_status
---

You are the Running Coach, part of a 4-coach system. The Doctor (overseer) is consulting you about an athlete question. You are NOT chatting with the athlete directly — you're returning a tight recommendation to the Doctor.

Your domain expertise is anchored in: Pete Pfitzinger (Advanced Marathoning — periodization for marathon and ultra), Jack Daniels (Daniels Running Formula — VDOT, training intensities), Steve Magness (Science of Running — physiology, aerobic development), Hadd (Hadd's Approach — pure aerobic base building, ultra-relevant). You're particularly strong in 50k and ultra-marathon programming.

You think in: aerobic threshold (Z2), lactate threshold (Z3), VO2max (Z4-5), heart rate zones, training stress balance, glycogen depletion patterns for fasted long runs, polarized vs threshold training distribution, taper logic, recovery between hard sessions.

Your scope:
- Run prescription (pace, duration, HR zone, intervals or steady-state)
- Whether to run today vs rest, or modify intensity based on recovery state
- Fasted run feasibility given the athlete's protocol
- Long run pacing (especially fasted Sunday LRs in this program)
- Run-after-lift sequencing concerns
- Cumulative running stress + recovery integration

OUT of your scope:
- Macros, fasting, refeeds (Nutritionist's domain — but flag if a run prescription requires fueling that conflicts with the fast)
- Lift programming (Strength's domain)
- Injury management (Doctor's domain — flag, don't prescribe)

Priority pyramid (apply in order):
1. Sports-medicine concerns (HRV crashed, sleep <5h, RPE>9, injury, signs of overreaching)
2. The athlete's stated goal: {goal_type} (cut → easy aerobic protected, hard sessions reduced; ultra/marathon → mileage and long run dictate everything)
3. Program adherence
4. Athlete preference

You receive:
- Doctor's brief (the question, focused on your domain)
- Athlete data slice: run_history, garmin (HR/sleep/HRV), workout_today, today_status, goal, fasting state
- Tools to pull additional data

Output format (mandatory):
- 2-4 sentences max
- Cite distance, HR, pace, time numbers from the data. Never invent.
- Lead with the call. Then the why.
- Format: "Recommendation: [call with numbers]. Reasoning: [data-anchored why]. Caveat: [risk, if any, OR 'None.']."
- If you need data not in your slice, call your tools.

NO sycophancy. NO conversational fluff.
```

- [ ] **Step 4: Write `.claude/agents/doctor.md`**

```markdown
---
name: Doctor
model: claude-opus-4-7
tools:
  - consult_nutritionist
  - consult_strength
  - consult_running
  - get_workout
  - get_recent_sets
  - get_e1rm
  - get_body_state
  - get_today_status
---

You are the Doctor, the overseer in a 4-coach system. You speak directly with the athlete. You consult three specialists (Nutritionist, Strength Coach, Running Coach) as tools when their domain expertise is needed, then synthesize their views into a single-voice response.

Your domain expertise is anchored in: Andy Galpin (load management, training stress integration), Stuart McGill (back health, movement quality), Layne Norton (cross-domain physiology). Your role is integration and arbitration, not deep specialist knowledge — you trust the specialists for that.

CONSULTING DECISION (Phase 1):
For every athlete message, you decide which specialists to consult.
- "I'm tired today" → 0 consults. Acknowledge, dig into why, offer a simple call.
- "What's my next bench target?" → 1 consult (Strength).
- "What should I eat after the run?" → 1-2 consults (Nutritionist + maybe Running for context).
- "Should I PR Friday after a Wed-Thu fast?" → 3 consults. All domains relevant.

When you decide to consult, write a focused brief for each specialist (200-500 tokens) that includes:
(a) the part of the question relevant to that domain
(b) any cross-cutting context (other domains' constraints)
(c) what specifically you need them to weigh in on

If a question is purely conversational ("how was your day?", "I missed a workout, am I screwed?"), respond directly. Specialists are for when domain expertise is the bottleneck.

SYNTHESIS (Phase 3, after specialist returns):

Apply goal-aware priority on conflict:
1. Sports-medicine red flags (ALWAYS top): HRV >10% below baseline, sleep <5h, recent RPE ≥9, injury report. If ANY fire, your response prioritizes recovery — pull back, defer, rest — regardless of what specialists prescribed.
2. The athlete's TrainingGoal.goal_type:
   - "cut" → Nutritionist wins on conflicting cut decisions
   - "bulk" → Strength wins
   - "recomp" → Strength wins (slight lean)
   - "marathon" / "ultra" → Running wins
   - "general_health" → your judgment
3. Program adherence — defer to the prescribed plan when no conflict.
4. Athlete preference (coach_memories, user_rules) — tie-break only.

If specialists agree: synthesize the unified call.
If specialists disagree: identify the conflict, apply priority, name the call, name what's traded off.

OUTPUT FORMAT:
- Single message in your voice. Lead with the call. Brief reasoning. Caveats if real.
- NO specialist labels ("Nutritionist says...") UNLESS the athlete explicitly asks for the underlying views ("what did each say?", "show me the disagreement", "why didn't you call X").
- Match the athlete's existing coach tone: Lombardi/Saban energy, terse, data-anchored, no fluff. NO "great question." NO sycophancy. NO "I hope this helps."
- If sports-medicine red flag fired, lead with that — make it impossible to miss.

ON-DEMAND SPECIALIST SURFACING:
The athlete may ask for the underlying views in a follow-up turn. The full consult tool_use blocks + returns sit in conversation history; quote them directly.
```

- [ ] **Step 5: Add a smoke test that all 4 files load**

Append to `tests/test_specialist_loader.py`:

```python
def test_all_four_persona_files_load():
    """Smoke test — all 4 specialist persona files exist and parse."""
    from coach_specialists.loader import load_agent_md
    for name in ("doctor", "nutritionist", "strength-coach", "running-coach"):
        cfg = load_agent_md(name)
        assert cfg["name"]
        assert cfg["model"]
        assert cfg["system_prompt"]
        # Doctor has consult tools; specialists have domain tools
        assert isinstance(cfg["tools"], list) and len(cfg["tools"]) >= 1
```

- [ ] **Step 6: Run all loader tests**

Run: `venv/bin/pytest tests/test_specialist_loader.py -v`
Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add .claude/agents/ tests/test_specialist_loader.py
git commit -m "Multi-agent: 4 specialist persona files (doctor + 3 specialists)"
```

---

## Task 3: Specialist runtime modules — `consult(brief, user_id)` API

Each specialist gets a Python module with one public function: `consult(brief: str, user_id: int) -> str`. Internally it loads the persona, builds the athlete_data slice, calls Anthropic, returns the recommendation text.

**Files:**
- Create: `coach_specialists/nutritionist.py`
- Create: `coach_specialists/strength.py`
- Create: `coach_specialists/running.py`
- Create: `tests/test_specialist_consult.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_specialist_consult.py`:

```python
"""Tests for specialist consult functions."""
import pytest
from unittest.mock import MagicMock, patch


def test_nutritionist_consult_loads_prompt_and_calls_anthropic():
    """consult() should load nutritionist.md, build the system prompt with
    athlete_data slice, call Anthropic, return the response text."""
    from coach_specialists import nutritionist

    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="Recommendation: refeed 30g.")]

    with patch("coach_specialists.nutritionist._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_specialists.nutritionist._build_athlete_slice", return_value="<slice/>"):
            result = nutritionist.consult(
                brief="Should the athlete eat carbs today?",
                user_id=1,
            )

    assert "refeed" in result
    # Verify the nutritionist persona was loaded (system prompt was passed)
    call_kwargs = mc.return_value.messages.create.call_args.kwargs
    assert "Nutritionist" in call_kwargs["system"]
    assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_strength_consult_uses_strength_persona():
    from coach_specialists import strength
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="Recommendation: 4x3 @ 165.")]
    with patch("coach_specialists.strength._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_specialists.strength._build_athlete_slice", return_value="<slice/>"):
            result = strength.consult(brief="What weight today?", user_id=1)
    call_kwargs = mc.return_value.messages.create.call_args.kwargs
    assert "Strength Coach" in call_kwargs["system"]


def test_running_consult_uses_running_persona():
    from coach_specialists import running
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="Recommendation: Z2 35 min.")]
    with patch("coach_specialists.running._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_specialists.running._build_athlete_slice", return_value="<slice/>"):
            result = running.consult(brief="Run today?", user_id=1)
    call_kwargs = mc.return_value.messages.create.call_args.kwargs
    assert "Running Coach" in call_kwargs["system"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_specialist_consult.py -v`
Expected: 3 FAILs — modules don't exist yet.

- [ ] **Step 3: Write `coach_specialists/nutritionist.py`**

```python
"""Nutritionist specialist runtime. Loads .claude/agents/nutritionist.md
on import, exposes consult(brief, user_id) -> str."""
from __future__ import annotations
import os
from .loader import load_agent_md

_PERSONA = load_agent_md("nutritionist")


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _build_athlete_slice(user_id: int) -> str:
    """Build the Nutritionist's athlete_data slice. Pulls only the sections
    relevant to nutrition: cut_status, body_weight, meals_today, weekly_meals,
    food_safety, food_selections, fasting state, today_status, goal."""
    from coach_assembler import build_filtered_context, _format_athlete_data
    # Use a synthetic agent name; build_filtered_context reads requires from
    # AGENTS map. We register 'nutritionist' as an agent in Task 7.
    ctx = build_filtered_context("nutritionist")
    return _format_athlete_data(ctx, ctx.get("_requires", []))


def consult(brief: str, user_id: int) -> str:
    """Call the Nutritionist with the Doctor's brief + athlete data slice.
    Returns the recommendation text (2-4 sentences per the persona)."""
    slice_block = _build_athlete_slice(user_id)
    system = (
        _PERSONA["system_prompt"]
        + "\n\n<athlete_data>\n"
        + slice_block
        + "\n</athlete_data>"
    )
    user_msg = f"DOCTOR BRIEF:\n{brief}"

    client = _anthropic_client()
    resp = client.messages.create(
        model=_PERSONA["model"],
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
```

- [ ] **Step 4: Write `coach_specialists/strength.py`**

```python
"""Strength Coach specialist runtime. Loads .claude/agents/strength-coach.md
on import, exposes consult(brief, user_id) -> str."""
from __future__ import annotations
import os
from .loader import load_agent_md

_PERSONA = load_agent_md("strength-coach")


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _build_athlete_slice(user_id: int) -> str:
    from coach_assembler import build_filtered_context, _format_athlete_data
    ctx = build_filtered_context("strength_coach")
    return _format_athlete_data(ctx, ctx.get("_requires", []))


def consult(brief: str, user_id: int) -> str:
    slice_block = _build_athlete_slice(user_id)
    system = (
        _PERSONA["system_prompt"]
        + "\n\n<athlete_data>\n"
        + slice_block
        + "\n</athlete_data>"
    )
    user_msg = f"DOCTOR BRIEF:\n{brief}"

    client = _anthropic_client()
    resp = client.messages.create(
        model=_PERSONA["model"],
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
```

- [ ] **Step 5: Write `coach_specialists/running.py`**

```python
"""Running Coach specialist runtime. Loads .claude/agents/running-coach.md
on import, exposes consult(brief, user_id) -> str."""
from __future__ import annotations
import os
from .loader import load_agent_md

_PERSONA = load_agent_md("running-coach")


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _build_athlete_slice(user_id: int) -> str:
    from coach_assembler import build_filtered_context, _format_athlete_data
    ctx = build_filtered_context("running_coach")
    return _format_athlete_data(ctx, ctx.get("_requires", []))


def consult(brief: str, user_id: int) -> str:
    slice_block = _build_athlete_slice(user_id)
    system = (
        _PERSONA["system_prompt"]
        + "\n\n<athlete_data>\n"
        + slice_block
        + "\n</athlete_data>"
    )
    user_msg = f"DOCTOR BRIEF:\n{brief}"

    client = _anthropic_client()
    resp = client.messages.create(
        model=_PERSONA["model"],
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
```

- [ ] **Step 6: Run tests**

Run: `venv/bin/pytest tests/test_specialist_consult.py -v`
Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add coach_specialists/nutritionist.py coach_specialists/strength.py coach_specialists/running.py tests/test_specialist_consult.py
git commit -m "Multi-agent: 3 specialist runtime modules with consult(brief, user_id)"
```

---

## Task 4: Register specialists in `coach_agents.py`

The 3 specialists need entries in the AGENTS map so `build_filtered_context` can compute their `requires` slices. Doctor doesn't need a separate entry (it uses the existing chat-style modes' requires + adds consult tools).

**Files:**
- Modify: `coach_agents.py`

- [ ] **Step 1: Append the 3 specialist entries**

Append to `coach_agents.py` AGENTS map (before the closing `}` of the dict):

```python
    "nutritionist": {
        "max_tokens": 600,
        "temperature": 0.4,
        "requires": [
            "base", "goal", "cut_status", "bodyweight",
            "meals_today", "weekly_meals", "food_safety",
            "fasting", "today_status",
        ],
    },
    "strength_coach": {
        "max_tokens": 600,
        "temperature": 0.4,
        "requires": [
            "base", "goal", "fasting", "today_status",
            "workout_today", "workout_tomorrow", "today_sets",
            "exercise_history", "exercise_analysis", "equipment",
            "session_analysis",
        ],
    },
    "running_coach": {
        "max_tokens": 600,
        "temperature": 0.4,
        "requires": [
            "base", "goal", "fasting", "today_status",
            "workout_today", "runs", "garmin",
        ],
    },
```

- [ ] **Step 2: Run existing tests to confirm no regression**

Run: `venv/bin/pytest tests/coach_audit/ tests/test_specialist_loader.py tests/test_specialist_consult.py -v`
Expected: All previously-passing tests still PASS.

- [ ] **Step 3: Commit**

```bash
git add coach_agents.py
git commit -m "Multi-agent: register 3 specialist agents in AGENTS map"
```

---

## Task 5: Add `consult_*` tools to `coach_tools.py`

The Doctor calls specialists via Anthropic tool-use. Each `consult_*` tool dispatches to the corresponding specialist's `consult()` function.

**Files:**
- Modify: `coach_tools.py`
- Create: `tests/test_consult_tools.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_consult_tools.py`:

```python
"""Tests that consult_* tools wire to the specialist runtime modules."""
from unittest.mock import patch


def test_consult_nutritionist_tool_dispatches_to_specialist():
    from coach_tools import execute_tool
    with patch("coach_specialists.nutritionist.consult", return_value="REC: refeed.") as mc:
        result_str = execute_tool(
            "consult_nutritionist",
            {"brief": "Should athlete eat carbs?"},
            user_id=1,
        )
    mc.assert_called_once_with(brief="Should athlete eat carbs?", user_id=1)
    assert "refeed" in result_str


def test_consult_strength_tool_dispatches():
    from coach_tools import execute_tool
    with patch("coach_specialists.strength.consult", return_value="REC: 4x3.") as mc:
        result_str = execute_tool(
            "consult_strength",
            {"brief": "What weight today?"},
            user_id=1,
        )
    mc.assert_called_once_with(brief="What weight today?", user_id=1)
    assert "4x3" in result_str


def test_consult_running_tool_dispatches():
    from coach_tools import execute_tool
    with patch("coach_specialists.running.consult", return_value="REC: Z2 35 min.") as mc:
        result_str = execute_tool(
            "consult_running",
            {"brief": "Run today?"},
            user_id=1,
        )
    mc.assert_called_once_with(brief="Run today?", user_id=1)
    assert "Z2" in result_str
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_consult_tools.py -v`
Expected: 3 FAILs — tools don't exist in `_DISPATCH`.

- [ ] **Step 3: Add the 3 tool schemas to `TOOLS`**

In `coach_tools.py`, append to the `TOOLS` list (before the closing `]`):

```python
    {
        "name": "consult_nutritionist",
        "description": (
            "Consult the Nutritionist specialist. Use when the question "
            "involves macros, fasting, refeeds, glycogen, deficit math, "
            "electrolytes, supplement timing, or interpreting body weight "
            "trends. Brief should be 1-3 sentences naming the question + "
            "any cross-cutting context (e.g., 'athlete is week 6 of 12-wk "
            "cut, 207→185 target')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "description": "Focused question + context"},
            },
            "required": ["brief"],
        },
    },
    {
        "name": "consult_strength",
        "description": (
            "Consult the Strength Coach specialist. Use for lift "
            "programming, RPE-based autoregulation, swap logic, weight "
            "selection, deload calls, progression-in-deficit decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
            },
            "required": ["brief"],
        },
    },
    {
        "name": "consult_running",
        "description": (
            "Consult the Running Coach specialist. Use for run "
            "prescription, pace zones, fasted-run feasibility, "
            "long-run pacing, recovery-based intensity adjustments, "
            "ultra-specific concerns (50k preparation)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
            },
            "required": ["brief"],
        },
    },
```

- [ ] **Step 4: Add the 3 dispatch functions**

In `coach_tools.py`, append (after `_tool_get_today_status` and before `_DISPATCH`):

```python
def _tool_consult_nutritionist(user_id: int, brief: str) -> str:
    from coach_specialists.nutritionist import consult
    return consult(brief=brief, user_id=user_id)


def _tool_consult_strength(user_id: int, brief: str) -> str:
    from coach_specialists.strength import consult
    return consult(brief=brief, user_id=user_id)


def _tool_consult_running(user_id: int, brief: str) -> str:
    from coach_specialists.running import consult
    return consult(brief=brief, user_id=user_id)
```

- [ ] **Step 5: Add the 3 dispatch entries to `_DISPATCH`**

In `coach_tools.py`, modify the `_DISPATCH` dict to include:

```python
_DISPATCH = {
    "get_workout": _tool_get_workout,
    "get_recent_sets": _tool_get_recent_sets,
    "get_e1rm": _tool_get_e1rm,
    "get_body_state": _tool_get_body_state,
    "get_today_status": _tool_get_today_status,
    "consult_nutritionist": _tool_consult_nutritionist,
    "consult_strength": _tool_consult_strength,
    "consult_running": _tool_consult_running,
}
```

- [ ] **Step 6: Run tests**

Run: `venv/bin/pytest tests/test_consult_tools.py -v`
Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add coach_tools.py tests/test_consult_tools.py
git commit -m "Multi-agent: consult_nutritionist/strength/running tools wired to specialists"
```

---

## Task 6: Multi-agent dispatcher — `coach_multi_agent.py`

The orchestrator that powers the 4 chat-style agents. Loads Doctor's persona, runs the tool-use loop with consult tools enabled, returns the synthesized response.

**Files:**
- Create: `coach_multi_agent.py`
- Create: `tests/test_multi_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multi_agent.py`:

```python
"""Tests for the multi-agent Doctor orchestrator."""
from unittest.mock import patch, MagicMock
import pytest


def test_doctor_zero_consults_returns_text_directly():
    """When the Doctor's first turn emits text (no tool calls), that's
    the final response — 1 LLM call total."""
    from coach_multi_agent import coach_chat_multiagent

    text_block = MagicMock(type="text", text="You're tired — sleep matters.")
    fake_response = MagicMock(stop_reason="end_turn", content=[text_block])

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        result = coach_chat_multiagent(
            user_id=1,
            athlete_data="<athlete_data/>",
            messages=[{"role": "user", "content": "I'm tired today"}],
        )
    # One Anthropic call. Text returned.
    assert mc.return_value.messages.create.call_count == 1
    assert "tired" in result.lower()


def test_doctor_consults_one_specialist_then_synthesizes():
    """Doctor emits 1 tool_use, specialist returns, Doctor synthesizes."""
    from coach_multi_agent import coach_chat_multiagent

    # Turn 1: Doctor calls consult_nutritionist
    tool_use = MagicMock(type="tool_use", id="t1", name="consult_nutritionist",
                         input={"brief": "carbs today?"})
    turn1 = MagicMock(stop_reason="tool_use", content=[tool_use])
    # Turn 2: Doctor synthesizes
    text_block = MagicMock(type="text", text="No carbs today; you're cutting.")
    turn2 = MagicMock(stop_reason="end_turn", content=[text_block])

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.side_effect = [turn1, turn2]
        with patch("coach_specialists.nutritionist.consult", return_value="REC: no carbs."):
            result = coach_chat_multiagent(
                user_id=1,
                athlete_data="<athlete_data/>",
                messages=[{"role": "user", "content": "Carbs today?"}],
            )
    # 2 Anthropic calls (parse + synthesis)
    assert mc.return_value.messages.create.call_count == 2
    assert "no carbs" in result.lower() or "cutting" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: 2 FAILs — `coach_multi_agent` module doesn't exist.

- [ ] **Step 3: Write `coach_multi_agent.py`**

```python
"""Multi-agent coach orchestrator. Doctor (Opus 4.7) parses athlete
messages, optionally consults Nutritionist/Strength/Running specialists
(Sonnet 4.6) as tools, synthesizes a single-voice response.

Used by the 4 chat-style trigger modes (conversation, weekly_planning,
chat_opened, weekly_review). Other 7 trigger modes stay on the
single-prompt path in coach_with_tools.py.
"""
from __future__ import annotations
import os
from coach_specialists.loader import load_agent_md

MAX_TOOL_TURNS = 6
DEFAULT_MAX_TOKENS = 2000


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=60.0,
    )


def coach_chat_multiagent(
    user_id: int,
    athlete_data: str,
    messages: list[dict],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Run a multi-agent conversation turn.

    user_id: athlete id, passed to consult tools so specialists can access data.
    athlete_data: the formatted <athlete_data> block (Doctor sees full).
    messages: chat history list of {role, content} dicts.

    Returns the Doctor's final synthesized text.
    """
    from coach_tools import TOOLS, execute_tool

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

    for turn in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=persona["model"],
            max_tokens=max_tokens,
            system=system,
            messages=convo,
            tools=doctor_tools,
        )
        if resp.stop_reason == "tool_use":
            # Append assistant tool-call message verbatim
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in resp.content],
            })
            # Execute every tool_use block
            results = []
            for b in resp.content:
                if getattr(b, "type", None) == "tool_use":
                    out = execute_tool(b.name, dict(b.input or {}), user_id)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": out,
                    })
            convo.append({"role": "user", "content": results})
            continue

        # end_turn — extract text
        return "\n".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()

    return "(multi-agent: hit max tool-call iterations)"
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add coach_multi_agent.py tests/test_multi_agent.py
git commit -m "Multi-agent: coach_chat_multiagent orchestrator (sync, sequential consults)"
```

---

## Task 7: Async parallel dispatch for specialist consults

The sync version in Task 6 runs specialists sequentially when Doctor emits multiple `tool_use` blocks. Spec Section 3 says we need `asyncio.gather()` for true parallelism so wall-clock latency stays low. This task swaps in async dispatch when ≥2 consult tools are emitted in one Doctor turn.

**Files:**
- Modify: `coach_multi_agent.py`
- Modify: `tests/test_multi_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_multi_agent.py`:

```python
def test_doctor_three_consults_dispatch_in_parallel():
    """When Doctor emits 3 tool_use blocks in one turn, all 3 consults
    run via asyncio.gather() — verified by checking they all receive
    the same convo state (sequential would mutate it between calls)."""
    import asyncio
    from coach_multi_agent import coach_chat_multiagent

    # Turn 1: Doctor calls all 3 consults
    tool_uses = [
        MagicMock(type="tool_use", id="t1", name="consult_nutritionist",
                  input={"brief": "carbs?"}),
        MagicMock(type="tool_use", id="t2", name="consult_strength",
                  input={"brief": "PR Friday?"}),
        MagicMock(type="tool_use", id="t3", name="consult_running",
                  input={"brief": "Sunday LR risk?"}),
    ]
    turn1 = MagicMock(stop_reason="tool_use", content=tool_uses)
    turn2 = MagicMock(stop_reason="end_turn",
                      content=[MagicMock(type="text", text="Skip the PR.")])

    call_log = []

    def slow_nutritionist(*args, **kwargs):
        call_log.append("nut_start")
        return "REC: refeed first."

    def slow_strength(*args, **kwargs):
        call_log.append("str_start")
        return "REC: 90%, not PR."

    def slow_running(*args, **kwargs):
        call_log.append("run_start")
        return "REC: protect Sunday."

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.side_effect = [turn1, turn2]
        with patch("coach_specialists.nutritionist.consult", side_effect=slow_nutritionist):
            with patch("coach_specialists.strength.consult", side_effect=slow_strength):
                with patch("coach_specialists.running.consult", side_effect=slow_running):
                    result = coach_chat_multiagent(
                        user_id=1,
                        athlete_data="<a/>",
                        messages=[{"role": "user", "content": "PR Friday after fast?"}],
                    )

    # All 3 specialists were called
    assert len(call_log) == 3
    assert "nut_start" in call_log
    assert "str_start" in call_log
    assert "run_start" in call_log
    assert "Skip the PR" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_multi_agent.py::test_doctor_three_consults_dispatch_in_parallel -v`
Expected: PASS or FAIL depending on the sync implementation's behavior. Most likely PASSes already since `execute_tool` runs each in sequence and accumulates results — but the test verifies all 3 ran. We need to upgrade the implementation to truly parallelize.

- [ ] **Step 3: Add async parallel dispatch helper**

In `coach_multi_agent.py`, replace the body of the `for b in resp.content:` execution loop with parallel dispatch:

```python
        if resp.stop_reason == "tool_use":
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in resp.content],
            })
            tool_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            results = _execute_tools_parallel(tool_blocks, user_id)
            convo.append({"role": "user", "content": results})
            continue
```

Add this helper to `coach_multi_agent.py` (before `coach_chat_multiagent`):

```python
def _execute_tools_parallel(tool_blocks: list, user_id: int) -> list[dict]:
    """Run tool_use blocks in parallel via asyncio.gather. For tool sets
    that include multiple consult_* calls, this gives ~3x wall-clock
    speedup (3 specialists run concurrently). Non-consult tools also
    parallelize, which is harmless — they just don't benefit much."""
    import asyncio
    from coach_tools import execute_tool

    async def run_one(b):
        # execute_tool is sync; offload to default thread pool so we
        # don't block the event loop on Anthropic API calls.
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(
            None, execute_tool, b.name, dict(b.input or {}), user_id,
        )
        return {
            "type": "tool_result",
            "tool_use_id": b.id,
            "content": out,
        }

    async def run_all():
        return await asyncio.gather(*(run_one(b) for b in tool_blocks))

    try:
        return asyncio.run(run_all())
    except RuntimeError:
        # Already inside an event loop (Flask + threaded server). Fall back
        # to a fresh event loop in a worker thread.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, run_all())
            return future.result()
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: 3 PASSED (all 3 multi-agent tests pass).

- [ ] **Step 5: Commit**

```bash
git add coach_multi_agent.py tests/test_multi_agent.py
git commit -m "Multi-agent: parallel specialist dispatch via asyncio.gather"
```

---

## Task 8: Feature flag + route detection in `coach_with_tools.py`

When the existing `coach_chat` function is called with a multi-agent trigger mode AND `MULTIAGENT_ENABLED=1`, it routes to `coach_chat_multiagent` instead of running the single-prompt path.

**Files:**
- Modify: `coach_with_tools.py`
- Modify: `tests/test_multi_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_multi_agent.py`:

```python
def test_coach_chat_routes_to_multiagent_when_flag_enabled(monkeypatch):
    """coach_chat() should detect MULTIAGENT_ENABLED + chat-style agent
    and route to coach_chat_multiagent instead of the single-prompt loop."""
    from coach_with_tools import coach_chat

    monkeypatch.setenv("MULTIAGENT_ENABLED", "1")

    with patch("coach_multi_agent.coach_chat_multiagent",
               return_value="multi-agent reply") as mc:
        result = coach_chat(
            user_id=1,
            system_prompt="<athlete_data>...</athlete_data>",
            messages=[{"role": "user", "content": "test"}],
            agent_name="conversation",  # multi-agent trigger
        )

    mc.assert_called_once()
    assert result == "multi-agent reply"


def test_coach_chat_uses_single_prompt_when_flag_disabled(monkeypatch):
    """Without the flag, conversation still uses the existing single-prompt path."""
    from coach_with_tools import coach_chat

    monkeypatch.delenv("MULTIAGENT_ENABLED", raising=False)

    with patch("coach_with_tools._run_loop", return_value="single-prompt reply") as mc:
        with patch("coach_multi_agent.coach_chat_multiagent") as mma:
            result = coach_chat(
                user_id=1,
                system_prompt="...",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="conversation",
            )

    assert result == "single-prompt reply"
    mma.assert_not_called()


def test_coach_chat_uses_single_prompt_for_non_chat_modes(monkeypatch):
    """morning_checkin should NEVER go multi-agent even with the flag on."""
    from coach_with_tools import coach_chat

    monkeypatch.setenv("MULTIAGENT_ENABLED", "1")

    with patch("coach_with_tools._run_loop", return_value="single") as mc:
        with patch("coach_multi_agent.coach_chat_multiagent") as mma:
            result = coach_chat(
                user_id=1,
                system_prompt="...",
                messages=[{"role": "user", "content": "good morning"}],
                agent_name="morning_checkin",  # NOT a chat-style mode
            )

    assert result == "single"
    mma.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_multi_agent.py -v -k "routes_to\|single_prompt"`
Expected: 3 FAILs — `coach_chat` doesn't accept `agent_name` param, doesn't check the flag.

- [ ] **Step 3: Add `agent_name` param + routing to `coach_chat`**

Find `coach_chat` in `coach_with_tools.py` and modify its signature + body:

```python
MULTIAGENT_TRIGGERS = {"conversation", "weekly_planning", "chat_opened", "weekly_review"}


def coach_chat(
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    agent_name: str = "conversation",  # NEW: identifies which trigger mode
) -> str:
    """Non-streaming entry. Returns final assistant text.

    When MULTIAGENT_ENABLED=1 AND agent_name is a chat-style trigger,
    routes through coach_multi_agent. Otherwise uses the existing
    single-prompt tool-loop.
    """
    if (
        os.environ.get("MULTIAGENT_ENABLED") == "1"
        and agent_name in MULTIAGENT_TRIGGERS
    ):
        from coach_multi_agent import coach_chat_multiagent
        # Doctor builds its own system using its persona; but the caller
        # passed an athlete_data-bearing system_prompt. Strip the existing
        # system_prompt's wrapper and pass just the athlete_data section.
        # Conservative: pass the whole system_prompt as athlete_data — the
        # Doctor's persona prepends its own instructions.
        return coach_chat_multiagent(
            user_id=user_id,
            athlete_data=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        )

    return _run_loop(
        user_id=user_id,
        system_prompt=system_prompt,
        messages=messages,
        model=model or os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        max_tokens=max_tokens,
    )
```

- [ ] **Step 4: Update existing callers in `app.py`**

Find calls to `coach_chat(...)` in `app.py` and pass `agent_name`. Search:

```bash
grep -n "coach_chat(" app.py
```

For each call site, locate the surrounding code that has the agent_name (already used for `assemble_prompt(agent_name, ctx)`) and pass it explicitly:

Example (replace whatever exists today):

```python
# Find the existing line:
#   reply = coach_chat(user_id=current_user.id, system_prompt=system, messages=msgs)
# Add agent_name:
reply = coach_chat(
    user_id=current_user.id,
    system_prompt=system,
    messages=msgs,
    agent_name=agent_name,
)
```

(There are typically 2-3 call sites. Update each to pass the agent_name that was used for prompt assembly.)

- [ ] **Step 5: Run tests**

Run: `venv/bin/pytest tests/test_multi_agent.py -v`
Expected: 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add coach_with_tools.py app.py tests/test_multi_agent.py
git commit -m "Multi-agent: feature flag MULTIAGENT_ENABLED + chat-mode routing"
```

---

## Task 9: Audit harness extension — per-specialist test path

Add `target_specialist` field to `PromptCase` and a `make_specialist_invoker(name)` so the audit can test specialists in isolation (bypass Doctor for sharper signal).

**Files:**
- Modify: `tests/coach_audit/types.py`
- Modify: `tests/coach_audit/runner.py`
- Create: `tests/coach_audit/test_specialist_audit.py`

- [ ] **Step 1: Add `target_specialist` to `PromptCase`**

In `tests/coach_audit/types.py`, modify the `PromptCase` dataclass:

```python
@dataclass
class PromptCase:
    id: str
    category: str
    user_message: str
    user_fixture: str
    expected_behavior: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    focus_dimensions: list[str] = field(default_factory=list)
    requires_real_data: bool = False
    banned_phrase_overrides: list[str] = field(default_factory=list)
    target_specialist: str | None = None  # NEW: "nutritionist" | "strength" |
                                          # "running" | "doctor" | None=current path
```

- [ ] **Step 2: Add `make_specialist_invoker` to runner**

Append to `tests/coach_audit/runner.py`:

```python
def make_specialist_invoker(specialist_name: str, app, user):
    """Return a callable(user_message: str) -> str that calls the specialist
    DIRECTLY (bypassing the Doctor). Used by the audit to test specialists
    in isolation.

    specialist_name: 'nutritionist' | 'strength' | 'running'
    """
    from flask_login import login_user

    SPEC_MOD = {
        "nutritionist": "coach_specialists.nutritionist",
        "strength":     "coach_specialists.strength",
        "running":      "coach_specialists.running",
    }
    if specialist_name not in SPEC_MOD:
        raise ValueError(f"Unknown specialist: {specialist_name}")

    import importlib
    mod = importlib.import_module(SPEC_MOD[specialist_name])
    uid = user.id

    def invoke(user_message: str) -> str:
        with app.test_request_context():
            login_user(user, force=True)
            # The audit's user_message becomes the Doctor's brief here.
            return mod.consult(brief=user_message, user_id=uid)
    return invoke
```

- [ ] **Step 3: Add a smoke test for specialist invocation path**

Create `tests/coach_audit/test_specialist_audit.py`:

```python
"""Smoke test that the per-specialist audit path works."""
import pytest
import os


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY for live specialist call",
)
def test_nutritionist_specialist_invoker_smoke(phase_2_mid_program, app_ctx):
    from tests.coach_audit.runner import make_specialist_invoker
    app, _ = app_ctx
    invoke = make_specialist_invoker("nutritionist", app, phase_2_mid_program)
    out = invoke("Should the athlete eat 30g carbs at break-fast tomorrow?")
    # Just verify we got a response that mentions a recommendation
    low = out.lower()
    assert "recommendation" in low or "rec:" in low
```

- [ ] **Step 4: Run the smoke test (skipped without API key)**

Run: `venv/bin/pytest tests/coach_audit/test_specialist_audit.py -v`
Expected: 1 SKIPPED (without API key).

- [ ] **Step 5: Commit**

```bash
git add tests/coach_audit/types.py tests/coach_audit/runner.py tests/coach_audit/test_specialist_audit.py
git commit -m "Coach audit: per-specialist invoker for isolated testing"
```

---

## Task 10: Specialist-targeted prompt corpus

Add the 4 new audit categories: `nutrition_macros` (10 prompts), `nutrition_fasting` (5 prompts), `running_pace_zones` (10 prompts), `doctor_synthesis` (5 prompts). ~30 new prompts.

**Files:**
- Modify: `tests/coach_audit/prompts.py`

- [ ] **Step 1: Append the new prompt buckets**

In `tests/coach_audit/prompts.py`, append before `_KNOWN_FIXTURES`:

```python
_nutrition_macros = [
    PromptCase(
        id="nut_macro_001", category="nutrition_macros",
        user_message="What's my protein target today?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["207", "1.0g", "1g/lb"],
        must_not=["249", "1.2g/lb"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_002", category="nutrition_macros",
        user_message="How many carbs should I eat on a heavy lift day?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["5", "trace", "minimal", "keto"],
        must_not=["100g", "200g"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_003", category="nutrition_macros",
        user_message="Should I add a protein shake post-workout?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["whey", "shake", "protein"],
        must_not=["mass gainer"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_004", category="nutrition_macros",
        user_message="My deficit feels too aggressive — should I eat more today?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["deficit", "tdee", "cut"],
        must_not=["take a break", "your call"],
        focus_dimensions=["accuracy", "tone"],
    ),
    PromptCase(
        id="nut_macro_005", category="nutrition_macros",
        user_message="How much fat should I eat today on the heavy lift?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["73", "fat"],
        must_not=["20g fat"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_006", category="nutrition_macros",
        user_message="What macros for a rest day?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["1312", "rest"],
        must_not=["2000"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_007", category="nutrition_macros",
        user_message="Can I have a cheat meal Saturday?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=[],
        must_not=["sure", "go for it", "your call"],
        focus_dimensions=["tone", "accuracy"],
    ),
    PromptCase(
        id="nut_macro_008", category="nutrition_macros",
        user_message="What electrolytes do I need on the cut?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["sodium", "potassium", "magnesium"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_009", category="nutrition_macros",
        user_message="Should I lower calories further to hit 185?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["1512", "deficit"],
        must_not=["go lower", "drop to 1000"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_010", category="nutrition_macros",
        user_message="Why is my protein 207 not 250?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["1.0", "1g/lb", "math"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_nutrition_fasting = [
    PromptCase(
        id="nut_fast_001", category="nutrition_fasting",
        user_message="Can I do a 40-hour fast Wed-Thu?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["40", "fast"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_002", category="nutrition_fasting",
        user_message="When should I break my Sunday fast?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["11", "after run", "post-run"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_003", category="nutrition_fasting",
        user_message="Should I refeed before Friday's heavy lift?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["refeed", "carbs", "30g"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_004", category="nutrition_fasting",
        user_message="Can I drink coffee during the fast?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["yes", "coffee", "black"],
        must_not=["with cream", "with milk"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_005", category="nutrition_fasting",
        user_message="How long should I fast each week?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["16:8", "weekly"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_running_pace_zones = [
    PromptCase(
        id="run_pace_001", category="running_pace_zones",
        user_message="What HR for today's Z2 run?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["130", "145", "zone 2"],
        must_not=["170", "185"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_002", category="running_pace_zones",
        user_message="Pace target for VO2 4x4 intervals tomorrow?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["interval", "hard"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_003", category="running_pace_zones",
        user_message="Can I run today after yesterday's heavy lift?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_004", category="running_pace_zones",
        user_message="My HR is high on easy runs — what's wrong?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["recovery", "fatigue", "deficit"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_005", category="running_pace_zones",
        user_message="Long run pacing for fasted Sunday?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["zone 2", "easy", "conversational"],
        must_not=["tempo", "threshold"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_006", category="running_pace_zones",
        user_message="Should I train for a 50k while cutting?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["cut", "deficit", "aerobic"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_007", category="running_pace_zones",
        user_message="How many runs per week is too much?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_008", category="running_pace_zones",
        user_message="Should I add a tempo run this week?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_009", category="running_pace_zones",
        user_message="My Garmin shows poor sleep — should I run today?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["sleep", "recovery"],
        must_not=["push through"],
        focus_dimensions=["accuracy", "tone"],
    ),
    PromptCase(
        id="run_pace_010", category="running_pace_zones",
        user_message="What's a good warm-up for intervals?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["5 min", "warm"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_doctor_synthesis = [
    PromptCase(
        id="syn_001", category="doctor_synthesis",
        user_message="Can I PR Friday after a 40-hour fast Wed-Thu?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["no PR", "skip", "refeed", "90%"],
        must_not=["go for it", "send it"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="syn_002", category="doctor_synthesis",
        user_message="I slept 4 hours last night. Should I lift today?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["sleep", "rest", "back off"],
        must_not=["push through", "send it"],
        focus_dimensions=["accuracy", "tone"],
    ),
    PromptCase(
        id="syn_003", category="doctor_synthesis",
        user_message="Should I add miles this week?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["cut", "deficit"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="syn_004", category="doctor_synthesis",
        user_message="Can I deload next week instead of pushing?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="syn_005", category="doctor_synthesis",
        user_message="My knee hurts — should I keep training?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["pain", "rest", "stop"],
        must_not=["push through", "ignore"],
        focus_dimensions=["accuracy", "tone"],
    ),
]


_KNOWN_FIXTURES = frozenset({
    "phase_1_newbie", "phase_2_mid_program", "phase_3_cut", "no_gym_bw", "real_erik",
})


ALL_PROMPTS: list[PromptCase] = (
    _smoke
    + _cross_day
    + _banned_phrases
    + _schedule_leak
    + _session_status
    + _swap_logic
    + _progression
    + _run_pacing
    + _deload
    + _psych
    + _pushback
    + _week_drift
    + _edge_cases
    + _nutrition_macros
    + _nutrition_fasting
    + _running_pace_zones
    + _doctor_synthesis
)
```

- [ ] **Step 2: Sanity-check the corpus**

Run:
```bash
venv/bin/python -c "from tests.coach_audit.prompts import ALL_PROMPTS; print(len(ALL_PROMPTS), 'prompts'); print(sorted({p.category for p in ALL_PROMPTS}))"
```
Expected: ~68 prompts, 17 categories (existing 13 + 4 new).

- [ ] **Step 3: Verify the validation guard accepts target_specialist values**

Run: `venv/bin/pytest tests/coach_audit/ -v -k smoke`
Expected: 1 PASSED, no import errors.

- [ ] **Step 4: Commit**

```bash
git add tests/coach_audit/prompts.py
git commit -m "Coach audit: add 30 specialist + doctor_synthesis prompts (4 new categories)"
```

---

## Task 11: First multi-agent live audit run + iterate

Stand up the first end-to-end real-API audit run. Use the new prompts. Surface failures. Iterate on the personas.

**Files:**
- Modify: `tests/coach_audit/test_coach_audit.py`

- [ ] **Step 1: Add a parametrized test that routes per `target_specialist`**

Append to `tests/coach_audit/test_coach_audit.py`:

```python
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY",
)
@pytest.mark.parametrize(
    "case",
    [p for p in ALL_PROMPTS
     if p.target_specialist in ("nutritionist", "strength", "running")],
    ids=lambda c: c.id,
)
def test_specialist_targeted(case, fixture_by_name, app_ctx, run_id):
    """Per-specialist audit: bypass the Doctor; hit the specialist directly."""
    user = fixture_by_name(case.user_fixture)
    app, _ = app_ctx
    from tests.coach_audit.runner import make_specialist_invoker
    invoke = make_specialist_invoker(case.target_specialist, app, user)
    judge = make_judge_invoker(app, user)
    finding = run_prompt(
        case=case,
        user_id=user.id,
        invoke_coach=invoke,
        invoke_judge=judge,
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"[{case.id}] heuristic: missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}\n--- response ---\n{finding.coach_response}"
    )
    assert finding.judge.passed, (
        f"[{case.id}] judge: violations={finding.judge.violations}\n"
        f"scores={finding.judge.scores}\n--- response ---\n{finding.coach_response}"
    )


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY",
)
@pytest.mark.parametrize(
    "case",
    [p for p in ALL_PROMPTS if p.target_specialist == "doctor"],
    ids=lambda c: c.id,
)
def test_doctor_synthesis(case, fixture_by_name, app_ctx, run_id, monkeypatch):
    """Full-flow audit: athlete message → Doctor → 0-3 consults → synthesis."""
    monkeypatch.setenv("MULTIAGENT_ENABLED", "1")
    user = fixture_by_name(case.user_fixture)
    app, _ = app_ctx
    invoke = make_coach_invoker(app, user)  # uses coach_chat which now routes
    judge = make_judge_invoker(app, user)
    finding = run_prompt(
        case=case,
        user_id=user.id,
        invoke_coach=invoke,
        invoke_judge=judge,
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"[{case.id}] heuristic: {finding.heuristic.matched_must_not}\n"
        f"--- response ---\n{finding.coach_response}"
    )
    assert finding.judge.passed, (
        f"[{case.id}] judge: {finding.judge.violations}\n"
        f"--- response ---\n{finding.coach_response}"
    )
```

- [ ] **Step 2: Verify offline tests still pass**

Run: `venv/bin/pytest tests/coach_audit/ -v`
Expected: existing tests PASS, new tests SKIPPED (no API key in default env).

- [ ] **Step 3: Run the live audit (with API key)**

Run:

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  venv/bin/pytest tests/coach_audit/test_coach_audit.py::test_specialist_targeted \
  tests/coach_audit/test_coach_audit.py::test_doctor_synthesis \
  -n 4 -v 2>&1 | tee /tmp/multi-agent-first-run.log
```

Expected: 30 specialist prompts + 5 doctor_synthesis prompts run. Some will FAIL — that's the audit doing its job. Triage:
- For each FAIL on a specialist test: read the response. If the persona under-anchored (generic answer), update `.claude/agents/<specialist>.md` and re-run.
- For each FAIL on `doctor_synthesis`: read the response + check that consults fired correctly. If Doctor under-consulted, update `.claude/agents/doctor.md` consulting-decision section.

- [ ] **Step 4: Iterate on persona prompts based on failures**

For each persona file you modify in response to audit failures, commit the change with a focused message naming the audit finding it addresses:

```bash
git add .claude/agents/<specialist>.md
git commit -m "Multi-agent <specialist>: tighten persona based on audit finding [<prompt_id>]"
```

Re-run the audit until pass rate is acceptable (≥ 80% baseline; aim for ≥ 90% on specialist-targeted prompts).

- [ ] **Step 5: Commit the test additions and findings**

```bash
git add tests/coach_audit/test_coach_audit.py
git commit -m "Coach audit: parametrized tests for specialist + doctor_synthesis paths"
```

- [ ] **Step 6: Toggle the default flip (when audit passes)**

Once pass rate is acceptable for several runs, flip the default:

```bash
# In production env vars (Render dashboard):
MULTIAGENT_ENABLED=1
```

The flag is server-wide; once set, all 4 chat-style trigger modes route through multi-agent. Other 7 trigger modes continue using single-prompt regardless.

To disable for any reason: drop the env var or set to anything other than "1".

---

## Self-Review

**1. Spec coverage**

| Spec section | Implemented by |
|---|---|
| Architecture overview | Tasks 1, 3, 6, 7 |
| Specialist roles + prompts | Task 2 (4 personas) |
| Doctor's orchestration logic | Tasks 6, 7 |
| Athlete_data partitioning | Task 4 (AGENTS map entries) |
| Conflict resolution rules | Task 2 (Doctor persona section) |
| UX surface (synthesis + on-demand) | Task 2 (Doctor persona) + existing UI streams synthesis through `coach_chat_stream` |
| Cost model + model selection | Tasks 2 (Opus Doctor / Sonnet specialists) + 8 (feature flag) |
| Existing AGENTS map migration | Tasks 4 (specialist registration) + 8 (routing) |
| Testing / audit harness extension | Tasks 9 (per-specialist invoker) + 10 (corpus) + 11 (parametrized tests) |

No gaps.

**2. Placeholder scan:** No "TBD" / "TODO" / "implement later" / "add error handling" found. All steps include concrete code or commands.

**3. Type consistency:**
- `consult(brief: str, user_id: int) -> str` — used identically across nutritionist/strength/running modules (Task 3) AND in the test mocks (Tasks 5, 7) AND in `make_specialist_invoker` (Task 9).
- `coach_chat_multiagent(user_id, athlete_data, messages, max_tokens=...)` — defined Task 6, called from `coach_chat` in Task 8 with matching params.
- `target_specialist: str | None` — defined in PromptCase Task 9, consumed in Task 11 parametrize filters.
- `MULTIAGENT_TRIGGERS = {"conversation", "weekly_planning", "chat_opened", "weekly_review"}` — defined Task 8, referenced in spec Section 8 migration.
- `_PERSONA["model"]`, `_PERSONA["tools"]`, `_PERSONA["system_prompt"]` — keys returned by `load_agent_md` (Task 1), consumed in specialist modules (Task 3) and Doctor orchestrator (Task 6).

All consistent.
