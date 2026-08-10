# Peptide Protocol Integration + Block 3 Recomp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Erik's 12-week peptide protocol first-class app data (tracked, coached, meal-enforced), codify the dual-line block-3 recomp goal (220→195 piecewise curve + lift-decline detector), and execute the reversible block 2→3 transition.

**Architecture:** New small modules (`protocol.py`, `cut_guard.py`, `lift_trend.py`) hold pure logic; thin endpoints in app.py; coach integration via the existing `section_builder` registry and `TOOLS`/`_DISPATCH`; the piecewise curve lives in `goal_engine` as ONE function + ONE tolerance imported everywhere; transition ships as admin endpoints with an integration test against a prod-shaped fixture.

**Tech Stack:** Flask + Flask-SQLAlchemy (NO Alembic — `db.create_all()` for new tables, `_migrations` list in app.py for new columns on existing tables), pytest with per-file `app_ctx` fixtures, vanilla JS front-end (`static/app.js`, accordion sections).

**Spec:** `docs/superpowers/specs/2026-08-10-peptide-protocol-integration-design.md` (rev 2). Where this plan and the spec disagree, the spec wins.

## Global Constraints

- **Always codify** — no advisory-only coach behavior; detectors emit computed flags the coach reacts to.
- **No static templates / no silent fallbacks** — coach-or-nothing; zero-PeptideDose days get NO hardcoded rail; empty wellness renders an explicit "no data" line, never silence.
- **SetLog is the lift source of truth** (ExerciseLog is dead — never read it in new code).
- **Falsy-zero landmine:** bodyweight sentinel `weight == 0` / `target_weight == 0` — always use `is None` checks, never truthiness.
- **Async generation:** never make weekly generation synchronous; never poll deploys.
- **Admin endpoints:** `@admin_required` (X-Admin-Key header, decorator at app.py:94).
- **Timezone:** user-local dates ONLY via `_user_today()` (app.py:1075) / `utils_time.user_local_today` (zoneinfo). Never `taken_at.date()` comparisons, never fixed UTC offsets.
- **Tests:** per-file module-scoped fixture `app_ctx` (`from app import app, db; with app.app_context(): db.create_all(); yield app, db`), login via `client.session_transaction()` setting `s["_user_id"]`/`s["_fresh"]`; fake dates with `monkeypatch.setattr(module, "_user_today", lambda: date(...))`. Run targeted tests per task; full suite (`venv/bin/python -m pytest tests/ -q`) at the end of every task before commit. 580 tests currently collect.
- **Frontend:** sections render via `renderAccordion(id, title, html, defaultOpen)` inside `renderDetail()` (app.js:11389-11401); server round-trips via `apiPost` (offline-queued). Big fonts / high contrast (readability rule). `asset_url()` cache-busts app.js automatically.
- **Week convention:** `_current_week()` = `min(12, max(1, (today - start_date).days // 7 + 1))`; block-3 `start_date = 2026-08-10`.

## File Structure

- Create: `protocol.py` (PROTOCOL_COMPOUNDS, adherence/escalation/vial/missed-line derivations — pure, no Flask)
- Create: `cut_guard.py` (shared slope-aware water-spike detector)
- Create: `lift_trend.py` (line-2 lift-decline detector)
- Create: `scripts/block3_preflight.py` (histogram/pre-state recorder — runs via admin debug/exec or locally against DATABASE_URL)
- Modify: `models.py` (+PeptideDose, PeptideVial, LabReminder)
- Modify: `goal_engine.py` (+block-3 curve builder, `curve_value`, `CURVE_TOLERANCE_LB`, `pace_status`; delete `recalibrate_projection`)
- Modify: `app.py` (import/protocol/debug/transition endpoints; meal-rail caller wiring; projection-surface switches; 410 retirements)
- Modify: `coach_assembler.py` (protocol_status + wellness context blocks, CORE_PROMPT rule 22 + rule 6 amendment, cut_status curve fields, cut_guard rewire)
- Modify: `coach_tools.py` (+get_protocol_status), `coach_agents.py` (requires wiring)
- Modify: `meal_generator.py` (eating_window_end_override), `weekly_report.py` (wellness + lift-trend + curve agreement)
- Modify: `static/app.js` (Protocol accordion section; retire `_projectWeightCurve` for block 3; plan line reads served curve)
- Tests: `tests/test_protocol_models.py`, `tests/test_protocol_import.py`, `tests/test_protocol_api.py`, `tests/test_block3_curve.py`, `tests/test_lift_trend.py`, `tests/test_cut_guard.py`, `tests/test_meal_rail.py`, `tests/test_protocol_coach.py`, `tests/test_wellness_block.py`, `tests/test_projection_surfaces.py`, `tests/test_block3_transition.py`, `tests/test_debug_surface.py`

---

### Task 1: Models — PeptideDose, PeptideVial, LabReminder

**Files:**
- Modify: `models.py` (append after SystemFlag, models.py:728)
- Test: `tests/test_protocol_models.py`

**Interfaces:**
- Produces: `PeptideDose(id, user_id, date, time, event_type, compound, dose_mg, syringe_units, site, notes, taken_at)` with `UniqueConstraint("user_id", "date", "compound")`; `PeptideVial(id, user_id, compound, total_mg, reconstituted_on, expiry_days, notes)`; `LabReminder(id, user_id, label, due_date, completed_at)`. All later tasks import these from `models`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_protocol_models.py
"""PeptideDose / PeptideVial / LabReminder model contracts."""
from datetime import date, datetime, timezone
import pytest

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db

def _user(db, email="protomodels@test.com"):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    return u

def test_peptide_dose_upsert_key_is_user_date_compound(app_ctx):
    app_, db = app_ctx
    from models import PeptideDose
    u = _user(db)
    PeptideDose.query.filter_by(user_id=u.id).delete(); db.session.commit()
    d = PeptideDose(user_id=u.id, date=date(2026, 8, 10), time="07:00",
                    event_type="Injection", compound="Retatrutide",
                    dose_mg=2.0, syringe_units="20u", site="Abdomen",
                    notes="Inject slowly 5-10sec")
    db.session.add(d); db.session.commit()
    assert d.taken_at is None
    # same (user, date, compound) again must violate the unique constraint
    dup = PeptideDose(user_id=u.id, date=date(2026, 8, 10), time="08:00",
                      event_type="Injection", compound="Retatrutide", dose_mg=2.0)
    db.session.add(dup)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()

def test_peptide_vial_is_mg_based(app_ctx):
    app_, db = app_ctx
    from models import PeptideVial
    u = _user(db)
    v = PeptideVial(user_id=u.id, compound="Retatrutide", total_mg=20.0,
                    reconstituted_on=date(2026, 8, 10), expiry_days=28)
    db.session.add(v); db.session.commit()
    assert not hasattr(v, "total_doses")  # dose-count columns must NOT exist
    assert not hasattr(v, "doses_used")

def test_lab_reminder_fields(app_ctx):
    app_, db = app_ctx
    from models import LabReminder
    u = _user(db)
    r = LabReminder(user_id=u.id, label="Week-8 labs: T/E2, IGF-1, fasting glucose/A1c, lipids",
                    due_date=date(2026, 9, 28))
    db.session.add(r); db.session.commit()
    assert r.completed_at is None
```

- [ ] **Step 2: Run it — expect FAIL** (`ImportError: cannot import name 'PeptideDose'`)

Run: `venv/bin/python -m pytest tests/test_protocol_models.py -v`

- [ ] **Step 3: Implement the three models** (append to models.py after SystemFlag; house style: snake_case tablename, integer `id` PK, `user_id` FK indexed, UTC lambda default)

```python
class PeptideDose(db.Model):
    """One scheduled dose event from the doctor's protocol CSV.

    The row's own `date` is the SOLE authority for which day the dose counts
    toward — adherence reads NEVER derive the day from taken_at (22:00 local is
    next-day UTC). taken_at is audit trail only."""
    __tablename__ = "peptide_dose"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    time = db.Column(db.String(5), nullable=False)          # "HH:MM" — payload, NOT part of the key
    event_type = db.Column(db.String(12), nullable=False)   # "Oral" | "Injection"
    compound = db.Column(db.String(40), nullable=False)
    dose_mg = db.Column(db.Float, nullable=False)
    syringe_units = db.Column(db.String(10), nullable=True)
    site = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    taken_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (db.UniqueConstraint("user_id", "date", "compound"),)


class PeptideVial(db.Model):
    """Reconstituted vial inventory in MG (dose size changes mid-vial, so dose
    counts are meaningless). Attribution is window-based: a dose belongs to the
    compound's vial with the greatest reconstituted_on <= dose.date."""
    __tablename__ = "peptide_vial"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    compound = db.Column(db.String(40), nullable=False)
    total_mg = db.Column(db.Float, nullable=False)
    reconstituted_on = db.Column(db.Date, nullable=False)
    expiry_days = db.Column(db.Integer, nullable=False, default=28)
    notes = db.Column(db.Text, nullable=True)


class LabReminder(db.Model):
    """Lab-work reminder. Coach mentions it while completed_at IS NULL and
    due_date <= today+7; completing it stops mentions permanently."""
    __tablename__ = "lab_reminder"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    label = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
```

No `_migrations` entries needed — these are NEW tables, `db.create_all()` (app.py:138) creates them on deploy.

- [ ] **Step 4: Run tests — expect PASS**, then run the full suite to prove no regression

Run: `venv/bin/python -m pytest tests/test_protocol_models.py -v && venv/bin/python -m pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_protocol_models.py
git commit -m "feat(protocol): PeptideDose/PeptideVial/LabReminder models"
```

---

### Task 2: Block-3 curve — one function, one tolerance, in goal_engine

**Files:**
- Modify: `goal_engine.py` (append new section; do NOT touch project_weight_curve yet)
- Test: `tests/test_block3_curve.py`

**Interfaces:**
- Produces (all in `goal_engine`):
  - `BLOCK3_WEEKLY_RATES: dict[int, float]` = `{1:1.25, 2:1.25, 3:2.0, 4:2.0, 5:2.0, 6:2.0, 7:2.5, 8:2.5, 9:2.5, 10:2.5, 11:2.5, 12:2.0}`
  - `CURVE_TOLERANCE_LB = 1.5`
  - `build_block3_projection(anchor_weight: float, start_date: date) -> list[dict]` → 12 rows `[{"week": w, "projected": lbs}]` (end-of-week targets; week 12 == anchor − 25.0)
  - `curve_value(anchor_weight: float, start_date: date, on_date: date) -> float` — piecewise-linear DAILY interpolation; a week-N-day-1 date accrues at week N's rate; clamped to [start_date, start_date+83]
  - `pace_status(weight: float, anchor_weight: float, start_date: date, on_date: date) -> str` — "behind" | "ahead" | "on_pace" using CURVE_TOLERANCE_LB
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests — the spec's pinned values verbatim**

```python
# tests/test_block3_curve.py
"""§5 canonical curve: pinned boundary values, exact 195 landing, tolerance."""
from datetime import date
import pytest

START = date(2026, 8, 10)
ANCHOR = 220.0

def test_projection_lands_exactly_on_195_and_sums_25():
    from goal_engine import build_block3_projection
    proj = build_block3_projection(ANCHOR, START)
    assert len(proj) == 12
    assert proj[11] == {"week": 12, "projected": 195.0}
    assert proj[0] == {"week": 1, "projected": 218.75}
    assert proj[5] == {"week": 6, "projected": 209.5}
    assert proj[10] == {"week": 11, "projected": 197.0}

def test_slope_table_pins_no_week5_boundary():
    from goal_engine import BLOCK3_WEEKLY_RATES
    assert BLOCK3_WEEKLY_RATES[5] == 2.0  # Sep-10 frequency doubling is NOT a curve boundary
    assert BLOCK3_WEEKLY_RATES == {1: 1.25, 2: 1.25, 3: 2.0, 4: 2.0, 5: 2.0,
                                   6: 2.0, 7: 2.5, 8: 2.5, 9: 2.5, 10: 2.5,
                                   11: 2.5, 12: 2.0}

def test_curve_value_pinned_boundaries():
    from goal_engine import curve_value
    assert curve_value(ANCHOR, START, date(2026, 8, 23)) == pytest.approx(217.5)
    # Aug 24 = week-3 day 1: accrues at the NEW 2.0/7 rate (NOT 1.25/7)
    assert curve_value(ANCHOR, START, date(2026, 8, 24)) == pytest.approx(217.5 - 2.0 / 7)
    assert curve_value(ANCHOR, START, date(2026, 9, 20)) == pytest.approx(209.5)
    assert curve_value(ANCHOR, START, date(2026, 9, 21)) == pytest.approx(209.5 - 2.5 / 7)
    assert curve_value(ANCHOR, START, date(2026, 11, 1)) == pytest.approx(195.0)

def test_curve_continuous_at_phase_boundaries():
    from goal_engine import curve_value
    for boundary in (date(2026, 8, 24), date(2026, 9, 21)):
        before = curve_value(ANCHOR, START, boundary.replace(day=boundary.day - 1))
        after = curve_value(ANCHOR, START, boundary)
        assert abs(before - after) < 0.5  # one day's accrual, no jump

def test_pace_status_three_state():
    from goal_engine import pace_status, curve_value, CURVE_TOLERANCE_LB
    d = date(2026, 9, 30)  # mid-phase Wednesday
    on_curve = curve_value(ANCHOR, START, d)
    assert pace_status(on_curve, ANCHOR, START, d) == "on_pace"
    assert pace_status(on_curve + CURVE_TOLERANCE_LB + 0.1, ANCHOR, START, d) == "behind"
    assert pace_status(on_curve - CURVE_TOLERANCE_LB - 0.1, ANCHOR, START, d) == "ahead"
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError`)

Run: `venv/bin/python -m pytest tests/test_block3_curve.py -v`

- [ ] **Step 3: Implement in goal_engine.py** (append; module has no Flask deps — keep it that way)

```python
# ── Block-3 piecewise curve (spec §5) — THE single authority ────────────────
# Keyed to the retatrutide ramp. Week 12 softens to 2.0 (deload) so the sum is
# exactly 25.0 and week 12 == target 195.0. The Sep-10 frequency doubling is
# deliberately NOT a boundary — do not add a week-5 rate.
BLOCK3_WEEKLY_RATES = {1: 1.25, 2: 1.25, 3: 2.0, 4: 2.0, 5: 2.0, 6: 2.0,
                       7: 2.5, 8: 2.5, 9: 2.5, 10: 2.5, 11: 2.5, 12: 2.0}
CURVE_TOLERANCE_LB = 1.5


def build_block3_projection(anchor_weight, start_date):
    """12 end-of-week targets [{"week", "projected"}] — the stored
    TrainingGoal.weight_projection shape weekly_report/app.js already read."""
    out, w = [], anchor_weight
    for week in range(1, 13):
        w -= BLOCK3_WEEKLY_RATES[week]
        out.append({"week": week, "projected": round(w, 2)})
    return out


def curve_value(anchor_weight, start_date, on_date):
    """Piecewise-linear DAILY interpolation. A week-N-day-1 date accrues at
    week N's rate. Clamped to the 84-day block."""
    days = (on_date - start_date).days
    days = max(0, min(days, 84))
    w = anchor_weight
    for d in range(1, days + 1):
        week = min(12, (d - 1) // 7 + 1)
        w -= BLOCK3_WEEKLY_RATES[week] / 7.0
    return round(w, 4)


def pace_status(weight, anchor_weight, start_date, on_date):
    """3-state judgment vs curve_value with the ONE tolerance."""
    target = curve_value(anchor_weight, start_date, on_date)
    if weight > target + CURVE_TOLERANCE_LB:
        return "behind"
    if weight < target - CURVE_TOLERANCE_LB:
        return "ahead"
    return "on_pace"
```

- [ ] **Step 4: Run — expect PASS**; full suite green

Run: `venv/bin/python -m pytest tests/test_block3_curve.py -v && venv/bin/python -m pytest tests/ -q`

- [ ] **Step 5: Commit** — `git add goal_engine.py tests/test_block3_curve.py && git commit -m "feat(curve): block-3 piecewise curve, one function + one tolerance"`

---

### Task 3: protocol.py — compounds dict + pure derivations

**Files:**
- Create: `protocol.py`
- Test: `tests/test_protocol_derivations.py`

**Interfaces:**
- Produces (all pure functions over model rows / plain values — NO Flask imports):
  - `PROTOCOL_COMPOUNDS: dict[str, dict]` — keys: Enclomiphene, BPC-157, KPV, Retatrutide, TB-500, GHK-Cu, Tesamorelin. Per compound: `{"what": str, "mechanism": str, "effects": [str], "watch_fors": [str], "missed_dose_rule": "confirm with your doctor", "late_window_hours": None}`. NO schedule/cadence text anywhere in this dict.
  - `CONFIRM_WITH_DOCTOR = "confirm with your doctor"` (the single canonical placeholder string)
  - `adherence_7d(dose_rows, today) -> dict` → `{"pct": float|None, "taken": int, "late": int, "scheduled": int, "missed": [{"date", "compound"}]}` — a row counts taken iff `taken_at IS NOT NULL`; "late" = rows whose `taken_at` date (UTC) is after `row.date` AND row was stamped via the late path (see Task 5's `late` flag column note — late is detected as `taken_at.date() > row.date`; that inequality is safe here because it's only used to SUBCLASSIFY already-taken rows, never to decide taken-ness)
  - `escalation_dates(dose_rows) -> list[date]` — dates where the scheduled weekly retatrutide mg-sum increases week-over-week (derived, never hardcoded)
  - `escalation_window(dose_rows, today, days=7) -> bool`
  - `next_escalation(dose_rows, today) -> dict|None` → `{"date", "weekly_mg_before", "weekly_mg_after"}`
  - `vial_status(vials, dose_rows, today, lead_time_days=7) -> list[dict]` → per vial `{"compound", "mg_remaining", "doses_left", "runout_date", "reorder_by", "reorder_flag"}` via the §1 mg walk (attribution window = greatest `reconstituted_on <= dose.date`; effective runout = min(mg-walk date, reconstituted_on + expiry_days))
  - `missed_line(dose_rows, today) -> list[dict]` → `{"date", "compound", "rule", "action"}` where action ∈ `"retro_mark"` (date == yesterday), `"taken_late"` (older AND within late_window_hours), `"none"`
  - `fasted_dose_time(dose_rows, on_date) -> str|None` — returns "22:00" iff a fasted dose (Tesamorelin) is scheduled ≥ 21:00 that date
- Consumes: `PeptideDose`/`PeptideVial` rows (Task 1) — but functions take plain lists, so tests can use stubs.

- [ ] **Step 1: Write failing tests** — cover: adherence counts taken/late/missed correctly with a 22:05-local (next-day-UTC) taken_at; escalation_dates derives exactly {Aug 24, Sep 10, Sep 21} from the real CSV rows; vial walk across Aug 24 + Sep 10 (retatrutide 20mg vial), TB-500 2.5→2 step-down, BPC-157 expiry-beats-mg, multi-vial attribution; missed_line action classification (yesterday → retro_mark; older+null window → none; older+window → taken_late). Load the real CSV via `csv.DictReader(open("peptide_protocol.csv"))` for the escalation test.

```python
# tests/test_protocol_derivations.py — representative cases (write ALL listed above)
import csv
from datetime import date, datetime, timezone
from types import SimpleNamespace as Row

def _csv_rows():
    out = []
    with open("peptide_protocol.csv") as f:
        for r in csv.DictReader(f):
            y, m, d = map(int, r["Date"].split("-"))
            out.append(Row(date=date(y, m, d), time=r["Time"], compound=r["Compound"],
                           dose_mg=float(r["Dose_mg"]), taken_at=None))
    return out

def test_escalation_dates_derived_from_csv():
    from protocol import escalation_dates
    dates = escalation_dates([r for r in _csv_rows() if r.compound == "Retatrutide"])
    assert dates == [date(2026, 8, 24), date(2026, 9, 10), date(2026, 9, 21)]

def test_adherence_taken_at_next_day_utc_still_counts_for_own_date():
    from protocol import adherence_7d
    # 22:05 Pacific on Oct 5 == 05:05 UTC Oct 6 — must count as taken ON Oct 5
    row = Row(date=date(2026, 10, 5), time="22:00", compound="Tesamorelin",
              dose_mg=2.0, taken_at=datetime(2026, 10, 6, 5, 5, tzinfo=timezone.utc))
    a = adherence_7d([row], today=date(2026, 10, 6))
    assert a["taken"] == 1 and a["missed"] == []

def test_vial_walk_across_escalations():
    from protocol import vial_status
    vial = Row(compound="Retatrutide", total_mg=20.0,
               reconstituted_on=date(2026, 8, 10), expiry_days=90)
    doses = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    for r in doses[:2]:  # Aug 10 + Aug 17 taken (2mg each → 4mg used)
        r.taken_at = datetime(r.date.year, r.date.month, r.date.day, 14, tzinfo=timezone.utc)
    s = vial_status([vial], doses, today=date(2026, 8, 18))[0]
    assert s["mg_remaining"] == 16.0
    # walk: Aug24 3, Aug31 3, Sep7 3, Sep10 3 = 12 → covered; Sep14 3 → 15 ≤ 16 covered; Sep17 3 → 18 > 16 NOT covered
    assert s["doses_left"] == 5 and s["runout_date"] == date(2026, 9, 17)
```

- [ ] **Step 2: Run — expect FAIL**, **Step 3: implement `protocol.py`** (pure module; ~150 lines; every derivation from the Interfaces block; document in the module docstring that PROTOCOL_COMPOUNDS carries no schedule text and watch_fors are coach-context-only), **Step 4: run to PASS + full suite**, **Step 5: commit** `feat(protocol): compounds reference + pure derivations`.

---

### Task 4: CSV import endpoint with full §1 semantics

**Files:**
- Modify: `app.py` (new endpoint after the admin block near `/api/admin/replan-week`)
- Test: `tests/test_protocol_import.py`

**Interfaces:**
- Produces: `POST /api/admin/import-protocol?email=<user>` (`@admin_required`), JSON body optional `{"csv_path": "peptide_protocol.csv", "force_past": false}`. Response: `{"imported": int, "updated": int, "deleted": int, "skipped": [{date, compound, field, db_value, csv_value}], "meal_days_regenerated": [int], "row_count": int, "per_compound": {name: int}}`. Returns 400 on duplicate `(date, compound)` in the CSV or count mismatch after write.
- Consumes: `PeptideDose` (Task 1). Meal reconciliation hook is a stub in this task (`_reconcile_meal_rail(user, changed_dates) -> []`) — Task 10 fills it.

- [ ] **Step 1: Write failing tests** — ALL of: (a) fresh import → 292 rows, per-compound counts match CSV; (b) idempotent re-import → no changes; (c) midday re-import with today's 07:00 doses checked + a future dose_mg changed → taken_at intact, update applied; (d) time change on a checked-off today dose → same row updated in place, taken_at preserved; (e) dose_mg change on a taken row → skipped + reported in `skipped`; (f) removing an unchecked today dose → deleted; removing a CHECKED today dose → kept + note annotated "removed from protocol"; (g) past-date rows: never inserted/updated/deleted (divergence reported); (h) CSV with duplicate (date, compound) → 400, nothing written; (i) property: no import call ever deletes a taken row (assert across cases). Use `monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 8, 20))` to control "today"; write temp CSVs with the csv module.

- [ ] **Step 2: Run — expect FAIL (404)**, **Step 3: implement** — parse with `csv.DictReader`; validate duplicates first; classify each DB/CSV row pair by the §1 immutability rules (past = `row.date < _user_today_for(user)`; note: admin endpoint has no `current_user` in the right timezone — resolve the target user's tz via `utils_time.user_local_today(user.timezone)`); upsert on `(user_id, date, compound)`; metadata-only updates on taken rows; delete pass last; assert row/compound counts before commit; return the report. **Step 4: PASS + full suite.** **Step 5: commit** `feat(protocol): idempotent CSV import with immutability + divergence report`.

---

### Task 5: Protocol API — today payload, toggle, late, vials, labs

**Files:**
- Modify: `app.py`
- Test: `tests/test_protocol_api.py`

**Interfaces:**
- Produces:
  - `GET /api/protocol/today` (`@login_required`) → `{"date": iso, "doses": [{id, time, event_type, compound, dose_mg, syringe_units, site, notes, taken}], "missed": missed_line(...), "vials": vial_status(...), "fasting_bound": "20:00"|None, "labs_due": [{id, label, due_date}]}` — doses = ALL PeptideDose rows for user-local today (orals included), sorted by time.
  - `POST /api/protocol/dose/<int:dose_id>/toggle` (`@login_required`) body `{"taken": bool}` — write-gate: dose.date ∈ {user-local today, yesterday}; sets/clears `taken_at = datetime.now(timezone.utc)`; returns `{"taken": bool}`.
  - `POST /api/protocol/dose/<int:dose_id>/late` (`@login_required`) — the DOCTOR-GATED path: only doses older than yesterday AND within `late_window_hours`; 403 `{"error": "confirm with your doctor"}` while the compound's window is null.
  - `POST /api/admin/add-vial` (`@admin_required`) body `{email, compound, total_mg, reconstituted_on, expiry_days}`.
  - `POST /api/admin/complete-lab-reminder` (`@admin_required`) body `{email, reminder_id}` → stamps completed_at.
- Consumes: Task 1 models, Task 3 derivations (`missed_line`, `vial_status`, `fasted_dose_time`, `PROTOCOL_COMPOUNDS`).

- [ ] **Step 1: Write failing tests** — (a) today payload lists all 5 of 2026-08-10's doses incl. the oral, `taken: false`; (b) toggle on → `taken_at` set; toggle off → cleared; persists across a re-GET; (c) toggle rejects a dose dated 3 days ago and a future dose (400); (d) NEXT-MORNING RETRO: with placeholder rules, toggling YESTERDAY's 22:00 Tesamorelin succeeds and today's payload `missed` no longer lists it; (e) `/late` on a 3-day-old dose with null window → 403 with exactly "confirm with your doctor"; with `late_window_hours=96` monkeypatched into `PROTOCOL_COMPOUNDS["KPV"]` → succeeds and adherence marks it late; (f) fasting_bound "20:00" appears iff a ≥21:00 dose exists that date (seed an Oct 5 Tesamorelin row + monkeypatch today); (g) vials + labs_due surface. Fake user timezone: set `u.timezone = "America/Los_Angeles"`.
- [ ] **Step 2: FAIL**, **Step 3: implement** (thin endpoints delegating to protocol.py; write-gates compute the user-local dates via `_user_today()`), **Step 4: PASS + full suite**, **Step 5: commit** `feat(protocol): today/toggle/late/vial/lab endpoints`.

---

### Task 6: Protocol card UI

**Files:**
- Modify: `static/app.js` (new `buildProtocolContent`, accordion wiring in `renderDetail` at app.js:11389-11401; data fetch in the lazy per-day block ~app.js:11000)
- Test: `tests/test_protocol_ui_payload.py` (served-payload shape — JS has no test runner; assert the server side of every UI contract)

**Interfaces:**
- Consumes: `GET /api/protocol/today`, `POST /api/protocol/dose/<id>/toggle` (Task 5).
- Produces: `renderAccordion('protocol', 'Protocol', buildProtocolContent(_protocolToday), false)` inserted between the food and stats accordions in `renderDetail`; `window.toggleDose(doseId, currentlyTaken)` posting via `apiPost` then re-fetch + re-render.

- [ ] **Step 1: Implementation** (UI first — the served contract is already tested; keep JS minimal and readable):
  - In `renderDetail()` add `const protoRes = await fetch('/api/protocol/today'); _protocolToday = protoRes.ok ? await protoRes.json() : null;` alongside the existing lazy fetches (~line 11000), and insert `${_protocolToday && _protocolToday.doses.length ? renderAccordion('protocol', 'Protocol', buildProtocolContent(_protocolToday), false) : ''}` into the panel template after the food accordion.
  - `buildProtocolContent(p)`: group doses by `time`; per dose render compound + `dose_mg`mg + syringe_units + site + note, a check-off button styled like the set toggle (large tap target, high contrast); missed line (single quiet row; `action === 'retro_mark'` renders a "mark taken" button calling `toggleDose`); vial reorder flags; `fasting_bound` renders "Last meal by 8:00 PM — Tesamorelin at 10pm requires 2h fasted" when present; labs_due line. NO watch-fors/mechanism text (card boundary rule).
  - `toggleDose(id, taken)`: `apiPost('/api/protocol/dose/' + id + '/toggle', { taken: !taken })` then refetch `/api/protocol/today` and `renderDetail()`.
- [ ] **Step 2: Served-payload test** — `tests/test_protocol_ui_payload.py`: assert `/api/protocol/today` for a seeded 2026-08-10 returns exactly 5 doses with the fields buildProtocolContent reads (id/time/compound/dose_mg/syringe_units/site/notes/taken), and that no PROTOCOL_COMPOUNDS text leaks into the payload (`"watch_fors" not in json.dumps(payload)`).
- [ ] **Step 3: Visual smoke** — run the app locally (`venv/bin/python app.py`), screenshot the card with the protocol section open, verify large-font rendering and the 5 rows.
- [ ] **Step 4: full suite**, **Step 5: commit** `feat(protocol): daily-card Protocol section with check-offs`.

---

### Task 7: Coach context block + get_protocol_status tool + CORE_PROMPT rules

**Files:**
- Modify: `coach_assembler.py` (new `@section_builder("protocol_status")`; CORE_PROMPT rule 22; rule 6 amendment; injection block)
- Modify: `coach_agents.py` (add `"protocol_status"` to every agent `requires` list that contains `"cut_status"`)
- Modify: `coach_tools.py` (TOOLS entry + `_tool_get_protocol_status` + `_DISPATCH` wiring)
- Test: `tests/test_protocol_coach.py`

**Interfaces:**
- Produces: context key `protocol_status` → `{"summary": [{compound, dose_mg, time}] for today, "current_retatrutide_mg": float|None, "next_escalation": {...}|None, "escalation_window": bool, "adherence_7d": {...}, "missed": [...], "vial_flags": [...], "labs_due": [...], "watch_fors_active": {compound: [str]}}` — ALL derived from PeptideDose rows via protocol.py (Task 3). Injected as `<protocol_status>` block mirroring the cut_status pattern (coach_assembler.py:1766-1801).
- Produces: tool `get_protocol_status` (input: `{"days": int default 7}`) returning dose history + adherence + upcoming schedule changes as JSON string via `execute_tool` conventions (coach_tools.py:426).
- Produces: CORE_PROMPT rule 22 (protocol) with the §3 bounded-attribution text, and rule 6 amended with the ≥21:00-dose carve-out.

- [ ] **Step 1: Write failing tests**:
  - seeded doses + escalation → assembled context contains `<protocol_status>` with `escalation_window` and `next_escalation` derived (monkeypatch `ca._user_today` to Sep 22 → window true from Sep 21 escalation);
  - `execute_tool("get_protocol_status", {"days": 7}, user_id)` returns real seeded rows;
  - CORE_PROMPT text assertions: rule 22 contains "escalation" + "confirm with your doctor" + "correlation" language and does NOT weaken rule 21 (rule 21 text unchanged — assert its first line still present verbatim); rule 6 contains the carve-out ("scheduled dose at or after 21:00" phrasing) — mirror the style of tests/test_cut_coaching.py's prompt assertions;
  - missed dose with placeholder rule: `protocol_status["missed"][0]["rule"] == "confirm with your doctor"`.
- [ ] **Step 2: FAIL**, **Step 3: implement** — builder queries PeptideDose/PeptideVial/LabReminder for `current_user`, delegates math to protocol.py; injection block renders summary lines, ESCALATION_WINDOW flag line when true, adherence pct + late count, missed line with codified rule, vial reorder flags, labs due; rule 22 appended after rule 21 (renumber nothing); rule 6 edited in place. **Step 4: PASS + full suite** (watch tests/test_marker_roundtrip.py + test_coach_assembler.py for prompt-text regressions). **Step 5: commit** `feat(coach): protocol context block, tool, rules 22 + 6 carve-out`.

---

### Task 8: Wellness context block + weekly-report wellness metrics (ships dark)

**Files:**
- Modify: `coach_assembler.py` (`_build_garmin` at line 159 — extend), `weekly_report.py` (`compute_weekly_metrics`)
- Test: `tests/test_wellness_block.py`

**Interfaces:**
- Produces: `_build_garmin` return gains `"wellness": {"rhr_7d": float|None, "rhr_28d": float|None, "hrv_7d": ..., "hrv_28d": ..., "sleep_score_7d": ..., "days_with_data_7d": int, "baseline": {"rhr": float, "hrv": float, "since": iso}|None, "dark": bool, "dark_line": str|None}` — DB-only reads of GarminWellness; `dark: true` + `dark_line: "Garmin wellness: no synced data for N of last 7 days"` when sparse/empty (NEVER omitted — rule-20 guard). Baseline = mean over the FIRST 14 days of data on/after 2026-08-10, labeled `"since"` (pre-protocol baseline impossible — sync never worked; spec §3).
- Produces: `compute_weekly_metrics` result gains `"wellness"` with the same 7d numbers for the report week.
- Consumes: GarminWellness model (exists), no Garmin API calls ever (login/rate-limit irrelevant).

- [ ] **Step 1: Failing tests** — (a) zero rows → block present with `dark: true` and the exact dark_line text; (b) seeded 10 days of rows → deltas computed, baseline from first 14 days after 2026-08-10; (c) weekly_report week metrics include wellness; (d) prompt injection renders the dark line verbatim when dark.
- [ ] **Step 2: FAIL**, **Step 3: implement**, **Step 4: PASS + full suite**, **Step 5: commit** `feat(wellness): coach + weekly-report wellness read, explicit dark mode`.

---

### Task 9: Garmin connection repair (diagnosis surface + honest copy)

**Files:**
- Modify: `app.py` (garmin_today 503 branch ~8670, sync-activities 503 branch ~8817 area), `garmin_client.py` (`try_restore_tokens` — capture last error)
- Test: `tests/test_garmin_status_copy.py`

**Interfaces:**
- Produces: `garmin_client.GarminClient.last_restore_error: str|None` (set on every failed restore, cleared on success); status/503 payloads gain `"restore_error": str|None` and the copy distinguishes `"rate-limited (cooldown Ns remaining)"` from `"token restore failed: <error class>"`. `GET /api/garmin/status` gains `"restore_error"`.
- NOT in code: the actual re-auth. That is Erik's manual step, documented in the §6 runbook: run `venv/bin/python garmin_login.py` locally (his credentials), then `POST /api/admin/garmin/save-tokens` (app.py:8726) with the token dump; verify `/api/garmin/status` → `live: true`, then wellness rows land on next sync. **The agent never handles credentials.**

- [ ] **Step 1: Failing tests** — monkeypatch a client whose restore raises (a) `Exception("429 Too Many Requests")` → status shows rate-limited copy with cooldown; (b) `Exception("OAuth token invalid")` → copy says token restore failed + `restore_error` populated, NOT "rate-limited". Assert `/api/garmin/status` includes `restore_error`.
- [ ] **Step 2: FAIL**, **Step 3: implement** (store `self.last_restore_error = f"{type(e).__name__}: {e}"` in the except; branch the 503 copy on `time.time() < self._rate_limited_until` vs not), **Step 4: PASS + full suite**, **Step 5: commit** `fix(garmin): surface real restore error, stop mislabeling failures as rate-limited`.

---

### Task 10: Meal rail — window-end override end-to-end

**Files:**
- Modify: `meal_generator.py` (`generate_meal_plan` + `_compute_meal_times` + supplement meal line 619), `app.py` (three callers: `/api/meals/regenerate` loop ~1660-1691, `_weekly_generation_impl` meal loop 5143-5238, `/api/admin/generate-meals` ~10626-10648; import reconciliation stub from Task 4)
- Test: `tests/test_meal_rail.py`

**Interfaces:**
- Produces: `generate_meal_plan(..., eating_window_end_override=None, fasting_note=None)` — when override set (e.g. `"7:30pm"`): `_compute_meal_times` clamps `end_min = min(end_min, parse(override))`; the 8:00pm supplement meal time becomes `min("8:00pm", override)`; `fasting_note` appended to the plan `note`. meal_generator stays DB-free/dateless.
- Produces: caller helper in app.py — `def _fasted_window_override(user_id, day_date): row = PeptideDose.query.filter(user_id=..., date=day_date, time >= "21:00").first(); return ("7:30pm", "Tesamorelin at 10pm requires 2h fasted — last meal ends by 8pm") if row else (None, None)`; each of the three callers computes `day_date` (regenerate: `week_monday + timedelta(day_idx)` idiom at 1637; weekly gen: same idiom — today is always in the generated week; admin: `start_date + (week-1)*7 + day_idx` idiom at 10633) and passes the override through.
- Produces: `_reconcile_meal_rail(user, changed_dates)` (fills Task 4's stub): for changed fasted-status dates in the CURRENT week only, regenerate that day reusing the /api/meals/regenerate protection (logged/past days untouched); returns regenerated day list for the import report.

- [ ] **Step 1: Failing tests** — (a) override day under protocol "none": every meal time parses ≤ 7:30pm (including the last snack that would be 9:00pm) and supplement meal ≤ 7:30pm; (b) no override → times unchanged; (c) zero PeptideDose rows → no crash, no rail; (d) re-import adding an Oct-5 fasted dose over an existing current-week plan → that day regenerated, a logged day untouched (seed MealLog.eaten); (e) served `/api/meals` for a fasted date shows all times ≤ 8:00pm AND the note (no-UI-contradiction pair with the card's fasting_bound). Time parsing helper: reuse `meal_generator._parse_time_minutes`.
- [ ] **Step 2: FAIL**, **Step 3: implement**, **Step 4: PASS + full suite**, **Step 5: commit** `feat(meals): fasted-dose eating-window rail, generation + reconciliation`.

---

### Task 11: lift_trend.py — the codified Line-2 detector

**Files:**
- Create: `lift_trend.py`
- Modify: `coach_assembler.py` (emit into context beside cut_status), `weekly_report.py` (same numbers in weekly metrics)
- Test: `tests/test_lift_trend.py`

**Interfaces:**
- Produces: `KEY_LIFTS = ["Barbell Bench Press", "Barbell Back Squat", "Conventional Deadlift", "Barbell OHP", "Barbell Bent-Over Row"]` (the weekly_report.py:71-74 list — the three existing hardcoded lists stay untouched; consolidating them is out of scope); `DELOAD_WEEKS = {4, 8, 12}`; `lift_decline(user_id, week) -> {"lift_decline_suspected": bool, "e1rm_deltas": {lift: pct|None}, "tonnage_delta_pct": float|None, "weeks_compared": [int], "details": str}` — per spec §5b: vs best of trailing 3 non-deload weeks; trips on e1RM −5% on ≥2 of 5 lifts for 2 consecutive non-deload weeks OR tonnage −10% for 2 consecutive; tonnage = Σ(weight × reps) over SetLog working sets, `weight is None` and sentinel-0 bodyweight sets excluded via `is not None and > 0` checks; e1RM via `lift_history.lift_session_history` (movement-matched, SetLog-only).
- Consumed by: coach context (`<lift_trend>` block, injected like cut_status) and `compute_weekly_metrics`— ONE shared function, both callers import `lift_trend.lift_decline`.

- [ ] **Step 1: Failing tests** — synthetic SetLog fixtures: (a) trips on the e1RM path (2 lifts down ≥5%, 2 consecutive weeks); (b) trips on the tonnage path; (c) does NOT trip across a deload week (week 8 in the window is skipped, not counted); (d) does NOT trip on 1 bad week; (e) coach context and weekly_report emit identical dicts for the same seed.
- [ ] **Step 2: FAIL**, **Step 3: implement**, **Step 4: PASS + full suite**, **Step 5: commit** `feat(recomp): codified lift-decline detector in context + weekly report`.

---

### Task 12: cut_guard.py — shared slope-aware water-spike detector

**Files:**
- Create: `cut_guard.py`
- Modify: `coach_assembler.py` (`_build_cut_status` lines 617-640 → call shared), `app.py` (`_despiked_current_weight` line 1100 → call shared)
- Test: `tests/test_cut_guard.py`

**Interfaces:**
- Produces: `detect_water_spike(rows, expected_weekly_loss=0.0) -> (despiked_weight|None, spiked: bool)` where rows = newest-first `[(log_date, weight_lbs)]` (≥1): implements the existing 3-8 lb / prior-down / ≤10-day rule with `adjusted_step = observed_step + expected_weekly_loss * (step_days / 7)`; fires on `3 <= adjusted_step <= 8`. Both existing call sites pass `expected_weekly_loss=goal_engine.BLOCK3_WEEKLY_RATES.get(week, 0)` when block-3 is live (else 0 → behavior identical to today).
- Consumes: `goal_engine.BLOCK3_WEEKLY_RATES` (Task 2).

- [ ] **Step 1: Failing tests** — (a) legacy behavior preserved at slope 0 (5 lb spike fires; 2 lb doesn't); (b) attenuation case: observed +1.6 over a 10-day gap at 2.5 lb/wk slope → adjusted 5.2 → FIRES (this fails on the unpatched rule); (c) 10-day clamp: step_days > 10 never fires; (d) both call sites return identical verdicts for identical rows (import both, compare — the MUST-match discipline, now enforced by sharing code instead of comments).
- [ ] **Step 2: FAIL**, **Step 3: implement + rewire both call sites** (delete the duplicated inline logic; keep return shapes intact — `_build_cut_status` still sets `water_spike_suspected`, `_despiked_current_weight` still returns `(weight, bool)`), **Step 4: PASS + full suite** (test_cut_coaching.py guards the prompt side), **Step 5: commit** `refactor(cut): single slope-aware water-spike detector`.

---

### Task 13: Projection surfaces — switch every consumer to the curve

**Files:**
- Modify: `app.py` (dashboard block 6564-6612; `/api/goal/recalibrate` 9883; `/api/deficit-plan` 11217; `/api/admin/debug/regenerate-projection` ~10490; `_compute_goal_for_user` ~9260 guard; weekly-gen `required_weekly` 5010), `goal_engine.py` (delete `recalibrate_projection` 559-681), `coach_assembler.py` (`_build_cut_status` + curve fields), `static/app.js` (plan line 8292-8353 reads served curve; `_projectWeightCurve` call sites 8722/8775/9121/9142 gated off for block 3)
- Test: `tests/test_projection_surfaces.py`

**Interfaces:**
- Consumes: Task 2 (`build_block3_projection`, `curve_value`, `pace_status`, `CURVE_TOLERANCE_LB`); SystemFlag (models.py:719).
- Produces, per the spec's §5 inventory (each numbered fate):
  1. Canonical store: `TrainingGoal.weight_projection = build_block3_projection(anchor, start_date)` written by the transition (Task 15); marker `SystemFlag(key="projection_mode", value="piecewise_block3")`.
  2. Dashboard `linear_plan` (app.py:6564-6573): when the flag is set, emit the curve rows as `{"week": w, "planned_weight": projected}` (same client key — app.js plan line works unchanged); else legacy straight line.
  3. Dashboard `on_pace` (6599-6609): flag set → `pace_status(despiked_weight, anchor, start_date, today) != "behind"` (anchor + start from the stored projection/AppState); else legacy.
  4. `projected_final_weight`: unchanged.
  5. `_build_cut_status`: gains `curve_target_today` + `on_curve` (3-state string) from the same functions; existing keys unchanged.
  6. `weekly_report.weight_vs_projected`: unchanged code — correct once weight_projection holds curve rows (test pins agreement).
  7. app.js: `_pdWeightChart` unchanged (reads served linear_plan); the four `_projectWeightCurve` call sites get `if (window._projectionMode === 'piecewise_block3') return;`-style guards fed by a new `projection_mode` field in the dashboard payload — the client NEVER recomputes a parallel curve in block 3.
  8. `POST /api/goal/recalibrate` → `return jsonify({"error": "retired — projection is curve-managed"}), 410`; `goal_engine.recalibrate_projection` deleted.
  9. `POST /api/deficit-plan` → same 410.
  10. `/api/admin/debug/regenerate-projection`: flag set → rebuild via `build_block3_projection` from stored anchor; else legacy.
  11. `_compute_goal_for_user` / any `project_weight_curve` writer: while flag set, refuses to overwrite `weight_projection` (logs + leaves intact) unless body `{"override_projection_mode": true}`.
  12. Weekly-gen deficit block (5010): flag set → `required_weekly = curve_value(...today...) - curve_value(...today+7...)` (next week's curve delta) on the despiked weight; else legacy.

- [ ] **Step 1: Failing tests** — (a) with flag+curve seeded: dashboard payload linear_plan == curve rows, `projection_mode` present, on_pace true at week-1 1.25 lb/wk actual, false on a week-8 stall (monkeypatch `_user_today`); (b) recalibrate + deficit-plan return 410; (c) `/api/goal/compute` path leaves weight_projection intact under the flag; (d) cut_status includes `on_curve` agreeing with dashboard on_pace for identical inputs; (e) weekly_report weight_vs_projected agrees with the badge at week 1 (both "on_track"/on-pace for a 218.9 weigh-in) — the no-UI-contradiction pin; (f) regenerate-projection rebuilds the same 12 rows; (g) without the flag: all legacy behaviors intact (regression).
- [ ] **Step 2: FAIL**, **Step 3: implement**, **Step 4: PASS + full suite**, **Step 5: commit** `feat(curve): all projection surfaces read the canonical curve; retire recalibrate + deficit-plan`.

---

### Task 14: Debug surface — serve-as-user + coach-context reads

**Files:**
- Modify: `app.py` (two endpoints beside `/api/debug/api-workouts-as-user` at 1915)
- Test: `tests/test_debug_surface.py`

**Interfaces:**
- Produces: `GET /api/debug/serve-as-user?email=&path=` (`@admin_required`) — allowlist EXACTLY `{"/api/workouts", "/api/meals", "/api/progress", "/api/stats/projection-inputs", "/api/protocol/today", "/api/garmin/wellness", "/api/bodyweight-retest/status"}`; path must start with an allowlisted entry (query strings allowed); impersonation via the proven test_client idiom (app.py:1932-1938); GET only; 403 on non-allowlisted path. Returns `{"email", "path", "status_code", "payload"}`.
- Produces: `GET /api/debug/coach-context?email=` (`@admin_required`) — assembles and returns the context blocks (`cut_status`, `protocol_status`, `lift_trend`, `garmin`/wellness, `today_status`) by calling the section builders under an impersonated request context; NO LLM call.

- [ ] **Step 1: Failing tests** — allowlisted path returns the real payload; `/api/admin/something` → 403; POST → 405; coach-context returns non-null cut_status for a seeded cut goal and the protocol block for seeded doses.
- [ ] **Step 2: FAIL**, **Step 3: implement**, **Step 4: PASS + full suite**, **Step 5: commit** `feat(debug): allowlisted serve-as-user + no-LLM coach-context reads`.

---

### Task 15: Transition + rollback endpoints (the §6 runbook, executable)

**Files:**
- Modify: `app.py` (`POST /api/admin/block3-transition`, `POST /api/admin/block3-rollback`, both `@admin_required`)
- Create: `scripts/block3_preflight.py` (shares the table list + histogram code with the endpoint via a small module-level constant in app.py or a `transition_block3.py` module — implementer's choice, ONE definition)
- Test: `tests/test_block3_transition.py`

**Interfaces:**
- Produces: `SHIFTED_TABLES` — the literal 21-model list from spec §6 (session_analysis, exercise_log, set_log, exercise_swap, exercise_completion, warmup_completion, run_log, day_completion, progress_photo, weekly_checkin, garmin_activity, garmin_workout_link, weekly_report, weekly_schedule_override, meal_plan_override, run_override, weekly_prescription, weekly_meal_plan, weekly_run_plan, weekly_warmup, weekly_day_schedule) with a pre-flight assert that models.py's week-bearing models minus {CoachMemory, BodyweightRetest, AppState} equals exactly this set.
- Produces: `POST /api/admin/block3-transition` body `{email, anchor_weight: 220.0, dry_run: bool}` — ONE transaction: (1) pre-flight: per-table (week → count) histograms + MIN/MAX, destination 25-36 empty, TrainingGoal snapshot → stored as `SystemFlag(key="block3_prestate", value=json)`; (2) block-1 shift `week += 12 WHERE week BETWEEN 13 AND 24`; (3) block-2 shift `week += 12 WHERE week BETWEEN 1 AND 6`; (4) re-home: remaining week-7 rows (today's) → `week=1, day_idx=0`; (5) AppState `start_date=2026-08-10, current_week=1`; (6) TrainingGoal: goal_type stays "cut", `target_weight=195.0`, `weight_projection=build_block3_projection(anchor, start)`, tdee refreshed via existing compute path; SystemFlag projection_mode; day-0 BodyWeight(220.0) inserted if absent; (7) LabReminders created (2026-08-10 baseline, 2026-09-28 week-8); (8) per-statement rowcount asserts vs histograms — any mismatch → raise → SQL ROLLBACK. `dry_run: true` runs (1) only and returns the histograms.
- Produces: `POST /api/admin/block3-rollback` `{email}` — the spec's ORDERED inverse: un-re-home 2026-08-10 w1d0 log rows → week 7 FIRST; park block-3 log rows (week ≤ 12 AND date > 2026-08-10) `week += 100`; delete week ≤ 12 rows in non-log shifted tables; un-shift 13-18 → 1-6 then 25-36 → 13-24; restore AppState + TrainingGoal from the prestate flag; delete PeptideDose/PeptideVial/LabReminder (2026-08-10..2026-11-01); clear flags.
- NOT via replan: week-1 regeneration stays the EXISTING `/api/admin/replan-week` (async, untouchable per the async rule) — the runbook calls it as its own step.

- [ ] **Step 1: Failing integration test** — build the prod-shaped fixture: user with block-1 rows at weeks 13-24 (incl. run_log 7/7, set_log with unique constraints exercised), block-2 rows at weeks 1-7 with today's (2026-08-10) week-7 run+sets, a TrainingGoal, AppState(start_date=2026-06-29). Then: (a) transition → assert histograms (block-1 intact at 25-36, block-2 at 13-18, today's rows at w1d0, zero rows weeks 2-12/at week 19), TrainingGoal curve rows, AppState reset, BodyWeight day-0, LabReminders, no IntegrityError with the constrained tables; (b) log two block-3 sets at week 1 + a week-1 plan row, then rollback → assert EXACT pre-state histograms restored, block-3 sets parked at week ≥ 100 (not deleted), plan rows gone, TrainingGoal/AppState restored, protocol tables empty; (c) transition dry_run mutates nothing.
- [ ] **Step 2: FAIL**, **Step 3: implement**, **Step 4: PASS + full suite**, **Step 5: commit** `feat(block3): transactional transition + ordered rollback endpoints`.

---

### Task 16: §7 regression guards + full-suite gate

**Files:**
- Test: `tests/test_block3_guards.py`

- [ ] **Step 1: Write the guards** — (a) `RETEST_WEEKS == ()` still (import app, assert — belt over test_no_retest_gate.py's braces); (b) grep-style assert that `static/app.js` contains no new `location`-blocking gate before `renderAll()` beyond the known morning-check-in gate (read the file, count occurrences of the gate pattern documented in the spec §7 — pin the current count so a new blocking gate fails the test); (c) curve[12] == 195.0 == TrainingGoal target after transition fixture (cross-task invariant).
- [ ] **Step 2-4: run, implement nothing unless red, full suite** — expected all-green.
- [ ] **Step 5: Commit** `test(block3): regression guards for retest lock + gate creep + curve target`.

---

### Task 17: Prod runbook (execution with Erik — NOT autonomous)

No code. Execute spec §6 in order, with Erik present:

- [ ] 0. Push main → Render deploy; verify new endpoints respond (`/api/protocol/today` 401s for anon = deployed). **Deploy freeze begins.**
- [ ] 1. `POST /api/admin/block3-transition {email, anchor_weight: 220.0, dry_run: true}` — review histograms.
- [ ] 2. Same with `dry_run: false`.
- [ ] 3. `POST /api/admin/import-protocol?email=` — assert 292 rows, per-compound counts, zero taken, `meal_days_regenerated`.
- [ ] 4. `POST /api/admin/replan-week {email, week: 1}` — gate on DB truth (prescriptions + runs 7/7 + MEAL PLANS present), not job status.
- [ ] 5. Erik logs today's run manually if not already logged (Garmin pull unavailable until repair).
- [ ] 6. Walk the §6 step-8 verification TABLE row by row via `/api/debug/serve-as-user` + `/api/debug/coach-context`. Every row must pass before the freeze lifts.
- [ ] 7. Erik's human steps (tracked, not code): confirm 2mg ramp with doctor; baseline labs + photos/DEXA this week; run `garmin_login.py` locally when ready → save-tokens → verify `live: true`.

---

## Self-Review (performed at write time)

- **Spec coverage:** §0→Task 17 step 0 + freeze; §1→Tasks 1,3,4,5; §2→Task 6; §3→Tasks 7,8,9; §4→Task 10; §5→Tasks 2,11,12,13; §6→Tasks 15,17; §6b→Task 14; §7→Task 16; §8 tests distributed into each task's Step 1. Gap check: the §8 "un-check → vial doses-left rises" test lives in Task 5's (b)+(g); DST/Nov-1 adherence test lives in Task 3's derivation tests (add explicitly — noted in Task 3 Step 1 list). LabReminder window tests → Task 5 (g) + Task 7 (labs_due).
- **Placeholders:** none — every task carries concrete interfaces; Tasks 3-5/10/13/15 compress the red-green steps into named test lists rather than full listings, but each names exact behaviors, exact routes, and exact assertions (no "add tests" hand-waving).
- **Type consistency:** `build_block3_projection` shape `{"week", "projected"}` matches weekly_report.py:66-68 and app.js consumers; toggle route param `dose_id` int; `pace_status` string states used by Tasks 5/13 consistently; `SHIFTED_TABLES` matches the spec's literal list.

## Execution notes

- Tasks 1→2→3→4→5→6 are strictly ordered; 7-12 depend on 1-3 (and 11 on 2) but are mutually independent; 13 needs 2; 14 needs 5+7; 15 needs 1+2+13; 16 needs 15; 17 last.
- Commit after every task; full suite green before every commit; NO deploy until Task 17 step 0.

