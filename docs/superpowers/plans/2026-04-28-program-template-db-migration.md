# Program Template DB Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the program template — currently a hardcoded `PHASE_TEMPLATES` Python dict in `workout_data.py` — into proper database tables (`ProgramTemplateDay`, `ProgramTemplate`, `ExerciseAlias`) so the engine, coach, UI, and admin all read a single editable source of truth instead of a frozen dict.

**Architecture:** Three new SQLAlchemy models. A new `program_template_io.py` module owns all reads. Seeding runs idempotently at app startup from `workout_data.py` — the dict becomes a seed source, not a runtime authority. `workout_data.get_workouts()` is preserved as a thin shim that delegates to the new reader so coach/UI callers don't need to change. Admin endpoints (PATCH/POST/DELETE) let templates be edited in DB without code deploys; rows touched by admin set `is_user_modified=True` and the seed never overwrites them.

**Tech Stack:** Flask, SQLAlchemy, SQLite (dev) / Postgres (prod), pytest.

---

## File Structure

**New files:**
- `program_template_io.py` — read API, alias resolution, phase mapping
- `program_seed.py` — idempotent seeder, called from `app.py` startup
- `tests/test_program_template_seed.py` — seed idempotency + user-modified preservation
- `tests/test_program_template_io.py` — read API contracts (duplicate Lat Pulldown disambiguation, phase mapping, alias resolution)
- `tests/test_program_template_admin.py` — PATCH/POST/DELETE behaviors and validation

**Modified files:**
- `models.py` — add `ProgramTemplateDay`, `ProgramTemplate`, `ExerciseAlias` classes
- `app.py` — call seed at startup; add admin endpoints; switch `api_workouts`, `api_prescription_seed`, `api_generate_weekly_program`, `api_warmups`, the new-user prescription seed, and the `_get_workout_exercises` helper to read via `program_template_io`
- `workout_data.py` — `get_workouts` and `get_workouts_for_user` become thin shims that delegate to `program_template_io.get_program_week`; comment block declares the dicts SEED-ONLY
- `training_engine.py` — switch `_get_configured_sets_reps` to read via `program_template_io`; `resolve_name` import switches to the new module
- `coach_assembler.py` — switch `_resolve_workout_for_day`, `_build_week_schedule`, `_build_completed_days`, `_build_exercise_history`, `_build_exercise_analysis`, `_build_base` to use `program_template_io`
- `equipment_swaps.py` — switch `resolve_name` import to `program_template_io`
- `tests/conftest.py` — add `seeded_program` session-scoped fixture so tests have the seeded template available

---

## Phase Mapping (locked)

```
weeks 1-3 → "phase1"
week 4    → "deload"
weeks 5-7 → "phase2"
week 8    → "deload"
weeks 9-11→ "phase3"
week 12   → "test"
```

Variant: `"gym"` (default) or `"bw"` (no-gym). Total: 5 phases × 2 variants × 7 days = 70 day rows; ~400 exercise rows.

---

## Task 1: Schema — three new model classes

**Files:**
- Modify: `models.py` (add three classes after `Exercise` at line 553)

- [ ] **Step 1: Add `ProgramTemplateDay`, `ProgramTemplate`, `ExerciseAlias` classes**

```python
class ProgramTemplateDay(db.Model):
    """Per-(phase, variant, day_idx) day metadata for the canonical program.
    Phase is one of 'phase1'/'phase2'/'phase3'/'deload'/'test'. Variant is
    'gym' or 'bw'. is_user_modified=True means the seed must skip this row
    on subsequent boots so admin/manual edits survive restarts."""
    __tablename__ = "program_template_day"
    id = db.Column(db.Integer, primary_key=True)
    phase = db.Column(db.String(16), nullable=False)
    variant = db.Column(db.String(8), nullable=False, default="gym")
    day_idx = db.Column(db.Integer, nullable=False)
    lift_name = db.Column(db.String(120), nullable=False)
    is_rest = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text)
    is_user_modified = db.Column(db.Boolean, nullable=False, default=False)
    schema_version = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("phase", "variant", "day_idx", name="uq_ptd_phase_variant_day"),
        db.Index("ix_ptd_phase_variant", "phase", "variant"),
    )


class ProgramTemplate(db.Model):
    """A single exercise prescription within a ProgramTemplateDay. order_idx
    distinguishes exercises that appear twice in the same day (Phase 2 Tuesday
    has Lat Pulldown at order_idx=0 heavy 5x5 AND order_idx=2 pump 3x12).
    reps is freeform string ("5", "10-12", "1RM", "45s")."""
    __tablename__ = "program_template"
    id = db.Column(db.Integer, primary_key=True)
    day_id = db.Column(db.Integer, db.ForeignKey("program_template_day.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    order_idx = db.Column(db.Integer, nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=True, index=True)
    exercise_name = db.Column(db.String(100), nullable=False)
    sets = db.Column(db.Integer, nullable=False)
    reps = db.Column(db.String(50), nullable=False)
    rest = db.Column(db.String(32))
    note = db.Column(db.Text)
    is_user_modified = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("day_id", "order_idx", name="uq_pt_day_order"),
        db.Index("ix_pt_day_order", "day_id", "order_idx"),
    )


class ExerciseAlias(db.Model):
    """Resolves informal names to canonical Exercise.name. Replaces the
    NAME_ALIASES dict in workout_data.py at runtime."""
    __tablename__ = "exercise_alias"
    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(120), nullable=False, unique=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: Verify import works**

Run: `source venv/bin/activate && python -c "from models import ProgramTemplateDay, ProgramTemplate, ExerciseAlias; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add models.py
git commit -m "Add ProgramTemplateDay, ProgramTemplate, ExerciseAlias models"
```

---

## Task 2: Seeder — idempotent migration from PHASE_TEMPLATES

**Files:**
- Create: `program_seed.py`
- Test: `tests/test_program_template_seed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_program_template_seed.py
"""Seed must be idempotent and must not clobber admin/user edits."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


class TestSeed:
    def test_first_seed_creates_full_set(self, app_ctx):
        app, db = app_ctx
        from program_seed import seed_program_template
        from models import ProgramTemplateDay, ProgramTemplate
        with app.test_request_context():
            seed_program_template()
            day_count = ProgramTemplateDay.query.count()
            row_count = ProgramTemplate.query.count()
        # 5 phases (phase1, phase2, phase3, deload, test) × 2 variants × 7 days = 70
        assert day_count == 70, f"expected 70 days, got {day_count}"
        assert row_count > 200, f"expected ~400 rows, got {row_count}"

    def test_second_seed_is_noop(self, app_ctx):
        app, db = app_ctx
        from program_seed import seed_program_template
        from models import ProgramTemplateDay, ProgramTemplate
        with app.test_request_context():
            seed_program_template()
            day_count_before = ProgramTemplateDay.query.count()
            row_count_before = ProgramTemplate.query.count()
            seed_program_template()
            assert ProgramTemplateDay.query.count() == day_count_before
            assert ProgramTemplate.query.count() == row_count_before

    def test_user_modified_row_survives_reseed(self, app_ctx):
        app, db = app_ctx
        from program_seed import seed_program_template
        from models import ProgramTemplate
        with app.test_request_context():
            seed_program_template()
            row = ProgramTemplate.query.first()
            row.reps = "999"
            row.is_user_modified = True
            db.session.commit()
            seed_program_template()
            db.session.refresh(row)
            assert row.reps == "999", "user-modified row was clobbered"

    def test_phase_2_tuesday_has_two_lat_pulldowns(self, app_ctx):
        app, db = app_ctx
        from program_seed import seed_program_template
        from models import ProgramTemplateDay, ProgramTemplate
        with app.test_request_context():
            seed_program_template()
            day = ProgramTemplateDay.query.filter_by(
                phase="phase2", variant="gym", day_idx=1).first()
            rows = ProgramTemplate.query.filter_by(day_id=day.id).order_by(
                ProgramTemplate.order_idx).all()
            lat_rows = [r for r in rows if r.exercise_name == "Lat Pulldown"]
        assert len(lat_rows) == 2, f"expected 2 Lat Pulldown rows, got {len(lat_rows)}"
        assert lat_rows[0].sets == 5 and lat_rows[0].reps == "5"
        assert lat_rows[1].sets == 3 and lat_rows[1].reps == "12"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_program_template_seed.py -x -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'program_seed'`

- [ ] **Step 3: Write `program_seed.py`**

```python
# program_seed.py
"""Idempotent seeder: PHASE_TEMPLATES + BW_PHASE_TEMPLATES dicts → DB rows."""
import logging
from workout_data import (
    PHASE_TEMPLATES, BW_PHASE_TEMPLATES, NAME_ALIASES, EXERCISES,
    _phase1_week, _phase2_week, _phase3_week, _deload_week, _test_week,
)

log = logging.getLogger(__name__)

EXPECTED_DAY_COUNT = 70  # 5 phases × 2 variants × 7 days


def _phase_key_normalize(raw_key, dict_label):
    """PHASE_TEMPLATES uses int keys (1/2/3) plus 'deload'/'test'.
    BW_PHASE_TEMPLATES uses 'phase1_bw'/'deload_bw'/etc. Normalize all to
    the canonical phase enum."""
    s = str(raw_key)
    if s in ("1", "phase1", "phase1_bw"): return "phase1"
    if s in ("2", "phase2", "phase2_bw"): return "phase2"
    if s in ("3", "phase3", "phase3_bw"): return "phase3"
    if "deload" in s: return "deload"
    if "test" in s: return "test"
    log.warning(f"unknown phase key {raw_key!r} in {dict_label}")
    return None


def _lift_names_for_phase(phase, variant):
    """Pull liftName per day_idx by calling the legacy week builders.
    Once the seed runs, runtime never calls these again — they're seed-only."""
    if variant == "gym":
        builder = {
            "phase1": _phase1_week, "phase2": _phase2_week,
            "phase3": _phase3_week, "deload": _deload_week, "test": _test_week,
        }.get(phase)
    else:
        # BW variants reuse the same lift-name structure for now; if/when BW
        # builders diverge, add a separate lookup here.
        builder = {
            "phase1": _phase1_week, "phase2": _phase2_week,
            "phase3": _phase3_week, "deload": _deload_week, "test": _test_week,
        }.get(phase)
    if not builder:
        return {}
    try:
        days = builder()
    except Exception:
        return {}
    return {i: (d.get("liftName", "Rest"), d.get("isRest", False))
            for i, d in enumerate(days)}


def seed_aliases():
    """Seed ExerciseAlias rows from NAME_ALIASES. Idempotent."""
    from models import db, Exercise, ExerciseAlias
    existing = {a.alias for a in ExerciseAlias.query.all()}
    canonical_to_id = {e.name: e.id for e in Exercise.query.all()}
    inserted = 0
    for alias, canonical in NAME_ALIASES.items():
        if alias in existing:
            continue
        ex_id = canonical_to_id.get(canonical)
        if ex_id is None:
            log.warning(f"alias {alias!r} → {canonical!r} but no Exercise row exists")
            continue
        db.session.add(ExerciseAlias(
            alias=alias, exercise_id=ex_id, canonical_name=canonical))
        inserted += 1
    if inserted:
        try:
            db.session.commit()
            log.info(f"seeded {inserted} ExerciseAlias rows")
        except Exception:
            db.session.rollback()


def _seed_one_variant(source_dict, variant):
    """Insert ProgramTemplateDay + ProgramTemplate rows for a (variant) dict."""
    from models import db, Exercise, ProgramTemplateDay, ProgramTemplate
    inserted_days = 0
    inserted_rows = 0
    canonical_to_id = {e.name: e.id for e in Exercise.query.all()}

    for raw_phase, day_map in source_dict.items():
        phase = _phase_key_normalize(raw_phase, f"variant={variant}")
        if not phase:
            continue
        lift_names = _lift_names_for_phase(phase, variant)
        for day_idx in range(7):
            existing = ProgramTemplateDay.query.filter_by(
                phase=phase, variant=variant, day_idx=day_idx).first()
            if existing:
                # Already seeded; never reconcile children — admin edits sacred.
                continue
            lift_name, is_rest = lift_names.get(day_idx, ("Rest", True))
            day = ProgramTemplateDay(
                phase=phase, variant=variant, day_idx=day_idx,
                lift_name=lift_name, is_rest=is_rest)
            db.session.add(day)
            db.session.flush()  # get day.id
            inserted_days += 1
            for order, ex in enumerate(day_map.get(day_idx, []) or []):
                from workout_data import resolve_name
                canonical = resolve_name(ex.get("exercise", "")).strip()
                if not canonical:
                    continue
                db.session.add(ProgramTemplate(
                    day_id=day.id,
                    order_idx=order,
                    exercise_id=canonical_to_id.get(canonical),
                    exercise_name=canonical,
                    sets=int(ex.get("sets") or 0),
                    reps=str(ex.get("reps") or ""),
                    rest=ex.get("rest"),
                    note=ex.get("note") or "",
                ))
                inserted_rows += 1
    return inserted_days, inserted_rows


def seed_program_template():
    """Top-level seeder. Idempotent. Skips per-day rows that already exist
    (regardless of is_user_modified — once seeded, admin owns the row)."""
    from models import db, ProgramTemplateDay
    try:
        existing_days = ProgramTemplateDay.query.count()
    except Exception:
        log.warning("ProgramTemplateDay table not present yet; skipping seed")
        return
    if existing_days >= EXPECTED_DAY_COUNT:
        log.debug(f"program template already seeded ({existing_days} days); noop")
        return

    seed_aliases()

    try:
        d_gym, r_gym = _seed_one_variant(PHASE_TEMPLATES, "gym")
        d_bw, r_bw = _seed_one_variant(BW_PHASE_TEMPLATES, "bw")
        db.session.commit()
        log.info(
            f"seeded program template: {d_gym + d_bw} days, "
            f"{r_gym + r_bw} exercise rows"
        )
    except Exception as e:
        db.session.rollback()
        log.error(f"program template seed failed: {e!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_template_seed.py -x -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add program_seed.py tests/test_program_template_seed.py
git commit -m "Add idempotent program template seeder with user-modified preservation"
```

---

## Task 3: Read API — `program_template_io.py`

**Files:**
- Create: `program_template_io.py`
- Test: `tests/test_program_template_io.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_program_template_io.py
"""Read API contracts. Crucial: duplicate exercises in the same day must be
returned as separate rows in order so the engine sees both."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        from program_seed import seed_program_template
        seed_program_template()
        yield app, db


class TestPhaseFor Week:
    @pytest.mark.parametrize("week,expected", [
        (1, "phase1"), (3, "phase1"), (4, "deload"),
        (5, "phase2"), (7, "phase2"), (8, "deload"),
        (9, "phase3"), (11, "phase3"), (12, "test"),
    ])
    def test_phase_mapping(self, app_ctx, week, expected):
        from program_template_io import phase_for_week
        assert phase_for_week(week) == expected


class TestGetProgramDay:
    def test_returns_exercises_in_order(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import get_program_day
        with app.test_request_context():
            day = get_program_day("phase2", 1, has_gym=True)
        names = [e["exercise"] for e in day]
        # Phase 2 Tuesday lists Lat Pulldown twice — both must come back.
        assert names.count("Lat Pulldown") == 2, names

    def test_pump_and_heavy_lat_pulldown_distinguished(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import get_program_day
        with app.test_request_context():
            day = get_program_day("phase2", 1, has_gym=True)
        lats = [e for e in day if e["exercise"] == "Lat Pulldown"]
        assert len(lats) == 2
        assert lats[0]["sets"] == 5 and lats[0]["reps"] == "5"
        assert lats[1]["sets"] == 3 and lats[1]["reps"] == "12"
        assert lats[0]["order"] < lats[1]["order"]

    def test_unknown_phase_returns_empty(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import get_program_day
        with app.test_request_context():
            assert get_program_day("phaseX", 1, has_gym=True) == []


class TestResolveName:
    def test_alias_resolves(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import resolve_name
        with app.test_request_context():
            assert resolve_name("Bench Press") == "Barbell Bench Press"

    def test_canonical_passes_through(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import resolve_name
        with app.test_request_context():
            assert resolve_name("Barbell Bench Press") == "Barbell Bench Press"

    def test_unknown_passes_through(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import resolve_name
        with app.test_request_context():
            assert resolve_name("Glute Bridge (weighted)") == "Glute Bridge (weighted)"


class TestGetProgramWeek:
    def test_returns_seven_days(self, app_ctx):
        app, _ = app_ctx
        from program_template_io import get_program_week
        with app.test_request_context():
            week = get_program_week(5, has_gym=True)
        assert len(week) == 7
        assert week[1]["liftName"]
        assert any(e["name"] == "Lat Pulldown" for e in week[1]["exercises"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_program_template_io.py -x -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'program_template_io'`

- [ ] **Step 3: Write `program_template_io.py`**

```python
# program_template_io.py
"""Read API for the program template. Single replacement for direct reads
of PHASE_TEMPLATES / BW_PHASE_TEMPLATES / NAME_ALIASES in workout_data.py.

All callers in app.py, training_engine.py, coach_assembler.py, and
equipment_swaps.py go through here. workout_data.get_workouts is preserved
as a thin shim that delegates to get_program_week."""

from typing import Optional


def phase_for_week(week: int) -> str:
    if week == 4 or week == 8:
        return "deload"
    if week == 12:
        return "test"
    if 1 <= week <= 3:
        return "phase1"
    if 5 <= week <= 7:
        return "phase2"
    if 9 <= week <= 11:
        return "phase3"
    return "phase1"  # safe fallback


def get_program_day(phase: str, day_idx: int, has_gym: bool = True) -> list[dict]:
    """Return list of exercise prescriptions for one day. Empty list = rest day.

    Each item: {exercise, sets, reps, rest, note, exercise_id, order}.
    Order matters — duplicate exercise names within a day are distinguished
    by their position (Phase 2 Tuesday: Lat Pulldown at order=0 5x5 heavy
    AND order=2 3x12 pump)."""
    from models import ProgramTemplateDay, ProgramTemplate
    variant = "gym" if has_gym else "bw"
    day = ProgramTemplateDay.query.filter_by(
        phase=phase, variant=variant, day_idx=day_idx).first()
    if not day or day.is_rest:
        return []
    rows = (ProgramTemplate.query.filter_by(day_id=day.id)
            .order_by(ProgramTemplate.order_idx).all())
    return [{
        "exercise": r.exercise_name,
        "exercise_id": r.exercise_id,
        "order": r.order_idx,
        "sets": r.sets,
        "reps": r.reps,
        "rest": r.rest,
        "note": r.note or "",
    } for r in rows]


def get_program_day_meta(phase: str, day_idx: int, has_gym: bool = True) -> dict:
    """Return day-level metadata (lift_name, is_rest)."""
    from models import ProgramTemplateDay
    variant = "gym" if has_gym else "bw"
    day = ProgramTemplateDay.query.filter_by(
        phase=phase, variant=variant, day_idx=day_idx).first()
    if not day:
        return {"lift_name": "Rest", "is_rest": True, "notes": ""}
    return {
        "lift_name": day.lift_name,
        "is_rest": day.is_rest,
        "notes": day.notes or "",
    }


def get_program_week(week: int, has_gym: bool = True) -> list[dict]:
    """Return 7-day list shaped for the existing UI/coach consumers.

    Each day: {day_idx, day, liftName, isRest, exercises: [{name, sets,
    rest, note}, ...]}. The 'sets' field is a 'NxR' string for
    backward-compat with consumers that parse it that way."""
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    phase = phase_for_week(week)
    out = []
    for d in range(7):
        meta = get_program_day_meta(phase, d, has_gym=has_gym)
        rows = get_program_day(phase, d, has_gym=has_gym)
        exercises = [{
            "name": r["exercise"],
            "sets": f'{r["sets"]}x{r["reps"]}',
            "rest": r["rest"] or "60s",
            "note": r["note"] or "",
        } for r in rows]
        out.append({
            "day_idx": d,
            "day": DAY_NAMES[d],
            "liftName": meta["lift_name"],
            "isRest": meta["is_rest"],
            "exercises": exercises,
        })
    return out


def resolve_name(name: str) -> str:
    """Look up a canonical exercise name via ExerciseAlias. Falls back to
    the input if no alias row exists. Empty input returns empty string."""
    if not name:
        return ""
    from models import ExerciseAlias
    row = ExerciseAlias.query.filter_by(alias=name).first()
    return row.canonical_name if row else name


def get_configured_sets_reps(
    exercise_name: str, week: int, day_idx: int,
    exercise_order: Optional[int] = None,
    has_gym: bool = True,
) -> Optional[tuple[int, str]]:
    """Return (sets, reps) from the program template, or None.

    When exercise_order is provided, look up by position first and verify
    the name matches (after resolve_name on both sides). Falls back to
    first-name-match when order is None or doesn't line up."""
    canon = resolve_name(exercise_name).lower()
    phase = phase_for_week(week)
    rows = get_program_day(phase, day_idx, has_gym=has_gym)
    if not rows:
        return None
    if exercise_order is not None and 0 <= exercise_order < len(rows):
        row = rows[exercise_order]
        if resolve_name(row["exercise"]).lower() == canon:
            return (row["sets"], str(row["reps"]))
    for row in rows:
        if resolve_name(row["exercise"]).lower() == canon:
            return (row["sets"], str(row["reps"]))
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_template_io.py -x -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add program_template_io.py tests/test_program_template_io.py
git commit -m "Add program_template_io module: DB-backed read API for templates"
```

---

## Task 4: Wire the seed into app startup

**Files:**
- Modify: `app.py` (after the existing `Exercise` seed block at ~line 384)

- [ ] **Step 1: Insert the seed call**

Find the block that ends `# ONE-TIME: Canonicalize exercise names in set_log and exercise_log` (around app.py:386) and insert immediately above it:

```python
    # Seed program template (ProgramTemplateDay + ProgramTemplate + ExerciseAlias).
    # Idempotent — skips fully-seeded DBs and never overwrites is_user_modified rows.
    try:
        from program_seed import seed_program_template
        seed_program_template()
    except Exception:
        import logging
        logging.exception("program template seed failed at startup")
        db.session.rollback()
```

- [ ] **Step 2: Smoke-test that the app boots**

Run: `source venv/bin/activate && python -c "import app; print('boot OK')"`
Expected: `boot OK` (with seed log lines visible)

- [ ] **Step 3: Verify seeded data exists**

Run:
```bash
source venv/bin/activate && python -c "
from app import app, db
from models import ProgramTemplateDay, ProgramTemplate, ExerciseAlias
with app.app_context():
    print('days:', ProgramTemplateDay.query.count())
    print('rows:', ProgramTemplate.query.count())
    print('aliases:', ExerciseAlias.query.count())
"
```
Expected: `days: 70`, `rows: 200+`, `aliases: 30+` (rough — depends on dev DB state)

- [ ] **Step 4: Run full test suite to verify no regression**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass (27 existing + new tests)

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "Seed program template at app startup"
```

---

## Task 5: Switch `workout_data.get_workouts` to a shim

**Files:**
- Modify: `workout_data.py:1541-1583` (`get_workouts` and `get_workouts_for_user`)

- [ ] **Step 1: Replace `get_workouts` body with delegation**

```python
def get_workouts(week):
    """Return list of 7 day dicts for the given week.

    Runtime source of truth is the program_template DB tables. The
    PHASE_TEMPLATES/BW_PHASE_TEMPLATES dicts above are SEED-ONLY now —
    program_seed.seed_program_template() reads them once on startup.
    Edit a template by updating ProgramTemplate rows (admin endpoint),
    not by editing this file. The dicts will be removed in a future
    release once the admin UI is in place."""
    from program_template_io import get_program_week
    return get_program_week(week, has_gym=True)


def get_workouts_for_user(week, has_gym=True):
    """Variant for bodyweight (has_gym=False) users."""
    from program_template_io import get_program_week
    return get_program_week(week, has_gym=has_gym)
```

- [ ] **Step 2: Add SEED-ONLY marker comment above PHASE_TEMPLATES**

Find `PHASE_TEMPLATES = {` (around line 962) and add immediately above:

```python
# ─── SEED-ONLY DATA — DO NOT EDIT FOR RUNTIME EFFECT ──────────────────────
# These dicts are read ONCE by program_seed.seed_program_template() at app
# startup to populate the program_template DB tables. Runtime reads happen
# through program_template_io.get_program_day() and friends. Editing here
# does NOT change a deployed app's behavior — edit ProgramTemplate rows
# instead (see /api/admin/program-template-row/<id>).
```

- [ ] **Step 3: Run full test suite**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass (the shim returns the same shape consumers expect)

- [ ] **Step 4: Smoke-test `/api/workouts` shape**

Run:
```bash
source venv/bin/activate && python -c "
from app import app
from workout_data import get_workouts
with app.app_context():
    days = get_workouts(5)
    assert len(days) == 7
    print('day 1 lift:', days[1]['liftName'])
    print('day 1 exercises:', [(e['name'], e['sets']) for e in days[1]['exercises']])
"
```
Expected: 7 days, day 1 (Tuesday) shows Lat Pulldown 5x5 and 3x12.

- [ ] **Step 5: Commit**

```bash
git add workout_data.py
git commit -m "Delegate get_workouts/get_workouts_for_user to DB-backed reader"
```

---

## Task 6: Switch `training_engine` and `equipment_swaps` to DB-backed `resolve_name` and configured-reps

**Files:**
- Modify: `training_engine.py` (`_get_configured_sets_reps` body and `resolve_name` import)
- Modify: `equipment_swaps.py` (`resolve_name` import in `get_alternatives`, `check_exercise_available`, `find_swap_entry`, `is_valid_swap`, `auto_swap_workout`)

- [ ] **Step 1: Replace `_get_configured_sets_reps` body in training_engine.py**

Find `def _get_configured_sets_reps(...)` and replace its body with:

```python
def _get_configured_sets_reps(exercise_name, week, day_idx, exercise_order=None):
    """Return (sets, reps) from the program template, or None if unknown.

    Delegates to program_template_io which reads from the DB-backed template.
    Preserves the exercise_order disambiguation behavior."""
    from program_template_io import get_configured_sets_reps
    return get_configured_sets_reps(
        exercise_name, week, day_idx,
        exercise_order=exercise_order,
        has_gym=True,
    )
```

- [ ] **Step 2: Update `resolve_name` import in training_engine.py**

Find every `from workout_data import resolve_name` (and any aliased imports) and replace with `from program_template_io import resolve_name`.

- [ ] **Step 3: Update `resolve_name` import in equipment_swaps.py**

Same replacement: every `from workout_data import resolve_name` → `from program_template_io import resolve_name`. Use grep to find all sites:

```bash
grep -n "from workout_data import.*resolve_name" equipment_swaps.py training_engine.py app.py coach_assembler.py
```

For each match, replace `workout_data` with `program_template_io` for the `resolve_name` import. If the line imports other symbols, split into two imports.

- [ ] **Step 4: Run full test suite**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add training_engine.py equipment_swaps.py app.py coach_assembler.py
git commit -m "Route engine and equipment-swap reads through program_template_io"
```

---

## Task 7: Admin endpoints for editing templates

**Files:**
- Modify: `app.py` (add new endpoints near other `@admin_required` routes around line 6431)
- Test: `tests/test_program_template_admin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_program_template_admin.py
"""Admin can PATCH template rows; user-modified flag flips; immutable
fields refuse changes."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        from program_seed import seed_program_template
        seed_program_template()
        yield app, db


@pytest.fixture
def admin_client(app_ctx):
    app, db = app_ctx
    from models import User
    u = User(email="admin-template@example.com", password_hash="x", is_admin=True)
    db.session.add(u); db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(u.id)
        sess["_fresh"] = True
    return client


class TestAdminPatchTemplateRow:
    def test_patch_reps_succeeds(self, app_ctx, admin_client):
        app, db = app_ctx
        from models import ProgramTemplate
        with app.app_context():
            row = ProgramTemplate.query.first()
            row_id = row.id
            old_reps = row.reps
        resp = admin_client.patch(
            f"/api/admin/program-template-row/{row_id}",
            json={"reps": "8-10"})
        assert resp.status_code == 200
        with app.app_context():
            r = ProgramTemplate.query.get(row_id)
            assert r.reps == "8-10"
            assert r.is_user_modified is True

    def test_patch_immutable_field_rejects(self, app_ctx, admin_client):
        app, db = app_ctx
        from models import ProgramTemplate
        with app.app_context():
            row_id = ProgramTemplate.query.first().id
        resp = admin_client.patch(
            f"/api/admin/program-template-row/{row_id}",
            json={"day_id": 999})
        assert resp.status_code == 400

    def test_patch_invalid_sets_rejects(self, app_ctx, admin_client):
        app, db = app_ctx
        from models import ProgramTemplate
        with app.app_context():
            row_id = ProgramTemplate.query.first().id
        resp = admin_client.patch(
            f"/api/admin/program-template-row/{row_id}",
            json={"sets": 0})
        assert resp.status_code == 400

    def test_patch_unknown_id_404(self, app_ctx, admin_client):
        resp = admin_client.patch(
            "/api/admin/program-template-row/999999",
            json={"reps": "5"})
        assert resp.status_code == 404


class TestAdminGetTemplateDay:
    def test_returns_day_with_rows(self, app_ctx, admin_client):
        resp = admin_client.get(
            "/api/admin/program-template/phase2/gym?day_idx=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["lift_name"]
        assert any(e["exercise_name"] == "Lat Pulldown" for e in data["rows"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_program_template_admin.py -x -v`
Expected: 404 on the new endpoints.

- [ ] **Step 3: Add endpoints to `app.py`**

Add near other admin endpoints (around app.py:6431):

```python
@app.route("/api/admin/program-template/<phase>/<variant>")
@admin_required
def api_admin_program_template_get(phase, variant):
    """Return all rows for one (phase, variant) day. Query param day_idx required."""
    from models import ProgramTemplateDay, ProgramTemplate
    day_idx = request.args.get("day_idx", type=int)
    if day_idx is None:
        return jsonify({"error": "day_idx required"}), 400
    day = ProgramTemplateDay.query.filter_by(
        phase=phase, variant=variant, day_idx=day_idx).first()
    if not day:
        return jsonify({"error": "day not found"}), 404
    rows = (ProgramTemplate.query.filter_by(day_id=day.id)
            .order_by(ProgramTemplate.order_idx).all())
    return jsonify({
        "day_id": day.id,
        "phase": day.phase, "variant": day.variant, "day_idx": day.day_idx,
        "lift_name": day.lift_name, "is_rest": day.is_rest,
        "is_user_modified": day.is_user_modified,
        "rows": [{
            "id": r.id, "order_idx": r.order_idx,
            "exercise_name": r.exercise_name,
            "exercise_id": r.exercise_id,
            "sets": r.sets, "reps": r.reps,
            "rest": r.rest, "note": r.note or "",
            "is_user_modified": r.is_user_modified,
        } for r in rows],
    })


_PROGRAM_TEMPLATE_MUTABLE = {"exercise_id", "exercise_name", "sets", "reps", "rest", "note"}


@app.route("/api/admin/program-template-row/<int:row_id>", methods=["PATCH"])
@admin_required
def api_admin_program_template_patch(row_id):
    """Update a ProgramTemplate row in place. Only mutable fields allowed.
    Sets is_user_modified=True so the seeder leaves it alone."""
    from models import ProgramTemplate, Exercise
    row = ProgramTemplate.query.get(row_id)
    if not row:
        return jsonify({"error": "row not found"}), 404
    data = request.get_json() or {}
    bad = [k for k in data if k not in _PROGRAM_TEMPLATE_MUTABLE]
    if bad:
        return jsonify({"error": f"immutable fields: {bad}"}), 400
    if "sets" in data:
        try:
            s = int(data["sets"])
            if s < 1:
                raise ValueError()
        except (TypeError, ValueError):
            return jsonify({"error": "sets must be a positive integer"}), 400
        row.sets = s
    if "reps" in data:
        reps = str(data["reps"]).strip()
        if not reps or len(reps) > 50:
            return jsonify({"error": "reps must be 1-50 chars"}), 400
        row.reps = reps
    if "rest" in data:
        row.rest = (data["rest"] or "")[:32] or None
    if "note" in data:
        row.note = data["note"] or ""
    if "exercise_name" in data:
        from program_template_io import resolve_name
        canon = resolve_name(data["exercise_name"]).strip()
        if not canon:
            return jsonify({"error": "exercise_name required"}), 400
        ex = Exercise.query.filter_by(name=canon).first()
        row.exercise_name = canon
        row.exercise_id = ex.id if ex else None
    if "exercise_id" in data:
        ex = Exercise.query.get(data["exercise_id"])
        if not ex:
            return jsonify({"error": "exercise_id not found"}), 400
        row.exercise_id = ex.id
        row.exercise_name = ex.name
    row.is_user_modified = True
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "row_id": row.id})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_program_template_admin.py -x -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_program_template_admin.py
git commit -m "Add admin GET/PATCH endpoints for program template rows"
```

---

## Task 8: Final regression sweep + rollout note

**Files:**
- Modify: `tests/conftest.py` (add `seeded_program` fixture for test reuse)

- [ ] **Step 1: Add seeded fixture to `tests/conftest.py`**

Append:

```python
import pytest


@pytest.fixture(scope="session")
def seeded_program():
    """Idempotent program-template seed for tests that need it. Module/session
    scoped so the seed runs at most once per test session."""
    from app import app, db
    with app.app_context():
        db.create_all()
        from program_seed import seed_program_template
        seed_program_template()
    yield
```

- [ ] **Step 2: Run full test suite**

Run: `source venv/bin/activate && python -m pytest tests/ -q`
Expected: all PASS — no regressions in test_swap_validation, test_training_engine_volume, test_program_template_*.

- [ ] **Step 3: Smoke-test the prod-shaped flow**

Run:
```bash
source venv/bin/activate && python -c "
from app import app
with app.app_context():
    from workout_data import get_workouts
    from training_engine import compute_next_targets
    days = get_workouts(5)
    print('week 5 day 1:', [(e['name'], e['sets']) for e in days[1]['exercises']])
    # Engine still works without history (no SetLog rows)
    t = compute_next_targets(1, 'Lat Pulldown', week=5, day_idx=1, exercise_order=2)
    print('engine pump:', t['target_sets'], 'x', t['target_reps'])
"
```
Expected: Lat Pulldown listed twice in day 1; engine returns 3 sets x 12 reps for the pump row (no rep-drop bump).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "Add seeded_program test fixture for shared template seed"
```

- [ ] **Step 5: Push**

```bash
git push origin main
```

---

## Open Questions (FOR USER REVIEW BEFORE EXECUTION)

1. **BW variant lift names.** The seeder reuses gym lift-name builders for the bw variant. If your BW program has different day names/structure, identify the BW-specific source (likely a separate function in workout_data.py) and pass it to `_lift_names_for_phase`. **Confirm or point at the right builder.**

2. **Reseeding admin-modified rows.** The seeder currently never overwrites a `ProgramTemplateDay` once it exists. Do you want an admin "reset to default for this phase/variant" endpoint? Adds a footgun (clears all user edits for that phase) but recovers from a bad admin edit. **Yes/no.**

3. **`Exercise` catalog completeness.** Some BW-only template entries ("Pistol Squat (or assisted)", "Inverted Row (table/ledge)") aren't in the `EXERCISES` catalog today. The seeder will insert ProgramTemplate rows with `exercise_id=NULL` for those. Acceptable for now; backfilling EXERCISES is a separate task. **OK with nullable FK during transition?**

4. **Workout-day metadata other than lift_name.** `DAY_MEAL_TYPES` and `DAY_WARMUP_TYPES` (workout_data.py:305+) are also in the dict but not yet migrated. Within scope of this plan or separate? **Recommend: separate plan**, keep this plan focused on exercise prescriptions.

5. **`workout_data.py` deletion timing.** The dicts stay as seed source for at least one release. When do we delete them? **Recommend: after one prod release with admin endpoints exercised, in a separate PR.**

---

## Risk Mitigations Designed Into the Plan

- **Race condition on seed (CRITICAL #1 from adversarial review):** seed checks `count() >= EXPECTED_DAY_COUNT` before any writes; once seeded, subsequent boots skip immediately.
- **NAME_ALIAS rename orphaning SetLog (HIGH #3):** `seed_aliases` is purely additive — never deletes or renames existing alias rows. Existing one-time canonicalization at app.py:386 stays.
- **Coach context drift (HIGH #4):** `get_program_week` returns the same `{name, sets: "NxR", rest, note}` shape consumers already parse.
- **Idempotency vs admin edits (HIGH #5):** `is_user_modified` flag on both day and row; seed never overwrites flagged rows.
- **Reps schema brittleness (HIGH #7):** `reps` column is `String(50)` (was 20).
- **Test isolation (HIGH #8):** session-scoped `seeded_program` fixture seeds once per test process.
- **Performance (MEDIUM #10):** acceptable for now (12 weeks × 7 days × ~2 small queries = 168 lightweight queries on `/api/workouts`). If a profile shows it as a problem, add an in-process cache keyed by (phase, variant) — invalidate on admin PATCH.
- **Deployment ordering (MEDIUM #12):** schema and code ship together (single deploy via `git push`). Seed runs at startup, populating immediately.
- **Logging signal (cross-cutting):** seed logs `seeded N days, M rows` once per cold boot. Subsequent boots are silent (no spam). Failed seed logs the exception.

---

## Spec Coverage Self-Review

- ✅ Tables for the program template: Tasks 1–2.
- ✅ Seed strategy with idempotency and admin-edit preservation: Task 2.
- ✅ Read API replacing every `PHASE_TEMPLATES` consumer: Tasks 3, 5, 6.
- ✅ Cutover of every read site: Tasks 5 (workout_data shim), 6 (engine + swaps), 8 (regression sweep). Coach assembler and app.py read sites are covered indirectly because they go through `get_workouts` which now delegates.
- ✅ Admin write surface: Task 7.
- ✅ Test strategy: Tasks 2, 3, 7, 8 each ship tests; conftest fixture in 8.
- ⚠️ Open questions surfaced explicitly above; do not execute until those are answered.
