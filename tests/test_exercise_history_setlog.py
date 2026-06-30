"""The coach's exercise_history must read SetLog (the live table), not the legacy
ExerciseLog (dead in prod since April). Bug (2026-06-29, coach-judge prog_001/003,
deload_003): asked "what did I hit on bench?", the coach answered "No logged bench
sets on file" while DB Bench Press sets were logged in SetLog — because
_build_exercise_history queried ExerciseLog, which the logging flow stopped
writing. today_sets already reads SetLog correctly; history must match.
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_exercise_history_surfaces_setlog_sessions(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import User, SetLog, ExerciseLog
    from flask_login import login_user
    u = User.query.filter_by(email="hist-setlog@test.com").first()
    if not u:
        u = User(email="hist-setlog@test.com")
        db.session.add(u); db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    ExerciseLog.query.filter_by(user_id=u.id).delete()  # legacy table stays EMPTY
    # Three logged bench sessions in SetLog (what the live flow writes), nothing
    # in ExerciseLog — exactly the prod/fixture shape.
    sessions = [
        (5, date(2026, 5, 4),  [(60, 6), (65, 5), (70, 5)]),
        (6, date(2026, 5, 11), [(65, 5), (70, 5), (72, 4)]),
        (7, date(2026, 5, 18), [(70, 5), (72, 4), (75, 4)]),  # most recent: top 75x4
    ]
    for wk, d, sets in sessions:
        for i, (w, reps) in enumerate(sets):
            db.session.add(SetLog(user_id=u.id, week=wk, day_idx=1, set_number=i,
                                  exercise_name="DB Bench Press", weight=w, reps=reps,
                                  done=True, logged_date=d))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        hist = ca._build_exercise_history()["exercise_history"]
    assert "DB Bench Press" in hist, f"bench history missing: {list(hist)}"
    entries = hist["DB Bench Press"]
    assert entries, "no sessions returned"
    # most recent session first, top set surfaced so the coach can cite "75x4"
    assert entries[0]["weight"] == 75
    assert entries[0]["reps_completed"] == 4
    assert len(entries) <= 3


def test_get_recent_sets_finds_equipment_variant(app_ctx):
    """The coach's get_recent_sets tool must find logged 'DB Bench Press' when it
    queries the archetype name 'Barbell Bench Press'. Substring matching is
    asymmetric ('%Barbell Bench Press%' isn't in 'DB Bench Press'), which made the
    coach answer 'no bench logged' (judge prog_001). A movement-key fallback
    bridges equipment variants of the same lift.
    """
    import json
    from app import db
    from models import User, SetLog
    import coach_tools as ct
    u = User.query.filter_by(email="toolvariant@test.com").first()
    if not u:
        u = User(email="toolvariant@test.com")
        db.session.add(u); db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    for i, (w, reps) in enumerate([(70, 5), (72, 4), (75, 4)]):
        db.session.add(SetLog(user_id=u.id, week=7, day_idx=1, set_number=i,
                              exercise_name="DB Bench Press", weight=w, reps=reps,
                              done=True, logged_date=date(2026, 5, 18)))
    db.session.commit()
    out = json.loads(ct._tool_get_recent_sets(u.id, "Barbell Bench Press"))
    assert len(out["sets"]) == 3, out.get("note")
    assert out["exercise"] == "DB Bench Press"  # surfaces what was actually logged
