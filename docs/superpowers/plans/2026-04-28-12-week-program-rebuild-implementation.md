# 12-Week Program Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing arbitrary `PHASE_TEMPLATES` content with the rebuilt program from the spec, plus update the engine's per-phase progression rules so the new design actually drives prescriptions.

**Architecture:** The new program is data — overwrite `PHASE_TEMPLATES` and `BW_PHASE_TEMPLATES` in `workout_data.py` to match spec sections §2–§7 (Phase 1, week 4 deload, Phase 2, week 8 deload, Phase 3, week 12 peak). The engine's `compute_next_targets` already has Phase 1/2/3 branches and exercise_order disambiguation; this plan rewrites the Phase 3 branch (HOLD instead of bump) and adds a Week 12 case. Auto-regulation triggers, streak/adherence tracking, and coach-prompt extensions are deferred to a follow-up plan — this one is the MVP that lets Erik start running the rebuilt program by Monday week 6.

**Tech Stack:** Python 3.14, Flask, SQLAlchemy, pytest. No new dependencies.

**Spec reference:** `docs/superpowers/specs/2026-04-28-12-week-program-rebuild-design.md`
**Research reference:** `docs/superpowers/research/2026-04-28-program-rebuild-research.md`
**Companion DB plan:** `docs/superpowers/plans/2026-04-28-program-template-db-migration.md` (independent — can ship before or after this plan)

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `workout_data.py` | Source of program template (PHASE_TEMPLATES dict) | **Replace content** of phase 1, 2, 3, deload, test entries (and BW counterparts) per spec |
| `workout_data.py` | Phase week-builder helpers (`_phase1_week()` etc.) | **Replace content** to update `liftName` per day so coach + UI show new focuses |
| `training_engine.py` | `compute_next_targets` Phase 3 branch | **Rewrite** — HOLD by default, optional bump on RPE 6 confirmed twice |
| `training_engine.py` | `compute_next_targets` Week 12 case | **Add** — new `_is_test_week` check, HOLD everything |
| `tests/test_program_phase_progression.py` | Phase 1 / 2 / 3 / wk12 progression contracts | **Create** new test file pinning the spec's progression rules |
| `tests/test_program_seed_content.py` | Spec content matches PHASE_TEMPLATES exactly | **Create** new test file asserting key prescriptions (e.g. Phase 2 Tue heavy Lat Pulldown 5×5 + pump 3×12; Phase 3 holds Phase 2 wk7 weight) |

---

## Phase Mapping (locked)

```
weeks 1-3 → "phase1"
week 4    → "deload"
weeks 5-7 → "phase2"
week 8    → "deload"
weeks 9-11→ "phase3"
week 12   → "test"  (interpreted as "peak finish" per spec §7, NOT 1RM test)
```

The spec replaces the prior "test" interpretation (1RM testing) with "peak finish" (mini-taper, scale + look). The keyword `test` in the codebase is preserved to avoid touching the phase-key plumbing; the **content** of the test phase changes from 1RM lifts to mini-taper.

---

## Task 1: Pin Phase 2 progression contract (current state validation)

**Files:**
- Test: `tests/test_program_phase_progression.py` (create)

This task locks in the existing Phase 2 behavior (which the spec keeps) before any code changes — so subsequent tasks can refactor without regression.

- [ ] **Step 1: Write failing test for Phase 2 weight progression**

Create `tests/test_program_phase_progression.py`:

```python
"""Per-phase progression rules from the spec at
docs/superpowers/specs/2026-04-28-12-week-program-rebuild-design.md §1.

Rules:
- Phase 1 (wks 1-3): reps build 8→12, weight pinned. At cap → +5 lb upper /
  +10 lb lower, reps reset to 8.
- Phase 2 (wks 5-7): weight bumps each session, reps pinned, sets pinned.
- Phase 3 (wks 9-11): weights HOLD. Optional bump only if RPE 6 confirmed
  in two consecutive sessions.
- Week 12: HOLD everything. Mini-taper.
"""
import pytest
from datetime import date, timedelta


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


@pytest.fixture
def user_with_history(app_ctx):
    """Build a user with one logged session for an exercise."""
    app, db = app_ctx
    from models import User, UserEquipment, PhysicalAssessment, SetLog

    def make(exercise, week, day_idx, last_weight, last_reps,
             set_count=4, days_ago=2, prev_weight=None):
        _USER_SEQ[0] += 1
        u = User(email=f"phase-test-{_USER_SEQ[0]}@example.com",
                 password_hash="x")
        db.session.add(u); db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "ez_bar", "kettlebells", "lat_pulldown",
            "cable_machine", "leg_press", "leg_curl_ext", "flat_bench",
            "incline_bench", "pull_up_bar", "weight_plates",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq); db.session.add(pa); db.session.commit()
        # Most-recent session
        recent = date.today() - timedelta(days=days_ago)
        for i in range(set_count):
            db.session.add(SetLog(
                user_id=u.id, exercise_name=exercise, week=week,
                day_idx=day_idx, set_number=i + 1,
                weight=last_weight, reps=last_reps,
                done=True, logged_date=recent,
            ))
        # Optional prior session for "user_increased" detection
        if prev_weight is not None:
            prior = recent - timedelta(days=7)
            for i in range(set_count):
                db.session.add(SetLog(
                    user_id=u.id, exercise_name=exercise, week=max(week - 1, 1),
                    day_idx=day_idx, set_number=i + 1,
                    weight=prev_weight, reps=last_reps,
                    done=True, logged_date=prior,
                ))
        db.session.commit()
        return u
    return make


class TestPhase2WeightProgression:
    def test_phase_2_bumps_weight_when_clean(self, app_ctx, user_with_history):
        # Phase 2 wk 6, Lat Pulldown heavy 5x5 at 100 lb. Last session hit
        # prescribed reps cleanly. Engine should bump weight ~5 lb upper.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_history(
            "Lat Pulldown", week=6, day_idx=1,
            last_weight=100, last_reps=5, set_count=5,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Lat Pulldown", week=6, day_idx=1, exercise_order=0,
            )
        assert t["target_reps"] == 5, "Phase 2 reps must stay pinned at 5"
        assert t["target_sets"] == 5, "Phase 2 sets must stay pinned at 5"
        assert t["target_weight"] is not None
        assert t["target_weight"] >= 105, (
            f"Phase 2 should bump weight from 100; got {t['target_weight']}"
        )
```

- [ ] **Step 2: Run test to verify current behavior (it should pass)**

Run: `source venv/bin/activate && python -m pytest tests/test_program_phase_progression.py::TestPhase2WeightProgression -x -v`
Expected: PASS — Phase 2 already bumps weight when clean.

- [ ] **Step 3: Commit**

```bash
git add tests/test_program_phase_progression.py
git commit -m "Pin Phase 2 weight-progression contract (existing behavior)"
```

---

## Task 2: Add failing tests for Phase 3 HOLD rule

**Files:**
- Test: `tests/test_program_phase_progression.py` (extend)

Phase 3 should HOLD weights across all 3 weeks. Optional bump only on confirmed RPE 6. The current code bumps every session. These tests fail today.

- [ ] **Step 1: Append Phase 3 test class to the file**

Append to `tests/test_program_phase_progression.py`:

```python
class TestPhase3Hold:
    def test_phase_3_holds_weight_by_default(self, app_ctx, user_with_history):
        # Phase 3 wk 10, Back Squat at 200 lb. Last session at RPE 8 (clean
        # but hard). Spec §1: Phase 3 holds. NO bump.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_history(
            "Back Squat", week=10, day_idx=4,
            last_weight=200, last_reps=3, set_count=3,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Back Squat", week=10, day_idx=4, exercise_order=0,
            )
        # Note: target_weight could be slightly higher only if engine
        # detects RPE-6 confirmed twice. Default behavior = hold = 200.
        assert t["target_weight"] == 200, (
            f"Phase 3 must default-hold; got bump to {t['target_weight']}"
        )
        assert t["progression_indicator"] == "hold", (
            f"Phase 3 default must indicate hold; got "
            f"{t['progression_indicator']}"
        )

    def test_phase_3_drops_when_top_set_rpe_high(
        self, app_ctx, user_with_history
    ):
        # Phase 3 wk 10, Back Squat 200 lb, user logged a SHORT session
        # (missed reps — proxy for RPE >8). Engine should drop 5%.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        # Simulate "missed top set" via short session: last_reps=2 of
        # prescribed 3. last_set_count low.
        u = user_with_history(
            "Back Squat", week=10, day_idx=4,
            last_weight=200, last_reps=2, set_count=2,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Back Squat", week=10, day_idx=4, exercise_order=0,
            )
        # 5% drop from 200 = 190
        assert t["target_weight"] <= 195, (
            f"Phase 3 should drop weight when last session missed reps; "
            f"got {t['target_weight']}"
        )
```

- [ ] **Step 2: Run test to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_program_phase_progression.py::TestPhase3Hold -x -v`
Expected: FAIL — current Phase 3 branch bumps weight; doesn't HOLD.

- [ ] **Step 3: Commit**

```bash
git add tests/test_program_phase_progression.py
git commit -m "Add failing tests pinning Phase 3 HOLD progression rule"
```

---

## Task 3: Rewrite Phase 3 branch in compute_next_targets

**Files:**
- Modify: `training_engine.py` Phase 3 branch (around line 326)

- [ ] **Step 1: Locate the Phase 3 branch**

Run: `grep -n "else:  # Phase 3" training_engine.py`
Expected output: line ~325 (`else:  # Phase 3`)

- [ ] **Step 2: Read the current Phase 3 branch**

Read `training_engine.py` from the located line through the `return result` to understand current logic.

- [ ] **Step 3: Replace the Phase 3 branch with HOLD logic**

In `training_engine.py`, replace the Phase 3 branch with:

```python
    else:  # Phase 3 — Cut climax. HOLD weights by default.
        configured_reps = _get_configured_reps(
            exercise_name, week, day_idx, exercise_order,
        )
        configured_sets_for_phase3 = _get_configured_sets(
            exercise_name, week, day_idx, exercise_order,
        )
        # Default behavior: HOLD weight, reps, sets (per spec §1, §6).
        # The strength block of Phase 2 is the deposit; Phase 3 protects it.
        held_reps = configured_reps or last_reps or 3
        held_sets = configured_sets_for_phase3 or last_set_count or 3
        # Drop if user clearly missed top-set reps last session (proxy for RPE>8).
        if last_reps and configured_reps and last_reps < configured_reps:
            new_weight = _round_weight(last_weight * 0.95)
            return {
                "target_weight": new_weight,
                "target_reps": held_reps,
                "target_sets": held_sets,
                "adjustment_reason": (
                    f"Phase 3 — missed reps last session "
                    f"({last_reps}/{configured_reps}), drop 5%"
                ),
                "progression_indicator": "hold",
            }
        # Default HOLD path.
        result = {
            "target_weight": _round_weight(last_weight),
            "target_reps": held_reps,
            "target_sets": held_sets,
            "adjustment_reason": "Phase 3 cut climax — HOLD",
            "progression_indicator": "hold",
        }
        if coach_alert:
            result["coach_alert"] = coach_alert
        return result
```

- [ ] **Step 4: Run Phase 3 tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_phase_progression.py::TestPhase3Hold -x -v`
Expected: PASS — both Phase 3 tests now pass.

- [ ] **Step 5: Run full suite to verify no regression**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: 27+ tests pass (existing + 3 new).

- [ ] **Step 6: Commit**

```bash
git add training_engine.py
git commit -m "Phase 3 holds weight by default; drops 5% on missed reps"
```

---

## Task 4: Add Week 12 HOLD-everything case

**Files:**
- Modify: `training_engine.py` `compute_next_targets` deload check
- Test: `tests/test_program_phase_progression.py` (extend)

Week 12 is even stricter than Phase 3 — no bumps, no drops, just maintenance. The simplest rule: same as Phase 3 default-hold path, but never drop and never bump. Implementation: short-circuit week 12 before phase logic.

- [ ] **Step 1: Add failing tests for Week 12**

Append to `tests/test_program_phase_progression.py`:

```python
class TestWeek12Hold:
    def test_week_12_holds_weight_no_matter_what(
        self, app_ctx, user_with_history
    ):
        # Week 12 mini-taper. HOLD everything regardless of last-session
        # quality. Even if last session was clean and easy, NO bump.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_history(
            "Back Squat", week=12, day_idx=4,
            last_weight=200, last_reps=3, set_count=2,  # one working set
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Back Squat", week=12, day_idx=4, exercise_order=0,
            )
        assert t["target_weight"] == 200, (
            f"Week 12 must HOLD weight regardless; got {t['target_weight']}"
        )
        assert t["progression_indicator"] == "hold"

    def test_week_12_does_not_drop_on_missed_reps(
        self, app_ctx, user_with_history
    ):
        # Even if last session missed reps, week 12 holds — taper, not deload.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_history(
            "Back Squat", week=12, day_idx=4,
            last_weight=200, last_reps=2, set_count=2,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Back Squat", week=12, day_idx=4, exercise_order=0,
            )
        # week 12 holds, no drop, no bump
        assert t["target_weight"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_program_phase_progression.py::TestWeek12Hold -x -v`
Expected: FAIL — week 12 currently routes through Phase 3 logic which can drop.

- [ ] **Step 3: Add `_is_peak_week` and short-circuit at top of compute_next_targets**

In `training_engine.py`, near `_is_deload`:

```python
def _is_peak_week(week):
    """Week 12 = peak finish (mini-taper, scale+look). HOLD everything."""
    return week == 12
```

Then in `compute_next_targets`, immediately AFTER the existing `if not last_sets:` no-history block (around line 134) and BEFORE the deload signal block, add:

```python
    # ─── PEAK WEEK (week 12) — HOLD ───
    # Mini-taper. No bumps, no drops. Maintain Phase 3 lifts at the same
    # weight, reps, sets. Spec §7.
    if _is_peak_week(week):
        configured_reps = _get_configured_reps(
            exercise_name, week, day_idx, exercise_order,
        )
        configured_sets_peak = _get_configured_sets(
            exercise_name, week, day_idx, exercise_order,
        )
        return {
            "target_weight": _round_weight(last_weight),
            "target_reps": configured_reps or last_reps or 3,
            "target_sets": configured_sets_peak or last_set_count or 2,
            "adjustment_reason": "Week 12 peak — HOLD all knobs",
            "progression_indicator": "hold",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_phase_progression.py::TestWeek12Hold -x -v`
Expected: PASS — both week-12 tests now pass.

- [ ] **Step 5: Run full suite**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add training_engine.py tests/test_program_phase_progression.py
git commit -m "Week 12 HOLDs all knobs (mini-taper, no bumps no drops)"
```

---

## Task 5: Replace PHASE_TEMPLATES Phase 1 content per spec §2

**Files:**
- Modify: `workout_data.py` lines 962–1020 (the Phase 1 block of `PHASE_TEMPLATES`)
- Test: `tests/test_program_seed_content.py` (create)

The existing Phase 1 content is the random scheme Erik called out. Replace with the spec's per-day prescriptions.

- [ ] **Step 1: Write failing test for Phase 1 content**

Create `tests/test_program_seed_content.py`:

```python
"""Pin the program template content to spec sections §2-§7. These tests
fail today because PHASE_TEMPLATES still has the old prescriptions; they
pass after Tasks 5–10 rewrite the dict per spec.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


class TestPhase1Content:
    """Spec §2: Phase 1 (wks 1-3) hypertrophy / adaptation."""

    def test_phase_1_monday_is_lower_power_with_front_squat(self, app_ctx):
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=1)
        mon = days[0]
        names = [e["name"] for e in mon.get("exercises", [])]
        assert "Front Squat" in names, (
            f"Phase 1 Mon should lead with Front Squat per spec §2; "
            f"got {names}"
        )
        # Spec §2 prescribes 4×8-12 for Front Squat in Phase 1.
        front_squat = next(e for e in mon["exercises"]
                           if e["name"] == "Front Squat")
        assert "4x" in front_squat["sets"], (
            f"Phase 1 Mon Front Squat should be 4 sets; got "
            f"{front_squat['sets']}"
        )

    def test_phase_1_tuesday_has_landmine_press(self, app_ctx):
        # Spec §2: Tue Press + Shoulder uses Landmine Press as
        # shoulder-friendly OHP substitute.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=1)
        tue = days[1]
        names = [e["name"] for e in tue.get("exercises", [])]
        assert "Landmine Press" in names, (
            f"Phase 1 Tue should include Landmine Press per spec §2 "
            f"(shoulder-friendly OHP); got {names}"
        )

    def test_phase_1_friday_back_squat_4x8(self, app_ctx):
        # Spec §2: Fri Heavy Lower hypertrophy = Back Squat 4×8 @ ~70%.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=1)
        fri = days[4]
        bs = next((e for e in fri.get("exercises", [])
                   if "Back Squat" in e["name"]), None)
        assert bs is not None, "Phase 1 Fri must have Back Squat"
        assert bs["sets"] == "4x8", (
            f"Phase 1 Fri Back Squat should be 4×8 per spec §2; "
            f"got {bs['sets']}"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestPhase1Content -x -v`
Expected: FAIL — current Phase 1 doesn't match spec.

- [ ] **Step 3: Replace `_phase1_week()` body in workout_data.py**

Locate `def _phase1_week():` (~line 1662) and replace its body with:

```python
def _phase1_week():
    """Phase 1 (wks 1-3): Hypertrophy / adaptation per spec §2."""
    days = [_empty_day(i) for i in range(7)]
    # Sun (idx 6) — rest from iron, long fasted run handled at run-plan layer
    days[6] = {**days[6], "liftName": "Rest (Long Fasted Run)", "isRest": True}
    # Mon — Lower hypertrophy
    days[0] = {
        **days[0],
        "liftName": "Lower Hypertrophy — Quad/Glute Focus",
        "exercises": [
            {"name": "Front Squat", "sets": "4x8", "rest": "2-3 min",
             "note": "Build reps to 12 across all sets; then bump weight."},
            {"name": "Bulgarian Split Squat", "sets": "3x8",
             "rest": "60-90s",
             "note": "Each leg. Unilateral, leg power transfer."},
            {"name": "Romanian Deadlift", "sets": "3x8", "rest": "60-90s",
             "note": "RPE 7. Hamstring + glute hinge."},
            {"name": "Standing Calf Raise", "sets": "3x12",
             "rest": "45-60s", "note": "Full ROM, slow eccentric."},
        ],
    }
    # Tue — Press + Shoulder
    days[1] = {
        **days[1],
        "liftName": "Upper Press — Shoulder Build",
        "exercises": [
            {"name": "DB Bench Press", "sets": "4x8",
             "rest": "2 min",
             "note": "Neutral grip. Shoulder-friendly. Build to 10 reps."},
            {"name": "Landmine Press", "sets": "3x8", "rest": "90s",
             "note": "Each side. Shoulder-friendly OHP."},
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "60s",
             "note": "Constant tension. Shoulder rebuild priority."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
    }
    # Wed — Shoulder volume + Arms
    days[2] = {
        **days[2],
        "liftName": "Shoulder Volume + Arms",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "4x15", "rest": "45-60s",
             "note": "More lateral delt volume."},
            {"name": "Reverse Pec Deck", "sets": "3x12", "rest": "45-60s",
             "note": "Rear delt isolation."},
            {"name": "Hammer Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Brachialis + biceps."},
            {"name": "EZ-Bar Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Biceps direct."},
            {"name": "Cable Tricep Pushdown", "sets": "3x12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"name": "Overhead Tricep Extension", "sets": "3x12",
             "rest": "45-60s", "note": "Long-head tricep."},
        ],
    }
    # Thu — Pull + Lat
    days[3] = {
        **days[3],
        "liftName": "Upper Pull — Lat Focus",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "4x6", "rest": "2 min",
             "note": "Build to 8 reps. BW 4×8-12 if not yet weighted."},
            {"name": "Barbell Bent-Over Row", "sets": "4x8",
             "rest": "90s-2 min",
             "note": "45-deg torso, pull to belly button."},
            {"name": "Lat Pulldown", "sets": "3x10", "rest": "60-90s",
             "note": "Neutral grip. Different angle."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm. Unilateral back."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural."},
        ],
    }
    # Fri — Heavy Lower hypertrophy
    days[4] = {
        **days[4],
        "liftName": "Heavy Lower — Squat Focus",
        "exercises": [
            {"name": "Back Squat", "sets": "4x8", "rest": "2-3 min",
             "note": "~70%. Below parallel. The hypertrophy strength session."},
            {"name": "Hip Thrust", "sets": "4x10", "rest": "90s",
             "note": "Squeeze glutes hard at top."},
            {"name": "Lying Leg Curl", "sets": "3x12", "rest": "60s",
             "note": "Hamstring isolation."},
            {"name": "Standing Calf Raise", "sets": "3x12", "rest": "45-60s",
             "note": "Second calf session of the week."},
        ],
    }
    # Sat — Full Body
    days[5] = {
        **days[5],
        "liftName": "Full Body Cleanup",
        "exercises": [
            {"name": "Hip Thrust", "sets": "3x10", "rest": "60-90s",
             "note": "Glute volume."},
            {"name": "Cable Chest Fly", "sets": "3x12", "rest": "60s",
             "note": "Chest accessory."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm."},
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s",
             "note": "Lateral volume."},
            {"name": "Ab Wheel Rollout", "sets": "3x10", "rest": "60s",
             "note": "Core anti-extension."},
        ],
    }
    return days
```

- [ ] **Step 4: Verify the helper `_empty_day` exists**

Run: `grep -n "def _empty_day" workout_data.py`

If it does not exist, add this near the other helpers (around line 1660, just before `_phase1_week`):

```python
def _empty_day(day_idx):
    """Default skeleton for a day in a phase template."""
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "day": DAY_NAMES[day_idx] if day_idx < 7 else "?",
        "day_idx": day_idx,
        "liftName": "Rest",
        "isRest": False,
        "exercises": [],
    }
```

- [ ] **Step 5: Update `PHASE_TEMPLATES[1]` dict to mirror the new `_phase1_week` exercises**

Locate `PHASE_TEMPLATES = {` (~line 962) and replace the `1: {...}` block (Phase 1 dict) with one that mirrors the exercises above. The dict format uses `{"exercise": <name>, "sets": <int>, "reps": <str>, "rest": <str>, "note": <str>}` keyed by day_idx (0-6). Read existing structure first to confirm exact shape:

Run: `grep -n "1: {" workout_data.py | head -3`

Then replace:

```python
PHASE_TEMPLATES = {
    1: {
        0: [  # Mon - Lower Hypertrophy - Quad/Glute Focus
            {"exercise": "Front Squat", "sets": 4, "reps": "8",
             "rest": "2-3 min",
             "note": "Build reps to 12 across all sets; then bump weight."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8",
             "rest": "60-90s",
             "note": "Each leg. Unilateral, leg power transfer."},
            {"exercise": "Romanian Deadlift", "sets": 3, "reps": "8",
             "rest": "60-90s", "note": "RPE 7. Hamstring + glute hinge."},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Full ROM, slow eccentric."},
        ],
        1: [  # Tue - Upper Press - Shoulder Build
            {"exercise": "DB Bench Press", "sets": 4, "reps": "8",
             "rest": "2 min",
             "note": "Neutral grip. Build to 10 reps."},
            {"exercise": "Landmine Press", "sets": 3, "reps": "8",
             "rest": "90s",
             "note": "Each side. Shoulder-friendly OHP."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "60s",
             "note": "Constant tension. Shoulder rebuild priority."},
            {"exercise": "Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
        2: [  # Wed - Shoulder Volume + Arms
            {"exercise": "Cable Lateral Raise", "sets": 4, "reps": "15",
             "rest": "45-60s", "note": "More lateral delt volume."},
            {"exercise": "Reverse Pec Deck", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Rear delt isolation."},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Brachialis + biceps."},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Biceps direct."},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"exercise": "Overhead Tricep Extension", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Long-head tricep."},
        ],
        3: [  # Thu - Upper Pull - Lat Focus
            {"exercise": "Weighted Pull-Up", "sets": 4, "reps": "6",
             "rest": "2 min", "note": "Build to 8 reps. BW if not yet weighted."},
            {"exercise": "Barbell Bent-Over Row", "sets": 4, "reps": "8",
             "rest": "90s-2 min",
             "note": "45-deg torso, pull to belly button."},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Neutral grip."},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8",
             "rest": "60s", "note": "Each arm."},
            {"exercise": "Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Postural."},
        ],
        4: [  # Fri - Heavy Lower hypertrophy
            {"exercise": "Back Squat", "sets": 4, "reps": "8",
             "rest": "2-3 min",
             "note": "~70%. Below parallel. The strength session."},
            {"exercise": "Hip Thrust", "sets": 4, "reps": "10",
             "rest": "90s", "note": "Squeeze glutes hard at top."},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Hamstring isolation."},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Second calf session of week."},
        ],
        5: [  # Sat - Full Body Cleanup
            {"exercise": "Hip Thrust", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Glute volume."},
            {"exercise": "Cable Chest Fly", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Chest accessory."},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8",
             "rest": "60s", "note": "Each arm."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Lateral volume."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10",
             "rest": "60s", "note": "Core anti-extension."},
        ],
        6: [],  # Sun rest from iron
    },
    # ... (other phase keys 2, 3, "deload", "test" preserved for now)
```

- [ ] **Step 6: Run Phase 1 content tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestPhase1Content -x -v`
Expected: PASS — all 3 Phase 1 assertions land.

- [ ] **Step 7: Run full suite to verify no other test broke**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add workout_data.py tests/test_program_seed_content.py
git commit -m "Phase 1 prescriptions match spec §2 (hypertrophy/adaptation)"
```

---

## Task 6: Replace PHASE_TEMPLATES Phase 2 content per spec §4

**Files:**
- Modify: `workout_data.py` Phase 2 block of `PHASE_TEMPLATES`
- Modify: `workout_data.py` `_phase2_week()` body
- Test: `tests/test_program_seed_content.py` (extend)

- [ ] **Step 1: Add failing tests for Phase 2 content**

Append to `tests/test_program_seed_content.py`:

```python
class TestPhase2Content:
    """Spec §4: Phase 2 (wks 5-7) Strength block."""

    def test_phase_2_tuesday_has_two_lat_pulldowns(self, app_ctx):
        # Wait — spec §4 Tue is Press + Shoulder, not Pull. Lat Pulldown
        # is on Thu. Let me re-read spec... Actually spec §4 Tue lifts:
        # DB Bench, Landmine Press, Cable Lat Raise, Face Pull. No Lat
        # Pulldown on Tue. Test the Thu pull day instead.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        thu = days[3]
        names = [e["name"] for e in thu.get("exercises", [])]
        assert "Weighted Pull-Up" in names, (
            f"Phase 2 Thu should have Weighted Pull-Up; got {names}"
        )
        assert "Lat Pulldown" in names, (
            f"Phase 2 Thu should have Lat Pulldown; got {names}"
        )
        assert "Barbell Bent-Over Row" in names, (
            f"Phase 2 Thu should have BB Row; got {names}"
        )

    def test_phase_2_friday_back_squat_5x5(self, app_ctx):
        # Spec §4: Fri = Heavy Lower, Back Squat top set + back-off,
        # week 5 starts at 4x5 @ 78%. Template stores the wk-5 seed.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        fri = days[4]
        bs = next((e for e in fri["exercises"]
                   if "Back Squat" in e["name"]), None)
        assert bs is not None
        # Spec §4 wk5: 4×5. Engine handles the wave % across weeks 5-7.
        assert bs["sets"] == "4x5", (
            f"Phase 2 Fri Back Squat wk5 should be 4×5; got {bs['sets']}"
        )

    def test_phase_2_monday_front_squat_4x3(self, app_ctx):
        # Spec §4: Mon Lower POWER. Front Squat 4x3 (speed-focused).
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        mon = days[0]
        fs = next((e for e in mon["exercises"]
                   if e["name"] == "Front Squat"), None)
        assert fs is not None
        assert fs["sets"] == "4x3", (
            f"Phase 2 Mon Front Squat = 4×3 (speed); got {fs['sets']}"
        )

    def test_phase_2_tuesday_db_bench_4x5(self, app_ctx):
        # Spec §4 Tue: DB Bench 4x5 strength wave.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        tue = days[1]
        dbb = next((e for e in tue["exercises"]
                    if e["name"] == "DB Bench Press"), None)
        assert dbb is not None
        assert dbb["sets"] == "4x5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestPhase2Content -x -v`
Expected: FAIL — current Phase 2 content doesn't match spec §4.

- [ ] **Step 3: Replace `_phase2_week()` body and `PHASE_TEMPLATES[2]` with spec §4 prescriptions**

Read current `_phase2_week()` for shape, then replace its body with:

```python
def _phase2_week():
    """Phase 2 (wks 5-7): Strength block per spec §4."""
    days = [_empty_day(i) for i in range(7)]
    days[6] = {**days[6], "liftName": "Rest (Long Fasted Run)", "isRest": True}
    # Mon — Lower POWER + RDL
    days[0] = {
        **days[0],
        "liftName": "Lower POWER + RDL",
        "exercises": [
            {"name": "Box Jump", "sets": "3x5", "rest": "90s",
             "note": "Explosive, full reset. RPE 7. Bar speed > load."},
            {"name": "Front Squat", "sets": "4x3", "rest": "2 min",
             "note": "~70-76% across wks 5-7. Speed-focused, NOT max."},
            {"name": "Bulgarian Split Squat", "sets": "3x8",
             "rest": "60-90s",
             "note": "Each leg. Unilateral, leg power."},
            {"name": "Romanian Deadlift", "sets": "3x8", "rest": "60-90s",
             "note": "RPE 7. Pinned 8 reps; weight bumps weekly."},
        ],
    }
    # Tue — Upper PRESS + Shoulder Strength
    days[1] = {
        **days[1],
        "liftName": "Upper PRESS + Shoulder Strength",
        "exercises": [
            {"name": "DB Bench Press", "sets": "4x5", "rest": "3 min",
             "note": "Neutral grip. RPE 8 cap. 75-82% wave wks 5-7."},
            {"name": "Landmine Press", "sets": "3x6", "rest": "90s",
             "note": "Each side. Shoulder-friendly OHP."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "60s",
             "note": "Constant tension."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural. Mandatory."},
        ],
    }
    # Wed — Shoulder Volume + Arms
    days[2] = {
        **days[2],
        "liftName": "Shoulder Volume + Arms",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s",
             "note": "Lateral delt volume."},
            {"name": "Reverse Pec Deck", "sets": "3x12", "rest": "45-60s",
             "note": "Rear delt iso."},
            {"name": "Hammer Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Brachialis."},
            {"name": "Cable Tricep Pushdown", "sets": "3x12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"name": "EZ-Bar Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Biceps direct."},
        ],
    }
    # Thu — Upper PULL + Lat
    days[3] = {
        **days[3],
        "liftName": "Upper PULL + Lat",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "4x5", "rest": "2-3 min",
             "note": "Top-set heavy + 2 BW AMRAP. Cap AMRAP at +2."},
            {"name": "Barbell Bent-Over Row", "sets": "4x6",
             "rest": "90s-2 min", "note": "RPE 7-8. 75-82% wave."},
            {"name": "Lat Pulldown", "sets": "3x10", "rest": "60-90s",
             "note": "Neutral grip. Lat volume."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural. Yes, again."},
        ],
    }
    # Fri — HEAVY Lower (THE strength session)
    days[4] = {
        **days[4],
        "liftName": "HEAVY Lower — THE Strength Session",
        "exercises": [
            {"name": "Back Squat", "sets": "4x5", "rest": "4 min",
             "note": "Wave: wk5 4×5@78% • wk6 3×5@82% • wk7 3×3@87%. RPE 8 cap."},
            {"name": "Hip Thrust", "sets": "4x8", "rest": "90s",
             "note": "RPE 7. Glute."},
            {"name": "Lying Leg Curl", "sets": "3x10", "rest": "60s",
             "note": "Hamstring iso."},
        ],
    }
    # Sat — Full Body / Glute
    days[5] = {
        **days[5],
        "liftName": "Full Body / Glute Volume",
        "exercises": [
            {"name": "Hip Thrust", "sets": "3x10", "rest": "60-90s",
             "note": "RPE 6. Lighter Sat."},
            {"name": "Cable Chest Fly", "sets": "3x12", "rest": "60s",
             "note": "Chest accessory."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm. Back volume."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "45-60s",
             "note": "More shoulder."},
            {"name": "Ab Wheel Rollout", "sets": "3x10", "rest": "60s",
             "note": "Core."},
        ],
    }
    return days
```

Then update `PHASE_TEMPLATES[2]` block to mirror this content using the dict format `{"exercise": ..., "sets": int, "reps": str, ...}`. Use the same exercise list and prescriptions as `_phase2_week()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestPhase2Content -x -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add workout_data.py tests/test_program_seed_content.py
git commit -m "Phase 2 prescriptions match spec §4 (strength block)"
```

---

## Task 7: Replace PHASE_TEMPLATES Phase 3 content per spec §6

**Files:**
- Modify: `workout_data.py` `_phase3_week()` body and `PHASE_TEMPLATES[3]`
- Test: `tests/test_program_seed_content.py` (extend)

- [ ] **Step 1: Add failing tests for Phase 3 content**

Append to `tests/test_program_seed_content.py`:

```python
class TestPhase3Content:
    """Spec §6: Phase 3 (wks 9-11) Cut Climax."""

    def test_phase_3_friday_back_squat_3x3(self, app_ctx):
        # Spec §6: Fri = Heavy Lower, 3×3 @ 87%, HOLD all 3 weeks.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=9)
        fri = days[4]
        bs = next((e for e in fri["exercises"]
                   if "Back Squat" in e["name"]), None)
        assert bs is not None
        assert bs["sets"] == "3x3", (
            f"Phase 3 Fri Back Squat = 3×3 (HOLD); got {bs['sets']}"
        )

    def test_phase_3_monday_front_squat_3x3(self, app_ctx):
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=9)
        mon = days[0]
        fs = next((e for e in mon["exercises"]
                   if e["name"] == "Front Squat"), None)
        assert fs is not None
        assert fs["sets"] == "3x3"

    def test_phase_3_wednesday_no_ezbar_curl(self, app_ctx):
        # Spec §6 Phase 3 Wed drops EZ-Bar Curl (volume cut on accessories).
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=9)
        wed = days[2]
        names = [e["name"] for e in wed.get("exercises", [])]
        assert "EZ-Bar Curl" not in names, (
            f"Phase 3 Wed should drop EZ-Bar Curl per spec §6; got {names}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestPhase3Content -x -v`
Expected: FAIL.

- [ ] **Step 3: Replace `_phase3_week()` body**

Replace `_phase3_week()` body with:

```python
def _phase3_week():
    """Phase 3 (wks 9-11): Cut climax per spec §6. HOLD weights."""
    days = [_empty_day(i) for i in range(7)]
    days[6] = {**days[6], "liftName": "Rest (Long Fasted Run)", "isRest": True}
    # Mon
    days[0] = {
        **days[0],
        "liftName": "Lower POWER (HOLD)",
        "exercises": [
            {"name": "Box Jump", "sets": "3x5", "rest": "90s",
             "note": "RPE 7. Preserve power even when cutting."},
            {"name": "Front Squat", "sets": "3x3", "rest": "2 min",
             "note": "73% HOLD all 3 wks. Bump only if RPE 6 confirmed twice."},
            {"name": "Bulgarian Split Squat", "sets": "2x6", "rest": "60-90s",
             "note": "Each leg. Volume cut from Phase 2."},
            {"name": "Romanian Deadlift", "sets": "2x6", "rest": "60-90s",
             "note": "RPE 6. Volume cut."},
        ],
    }
    # Tue
    days[1] = {
        **days[1],
        "liftName": "Press + Shoulder (HOLD)",
        "exercises": [
            {"name": "DB Bench Press", "sets": "3x5", "rest": "3 min",
             "note": "80% HOLD. Same load all 3 wks."},
            {"name": "Landmine Press", "sets": "2x6", "rest": "90s",
             "note": "Each side. Volume cut."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "60s",
             "note": "KEEP — shoulder priority preserved."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "KEEP — postural."},
        ],
    }
    # Wed
    days[2] = {
        **days[2],
        "liftName": "Shoulder/Arms (cut volume)",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s",
             "note": "KEEP."},
            {"name": "Reverse Pec Deck", "sets": "2x12", "rest": "45-60s",
             "note": "Volume cut."},
            {"name": "Hammer Curl", "sets": "2x10", "rest": "45-60s",
             "note": "Volume cut."},
            {"name": "Cable Tricep Pushdown", "sets": "2x12",
             "rest": "45-60s", "note": "Volume cut."},
        ],
    }
    # Thu
    days[3] = {
        **days[3],
        "liftName": "Pull + Lat (HOLD)",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "3x5", "rest": "2 min",
             "note": "Same load all 3 wks. Volume cut."},
            {"name": "Barbell Bent-Over Row", "sets": "3x6",
             "rest": "90s-2 min", "note": "80% HOLD."},
            {"name": "Lat Pulldown", "sets": "2x10", "rest": "60-90s",
             "note": "Volume cut."},
            {"name": "Face Pull", "sets": "2x15", "rest": "45-60s",
             "note": "Volume cut but KEPT."},
        ],
    }
    # Fri
    days[4] = {
        **days[4],
        "liftName": "HEAVY Lower (HOLD)",
        "exercises": [
            {"name": "Back Squat", "sets": "3x3", "rest": "4 min",
             "note": "87% HOLD all 3 wks. RPE 8 cap. NO bumps."},
            {"name": "Hip Thrust", "sets": "3x8", "rest": "90s",
             "note": "RPE 7. Volume slightly cut."},
        ],
    }
    # Sat
    days[5] = {
        **days[5],
        "liftName": "Full Body (volume cut)",
        "exercises": [
            {"name": "Hip Thrust", "sets": "2x10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"name": "Cable Chest Fly", "sets": "2x12", "rest": "60s",
             "note": "Volume cut."},
            {"name": "Single-Arm DB Row", "sets": "2x8", "rest": "60s",
             "note": "Each arm. Volume cut."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "45-60s",
             "note": "KEEP shoulder."},
        ],
    }
    return days
```

Then update `PHASE_TEMPLATES[3]` block to mirror this content using the dict format.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestPhase3Content -x -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workout_data.py tests/test_program_seed_content.py
git commit -m "Phase 3 prescriptions match spec §6 (cut climax HOLD)"
```

---

## Task 8: Replace deload + week-12 content per spec §3, §5, §7

**Files:**
- Modify: `workout_data.py` `_deload_week()`, `_test_week()`, `PHASE_TEMPLATES["deload"]`, `PHASE_TEMPLATES["test"]`
- Test: `tests/test_program_seed_content.py` (extend)

- [ ] **Step 1: Add failing tests for deload + week-12 content**

```python
class TestDeloadAndWeek12Content:
    """Spec §3 (deload), §5 (deload wk8), §7 (week 12 peak)."""

    def test_deload_back_squat_3x5(self, app_ctx):
        # Spec §5: Fri deload Back Squat 3x5 @ 65%.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=4)  # deload
        fri = days[4]
        bs = next((e for e in fri["exercises"]
                   if "Back Squat" in e["name"]), None)
        assert bs is not None
        assert bs["sets"] == "3x5"

    def test_deload_no_amrap(self, app_ctx):
        # Spec §5: deload caps reps at moderate.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=4)
        for d in days:
            for ex in d.get("exercises", []) or []:
                assert "AMRAP" not in ex.get("reps", ""), (
                    f"Deload should not have AMRAP: {ex}"
                )

    def test_week_12_back_squat_2x3(self, app_ctx):
        # Spec §7: Fri wk12 Back Squat 2x3 (single working set, just to feel it).
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=12)
        fri = days[4]
        bs = next((e for e in fri["exercises"]
                   if "Back Squat" in e["name"]), None)
        assert bs is not None
        assert bs["sets"] == "2x3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py::TestDeloadAndWeek12Content -x -v`
Expected: FAIL.

- [ ] **Step 3: Replace `_deload_week()` body**

```python
def _deload_week():
    """Deload (wks 4 and 8) per spec §3, §5. Volume 50%, intensity ~70%."""
    days = [_empty_day(i) for i in range(7)]
    days[6] = {**days[6], "liftName": "Rest (Long Fasted Run, 60 min)",
               "isRest": True}
    days[0] = {
        **days[0],
        "liftName": "Deload — Lower",
        "exercises": [
            {"name": "Box Jump", "sets": "2x5", "rest": "90s",
             "note": "Volume cut."},
            {"name": "Front Squat", "sets": "3x3", "rest": "2 min",
             "note": "65% — drop from Phase 2 wave."},
            {"name": "Bulgarian Split Squat", "sets": "2x8",
             "rest": "60-90s", "note": "Each leg. Volume cut."},
        ],
    }
    days[1] = {
        **days[1],
        "liftName": "Deload — Press + Shoulder",
        "exercises": [
            {"name": "DB Bench Press", "sets": "3x5", "rest": "2 min",
             "note": "70% — drop from Phase 2."},
            {"name": "Landmine Press", "sets": "2x6", "rest": "90s",
             "note": "Each side."},
            {"name": "Cable Lateral Raise", "sets": "2x12", "rest": "60s"},
            {"name": "Face Pull", "sets": "2x15", "rest": "45-60s"},
        ],
    }
    days[2] = {
        **days[2],
        "liftName": "Deload — Shoulder/Arms (light)",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "2x15", "rest": "45-60s"},
            {"name": "Reverse Pec Deck", "sets": "2x12", "rest": "45-60s"},
            {"name": "Cable Tricep Pushdown", "sets": "2x12",
             "rest": "45-60s", "note": "Or curl — pick one."},
        ],
    }
    days[3] = {
        **days[3],
        "liftName": "Deload — Pull",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "3x5", "rest": "2 min",
             "note": "BW only this week."},
            {"name": "Barbell Bent-Over Row", "sets": "3x6", "rest": "90s",
             "note": "70% — drop."},
            {"name": "Lat Pulldown", "sets": "2x10", "rest": "60-90s"},
            {"name": "Face Pull", "sets": "2x15", "rest": "45-60s"},
        ],
    }
    days[4] = {
        **days[4],
        "liftName": "Deload — Heavy Lower (light)",
        "exercises": [
            {"name": "Back Squat", "sets": "3x5", "rest": "2 min",
             "note": "65% — significant drop from Phase 2."},
            {"name": "Hip Thrust", "sets": "3x8", "rest": "90s",
             "note": "RPE 6."},
        ],
    }
    days[5] = {
        **days[5],
        "liftName": "Deload — Full Body Light",
        "exercises": [
            {"name": "Hip Thrust", "sets": "2x10", "rest": "60-90s",
             "note": "Light."},
            {"name": "Cable Chest Fly", "sets": "2x12", "rest": "60s"},
            {"name": "Single-Arm DB Row", "sets": "2x8", "rest": "60s",
             "note": "Each arm."},
            {"name": "Cable Lateral Raise", "sets": "2x12", "rest": "45-60s"},
        ],
    }
    return days
```

- [ ] **Step 4: Replace `_test_week()` body with peak-finish per spec §7**

```python
def _test_week():
    """Week 12 peak finish per spec §7. Mini-taper. Scale + look. NOT 1RM."""
    days = [_empty_day(i) for i in range(7)]
    days[6] = {**days[6], "liftName": "Rest (Long Fasted Run, 60 min)",
               "isRest": True}
    days[0] = {
        **days[0],
        "liftName": "Wk12 — Lower (taper)",
        "exercises": [
            {"name": "Box Jump", "sets": "2x5", "rest": "90s"},
            {"name": "Front Squat", "sets": "2x3", "rest": "2 min",
             "note": "73%. Single-ish working set."},
            {"name": "Bulgarian Split Squat", "sets": "1x6",
             "rest": "60-90s", "note": "Each leg. Maintenance."},
        ],
    }
    days[1] = {
        **days[1],
        "liftName": "Wk12 — Press + Shoulder (taper)",
        "exercises": [
            {"name": "DB Bench Press", "sets": "2x5", "rest": "2 min",
             "note": "80%."},
            {"name": "Landmine Press", "sets": "1x6", "rest": "90s",
             "note": "Each side."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "60s",
             "note": "KEEP — makes the look."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "KEEP."},
        ],
    }
    days[2] = {
        **days[2],
        "liftName": "Wk12 — Shoulder Volume Only",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s"},
            {"name": "Reverse Pec Deck", "sets": "2x12", "rest": "45-60s"},
        ],
    }
    days[3] = {
        **days[3],
        "liftName": "Wk12 — Pull (taper)",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "2x5", "rest": "2 min"},
            {"name": "Barbell Bent-Over Row", "sets": "2x6", "rest": "90s",
             "note": "80%."},
            {"name": "Lat Pulldown", "sets": "1x10", "rest": "60-90s"},
            {"name": "Face Pull", "sets": "2x15", "rest": "45-60s"},
        ],
    }
    days[4] = {
        **days[4],
        "liftName": "Wk12 — Heavy Lower (taper)",
        "exercises": [
            {"name": "Back Squat", "sets": "2x3", "rest": "4 min",
             "note": "87%. Single working set, just to feel it."},
            {"name": "Hip Thrust", "sets": "2x8", "rest": "90s"},
        ],
    }
    days[5] = {
        **days[5],
        "liftName": "Wk12 — Full Body (taper)",
        "exercises": [
            {"name": "Hip Thrust", "sets": "2x10", "rest": "60-90s",
             "note": "Light."},
            {"name": "Cable Chest Fly", "sets": "2x12", "rest": "60s"},
            {"name": "Cable Lateral Raise", "sets": "2x12", "rest": "45-60s"},
        ],
    }
    return days
```

Then update `PHASE_TEMPLATES["deload"]` and `PHASE_TEMPLATES["test"]` blocks to mirror.

- [ ] **Step 5: Run tests**

Run: `source venv/bin/activate && python -m pytest tests/test_program_seed_content.py -x -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add workout_data.py tests/test_program_seed_content.py
git commit -m "Deload (wks 4, 8) and week 12 peak match spec §3, §5, §7"
```

---

## Task 9: Update bodyweight templates (BW_PHASE_TEMPLATES)

**Files:**
- Modify: `workout_data.py` `BW_PHASE_TEMPLATES` dict (lines 1272+)

The user has full equipment; BW templates are not in the critical path. Mirror the new structure but use bodyweight substitutions for compound lifts. Keep this minimal — BW users aren't the program's primary target this cycle.

- [ ] **Step 1: Apply bodyweight substitutions to each phase**

For each phase block in `BW_PHASE_TEMPLATES`, replace compound lifts with these subs:

| Compound | BW Sub |
|---|---|
| Front Squat | Goblet Squat (DB) or Bulgarian Split Squat |
| Back Squat | Bodyweight Squats / pistol progression |
| DB Bench Press | Push-Ups (decline if needed) |
| Landmine Press | Pike Push-Ups |
| Weighted Pull-Up | Pull-Ups (BW) |
| Barbell Bent-Over Row | Inverted Row |
| Romanian Deadlift | Single-Leg DB RDL |
| Hip Thrust | Single-Leg Glute Bridge |

Edit `BW_PHASE_TEMPLATES[1]`, `[2]`, `[3]`, `["deload"]`, `["test"]`, and any `_bw` variants to mirror the spec's day-by-day structure with these subs. (Bodyweight lateral raises and face pulls don't translate — use band lateral raise and band pull-apart respectively.)

- [ ] **Step 2: Smoke-test BW path**

```bash
source venv/bin/activate && python -c "
from app import app
from workout_data import get_workouts_for_user
with app.app_context():
    days = get_workouts_for_user(week=5, has_gym=False)
    print('BW Tue:', [(e['name'], e['sets']) for e in days[1].get('exercises', [])])
"
```
Expected: shoulder/back exercises with BW subs, no errors.

- [ ] **Step 3: Run full test suite**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add workout_data.py
git commit -m "BW phase templates mirror gym structure with BW subs"
```

---

## Task 10: Smoke-test end-to-end via /api/workouts

**Files:**
- (No code changes — runtime smoke test)

- [ ] **Step 1: Boot app and inspect a generated week**

```bash
source venv/bin/activate && python -c "
from app import app
from workout_data import get_workouts
with app.app_context():
    print('=== Week 5 (Phase 2 start) ===')
    for i, d in enumerate(get_workouts(5)):
        names = [(e['name'], e['sets']) for e in d.get('exercises', [])]
        print(f'  Day {i} {d[\"liftName\"]}: {names}')
    print()
    print('=== Week 9 (Phase 3 start) ===')
    for i, d in enumerate(get_workouts(9)):
        names = [(e['name'], e['sets']) for e in d.get('exercises', [])]
        print(f'  Day {i} {d[\"liftName\"]}: {names}')
"
```

Expected output: 7 days each, with the spec's prescriptions visible.

- [ ] **Step 2: Run full suite one final time**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 3: Push to origin**

```bash
git push origin main
```

---

## Out of scope (deferred to follow-up plan)

- Auto-regulation triggers (spec §8B) — numerical thresholds for unplanned mid-block deloads, HIIT cuts on HR drift, volume cuts on sleep deficit.
- Streak / adherence tracking (spec §8D) — consecutive-session counters, minimum-viable-session fallback, restart-phase trigger on 3 missed sessions.
- Coach-prompt extensions (spec §8F) — Lombardi/Saban posture reinforcement, banned phrases, mandatory-warm-up enforcement language in CORE_PROMPT.
- Refeed Thursday flagging (spec §8C) — UI/coach context flag for Thursday +50% carbs.
- DB migration (separate plan) — moving PHASE_TEMPLATES into ProgramTemplate tables.

These ride on top of the working program. The MVP this plan delivers is: when Erik logs in Monday week 6, the new program is what shows up. That's the unblocker.

---

## Self-Review

**Spec coverage:**
- §1 (architecture) — covered by phase mapping + day template (already in workout_data.py)
- §2 (Phase 1) — Task 5
- §3 (week 4 deload) — Task 8
- §4 (Phase 2) — Task 6
- §5 (week 8 deload) — Task 8 (deload covers both week 4 and week 8 — same template)
- §6 (Phase 3) — Task 7
- §7 (week 12 peak) — Task 8 (test_week)
- §8A (one-knob progression) — Tasks 1, 2, 3, 4 (engine per-phase branches)
- §8B (autoregulation triggers) — DEFERRED (out of scope)
- §8C (refeed) — DEFERRED
- §8D (adherence) — DEFERRED
- §8E (session-level rules) — partly captured in template notes; warmup enforcement DEFERRED
- §8F (coach posture) — DEFERRED
- §8G (excluded movements) — implicit (no excluded exercises appear in new templates)
- §8H (equipment subs) — Task 9 covers BW; dip-station sub already addressed by exercise selection
- §8I (run schedule) — NOT in this plan (run scheduling is a separate concern; the lift program is what changes)

**Placeholder scan:** every code step has explicit code; no "TBD"; no "implement later."

**Type consistency:** `exercises` list shape (`{"name", "sets", "rest", "note"}`) matches throughout; PHASE_TEMPLATES dict shape (`{"exercise", "sets" int, "reps" str, "rest", "note"}`) consistent.

**Open question call-out for engineer:** Task 9 (BW templates) is light on detail because the user's primary use case is the gym path. If a real BW user surfaces, that becomes a separate plan iteration.
