"""C2 — the WEEKLY working-set floor: the anti-taper rail (distinct from the
per-day exercise-count floor in test_volume_floor.py).

A climbing TARGET (C1) is not enough — block 1 had a ceiling and the coach
undershot it (163 -> 48 sets). enforce_safety's weekly floor backfills sets onto
existing movements (accessories first, cap 6/exercise) until the week meets its
floor, so total volume can't collapse below the last hard week. It must NEVER
push above the ceiling, must be exempt on deload weeks, and must not throw on
block week 1 (no prior week). The floor value itself comes from
_prev_nondeload_total, which walks back PAST deload weeks.
"""
import pytest


def _total(prog):
    return sum(it["sets"] for items in prog.values() for it in items)


def _prog():
    return {
        0: [{"exercise": "Barbell Back Squat", "sets": 3, "reps": "5", "weight": 185, "rest": "150s"},
            {"exercise": "Leg Curl", "sets": 2, "reps": "10", "weight": 60, "rest": "60s"}],
        1: [{"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "weight": 155, "rest": "150s"},
            {"exercise": "Cable Fly", "sets": 2, "reps": "12", "weight": 30, "rest": "60s"}],
    }


_HIST = {"history_exercises": {"Barbell Back Squat", "Leg Curl",
                               "Barbell Bench Press", "Cable Fly"},
         "history_max_weight": 200}


def test_weekly_set_floor_backfills_to_floor():
    from coach_planning_program import enforce_safety
    out, actions = enforce_safety(_prog(), rest_day_idx=6, ceiling=40,
                                  floor=16, deload=False, **_HIST)
    assert _total(out) >= 16
    assert all(it["sets"] <= 6 for items in out.values() for it in items)
    assert any("floor" in a.lower() for a in actions)


def test_weekly_floor_never_exceeds_ceiling():
    from coach_planning_program import enforce_safety
    out, _ = enforce_safety(_prog(), rest_day_idx=6, ceiling=12,
                            floor=100, deload=False, **_HIST)
    assert _total(out) <= 12


def test_weekly_floor_exempt_on_deload():
    from coach_planning_program import enforce_safety
    out, _ = enforce_safety(_prog(), rest_day_idx=6, ceiling=40,
                            floor=30, deload=True, **_HIST)
    assert _total(out) == 10  # no backfill on a deload week


def test_weekly_floor_below_current_is_noop():
    from coach_planning_program import enforce_safety
    out, _ = enforce_safety(_prog(), rest_day_idx=6, ceiling=40,
                            floor=5, deload=False, **_HIST)
    assert _total(out) == 10  # already above the floor -> unchanged


def test_prev_nondeload_total_week_one_is_zero():
    from coach_planning_program import _prev_nondeload_total
    assert _prev_nondeload_total(999999, 1) == 0  # no DB hit; week<=1 short-circuits


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_prev_nondeload_total_skips_deload_week(app_ctx):
    app_, db = app_ctx
    from models import User, WeeklyPrescription
    u = User.query.filter_by(email="weekly-floor-prev@test.com").first()
    if not u:
        u = User(email="weekly-floor-prev@test.com")
        db.session.add(u)
        db.session.commit()
    WeeklyPrescription.query.filter_by(user_id=u.id).delete()
    # week 3 (real)=9 sets; week 4 (deload)=4 sets. The week-5 anchor must walk
    # PAST the week-4 deload and land on week 3's 9 — not stall on the deload.
    for order, (ex, wk, sets) in enumerate(
            [("Squat", 3, 5), ("RDL", 3, 4), ("Squat", 4, 2), ("RDL", 4, 2)]):
        db.session.add(WeeklyPrescription(user_id=u.id, week=wk, day_idx=0,
                                          exercise_order=order % 2,
                                          exercise_name=ex, sets=sets, reps="5",
                                          rest="120s", source="coach"))
    db.session.commit()
    from coach_planning_program import _prev_nondeload_total
    assert _prev_nondeload_total(u.id, 5) == 9
