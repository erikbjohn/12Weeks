"""The run coach must never ship a regression vs last week's same-day, same-type
prescription outside a deload week. The prompt asks for it (rule 1) but prompt
adherence is unreliable, so _apply_run_regression_floor enforces it in code.
"""
import pytest


def test_segments_total_is_the_honest_sum():
    """The headline duration is the sum of the coach's own segments — it can
    never be the invented '38 min' for a 34-min session again."""
    from coach_planning_runs import _segments_total_min
    segs = [
        {"kind": "warmup", "minutes": 10},
        {"kind": "work", "minutes": 3, "reps": 4},      # 12
        {"kind": "recovery", "minutes": 3, "reps": 3},  # 9
        {"kind": "cooldown", "minutes": 6},
    ]
    assert _segments_total_min(segs) == 10 + 12 + 9 + 6 == 37
    assert _segments_total_min([{"kind": "steady", "minutes": 60}]) == 60
    assert _segments_total_min([]) == 0


def test_segments_detail_matches_structure():
    from coach_planning_runs import _segments_to_detail
    d = _segments_to_detail([
        {"kind": "work", "minutes": 3, "reps": 4, "hr": "165-175"},
        {"kind": "cooldown", "minutes": 6},
    ])
    assert "4×3 min work" in d
    assert "165-175" in d
    assert "6 min cooldown" in d


def test_parse_run_magnitude():
    from coach_planning_runs import _parse_run_magnitude
    assert _parse_run_magnitude("38 min") == (38.0, "min")
    assert _parse_run_magnitude("9 mi") == (9.0, "mi")
    assert _parse_run_magnitude("9.5 mi") == (9.5, "mi")
    assert _parse_run_magnitude("") == (None, None)
    assert _parse_run_magnitude(None) == (None, None)


@pytest.fixture(scope="module")
def ctx():
    from app import app, db
    from models import User
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="runfloor@test.com").first()
        if not u:
            u = User(email="runfloor@test.com", name="RF",
                     role="user", email_verified=True)
            db.session.add(u); db.session.commit()
        uid = u.id
    return app, uid


def _seed_prev(app, uid, week, day_idx, run_type, duration):
    from app import db
    from models import WeeklyRunPlan
    with app.app_context():
        WeeklyRunPlan.query.filter_by(user_id=uid, week=week, day_idx=day_idx).delete()
        db.session.add(WeeklyRunPlan(
            user_id=uid, week=week, day_idx=day_idx, run_type=run_type,
            label="x", duration=duration, detail="", source="coach"))
        db.session.commit()


def test_floors_regression_to_last_week(ctx):
    app, uid = ctx
    _seed_prev(app, uid, 9, 1, "hiit", "40 min")
    from coach_planning_runs import _apply_run_regression_floor
    with app.app_context():
        out = _apply_run_regression_floor(
            {1: {"type": "hiit", "label": "VO2", "duration": "38 min", "detail": ""}},
            uid, 10)
    assert out[1]["duration"] == "40 min", "must floor up to last week's 40 min"
    assert "held at last week" in out[1]["detail"]


def test_does_not_touch_an_increase(ctx):
    app, uid = ctx
    _seed_prev(app, uid, 9, 1, "hiit", "40 min")
    from coach_planning_runs import _apply_run_regression_floor
    with app.app_context():
        out = _apply_run_regression_floor(
            {1: {"type": "hiit", "label": "VO2", "duration": "44 min", "detail": ""}},
            uid, 10)
    assert out[1]["duration"] == "44 min"


def test_deload_week_may_drop(ctx):
    app, uid = ctx
    _seed_prev(app, uid, 7, 1, "hiit", "40 min")
    from coach_planning_runs import _apply_run_regression_floor
    with app.app_context():
        out = _apply_run_regression_floor(
            {1: {"type": "hiit", "label": "VO2", "duration": "28 min", "detail": ""}},
            uid, 8)  # week 8 is a deload
    assert out[1]["duration"] == "28 min", "deload week may legitimately reduce"


def test_different_type_is_not_a_regression(ctx):
    app, uid = ctx
    _seed_prev(app, uid, 9, 1, "hiit", "40 min")
    from coach_planning_runs import _apply_run_regression_floor
    with app.app_context():
        out = _apply_run_regression_floor(
            {1: {"type": "z2", "label": "Z2", "duration": "30 min", "detail": ""}},
            uid, 10)
    assert out[1]["duration"] == "30 min"
