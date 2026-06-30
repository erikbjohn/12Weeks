"""C5 — the DURABLE phantom-done fix: a stale DayCompletion.done from a prior
cycle must never read as 'complete today'.

Erik caught this 2026-06-29: the program clamps the week at 12 once the block
ends, so a later Monday re-found the week-12 Monday's done-flag and reported the
workout DONE when nothing was logged that day. The earlier slot_sets date-filter
only saved the ZERO-log case; once one set is logged on the clamped day, slot_sets
is non-empty and the bare dc.done short-circuited to 'complete' (the critic's
catch). Fix: dc.done is honored only when its recorded completed_at date == today,
in BOTH engines (coach_assembler._build_today_status, coach_rules._compute_workout_status).
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _user(db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    return u


# ---- coach_rules._compute_workout_status -----------------------------------------

def test_stale_daycompletion_without_sets_today_is_not_complete(app_ctx):
    app_, db = app_ctx
    from models import SetLog, DayCompletion
    import coach_rules as cr
    u = _user(db, "phantom-rules@test.com")
    today = date(2026, 6, 29)
    SetLog.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
    DayCompletion.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
    # done-flag recorded TWO WEEKS AGO; nothing logged today.
    db.session.add(DayCompletion(user_id=u.id, week=12, day_idx=0, done=True,
                                 completed_at=(today - timedelta(days=14)).isoformat()))
    db.session.commit()
    assert cr._compute_workout_status(u.id, 12, 0, today, is_rest=False) == "not_started"


def test_daycompletion_completed_today_is_complete(app_ctx):
    app_, db = app_ctx
    from models import SetLog, DayCompletion
    import coach_rules as cr
    u = _user(db, "phantom-rules-today@test.com")
    today = date(2026, 6, 29)
    SetLog.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
    DayCompletion.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
    db.session.add(DayCompletion(user_id=u.id, week=12, day_idx=0, done=True,
                                 completed_at=today.isoformat()))
    db.session.commit()
    assert cr._compute_workout_status(u.id, 12, 0, today, is_rest=False) == "complete"


# ---- coach_assembler._build_today_status -----------------------------------------

def test_assembler_partial_log_with_stale_daycompletion_is_in_progress(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import SetLog, DayCompletion
    from flask_login import login_user
    today = date(2026, 6, 29)  # Monday, clamped week 12
    assert today.weekday() == 0
    with app_.test_request_context():
        u = _user(db, "phantom-asm@test.com")
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: 12)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        resolved = ca._resolve_workout_for_day(12, 0)
        names = [e.get("name") for e in (resolved or {}).get("exercises", []) if e.get("name")]
        assert len(names) >= 2, f"need a multi-exercise day: {resolved}"
        SetLog.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
        DayCompletion.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
        # stale done-flag (14 days old) + ONE exercise logged TODAY -> partial.
        db.session.add(DayCompletion(user_id=u.id, week=12, day_idx=0, done=True,
                                     completed_at=(today - timedelta(days=14)).isoformat()))
        db.session.add(SetLog(user_id=u.id, week=12, day_idx=0, exercise_name=names[0],
                              set_number=0, weight=100, reps=5, done=True, logged_date=today))
        db.session.commit()
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "in_progress", ts
