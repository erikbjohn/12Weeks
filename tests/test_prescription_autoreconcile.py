"""When the athlete logs a BARBELL lift heavier than its prescription, the plan
must auto-reconcile UP so the card never shows "plan 145" next to a logged 155.

Erik (wk10 Sat): benched 155 on a 145 prescription. The plan stayed 145 (the
header) while his set fields + logs read 155 — a visible contradiction that only
cleared when the admin `heal` routine was run by hand. This wires that reconcile
to fire at log time, for one lift, this week + forward, skipping deload weeks.
Mirrors /api/admin/heal-prescriptions. COMPOUNDS only — isolations may be
deliberately light (new-movement light-starts), so they are NOT force-raised.

(2026-08-20: the gate said "barbell", which excluded every dumbbell compound.
DB Bench Press stayed prescribed at 30 lb after being logged at 40, and the card
read "Last: 40 lb -> 30 lb". The rule is compound-vs-isolation, per the catalog.)
"""
from datetime import date

import pytest


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


def _set_rx(db, uid, week, day_idx, name, weight, order=0, reason="orig reason"):
    from models import WeeklyPrescription
    WeeklyPrescription.query.filter_by(
        user_id=uid, week=week, day_idx=day_idx, exercise_name=name).delete()
    db.session.add(WeeklyPrescription(
        user_id=uid, week=week, day_idx=day_idx, exercise_name=name,
        exercise_order=order, sets=3, reps="5", target_weight=weight,
        source="coach", adjustment_reason=reason))
    db.session.commit()


def _target(db, uid, week, day_idx, name):
    from models import WeeklyPrescription
    rx = WeeklyPrescription.query.filter_by(
        user_id=uid, week=week, day_idx=day_idx, exercise_name=name).first()
    return rx.target_weight if rx else None


def test_barbell_overlift_raises_this_week_and_forward_skipping_deload(app_ctx):
    app_, db = app_ctx
    from app import _reconcile_prescription_to_logged
    with app_.app_context():
        u = _mk_user(db, "autoreconcile@test.com")
        uid = u.id
        _set_rx(db, uid, 10, 5, "Barbell Bench Press", 145)   # this week (logged day)
        _set_rx(db, uid, 11, 1, "Barbell Bench Press", 145)   # forward
        _set_rx(db, uid, 12, 1, "Barbell Bench Press", 145)   # forward DELOAD
        _set_rx(db, uid, 9, 1, "Barbell Bench Press", 145)    # PAST — must not change
        from models import WeeklyDaySchedule
        for d in range(7):  # week 12 is a deload only because the coach flagged it
            db.session.add(WeeklyDaySchedule(user_id=uid, week=12, day_idx=d, lift_name="x",
                                             deload=True, deload_reason="coach call"))
        db.session.commit()

        changed = _reconcile_prescription_to_logged(uid, "Barbell Bench Press", 155, 10)

        assert _target(db, uid, 10, 5, "Barbell Bench Press") == 155, "this week not raised"
        assert _target(db, uid, 11, 1, "Barbell Bench Press") == 155, "forward week not raised"
        assert _target(db, uid, 12, 1, "Barbell Bench Press") == 145, "deload week must stay light"
        assert _target(db, uid, 9, 1, "Barbell Bench Press") == 145, "past week must not change"
        weeks_changed = {c["week"] for c in changed}
        assert weeks_changed == {10, 11}


def test_logging_below_prescription_never_lowers_it(app_ctx):
    app_, db = app_ctx
    from app import _reconcile_prescription_to_logged
    with app_.app_context():
        u = _mk_user(db, "autoreconcile-down@test.com")
        uid = u.id
        _set_rx(db, uid, 10, 5, "Barbell Bench Press", 145)
        changed = _reconcile_prescription_to_logged(uid, "Barbell Bench Press", 135, 10)
        assert _target(db, uid, 10, 5, "Barbell Bench Press") == 145
        assert changed == []


def test_non_barbell_isolation_is_not_force_raised(app_ctx):
    app_, db = app_ctx
    from app import _reconcile_prescription_to_logged
    with app_.app_context():
        u = _mk_user(db, "autoreconcile-iso@test.com")
        uid = u.id
        _set_rx(db, uid, 10, 5, "Cable Chest Fly", 30)
        changed = _reconcile_prescription_to_logged(uid, "Cable Chest Fly", 45, 10)
        assert _target(db, uid, 10, 5, "Cable Chest Fly") == 30
        assert changed == []


# ─── Compound, not barbell: the 2026-08-20 DB Bench Press regression ────────

def test_dumbbell_compound_is_reconciled_like_a_barbell_lift(app_ctx):
    """DB Bench Press logged at 40 must not leave a 30 lb plan on the card."""
    app_, db = app_ctx
    from app import _reconcile_prescription_to_logged
    with app_.app_context():
        u = _mk_user(db, "autoreconcile-dbcompound@test.com")
        uid = u.id
        _set_rx(db, uid, 2, 3, "DB Bench Press", 30)
        changed = _reconcile_prescription_to_logged(uid, "DB Bench Press", 40, 2)
        assert _target(db, uid, 2, 3, "DB Bench Press") == 40
        assert changed, "a logged-heavier dumbbell compound must raise the plan"


def test_dumbbell_isolation_is_still_protected(app_ctx):
    """The exemption is ISOLATION, not 'has a dumbbell in the name'."""
    app_, db = app_ctx
    from app import _reconcile_prescription_to_logged
    with app_.app_context():
        u = _mk_user(db, "autoreconcile-dbiso@test.com")
        uid = u.id
        _set_rx(db, uid, 2, 3, "Hammer Curl", 20)
        changed = _reconcile_prescription_to_logged(uid, "Hammer Curl", 35, 2)
        assert _target(db, uid, 2, 3, "Hammer Curl") == 20
        assert changed == []


def test_autoreconcile_gate_splits_on_catalog_category():
    from app import _should_autoreconcile
    for compound in ("DB Bench Press", "Barbell Bench Press", "Single-Arm DB Row",
                     "Goblet Squat", "Barbell Back Squat"):
        assert _should_autoreconcile(compound) is True, compound
    for isolation in ("Hammer Curl", "Lateral Raise", "Cable Tricep Pushdown",
                      "DB Curl", "DB Shrug"):
        assert _should_autoreconcile(isolation) is False, isolation


def test_unknown_movement_keeps_the_old_barbell_heuristic():
    """No catalog entry -> behave exactly as before, so nothing regresses."""
    from app import _should_autoreconcile
    assert _should_autoreconcile("Totally Made Up Lift") is False
    assert _should_autoreconcile("Barbell Made Up Lift") is True
