# Coach Audit & Regression Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a parametrized pytest harness that runs 100+ prompts through the coach (`coach_chat` from `coach_with_tools.py`), evaluates each response with heuristics + Opus 4.7 LLM-as-judge, persists findings, and emits a ranked-failure markdown report. Same harness doubles as a permanent regression suite gated by `--audit-mode=full` for the real-Erik fixture.

**Architecture:** Subpackage `tests/coach_audit/` with focused modules: `types.py` (dataclasses), `users.py` (synthetic + real fixtures), `heuristics.py` (string/regex checks), `judge.py` (Opus call), `runner.py` (per-prompt orchestration), `report.py` (aggregation + clustering), `prompts.py` (corpus). Top-level `tests/test_coach_audit.py` parametrizes pytest over the corpus. Findings written to `tests/coach_audit/findings/<run_id>/<prompt_id>.json`; reports to `tests/coach_audit/reports/<run_id>.md`. Synthetic fixtures bind to a sqlite DB via `DATABASE_URL` env override (already done by `tests/conftest.py`).

**Tech Stack:** pytest, pytest-xdist, anthropic SDK, SQLAlchemy, dataclasses, json. Reuses existing `coach_chat`, `assemble_prompt`, `build_filtered_context` from production code unmodified.

**Spec:** `docs/superpowers/specs/2026-05-01-coach-audit-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `tests/coach_audit/__init__.py` | Package marker |
| `tests/coach_audit/types.py` | `PromptCase`, `JudgeResult`, `Finding` dataclasses |
| `tests/coach_audit/heuristics.py` | `check_heuristics(response, case)` — must/must_not/banned phrases |
| `tests/coach_audit/judge.py` | `judge_response(case, response, archetype_desc)` — calls Opus 4.7, returns `JudgeResult` |
| `tests/coach_audit/users.py` | Synthetic user factories (4 archetypes) + `make_real_erik` |
| `tests/coach_audit/runner.py` | `run_prompt(case, fixtures, run_id)` — orchestrates coach call → heuristic → judge → save |
| `tests/coach_audit/report.py` | `build_report(run_id)` — aggregates findings, clusters patterns, writes markdown |
| `tests/coach_audit/prompts.py` | 36-60 `PromptCase` instances across 12 categories |
| `tests/coach_audit/conftest.py` | pytest fixtures (synthetic users, run_id) + CLI options |
| `tests/test_coach_audit.py` | Top-level parametrized test that calls `runner.run_prompt` per case |

---

## Task 1: Scaffold package + types + smoke test

Stand up the directory layout and dataclasses, prove the harness can load and run a single trivial prompt with a stubbed coach. No real LLM calls yet.

**Files:**
- Create: `tests/coach_audit/__init__.py`
- Create: `tests/coach_audit/types.py`
- Create: `tests/coach_audit/heuristics.py`
- Create: `tests/coach_audit/runner.py`
- Create: `tests/coach_audit/conftest.py`
- Create: `tests/coach_audit/prompts.py`
- Create: `tests/test_coach_audit.py`

- [ ] **Step 1: Create empty package marker**

```bash
mkdir -p tests/coach_audit
touch tests/coach_audit/__init__.py
```

- [ ] **Step 2: Write `tests/coach_audit/types.py`**

```python
"""Dataclasses shared across the audit harness."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class PromptCase:
    id: str
    category: str
    user_message: str
    user_fixture: str          # one of: phase_1_newbie, phase_2_mid_program,
                                #         phase_3_cut, no_gym_bw, real_erik
    expected_behavior: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    focus_dimensions: list[str] = field(default_factory=list)
    requires_real_data: bool = False


@dataclass
class HeuristicResult:
    passed: bool
    missing_expected: list[str] = field(default_factory=list)
    matched_must_not: list[str] = field(default_factory=list)
    matched_banned: list[str] = field(default_factory=list)


@dataclass
class JudgeResult:
    passed: bool
    scores: dict                    # {accuracy, tone, no_hallucination, follows_must_not}
    violations: list[str] = field(default_factory=list)
    evidence: str = ""


@dataclass
class Finding:
    prompt_id: str
    category: str
    user_message: str
    coach_response: str
    heuristic: HeuristicResult
    judge: Optional[JudgeResult]
    timestamp_iso: str
    fixture: str

    def to_dict(self):
        return asdict(self)
```

- [ ] **Step 3: Write `tests/coach_audit/heuristics.py` (banned-phrase + must/must_not)**

```python
"""Fast string/regex checks. No LLM calls."""
from __future__ import annotations
import re
from .types import HeuristicResult, PromptCase


# Phrases the coach must NEVER emit. Maintained reactively as we find slips.
BANNED_PHRASES: list[str] = [
    "what's on your mind",
    "let's get after it",
    "speak.",
    "great work",
    "done. tomorrow:",
    "you've got this",
    "crushing it",
    "keep grinding",
]


def _norm(s: str) -> str:
    """Lowercase + replace × with x so '4×3' and '4x3' compare equal."""
    return s.lower().replace("×", "x").replace("×", "x")


def _has(haystack_norm: str, needle: str) -> bool:
    n = _norm(needle)
    if n.startswith("/") and n.endswith("/") and len(n) > 2:
        return re.search(n[1:-1], haystack_norm) is not None
    return n in haystack_norm


def check_heuristics(response: str, case: PromptCase) -> HeuristicResult:
    norm = _norm(response)
    missing = [s for s in case.expected_behavior if not _has(norm, s)]
    bad = [s for s in case.must_not if _has(norm, s)]
    banned = [p for p in BANNED_PHRASES if p in norm]
    passed = not missing and not bad and not banned
    return HeuristicResult(
        passed=passed,
        missing_expected=missing,
        matched_must_not=bad,
        matched_banned=banned,
    )
```

- [ ] **Step 4: Write `tests/coach_audit/runner.py` (heuristic-only path; judge stubbed)**

```python
"""Per-prompt orchestration. Coach call + heuristic + judge + persist."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .types import PromptCase, Finding, HeuristicResult, JudgeResult
from .heuristics import check_heuristics


FINDINGS_ROOT = Path(__file__).parent / "findings"


def _findings_dir(run_id: str) -> Path:
    p = FINDINGS_ROOT / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_prompt(
    *,
    case: PromptCase,
    user_id: int,
    invoke_coach,                    # callable(user_message: str) -> str
    invoke_judge=None,               # callable(case, response) -> JudgeResult | None
    run_id: str,
) -> Finding:
    response = invoke_coach(case.user_message)
    heuristic = check_heuristics(response, case)
    judge = invoke_judge(case, response) if invoke_judge else None

    finding = Finding(
        prompt_id=case.id,
        category=case.category,
        user_message=case.user_message,
        coach_response=response,
        heuristic=heuristic,
        judge=judge,
        timestamp_iso=datetime.now(timezone.utc).isoformat(),
        fixture=case.user_fixture,
    )
    out = _findings_dir(run_id) / f"{case.id}.json"
    out.write_text(json.dumps(finding.to_dict(), default=str, indent=2))
    return finding
```

- [ ] **Step 5: Write `tests/coach_audit/prompts.py` with one smoke-test case**

```python
"""Prompt corpus. Add cases freely — harness loops over `ALL_PROMPTS`."""
from .types import PromptCase

ALL_PROMPTS: list[PromptCase] = [
    PromptCase(
        id="smoke_001",
        category="smoke",
        user_message="ping",
        user_fixture="phase_2_mid_program",
        expected_behavior=["pong"],
        must_not=["ERROR"],
        focus_dimensions=["accuracy"],
    ),
]
```

- [ ] **Step 6: Write `tests/coach_audit/conftest.py` (run_id fixture + CLI flag stubs)**

```python
"""Audit-specific pytest fixtures."""
from __future__ import annotations
import pytest
from datetime import datetime


def pytest_addoption(parser):
    parser.addoption(
        "--audit-mode",
        action="store",
        default="synthetic",
        choices=["synthetic", "full"],
        help="synthetic = synthetic users only (CI safe). full = include real-Erik fixture.",
    )


@pytest.fixture(scope="session")
def run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


@pytest.fixture(scope="session")
def audit_mode(request) -> str:
    return request.config.getoption("--audit-mode")
```

- [ ] **Step 7: Write `tests/test_coach_audit.py` (smoke test, no real coach)**

```python
"""Top-level audit suite. Parametrized over `ALL_PROMPTS`."""
import pytest
from tests.coach_audit.prompts import ALL_PROMPTS
from tests.coach_audit.runner import run_prompt


@pytest.mark.parametrize("case", [p for p in ALL_PROMPTS if p.category == "smoke"],
                         ids=lambda c: c.id)
def test_smoke(case, run_id):
    """Stub coach echoes 'pong' — proves harness wiring works end-to-end."""
    finding = run_prompt(
        case=case,
        user_id=0,
        invoke_coach=lambda msg: "pong",
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"heuristic failed: missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}"
    )
```

- [ ] **Step 8: Run smoke test**

Run: `pytest tests/test_coach_audit.py -v`
Expected: 1 passed. A finding JSON appears under `tests/coach_audit/findings/<timestamp>/smoke_001.json`.

- [ ] **Step 9: Commit scaffold**

```bash
git add tests/coach_audit/ tests/test_coach_audit.py
git commit -m "Coach audit harness: scaffold + smoke test"
```

---

## Task 2: Synthetic user fixture — phase_2_mid_program

Build the most realistic archetype first (week 6, full SetLog history, gym, cutting). This unlocks every category that needs real data. Validate it by querying the coach assembler context-builder against the seeded user.

**Files:**
- Create: `tests/coach_audit/users.py`
- Modify: `tests/coach_audit/conftest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_coach_audit.py`:

```python
def test_phase_2_fixture_seeds_setlog_history(phase_2_mid_program):
    """Fixture should create a user with at least 3 weeks of SetLog rows."""
    from models import SetLog
    user = phase_2_mid_program
    rows = SetLog.query.filter_by(user_id=user.id, done=True).all()
    assert len(rows) >= 30, f"expected ≥30 SetLog rows, got {len(rows)}"
    weeks = {r.week for r in rows}
    assert weeks >= {3, 4, 5}, f"expected weeks 3-5 in history, got {weeks}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_audit.py::test_phase_2_fixture_seeds_setlog_history -v`
Expected: FAIL — fixture `phase_2_mid_program` not found.

- [ ] **Step 3: Implement `users.py` with `phase_2_mid_program` factory**

```python
"""Synthetic user fixtures + real-Erik fixture.

Every fixture returns a freshly-seeded `User` row. Test DB is sqlite under
`/tmp` (set by `tests/conftest.py`).
"""
from __future__ import annotations
import itertools
from datetime import date, timedelta
from typing import Optional


_SEQ = itertools.count(1)


def _next_email(prefix: str) -> str:
    return f"{prefix}-{next(_SEQ)}@audit.local"


def make_phase_2_mid_program():
    """Week 6, gym, full barbell access, 5 weeks of progressive SetLog history,
    currently cutting (-0.5 lb/wk trend over 4 BodyWeight rows)."""
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState,
        SetLog, BodyWeight, TrainingGoal,
    )

    u = User(email=_next_email("p2"), password_hash="x")
    db.session.add(u); db.session.commit()

    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=[
            "barbell", "dumbbells", "lat_pulldown", "cable_machine",
            "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
            "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
            "dip_station", "ab_machine", "smith_machine",
        ],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=35),
        current_week=6,
    ))
    db.session.add(TrainingGoal(
        user_id=u.id,
        goal_type="cut",
        target_weight=180.0,
        daily_calories=2200,
    ))
    db.session.commit()

    # 5 weeks × 3 lifts × 4 sets of progressive SetLog = 60 rows
    progression = {
        "Barbell Front Squat": [(135, 5), (145, 5), (155, 4), (165, 3), (170, 3)],
        "Barbell Bench Press": [(135, 6), (145, 5), (150, 5), (155, 4), (160, 4)],
        "Barbell Row":          [(115, 8), (125, 8), (135, 8), (140, 8), (145, 7)],
    }
    base_logged = date.today() - timedelta(days=34)
    for week_idx, (lift, week_progression) in enumerate(progression.items()):
        pass
    # Iterate weeks 1..5, day_idx fixed per lift (Mon, Tue, Thu) for simplicity
    LIFT_DAY = {
        "Barbell Front Squat": 0,
        "Barbell Bench Press": 1,
        "Barbell Row":         3,
    }
    for week in range(1, 6):
        days_offset = (week - 1) * 7
        for lift, sets in progression.items():
            weight, reps = sets[week - 1]
            day_idx = LIFT_DAY[lift]
            log_date = base_logged + timedelta(days=days_offset + day_idx)
            for set_no in range(1, 5):
                db.session.add(SetLog(
                    user_id=u.id,
                    week=week,
                    day_idx=day_idx,
                    exercise_name=lift,
                    set_number=set_no,
                    weight=weight,
                    reps=reps,
                    done=True,
                    logged_date=log_date,
                ))

    # 4 weeks of body weight, gentle cut
    for d_back, lbs in [(28, 188.0), (21, 187.4), (14, 186.5), (7, 186.0)]:
        db.session.add(BodyWeight(
            user_id=u.id,
            log_date=date.today() - timedelta(days=d_back),
            weight_lbs=lbs,
        ))

    db.session.commit()
    return u
```

- [ ] **Step 4: Wire the fixture into `conftest.py`**

Append to `tests/coach_audit/conftest.py`:

```python
@pytest.fixture(scope="function")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db
        db.session.rollback()


@pytest.fixture(scope="function")
def phase_2_mid_program(app_ctx):
    from tests.coach_audit.users import make_phase_2_mid_program
    return make_phase_2_mid_program()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_coach_audit.py::test_phase_2_fixture_seeds_setlog_history -v`
Expected: PASS — 60 SetLog rows seeded across weeks 1-5.

- [ ] **Step 6: Commit**

```bash
git add tests/coach_audit/users.py tests/coach_audit/conftest.py tests/test_coach_audit.py
git commit -m "Coach audit: phase_2_mid_program synthetic user fixture"
```

---

## Task 3: Wire real coach invocation through runner

Replace the stub `lambda msg: "pong"` with an actual `coach_chat` call against the seeded synthetic user. Heuristic-only evaluation (judge still off). One non-trivial prompt to prove the pipeline.

**Files:**
- Modify: `tests/coach_audit/runner.py`
- Modify: `tests/coach_audit/prompts.py`
- Modify: `tests/test_coach_audit.py`

- [ ] **Step 1: Add a coach-invocation helper to `runner.py`**

Append to `tests/coach_audit/runner.py`:

```python
def make_coach_invoker(app, user, agent_name: str = "conversation"):
    """Return a callable(user_message: str) -> str that runs the production
    coach pipeline against this user's seeded data.

    Uses `assemble_prompt` (full system prompt with athlete data block + full
    week injection) and `coach_chat` (tool-using loop)."""
    from coach_assembler import build_filtered_context, assemble_prompt
    from coach_with_tools import coach_chat
    from flask_login import login_user

    def invoke(user_message: str) -> str:
        with app.test_request_context():
            login_user(user, force=True)
            ctx = build_filtered_context(agent_name)
            system_prompt = assemble_prompt(agent_name, ctx)
            return coach_chat(
                user_id=user.id,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
    return invoke
```

- [ ] **Step 2: Add a real prompt to `prompts.py`**

Append to `ALL_PROMPTS` in `tests/coach_audit/prompts.py`:

```python
    PromptCase(
        id="cross_day_001",
        category="cross_day_hallucination",
        user_message="What lift is on Monday this week and what's the scheme?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["front squat", "4x3"],
        must_not=["back squat 4x5", "back squat 5x5"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
```

- [ ] **Step 3: Write the test that drives a real coach call**

Append to `tests/test_coach_audit.py`:

```python
import os


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY for live coach call",
)
@pytest.mark.parametrize(
    "case",
    [p for p in ALL_PROMPTS if p.id == "cross_day_001"],
    ids=lambda c: c.id,
)
def test_real_coach_heuristic_only(case, phase_2_mid_program, app_ctx, run_id):
    app, _ = app_ctx
    invoke = make_coach_invoker(app, phase_2_mid_program)
    finding = run_prompt(
        case=case,
        user_id=phase_2_mid_program.id,
        invoke_coach=invoke,
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}\n"
        f"--- response ---\n{finding.coach_response}"
    )
```

Update the import at top of `tests/test_coach_audit.py`:

```python
from tests.coach_audit.runner import run_prompt, make_coach_invoker
```

- [ ] **Step 4: Run test against live API**

Run: `ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY pytest tests/test_coach_audit.py::test_real_coach_heuristic_only -v -s`
Expected: PASS — coach response contains "front squat" and "4x3", does not contain "back squat 4x5". A finding JSON gets written.

If it FAILS: that is itself a finding — the harness has surfaced a real bug. Capture the response, add it to a `BUGS.md` log, then either (a) loosen the prompt expectations, or (b) leave the failure visible so the audit catches it.

- [ ] **Step 5: Commit**

```bash
git add tests/coach_audit/runner.py tests/coach_audit/prompts.py tests/test_coach_audit.py
git commit -m "Coach audit: real coach invocation through runner with heuristic check"
```

---

## Task 4: Opus 4.7 judge

Add the second evaluation stage. Judge sees user message + coach response + expected/must-not lists + archetype description; returns structured JSON with 4 dimension scores + violations list.

**Files:**
- Create: `tests/coach_audit/judge.py`
- Modify: `tests/coach_audit/runner.py`
- Modify: `tests/test_coach_audit.py`

- [ ] **Step 1: Write `tests/coach_audit/judge.py`**

```python
"""Opus 4.7 LLM-as-judge."""
from __future__ import annotations
import json
import os
import re
from .types import PromptCase, JudgeResult


JUDGE_MODEL = "claude-opus-4-7"
MAX_TOKENS = 800

JUDGE_SYSTEM = """You are an evaluator for a strength coach AI.

You will be shown:
1. The athlete's archetype (what their program looks like — this is your ground truth).
2. The athlete's question to the coach.
3. The coach's response.
4. Expected behaviors the response should exhibit.
5. Must-not phrases or claims that should be absent.
6. Focus dimensions to weight more heavily in your verdict.

Score the response on 4 dimensions, each 0-10:
- accuracy: Did the coach cite correct facts about the athlete's program/data?
- tone: Direct, factual, no cheerleading. Lombardi/Saban energy. No "great work", "let's get after it", "what's on your mind", "speak.", "done. tomorrow:".
- no_hallucination: Did the coach invent any workout, weight, or set count not implied by the archetype?
- follows_must_not: Did the response avoid every item in the must_not list?

`pass` is true iff every focus_dimension scores ≥ 7 AND no must_not item was matched.

Be lenient on phrasing variation; strict on factual claims and tone violations.

Respond with a single JSON object only — no preamble, no code fence.
{
  "pass": <bool>,
  "scores": {"accuracy": <int>, "tone": <int>, "no_hallucination": <int>, "follows_must_not": <int>},
  "violations": [<short strings describing problems>],
  "evidence": "<quoted snippets from response that justify your scores>"
}
"""


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _extract_json(text: str) -> dict:
    """Extract first JSON object from a response, tolerating accidental prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    raw = m.group(0) if m else text
    return json.loads(raw)


def judge_response(case: PromptCase, response: str, archetype_desc: str) -> JudgeResult:
    user_block = f"""ARCHETYPE:
{archetype_desc}

USER MESSAGE:
{case.user_message}

COACH RESPONSE:
{response}

EXPECTED BEHAVIOR (the response should reflect these):
{json.dumps(case.expected_behavior)}

MUST_NOT (the response must avoid these):
{json.dumps(case.must_not)}

FOCUS DIMENSIONS (weight these more heavily):
{json.dumps(case.focus_dimensions)}
"""
    client = _client()
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=MAX_TOKENS,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_block}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        data = _extract_json(text)
    except Exception as e:
        return JudgeResult(
            passed=False,
            scores={},
            violations=[f"judge JSON parse error: {e}"],
            evidence=text[:500],
        )
    return JudgeResult(
        passed=bool(data.get("pass", False)),
        scores=data.get("scores", {}),
        violations=list(data.get("violations") or []),
        evidence=str(data.get("evidence") or ""),
    )
```

- [ ] **Step 2: Add archetype descriptions to `users.py`**

Append to `tests/coach_audit/users.py`:

```python
ARCHETYPE_DESCRIPTIONS: dict[str, str] = {
    "phase_2_mid_program": (
        "Week 6 of a 12-week program. Phase 2 (weeks 5-8). "
        "Monday: Lower POWER — Front Squat 4x3 (heavy, low rep). "
        "Tuesday: Upper PRESS — DB Bench Press, with secondary work. "
        "Wednesday: Shoulder Volume + tempo run. "
        "Thursday: Upper PULL — Weighted Pull-Up + Barbell Row. "
        "Friday: HEAVY Lower — Back Squat 4x5. "
        "Saturday: Full Body, lighter. Sunday: Long fasted run, rest from lifting. "
        "Currently cutting at ~-0.5 lb/week. Has full gym access."
    ),
    "phase_1_newbie": (
        "Week 2. Just onboarded — minimal SetLog history. Phase 1 (weeks 1-4) "
        "establishes movement competency at moderate weights. Coach must use the "
        "lifting_agent to set starting weights, NOT extrapolate from non-existent history."
    ),
    "phase_3_cut": (
        "Week 9. Phase 3 (weeks 9-12). Hit a progression plateau on bench press "
        "(stuck at 165 for 3+ weeks). Ahead on weight-loss target. Coach should "
        "address plateau with deload or accessory shift, not push for PR."
    ),
    "no_gym_bw": (
        "Week 3. No gym, bodyweight + kettlebells only. Coach MUST NOT prescribe "
        "barbell lifts. Programming is push-up / pull-up progressions, "
        "kettlebell goblet squats, KB swings, single-leg work."
    ),
    "real_erik": (
        "Live athlete. Pull current state from production. Whatever the program "
        "says is ground truth — coach should cite from `get_workout` tool results "
        "and the full-week block in athlete_data."
    ),
}
```

- [ ] **Step 3: Wire judge into runner**

Modify `tests/coach_audit/runner.py` — replace `make_coach_invoker` ending of file with:

```python
def make_judge_invoker():
    """Returns a judge function bound to ARCHETYPE_DESCRIPTIONS lookup."""
    from .judge import judge_response
    from .users import ARCHETYPE_DESCRIPTIONS

    def invoke(case, response):
        desc = ARCHETYPE_DESCRIPTIONS.get(case.user_fixture, "")
        return judge_response(case, response, desc)
    return invoke
```

- [ ] **Step 4: Update test to drive heuristic + judge**

Replace `test_real_coach_heuristic_only` in `tests/test_coach_audit.py` with:

```python
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY for live coach + judge",
)
@pytest.mark.parametrize(
    "case",
    [p for p in ALL_PROMPTS if p.id == "cross_day_001"],
    ids=lambda c: c.id,
)
def test_real_coach_with_judge(case, phase_2_mid_program, app_ctx, run_id):
    app, _ = app_ctx
    invoke = make_coach_invoker(app, phase_2_mid_program)
    judge = make_judge_invoker()
    finding = run_prompt(
        case=case,
        user_id=phase_2_mid_program.id,
        invoke_coach=invoke,
        invoke_judge=judge,
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"heuristic: missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}"
    )
    assert finding.judge.passed, (
        f"judge: violations={finding.judge.violations}\n"
        f"scores={finding.judge.scores}\n"
        f"evidence={finding.judge.evidence}"
    )
```

Update the import:

```python
from tests.coach_audit.runner import run_prompt, make_coach_invoker, make_judge_invoker
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_coach_audit.py::test_real_coach_with_judge -v -s`
Expected: PASS — judge confirms response matches archetype. Finding JSON now has both `heuristic` and `judge` populated.

- [ ] **Step 6: Commit**

```bash
git add tests/coach_audit/judge.py tests/coach_audit/users.py tests/coach_audit/runner.py tests/test_coach_audit.py
git commit -m "Coach audit: Opus 4.7 judge with structured JSON output"
```

---

## Task 5: Three more synthetic user fixtures

Add `phase_1_newbie`, `phase_3_cut`, and `no_gym_bw`. Each is a thin variant of `phase_2_mid_program` with different `AppState`, equipment, and SetLog shape.

**Files:**
- Modify: `tests/coach_audit/users.py`
- Modify: `tests/coach_audit/conftest.py`
- Modify: `tests/test_coach_audit.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_coach_audit.py`:

```python
def test_phase_1_newbie_has_no_history(phase_1_newbie):
    from models import SetLog, AppState
    user = phase_1_newbie
    rows = SetLog.query.filter_by(user_id=user.id).all()
    assert len(rows) == 0, "phase_1_newbie should have no SetLog history"
    state = AppState.query.filter_by(user_id=user.id).first()
    assert state.current_week == 2


def test_phase_3_cut_has_plateau_pattern(phase_3_cut):
    from models import SetLog
    bench_rows = SetLog.query.filter_by(
        user_id=phase_3_cut.id,
        exercise_name="Barbell Bench Press",
    ).all()
    weights = sorted({r.weight for r in bench_rows})
    assert 165 in weights, "phase_3_cut should have bench plateau at 165"


def test_no_gym_bw_lacks_barbell(no_gym_bw):
    from models import UserEquipment
    eq = UserEquipment.query.filter_by(user_id=no_gym_bw.id).first()
    assert "barbell" not in (eq.available_equipment or [])
    assert "kettlebells" in (eq.available_equipment or [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_audit.py -v -k "phase_1_newbie or phase_3_cut or no_gym_bw" --no-header`
Expected: 3 FAILs — fixtures undefined.

- [ ] **Step 3: Implement the three factories**

Append to `tests/coach_audit/users.py`:

```python
def make_phase_1_newbie():
    from app import db
    from models import User, UserEquipment, PhysicalAssessment, AppState
    u = User(email=_next_email("p1"), password_hash="x")
    db.session.add(u); db.session.commit()
    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=["barbell", "dumbbells", "flat_bench", "pull_up_bar"],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=7),
        current_week=2,
    ))
    db.session.commit()
    return u


def make_phase_3_cut():
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState,
        SetLog, BodyWeight, TrainingGoal,
    )
    u = User(email=_next_email("p3"), password_hash="x")
    db.session.add(u); db.session.commit()
    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=[
            "barbell", "dumbbells", "flat_bench", "pull_up_bar",
            "lat_pulldown", "cable_machine",
        ],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=56),
        current_week=9,
    ))
    db.session.add(TrainingGoal(
        user_id=u.id, goal_type="cut", target_weight=175.0, daily_calories=2000,
    ))
    db.session.commit()

    # Bench plateau: 3 weeks all at 165
    base = date.today() - timedelta(days=56)
    for week in range(6, 9):
        log_date = base + timedelta(days=(week - 1) * 7 + 1)
        for set_no in range(1, 5):
            db.session.add(SetLog(
                user_id=u.id, week=week, day_idx=1,
                exercise_name="Barbell Bench Press",
                set_number=set_no, weight=165, reps=4,
                done=True, logged_date=log_date,
            ))

    # Weight ahead of target (181 with target 175 — only 6 lb to go in 4 wk left)
    for d_back, lbs in [(28, 188.0), (21, 185.0), (14, 183.0), (7, 181.0)]:
        db.session.add(BodyWeight(
            user_id=u.id,
            log_date=date.today() - timedelta(days=d_back),
            weight_lbs=lbs,
        ))
    db.session.commit()
    return u


def make_no_gym_bw():
    from app import db
    from models import User, UserEquipment, PhysicalAssessment, AppState
    u = User(email=_next_email("bw"), password_hash="x")
    db.session.add(u); db.session.commit()
    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=["kettlebells", "pull_up_bar"],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=False))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=14),
        current_week=3,
    ))
    db.session.commit()
    return u
```

- [ ] **Step 4: Wire fixtures**

Append to `tests/coach_audit/conftest.py`:

```python
@pytest.fixture(scope="function")
def phase_1_newbie(app_ctx):
    from tests.coach_audit.users import make_phase_1_newbie
    return make_phase_1_newbie()


@pytest.fixture(scope="function")
def phase_3_cut(app_ctx):
    from tests.coach_audit.users import make_phase_3_cut
    return make_phase_3_cut()


@pytest.fixture(scope="function")
def no_gym_bw(app_ctx):
    from tests.coach_audit.users import make_no_gym_bw
    return make_no_gym_bw()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_coach_audit.py -v -k "phase_1_newbie or phase_3_cut or no_gym_bw"`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/coach_audit/users.py tests/coach_audit/conftest.py tests/test_coach_audit.py
git commit -m "Coach audit: phase_1_newbie, phase_3_cut, no_gym_bw fixtures"
```

---

## Task 6: Generic parametrized test driver

Replace the per-prompt-id explicit tests with a single parametrized test that loops over the entire corpus, looks up the right fixture by name, and runs `run_prompt`. This is the harness's true entry point.

**Files:**
- Modify: `tests/test_coach_audit.py`
- Modify: `tests/coach_audit/conftest.py`

- [ ] **Step 1: Add fixture-by-name resolver to `conftest.py`**

Append to `tests/coach_audit/conftest.py`:

```python
@pytest.fixture
def fixture_by_name(request):
    """Look up a fixture by its string name. Used to map PromptCase.user_fixture
    → the actual user object."""
    def _resolve(name):
        return request.getfixturevalue(name)
    return _resolve
```

- [ ] **Step 2: Replace per-id tests with single parametrized loop**

Replace `test_real_coach_with_judge` in `tests/test_coach_audit.py` with:

```python
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY for live coach + judge",
)
@pytest.mark.parametrize(
    "case",
    [p for p in ALL_PROMPTS if p.category not in ("smoke",)],
    ids=lambda c: c.id,
)
def test_audit_case(case, fixture_by_name, app_ctx, run_id, audit_mode):
    if case.requires_real_data and audit_mode != "full":
        pytest.skip("requires --audit-mode=full")

    user = fixture_by_name(case.user_fixture)
    app, _ = app_ctx
    invoke = make_coach_invoker(app, user)
    judge = make_judge_invoker()
    finding = run_prompt(
        case=case,
        user_id=user.id,
        invoke_coach=invoke,
        invoke_judge=judge,
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"[{case.id}] heuristic: "
        f"missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}\n"
        f"--- response ---\n{finding.coach_response}"
    )
    assert finding.judge.passed, (
        f"[{case.id}] judge: violations={finding.judge.violations}\n"
        f"scores={finding.judge.scores}\n"
        f"evidence={finding.judge.evidence}\n"
        f"--- response ---\n{finding.coach_response}"
    )
```

Keep the smoke test and the fixture-shape tests; remove the now-redundant `test_real_coach_with_judge`.

- [ ] **Step 3: Run with current single-prompt corpus**

Run: `pytest tests/test_coach_audit.py::test_audit_case -v -s`
Expected: 1 case (`cross_day_001`) runs and PASSes.

- [ ] **Step 4: Commit**

```bash
git add tests/test_coach_audit.py tests/coach_audit/conftest.py
git commit -m "Coach audit: generic parametrized test driver"
```

---

## Task 7: Prompt corpus — first 50 prompts

Add 3-5 prompts per category × 12 categories. Concrete, real-world, drawn from past coach failures.

**Files:**
- Modify: `tests/coach_audit/prompts.py`

- [ ] **Step 1: Write the prompts**

Replace `ALL_PROMPTS` in `tests/coach_audit/prompts.py` with:

```python
"""Prompt corpus. Add cases freely — harness loops over `ALL_PROMPTS`."""
from .types import PromptCase


_smoke = [
    PromptCase(
        id="smoke_001", category="smoke",
        user_message="ping",
        user_fixture="phase_2_mid_program",
        expected_behavior=["pong"],
        must_not=["ERROR"],
        focus_dimensions=["accuracy"],
    ),
]

_cross_day = [
    PromptCase(
        id="cross_day_001", category="cross_day_hallucination",
        user_message="What lift is on Monday this week and what's the scheme?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["front squat", "4x3"],
        must_not=["back squat 4x5", "back squat 5x5"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="cross_day_002", category="cross_day_hallucination",
        user_message="Tell me Friday's lift, sets, and reps.",
        user_fixture="phase_2_mid_program",
        expected_behavior=["back squat", "4x5"],
        must_not=["front squat 4x3", "deadlift"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="cross_day_003", category="cross_day_hallucination",
        user_message="What am I doing Thursday?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["pull"],
        must_not=["squat"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="cross_day_004", category="cross_day_hallucination",
        user_message="Walk me through the whole week.",
        user_fixture="phase_2_mid_program",
        expected_behavior=["monday", "tuesday", "wednesday", "thursday", "friday"],
        must_not=["bench press monday", "deadlift"],
        focus_dimensions=["accuracy"],
    ),
]

_banned_phrases = [
    PromptCase(
        id="banned_001", category="banned_phrases",
        user_message="I'm tired today.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great work", "let's get after it", "you've got this", "what's on your mind"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="banned_002", category="banned_phrases",
        user_message="Just finished my squats.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great work", "crushing it", "keep grinding", "done. tomorrow:"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="banned_003", category="banned_phrases",
        user_message="Hi.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["what's on your mind", "speak."],
        focus_dimensions=["tone"],
    ),
]

_schedule_leak = [
    PromptCase(
        id="schedule_001", category="schedule_leak",
        user_message="What's the plan today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["<schedule>", "</schedule>", "<directive>"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="schedule_002", category="schedule_leak",
        user_message="Give me my full week schedule.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["<schedule>", "</schedule>"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="schedule_003", category="schedule_leak",
        user_message="When is my next workout?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["<schedule>", "<directive>", "<motivation>"],
        focus_dimensions=["tone"],
    ),
]

_session_status = [
    PromptCase(
        id="session_001", category="session_status",
        user_message="Should I lift now?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="session_002", category="session_status",
        user_message="What's left for me to do today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="session_003", category="session_status",
        user_message="Did I finish my workout already?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_swap_logic = [
    PromptCase(
        id="swap_001", category="swap_logic",
        user_message="Bench is taken, give me a substitute.",
        user_fixture="phase_2_mid_program",
        expected_behavior=["dumbbell"],
        must_not=["barbell bench"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="swap_002", category="swap_logic",
        user_message="No barbell today. What can I do for squats?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["barbell"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="swap_003", category="swap_logic",
        user_message="Swap front squat for something easier on my knees.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["front squat"],
        focus_dimensions=["accuracy"],
    ),
]

_progression = [
    PromptCase(
        id="prog_001", category="progression_citation",
        user_message="What weight should I start bench at today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["165", "160"],   # last logged peak
        must_not=["315", "405"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="prog_002", category="progression_citation",
        user_message="What did I hit last front squat session?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["170"],
        must_not=["315"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="prog_003", category="progression_citation",
        user_message="What's my next bench target?",
        user_fixture="phase_3_cut",
        expected_behavior=[],
        must_not=["205"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
]

_run_pacing = [
    PromptCase(
        id="run_001", category="run_pacing",
        user_message="What's the run today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_002", category="run_pacing",
        user_message="How long is my Sunday run?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_003", category="run_pacing",
        user_message="Tempo run pace target?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_deload = [
    PromptCase(
        id="deload_001", category="deload_handling",
        user_message="What's this week's stress level?",
        user_fixture="phase_3_cut",
        expected_behavior=[],
        must_not=["push for PR", "personal record"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="deload_002", category="deload_handling",
        user_message="Should I PR today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["yes"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="deload_003", category="deload_handling",
        user_message="I want to add weight every set.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_psych = [
    PromptCase(
        id="psych_001", category="psych_intake_resume",
        user_message="My job is super stressful and I'm not sleeping.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great work", "you've got this"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="psych_002", category="psych_intake_resume",
        user_message="I missed two workouts this week, I'm done.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["okay, take a break", "great work"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="psych_003", category="psych_intake_resume",
        user_message="Can you check in on how I'm feeling?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["what's on your mind"],
        focus_dimensions=["tone"],
    ),
]

_pushback = [
    PromptCase(
        id="pushback_001", category="boundary_pushback",
        user_message="I don't feel like lifting today, can I just skip?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["sure", "your call", "at least log it"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="pushback_002", category="boundary_pushback",
        user_message="Can I drop the weight to 135 instead of 170?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["sure"],
        focus_dimensions=["tone", "accuracy"],
    ),
    PromptCase(
        id="pushback_003", category="boundary_pushback",
        user_message="Tell me I did a great job today.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great job", "great work", "you did great"],
        focus_dimensions=["tone"],
    ),
]

_week_drift = [
    PromptCase(
        id="drift_001", category="week_drift",
        user_message="What week am I on?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["6", "week 6"],
        must_not=["week 5", "week 7"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="drift_002", category="week_drift",
        user_message="How many weeks have I done?",
        user_fixture="phase_3_cut",
        expected_behavior=["8", "9"],
        must_not=["12"],
        focus_dimensions=["accuracy"],
    ),
]

_edge_cases = [
    PromptCase(
        id="edge_001", category="edge_cases",
        user_message="What should I lift today?",
        user_fixture="phase_1_newbie",
        expected_behavior=[],
        must_not=["315", "405", "your last set was"],
        focus_dimensions=["no_hallucination"],
    ),
    PromptCase(
        id="edge_002", category="edge_cases",
        user_message="What's my squat 1RM?",
        user_fixture="phase_1_newbie",
        expected_behavior=[],
        must_not=["315", "405"],
        focus_dimensions=["no_hallucination"],
    ),
    PromptCase(
        id="edge_003", category="edge_cases",
        user_message="Plan today's workout.",
        user_fixture="no_gym_bw",
        expected_behavior=[],
        must_not=["barbell", "bench press", "back squat"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="edge_004", category="edge_cases",
        user_message="What should I bench today?",
        user_fixture="no_gym_bw",
        expected_behavior=[],
        must_not=["barbell", "bench press 165"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
]


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
)
```

- [ ] **Step 2: Sanity-check corpus loads**

Run: `python -c "from tests.coach_audit.prompts import ALL_PROMPTS; print(len(ALL_PROMPTS), 'prompts'); print(sorted({p.category for p in ALL_PROMPTS}))"`
Expected: ~36 prompts across 13 categories (12 + smoke).

- [ ] **Step 3: Run full audit (subset of prompts to limit cost)**

Run: `pytest tests/test_coach_audit.py::test_audit_case -v -s -k "cross_day_001 or banned_001 or schedule_001"`
Expected: 3 PASSes (these are highest-confidence prompts).

- [ ] **Step 4: Commit**

```bash
git add tests/coach_audit/prompts.py
git commit -m "Coach audit: 35+ prompt corpus across 12 categories"
```

---

## Task 8: Real Erik fixture (gated)

Pull live state from production into the test sqlite DB so the audit can run against actual data shape. Read-only — write only to local sqlite. Gated by `--audit-mode=full`.

**Files:**
- Modify: `tests/coach_audit/users.py`
- Modify: `tests/coach_audit/conftest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_coach_audit.py`:

```python
@pytest.mark.real_data
def test_real_erik_fixture_loads(real_erik, audit_mode):
    if audit_mode != "full":
        pytest.skip("requires --audit-mode=full")
    from models import AppState
    state = AppState.query.filter_by(user_id=real_erik.id).first()
    assert state is not None
    assert state.current_week >= 1
```

- [ ] **Step 2: Implement `make_real_erik` in `users.py`**

Append to `tests/coach_audit/users.py`:

```python
def make_real_erik():
    """Pull Erik's current state from production via /api/admin/debug/sql,
    mirror into the local test DB. Read-only against prod."""
    import os
    import requests
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState,
        WeeklyPrescription, WeeklyRunPlan, SetLog, BodyWeight, TrainingGoal,
    )

    api_key = os.environ.get("ADMIN_API_KEY")
    if not api_key:
        raise RuntimeError("ADMIN_API_KEY not set — cannot mirror real Erik state.")
    base = os.environ.get("PLACEMETRY_PROD_URL", "https://12weeks-app.onrender.com")

    def q(sql: str) -> list[dict]:
        r = requests.post(
            f"{base}/api/admin/debug/sql",
            headers={"X-Admin-Key": api_key, "Content-Type": "application/json"},
            json={"sql": sql},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("rows") or []

    # 1) Resolve Erik's user_id via email
    user_rows = q("SELECT id, email, password_hash FROM \"user\" WHERE email = 'erik@placemetry.com' LIMIT 1")
    if not user_rows:
        raise RuntimeError("real Erik not found in prod by email")
    src = user_rows[0]
    src_id = src["id"]

    # 2) Mirror — local copies get fresh PKs
    u = User(email=_next_email("erik"), password_hash="x")
    db.session.add(u); db.session.commit()
    new_id = u.id

    # AppState
    rows = q(f"SELECT current_week, start_date FROM app_state WHERE user_id = {src_id}")
    if rows:
        r = rows[0]
        from datetime import date as _date
        sd = r["start_date"]
        if isinstance(sd, str):
            sd = _date.fromisoformat(sd[:10])
        db.session.add(AppState(user_id=new_id, current_week=r["current_week"], start_date=sd))

    # UserEquipment
    rows = q(f"SELECT available_equipment FROM user_equipment WHERE user_id = {src_id}")
    if rows:
        eq = rows[0]["available_equipment"] or []
        db.session.add(UserEquipment(user_id=new_id, available_equipment=eq))

    # PhysicalAssessment
    rows = q(f"SELECT has_gym FROM physical_assessment WHERE user_id = {src_id}")
    if rows:
        db.session.add(PhysicalAssessment(user_id=new_id, has_gym=bool(rows[0]["has_gym"])))

    # SetLog (last 60 days)
    rows = q(f"""
        SELECT week, day_idx, exercise_name, set_number, weight, reps, done, logged_date
        FROM set_log
        WHERE user_id = {src_id} AND logged_date > current_date - 60
        ORDER BY logged_date DESC LIMIT 500
    """)
    from datetime import date as _date
    for r in rows:
        ld = r["logged_date"]
        if isinstance(ld, str):
            ld = _date.fromisoformat(ld[:10])
        db.session.add(SetLog(
            user_id=new_id,
            week=r["week"], day_idx=r["day_idx"],
            exercise_name=r["exercise_name"],
            set_number=r["set_number"],
            weight=r["weight"], reps=r["reps"],
            done=bool(r["done"]),
            logged_date=ld,
        ))

    # WeeklyRunPlan (current week)
    rows = q(f"""
        SELECT week, day_idx, run_type, label, duration, detail, source
        FROM weekly_run_plan WHERE user_id = {src_id}
    """)
    for r in rows:
        db.session.add(WeeklyRunPlan(
            user_id=new_id,
            week=r["week"], day_idx=r["day_idx"],
            run_type=r["run_type"], label=r["label"],
            duration=r["duration"], detail=r["detail"], source=r["source"],
        ))

    db.session.commit()
    return u
```

- [ ] **Step 3: Wire fixture and pytest mark**

Append to `tests/coach_audit/conftest.py`:

```python
@pytest.fixture(scope="function")
def real_erik(app_ctx):
    from tests.coach_audit.users import make_real_erik
    return make_real_erik()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_data: opt-in, hits prod via /api/admin/debug/sql"
    )
```

- [ ] **Step 4: Run gated test**

Run (default mode skips): `pytest tests/test_coach_audit.py::test_real_erik_fixture_loads -v`
Expected: SKIPPED (audit_mode != full).

Run (full mode): `ADMIN_API_KEY=$ADMIN_API_KEY pytest tests/test_coach_audit.py::test_real_erik_fixture_loads -v --audit-mode=full`
Expected: PASS — Erik's prod state mirrored into local sqlite.

- [ ] **Step 5: Commit**

```bash
git add tests/coach_audit/users.py tests/coach_audit/conftest.py tests/test_coach_audit.py
git commit -m "Coach audit: real Erik fixture mirrors prod state read-only"
```

---

## Task 9: Markdown report generator (summary + by-category + dimension fails)

Aggregate all findings JSON files in `findings/<run_id>/` into a single markdown report. No clustering yet — just stats and tables.

**Files:**
- Create: `tests/coach_audit/report.py`
- Create: `tests/coach_audit/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
"""Test the report generator with synthetic findings."""
import json
from pathlib import Path
import pytest


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    from tests.coach_audit import runner as runner_module
    findings_root = tmp_path / "findings"
    monkeypatch.setattr(runner_module, "FINDINGS_ROOT", findings_root)

    from tests.coach_audit import report as report_module
    monkeypatch.setattr(report_module, "FINDINGS_ROOT", findings_root)
    monkeypatch.setattr(report_module, "REPORTS_ROOT", tmp_path / "reports")

    run_id = "20260501-120000"
    d = findings_root / run_id
    d.mkdir(parents=True)

    findings = [
        {
            "prompt_id": "cross_day_001", "category": "cross_day_hallucination",
            "user_message": "What's Monday?", "coach_response": "Front Squat 4x3",
            "heuristic": {"passed": True, "missing_expected": [],
                          "matched_must_not": [], "matched_banned": []},
            "judge": {"passed": True,
                      "scores": {"accuracy": 9, "tone": 8, "no_hallucination": 9, "follows_must_not": 10},
                      "violations": [], "evidence": ""},
            "fixture": "phase_2_mid_program",
            "timestamp_iso": "2026-05-01T12:00:00+00:00",
        },
        {
            "prompt_id": "cross_day_002", "category": "cross_day_hallucination",
            "user_message": "Friday?", "coach_response": "Deadlift 5x5",
            "heuristic": {"passed": False, "missing_expected": ["back squat", "4x5"],
                          "matched_must_not": [], "matched_banned": []},
            "judge": {"passed": False,
                      "scores": {"accuracy": 2, "tone": 7, "no_hallucination": 1, "follows_must_not": 8},
                      "violations": ["Hallucinated deadlift; Friday is Back Squat 4x5"],
                      "evidence": "Deadlift 5x5"},
            "fixture": "phase_2_mid_program",
            "timestamp_iso": "2026-05-01T12:01:00+00:00",
        },
    ]
    for f in findings:
        (d / f"{f['prompt_id']}.json").write_text(json.dumps(f, indent=2))
    return run_id, tmp_path


def test_build_report_emits_summary(fake_run):
    from tests.coach_audit.report import build_report
    run_id, root = fake_run
    out = build_report(run_id)
    assert out.exists()
    text = out.read_text()
    assert "Summary" in text
    assert "Pass rate by category" in text
    assert "cross_day_hallucination" in text
    assert "50%" in text or "1 / 2" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/coach_audit/test_report.py -v`
Expected: FAIL — `report.py` not found.

- [ ] **Step 3: Implement `report.py`**

```python
"""Aggregate findings/<run_id>/*.json into a markdown report."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from .runner import FINDINGS_ROOT


REPORTS_ROOT = Path(__file__).parent / "reports"


def _load_findings(run_id: str) -> list[dict]:
    d = FINDINGS_ROOT / run_id
    if not d.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]


def _by_category(findings: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "fails": []})
    for f in findings:
        h_pass = f.get("heuristic", {}).get("passed", False)
        j = f.get("judge") or {}
        j_pass = j.get("passed", False) if j else h_pass
        passed = h_pass and j_pass
        bucket = out[f["category"]]
        bucket["pass" if passed else "fail"] += 1
        if not passed:
            bucket["fails"].append(f["prompt_id"])
    return out


def _dimension_avgs(findings: list[dict]) -> dict[str, float]:
    dims: dict[str, list[float]] = defaultdict(list)
    for f in findings:
        scores = (f.get("judge") or {}).get("scores") or {}
        for k, v in scores.items():
            try:
                dims[k].append(float(v))
            except (TypeError, ValueError):
                pass
    return {k: round(mean(vs), 2) for k, vs in dims.items() if vs}


def _heuristic_vs_judge(findings: list[dict]) -> dict[str, list[str]]:
    only_judge_failed = []
    only_heuristic_failed = []
    for f in findings:
        h = f.get("heuristic", {}).get("passed", False)
        j = (f.get("judge") or {}).get("passed", False)
        if h and not j:
            only_judge_failed.append(f["prompt_id"])
        elif j and not h:
            only_heuristic_failed.append(f["prompt_id"])
    return {
        "judge_only_fail": only_judge_failed,
        "heuristic_only_fail": only_heuristic_failed,
    }


def build_report(run_id: str) -> Path:
    findings = _load_findings(run_id)
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_ROOT / f"{run_id}.md"

    total = len(findings)
    passed = sum(
        1 for f in findings
        if f.get("heuristic", {}).get("passed")
        and (f.get("judge") or {}).get("passed", False)
    )
    fail = total - passed

    cats = _by_category(findings)
    dim_avgs = _dimension_avgs(findings)
    hvj = _heuristic_vs_judge(findings)

    lines: list[str] = [f"# Coach Audit Report — run {run_id}", ""]
    lines += [
        "## Summary",
        "",
        f"- Total prompts: **{total}**",
        f"- Passed: **{passed}** ({round(100 * passed / total, 1) if total else 0}%)",
        f"- Failed: **{fail}**",
        "",
    ]

    lines += ["## Pass rate by category", "",
              "| Category | Pass | Fail | Rate |", "|---|---|---|---|"]
    for cat, vals in sorted(cats.items(), key=lambda kv: kv[1]["fail"], reverse=True):
        denom = vals["pass"] + vals["fail"]
        rate = f"{round(100 * vals['pass'] / denom, 1)}%" if denom else "-"
        lines.append(f"| {cat} | {vals['pass']} | {vals['fail']} | {rate} |")
    lines.append("")

    if dim_avgs:
        lines += ["## Judge dimension averages", ""]
        for k, v in sorted(dim_avgs.items()):
            mark = " ⚠" if v < 7 else ""
            lines.append(f"- {k}: **{v}**{mark}")
        lines.append("")

    if hvj["judge_only_fail"] or hvj["heuristic_only_fail"]:
        lines += ["## Heuristic vs judge breakdown", ""]
        if hvj["judge_only_fail"]:
            lines.append(
                f"- **Judge caught what heuristic missed** "
                f"({len(hvj['judge_only_fail'])} prompts): "
                + ", ".join(hvj["judge_only_fail"])
            )
        if hvj["heuristic_only_fail"]:
            lines.append(
                f"- **Heuristic caught what judge missed** "
                f"({len(hvj['heuristic_only_fail'])} prompts): "
                + ", ".join(hvj["heuristic_only_fail"])
            )
        lines.append("")

    if fail:
        lines += ["## Failures by prompt", ""]
        for f in findings:
            h = f.get("heuristic", {}).get("passed", False)
            j = (f.get("judge") or {}).get("passed", False)
            if h and j:
                continue
            lines.append(f"### {f['prompt_id']} — {f['category']}")
            lines.append(f"**Prompt:** {f['user_message']}")
            lines.append(f"**Response (truncated):** {f['coach_response'][:400]}")
            if not h:
                hh = f["heuristic"]
                lines.append(
                    f"**Heuristic:** missing={hh['missing_expected']} "
                    f"must_not={hh['matched_must_not']} banned={hh['matched_banned']}"
                )
            if f.get("judge") and not j:
                jj = f["judge"]
                lines.append(f"**Judge violations:** {jj['violations']}")
                lines.append(f"**Judge scores:** {jj['scores']}")
            lines.append("")

    lines += ["", f"*Findings dir:* `tests/coach_audit/findings/{run_id}/`"]

    out_path.write_text("\n".join(lines))
    return out_path
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/coach_audit/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Hook report into pytest session finish**

Append to `tests/coach_audit/conftest.py`:

```python
def pytest_sessionfinish(session, exitstatus):
    """After all audit tests run, write a markdown report."""
    rid = getattr(session.config, "_audit_run_id", None)
    if rid is None:
        # Look for any session-scoped run_id fixture cache
        try:
            rid = session.config._audit_run_id_resolved
        except AttributeError:
            return
    try:
        from tests.coach_audit.report import build_report
        out = build_report(rid)
        print(f"\n[coach-audit] report written to {out}")
    except Exception as e:
        print(f"\n[coach-audit] report generation failed: {e}")


@pytest.fixture(scope="session", autouse=True)
def _stash_run_id(run_id, request):
    """Make run_id discoverable by pytest_sessionfinish."""
    request.config._audit_run_id_resolved = run_id
    yield
```

- [ ] **Step 6: Smoke-test end to end**

Run: `pytest tests/test_coach_audit.py -v -k smoke`
Expected: 1 PASS, plus a `[coach-audit] report written to .../reports/<run_id>.md` line in stdout.

- [ ] **Step 7: Commit**

```bash
git add tests/coach_audit/report.py tests/coach_audit/test_report.py tests/coach_audit/conftest.py
git commit -m "Coach audit: markdown report with per-category + dimension averages"
```

---

## Task 10: Pattern clustering (final Opus call)

After all per-prompt judge calls finish, send all failure summaries to Opus 4.7 in one final call to cluster them into named themes. Append the clusters to the report.

**Files:**
- Modify: `tests/coach_audit/report.py`
- Modify: `tests/coach_audit/test_report.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/coach_audit/test_report.py`:

```python
def test_cluster_patterns_returns_themes(monkeypatch):
    from tests.coach_audit import report as report_module

    fake_response = {
        "themes": [
            {"name": "Cross-day workout confusion", "count": 4,
             "prompts": ["cross_day_001", "cross_day_002"],
             "fix": "Tighten full-week injection in athlete_data"}
        ]
    }

    def fake_call(failures):
        return fake_response["themes"]
    monkeypatch.setattr(report_module, "_call_clustering_llm", fake_call)

    failures = [
        {"prompt_id": "cross_day_001", "category": "cross_day_hallucination",
         "judge": {"violations": ["Said Back Squat for Monday"]}},
        {"prompt_id": "cross_day_002", "category": "cross_day_hallucination",
         "judge": {"violations": ["Said Deadlift for Friday"]}},
    ]
    themes = report_module.cluster_patterns(failures)
    assert themes == fake_response["themes"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/coach_audit/test_report.py::test_cluster_patterns_returns_themes -v`
Expected: FAIL — `cluster_patterns` not defined.

- [ ] **Step 3: Implement `cluster_patterns` and integrate into report**

Append to `tests/coach_audit/report.py`:

```python
import os


CLUSTER_SYSTEM = """You are analyzing failures from a coach AI test suite.
You will be shown a list of failures, each with prompt_id, category, and judge violations.

Cluster these into 1-6 named themes. For each theme, return:
- name: short label (≤60 chars)
- count: number of failures in this theme
- prompts: list of prompt_ids
- fix: one-sentence recommended fix

Respond with JSON only:
{ "themes": [{"name": "...", "count": N, "prompts": [...], "fix": "..."}] }
"""


def _call_clustering_llm(failures: list[dict]) -> list[dict]:
    if not failures:
        return []
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_payload = json.dumps([
        {
            "prompt_id": f["prompt_id"],
            "category": f["category"],
            "violations": (f.get("judge") or {}).get("violations", []),
        }
        for f in failures
    ], indent=2)
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=CLUSTER_SYSTEM,
        messages=[{"role": "user", "content": user_payload}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    text = text.strip()
    if text.startswith("```"):
        import re as _re
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except Exception:
        return []
    return list(data.get("themes") or [])


def cluster_patterns(failures: list[dict]) -> list[dict]:
    return _call_clustering_llm(failures)
```

Modify `build_report` in `tests/coach_audit/report.py` — insert before the final `out_path.write_text(...)`:

```python
    failed_findings = [
        f for f in findings
        if not (f.get("heuristic", {}).get("passed")
                and (f.get("judge") or {}).get("passed", False))
    ]
    if failed_findings and os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("AUDIT_CLUSTER", "1") != "0":
        try:
            themes = cluster_patterns(failed_findings)
            if themes:
                lines += ["## Top failure patterns (clustered)", ""]
                for t in themes:
                    lines.append(f"### {t.get('name','(unnamed)')} ({t.get('count', 0)} occurrences)")
                    prompts = t.get("prompts") or []
                    if prompts:
                        lines.append(f"- Affected prompts: {', '.join(prompts)}")
                    fix = t.get("fix")
                    if fix:
                        lines.append(f"- Recommended fix: {fix}")
                    lines.append("")
        except Exception as e:
            lines += [f"_Pattern clustering failed: {e}_", ""]
```

- [ ] **Step 4: Run cluster test**

Run: `pytest tests/coach_audit/test_report.py -v`
Expected: 2 PASSes (existing + new clustering).

- [ ] **Step 5: Commit**

```bash
git add tests/coach_audit/report.py tests/coach_audit/test_report.py
git commit -m "Coach audit: pattern clustering via final Opus call"
```

---

## Task 11: Recommended-fixes ranking

Sort failure clusters into a prioritized fix list using `count × severity_weight`. Severity weight comes from category — `cross_day_hallucination` is HIGH, `tone` is MEDIUM, etc.

**Files:**
- Modify: `tests/coach_audit/report.py`
- Modify: `tests/coach_audit/test_report.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/coach_audit/test_report.py`:

```python
def test_rank_recommended_fixes():
    from tests.coach_audit.report import rank_fixes
    themes = [
        {"name": "Cross-day", "count": 4, "prompts": ["cross_day_001", "cross_day_002"], "fix": "Tighten injection"},
        {"name": "Tone slip", "count": 8, "prompts": ["banned_001"], "fix": "Tighten BANNED_PHRASES"},
    ]
    by_prompt_category = {
        "cross_day_001": "cross_day_hallucination",
        "cross_day_002": "cross_day_hallucination",
        "banned_001": "banned_phrases",
    }
    ranked = rank_fixes(themes, by_prompt_category)
    assert ranked[0]["name"] == "Cross-day"          # count×severity 4×3 = 12 vs 8×1 = 8
    assert "[HIGH]" in ranked[0]["badge"]
    assert ranked[1]["name"] == "Tone slip"
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/coach_audit/test_report.py::test_rank_recommended_fixes -v`
Expected: FAIL — `rank_fixes` not defined.

- [ ] **Step 3: Implement `rank_fixes`**

Append to `tests/coach_audit/report.py`:

```python
SEVERITY_BY_CATEGORY: dict[str, int] = {
    "cross_day_hallucination": 3,
    "schedule_leak":           3,
    "progression_citation":    3,
    "edge_cases":              3,   # equipment hallucination is high-impact
    "swap_logic":              2,
    "session_status":          2,
    "deload_handling":         2,
    "week_drift":              2,
    "boundary_pushback":       2,
    "run_pacing":              2,
    "psych_intake_resume":     1,
    "banned_phrases":          1,
    "smoke":                   0,
}

SEVERITY_BADGE = {3: "[HIGH]", 2: "[MED]", 1: "[LOW]", 0: "[INFO]"}


def rank_fixes(themes: list[dict], prompt_to_category: dict[str, str]) -> list[dict]:
    ranked = []
    for t in themes:
        prompts = t.get("prompts") or []
        cats = [prompt_to_category.get(p) for p in prompts if prompt_to_category.get(p)]
        if not cats:
            sev = 1
        else:
            sev = max(SEVERITY_BY_CATEGORY.get(c, 1) for c in cats)
        score = (t.get("count", 0)) * sev
        ranked.append({**t, "severity": sev, "score": score, "badge": SEVERITY_BADGE[sev]})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked
```

- [ ] **Step 4: Wire into `build_report`**

In `tests/coach_audit/report.py`, modify the cluster-patterns block to also rank:

Replace this snippet:

```python
            if themes:
                lines += ["## Top failure patterns (clustered)", ""]
                for t in themes:
                    lines.append(f"### {t.get('name','(unnamed)')} ({t.get('count', 0)} occurrences)")
                    prompts = t.get("prompts") or []
                    if prompts:
                        lines.append(f"- Affected prompts: {', '.join(prompts)}")
                    fix = t.get("fix")
                    if fix:
                        lines.append(f"- Recommended fix: {fix}")
                    lines.append("")
```

With:

```python
            if themes:
                prompt_to_category = {f["prompt_id"]: f["category"] for f in findings}
                ranked = rank_fixes(themes, prompt_to_category)
                lines += ["## Top failure patterns (clustered)", ""]
                for t in ranked:
                    lines.append(
                        f"### {t.get('badge','')} {t.get('name','(unnamed)')} "
                        f"(score {t.get('score', 0)}; {t.get('count', 0)} occurrences)"
                    )
                    prompts = t.get("prompts") or []
                    if prompts:
                        lines.append(f"- Affected prompts: {', '.join(prompts)}")
                    fix = t.get("fix")
                    if fix:
                        lines.append(f"- Recommended fix: {fix}")
                    lines.append("")
                lines += ["## Recommended fixes (ranked)", ""]
                for i, t in enumerate(ranked, 1):
                    lines.append(
                        f"{i}. {t['badge']} {t['name']} — {t.get('fix','(no fix supplied)')} "
                        f"(score {t['score']})"
                    )
                lines.append("")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/coach_audit/test_report.py -v`
Expected: 3 PASSes.

- [ ] **Step 6: Commit**

```bash
git add tests/coach_audit/report.py tests/coach_audit/test_report.py
git commit -m "Coach audit: rank recommended fixes by count × severity"
```

---

## Task 12: Parallel execution + first full audit run

Add `pytest-xdist` to the dev environment, gate the audit with a CLI flag, and run the first full audit. The first run is the deliverable.

**Files:**
- Modify: `requirements.txt` (or `requirements-dev.txt` if it exists; otherwise add a comment)
- Create: `tests/coach_audit/README.md`

- [ ] **Step 1: Add pytest-xdist**

Run:

```bash
grep -q pytest-xdist requirements.txt || echo "pytest-xdist>=3.5" >> requirements.txt
pip install -r requirements.txt
```

- [ ] **Step 2: Verify xdist works on smoke test**

Run: `pytest tests/test_coach_audit.py -v -k smoke -n 2`
Expected: PASS — note `[gw0] PASSED` style output indicating workers.

- [ ] **Step 3: Write `tests/coach_audit/README.md`**

```markdown
# Coach Audit Suite

Parametrized pytest harness that runs ~50 prompts through the production
coach (`coach_chat`), evaluates each response with heuristics + Opus 4.7
LLM-as-judge, persists findings, and emits a ranked-failure markdown report.

## Run modes

### CI mode (synthetic users only — safe, fast, ~$30/run)

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY pytest tests/test_coach_audit.py -n 8
```

### Full audit (real-Erik fixture too — slower, hits prod read-only)

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
ADMIN_API_KEY=$ADMIN_API_KEY \
pytest tests/test_coach_audit.py -n 8 --audit-mode=full
```

## Output

- `tests/coach_audit/findings/<run_id>/<prompt_id>.json` — per-prompt findings
- `tests/coach_audit/reports/<run_id>.md` — aggregated markdown report

## Adding a new prompt

Append a `PromptCase` to `tests/coach_audit/prompts.py`. Pick:
- `id`: stable string, used as filename
- `category`: one of the 12 categories (or add a new one + severity in `report.py`)
- `user_fixture`: name of pytest fixture (e.g., `phase_2_mid_program`)
- `expected_behavior`: substrings that must appear in response (lowercased; `×` ↔ `x`)
- `must_not`: substrings that must NOT appear
- `focus_dimensions`: judge weights these heavily

## Adding a new fixture

Add a factory to `tests/coach_audit/users.py`, register a fixture in
`tests/coach_audit/conftest.py`, and add an archetype description to
`ARCHETYPE_DESCRIPTIONS` (used by the judge).

## Cost

~$0.50/prompt with current Opus 4.7 pricing (1 coach call + 1 judge call).
50 prompts ≈ $25. Add ~$0.15 for final clustering. Run on demand or weekly.
```

- [ ] **Step 4: Run the first full audit (synthetic-only)**

Run:

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY pytest tests/test_coach_audit.py::test_audit_case -n 4 -v 2>&1 | tee /tmp/coach-audit-first-run.log
```

Expected: ~35 cases run. Some will FAIL (that's the point — it's an audit). The report is written to `tests/coach_audit/reports/<run_id>.md`.

- [ ] **Step 5: Commit findings + report**

```bash
git add requirements.txt tests/coach_audit/README.md
git add tests/coach_audit/findings/ tests/coach_audit/reports/
git commit -m "Coach audit: first audit run + report"
```

- [ ] **Step 6: Read the report and triage**

Open `tests/coach_audit/reports/<run_id>.md`. For each `[HIGH]` ranked theme, decide:
- **Fix now**: if root cause is a small prompt/code tweak (≤30 lines), fix and re-run.
- **Add as known issue**: append to a separate `tests/coach_audit/KNOWN_ISSUES.md` with rationale.
- **Loosen prompt**: if the test is unfair (over-strict expectation), tighten the `must_not` instead of `expected_behavior`.

This step is human-in-loop and not codified — the audit produced the artifact, fixing is a separate cycle.

---

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| pytest module + parametrization | Tasks 1, 6 |
| Subpackage with prompts/users/judge/runner/report | Tasks 1, 2, 4, 9 |
| pytest-xdist parallel | Task 12 |
| `--audit-mode=full` flag | Tasks 1, 8 |
| Per-prompt: coach call → heuristic → judge → save → assert | Tasks 1, 3, 4, 6 |
| `PromptCase` dataclass | Task 1 |
| Heuristic checks (must/must_not/banned) | Task 1 |
| Opus 4.7 judge with structured JSON | Task 4 |
| `focus_dimensions` (all 4 always emitted) | Task 4 |
| Findings persisted to `findings/<run_id>/<prompt_id>.json` | Task 1 |
| 4 synthetic user fixtures | Tasks 2, 5 |
| `real_erik` mirror via `/api/admin/debug/sql` | Task 8 |
| `--audit-mode=full` + `@pytest.mark.real_data` | Task 8 |
| Markdown report: summary, by-category, dimension fails | Task 9 |
| Heuristic-vs-judge breakdown | Task 9 |
| Pattern clustering via final Opus call | Task 10 |
| Recommended fixes ranked | Task 11 |
| Run-id format | Task 1 (conftest) |
| DB isolation via `DATABASE_URL` env | Task 1 (uses existing `tests/conftest.py`) |
| Incremental ramp (3-5/category × 12) | Task 7 |

No gaps.

**2. Placeholder scan:** No "TBD"/"TODO"/"implement later" found. All steps include concrete code.

**3. Type consistency:**
- `PromptCase` defined Task 1, used Tasks 3, 4, 6, 7
- `Finding` defined Task 1, persisted Tasks 1, 9
- `JudgeResult` defined Task 1, returned Task 4, consumed Tasks 9, 10, 11
- `HeuristicResult` defined Task 1, returned Task 1
- `make_phase_2_mid_program` etc. — names match between users.py and conftest.py
- `FINDINGS_ROOT` defined in runner.py, imported in report.py — consistent
- `_call_clustering_llm` and `cluster_patterns` are distinct (the test monkeypatches `_call_clustering_llm`, the public is `cluster_patterns`) — by design
- `ARCHETYPE_DESCRIPTIONS` keys match all fixture names in conftest

All consistent.
