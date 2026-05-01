# Coach Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM-with-instructions coach with a hybrid deterministic + LLM system: a rules engine pre-computes facts (schedule, directive, time, refusal triggers); the LLM only authors voice on top, and a validator enforces banned phrases + question-mark + byte-equality on pre-filled sections.

**Architecture:** `compute_coach_rules` (pure function) → `assemble_prompt` (rewritten with envelope contract) → LLM at temp 0.6 → `validate_response` (one retry with feedback, then deterministic fallback) → renderer strips tags. Past coach messages no longer feed the prompt; only ground-truth events from logs do.

**Tech Stack:** Python 3.11, Flask, SQLAlchemy (sqlite for tests), pytest, anthropic SDK.

**Spec:** `docs/superpowers/specs/2026-04-30-coach-rewrite-design.md`. Read it first.

---

## File Structure

**New files:**
- `coach_rules.py` — Rules engine. Dataclasses, time helpers, workout/run/fasting resolution, refusal detection, directive computation, pre-fill rendering, `compute_coach_rules` entry point.
- `coach_validator.py` — Response envelope parser, banned-phrase scan, question-mark scan, retry orchestration helpers, deterministic fallback template.
- `tests/test_coach_rules.py` — Unit tests for rules engine.
- `tests/test_coach_validator.py` — Unit tests for validator.
- `tests/test_coach_end_to_end.py` — Integration tests with mocked LLM.

**Files modified:**
- `coach_assembler.py` (~1430 lines) — Replace `_build_chat_history` with `_build_event_timeline`. Add sentinels to empty section builders. Time-window `_build_coach_memories`. Rewrite `CORE_PROMPT` (line 808). Rewrite `PROTOCOL_MAP` (line 904). Update `assemble_prompt` (line 1384) to inject pre-filled sections.
- `coach_agents.py` (108 lines) — Replace per-agent `requires` lists with single `ALL_SECTIONS` constant. Lower `weekly_review` temperature 1.0 → 0.6.
- `app.py:4909-5095` — `/api/chat` endpoint switched from raw LLM call to `coach_respond` orchestration function (defined in coach_assembler.py).

**Files NOT modified (read for reference only):**
- `coach.py` — Existing helpers; some may be reused, none rewritten.
- `coach_router.py` — Returns `agent_name` from the user message; unchanged.
- `coach_state.py` — anger_level update; unchanged.
- `models.py` — Schema unchanged.

**Test conventions** (from `tests/conftest.py` + existing tests):
- conftest.py sets a per-process temp sqlite DB before app import.
- Test classes use `app_ctx` module-scoped fixture: `(app, db) = app_ctx; with app.app_context(): ...`.
- Per-test users built via factory fixtures returning a user with seeded data.
- Tests run via `pytest tests/path -v`.

---

## Task 1: `coach_rules.py` skeleton — dataclasses + time helpers

**Files:**
- Create: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coach_rules.py`:

```python
"""Unit tests for the coach rules engine.

The rules engine is a pure function (user_id, now, latest_user_message)
-> CoachRules. No LLM. Deterministic. The cornerstone of the coach
rewrite — every fact the LLM sees about schedule, directive, time, and
refusal must come from here.
"""
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


class TestTimeHelpers:
    def test_user_local_now_has_pacific_tz(self):
        from coach_rules import _user_local_now
        n = _user_local_now()
        assert n.tzinfo is not None
        assert "Los_Angeles" in str(n.tzinfo)

    def test_user_local_now_accepts_override(self):
        from coach_rules import _user_local_now
        fixed = datetime(2026, 4, 30, 10, 30, tzinfo=timezone.utc)
        n = _user_local_now(now=fixed)
        # 10:30 UTC = 03:30 PDT
        assert n.hour == 3
        assert n.minute == 30


class TestDataclassesShape:
    def test_workout_summary_fields(self):
        from coach_rules import WorkoutSummary
        w = WorkoutSummary(
            lift_name="Front Squat",
            exercise_names=["Front Squat", "RDL"],
            is_rest=False,
        )
        assert w.lift_name == "Front Squat"
        assert w.exercise_names == ["Front Squat", "RDL"]
        assert w.is_rest is False

    def test_run_summary_fields(self):
        from coach_rules import RunSummary
        r = RunSummary(
            run_type="z2",
            label="Z2 30 min",
            scheduled_at=dtime(6, 45),
            detail="Easy effort, HR < 150",
        )
        assert r.run_type == "z2"
        assert r.label == "Z2 30 min"
        assert r.scheduled_at == dtime(6, 45)

    def test_directive_fields(self):
        from coach_rules import Directive
        d = Directive(text="Lift now. Front Squat.", category="workout_in_window")
        assert d.text == "Lift now. Front Squat."
        assert d.category == "workout_in_window"

    def test_coach_rules_is_frozen(self):
        from coach_rules import CoachRules, Directive
        # Try to construct with all required fields
        from datetime import datetime, timezone, time as dtime
        r = CoachRules(
            now_utc=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
            now_local=datetime(2026, 4, 30, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            local_date_iso="2026-04-30",
            local_weekday="Thursday",
            local_time_hhmm="10:00",
            workout_today=None,
            workout_today_scheduled_at=dtime(6, 0),
            workout_today_status="rest",
            run_today=None,
            run_today_status="rest",
            workout_tomorrow=None,
            workout_tomorrow_scheduled_at=None,
            run_tomorrow=None,
            fasting_active=False,
            fasting_hours=None,
            fasting_target_hours=None,
            fasting_break_at=None,
            directive=Directive(text="Recovery day.", category="rest"),
            refusal_required=False,
            refusal_reason=None,
            prefilled_schedule="<schedule>...</schedule>",
            prefilled_directive="<directive>Recovery day.</directive>",
        )
        # Frozen — should raise FrozenInstanceError
        with pytest.raises(Exception):
            r.local_weekday = "Friday"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_coach_rules.py -v`
Expected: FAIL with "ImportError: cannot import name '_user_local_now' from 'coach_rules'" (or similar — module doesn't exist yet).

- [ ] **Step 3: Create `coach_rules.py` with dataclasses + time helper**

Create `coach_rules.py`:

```python
"""Coach rules engine.

Pure function (user_id, now, latest_user_message) -> CoachRules.

No LLM. No external I/O beyond DB reads. Deterministic, fast.
The output is the *facts* the coach speaks — schedule, directive,
time, refusal triggers. The LLM only authors voice on top of these.

This eliminates the failure modes documented in
docs/superpowers/research/2026-04-30-coach-audit.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")


def _user_local_now(now: Optional[datetime] = None) -> datetime:
    """Return Pacific-local time. Pass `now` (UTC, tz-aware) to override
    for testing. The override path is the only way the rules engine
    ever sees a non-real clock — production never passes `now`."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(PACIFIC)


@dataclass(frozen=True)
class WorkoutSummary:
    lift_name: str
    exercise_names: list[str]
    is_rest: bool


@dataclass(frozen=True)
class RunSummary:
    run_type: str          # "z2" | "hiit" | "z2_long"
    label: str             # human-facing, e.g. "Z2 30 min" or "HIIT 6x400m"
    scheduled_at: Optional[dtime]
    detail: str


@dataclass(frozen=True)
class Directive:
    text: str
    category: str          # rule key from the directive table for telemetry


@dataclass(frozen=True)
class CoachRules:
    now_utc: datetime
    now_local: datetime
    local_date_iso: str
    local_weekday: str
    local_time_hhmm: str

    workout_today: Optional[WorkoutSummary]
    workout_today_scheduled_at: Optional[dtime]
    workout_today_status: str           # "not_started" | "in_progress" | "complete" | "rest"

    run_today: Optional[RunSummary]
    run_today_status: str               # "not_started" | "logged" | "skipped" | "rest"

    workout_tomorrow: Optional[WorkoutSummary]
    workout_tomorrow_scheduled_at: Optional[dtime]
    run_tomorrow: Optional[RunSummary]

    fasting_active: bool
    fasting_hours: Optional[float]
    fasting_target_hours: Optional[float]
    fasting_break_at: Optional[datetime]

    directive: Directive
    refusal_required: bool
    refusal_reason: Optional[str]

    prefilled_schedule: str             # Rendered <schedule>...</schedule>
    prefilled_directive: str            # Rendered <directive>...</directive>
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py -v`
Expected: PASS — 4 tests passing in TestTimeHelpers + TestDataclassesShape.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add coach_rules.py skeleton: dataclasses + time helper"
```

---

## Task 2: Workout resolution — today + tomorrow + status

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

This task computes `workout_today`, `workout_tomorrow`, `workout_today_status`, `workout_today_scheduled_at`, `workout_tomorrow_scheduled_at`. It mirrors the resolution chain in `coach_assembler.py:_resolve_workout_for_day` (PHASE_TEMPLATES → WeeklyPrescription → auto_swap_workout → ExerciseSwap), but exposes a leaner summary.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_rules.py`:

```python
class TestWorkoutResolution:
    def _make_user(self, app_ctx):
        from models import User, UserEquipment, PhysicalAssessment
        app, db = app_ctx
        u = User(email=f"rules-{id(self)}@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "lat_pulldown", "cable_machine",
            "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
            "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
            "dip_station", "ab_machine", "smith_machine",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq); db.session.add(pa); db.session.commit()
        return u

    def test_workout_today_resolves_for_phase_2_thursday(self, app_ctx):
        # Phase 2, Thursday (day_idx=3) — Erik's deadlift/back-side day.
        from coach_rules import _resolve_workout_for_day_summary
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            summary = _resolve_workout_for_day_summary(u.id, week=5, day_idx=3)
        assert summary is not None
        assert summary.is_rest is False
        # Phase 2 Thu has Weighted Pull-Up + BB Row per spec §4
        assert any("Row" in n or "Pull-Up" in n for n in summary.exercise_names)

    def test_workout_today_rest_day(self, app_ctx):
        # Phase 1 Sunday (day_idx=6) is rest in the new program.
        from coach_rules import _resolve_workout_for_day_summary
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            summary = _resolve_workout_for_day_summary(u.id, week=1, day_idx=6)
        assert summary is not None
        assert summary.is_rest is True
        assert summary.exercise_names == []


class TestWorkoutStatus:
    def test_status_not_started_when_no_sets_logged(self, app_ctx):
        from coach_rules import _compute_workout_status
        from datetime import date
        app, _ = app_ctx
        # No sets — status is "not_started" for a non-rest day
        with app.test_request_context():
            s = _compute_workout_status(
                user_id=999_999, week=5, day_idx=3,
                today_date=date.today(), is_rest=False,
            )
        assert s == "not_started"

    def test_status_rest_when_is_rest(self, app_ctx):
        from coach_rules import _compute_workout_status
        from datetime import date
        app, _ = app_ctx
        with app.test_request_context():
            s = _compute_workout_status(
                user_id=999_999, week=5, day_idx=6,
                today_date=date.today(), is_rest=True,
            )
        assert s == "rest"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestWorkoutResolution tests/test_coach_rules.py::TestWorkoutStatus -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_workout_for_day_summary'`.

- [ ] **Step 3: Implement workout resolution**

Append to `coach_rules.py`:

```python
def _resolve_workout_for_day_summary(user_id: int, week: int, day_idx: int) -> Optional[WorkoutSummary]:
    """Resolve the user's workout for (week, day_idx) through the same chain
    as api_workouts: PHASE_TEMPLATES → WeeklyPrescription → auto_swap → ExerciseSwap.

    Returns a lean WorkoutSummary (lift_name + exercise names), or None if the
    week/day cannot be resolved at all. Returns is_rest=True with empty exercises
    for rest days."""
    from coach_assembler import _resolve_workout_for_day
    day = _resolve_workout_for_day(week, day_idx)
    if day is None:
        return None
    if day.get("isRest"):
        return WorkoutSummary(
            lift_name=day.get("liftName", "Rest"),
            exercise_names=[],
            is_rest=True,
        )
    exercises = day.get("exercises", []) or []
    return WorkoutSummary(
        lift_name=day.get("liftName", ""),
        exercise_names=[e.get("name", "") for e in exercises if e.get("name")],
        is_rest=False,
    )


def _compute_workout_status(
    user_id: int,
    week: int,
    day_idx: int,
    today_date,
    is_rest: bool,
) -> str:
    """Returns one of: not_started | in_progress | complete | rest.

    Rest takes precedence. For non-rest days:
    - not_started: zero SetLog rows for this user/week/day_idx today.
    - in_progress: at least one SetLog row today, but not all configured sets done.
    - complete: every prescribed set has done=True.
    """
    if is_rest:
        return "rest"
    from models import SetLog
    sets_today = SetLog.query.filter_by(
        user_id=user_id, week=week, day_idx=day_idx,
        logged_date=today_date,
    ).all()
    if not sets_today:
        return "not_started"
    done_count = sum(1 for s in sets_today if s.done)
    # If any logged sets exist but not all done → in_progress.
    # We don't try to compute the "expected total" precisely — coach treats
    # any logged-but-incomplete session as in_progress.
    if done_count == 0:
        return "in_progress"
    # Heuristic: if the user logged any sets and stopped, treat as in_progress
    # unless the day's known exercise count appears all-completed. Keep it
    # simple — engine and api_workouts are the source of truth for "complete";
    # rules engine just needs a 4-bucket signal.
    if done_count >= len(sets_today):
        return "complete"
    return "in_progress"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py -v`
Expected: PASS — original tests + 4 new tests passing.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add workout resolution + status to coach rules engine"
```

---

## Task 3: Workout scheduled time + tomorrow

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

The default workout window is 06:00 (per Erik's preference: "I want both am stacked. Morning lift (6am)…"). Per-user override comes from `UserPreferences.workout_scheduled_at` if that table exists; otherwise fall back to 06:00 for non-rest days, None for rest.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_rules.py`:

```python
class TestWorkoutScheduledAt:
    def test_default_6am_for_non_rest(self, app_ctx):
        from coach_rules import _compute_workout_scheduled_at
        from datetime import time as dtime
        app, _ = app_ctx
        with app.test_request_context():
            t = _compute_workout_scheduled_at(user_id=999, is_rest=False)
        assert t == dtime(6, 0)

    def test_none_for_rest(self, app_ctx):
        from coach_rules import _compute_workout_scheduled_at
        app, _ = app_ctx
        with app.test_request_context():
            t = _compute_workout_scheduled_at(user_id=999, is_rest=True)
        assert t is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestWorkoutScheduledAt -v`
Expected: FAIL — `ImportError: cannot import name '_compute_workout_scheduled_at'`.

- [ ] **Step 3: Implement scheduled-time helper**

Append to `coach_rules.py`:

```python
DEFAULT_WORKOUT_TIME = dtime(6, 0)   # Erik's AM-stacked default


def _compute_workout_scheduled_at(user_id: int, is_rest: bool) -> Optional[dtime]:
    """Return the user's preferred workout time for the day, or None on rest.

    v1: hardcoded 6 AM default. UserPreferences override deferred to v2 —
    no users have a different preference today.
    """
    if is_rest:
        return None
    return DEFAULT_WORKOUT_TIME
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py::TestWorkoutScheduledAt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add workout scheduled-time helper to coach rules engine"
```

---

## Task 4: Run resolution — today + tomorrow + status

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

Run state comes from the `run` dict on each day in PHASE_TEMPLATES (added in commit a3639e8) plus `RunLog` rows for today.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_rules.py`:

```python
class TestRunResolution:
    def test_run_today_phase_2_thursday_is_hiit(self, app_ctx):
        from coach_rules import _resolve_run_for_day
        app, _ = app_ctx
        with app.test_request_context():
            r = _resolve_run_for_day(week=5, day_idx=3)
        assert r is not None
        assert r.run_type == "hiit"

    def test_run_today_sunday_is_long(self, app_ctx):
        from coach_rules import _resolve_run_for_day
        app, _ = app_ctx
        with app.test_request_context():
            r = _resolve_run_for_day(week=5, day_idx=6)
        assert r is not None
        assert r.run_type == "z2_long"


class TestRunStatus:
    def test_status_not_started_when_no_log(self, app_ctx):
        from coach_rules import _compute_run_status
        from datetime import date
        app, _ = app_ctx
        with app.test_request_context():
            s = _compute_run_status(
                user_id=999_999,
                today_date=date.today(),
                run_planned=True,
            )
        assert s == "not_started"

    def test_status_rest_when_no_run_planned(self, app_ctx):
        from coach_rules import _compute_run_status
        from datetime import date
        app, _ = app_ctx
        with app.test_request_context():
            s = _compute_run_status(
                user_id=999_999,
                today_date=date.today(),
                run_planned=False,
            )
        assert s == "rest"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestRunResolution tests/test_coach_rules.py::TestRunStatus -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_run_for_day'`.

- [ ] **Step 3: Implement run resolution**

Append to `coach_rules.py`:

```python
def _resolve_run_for_day(week: int, day_idx: int) -> Optional[RunSummary]:
    """Read the day's run dict from PHASE_TEMPLATES and project to RunSummary.

    Run dict shape: {"type": "z2"|"hiit"|"z2_long", "label": str,
                    "time": str, "detail": str}. None if no run scheduled.
    """
    from workout_data import get_workouts
    days = get_workouts(week)
    if day_idx >= len(days):
        return None
    run = days[day_idx].get("run")
    if not run:
        return None
    # Time may be e.g. "6:45 AM" — parse loosely; rules engine only needs a dtime.
    scheduled_at: Optional[dtime] = None
    raw_time = run.get("time", "")
    if raw_time:
        scheduled_at = _parse_time_loose(raw_time)
    return RunSummary(
        run_type=run.get("type", "z2"),
        label=run.get("label", ""),
        scheduled_at=scheduled_at,
        detail=run.get("detail", ""),
    )


def _parse_time_loose(raw: str) -> Optional[dtime]:
    """Parse loose time strings like '6:45 AM' or '6 AM' or '06:45'.
    Returns None if unparseable — rules engine treats None as 'unscheduled'."""
    import re
    s = raw.strip().upper()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", s)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2) or 0)
    suffix = m.group(3)
    if suffix == "PM" and h < 12:
        h += 12
    if suffix == "AM" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mm < 60):
        return None
    return dtime(h, mm)


def _compute_run_status(user_id: int, today_date, run_planned: bool) -> str:
    """Returns one of: not_started | logged | skipped | rest.

    rest: no run planned for today.
    not_started: run planned, no RunLog for today.
    logged: RunLog row exists for today.
    skipped: not used in v1 — would require explicit skip signal.
    """
    if not run_planned:
        return "rest"
    from models import RunLog
    log = RunLog.query.filter_by(
        user_id=user_id, run_date=today_date,
    ).first()
    return "logged" if log else "not_started"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py -v`
Expected: PASS — all rules tests passing.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add run resolution + status to coach rules engine"
```

---

## Task 5: Fasting state computation

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

Erik's fasting protocol per spec/intake: 16:8 IF (eats 11am-7pm) plus 40-hour weekend fast (Saturday 7pm → Monday 11am). The rules engine must compute the *current* fast hours and the next break time, deterministically from `now_local`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_rules.py`:

```python
class TestFastingState:
    def test_weekday_morning_in_16h_fast(self, app_ctx):
        # Wednesday 9 AM — fasting since Tue 7 PM = 14h into 16h IF
        from coach_rules import _compute_fasting_state
        from datetime import datetime
        app, _ = app_ctx
        wed_9am = datetime(2026, 4, 29, 9, 0, tzinfo=PACIFIC)
        with app.test_request_context():
            state = _compute_fasting_state(now_local=wed_9am)
        assert state.fasting_active is True
        assert state.fasting_target_hours == 16
        assert 13.5 <= state.fasting_hours <= 14.5
        # Break expected at 11 AM the same day
        assert state.fasting_break_at.hour == 11

    def test_weekday_eating_window(self, app_ctx):
        # Wednesday 1 PM — inside 11AM-7PM eating window
        from coach_rules import _compute_fasting_state
        from datetime import datetime
        app, _ = app_ctx
        wed_1pm = datetime(2026, 4, 29, 13, 0, tzinfo=PACIFIC)
        with app.test_request_context():
            state = _compute_fasting_state(now_local=wed_1pm)
        assert state.fasting_active is False
        assert state.fasting_hours is None

    def test_weekend_long_fast_active(self, app_ctx):
        # Sunday 10 AM — 39h into Sat-7PM-to-Mon-11AM fast
        from coach_rules import _compute_fasting_state
        from datetime import datetime
        app, _ = app_ctx
        sun_10am = datetime(2026, 5, 3, 10, 0, tzinfo=PACIFIC)
        with app.test_request_context():
            state = _compute_fasting_state(now_local=sun_10am)
        assert state.fasting_active is True
        assert state.fasting_target_hours == 40
        assert 38.5 <= state.fasting_hours <= 39.5
        # Break Monday 11 AM
        assert state.fasting_break_at.weekday() == 0  # Monday
        assert state.fasting_break_at.hour == 11
```

Note: `PACIFIC` import already available from earlier in the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestFastingState -v`
Expected: FAIL — `ImportError: cannot import name '_compute_fasting_state'`.

- [ ] **Step 3: Implement fasting state**

Append to `coach_rules.py`:

```python
from datetime import timedelta
from typing import NamedTuple


class FastingState(NamedTuple):
    fasting_active: bool
    fasting_hours: Optional[float]
    fasting_target_hours: Optional[int]
    fasting_break_at: Optional[datetime]


# Erik's fixed protocol — codified here. If we add per-user protocols later,
# move these to UserPreferences and pass them into compute_coach_rules.
EATING_WINDOW_START = dtime(11, 0)   # 11 AM
EATING_WINDOW_END = dtime(19, 0)     # 7 PM
WEEKEND_FAST_START_DAY = 5            # Saturday (Mon=0)
WEEKEND_FAST_START_TIME = dtime(19, 0)
WEEKEND_FAST_BREAK_DAY = 0            # Monday
WEEKEND_FAST_BREAK_TIME = dtime(11, 0)


def _compute_fasting_state(now_local: datetime) -> FastingState:
    """Compute current fasting state from local time alone.

    Protocol:
    - Mon 11 AM through Sat 7 PM: 16:8 IF — eat 11 AM to 7 PM, fast 7 PM to 11 AM.
    - Sat 7 PM through Mon 11 AM: 40-hour weekend fast.
    """
    weekday = now_local.weekday()
    today = now_local.date()
    t = now_local.time()

    weekend_start = datetime.combine(
        today - timedelta(days=(weekday - WEEKEND_FAST_START_DAY) % 7),
        WEEKEND_FAST_START_TIME,
        tzinfo=PACIFIC,
    )
    weekend_break = weekend_start + timedelta(hours=40)

    # Are we inside the weekend fast window?
    if weekend_start <= now_local < weekend_break:
        hours = (now_local - weekend_start).total_seconds() / 3600.0
        return FastingState(
            fasting_active=True,
            fasting_hours=round(hours, 2),
            fasting_target_hours=40,
            fasting_break_at=weekend_break,
        )

    # Inside weekday eating window?
    if EATING_WINDOW_START <= t < EATING_WINDOW_END:
        return FastingState(
            fasting_active=False,
            fasting_hours=None,
            fasting_target_hours=None,
            fasting_break_at=None,
        )

    # Otherwise: in 16:8 IF fast.
    if t >= EATING_WINDOW_END:
        # Fast started today at 7 PM
        fast_start = datetime.combine(today, EATING_WINDOW_END, tzinfo=PACIFIC)
        break_at = datetime.combine(today + timedelta(days=1), EATING_WINDOW_START, tzinfo=PACIFIC)
    else:
        # Fast started yesterday at 7 PM
        fast_start = datetime.combine(today - timedelta(days=1), EATING_WINDOW_END, tzinfo=PACIFIC)
        break_at = datetime.combine(today, EATING_WINDOW_START, tzinfo=PACIFIC)

    hours = (now_local - fast_start).total_seconds() / 3600.0
    return FastingState(
        fasting_active=True,
        fasting_hours=round(hours, 2),
        fasting_target_hours=16,
        fasting_break_at=break_at,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py::TestFastingState -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add fasting state computation to coach rules engine"
```

---

## Task 6: Refusal detection

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

Refusal detection runs against the latest user message. When triggered, the directive becomes "Train as planned. {prescribed_action}." and a `<refusal>` section is required from the LLM.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_rules.py`:

```python
class TestRefusalDetection:
    @pytest.mark.parametrize("msg", [
        "I'm gonna skip Friday's lift",
        "thinking about resting tomorrow",
        "can I take it easy today",
        "what about doing it tonight instead",
        "should I do the run later",
        "do I really have to lift today",
        "maybe I'll just do the run and skip the lift",
    ])
    def test_refusal_triggered(self, msg):
        from coach_rules import _detect_refusal
        triggered, reason = _detect_refusal(msg)
        assert triggered is True
        assert reason  # non-empty

    @pytest.mark.parametrize("msg", [
        "just finished the lift, felt great",
        "logged my run, hr was 142",
        "what's tomorrow",
        "phase 2 thursday — what's the plan",
        "",
        None,
    ])
    def test_refusal_not_triggered(self, msg):
        from coach_rules import _detect_refusal
        triggered, reason = _detect_refusal(msg)
        assert triggered is False
        assert reason is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestRefusalDetection -v`
Expected: FAIL — `ImportError: cannot import name '_detect_refusal'`.

- [ ] **Step 3: Implement refusal detection**

Append to `coach_rules.py`:

```python
import re

# Each pattern is a (regex, reason) tuple. Order matters — first match wins.
_REFUSAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(skip|skipping|skipped)\b.*\b(lift|workout|run|train)", re.I),
     "future-tense skip request"),
    (re.compile(r"\b(rest|resting|take it easy|easy day)\b.*\b(today|tomorrow|tonight)\b", re.I),
     "rest/easy-day request"),
    (re.compile(r"\b(can|could|should)\s+i\b.*\b(rest|skip|wait|delay)\b", re.I),
     "permission-to-skip"),
    (re.compile(r"\b(later|tonight|tomorrow|move it|push it|reschedule)\b.*\b(workout|run|lift|session)\b", re.I),
     "time-renegotiation"),
    (re.compile(r"\b(do i (really )?have to|do i need to|is it ok to skip)\b", re.I),
     "questioning-prescription"),
    (re.compile(r"\bshould i\b.*\b(lift|run|train|workout|do it)\b", re.I),
     "should-i-asking"),
    (re.compile(r"\bjust (do|skip)\b.*\b(the run|the lift|today|tomorrow)\b", re.I),
     "partial-compliance proposal"),
    (re.compile(r"\bmaybe i('ll| will)\b.*\b(skip|rest|just)\b", re.I),
     "soft-future skip"),
]


def _detect_refusal(latest_user_message: Optional[str]) -> tuple[bool, Optional[str]]:
    """Scan the latest user message for refusal/renegotiation patterns.

    Returns (triggered, reason). The reason is logged for telemetry and
    fed back to the LLM in the <refusal> section of the prompt.
    """
    if not latest_user_message:
        return (False, None)
    for pattern, reason in _REFUSAL_PATTERNS:
        if pattern.search(latest_user_message):
            return (True, reason)
    return (False, None)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py::TestRefusalDetection -v`
Expected: PASS — 7 triggered cases + 6 non-triggered cases.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add refusal detection to coach rules engine"
```

---

## Task 7: Directive computation — the 15-rule table

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

This is the heart of the rules engine. Given workout/run/fasting state + time, decide what the coach is telling the athlete to do *right now*. Spec §1 contains the full rule table.

- [ ] **Step 1: Write failing tests covering each rule branch**

Append to `tests/test_coach_rules.py`:

```python
class TestDirectiveComputation:
    """One test per rule in the 15-row directive table from the spec."""

    def _base_kwargs(self, **overrides):
        """Build the keyword args for _compute_directive with sensible defaults."""
        from datetime import datetime, time as dtime
        kwargs = {
            "now_local": datetime(2026, 4, 30, 6, 30, tzinfo=PACIFIC),  # Thu 6:30am
            "workout_today": None,
            "workout_today_scheduled_at": dtime(6, 0),
            "workout_today_status": "rest",
            "run_today": None,
            "run_today_status": "rest",
            "workout_tomorrow": None,
            "workout_tomorrow_scheduled_at": None,
            "run_tomorrow": None,
            "fasting_active": False,
            "weekend_fast_active": False,
            "is_pr_session": False,
            "next_target_hint": None,
            "refusal_required": False,
            "phase_summary": "Phase 2, week 5",
        }
        kwargs.update(overrides)
        return kwargs

    def _summary(self, lift="Front Squat"):
        from coach_rules import WorkoutSummary
        return WorkoutSummary(lift_name=lift, exercise_names=[lift], is_rest=False)

    def _run(self, label="Z2 30 min"):
        from coach_rules import RunSummary
        return RunSummary(run_type="z2", label=label, scheduled_at=None, detail="")

    def test_rule_1_refusal_overrides(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="not_started",
            refusal_required=True,
        ))
        assert "Train as planned" in d.text
        assert d.category == "refusal"

    def test_rule_2_in_progress(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="in_progress",
        ))
        assert "Continue" in d.text
        assert "Front Squat" in d.text

    def test_rule_3_workout_done_run_pending(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="complete",
            run_today=self._run("Z2 30 min"), run_today_status="not_started",
        ))
        assert "Run now" in d.text
        assert "Z2 30 min" in d.text

    def test_rule_4_in_window(self):
        from datetime import datetime, time as dtime
        from coach_rules import _compute_directive
        # Window is ±2h around 6 AM scheduled — 6:30 AM is in window
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 6, 30, tzinfo=PACIFIC),
            workout_today=self._summary(), workout_today_status="not_started",
            workout_today_scheduled_at=dtime(6, 0),
        ))
        assert "Lift now" in d.text
        assert "Front Squat" in d.text

    def test_rule_5_before_window(self):
        from datetime import datetime, time as dtime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 3, 30, tzinfo=PACIFIC),
            workout_today=self._summary(), workout_today_status="not_started",
            workout_today_scheduled_at=dtime(6, 0),
        ))
        assert "Lift at" in d.text or "06:00" in d.text

    def test_rule_6_after_window_missed(self):
        from datetime import datetime, time as dtime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 13, 0, tzinfo=PACIFIC),
            workout_today=self._summary(), workout_today_status="not_started",
            workout_today_scheduled_at=dtime(6, 0),
        ))
        assert "Missed" in d.text or "missed" in d.text

    def test_rule_7_sunday_long_run(self):
        from datetime import datetime
        from coach_rules import _compute_directive, RunSummary
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 5, 3, 7, 0, tzinfo=PACIFIC),  # Sunday
            workout_today=None, workout_today_status="rest",
            run_today=RunSummary(run_type="z2_long", label="Z2 long 75 min",
                                 scheduled_at=None, detail=""),
            run_today_status="not_started",
        ))
        assert "long run" in d.text.lower() or "Z2 long" in d.text

    def test_rule_8_run_pending_non_sunday(self):
        from datetime import datetime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 7, 0, tzinfo=PACIFIC),  # Thu
            workout_today=None, workout_today_status="rest",
            run_today=self._run("Z2 30 min"), run_today_status="not_started",
        ))
        assert "Run today" in d.text or "Run now" in d.text

    def test_rule_10_recovery_day(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=None, workout_today_status="rest",
            run_today=None, run_today_status="rest",
        ))
        assert "Recovery" in d.text or "recovery" in d.text

    def test_rule_11_both_complete(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="complete",
            run_today=self._run(), run_today_status="logged",
            workout_tomorrow=self._summary(lift="DB Bench"),
        ))
        assert "Tomorrow" in d.text
        assert "DB Bench" in d.text

    def test_rule_12_weekend_fast(self):
        from datetime import datetime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 5, 3, 10, 0, tzinfo=PACIFIC),  # Sunday 10am
            workout_today=None, workout_today_status="rest",
            run_today=None, run_today_status="rest",
            weekend_fast_active=True,
        ))
        assert "Fast" in d.text or "fast" in d.text
        assert "Monday" in d.text or "11" in d.text

    def test_rule_15_generic_chat(self):
        # No refusal, no workout today, no run today → fallback
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs())
        assert d.text  # non-empty
        assert d.category in {"recovery", "generic_chat"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestDirectiveComputation -v`
Expected: FAIL — `ImportError: cannot import name '_compute_directive'`.

- [ ] **Step 3: Implement directive computation**

Append to `coach_rules.py`:

```python
WORKOUT_WINDOW_HOURS = 2  # ±2h around scheduled time = "in window"


def _in_workout_window(now_local: datetime, scheduled_at: Optional[dtime]) -> str:
    """Return 'before' | 'in' | 'after' relative to ±2h window."""
    if scheduled_at is None:
        return "in"
    sched_dt = datetime.combine(now_local.date(), scheduled_at, tzinfo=PACIFIC)
    delta = (now_local - sched_dt).total_seconds() / 3600.0
    if delta < -WORKOUT_WINDOW_HOURS:
        return "before"
    if delta > WORKOUT_WINDOW_HOURS:
        return "after"
    return "in"


def _compute_directive(
    *,
    now_local: datetime,
    workout_today: Optional[WorkoutSummary],
    workout_today_scheduled_at: Optional[dtime],
    workout_today_status: str,
    run_today: Optional[RunSummary],
    run_today_status: str,
    workout_tomorrow: Optional[WorkoutSummary],
    workout_tomorrow_scheduled_at: Optional[dtime],
    run_tomorrow: Optional[RunSummary],
    fasting_active: bool,
    weekend_fast_active: bool,
    is_pr_session: bool,
    next_target_hint: Optional[str],
    refusal_required: bool,
    phase_summary: str,
) -> Directive:
    """The 15-rule directive table from the spec. First match wins."""

    # Rule 1 — refusal overrides everything
    if refusal_required:
        prescribed = (
            workout_today.lift_name if workout_today and not workout_today.is_rest
            else (run_today.label if run_today else "Recovery day")
        )
        return Directive(
            text=f"Train as planned. {prescribed}.",
            category="refusal",
        )

    # Rule 2 — workout in progress
    if workout_today_status == "in_progress" and workout_today:
        return Directive(
            text=f"Continue. Finish {workout_today.lift_name}.",
            category="workout_in_progress",
        )

    # Rule 3 — workout complete, run pending
    if workout_today_status == "complete" and run_today_status == "not_started" and run_today:
        return Directive(
            text=f"Run now. {run_today.label}.",
            category="workout_done_run_pending",
        )

    # Rule 4 — workout pending, in window
    if workout_today_status == "not_started" and workout_today and not workout_today.is_rest:
        window = _in_workout_window(now_local, workout_today_scheduled_at)
        if window == "in":
            return Directive(
                text=f"Lift now. {workout_today.lift_name}.",
                category="workout_in_window",
            )
        # Rule 5 — before window
        if window == "before":
            sched = workout_today_scheduled_at.strftime("%-I:%M %p") if workout_today_scheduled_at else ""
            return Directive(
                text=f"Lift at {sched}. {workout_today.lift_name}.",
                category="workout_before_window",
            )
        # Rule 6 — after window (missed)
        sched = workout_today_scheduled_at.strftime("%-I:%M %p") if workout_today_scheduled_at else ""
        return Directive(
            text=f"Missed the {sched} window. Lift now or move to evening. Log it.",
            category="workout_missed_window",
        )

    # Rule 7 — Sunday long run pending
    if (
        run_today
        and run_today.run_type == "z2_long"
        and run_today_status == "not_started"
    ):
        return Directive(
            text=f"Sunday long run. {run_today.label}. Fasted.",
            category="sunday_long_run",
        )

    # Rule 8 — generic run pending (non-Sunday)
    if (
        run_today
        and run_today_status == "not_started"
        and (workout_today is None or workout_today.is_rest)
    ):
        sched = (
            run_today.scheduled_at.strftime("%-I:%M %p")
            if run_today.scheduled_at else ""
        )
        suffix = f" at {sched}" if sched else ""
        return Directive(
            text=f"Run today. {run_today.label}{suffix}.",
            category="run_pending",
        )

    # Rule 11 — both complete (subsumes rule 9)
    if (
        (workout_today_status in ("complete", "rest"))
        and (run_today_status in ("logged", "rest"))
        and (workout_today_status == "complete" or run_today_status == "logged")
    ):
        if workout_tomorrow and not workout_tomorrow.is_rest:
            sched = (
                workout_tomorrow_scheduled_at.strftime("%-I:%M %p")
                if workout_tomorrow_scheduled_at else "6 AM"
            )
            return Directive(
                text=f"Done. Tomorrow: {workout_tomorrow.lift_name} at {sched}.",
                category="day_done_lift_tomorrow",
            )
        return Directive(text="Done. Recovery day tomorrow.", category="day_done_rest_tomorrow")

    # Rule 12 — weekend fast active
    if weekend_fast_active:
        return Directive(
            text="Fast holds. Break Monday 11 AM.",
            category="weekend_fast",
        )

    # Rule 13 — Sunday evening planning (only if no run pending — rule 7 caught that)
    if now_local.weekday() == 6 and now_local.hour >= 18:  # Sunday 6 PM+
        if workout_tomorrow and not workout_tomorrow.is_rest:
            sched = (
                workout_tomorrow_scheduled_at.strftime("%-I:%M %p")
                if workout_tomorrow_scheduled_at else "6 AM"
            )
            return Directive(
                text=f"Monday: {workout_tomorrow.lift_name} at {sched}. Be on the platform.",
                category="sunday_eve_plan",
            )

    # Rule 14 — PR / weight bump cue
    if is_pr_session and next_target_hint:
        return Directive(
            text=f"PR logged. Next session: {next_target_hint}.",
            category="pr_logged",
        )

    # Rule 10 — recovery day fallback
    if (
        (workout_today is None or workout_today.is_rest)
        and (run_today is None)
    ):
        return Directive(
            text="Recovery day. Eat clean, sleep early.",
            category="recovery",
        )

    # Rule 15 — generic chat
    return Directive(
        text=f"{phase_summary}. Stay on plan.",
        category="generic_chat",
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py::TestDirectiveComputation -v`
Expected: PASS — 12 directive tests.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add directive computation (15-rule table) to coach rules engine"
```

---

## Task 8: Pre-fill rendering — `<schedule>` and `<directive>` sections

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

These two strings are rendered by the rules engine and echoed verbatim into the LLM prompt and the LLM's response. Validator byte-compares the response to these strings.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_rules.py`:

```python
class TestPrefillRendering:
    def test_schedule_includes_now_and_workout_and_run(self):
        from coach_rules import _render_prefilled_schedule, WorkoutSummary, RunSummary
        from datetime import datetime, time as dtime
        s = _render_prefilled_schedule(
            now_local=datetime(2026, 4, 30, 6, 30, tzinfo=PACIFIC),
            workout_today=WorkoutSummary(
                lift_name="Front Squat", exercise_names=["Front Squat"], is_rest=False,
            ),
            workout_today_scheduled_at=dtime(6, 0),
            run_today=RunSummary(run_type="z2", label="Z2 30 min",
                                 scheduled_at=dtime(6, 45), detail=""),
            workout_tomorrow=None,
            workout_tomorrow_scheduled_at=None,
            run_tomorrow=None,
        )
        assert s.startswith("<schedule>")
        assert s.endswith("</schedule>")
        assert "Thursday" in s
        assert "06:30" in s or "6:30" in s
        assert "Front Squat" in s
        assert "Z2 30 min" in s

    def test_directive_renders_clean(self):
        from coach_rules import _render_prefilled_directive, Directive
        s = _render_prefilled_directive(
            Directive(text="Lift now. Front Squat.", category="workout_in_window")
        )
        assert s == "<directive>Lift now. Front Squat.</directive>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestPrefillRendering -v`
Expected: FAIL — `ImportError: cannot import name '_render_prefilled_schedule'`.

- [ ] **Step 3: Implement renderers**

Append to `coach_rules.py`:

```python
def _render_prefilled_schedule(
    *,
    now_local: datetime,
    workout_today: Optional[WorkoutSummary],
    workout_today_scheduled_at: Optional[dtime],
    run_today: Optional[RunSummary],
    workout_tomorrow: Optional[WorkoutSummary],
    workout_tomorrow_scheduled_at: Optional[dtime],
    run_tomorrow: Optional[RunSummary],
) -> str:
    """Build the <schedule>...</schedule> block. Echoed byte-identical
    by the LLM. Validator rejects any drift."""
    lines = ["<schedule>"]
    weekday = now_local.strftime("%A")
    date_str = now_local.strftime("%Y-%m-%d")
    time_str = now_local.strftime("%H:%M")
    lines.append(f"Now: {weekday} {date_str} {time_str} Pacific")

    if workout_today is None:
        lines.append("Today workout: (none)")
    elif workout_today.is_rest:
        lines.append("Today workout: REST")
    else:
        sched = workout_today_scheduled_at.strftime("%H:%M") if workout_today_scheduled_at else "(unscheduled)"
        lines.append(f"Today workout: {workout_today.lift_name} at {sched}")

    if run_today is None:
        lines.append("Today run: (none)")
    else:
        sched = run_today.scheduled_at.strftime("%H:%M") if run_today.scheduled_at else "(unscheduled)"
        lines.append(f"Today run: {run_today.label} at {sched}")

    if workout_tomorrow is None:
        lines.append("Tomorrow workout: (none)")
    elif workout_tomorrow.is_rest:
        lines.append("Tomorrow workout: REST")
    else:
        sched = workout_tomorrow_scheduled_at.strftime("%H:%M") if workout_tomorrow_scheduled_at else "(unscheduled)"
        lines.append(f"Tomorrow workout: {workout_tomorrow.lift_name} at {sched}")

    if run_tomorrow is None:
        lines.append("Tomorrow run: (none)")
    else:
        sched = run_tomorrow.scheduled_at.strftime("%H:%M") if run_tomorrow.scheduled_at else "(unscheduled)"
        lines.append(f"Tomorrow run: {run_tomorrow.label} at {sched}")

    lines.append("</schedule>")
    return "\n".join(lines)


def _render_prefilled_directive(directive: Directive) -> str:
    """Build the <directive>...</directive> block on a single line."""
    return f"<directive>{directive.text}</directive>"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py::TestPrefillRendering -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add pre-fill rendering for <schedule> and <directive> sections"
```

---

## Task 9: `compute_coach_rules` orchestration

**Files:**
- Modify: `coach_rules.py`
- Test: `tests/test_coach_rules.py`

Top-level entry. Pulls together all helpers + DB reads + builds the frozen `CoachRules` dataclass.

- [ ] **Step 1: Write failing test**

Append to `tests/test_coach_rules.py`:

```python
class TestComputeCoachRulesEnd:
    def _make_user(self, app_ctx):
        from models import User, UserEquipment, PhysicalAssessment
        app, db = app_ctx
        u = User(email=f"end-{id(self)}@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "lat_pulldown", "cable_machine",
            "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
            "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
            "dip_station", "ab_machine", "smith_machine",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq); db.session.add(pa); db.session.commit()
        return u

    def test_end_to_end_thursday_morning(self, app_ctx):
        from coach_rules import compute_coach_rules
        from datetime import datetime
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        # Thu 2026-04-30 = day_idx 3, week 5 (per Erik's calendar). Engine
        # doesn't know about external calendar; we just verify the rules
        # built compose into a valid CoachRules object with non-empty
        # pre-filled sections and a directive.
        with app.test_request_context():
            rules = compute_coach_rules(
                user_id=u.id,
                now=datetime(2026, 4, 30, 13, 30),  # naive UTC
                latest_user_message=None,
            )
        assert rules.local_weekday in {
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        }
        assert rules.prefilled_schedule.startswith("<schedule>")
        assert rules.prefilled_directive.startswith("<directive>")
        assert rules.directive.text  # non-empty
        assert rules.refusal_required is False

    def test_refusal_propagates_to_directive_and_flag(self, app_ctx):
        from coach_rules import compute_coach_rules
        from datetime import datetime
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            rules = compute_coach_rules(
                user_id=u.id,
                now=datetime(2026, 4, 30, 13, 30),
                latest_user_message="thinking about resting tomorrow",
            )
        assert rules.refusal_required is True
        assert rules.refusal_reason
        assert "Train as planned" in rules.directive.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_rules.py::TestComputeCoachRulesEnd -v`
Expected: FAIL — `ImportError: cannot import name 'compute_coach_rules'`.

- [ ] **Step 3: Implement orchestration**

Append to `coach_rules.py`:

```python
def _current_week_for_user(user_id: int, today_local) -> int:
    """Return the user's current 12-week phase week. Mirrors logic in
    coach_assembler._current_week — read from User.start_date."""
    from models import User
    from datetime import date as date_cls
    user = User.query.get(user_id)
    if not user or not getattr(user, "program_start_date", None):
        return 1
    delta_days = (today_local - user.program_start_date).days
    week = max(1, min(12, (delta_days // 7) + 1))
    return week


def _phase_summary_for_week(week: int) -> str:
    if week <= 4:
        return f"Phase 1 (week {week})"
    if week <= 8:
        return f"Phase 2 (week {week})"
    if week == 9:
        return f"Deload (week {week})"
    return f"Phase 3 (week {week})"


def compute_coach_rules(
    user_id: int,
    now: Optional[datetime] = None,
    latest_user_message: Optional[str] = None,
) -> CoachRules:
    """Top-level entry. Pure function (modulo DB reads).

    Args:
        user_id: The athlete's user ID.
        now: Override clock (UTC, tz-aware). Production passes None.
        latest_user_message: The user's latest chat message (for refusal scan).
    """
    now_local = _user_local_now(now)
    today = now_local.date()
    weekday_idx = now_local.weekday()  # Mon=0
    tomorrow_idx = (weekday_idx + 1) % 7
    week = _current_week_for_user(user_id, today)
    next_week = week + 1 if tomorrow_idx == 0 else week  # rolls Sunday→Monday

    # Workout today
    workout_today = _resolve_workout_for_day_summary(user_id, week, weekday_idx)
    is_rest_today = bool(workout_today and workout_today.is_rest) or workout_today is None
    workout_today_scheduled_at = _compute_workout_scheduled_at(user_id, is_rest_today)
    workout_today_status = _compute_workout_status(
        user_id, week, weekday_idx, today, is_rest_today,
    )

    # Workout tomorrow
    workout_tomorrow = _resolve_workout_for_day_summary(user_id, next_week, tomorrow_idx)
    is_rest_tomorrow = bool(workout_tomorrow and workout_tomorrow.is_rest) or workout_tomorrow is None
    workout_tomorrow_scheduled_at = _compute_workout_scheduled_at(user_id, is_rest_tomorrow)

    # Run today / tomorrow
    run_today = _resolve_run_for_day(week, weekday_idx)
    run_today_status = _compute_run_status(user_id, today, run_planned=run_today is not None)
    run_tomorrow = _resolve_run_for_day(next_week, tomorrow_idx)

    # Fasting
    fasting = _compute_fasting_state(now_local)

    # Refusal
    refusal_required, refusal_reason = _detect_refusal(latest_user_message)

    # Directive
    directive = _compute_directive(
        now_local=now_local,
        workout_today=workout_today,
        workout_today_scheduled_at=workout_today_scheduled_at,
        workout_today_status=workout_today_status,
        run_today=run_today,
        run_today_status=run_today_status,
        workout_tomorrow=workout_tomorrow,
        workout_tomorrow_scheduled_at=workout_tomorrow_scheduled_at,
        run_tomorrow=run_tomorrow,
        fasting_active=fasting.fasting_active,
        weekend_fast_active=(fasting.fasting_active and fasting.fasting_target_hours == 40),
        is_pr_session=False,  # v1 — wire PR detection in v2
        next_target_hint=None,
        refusal_required=refusal_required,
        phase_summary=_phase_summary_for_week(week),
    )

    prefilled_schedule = _render_prefilled_schedule(
        now_local=now_local,
        workout_today=workout_today,
        workout_today_scheduled_at=workout_today_scheduled_at,
        run_today=run_today,
        workout_tomorrow=workout_tomorrow,
        workout_tomorrow_scheduled_at=workout_tomorrow_scheduled_at,
        run_tomorrow=run_tomorrow,
    )
    prefilled_directive = _render_prefilled_directive(directive)

    return CoachRules(
        now_utc=now_local.astimezone(timezone.utc),
        now_local=now_local,
        local_date_iso=now_local.strftime("%Y-%m-%d"),
        local_weekday=now_local.strftime("%A"),
        local_time_hhmm=now_local.strftime("%H:%M"),
        workout_today=workout_today,
        workout_today_scheduled_at=workout_today_scheduled_at,
        workout_today_status=workout_today_status,
        run_today=run_today,
        run_today_status=run_today_status,
        workout_tomorrow=workout_tomorrow,
        workout_tomorrow_scheduled_at=workout_tomorrow_scheduled_at,
        run_tomorrow=run_tomorrow,
        fasting_active=fasting.fasting_active,
        fasting_hours=fasting.fasting_hours,
        fasting_target_hours=fasting.fasting_target_hours,
        fasting_break_at=fasting.fasting_break_at,
        directive=directive,
        refusal_required=refusal_required,
        refusal_reason=refusal_reason,
        prefilled_schedule=prefilled_schedule,
        prefilled_directive=prefilled_directive,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_rules.py -v`
Expected: PASS — entire `tests/test_coach_rules.py` green.

- [ ] **Step 5: Commit**

```bash
git add coach_rules.py tests/test_coach_rules.py
git commit -m "Add compute_coach_rules orchestration entry point"
```

---

## Task 10: `coach_validator.py` — envelope parsing + banned-phrase scan + fallback

**Files:**
- Create: `coach_validator.py`
- Test: `tests/test_coach_validator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_coach_validator.py`:

```python
"""Unit tests for the coach response validator."""
import pytest


class TestParseEnvelope:
    def test_parses_required_sections(self):
        from coach_validator import parse_envelope
        raw = (
            "<schedule>X</schedule>\n"
            "<directive>Y</directive>\n"
            "<motivation>Z</motivation>\n"
        )
        s = parse_envelope(raw)
        assert s["schedule"] == "X"
        assert s["directive"] == "Y"
        assert s["motivation"] == "Z"
        assert "refusal" not in s

    def test_parses_optional_refusal(self):
        from coach_validator import parse_envelope
        raw = (
            "<schedule>X</schedule>\n"
            "<directive>Y</directive>\n"
            "<motivation>Z</motivation>\n"
            "<refusal>No.</refusal>\n"
        )
        s = parse_envelope(raw)
        assert s["refusal"] == "No."

    def test_returns_empty_dict_on_garbage(self):
        from coach_validator import parse_envelope
        s = parse_envelope("not an envelope")
        assert s == {}


class TestBannedPhraseScan:
    @pytest.mark.parametrize("phrase", [
        "your call",
        "if you feel up to it",
        "great job",
        "would you like",
        "let's see how",
    ])
    def test_catches_banned(self, phrase):
        from coach_validator import scan_banned_phrases
        result = scan_banned_phrases(f"Hey, {phrase} out there.")
        assert result == phrase

    def test_passes_clean_text(self):
        from coach_validator import scan_banned_phrases
        assert scan_banned_phrases("Lift now. Front Squat.") is None


class TestQuestionScan:
    def test_catches_question(self):
        from coach_validator import scan_questions
        assert scan_questions("How did that feel?") is True

    def test_passes_statement(self):
        from coach_validator import scan_questions
        assert scan_questions("Front Squat 5x5 at 175. Log it.") is False


class TestValidateResponse:
    def _ok_envelope(self):
        return (
            "<schedule>S</schedule>\n"
            "<directive>D</directive>\n"
            "<motivation>Lift now. Stay tight.</motivation>\n"
        )

    def test_valid_response_passes(self):
        from coach_validator import validate_response
        result = validate_response(
            raw=self._ok_envelope(),
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is True

    def test_altered_schedule_fails(self):
        from coach_validator import validate_response
        result = validate_response(
            raw=self._ok_envelope().replace("<schedule>S</schedule>", "<schedule>WRONG</schedule>"),
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is False
        assert "schedule" in result.failure_reason.lower()

    def test_banned_phrase_in_motivation_fails(self):
        from coach_validator import validate_response
        raw = (
            "<schedule>S</schedule>\n"
            "<directive>D</directive>\n"
            "<motivation>Great job today!</motivation>\n"
        )
        result = validate_response(
            raw=raw,
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is False
        assert "great job" in result.failure_reason.lower()

    def test_question_in_motivation_fails(self):
        from coach_validator import validate_response
        raw = (
            "<schedule>S</schedule>\n"
            "<directive>D</directive>\n"
            "<motivation>How did that feel.</motivation>\n"  # period stripped, but...
            ""
        )
        # actually inject a real question
        raw = raw.replace("How did that feel.", "How did that feel?")
        result = validate_response(
            raw=raw,
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is False
        assert "question" in result.failure_reason.lower()

    def test_missing_required_refusal_fails(self):
        from coach_validator import validate_response
        result = validate_response(
            raw=self._ok_envelope(),
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=True,  # but no <refusal> in raw
        )
        assert result.ok is False
        assert "refusal" in result.failure_reason.lower()


class TestDeterministicFallback:
    def test_renders_basic(self):
        from coach_validator import deterministic_fallback
        out = deterministic_fallback(
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert "S" in out
        assert "D" in out
        assert "?" not in out

    def test_includes_refusal_when_required(self):
        from coach_validator import deterministic_fallback
        out = deterministic_fallback(
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>Train as planned.</directive>",
            refusal_required=True,
        )
        assert "Train as planned" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_validator.py -v`
Expected: FAIL — `ImportError: No module named 'coach_validator'`.

- [ ] **Step 3: Implement validator**

Create `coach_validator.py`:

```python
"""Coach response validator.

Parses the LLM's sectioned response, byte-compares pre-filled sections,
scans banned phrases and questions, returns a ValidationResult.

The retry logic + deterministic fallback are also defined here so the
orchestrator (coach_assembler.coach_respond) can call them cleanly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Hand-curated. Update via PR — never auto-add.
BANNED_PHRASES: list[str] = [
    # Capitulation
    "your call", "if you feel up to it", "if you want", "feel free to",
    "no pressure", "up to you", "whatever works", "however you want",
    # Cheerleading
    "great job", "amazing work", "you're doing great", "proud of you",
    "love it", "crushing it", "killing it", "way to go", "fantastic", "incredible",
    # Collaborative questions
    "would you like", "do you want", "should we", "ready to", "shall we",
    "want me to", "how about",
    # Future-tense softening
    "we could", "we might", "you might consider", "perhaps", "maybe try",
    # Negotiation
    "if that works", "let's see how", "see how you feel", "play it by ear",
    "if you're up for it",
]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    sections: dict = field(default_factory=dict)
    failure_reason: Optional[str] = None


_SECTION_RE = re.compile(
    r"<(schedule|directive|motivation|refusal)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)


def parse_envelope(raw: str) -> dict[str, str]:
    """Extract section name → content from the LLM's response.

    Returns {} on garbage. Newlines and surrounding whitespace inside each
    section are preserved, but stripped of leading/trailing whitespace.
    """
    out: dict[str, str] = {}
    for m in _SECTION_RE.finditer(raw or ""):
        name = m.group(1).lower()
        out[name] = m.group(2).strip()
    return out


def scan_banned_phrases(text: str) -> Optional[str]:
    """Return the first matching banned phrase (case-insensitive) or None."""
    if not text:
        return None
    lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            return phrase
    return None


def scan_questions(text: str) -> bool:
    """True if `text` contains a question mark. Cheap and aggressive."""
    return "?" in (text or "")


def validate_response(
    *,
    raw: str,
    prefilled_schedule: str,
    prefilled_directive: str,
    refusal_required: bool,
) -> ValidationResult:
    """Validate a single LLM response against the rules contract.

    Returns ValidationResult(ok=True, sections=...) on success,
    or ValidationResult(ok=False, failure_reason=...) on first failure.
    """
    sections = parse_envelope(raw)

    # 1. Required sections present
    missing = [k for k in ("schedule", "directive", "motivation") if k not in sections]
    if missing:
        return ValidationResult(ok=False, failure_reason=f"missing section(s): {missing}")

    # 2. Pre-filled byte equality (strip the outer tags before comparing inner content)
    schedule_inner = _strip_outer_tag(prefilled_schedule, "schedule")
    directive_inner = _strip_outer_tag(prefilled_directive, "directive")
    if sections["schedule"].strip() != schedule_inner.strip():
        return ValidationResult(ok=False, failure_reason="schedule altered from pre-fill")
    if sections["directive"].strip() != directive_inner.strip():
        return ValidationResult(ok=False, failure_reason="directive altered from pre-fill")

    # 3. Banned-phrase scan
    bp = scan_banned_phrases(sections.get("motivation", ""))
    if bp:
        return ValidationResult(ok=False, failure_reason=f"banned phrase in motivation: '{bp}'")
    bp = scan_banned_phrases(sections.get("refusal", ""))
    if bp:
        return ValidationResult(ok=False, failure_reason=f"banned phrase in refusal: '{bp}'")

    # 4. Question-mark scan
    if scan_questions(sections.get("motivation", "")):
        return ValidationResult(ok=False, failure_reason="motivation contains a question mark")
    if scan_questions(sections.get("refusal", "")):
        return ValidationResult(ok=False, failure_reason="refusal contains a question mark")

    # 5. Refusal required iff section present
    if refusal_required and "refusal" not in sections:
        return ValidationResult(ok=False, failure_reason="refusal required but not provided")

    return ValidationResult(ok=True, sections=sections)


def deterministic_fallback(
    *,
    prefilled_schedule: str,
    prefilled_directive: str,
    refusal_required: bool,
) -> str:
    """Austere fallback when the LLM fails validation twice. Pure rules
    output, no motivation, no flourish. Better than capitulation."""
    schedule_inner = _strip_outer_tag(prefilled_schedule, "schedule")
    directive_inner = _strip_outer_tag(prefilled_directive, "directive")
    parts = [schedule_inner.strip(), directive_inner.strip(), "Logged."]
    if refusal_required:
        parts.append("Plan stands.")
    return "\n\n".join(parts)


def _strip_outer_tag(s: str, tag: str) -> str:
    """Remove leading <tag> and trailing </tag>, preserving inner content."""
    s = s.strip()
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    if s.startswith(open_tag):
        s = s[len(open_tag):]
    if s.endswith(close_tag):
        s = s[:-len(close_tag)]
    return s
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_validator.py -v`
Expected: PASS — all validator tests green.

- [ ] **Step 5: Commit**

```bash
git add coach_validator.py tests/test_coach_validator.py
git commit -m "Add coach_validator: envelope parser, banned-phrase scan, fallback"
```

---

## Task 11: Replace `_build_chat_history` with `_build_event_timeline`

**Files:**
- Modify: `coach_assembler.py:102-133` (deleting `_build_chat_history`, adding new builders)
- Test: `tests/test_coach_assembler.py` (new file)

The new event timeline pulls from canonical tables only. Past coach messages no longer feed the prompt — except a tight "last 3 today" slice.

- [ ] **Step 1: Write failing tests**

Create `tests/test_coach_assembler.py`:

```python
"""Tests for the rewritten coach_assembler section builders."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


def _make_user(app_ctx):
    from models import User, UserEquipment, PhysicalAssessment
    app, db = app_ctx
    _USER_SEQ[0] += 1
    u = User(email=f"asm-{_USER_SEQ[0]}@example.com", password_hash="x")
    db.session.add(u); db.session.commit()
    eq = UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells"])
    pa = PhysicalAssessment(user_id=u.id, has_gym=True)
    db.session.add(eq); db.session.add(pa); db.session.commit()
    return u


class TestEventTimeline:
    def test_empty_timeline_returns_sentinel(self, app_ctx):
        from coach_assembler import _build_event_timeline
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            out = _build_event_timeline(u.id, days_back=7)
        assert "<event_timeline>" in out
        assert "NONE" in out

    def test_includes_set_log_events(self, app_ctx):
        from coach_assembler import _build_event_timeline
        from models import SetLog
        from datetime import date
        from app import db
        app, _ = app_ctx
        u = _make_user(app_ctx)
        db.session.add(SetLog(
            user_id=u.id, exercise_name="Front Squat", week=5, day_idx=0,
            set_number=1, weight=175, reps=5, done=True, logged_date=date.today(),
        ))
        db.session.commit()
        with app.test_request_context():
            out = _build_event_timeline(u.id, days_back=7)
        assert "Front Squat" in out
        assert "175" in out


class TestRecentCoachDirectives:
    def test_returns_only_today(self, app_ctx):
        from coach_assembler import _build_recent_coach_directives
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            out = _build_recent_coach_directives(u.id)
        assert "<recent_coach_directives>" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_assembler.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_event_timeline'`.

- [ ] **Step 3: Add `_build_event_timeline` and `_build_recent_coach_directives`**

In `coach_assembler.py`, find the `_build_chat_history` function at line ~102. Replace it with the two new builders below. Keep `_build_chat_history` removed (do not leave a deprecation stub — the spec says big-bang rewrite).

```python
def _build_event_timeline(user_id, days_back=7):
    """Structured ground-truth ledger from canonical logs.

    Replaces _build_chat_history. Past coach messages no longer feed the
    prompt — only events that *actually happened* (logged sets, runs,
    weigh-ins, fast breaks). This eliminates the hallucination-persistence
    failure mode documented in the audit.
    """
    from datetime import date, timedelta
    from models import SetLog, RunLog, BodyMeasurement
    cutoff = date.today() - timedelta(days=days_back)
    events: list[tuple] = []   # (timestamp_str, line)

    # Sets
    sets = SetLog.query.filter(
        SetLog.user_id == user_id,
        SetLog.logged_date >= cutoff,
    ).order_by(SetLog.logged_date.desc(), SetLog.id.asc()).limit(200).all()
    # Group by (logged_date, exercise_name) — one line per exercise per day
    grouped: dict[tuple, list] = {}
    for s in sets:
        key = (s.logged_date, s.exercise_name)
        grouped.setdefault(key, []).append(s)
    for (d, name), rows in grouped.items():
        sets_str = ", ".join(f"{r.set_number}: {r.weight}x{r.reps}" for r in rows)
        events.append((str(d), f"[{d}] LIFT {name}: {sets_str}"))

    # Runs
    runs = RunLog.query.filter(
        RunLog.user_id == user_id,
        RunLog.run_date >= cutoff,
    ).order_by(RunLog.run_date.desc()).limit(50).all()
    for r in runs:
        dist = getattr(r, "distance_miles", None) or "?"
        hr = getattr(r, "avg_hr", None) or "?"
        events.append((str(r.run_date),
                       f"[{r.run_date}] RUN {dist}mi avg HR {hr}"))

    # Weigh-ins
    weighs = BodyMeasurement.query.filter(
        BodyMeasurement.user_id == user_id,
        BodyMeasurement.measurement_date >= cutoff,
    ).order_by(BodyMeasurement.measurement_date.desc()).limit(20).all()
    for w in weighs:
        events.append((str(w.measurement_date),
                       f"[{w.measurement_date}] WEIGH-IN {w.weight} lb"))

    if not events:
        return "<event_timeline>\nNONE — athlete has no logged events in the last 7 days. Do not reference any.\n</event_timeline>"

    events.sort(key=lambda e: e[0], reverse=True)
    body = "\n".join(line for _, line in events)
    return f"<event_timeline>\n{body}\n</event_timeline>"


def _build_recent_coach_directives(user_id):
    """The coach's last 3 messages, today only. Provides continuity without
    perpetuating week-old hallucinations."""
    from datetime import date
    from models import ChatMessage
    msgs = (ChatMessage.query
            .filter_by(user_id=user_id, role="assistant", log_date=date.today())
            .order_by(ChatMessage.id.desc())
            .limit(3)
            .all())
    if not msgs:
        return "<recent_coach_directives>\nNONE — no coach messages today.\n</recent_coach_directives>"
    body = "\n---\n".join(m.content for m in reversed(msgs))
    return f"<recent_coach_directives>\n{body}\n</recent_coach_directives>"
```

Then **delete** the old `_build_chat_history` body. Anything else that calls it must be updated to call `_build_event_timeline` (search and update — likely the section_builder registry and `build_filtered_context` / `_format_athlete_data`).

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_assembler.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py tests/test_coach_assembler.py
git commit -m "Replace _build_chat_history with structured event timeline"
```

---

## Task 12: Sentinels in section builders + 21-day window for coach memories

**Files:**
- Modify: `coach_assembler.py` — `_build_runs` (line 428), `_build_exercise_history` (line 322), `_build_meals_today` (line 469), `_build_garmin` (line 145), `_build_coach_memories` (line 627)
- Test: `tests/test_coach_assembler.py`

Empty sections currently return empty string and are dropped from the prompt. The LLM fills the void with hallucination. Fix: every empty section emits an explicit "NONE — do not reference" sentinel.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_assembler.py`:

```python
class TestEmptySectionSentinels:
    def test_runs_empty_emits_sentinel(self, app_ctx):
        from coach_assembler import _build_runs
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_runs()
        assert "<runs>" in out
        assert "NONE" in out
        assert "Do not reference" in out

    def test_coach_memories_filtered_to_21_days(self, app_ctx):
        from coach_assembler import _build_coach_memories
        from models import CoachMemory
        from datetime import datetime, timedelta
        from app import db
        app, _ = app_ctx
        u = _make_user(app_ctx)
        # Old memory (40 days ago) — must be excluded
        old = CoachMemory(
            user_id=u.id, content="old memory",
            memory_type="event", week=1,
        )
        # SQLAlchemy default sets created_at=now; we need to override.
        old.created_at = datetime.utcnow() - timedelta(days=40)
        new = CoachMemory(
            user_id=u.id, content="recent memory",
            memory_type="event", week=5,
        )
        db.session.add(old); db.session.add(new); db.session.commit()
        with app.test_request_context():
            from flask_login import login_user
            login_user(u, force=True)
            out = _build_coach_memories()
        assert "recent memory" in out
        assert "old memory" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_assembler.py::TestEmptySectionSentinels -v`
Expected: FAIL.

- [ ] **Step 3: Update section builders to emit sentinels and time-window memories**

In `coach_assembler.py`, locate each builder and apply the sentinel pattern. For `_build_runs` (line 428):

```python
def _build_runs():
    from datetime import date, timedelta
    from models import RunLog
    from flask_login import current_user
    if not current_user.is_authenticated:
        return "<runs>\nNONE — not authenticated.\n</runs>"
    cutoff = date.today() - timedelta(days=14)
    rows = (RunLog.query
            .filter(RunLog.user_id == current_user.id, RunLog.run_date >= cutoff)
            .order_by(RunLog.run_date.desc())
            .limit(14).all())
    if not rows:
        return "<runs>\nNONE — no runs logged in the last 14 days. Do not reference any run.\n</runs>"
    lines = [f"[{r.run_date}] {getattr(r, 'distance_miles', '?')}mi" for r in rows]
    return "<runs>\n" + "\n".join(lines) + "\n</runs>"
```

Apply the same pattern to `_build_exercise_history`, `_build_meals_today`, `_build_garmin`. Each empty case emits a `<section>NONE — explanation. Do not reference.</section>` sentinel.

For `_build_coach_memories` (line 627):

```python
def _build_coach_memories():
    from datetime import datetime, timedelta
    from models import CoachMemory
    from flask_login import current_user
    if not current_user.is_authenticated:
        return "<coach_memories>\nNONE — not authenticated.\n</coach_memories>"
    cutoff = datetime.utcnow() - timedelta(days=21)
    rows = (CoachMemory.query
            .filter(CoachMemory.user_id == current_user.id, CoachMemory.created_at >= cutoff)
            .order_by(CoachMemory.created_at.desc())
            .limit(50).all())
    if not rows:
        return "<coach_memories>\nNONE — no memories in the last 21 days.\n</coach_memories>"
    lines = [f"- {m.content}" for m in rows]
    return "<coach_memories>\n" + "\n".join(lines) + "\n</coach_memories>"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_assembler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py tests/test_coach_assembler.py
git commit -m "Empty sections emit sentinels; coach memories windowed to 21 days"
```

---

## Task 13: Rewrite `CORE_PROMPT`

**Files:**
- Modify: `coach_assembler.py:808-903` (the `CORE_PROMPT` constant)
- Test: `tests/test_coach_assembler.py`

The new CORE_PROMPT defines the envelope contract, citation rule, posture, and banned phrases. It does NOT contain "ask the user" instructions.

- [ ] **Step 1: Write failing test**

Append to `tests/test_coach_assembler.py`:

```python
class TestCorePrompt:
    def test_includes_envelope_contract(self):
        from coach_assembler import CORE_PROMPT
        assert "<schedule>" in CORE_PROMPT
        assert "<directive>" in CORE_PROMPT
        assert "<motivation>" in CORE_PROMPT
        assert "<refusal>" in CORE_PROMPT

    def test_includes_byte_identical_instruction(self):
        from coach_assembler import CORE_PROMPT
        assert "byte" in CORE_PROMPT.lower() or "echo" in CORE_PROMPT.lower()

    def test_no_ask_questions_instruction(self):
        from coach_assembler import CORE_PROMPT
        # The new CORE_PROMPT must not instruct the LLM to ask questions
        forbidden = ["ask the athlete", "ask one question", "ask what they"]
        for phrase in forbidden:
            assert phrase not in CORE_PROMPT.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_assembler.py::TestCorePrompt -v`
Expected: FAIL.

- [ ] **Step 3: Replace CORE_PROMPT**

In `coach_assembler.py`, locate `CORE_PROMPT = """\` at line 808. Replace the entire string (through its closing `"""` around line 903) with:

```python
CORE_PROMPT = """\
You are Erik's strength coach. Lombardi/Saban posture: you decide, athlete executes.

# OUTPUT CONTRACT — REQUIRED

You MUST emit your response as four (or three) tagged sections, in order:

<schedule>...</schedule>
<directive>...</directive>
<motivation>...</motivation>
<refusal>...</refusal>   # only when instructed by the rules engine

The <schedule> and <directive> sections will be PRE-FILLED for you in this
prompt. You MUST echo them back BYTE-IDENTICAL — same content, same line breaks,
same tags. The validator rejects any drift. Do not paraphrase, summarize, or
"clean up" these sections.

<motivation> is YOUR section. 1-3 sentences. Voice only. NO questions. NO
banned phrases (see below).

<refusal> appears ONLY when the rules engine in the prompt sets
refusal_required=true. When it does, your <refusal> echoes the directive
and names the deviation. NO negotiation. NO questions.

# CITATION RULE

Every claim in <motivation> must reference a specific field from
<athlete_data>. If the athlete_data section is missing or marked NONE, do
not reference it. Hallucinations are unacceptable.

# BANNED PHRASES

These cause validation failure. Do NOT use them anywhere:
- "your call", "if you feel up to it", "if you want", "feel free to", "no pressure", "up to you"
- "great job", "amazing work", "you're doing great", "proud of you", "love it", "crushing it"
- "would you like", "do you want", "should we", "ready to", "shall we"
- "we could", "we might", "perhaps", "maybe try"
- "if that works", "let's see how", "see how you feel"

# POSTURE

- Statements, not questions. The coach decides; the athlete executes.
- Tight prose. No filler. No exclamation marks unless the athlete just PR'd.
- Reference logged events, not invented ones. If the timeline is empty, say so.
- Do not soften the directive. Do not negotiate.

# WHAT YOU SEE

The user message is wrapped in <latest_user_message>. The pre-filled
<schedule> and <directive> tell you what's happening and what to instruct.
The <event_timeline> is ground truth from logs — past coach messages are
NOT in scope. <recent_coach_directives> shows your last 3 messages today
for continuity only.
"""
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_assembler.py::TestCorePrompt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py tests/test_coach_assembler.py
git commit -m "Rewrite CORE_PROMPT with envelope contract and banned phrases"
```

---

## Task 14: Rewrite `PROTOCOL_MAP` + `coach_agents.py` cleanup

**Files:**
- Modify: `coach_assembler.py:904-1106` (the `PROTOCOL_MAP` dict)
- Modify: `coach_agents.py` — replace per-agent `requires` with `ALL_SECTIONS`, lower `weekly_review` temp 1.0 → 0.6
- Test: `tests/test_coach_assembler.py`

Each agent's protocol becomes a `<motivation>` style guide ONLY. All "Ask the user" instructions are deleted.

- [ ] **Step 1: Write failing test**

Append to `tests/test_coach_assembler.py`:

```python
class TestProtocolMap:
    def test_no_protocol_asks_questions(self):
        from coach_assembler import PROTOCOL_MAP
        for agent, protocol in PROTOCOL_MAP.items():
            assert "ask one question" not in protocol.lower(), agent
            assert "ask the athlete" not in protocol.lower(), agent
            assert "ask what they" not in protocol.lower(), agent

    def test_all_agents_have_protocol(self):
        from coach_assembler import PROTOCOL_MAP
        from coach_agents import AGENTS
        for agent in AGENTS:
            assert agent in PROTOCOL_MAP, f"missing protocol for {agent}"


class TestCoachAgentsConfig:
    def test_all_temps_are_06(self):
        from coach_agents import AGENTS
        for agent, cfg in AGENTS.items():
            if agent == "crisis":
                continue
            assert cfg["temperature"] == 0.6, f"{agent} has temp {cfg['temperature']}"

    def test_all_agents_use_all_sections(self):
        from coach_agents import AGENTS, ALL_SECTIONS
        for agent, cfg in AGENTS.items():
            if agent == "crisis":
                continue
            assert cfg["requires"] == ALL_SECTIONS, agent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_assembler.py::TestProtocolMap tests/test_coach_assembler.py::TestCoachAgentsConfig -v`
Expected: FAIL.

- [ ] **Step 3a: Replace PROTOCOL_MAP**

In `coach_assembler.py`, locate `PROTOCOL_MAP = {` at line 904. Replace the entire dict with:

```python
PROTOCOL_MAP = {
    "conversation": (
        "Voice for <motivation>: respond to the athlete's message in 1-3 sentences. "
        "Reference one specific field from <event_timeline> or <athlete_data>. "
        "End with a statement, not a question."
    ),
    "morning_checkin": (
        "Voice for <motivation>: acknowledge the check-in numbers (sleep, weight, mood). "
        "Tie to today's directive. Statement, not question."
    ),
    "morning_briefing": (
        "Voice for <motivation>: terse — 1 sentence. Cite today's lift and run. "
        "No questions."
    ),
    "weekly_planning": (
        "Voice for <motivation>: anchor on the week's goal (cut to 185). State "
        "the most important focus for the week. Reference last week's session count. "
        "No questions."
    ),
    "weekly_review": (
        "Voice for <motivation>: 2-3 sentences. Cite weekly_summary numbers "
        "(sessions completed, weight delta, run miles). Statement only."
    ),
    "workout_feedback": (
        "Voice for <motivation>: 1-2 sentences acknowledging the lift just logged. "
        "Cite a specific set from <event_timeline>. Tie to next session's progression. "
        "No questions."
    ),
    "run_complete": (
        "Voice for <motivation>: 1 sentence. Cite the run from <event_timeline>. "
        "Tie to the cut. Statement only."
    ),
    "meals_complete": (
        "Voice for <motivation>: 1 sentence acknowledging meals logged. Tie to "
        "calorie target. No questions."
    ),
    "end_of_day": (
        "Voice for <motivation>: 1-2 sentences. Cite today's compliance "
        "(workout done? run done? meals?). State tomorrow's focus."
    ),
    "chat_opened": (
        "Voice for <motivation>: 1-2 sentences. Reference the directive and "
        "<event_timeline>'s most recent event. No greeting questions."
    ),
    "crisis": (
        "Voice for <motivation>: drop posture. Be direct, supportive, brief. "
        "Suggest concrete next step. No banned phrases still applies."
    ),
}
```

- [ ] **Step 3b: Update `coach_agents.py`**

Replace the entire contents of `coach_agents.py` with:

```python
"""Agent definitions for the coaching system.

Each agent specifies max_tokens and temperature. The `requires` list is the
constant ALL_SECTIONS — every agent gets every section. Agent-specific
opting-out caused the 15.6h-fast hallucination (see audit 2026-04-30).
"""

ALL_SECTIONS = [
    "base", "checkins", "event_timeline", "recent_coach_directives",
    "workout_today", "workout_tomorrow", "week_schedule",
    "exercise_history", "exercise_analysis", "today_sets",
    "runs", "physical", "bodyweight", "garmin",
    "meals_today", "fasting", "food_safety", "goal",
    "coach_memories", "user_rules",
    "completed_days", "overrides", "next_week",
    "session_analysis", "missed_checkin", "intake", "supplements", "equipment",
]


AGENTS = {
    "conversation":      {"max_tokens": 800, "temperature": 0.6, "requires": ALL_SECTIONS},
    "morning_checkin":   {"max_tokens": 400, "temperature": 0.6, "requires": ALL_SECTIONS},
    "morning_briefing":  {"max_tokens": 300, "temperature": 0.6, "requires": ALL_SECTIONS},
    "weekly_planning":   {"max_tokens": 1500, "temperature": 0.6, "requires": ALL_SECTIONS},
    "weekly_review":     {"max_tokens": 1000, "temperature": 0.6, "requires": ALL_SECTIONS},
    "workout_feedback":  {"max_tokens": 800, "temperature": 0.6, "requires": ALL_SECTIONS},
    "run_complete":      {"max_tokens": 400, "temperature": 0.6, "requires": ALL_SECTIONS},
    "meals_complete":    {"max_tokens": 300, "temperature": 0.6, "requires": ALL_SECTIONS},
    "end_of_day":        {"max_tokens": 300, "temperature": 0.6, "requires": ALL_SECTIONS},
    "chat_opened":       {"max_tokens": 400, "temperature": 0.6, "requires": ALL_SECTIONS},
    "crisis":            {"max_tokens": 300, "temperature": 0.3, "requires": ALL_SECTIONS},
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_assembler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py coach_agents.py tests/test_coach_assembler.py
git commit -m "Rewrite PROTOCOL_MAP + simplify coach_agents (ALL_SECTIONS, temp 0.6)"
```

---

## Task 15: Update `assemble_prompt` to inject pre-filled sections + integrate rules engine

**Files:**
- Modify: `coach_assembler.py:1384` (the `assemble_prompt` function)
- Test: `tests/test_coach_assembler.py`

The new `assemble_prompt` takes `(agent_name, context, rules)` and embeds the pre-filled `<schedule>` + `<directive>` blocks into the system prompt.

- [ ] **Step 1: Write failing test**

Append to `tests/test_coach_assembler.py`:

```python
class TestAssemblePromptWithRules:
    def test_prompt_includes_prefilled_sections(self, app_ctx):
        from coach_assembler import assemble_prompt, build_filtered_context
        from coach_rules import compute_coach_rules
        from datetime import datetime
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            from flask_login import login_user
            login_user(u, force=True)
            ctx = build_filtered_context("conversation")
            rules = compute_coach_rules(
                user_id=u.id,
                now=datetime(2026, 4, 30, 14, 0),
                latest_user_message=None,
            )
            prompt = assemble_prompt("conversation", ctx, rules=rules)
        assert "<schedule>" in prompt
        assert "<directive>" in prompt
        assert rules.directive.text in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_assembler.py::TestAssemblePromptWithRules -v`
Expected: FAIL — `assemble_prompt` doesn't accept a `rules` argument.

- [ ] **Step 3: Update `assemble_prompt`**

In `coach_assembler.py`, replace the `assemble_prompt` function (currently at line 1384) with:

```python
def assemble_prompt(agent_name, context, rules=None):
    """Assemble the system prompt: CORE_PROMPT + protocol + pre-filled
    sections from rules engine + structured athlete data.

    Args:
        agent_name: Coach agent (conversation, run_complete, etc.).
        context: Output of build_filtered_context.
        rules: A CoachRules dataclass from compute_coach_rules. When None,
               the assembler still works for back-compat tests but emits
               empty pre-filled blocks (production should always pass rules).
    """
    parts = [CORE_PROMPT, "\n---\n", PROTOCOL_MAP.get(agent_name, "")]

    if rules is not None:
        parts.append("\n\n# PRE-FILLED SECTIONS (echo these back byte-identical)\n")
        parts.append(rules.prefilled_schedule)
        parts.append("\n")
        parts.append(rules.prefilled_directive)
        if rules.refusal_required:
            parts.append(
                f"\n\n# REFUSAL REQUIRED — reason: {rules.refusal_reason}. "
                "Emit a <refusal> section that echoes the directive and names the deviation."
            )

    parts.append("\n\n<athlete_data>\n")
    parts.append(_format_athlete_data(context, context.get("requires", [])))
    parts.append("\n</athlete_data>\n")

    return "".join(parts)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_assembler.py::TestAssemblePromptWithRules -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py tests/test_coach_assembler.py
git commit -m "Wire rules engine into assemble_prompt (pre-filled sections injected)"
```

---

## Task 16: `coach_respond` orchestration with retry + fallback

**Files:**
- Modify: `coach_assembler.py` — add `coach_respond` function at the end of the file
- Test: `tests/test_coach_end_to_end.py`

`coach_respond` is the new top-level entry: rules → assemble → LLM → validate → retry → render. The LLM call is abstracted through a function param so tests can mock it.

- [ ] **Step 1: Write failing tests**

Create `tests/test_coach_end_to_end.py`:

```python
"""Integration tests for the full coach pipeline with mocked LLM."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _make_user(app_ctx):
    from models import User, UserEquipment, PhysicalAssessment
    app, db = app_ctx
    u = User(email=f"e2e-{id(app)}-{db.session.no_autoflush}@example.com", password_hash="x")
    db.session.add(u); db.session.commit()
    eq = UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells"])
    pa = PhysicalAssessment(user_id=u.id, has_gym=True)
    db.session.add(eq); db.session.add(pa); db.session.commit()
    return u


class TestCoachRespond:
    def test_valid_first_call_renders_clean(self, app_ctx):
        from coach_assembler import coach_respond
        from datetime import datetime
        app, _ = app_ctx
        u = _make_user(app_ctx)

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            # Echo prefilled + add a clean motivation. Parse the system_prompt
            # for the pre-filled blocks; here we just return matching content
            # for the simplest case.
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Lift now. Front Squat 5x5.</motivation>"
            )

        # Patch the rules engine to return predictable pre-fills via monkeypatch.
        with app.test_request_context():
            from flask_login import login_user
            login_user(u, force=True)
            # We need pre-filled sections to match the LLM's echo exactly.
            # Use a low-level entry that lets us inject rules directly.
            from coach_rules import CoachRules, Directive
            from datetime import datetime, timezone, time as dtime
            from zoneinfo import ZoneInfo
            PACIFIC = ZoneInfo("America/Los_Angeles")
            rules = CoachRules(
                now_utc=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
                now_local=datetime(2026, 4, 30, 10, 0, tzinfo=PACIFIC),
                local_date_iso="2026-04-30", local_weekday="Thursday", local_time_hhmm="10:00",
                workout_today=None, workout_today_scheduled_at=None, workout_today_status="rest",
                run_today=None, run_today_status="rest",
                workout_tomorrow=None, workout_tomorrow_scheduled_at=None, run_tomorrow=None,
                fasting_active=False, fasting_hours=None, fasting_target_hours=None, fasting_break_at=None,
                directive=Directive(text="Recovery day.", category="recovery"),
                refusal_required=False, refusal_reason=None,
                prefilled_schedule="<schedule>SCHED</schedule>",
                prefilled_directive="<directive>DIR</directive>",
            )
            out = coach_respond(
                user_id=u.id,
                agent_name="conversation",
                user_message="hey",
                rules=rules,
                llm_fn=fake_llm,
            )
        # Renderer strips tags
        assert "SCHED" in out
        assert "DIR" in out
        assert "Lift now" in out
        assert "<schedule>" not in out

    def test_retry_then_succeed(self, app_ctx):
        from coach_assembler import coach_respond
        from coach_rules import CoachRules, Directive
        from datetime import datetime, timezone, time as dtime
        from zoneinfo import ZoneInfo
        PACIFIC = ZoneInfo("America/Los_Angeles")
        app, _ = app_ctx
        u = _make_user(app_ctx)

        call_count = [0]

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: banned phrase
                return (
                    "<schedule>SCHED</schedule>\n"
                    "<directive>DIR</directive>\n"
                    "<motivation>Great job today!</motivation>"
                )
            # Second call: clean
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Logged. Recovery day.</motivation>"
            )

        with app.test_request_context():
            from flask_login import login_user
            login_user(u, force=True)
            rules = CoachRules(
                now_utc=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
                now_local=datetime(2026, 4, 30, 10, 0, tzinfo=PACIFIC),
                local_date_iso="2026-04-30", local_weekday="Thursday", local_time_hhmm="10:00",
                workout_today=None, workout_today_scheduled_at=None, workout_today_status="rest",
                run_today=None, run_today_status="rest",
                workout_tomorrow=None, workout_tomorrow_scheduled_at=None, run_tomorrow=None,
                fasting_active=False, fasting_hours=None, fasting_target_hours=None, fasting_break_at=None,
                directive=Directive(text="Recovery day.", category="recovery"),
                refusal_required=False, refusal_reason=None,
                prefilled_schedule="<schedule>SCHED</schedule>",
                prefilled_directive="<directive>DIR</directive>",
            )
            out = coach_respond(
                user_id=u.id, agent_name="conversation",
                user_message="hey", rules=rules, llm_fn=fake_llm,
            )
        assert call_count[0] == 2
        assert "Great job" not in out
        assert "Logged" in out

    def test_double_failure_falls_back(self, app_ctx):
        from coach_assembler import coach_respond
        from coach_rules import CoachRules, Directive
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        PACIFIC = ZoneInfo("America/Los_Angeles")
        app, _ = app_ctx
        u = _make_user(app_ctx)

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            # Always returns a banned phrase
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Your call!</motivation>"
            )

        with app.test_request_context():
            from flask_login import login_user
            login_user(u, force=True)
            rules = CoachRules(
                now_utc=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
                now_local=datetime(2026, 4, 30, 10, 0, tzinfo=PACIFIC),
                local_date_iso="2026-04-30", local_weekday="Thursday", local_time_hhmm="10:00",
                workout_today=None, workout_today_scheduled_at=None, workout_today_status="rest",
                run_today=None, run_today_status="rest",
                workout_tomorrow=None, workout_tomorrow_scheduled_at=None, run_tomorrow=None,
                fasting_active=False, fasting_hours=None, fasting_target_hours=None, fasting_break_at=None,
                directive=Directive(text="Recovery day.", category="recovery"),
                refusal_required=False, refusal_reason=None,
                prefilled_schedule="<schedule>SCHED</schedule>",
                prefilled_directive="<directive>Recovery day.</directive>",
            )
            out = coach_respond(
                user_id=u.id, agent_name="conversation",
                user_message="hey", rules=rules, llm_fn=fake_llm,
            )
        # Fallback content: pre-filled + "Logged."
        assert "SCHED" in out
        assert "Recovery day" in out
        assert "Your call" not in out
        assert "Logged" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coach_end_to_end.py -v`
Expected: FAIL — `ImportError: cannot import name 'coach_respond'`.

- [ ] **Step 3: Implement `coach_respond`**

Append to `coach_assembler.py`:

```python
def render_response_to_user(sections: dict) -> str:
    """Strip tags, join sections in display order. The user never sees tags."""
    parts = []
    for key in ("schedule", "directive", "motivation", "refusal"):
        if key in sections and sections[key]:
            parts.append(sections[key].strip())
    return "\n\n".join(parts)


def coach_respond(
    user_id,
    agent_name,
    user_message,
    rules=None,
    llm_fn=None,
):
    """Top-level coach entry. Replaces the inline LLM call in /api/chat.

    Args:
        user_id: athlete user id.
        agent_name: agent key from AGENTS dict (e.g. 'conversation').
        user_message: the user's latest message text (or None for system events).
        rules: CoachRules dataclass. If None, computed via compute_coach_rules.
        llm_fn: Callable(system_prompt, messages, temperature, max_tokens) -> str.
                If None, uses the real Anthropic client. Tests pass a stub.

    Returns: rendered response string for the user (tags stripped).
    """
    from coach_rules import compute_coach_rules
    from coach_validator import validate_response, deterministic_fallback
    from coach_agents import AGENTS

    if rules is None:
        rules = compute_coach_rules(user_id=user_id, latest_user_message=user_message)

    context = build_filtered_context(agent_name)
    context["latest_user_message"] = user_message or ""
    system_prompt = assemble_prompt(agent_name, context, rules=rules)

    agent_cfg = AGENTS.get(agent_name, AGENTS["conversation"])
    messages = [{"role": "user", "content": user_message or "(system event)"}]

    if llm_fn is None:
        llm_fn = _real_llm_call

    raw = llm_fn(system_prompt, messages, agent_cfg["temperature"], agent_cfg["max_tokens"])

    result = validate_response(
        raw=raw,
        prefilled_schedule=rules.prefilled_schedule,
        prefilled_directive=rules.prefilled_directive,
        refusal_required=rules.refusal_required,
    )
    if result.ok:
        return render_response_to_user(result.sections)

    # Retry once with feedback
    retry_messages = messages + [
        {"role": "assistant", "content": raw},
        {"role": "user", "content": (
            f"Your response failed validation: {result.failure_reason}. "
            "Re-emit the response, fixing the specific issue. "
            "Echo the pre-filled <schedule> and <directive> sections byte-identical."
        )},
    ]
    raw2 = llm_fn(system_prompt, retry_messages, agent_cfg["temperature"], agent_cfg["max_tokens"])
    result2 = validate_response(
        raw=raw2,
        prefilled_schedule=rules.prefilled_schedule,
        prefilled_directive=rules.prefilled_directive,
        refusal_required=rules.refusal_required,
    )
    if result2.ok:
        return render_response_to_user(result2.sections)

    # Deterministic fallback
    return deterministic_fallback(
        prefilled_schedule=rules.prefilled_schedule,
        prefilled_directive=rules.prefilled_directive,
        refusal_required=rules.refusal_required,
    )


def _real_llm_call(system_prompt, messages, temperature, max_tokens):
    """Production LLM call. Imported lazily so tests don't need the API key."""
    import os
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coach_end_to_end.py -v`
Expected: PASS — 3 e2e tests.

- [ ] **Step 5: Commit**

```bash
git add coach_assembler.py tests/test_coach_end_to_end.py
git commit -m "Add coach_respond orchestration: rules → LLM → validate → retry → fallback"
```

---

## Task 17: Wire `coach_respond` into `/api/chat` endpoint

**Files:**
- Modify: `app.py:4909-5095` (the `/api/chat` POST handler)
- Test: manual smoke (no automated test — integration too tightly coupled to Anthropic)

- [ ] **Step 1: Read the current handler** to understand the surrounding logic (memory extraction, anger update, ChatMessage save).

Run: `grep -n "/api/chat" /Users/erikbjohn/Documents/Github/12Weeks/app.py`

- [ ] **Step 2: Replace the inline LLM block (lines ~4951-4969) with a `coach_respond` call**

Find:
```python
    # Get AI response
    from coach_assembler import assemble_prompt
    from coach import _build_messages
    from coach_agents import AGENTS
    import anthropic

    system_prompt = assemble_prompt(_route_info["agent_name"], context)
    messages = _build_messages(user_msg, context.get("chat_history", []), user_timezone=context.get("user_timezone"))
    agent_config = AGENTS.get(_route_info["agent_name"], AGENTS["conversation"])

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=CLAUDE_OPUS,
        max_tokens=agent_config["max_tokens"],
        temperature=agent_config["temperature"],
        system=system_prompt,
        messages=messages,
    )
    response_text = response.content[0].text
```

Replace with:
```python
    # Get AI response via the new orchestration: rules → assemble → LLM → validate → fallback
    from coach_assembler import coach_respond
    response_text = coach_respond(
        user_id=current_user.id,
        agent_name=_route_info["agent_name"],
        user_message=user_msg,
    )
```

- [ ] **Step 3: Verify the endpoint imports still work**

Run: `python -c "import app"`
Expected: no error.

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all tests passing.

- [ ] **Step 5: Manual smoke test (Python REPL — no new endpoint required)**

```bash
cd /Users/erikbjohn/Documents/Github/12Weeks
python -c "
from app import app, db
from models import User
from coach_assembler import coach_respond
with app.app_context():
    u = User.query.filter_by(email='erik@placemetry.com').first()
    if not u:
        print('Erik user not found in local DB; smoke against staging instead.')
    else:
        out = coach_respond(
            user_id=u.id,
            agent_name='conversation',
            user_message='what should I do right now',
        )
        print('--- COACH RESPONSE ---')
        print(out)
        print('--- END ---')
"
```

Verify the response:
- Contains a directive line (e.g., "Lift now." or "Recovery day.")
- Has no banned phrases (grep against the BANNED_PHRASES list in coach_validator.py)
- Has no question marks
- Schedule line includes the current Pacific time

This requires `ANTHROPIC_API_KEY` in the environment. If unset, expect the call to error in `_real_llm_call` — wrap in `llm_fn=lambda *a, **k: '<schedule>...</schedule>\\n<directive>...</directive>\\n<motivation>(stub)</motivation>'` to dry-run without API.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "Wire coach_respond into /api/chat endpoint"
```

---

## Task 18: Final integration sweep + delete dead code

**Files:**
- Modify: `coach_assembler.py` — remove the section_builder registry entry for `chat_history` if still present; ensure `_build_event_timeline` and `_build_recent_coach_directives` are registered.
- Modify: any caller of `_build_chat_history` or the old `chat_history` context key.

- [ ] **Step 1: Find leftover references**

Run: `grep -rn "_build_chat_history\|chat_history" --include="*.py" /Users/erikbjohn/Documents/Github/12Weeks/`
Expected: only references that need updating to `_build_event_timeline` or `event_timeline`.

- [ ] **Step 2: Update each reference**

For every `chat_history` reference in `coach_assembler.py` (especially in `build_filtered_context`, `_format_athlete_data`, the `section_builder` registry decorator usage), replace with `event_timeline`. For the removed `_build_chat_history`, ensure no orphaned `@section_builder("chat_history")` decorator remains.

For the `_build_messages` import in `app.py` (line ~4953) — now unused, delete the import line.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all tests passing.

- [ ] **Step 4: Manual smoke** of the full coach pipeline against real DB:

```bash
ADMIN_API_KEY=$ADMIN_API_KEY curl -sS -X POST http://localhost:5000/api/admin/debug/sql \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT email, id FROM \"user\" WHERE email = '\''erik@placemetry.com'\''"}'
```

Then trigger a real coach response via the production endpoint and inspect the rendered output.

- [ ] **Step 5: Commit**

```bash
git add -A coach_assembler.py app.py
git commit -m "Remove dead chat_history references; finalize event_timeline migration"
```

---

## Self-Review Checklist (run after the plan is committed)

- [ ] Spec coverage: every audit failure mode (1-10) addressed by at least one task?
- [ ] Type consistency: `CoachRules` field names match across rules engine, validator, assembler?
- [ ] No placeholders: no "TBD", no "similar to task X", every code block complete?
- [ ] Test independence: each test fixture creates its own user (no cross-test bleed)?
- [ ] Big-bang rollback: would `git revert <merge-commit>` cleanly restore the old coach? (Yes — all changes confined to coach_*, app.py:4909-5095, and tests.)
