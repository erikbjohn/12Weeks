"""SetLog-based lift history — the replacement for stale ExerciseLog reads on
dashboards/charts/e1RM. Must surface logged sessions, compute Epley e1RM, and
match equipment variants (logged 'DB Bench Press' answers 'Barbell Bench Press').
"""
from datetime import date

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _seed(db, email, exercise, sessions):
    from models import User, SetLog
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    for wk, d, sets in sessions:
        for i, (w, reps) in enumerate(sets):
            db.session.add(SetLog(user_id=u.id, week=wk, day_idx=1, set_number=i,
                                  exercise_name=exercise, weight=w, reps=reps,
                                  done=True, logged_date=d))
    db.session.commit()
    return u


def test_history_is_chronological_with_top_set_and_e1rm(app_ctx):
    _, db = app_ctx
    from lift_history import lift_session_history
    u = _seed(db, "lh-1@test.com", "Barbell Back Squat", [
        (5, date(2026, 5, 4),  [(135, 5), (145, 5), (155, 4)]),
        (6, date(2026, 5, 11), [(145, 5), (155, 5), (165, 3)]),
    ])
    h = lift_session_history(u.id, "Barbell Back Squat")
    assert [e["week"] for e in h] == [5, 6]            # oldest first
    assert h[0]["top_weight"] == 155 and h[0]["top_reps"] == 4
    assert h[1]["top_weight"] == 165
    # Epley: 165 * (1 + 3/30) = 181.5
    assert h[1]["e1rm"] == 181.5
    assert h[1]["sets"] == 3


def test_matches_equipment_variant_by_movement(app_ctx):
    _, db = app_ctx
    from lift_history import lift_session_history
    u = _seed(db, "lh-2@test.com", "DB Bench Press", [
        (7, date(2026, 5, 18), [(70, 5), (75, 4)]),
    ])
    # query the archetype/barbell name -> still finds the logged DB variant
    h = lift_session_history(u.id, "Barbell Bench Press")
    assert len(h) == 1 and h[0]["top_weight"] == 75
    assert h[0]["exercise_name"] == "DB Bench Press"


def test_limit_sessions_keeps_most_recent(app_ctx):
    _, db = app_ctx
    from lift_history import lift_session_history
    u = _seed(db, "lh-3@test.com", "Barbell OHP", [
        (1, date(2026, 4, 6),  [(65, 5)]),
        (2, date(2026, 4, 13), [(70, 5)]),
        (3, date(2026, 4, 20), [(75, 5)]),
    ])
    h = lift_session_history(u.id, "Barbell OHP", limit_sessions=2)
    assert [e["week"] for e in h] == [2, 3]
