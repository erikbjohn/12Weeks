# Garmin Connect Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bidirectional Garmin sync — completed running/HIIT activities auto-fill RunLog (pull), and planned run/HIIT days land on the watch as scheduled structured workouts (push).

**Architecture:** New `garmin_sync.py` module (pure prose-parser + workout-JSON builder + DB sync functions) sitting on the existing `GarminClient`/`GarminTokens` auth. Two new tables (`GarminActivity` audit, `GarminWorkoutLink` push bookkeeping), two new columns (`run_log.source`, `weekly_run_plan.segments_json`). Three new endpoints + a best-effort push hook in the weekly-planning job. Frontend: settings Garmin panel, throttled auto-pull on load, "from Garmin" provenance marker.

**Tech Stack:** Flask + SQLAlchemy, `garminconnect` 0.2.40 (already installed), pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-garmin-sync-design.md`

**Non-negotiable invariants (from spec + standing rules):**
- Never overwrite a manual RunLog (`source` NULL or `'manual'`) — Garmin only fills empty days; sync-created logs (`source='garmin'`) stay updatable by later syncs.
- Never push intervals that aren't provably in the plan. If structure can't be recovered (unparseable prose, or parsed total ≠ stored duration), push a single timed workout with the correct label/duration instead.
- Garmin failures never break planning, page load, or run logging. Best-effort + surfaced status, no silent failures, no fake success.

**Verified codebase facts (do not re-derive):**
- Date mapping: `day_date = AppState.start_date + timedelta(days=(week-1)*7 + day_idx)` (canonical use at `app.py:9869`); inverse: `diff=(d-start_date).days; week=diff//7+1; day_idx=diff%7`.
- `AppState` (`models.py:238-246`): per-user via `user_id`, has `start_date` (Date).
- `RunLog` (`models.py:194-206`): unique `(user_id, week, day_idx)`; fields `distance_miles` (Float), `avg_hr` (Int, whole-run mean), `elevation_ft` (Int), `duration_min` (Int), `notes`, `log_date`.
- `WeeklyRunPlan` (`models.py:591-603`): `run_type/label/duration(str)/detail(text)/source`.
- Run-plan save loop: `app.py:4847-4888` inside the weekly generation function (uses `current_user.id`); coach dict comes from `coach_planning_runs.generate_week_runs` → `{day_idx: {type,label,duration,detail}}`; segments built at `coach_planning_runs.py:442-448` then dropped.
- `_segments_to_detail` (`coach_planning_runs.py:215-248`) prose format: parts joined `"; "`; work = `"{n}×{m} min hard[ @ HR {hr}][ / {k} min easy][ ({note})]"` (n× always present); non-work = `"[{n}×]{m} min {kind}[ ({'@ HR {hr}' and/or note})]"`. A rationale is appended after `" — "` in stored detail.
- Real stored examples (parser fixtures): `"10 min warmup; 6×3 min hard @ HR ≥165 / 3 min easy; 7 min cooldown — Progressing from…"` (duration "53 min"); `"50 min steady (@ HR ≤135) — Stepping up…"` ("50 min"); `"10 min warmup; 65 min steady (@ HR ≤132); 10 min cooldown — Deload…"` ("85 min").
- `garminconnect` 0.2.40: `get_activities_by_date(startdate, enddate)`, `upload_workout(dict)→{workoutId:…}`, `schedule_workout(id, "YYYY-MM-DD")`, no delete_workout method (use `api.garth.request("DELETE","connectapi",f"{api.garmin_workouts}/workout/{id}", api=True)`).
- Activity JSON keys: `activityId`, `activityType.typeKey`, `startTimeLocal` (`"YYYY-MM-DD HH:MM:SS"`), `distance` (meters), `duration` (seconds), `averageHR`, `elevationGain` (meters).
- Startup migration mechanism: `app.py:136-218` — `db.create_all()` creates new tables; new columns on existing tables go in the `_migrations` list of `(table, column, type)` tuples.
- `_get_garmin(user_id=None)` at `app.py:874-882`; garmin endpoints at `app.py:8073-8176`; `_user_today()` at `app.py:905`; `_current_week()` at `app.py:914`.
- `/api/run-log` GET at `app.py:10393-10400` (feeds `_runLogCache` at `static/app.js:5272`), POST at `app.py:10364-10390`.
- Settings dropdown built inline at `static/app.js:4748-4789`; `garminLogin()` at `app.js:6849-6935` (calls `closeModal()` on success — replace with `closeGarminPanel()` in Task 9); run-card logged display at `app.js:10237-10282`.
- Test style: `tests/conftest.py` sets sqlite `DATABASE_URL` pre-import; DB tests use a module-scoped `app_ctx` fixture (`from app import app, db; with app.app_context(): db.create_all()`), e.g. `tests/test_prescription_autoreconcile.py`.

---

### Task 1: Models + startup migrations

**Files:**
- Modify: `models.py` (RunLog ~line 205, WeeklyRunPlan ~line 603, new classes after GarminTokens ~line 351)
- Modify: `app.py` `_migrations` list (~line 218, end of the list)

- [ ] **Step 1: Add `source` to RunLog**

In `models.py`, inside `class RunLog`, after the `notes` column (line ~205):

```python
    notes = db.Column(db.Text)
    source = db.Column(db.String(20))  # 'manual' | 'garmin'; legacy NULL = manual
```

- [ ] **Step 2: Add `segments_json` to WeeklyRunPlan**

In `models.py`, inside `class WeeklyRunPlan`, after the `detail` column:

```python
    detail = db.Column(db.Text)  # Full coaching cue
    segments_json = db.Column(db.Text)  # coach's structured segments [{kind,minutes,reps,hr,note}]
```

- [ ] **Step 3: Add the two new models**

In `models.py`, directly after `class GarminTokens` (line ~351):

```python
class GarminActivity(db.Model):
    """Audit log of activities pulled from Garmin Connect. One row per Garmin
    activity; the unique garmin_activity_id makes sync idempotent. week/day_idx
    are NULL when the activity falls outside the program calendar."""
    __tablename__ = "garmin_activity"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    garmin_activity_id = db.Column(db.String(40), nullable=False, unique=True)
    type_key = db.Column(db.String(40))
    start_time_local = db.Column(db.String(30))
    activity_date = db.Column(db.Date)
    week = db.Column(db.Integer, nullable=True)
    day_idx = db.Column(db.Integer, nullable=True)
    distance_miles = db.Column(db.Float)
    duration_min = db.Column(db.Integer)
    avg_hr = db.Column(db.Integer)
    elevation_ft = db.Column(db.Integer)
    raw_summary = db.Column(db.Text)  # JSON of selected raw Garmin fields
    pulled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class GarminWorkoutLink(db.Model):
    """Maps a planned run/HIIT day to the structured workout pushed to Garmin.
    structure_hash makes re-push idempotent; status surfaces failures in the UI."""
    __tablename__ = "garmin_workout_link"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    garmin_workout_id = db.Column(db.String(40))
    scheduled_date = db.Column(db.Date)
    structure_hash = db.Column(db.String(64))
    status = db.Column(db.String(10), default="ok")  # ok | failed
    error = db.Column(db.Text)
    pushed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("user_id", "week", "day_idx"),)
```

(`datetime`/`timezone` are already imported in models.py — GarminTokens uses the same default.)

- [ ] **Step 4: Register the new columns in the startup migration list**

In `app.py`, append to the `_migrations` list (ends near line 218 with `("exercise_swap", "original_name", "VARCHAR(120)")`):

```python
        ("run_log", "source", "VARCHAR(20)"),
        ("weekly_run_plan", "segments_json", "TEXT"),
```

- [ ] **Step 5: Smoke-verify schema creation**

Run: `venv/bin/python -c "import os; os.environ['DATABASE_URL']='sqlite:////tmp/garmin_schema_test.db'; from app import app, db; ctx=app.app_context(); ctx.push(); db.create_all(); from models import GarminActivity, GarminWorkoutLink; print(GarminActivity.__tablename__, GarminWorkoutLink.__tablename__)"`
Expected: prints `garmin_activity garmin_workout_link` with no traceback.

- [ ] **Step 6: Commit**

```bash
git add models.py app.py
git commit -m "Garmin sync: GarminActivity + GarminWorkoutLink tables, run_log.source, weekly_run_plan.segments_json"
```

---

### Task 2: Prose-detail → segments parser (pure, TDD)

**Files:**
- Create: `garmin_sync.py`
- Create: `tests/test_garmin_sync.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_garmin_sync.py`:

```python
"""Garmin sync: prose parser, workout builder, pull/push DB logic.

Parser fixtures are REAL stored WeeklyRunPlan.detail strings from wk11/12
(produced by coach_planning_runs._segments_to_detail + appended rationale).
"""
from datetime import date

import pytest


# ---------- parse_detail_to_segments ----------

def test_parse_vo2_intervals_with_rationale():
    from garmin_sync import parse_detail_to_segments
    detail = ("10 min warmup; 6×3 min hard @ HR ≥165 / 3 min easy; 7 min cooldown"
              " — Progressing from last week's 5×3 to 6×3 — extra rationale")
    segs = parse_detail_to_segments(detail)
    assert segs == [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "work", "minutes": 3, "reps": 6, "hr": "≥165"},
        {"kind": "recovery", "minutes": 3, "reps": 6},
        {"kind": "cooldown", "minutes": 7, "reps": 1},
    ]


def test_parse_steady_with_parenthesized_hr():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments("50 min steady (@ HR ≤135) — Stepping up from last week")
    assert segs == [{"kind": "steady", "minutes": 50, "reps": 1, "hr": "≤135"}]


def test_parse_long_run_three_blocks():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments(
        "10 min warmup; 65 min steady (@ HR ≤132); 10 min cooldown — Deload cuts back")
    assert segs == [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "steady", "minutes": 65, "reps": 1, "hr": "≤132"},
        {"kind": "cooldown", "minutes": 10, "reps": 1},
    ]


def test_parse_work_with_note_and_single_rep():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments("1×20 min hard @ HR 150-160 (tempo effort)")
    assert segs == [{"kind": "work", "minutes": 20, "reps": 1, "hr": "150-160", "note": "tempo effort"}]


def test_parse_steady_with_note_only():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments("30 min steady (easy spin)")
    assert segs == [{"kind": "steady", "minutes": 30, "reps": 1, "note": "easy spin"}]


def test_parse_unrecognized_returns_none():
    from garmin_sync import parse_detail_to_segments
    assert parse_detail_to_segments("Run hard until you feel it") is None
    assert parse_detail_to_segments("") is None
    assert parse_detail_to_segments(None) is None


def test_parse_partial_garbage_returns_none():
    # One good part + one bad part → None (never push half-invented structure)
    from garmin_sync import parse_detail_to_segments
    assert parse_detail_to_segments("10 min warmup; whatever feels right") is None


def test_segments_total_minutes():
    from garmin_sync import segments_total_minutes
    segs = [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "work", "minutes": 3, "reps": 6},
        {"kind": "recovery", "minutes": 3, "reps": 6},
        {"kind": "cooldown", "minutes": 7, "reps": 1},
    ]
    assert segments_total_minutes(segs) == 53
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'garmin_sync'`.

- [ ] **Step 3: Create `garmin_sync.py` with the parser**

```python
"""Garmin Connect sync: pull activities into RunLog, push planned runs/HIIT
to the watch as scheduled structured workouts.

Design doc: docs/superpowers/specs/2026-06-11-garmin-sync-design.md

Pure helpers (parser, builder, aggregation) live at module level with no app
imports so they're unit-testable; DB-touching functions import models inside
the function body.
"""

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Activity typeKeys that count as the day's run/HIIT. Strength and everything
# else is ignored (lifts are logged set-by-set in the app).
RUN_TYPE_KEYS = {
    "running", "trail_running", "treadmill_running", "track_running",
    "indoor_running", "virtual_run", "street_running",
}
HIIT_TYPE_KEYS = {"hiit", "indoor_cardio", "cardio"}

# ---------------------------------------------------------------------------
# Prose parser — exact inverse of coach_planning_runs._segments_to_detail.
# Stored detail = "<segments prose> — <rationale>"; parts joined by "; ".
# ---------------------------------------------------------------------------

_WORK_RE = re.compile(
    r"^(?:(?P<reps>\d+)×)?(?P<mins>\d+(?:\.\d+)?) min hard"
    r"(?: @ HR (?P<hr>[^/()]+?))?"
    r"(?: / (?P<easymins>\d+(?:\.\d+)?) min easy)?"
    r"(?: \((?P<note>.*)\))?$"
)
_PLAIN_RE = re.compile(
    r"^(?:(?P<reps>\d+)×)?(?P<mins>\d+(?:\.\d+)?) min (?P<kind>warmup|recovery|cooldown|steady)"
    r"(?: \((?P<extra>.*)\))?$"
)
_EXTRA_HR_RE = re.compile(r"^@ HR (?P<hr>\S+)\s*(?P<note>.*)$")


def _num(s):
    f = float(s)
    return int(f) if f == int(f) else f


def parse_detail_to_segments(detail):
    """Invert _segments_to_detail. Returns [{kind, minutes, reps, hr?, note?}]
    or None when ANY part doesn't match the machine format — callers must then
    fall back to a single timed workout (never invent structure)."""
    if not detail:
        return None
    prose = detail.split(" — ")[0].strip()
    if not prose:
        return None
    segments = []
    for part in [p.strip() for p in prose.split(";")]:
        if not part:
            return None
        m = _WORK_RE.match(part)
        if m:
            reps = int(m.group("reps")) if m.group("reps") else 1
            seg = {"kind": "work", "minutes": _num(m.group("mins")), "reps": reps}
            if m.group("hr"):
                seg["hr"] = m.group("hr").strip()
            if m.group("note"):
                seg["note"] = m.group("note")
            segments.append(seg)
            if m.group("easymins"):
                segments.append({"kind": "recovery", "minutes": _num(m.group("easymins")), "reps": reps})
            continue
        m = _PLAIN_RE.match(part)
        if m:
            seg = {
                "kind": m.group("kind"),
                "minutes": _num(m.group("mins")),
                "reps": int(m.group("reps")) if m.group("reps") else 1,
            }
            extra = m.group("extra")
            if extra:
                m2 = _EXTRA_HR_RE.match(extra)
                if m2:
                    seg["hr"] = m2.group("hr")
                    if m2.group("note"):
                        seg["note"] = m2.group("note")
                else:
                    seg["note"] = extra
            segments.append(seg)
            continue
        return None
    return segments or None


def segments_total_minutes(segments):
    """Sum of minutes×reps — must equal the stored duration or we fall back."""
    total = 0
    for s in segments or []:
        total += (s.get("minutes") or 0) * (s.get("reps") or 1)
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -x -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add garmin_sync.py tests/test_garmin_sync.py
git commit -m "Garmin sync: deterministic parser inverting run-plan prose to segments"
```

---

### Task 3: Segments → Garmin workout JSON builder (pure, TDD)

**Files:**
- Modify: `garmin_sync.py`
- Modify: `tests/test_garmin_sync.py`

- [ ] **Step 1: Write failing builder tests** (append to `tests/test_garmin_sync.py`)

```python
# ---------- HR encoding + workout JSON builder ----------

def test_hr_bounds_encoding():
    from garmin_sync import _hr_bounds
    assert _hr_bounds("≥165") == (165, 190)
    assert _hr_bounds("≤135") == (90, 135)
    assert _hr_bounds("150-160") == (150, 160)
    assert _hr_bounds("142") == (137, 147)
    assert _hr_bounds("Z2") is None
    assert _hr_bounds(None) is None


def test_build_workout_json_vo2_structure():
    from garmin_sync import build_workout_json
    segs = [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "work", "minutes": 3, "reps": 6, "hr": "≥165"},
        {"kind": "recovery", "minutes": 3, "reps": 6},
        {"kind": "cooldown", "minutes": 7, "reps": 1},
    ]
    wj = build_workout_json("12W Wk11 Tue — VO2 53 min", segs)
    assert wj["workoutName"] == "12W Wk11 Tue — VO2 53 min"
    assert wj["sportType"]["sportTypeKey"] == "running"
    steps = wj["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 3  # warmup, repeat-group, cooldown
    warmup, repeat, cooldown = steps
    assert warmup["stepType"]["stepTypeKey"] == "warmup"
    assert warmup["endConditionValue"] == 600.0
    assert warmup["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 6
    work, rec = repeat["workoutSteps"]
    assert work["stepType"]["stepTypeKey"] == "interval"
    assert work["endConditionValue"] == 180.0
    assert work["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (work["targetValueOne"], work["targetValueTwo"]) == (165, 190)
    assert rec["stepType"]["stepTypeKey"] == "recovery"
    assert cooldown["stepType"]["stepTypeKey"] == "cooldown"
    # step orders strictly increasing and unique across nesting
    orders = [warmup["stepOrder"], repeat["stepOrder"], work["stepOrder"],
              rec["stepOrder"], cooldown["stepOrder"]]
    assert orders == sorted(orders) and len(set(orders)) == 5


def test_build_workout_json_steady_hr_ceiling():
    from garmin_sync import build_workout_json
    wj = build_workout_json("x", [{"kind": "steady", "minutes": 50, "reps": 1, "hr": "≤135"}])
    step = wj["workoutSegments"][0]["workoutSteps"][0]
    assert step["type"] == "ExecutableStepDTO"
    assert step["endConditionValue"] == 3000.0
    assert (step["targetValueOne"], step["targetValueTwo"]) == (90, 135)


def test_build_simple_timed_workout():
    from garmin_sync import build_simple_timed_workout
    wj = build_simple_timed_workout("12W Wk11 Wed — Zone 2 50 min", 50)
    steps = wj["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1
    assert steps[0]["endConditionValue"] == 3000.0
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_structure_hash_changes_with_content_and_date():
    from garmin_sync import build_simple_timed_workout, structure_hash
    a = build_simple_timed_workout("n", 50)
    b = build_simple_timed_workout("n", 55)
    assert structure_hash(a, "2026-06-15") != structure_hash(b, "2026-06-15")
    assert structure_hash(a, "2026-06-15") != structure_hash(a, "2026-06-16")
    assert structure_hash(a, "2026-06-15") == structure_hash(a, "2026-06-15")
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -x -q`
Expected: FAIL with `ImportError` (cannot import `_hr_bounds`).

- [ ] **Step 3: Implement builder** (append to `garmin_sync.py`)

```python
# ---------------------------------------------------------------------------
# Garmin structured-workout JSON (workout-service schema).
# All sessions push as running workouts; HIIT days are run-based intervals.
# Schema mirrored from Garmin Connect workout-service payloads; verified live
# in Task 10 against get_workouts() on a real workout.
# ---------------------------------------------------------------------------

_STEP_TYPE = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "work": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "steady": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery"},
}
_SPORT_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}
_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
_HR_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}


def _hr_bounds(hr_text):
    """Coach HR cue → (low, high) bpm for Garmin's custom HR range, which
    requires BOTH bounds. The bound the coach didn't state is an encoding
    artifact (±window / generous cap), NOT plan content. Non-numeric → None."""
    if not hr_text:
        return None
    t = str(hr_text)
    nums = [int(n) for n in re.findall(r"\d+", t)]
    if not nums:
        return None
    if len(nums) >= 2:
        return (nums[0], nums[1])
    n = nums[0]
    if "≥" in t or ">" in t:
        return (n, min(n + 25, 200))
    if "≤" in t or "<" in t:
        return (max(n - 45, 80), n)
    return (n - 5, n + 5)


def _exec_step(seg, order):
    kind = (seg.get("kind") or "steady").lower()
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(_STEP_TYPE.get(kind, _STEP_TYPE["steady"])),
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
        "endConditionValue": float(seg.get("minutes") or 0) * 60.0,
    }
    bounds = _hr_bounds(seg.get("hr"))
    if bounds:
        step["targetType"] = dict(_HR_TARGET)
        step["targetValueOne"], step["targetValueTwo"] = bounds
    else:
        step["targetType"] = dict(_NO_TARGET)
    if seg.get("note"):
        step["description"] = str(seg["note"])[:200]
    return step


def _repeat_group(children, iterations, order_start):
    order = order_start
    group = {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
        "numberOfIterations": iterations,
        "smartRepeat": False,
        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
        "workoutSteps": [],
    }
    order += 1
    for child in children:
        group["workoutSteps"].append(_exec_step(child, order))
        order += 1
    return group, order


def build_workout_json(name, segments):
    """Segments → Garmin running workout. Work+recovery pairs with reps>1
    become a repeat group (matching how the prose reads as intervals)."""
    steps = []
    order = 1
    segs = list(segments or [])
    i = 0
    while i < len(segs):
        s = segs[i] or {}
        kind = (s.get("kind") or "steady").lower()
        reps = int(s.get("reps") or 1)
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        nxt_kind = (nxt.get("kind") or "").lower() if nxt else None
        if kind == "work" and reps > 1 and nxt_kind == "recovery":
            group, order = _repeat_group([s, nxt], reps, order)
            steps.append(group)
            i += 2
            continue
        if reps > 1:
            group, order = _repeat_group([s], reps, order)
            steps.append(group)
        else:
            steps.append(_exec_step(s, order))
            order += 1
        i += 1
    return {
        "workoutName": name,
        "sportType": dict(_SPORT_RUNNING),
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": dict(_SPORT_RUNNING),
            "workoutSteps": steps,
        }],
    }


def build_simple_timed_workout(name, total_minutes):
    """Fallback when structure can't be recovered: one timed step, no target.
    Correct label + duration, never invented intervals."""
    return build_workout_json(name, [{"kind": "steady", "minutes": total_minutes, "reps": 1}])


def structure_hash(workout_json, date_iso):
    """Idempotency key: same structure + same calendar date → no re-push."""
    payload = json.dumps(workout_json, sort_keys=True) + "|" + date_iso
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -x -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add garmin_sync.py tests/test_garmin_sync.py
git commit -m "Garmin sync: structured-workout JSON builder with repeat groups + HR ranges"
```

---

### Task 4: Date mapping + day aggregation helpers (pure, TDD)

**Files:**
- Modify: `garmin_sync.py`
- Modify: `tests/test_garmin_sync.py`

- [ ] **Step 1: Write failing tests** (append)

```python
# ---------- date mapping + aggregation ----------

def test_week_day_for_date():
    from garmin_sync import week_day_for_date
    start = date(2026, 1, 5)  # Monday, week 1 day 0
    assert week_day_for_date(start, date(2026, 1, 5)) == (1, 0)
    assert week_day_for_date(start, date(2026, 1, 11)) == (1, 6)
    assert week_day_for_date(start, date(2026, 1, 12)) == (2, 0)
    assert week_day_for_date(start, date(2026, 1, 4)) == (None, None)    # before program
    assert week_day_for_date(start, date(2026, 3, 30)) == (None, None)   # week 13 — outside
    assert week_day_for_date(None, date(2026, 1, 5)) == (None, None)


def test_aggregate_day_doubles_weighted_hr():
    from garmin_sync import aggregate_day
    rows = [
        {"distance_miles": 4.0, "duration_min": 40, "avg_hr": 120, "elevation_ft": 100},
        {"distance_miles": 2.0, "duration_min": 20, "avg_hr": 150, "elevation_ft": 50},
    ]
    agg = aggregate_day(rows)
    assert agg["distance_miles"] == 6.0
    assert agg["duration_min"] == 60
    assert agg["avg_hr"] == 130  # (120*40 + 150*20) / 60
    assert agg["elevation_ft"] == 150


def test_aggregate_day_missing_hr_and_empty():
    from garmin_sync import aggregate_day
    rows = [{"distance_miles": 3.0, "duration_min": 30, "avg_hr": None, "elevation_ft": None}]
    agg = aggregate_day(rows)
    assert agg["avg_hr"] is None and agg["distance_miles"] == 3.0
    assert aggregate_day([]) is None
    assert aggregate_day([{"distance_miles": 0, "duration_min": 0, "avg_hr": None, "elevation_ft": 0}]) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -x -q` — FAIL (ImportError).

- [ ] **Step 3: Implement** (append to `garmin_sync.py`)

```python
# ---------------------------------------------------------------------------
# Program calendar mapping + daily aggregation
# ---------------------------------------------------------------------------

def week_day_for_date(start_date, d):
    """Inverse of app.py's `start_date + (week-1)*7 + day_idx`. (None, None)
    when outside the 12-week program window."""
    if not start_date or not d:
        return (None, None)
    diff = (d - start_date).days
    if diff < 0:
        return (None, None)
    week = diff // 7 + 1
    if week > 12:
        return (None, None)
    return (week, diff % 7)


def aggregate_day(rows):
    """Aggregate one day's activities (dicts or GarminActivity rows) into
    RunLog fields. Doubles sum distance/duration/elevation; HR is the
    duration-weighted mean (consistent with avg_hr = whole-run mean)."""
    def _get(r, k):
        return r.get(k) if isinstance(r, dict) else getattr(r, k, None)

    rows = [r for r in (rows or [])
            if (_get(r, "duration_min") or 0) > 0 or (_get(r, "distance_miles") or 0) > 0]
    if not rows:
        return None
    dist = round(sum(_get(r, "distance_miles") or 0 for r in rows), 2)
    dur = int(sum(_get(r, "duration_min") or 0 for r in rows))
    elev = int(sum(_get(r, "elevation_ft") or 0 for r in rows))
    hr_rows = [r for r in rows if _get(r, "avg_hr") and _get(r, "duration_min")]
    hr = None
    if hr_rows:
        hr = int(round(sum(_get(r, "avg_hr") * _get(r, "duration_min") for r in hr_rows)
                       / sum(_get(r, "duration_min") for r in hr_rows)))
    return {
        "distance_miles": dist or None,
        "duration_min": dur or None,
        "avg_hr": hr,
        "elevation_ft": elev or None,
    }
```

- [ ] **Step 4: Run tests** — all PASS.

- [ ] **Step 5: Commit**

```bash
git add garmin_sync.py tests/test_garmin_sync.py
git commit -m "Garmin sync: program-calendar date mapping + daily activity aggregation"
```

---

### Task 5: Pull sync — activities → RunLog (DB, TDD)

**Files:**
- Modify: `garmin_sync.py`
- Modify: `tests/test_garmin_sync.py`

- [ ] **Step 1: Write failing DB tests** (append)

```python
# ---------- DB tests: sync_activities ----------

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _mk_user(db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    return u


def _mk_state(db, uid, start):
    from models import AppState
    s = AppState.query.filter_by(user_id=uid).first()
    if not s:
        s = AppState(user_id=uid)
        db.session.add(s)
    s.start_date = start
    db.session.commit()
    return s


class FakeGC:
    connected = True

    def __init__(self, activities=None):
        self.activities = activities or []
        self.uploaded, self.scheduled, self.deleted = [], [], []
        self._next_id = 1000

    def get_activities_between(self, start_iso, end_iso):
        return self.activities

    def upload_workout(self, wj):
        self._next_id += 1
        self.uploaded.append(wj)
        return {"workoutId": self._next_id}

    def schedule_workout(self, wid, date_str):
        self.scheduled.append((str(wid), date_str))
        return {}

    def delete_workout(self, wid):
        self.deleted.append(str(wid))
        return True


def _act(aid, day_iso, type_key="running", meters=8047, secs=3000, hr=140, elev_m=30):
    return {
        "activityId": aid,
        "activityName": "Morning Run",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": f"{day_iso} 06:10:00",
        "distance": meters,
        "duration": secs,
        "averageHR": hr,
        "elevationGain": elev_m,
    }


def test_sync_creates_garmin_runlog_and_audit_row(app_ctx):
    app_, db = app_ctx
    from models import RunLog, GarminActivity
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    gc = FakeGC([_act(101, "2026-01-06")])  # week 1, day 1
    res = sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 7))
    assert res["error"] is None
    assert "w1d1" in res["days_filled"]
    rl = RunLog.query.filter_by(user_id=u.id, week=1, day_idx=1).first()
    assert rl is not None and rl.source == "garmin"
    assert rl.distance_miles == 5.0 and rl.duration_min == 50 and rl.avg_hr == 140
    assert GarminActivity.query.filter_by(garmin_activity_id="101").count() == 1


def test_sync_never_overwrites_manual_log(app_ctx):
    app_, db = app_ctx
    from models import RunLog
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull2@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    db.session.add(RunLog(user_id=u.id, week=1, day_idx=2, distance_miles=5.2,
                          avg_hr=131, duration_min=48, source="manual",
                          log_date=date(2026, 1, 7)))
    db.session.commit()
    gc = FakeGC([_act(102, "2026-01-07", meters=8000, hr=145)])
    res = sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 8))
    assert "w1d2" in res["days_skipped_manual"]
    rl = RunLog.query.filter_by(user_id=u.id, week=1, day_idx=2).first()
    assert rl.distance_miles == 5.2 and rl.avg_hr == 131  # untouched


def test_sync_legacy_null_source_treated_as_manual(app_ctx):
    app_, db = app_ctx
    from models import RunLog
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull3@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    db.session.add(RunLog(user_id=u.id, week=1, day_idx=3, distance_miles=4.0,
                          source=None, log_date=date(2026, 1, 8)))
    db.session.commit()
    gc = FakeGC([_act(103, "2026-01-08")])
    res = sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 9))
    assert "w1d3" in res["days_skipped_manual"]
    assert RunLog.query.filter_by(user_id=u.id, week=1, day_idx=3).first().distance_miles == 4.0


def test_sync_doubles_aggregate_and_resync_idempotent(app_ctx):
    app_, db = app_ctx
    from models import RunLog, GarminActivity
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull4@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    gc = FakeGC([
        _act(104, "2026-01-09", meters=6437, secs=2400, hr=120, elev_m=20),  # 4mi 40min
        _act(105, "2026-01-09", meters=3219, secs=1200, hr=150, elev_m=10),  # 2mi 20min
    ])
    sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 10))
    rl = RunLog.query.filter_by(user_id=u.id, week=1, day_idx=4).first()
    assert rl.distance_miles == 6.0 and rl.duration_min == 60 and rl.avg_hr == 130
    # re-sync: no duplicate audit rows, log still correct (garmin rows updatable)
    sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 10))
    assert GarminActivity.query.filter_by(user_id=u.id, week=1, day_idx=4).count() == 2
    assert RunLog.query.filter_by(user_id=u.id, week=1, day_idx=4).count() == 1


def test_sync_ignores_strength_and_out_of_program(app_ctx):
    app_, db = app_ctx
    from models import RunLog, GarminActivity
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull5@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    gc = FakeGC([
        _act(106, "2026-01-10", type_key="strength_training"),
        _act(107, "2026-01-01"),  # before program start
    ])
    res = sync_activities(gc, u.id, days_back=30, today=date(2026, 1, 10))
    assert res["ignored"] == 1
    row = GarminActivity.query.filter_by(garmin_activity_id="107").first()
    assert row is not None and row.week is None and row.day_idx is None
    assert RunLog.query.filter_by(user_id=u.id, week=None).count() == 0


def test_sync_fetch_failure_reports_error(app_ctx):
    app_, db = app_ctx
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull6@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))

    class DeadGC(FakeGC):
        def get_activities_between(self, s, e):
            return None

    res = sync_activities(DeadGC(), u.id, days_back=3, today=date(2026, 1, 10))
    assert res["error"] is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -x -q` — FAIL (`sync_activities` not defined).

- [ ] **Step 3: Implement `sync_activities`** (append to `garmin_sync.py`)

```python
# ---------------------------------------------------------------------------
# PULL: Garmin activities → GarminActivity audit rows → RunLog
# ---------------------------------------------------------------------------

_RAW_KEYS = ("activityId", "activityName", "startTimeLocal", "distance",
             "duration", "averageHR", "maxHR", "elevationGain")


def sync_activities(gc, user_id, days_back=3, today=None):
    """Pull recent running/HIIT activities and fill RunLog for days the user
    hasn't logged manually. Manual logs (source NULL/'manual') are never
    touched; sync-created logs (source='garmin') are kept up to date."""
    from models import db, AppState, RunLog, GarminActivity

    result = {"pulled": 0, "days_filled": [], "days_skipped_manual": [],
              "ignored": 0, "error": None}
    today = today or date.today()
    state = AppState.query.filter_by(user_id=user_id).first()
    start_date = state.start_date if state else None

    start = (today - timedelta(days=days_back)).isoformat()
    acts = gc.get_activities_between(start, today.isoformat())
    if acts is None:
        result["error"] = "Garmin activity fetch failed (not connected or rate limited)"
        return result

    touched = set()
    for a in acts:
        type_key = ((a.get("activityType") or {}).get("typeKey") or "").lower()
        if type_key not in RUN_TYPE_KEYS | HIIT_TYPE_KEYS:
            result["ignored"] += 1
            continue
        aid = str(a.get("activityId"))
        start_local = a.get("startTimeLocal") or ""
        act_date = None
        if len(start_local) >= 10:
            try:
                act_date = date.fromisoformat(start_local[:10])
            except ValueError:
                act_date = None
        week, day_idx = week_day_for_date(start_date, act_date)
        fields = dict(
            user_id=user_id,
            type_key=type_key,
            start_time_local=start_local,
            activity_date=act_date,
            week=week,
            day_idx=day_idx,
            distance_miles=round((a.get("distance") or 0) / 1609.344, 2),
            duration_min=int(round((a.get("duration") or 0) / 60.0)),
            avg_hr=int(a["averageHR"]) if a.get("averageHR") else None,
            elevation_ft=int(round((a.get("elevationGain") or 0) * 3.28084)),
            raw_summary=json.dumps({k: a.get(k) for k in _RAW_KEYS}),
        )
        row = GarminActivity.query.filter_by(user_id=user_id, garmin_activity_id=aid).first()
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
        else:
            db.session.add(GarminActivity(garmin_activity_id=aid, **fields))
            result["pulled"] += 1
        if week is not None:
            touched.add((week, day_idx))
    db.session.commit()

    for week, day_idx in sorted(touched):
        key = f"w{week}d{day_idx}"
        existing = RunLog.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if existing and (existing.source or "manual") != "garmin":
            result["days_skipped_manual"].append(key)
            continue
        rows = GarminActivity.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).all()
        agg = aggregate_day(rows)
        if not agg:
            continue
        if not existing:
            existing = RunLog(user_id=user_id, week=week, day_idx=day_idx,
                              log_date=rows[0].activity_date)
            db.session.add(existing)
        existing.distance_miles = agg["distance_miles"]
        existing.duration_min = agg["duration_min"]
        existing.avg_hr = agg["avg_hr"]
        existing.elevation_ft = agg["elevation_ft"]
        existing.source = "garmin"
        result["days_filled"].append(key)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.exception("Garmin sync RunLog commit failed")
        result["error"] = f"DB commit failed: {e}"
    return result
```

- [ ] **Step 4: Run tests** — all PASS.

- [ ] **Step 5: Commit**

```bash
git add garmin_sync.py tests/test_garmin_sync.py
git commit -m "Garmin sync: pull activities into RunLog (fill-only, manual logs sacred, doubles aggregate)"
```

---

### Task 6: Push — planned week → scheduled Garmin workouts (DB, TDD)

**Files:**
- Modify: `garmin_sync.py`
- Modify: `tests/test_garmin_sync.py`

- [ ] **Step 1: Write failing tests** (append; reuses `app_ctx`, `FakeGC`, `_mk_user`, `_mk_state` from Task 5)

```python
# ---------- DB tests: push_week ----------

def _mk_run_plan(db, uid, week, day_idx, detail, duration, label="Run", run_type="z2", segments_json=None):
    from models import WeeklyRunPlan
    WeeklyRunPlan.query.filter_by(user_id=uid, week=week, day_idx=day_idx).delete()
    db.session.add(WeeklyRunPlan(
        user_id=uid, week=week, day_idx=day_idx, run_type=run_type, label=label,
        duration=duration, detail=detail, segments_json=segments_json, source="coach"))
    db.session.commit()


def test_push_week_uploads_and_schedules_future_days(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push1@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 2, 1, "10 min warmup; 6×3 min hard @ HR ≥165 / 3 min easy; 7 min cooldown — why",
                 "53 min", label="VO2", run_type="vo2")
    gc = FakeGC()
    res = push_week(gc, u.id, 2, today=date(2026, 1, 12))  # week 2 day 1 = Jan 13 (future)
    assert [p["day"] for p in res["pushed"]] == [1]
    assert len(gc.uploaded) == 1 and gc.scheduled[0][1] == "2026-01-13"
    # interval structure made it through
    steps = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"]
    assert any(s.get("type") == "RepeatGroupDTO" and s["numberOfIterations"] == 6 for s in steps)
    link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=2, day_idx=1).first()
    assert link.status == "ok" and link.garmin_workout_id and link.scheduled_date == date(2026, 1, 13)


def test_push_week_skips_past_days_and_unchanged(app_ctx):
    app_, db = app_ctx
    from garmin_sync import push_week
    u = _mk_user(db, "push2@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 2, 0, "30 min steady (@ HR ≤135) — why", "30 min")  # Jan 12
    _mk_run_plan(db, u.id, 2, 2, "40 min steady (@ HR ≤135) — why", "40 min")  # Jan 14
    gc = FakeGC()
    res = push_week(gc, u.id, 2, today=date(2026, 1, 13))
    assert {s["day"] for s in res["skipped"] if s["reason"] == "past"} == {0}
    assert [p["day"] for p in res["pushed"]] == [2]
    # second push: unchanged → no new uploads
    res2 = push_week(gc, u.id, 2, today=date(2026, 1, 13))
    assert {s["day"] for s in res2["skipped"] if s["reason"] == "unchanged"} == {2}
    assert len(gc.uploaded) == 1


def test_push_week_replaces_changed_day(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push3@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 3, 1, "30 min steady (@ HR ≤135) — why", "30 min")
    gc = FakeGC()
    push_week(gc, u.id, 3, today=date(2026, 1, 19))
    old_id = GarminWorkoutLink.query.filter_by(user_id=u.id, week=3, day_idx=1).first().garmin_workout_id
    _mk_run_plan(db, u.id, 3, 1, "45 min steady (@ HR ≤140) — why", "45 min")
    res = push_week(gc, u.id, 3, today=date(2026, 1, 19))
    assert [p["day"] for p in res["pushed"]] == [1]
    assert gc.deleted == [old_id]
    new_link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=3, day_idx=1).first()
    assert new_link.garmin_workout_id != old_id and new_link.status == "ok"


def test_push_duration_mismatch_falls_back_to_simple(app_ctx):
    # Parsed prose totals 53 min but stored duration says 60 → push simple timed
    app_, db = app_ctx
    from garmin_sync import push_week
    u = _mk_user(db, "push4@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 4, 1, "10 min warmup; 6×3 min hard / 3 min easy; 7 min cooldown — why",
                 "60 min", label="VO2")
    gc = FakeGC()
    res = push_week(gc, u.id, 4, today=date(2026, 1, 26))
    assert [p["day"] for p in res["pushed"]] == [1]
    steps = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1 and steps[0]["endConditionValue"] == 3600.0


def test_push_unparseable_and_no_duration_fails_loud(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push5@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 5, 1, "go by feel — why", None)
    gc = FakeGC()
    res = push_week(gc, u.id, 5, today=date(2026, 2, 2))
    assert [f["day"] for f in res["failed"]] == [1]
    assert GarminWorkoutLink.query.filter_by(user_id=u.id, week=5, day_idx=1).first().status == "failed"


def test_push_upload_error_marks_failed(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push6@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 6, 1, "30 min steady — why", "30 min")

    class FailGC(FakeGC):
        def upload_workout(self, wj):
            raise RuntimeError("garmin 500")

    res = push_week(FailGC(), u.id, 6, today=date(2026, 2, 9))
    assert [f["day"] for f in res["failed"]] == [1]
    link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=6, day_idx=1).first()
    assert link.status == "failed" and "garmin 500" in (link.error or "")


def test_push_prefers_segments_json_over_prose(app_ctx):
    app_, db = app_ctx
    from garmin_sync import push_week
    u = _mk_user(db, "push7@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    import json as _json
    segs = [{"kind": "steady", "minutes": 42, "reps": 1, "hr": "≤138"}]
    _mk_run_plan(db, u.id, 7, 1, "UNPARSEABLE PROSE", "42 min", segments_json=_json.dumps(segs))
    gc = FakeGC()
    res = push_week(gc, u.id, 7, today=date(2026, 2, 16))
    assert [p["day"] for p in res["pushed"]] == [1]
    step = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"][0]
    assert step["endConditionValue"] == 2520.0 and step["targetValueTwo"] == 138
```

- [ ] **Step 2: Run to verify failure** — FAIL (`push_week` not defined).

- [ ] **Step 3: Implement `push_week`** (append to `garmin_sync.py`)

```python
# ---------------------------------------------------------------------------
# PUSH: planned run/HIIT days → uploaded + calendar-scheduled Garmin workouts
# ---------------------------------------------------------------------------

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _minutes_from_duration(duration):
    """'53 min' → 53. None when absent/unparseable."""
    if not duration:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(duration))
    return _num(m.group(1)) if m else None


def _resolve_segments(plan):
    """segments_json (authoritative) → prose parse (validated against the
    stored duration) → None. A None means: fall back to simple timed."""
    if plan.segments_json:
        try:
            segs = json.loads(plan.segments_json)
            if isinstance(segs, list) and segs:
                return segs
        except Exception:
            log.warning("Bad segments_json on w%sd%s", plan.week, plan.day_idx)
    segs = parse_detail_to_segments(plan.detail)
    if not segs:
        return None
    planned = _minutes_from_duration(plan.duration)
    if planned is not None and abs(segments_total_minutes(segs) - planned) > 0.51:
        log.warning("Parsed segments total %s != stored duration %s (w%sd%s) — falling back",
                    segments_total_minutes(segs), plan.duration, plan.week, plan.day_idx)
        return None
    return segs


def push_week(gc, user_id, week, today=None):
    """Upload + schedule structured workouts for every planned run/HIIT day of
    `week` that is today or later. Idempotent via structure_hash; a changed day
    deletes its stale Garmin workout first. Failures are recorded on the link
    row and reported — never raised."""
    from models import db, AppState, WeeklyRunPlan, GarminWorkoutLink

    result = {"pushed": [], "skipped": [], "failed": []}
    today = today or date.today()
    state = AppState.query.filter_by(user_id=user_id).first()
    if not state or not state.start_date:
        result["failed"].append({"day": None, "error": "no program start_date"})
        return result

    plans = WeeklyRunPlan.query.filter_by(user_id=user_id, week=week).all()
    for plan in sorted(plans, key=lambda p: p.day_idx):
        day_date = state.start_date + timedelta(days=(week - 1) * 7 + plan.day_idx)
        if day_date < today:
            result["skipped"].append({"day": plan.day_idx, "reason": "past"})
            continue

        segments = _resolve_segments(plan)
        name = f"12W Wk{week} {_DAY_NAMES[plan.day_idx]} — {plan.label or 'Run'} {plan.duration or ''}".strip()
        if segments:
            wj = build_workout_json(name, segments)
        else:
            total = _minutes_from_duration(plan.duration)
            wj = build_simple_timed_workout(name, total) if total else None

        link = GarminWorkoutLink.query.filter_by(
            user_id=user_id, week=week, day_idx=plan.day_idx).first()
        if not link:
            link = GarminWorkoutLink(user_id=user_id, week=week, day_idx=plan.day_idx)
            db.session.add(link)

        if wj is None:
            link.status = "failed"
            link.error = "no recoverable structure and no duration"
            result["failed"].append({"day": plan.day_idx, "error": link.error})
            db.session.commit()
            continue

        h = structure_hash(wj, day_date.isoformat())
        if link.structure_hash == h and link.status == "ok":
            result["skipped"].append({"day": plan.day_idx, "reason": "unchanged"})
            continue

        try:
            if link.garmin_workout_id:
                gc.delete_workout(link.garmin_workout_id)  # best-effort
            resp = gc.upload_workout(wj)
            wid = str((resp or {}).get("workoutId"))
            if not wid or wid == "None":
                raise RuntimeError(f"upload returned no workoutId: {resp}")
            gc.schedule_workout(wid, day_date.isoformat())
            link.garmin_workout_id = wid
            link.scheduled_date = day_date
            link.structure_hash = h
            link.status = "ok"
            link.error = None
            link.pushed_at = datetime.now(timezone.utc)
            result["pushed"].append({"day": plan.day_idx, "workout_id": wid,
                                     "date": day_date.isoformat()})
        except Exception as e:
            log.exception("Garmin push failed w%sd%s", week, plan.day_idx)
            link.status = "failed"
            link.error = str(e)[:500]
            result["failed"].append({"day": plan.day_idx, "error": str(e)[:200]})
        db.session.commit()
    return result
```

- [ ] **Step 4: Run the full new test file**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add garmin_sync.py tests/test_garmin_sync.py
git commit -m "Garmin sync: push planned week as scheduled structured workouts (idempotent, fail-loud)"
```

---

### Task 7: GarminClient activity + workout wrappers

**Files:**
- Modify: `garmin_client.py` (append methods to `GarminClient`, after `get_weekly_hrv` ~line 279)

- [ ] **Step 1: Add the wrapper methods**

```python
    # ── Activities + workouts (sync support) ──────────────────────────────

    def get_activities_between(self, start_iso, end_iso):
        """List activities between two ISO dates (inclusive). None on failure
        (caller treats None as 'fetch failed', distinct from empty list)."""
        if not self.connected:
            return None
        try:
            return self.api.get_activities_by_date(start_iso, end_iso)
        except Exception as e:
            err = str(e)
            if "429" in err or "Too Many" in err:
                self._rate_limited_until = time.time() + 900
            log.warning("Garmin activities fetch failed: %s", e)
            return None

    def upload_workout(self, workout_json):
        """Create a structured workout on Garmin Connect. Raises on failure —
        push_week records the error on the link row."""
        return self.api.upload_workout(workout_json)

    def schedule_workout(self, workout_id, date_str):
        """Schedule an uploaded workout on a calendar date (YYYY-MM-DD)."""
        return self.api.schedule_workout(workout_id, date_str)

    def delete_workout(self, workout_id):
        """Best-effort delete of a previously pushed workout (stale re-push)."""
        try:
            self.api.garth.request(
                "DELETE", "connectapi",
                f"{self.api.garmin_workouts}/workout/{workout_id}", api=True)
            return True
        except Exception as e:
            log.warning("Garmin workout delete failed (%s): %s", workout_id, e)
            return False
```

- [ ] **Step 2: Verify the lib attribute exists**

Run: `venv/bin/python -c "import garminconnect, inspect; src=inspect.getsource(garminconnect.Garmin.__init__); print('garmin_workouts' in src)"`
Expected: `True`. (If False, grep the package for the workout URL attribute name and adjust `delete_workout` accordingly — `upload_workout` in the lib uses `f"{self.garmin_workouts}/workout"`.)

- [ ] **Step 3: Full test suite still green**

Run: `venv/bin/python -m pytest tests/ -q -x -p no:cacheprovider -k "garmin or run_formatter"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add garmin_client.py
git commit -m "Garmin sync: GarminClient activity-fetch + workout upload/schedule/delete wrappers"
```

---

### Task 8: Persist coach segments at planning time

**Files:**
- Modify: `coach_planning_runs.py` (~lines 442-462)
- Modify: `app.py` (~lines 4862-4878)

- [ ] **Step 1: Carry segments through the coach output**

In `coach_planning_runs.py`, the validation block currently reads (lines ~442-448):

```python
        segments = v.get("segments")
        if isinstance(segments, list) and segments:
            segments = _normalize_interval_recovery(segments)
            duration = f"{_segments_total_min(segments)} min"
            detail = _segments_to_detail(segments)
        else:
            duration = v.get("duration") or v.get("time") or "30 min"
            detail = v.get("detail") or ""
```

Change the `else` branch to also null the segments, and include them in the output dict (lines ~456-462):

```python
        segments = v.get("segments")
        if isinstance(segments, list) and segments:
            segments = _normalize_interval_recovery(segments)
            duration = f"{_segments_total_min(segments)} min"
            detail = _segments_to_detail(segments)
        else:
            duration = v.get("duration") or v.get("time") or "30 min"
            detail = v.get("detail") or ""
            segments = None
```

```python
        out[day_idx] = {
            "type": v.get("type") or "z2",
            "label": v.get("label") or "Run",
            "duration": duration,
            "detail": detail,
            "segments": segments,
        }
```

(Exact surrounding code may differ slightly — keep every existing key and only add `"segments"`. If the rationale/why is appended to `detail` elsewhere in this function, leave that untouched.)

- [ ] **Step 2: Persist segments_json in the save loop**

In `app.py` (~lines 4862-4878), extend `progressed` and the `WeeklyRunPlan(...)` constructor:

```python
            progressed = {
                "type": coach_run["type"],
                "label": coach_run["label"],
                "time": coach_run["duration"],
                "detail": coach_run["detail"],
                "segments": coach_run.get("segments"),
            }

            db.session.add(WeeklyRunPlan(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                run_type=progressed.get('type', 'z2'),
                label=progressed.get('label', 'Run'),
                duration=progressed.get('time', '30 min'),
                detail=progressed.get('detail', ''),
                segments_json=json.dumps(progressed["segments"]) if progressed.get("segments") else None,
                source='coach',
            ))
```

(`json` is already imported at the top of app.py — verify with `grep -n "^import json" app.py`; if absent, add it.)

- [ ] **Step 3: Persist segments in the gap-fill path too**

`_fill_missing_week_runs` (`app.py:3954`, save at ~3994) also writes coach runs (fail-loud gap fill when a preserved week has lifts but no runs). Extend its constructor identically:

```python
        db.session.add(WeeklyRunPlan(
            user_id=user_id, week=target_week, day_idx=di,
            run_type=cr["type"], label=cr["label"], duration=cr["duration"],
            detail=cr.get("detail", ""),
            segments_json=json.dumps(cr["segments"]) if cr.get("segments") else None,
            source='coach',
        ))
```

- [ ] **Step 4: Mid-week coach run edits void stale segments and re-push**

`_parse_coach_markers` (`app.py:613`, `[RUN: day=…]` block at ~743-768) codifies mid-week run changes by editing the `WeeklyRunPlan` row. A changed duration makes any stored `segments_json` wrong (it would push intervals that no longer match the plan), and the watch workout goes stale. In the `if wrp:` branch add the clear, and after the `db.session.commit()` add a best-effort re-push:

```python
            wrp = WeeklyRunPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if wrp:
                wrp.duration = duration
                if run_type:
                    wrp.run_type = run_type
                wrp.source = 'coach'
                wrp.segments_json = None  # duration changed — old structure is void
            else:
                db.session.add(WeeklyRunPlan(
                    user_id=user_id, week=week, day_idx=day_idx,
                    run_type=run_type or 'z2', label=run_type or 'Run',
                    duration=duration, detail=reason, source='coach'))
            db.session.commit()
            # Re-push the changed day to Garmin (hash makes the other days no-ops).
            _garmin_push_week_best_effort(user_id, week)
```

Define the helper directly after `_get_garmin` (`app.py:~882`) — Task 9 reuses it:

```python
def _garmin_push_week_best_effort(user_id, week):
    """Push a week's planned runs/HIIT to Garmin. Best-effort: never raises —
    a Garmin failure must never break planning or chat."""
    try:
        import garmin_sync
        gc = _get_garmin(user_id)
        if not gc.connected:
            gc.try_restore_tokens(user_id)
        if not gc.connected:
            return
        res = garmin_sync.push_week(gc, user_id, week, today=_user_today())
        logging.info("[GARMIN] push wk%s: pushed=%s skipped=%s failed=%s",
                     week, len(res["pushed"]), len(res["skipped"]), len(res["failed"]))
    except Exception:
        logging.exception("[GARMIN] best-effort push failed (wk%s)", week)
```

(`_user_today()` is defined at `app.py:905`, after this helper — that's fine, it's resolved at call time. With segments_json cleared and the old prose now disagreeing with the new duration, `_resolve_segments` falls back to a simple timed workout at the NEW duration — honest, never stale intervals.)

- [ ] **Step 5: Admin copy-week carries segments_json**

In the admin copy-week endpoint (`app.py:~1794`), add `segments_json=r.segments_json,` to the copied `WeeklyRunPlan(...)` constructor.

- [ ] **Step 6: Existing suite still green**

Run: `venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
Expected: PASS (the added `"segments"` key must not break `test_run_formatter.py` / `test_run_regression_floor.py`; if a test asserts the exact dict shape, update that test to include the new key).

- [ ] **Step 7: Commit**

```bash
git add coach_planning_runs.py app.py
git commit -m "Garmin sync: persist coach run segments; mid-week run edits void stale structure and re-push"
```

---

### Task 9: API endpoints + auto-push hook + manual-source stamping

**Files:**
- Modify: `app.py` (models import ~line 30s; garmin endpoints after `/api/garmin/logout` ~line 8176; run-plan commit hook ~line 4888; `/api/run-log` GET+POST ~lines 10364-10400)

- [ ] **Step 1: Import the new models**

Find the `from models import (...)` block at the top of `app.py` (it already imports `GarminTokens`, `RunLog`, `WeeklyRunPlan`, `AppState`) and add `GarminActivity, GarminWorkoutLink` to it.

- [ ] **Step 2: Add the three endpoints** (place directly after the `garmin_logout` endpoint, ~line 8176)

```python
_garmin_sync_last = {}  # user_id -> epoch seconds of last successful pull


@app.route("/api/garmin/sync-activities", methods=["POST"])
@login_required
def garmin_sync_activities():
    """Pull recent Garmin activities into RunLog. Throttled to 15 min unless
    {"force": true} (the manual Sync Now button)."""
    import garmin_sync
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    now = time.time()
    last = _garmin_sync_last.get(current_user.id, 0)
    if not force and now - last < 900:
        return jsonify({"throttled": True,
                        "seconds_until_next": int(900 - (now - last)),
                        "days_filled": []})
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        return jsonify({"error": "Not connected to Garmin"}), 401
    result = garmin_sync.sync_activities(
        gc, current_user.id,
        days_back=int(data.get("days_back") or 3),
        today=_user_today())
    if not result.get("error"):
        _garmin_sync_last[current_user.id] = now
    return jsonify(result)


@app.route("/api/garmin/push-week", methods=["POST"])
@login_required
def garmin_push_week():
    """Push the given week's planned runs/HIIT to the watch as scheduled workouts."""
    import garmin_sync
    data = request.get_json(silent=True) or {}
    week = int(data.get("week") or _current_week())
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        return jsonify({"error": "Not connected to Garmin"}), 401
    result = garmin_sync.push_week(gc, current_user.id, week, today=_user_today())
    return jsonify(result)


@app.route("/api/garmin/sync-status")
@login_required
def garmin_sync_status():
    """Connection + last pull + per-day push status for the settings panel."""
    week = request.args.get("week", type=int) or _current_week()
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    last = _garmin_sync_last.get(current_user.id)
    links = GarminWorkoutLink.query.filter_by(user_id=current_user.id, week=week).all()
    return jsonify({
        "connected": gc.connected,
        "last_activity_sync": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
        "week": week,
        "workouts": [{
            "day_idx": l.day_idx,
            "status": l.status,
            "error": l.error,
            "scheduled_date": l.scheduled_date.isoformat() if l.scheduled_date else None,
            "garmin_workout_id": l.garmin_workout_id,
        } for l in sorted(links, key=lambda x: x.day_idx)],
    })
```

Verify `import time`, `from datetime import datetime, timezone` (or equivalents) already exist at the top of app.py — `time.time()` and `datetime` are used elsewhere (e.g. `_rate_limited_until` handling, GarminTokens default). Add any missing import.

- [ ] **Step 3: Auto-push hook at BOTH generation exits**

`_weekly_generation_impl` (`app.py:4141`) has TWO function-level returns: the preserve-history early return at ~line 4240 and the main return at ~5033. Insert a call to the Task 8 helper immediately before each:

```python
    _garmin_push_week_best_effort(current_user.id, target_week)
```

(Both branches save run plans — the early branch via `_fill_missing_week_runs`. Do NOT append push results to `run_summary` — the coach consumes it; the helper logs instead.)

- [ ] **Step 4: Stamp manual source on run logs**

In `api_run_log` POST (~app.py:10364): add `existing.source = "manual"` in the update branch, and `source="manual"` in the create constructor:

```python
    if existing:
        existing.distance_miles = data.get("distance_miles")
        existing.avg_hr = data.get("avg_hr")
        existing.elevation_ft = data.get("elevation_ft")
        existing.duration_min = data.get("duration_min")
        existing.notes = data.get("notes")
        existing.source = "manual"
    else:
        existing = RunLog(
            user_id=current_user.id, week=data.get("week"), day_idx=data.get("day_idx"),
            distance_miles=data.get("distance_miles"), avg_hr=data.get("avg_hr"),
            elevation_ft=data.get("elevation_ft"), duration_min=data.get("duration_min"),
            notes=data.get("notes"), log_date=_user_today(), source="manual",
        )
```

In `api_run_logs` GET (~app.py:10393): include source:

```python
    return jsonify({f"{l.week}_{l.day_idx}": {
        "distance_miles": l.distance_miles, "avg_hr": l.avg_hr,
        "elevation_ft": l.elevation_ft, "duration_min": l.duration_min,
        "source": l.source or "manual",
    } for l in logs})
```

- [ ] **Step 5: Run full suite + app boot smoke**

Run: `venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
Expected: PASS.
Run: `venv/bin/python -c "import os; os.environ['DATABASE_URL']='sqlite:////tmp/garmin_boot_test.db'; import app; print('boot ok')"`
Expected: `boot ok`.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "Garmin sync: sync/push/status endpoints, auto-push after planning, manual source stamping"
```

---

### Task 10: Frontend — settings panel, auto-pull, provenance marker

**Files:**
- Modify: `static/app.js` (settings dropdown ~4748-4789; garminLogin `closeModal()` calls ~6849-6935; run-log cache load ~5272; logged-run display ~10254; saveRunLog cache ~7505)

- [ ] **Step 1: Add Garmin button to the settings dropdown**

In `showSettingsMenu()` (~app.js:4762), add before the Export Data button:

```js
    <button onclick="${_c}showGarminPanel()">&#8986; Garmin Sync</button>
```

- [ ] **Step 2: Add the Garmin panel**

Add near the other garmin functions (~app.js:6849). The login form reuses the existing `garminLogin()` element IDs (`garmin-email`, `garmin-password`, `garmin-mfa`, `garmin-error`, `garmin-submit`):

```js
function closeGarminPanel() {
  const el = document.getElementById('garmin-panel');
  if (el) el.remove();
}

async function showGarminPanel() {
  closeGarminPanel();
  const wrap = document.createElement('div');
  wrap.id = 'garmin-panel';
  wrap.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px';
  wrap.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;max-width:440px;width:100%;max-height:85vh;overflow-y:auto;padding:20px" onclick="event.stopPropagation()">' +
      '<h3 style="font-size:20px;margin-bottom:14px">&#8986; Garmin Sync</h3>' +
      '<div id="garmin-panel-body" style="font-size:16px">Loading&hellip;</div>' +
      '<button class="btn btn-secondary" style="width:100%;margin-top:14px;font-size:16px" onclick="closeGarminPanel()">Close</button>' +
    '</div>';
  wrap.onclick = closeGarminPanel;
  document.body.appendChild(wrap);
  await renderGarminPanelBody();
}

async function renderGarminPanelBody() {
  const body = document.getElementById('garmin-panel-body');
  if (!body) return;
  let st = null;
  try { st = await (await fetch('/api/garmin/sync-status?week=' + currentWeek)).json(); } catch(e) {}
  if (!st || !st.connected) {
    body.innerHTML =
      '<div style="color:var(--muted);margin-bottom:10px">Not connected.</div>' +
      '<input id="garmin-email" type="email" placeholder="Garmin email" class="weight-input" style="width:100%;margin-bottom:8px;font-size:16px">' +
      '<input id="garmin-password" type="password" placeholder="Password" class="weight-input" style="width:100%;margin-bottom:8px;font-size:16px">' +
      '<input id="garmin-mfa" type="text" placeholder="MFA code" class="weight-input" style="width:100%;margin-bottom:8px;font-size:16px;display:none">' +
      '<div id="garmin-error" style="display:none;color:#e66;margin-bottom:8px"></div>' +
      '<button id="garmin-submit" class="btn btn-primary" style="width:100%;font-size:16px" onclick="garminLogin()">Connect</button>';
    return;
  }
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const rows = (st.workouts || []).map(w =>
    '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">' +
      '<span>' + days[w.day_idx] + (w.scheduled_date ? ' &middot; ' + w.scheduled_date : '') + '</span>' +
      (w.status === 'ok'
        ? '<span style="color:var(--accent)">&#10003; on watch</span>'
        : '<span style="color:#e66" title="' + (w.error || '') + '">&#10007; failed</span>') +
    '</div>').join('');
  body.innerHTML =
    '<div style="margin-bottom:10px;color:var(--accent)">&#10003; Connected</div>' +
    '<div style="color:var(--muted);font-size:14px;margin-bottom:12px">Last run sync: ' +
      (st.last_activity_sync ? st.last_activity_sync.replace('T', ' ').slice(0, 16) + ' UTC' : 'not yet this session') + '</div>' +
    '<button class="btn btn-primary" style="width:100%;font-size:16px;margin-bottom:8px" onclick="garminSyncNow(this)">Sync runs now</button>' +
    '<button class="btn btn-primary" style="width:100%;font-size:16px;margin-bottom:12px" onclick="garminPushWeek(this)">Push Week ' + currentWeek + ' to watch</button>' +
    '<div style="font-size:14px;color:var(--muted);margin-bottom:4px">Week ' + st.week + ' workouts on Garmin:</div>' +
    (rows || '<div style="color:var(--muted)">None pushed yet.</div>') +
    '<button class="btn btn-secondary" style="width:100%;margin-top:12px;font-size:14px" onclick="garminLogout().then(renderGarminPanelBody)">Disconnect Garmin</button>';
}

async function garminSyncNow(btn) {
  btn.disabled = true; btn.textContent = 'Syncing…';
  try {
    const d = await (await fetch('/api/garmin/sync-activities', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({force: true}),
    })).json();
    if (d.error) { showToast('Garmin sync failed: ' + d.error, 'error'); }
    else {
      showToast('Synced. ' + (d.days_filled || []).length + ' day(s) filled' +
        ((d.days_skipped_manual || []).length ? ', ' + d.days_skipped_manual.length + ' manual day(s) untouched' : ''), 'success');
      const rl = await fetch('/api/run-log');
      if (rl.ok) { _runLogCache = await rl.json(); renderDetail(); }
    }
  } catch(e) { showToast('Garmin sync failed', 'error'); }
  btn.disabled = false; btn.textContent = 'Sync runs now';
  renderGarminPanelBody();
}

async function garminPushWeek(btn) {
  btn.disabled = true; btn.textContent = 'Pushing…';
  try {
    const d = await (await fetch('/api/garmin/push-week', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({week: currentWeek}),
    })).json();
    if (d.error) { showToast('Push failed: ' + d.error, 'error'); }
    else {
      showToast('Pushed ' + (d.pushed || []).length + ', skipped ' + (d.skipped || []).length +
        ', failed ' + (d.failed || []).length, (d.failed || []).length ? 'error' : 'success');
    }
  } catch(e) { showToast('Push failed', 'error'); }
  btn.disabled = false; btn.textContent = 'Push Week ' + currentWeek + ' to watch';
  renderGarminPanelBody();
}
```

- [ ] **Step 3: Point garminLogin at the panel lifecycle**

In `garminLogin()` (~app.js:6875 and ~6911) replace both `closeModal();` calls with `renderGarminPanelBody();` (after successful connect the panel re-renders into the connected view; `refreshGarmin()`/`renderAll()` calls stay).

- [ ] **Step 4: Auto-pull on load**

At the run-log cache load (~app.js:5272), add immediately BEFORE the `const rlRes = await fetch('/api/run-log')` line:

```js
    // Garmin auto-pull (server throttles to 15 min). Fire-and-forget; if new
    // runs landed, refresh the cache + card. 401 (not connected) is silent.
    fetch('/api/garmin/sync-activities', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (d && (d.days_filled || []).length) {
          return fetch('/api/run-log').then(r => r.json())
            .then(j => { _runLogCache = j; renderDetail(); });
        }
      })
      .catch(() => {});
```

- [ ] **Step 5: Provenance marker on the day card**

In the logged-run display (~app.js:10254-10261), after the elevation span inside the "✓ Logged" row, add:

```js
                (existingRun.source === 'garmin' ? '<span style="opacity:0.75">&#8986; from Garmin</span>' : '') +
```

And in `saveRunLog()` (~app.js:7505), include source in the cache write:

```js
  _runLogCache[key] = { distance_miles: dist, avg_hr: hr, elevation_ft: elev, duration_min: dur, source: 'manual' };
```

- [ ] **Step 6: JS syntax check + manual smoke**

Run: `node --check static/app.js`
Expected: no output (valid).
Then start the app locally (`venv/bin/python app.py` or the project's usual command), open the settings menu → Garmin Sync panel renders (login form when disconnected), no console errors.

- [ ] **Step 7: Commit**

```bash
git add static/app.js
git commit -m "Garmin sync UI: settings panel (connect/sync/push/status), auto-pull on load, provenance marker"
```

---

### Task 11: Live end-to-end verification (with Erik, against his real account)

**Files:** none (verification only). Production debug base: `https://one2weeks-9ewf.onrender.com` (NOT 12weeks.onrender.com).

- [ ] **Step 1: Verify the Garmin workout JSON schema against a real workout**

With Erik's connected session (tokens already in DB, or restored via `garmin_token_helper.py`), fetch one workout we pushed: `get_workout_by_id(<id>)` and diff field names against our builder output (`sportType`, `workoutSegments[].workoutSteps[]`, `stepType`, `endCondition`, `targetType`, `targetValueOne/Two`, `RepeatGroupDTO.numberOfIterations`). Fix the builder + its tests if Garmin rejects or renames anything (the upload error will name the offending field).

- [ ] **Step 2: Push one real day**

From the settings panel: Push current week. Confirm: (a) response shows pushed days with workout ids; (b) workout appears in Garmin Connect calendar on the right date with correct interval structure; (c) Erik confirms it shows on the watch after a watch sync.

- [ ] **Step 3: Pull one real run**

After Erik's next run (he runs daily): open the app → auto-sync fires → the day card shows the run as "✓ Logged … ⌚ from Garmin" with distance/duration/HR matching Garmin Connect. Cross-check the served values via the admin debug endpoint (`?email=` GET) against the GarminActivity audit row — no UI contradictions.

- [ ] **Step 4: Verify manual-log protection live**

On a day Erik already logged manually, run Sync Now → response lists that day under `days_skipped_manual` and the card values are unchanged.

- [ ] **Step 5: Deploy**

Push to main → Render deploys. Do NOT loop-poll the deploy (standing rule); state that it's deploying and stop. NOTE: deploy wipes the in-process `_garmin_sync_last` throttle map — harmless (first load just syncs again).

---

## Execution notes for workers

- Run the full suite (`venv/bin/python -m pytest tests/ -q -p no:cacheprovider`) after Tasks 8, 9, 10 — not just the new file.
- `tests/conftest.py` already redirects `DATABASE_URL` to a temp sqlite before app import; never point tests at `local.db` or prod.
- Don't re-run weekly planning or `force_regen` against prod while testing the push hook — plan-display recovery rules (memory: planning persists, job store is in-process).
- The `wk11-12-final.json` strings in Task 2's tests are real production prose; do not "fix" the em-dash or `×` characters — the parser must handle the exact unicode the coach emits.
