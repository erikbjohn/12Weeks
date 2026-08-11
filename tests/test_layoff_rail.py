"""Return-from-layoff rail: after a lifting layoff, prescribed loads are capped
to a fraction of each movement's recent top and weekly volume is reduced —
code-enforced (the prompt alone is advisory).

Trigger thresholds: >= 21 days since the last completed set = moderate
detraining (75% caps); >= 42 days = full return protocol (60% caps + volume
ceiling cut to 60%). The caps ride the SAME movement-key matching as the other
rails so equipment variants aren't treated as fresh lifts.
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _mk_program():
    return {0: [
        {"exercise": "Barbell Back Squat", "sets": 4, "reps": "8",
         "weight": 165.0, "rest": "120s", "why": "x"},
        {"exercise": "Romanian Deadlift", "sets": 2, "reps": "10",
         "weight": 145.0, "rest": "90s", "why": "x"},
    ]}


def _rails(program, layoff_days):
    from coach_planning_program import enforce_safety, _movement_key
    hist_top = {_movement_key("Barbell Back Squat"): 165.0,
                _movement_key("Romanian Deadlift"): 145.0}
    return enforce_safety(
        program, rest_day_idx=6, ceiling=100,
        history_exercises=["Barbell Back Squat", "Romanian Deadlift"],
        history_max_weight=165.0, history_top=hist_top,
        prev_by_day=None, min_per_day=1, deload=False, floor=0,
        layoff_days=layoff_days,
    )


def test_long_layoff_caps_to_60pct(app_ctx):
    out, actions = _rails(_mk_program(), layoff_days=56)
    sq = out[0][0]
    # 165 * 0.60 = 99 -> rounded to 100
    assert sq["weight"] == 100
    assert any("layoff" in a.lower() for a in actions)
    rdl = out[0][1]
    assert rdl["weight"] == 85  # 145 * 0.6 = 87 -> 85


def test_moderate_layoff_caps_to_75pct(app_ctx):
    out, _ = _rails(_mk_program(), layoff_days=30)
    assert out[0][0]["weight"] == 125  # 165 * 0.75 = 123.75 -> 125
    assert out[0][1]["weight"] == 110  # 145 * 0.75 = 108.75 -> 110


def test_no_layoff_leaves_weights_alone(app_ctx):
    out, actions = _rails(_mk_program(), layoff_days=5)
    assert out[0][0]["weight"] == 165.0
    assert not any("layoff" in a.lower() for a in actions)


def test_long_layoff_cuts_volume_ceiling(app_ctx):
    from coach_planning_program import enforce_safety, _movement_key
    # 10 exercises x 4 sets = 40 sets against ceiling 30; layoff cuts the
    # ceiling to 18 (30 * 0.6) so sets must trim to <= 18.
    program = {0: [
        {"exercise": "Barbell Back Squat", "sets": 4, "reps": "8",
         "weight": 100.0, "rest": "120s", "why": "x"}
        for _ in range(10)]}
    hist_top = {_movement_key("Barbell Back Squat"): 165.0}
    out, _ = enforce_safety(
        program, rest_day_idx=6, ceiling=30,
        history_exercises=["Barbell Back Squat"], history_max_weight=165.0,
        history_top=hist_top, prev_by_day=None, min_per_day=1,
        deload=False, floor=0, layoff_days=56,
    )
    total = sum(it["sets"] for items in out.values() for it in items)
    assert total <= 18


def test_layoff_days_helper_reads_last_done_set(app_ctx):
    app_, db = app_ctx
    from models import User, SetLog
    from coach_planning_program import _layoff_days
    u = User.query.filter_by(email="layoff@test.com").first()
    if not u:
        u = User(email="layoff@test.com")
        db.session.add(u)
        db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    assert _layoff_days(u.id) is None  # no history at all
    db.session.add(SetLog(user_id=u.id, exercise_name="Barbell Back Squat",
                          week=25, day_idx=0, set_number=0, weight=165,
                          reps=8, done=True,
                          logged_date=date.today() - timedelta(days=56)))
    db.session.commit()
    assert _layoff_days(u.id) == 56
