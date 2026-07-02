"""A partially-logged workout must NOT be reported to the coach as DONE.

Erik's real failure (2026-06-06, wk10 Sat "Full Body"): he had ONE bench set
logged for today's slot and nothing on the other four prescribed exercises. The
assembler's today_status used a binary `workout_logged = any SetLog row exists`,
so the directive told the model "workout: DONE — the lift is FINISHED. Do NOT
prescribe it." The coach recited it: "Today's Full Body lift is already logged …
you're done lifting." False — he'd done 1 of ~15 sets, 1 of 5 exercises.

today_status must be three-state: not_started | in_progress | complete. Only a
genuinely finished session may say DONE: every prescribed exercise has its
prescribed number of sets PERFORMED (canonical name-aware check in
workout_status.workout_state_from_rows), or a same-day DayCompletion. The old
6-sets/3-done heuristic is gone — it marked partials complete. A partial log
says IN PROGRESS and must explicitly tell the model the lift is NOT finished
and what's still open.
"""
from datetime import date

import pytest


# ---------------------------------------------------------------------------
# Pure formatter — the exact text the model reads. No DB, no login.
# ---------------------------------------------------------------------------

def test_in_progress_block_does_not_tell_model_the_lift_is_finished():
    from coach_assembler import _format_today_status_block
    ts = {
        "weekday": "Saturday", "date": "2026-06-06",
        "workout_prescribed": True, "workout_state": "in_progress",
        "workout_logged": True,
        "workout_logged_exercises": ["Barbell Bench Press"],
        "workout_remaining_exercises": [
            "Cable Chest Fly", "Lateral Raise", "Ab Wheel Rollout", "Plank"],
        "sets_done": 1, "sets_logged": 3,
        "run_prescribed": "z2", "run_label": "Zone 2 Easy",
        "run_duration": "40 min", "run_logged": False,
    }
    block = "\n".join(_format_today_status_block(ts))
    low = block.lower()
    assert "in progress" in low, block
    # must explicitly negate "finished/done"
    assert "not finished" in low or "not done" in low, block
    # must instruct the model NOT to claim completion
    assert "do not" in low, block
    # surfaces what's still open so the coach can be honest
    assert "Cable Chest Fly" in block, block
    # and must NOT emit the unconditional DONE directive
    assert "the lift is FINISHED" not in block, block


def test_complete_block_says_done():
    from coach_assembler import _format_today_status_block
    ts = {
        "weekday": "Saturday", "date": "2026-06-06",
        "workout_prescribed": True, "workout_state": "complete",
        "workout_logged": True, "run_prescribed": None, "run_logged": False,
    }
    low = "\n".join(_format_today_status_block(ts)).lower()
    assert "done" in low or "finished" in low


def test_not_started_block_says_pending():
    from coach_assembler import _format_today_status_block
    ts = {
        "weekday": "Saturday", "date": "2026-06-06",
        "workout_prescribed": True, "workout_state": "not_started",
        "workout_logged": False, "run_prescribed": None, "run_logged": False,
    }
    low = "\n".join(_format_today_status_block(ts)).lower()
    assert "pending" in low


def test_rest_block_says_rest():
    from coach_assembler import _format_today_status_block
    ts = {
        "weekday": "Sunday", "date": "2026-06-07",
        "workout_prescribed": False, "workout_state": "rest",
        "workout_logged": False, "run_prescribed": None, "run_logged": False,
    }
    low = "\n".join(_format_today_status_block(ts)).lower()
    assert "rest" in low


# ---------------------------------------------------------------------------
# State computation — real DB + login, mirrors Erik's exact partial log.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login_fresh_user(db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    return u


def _seed_coach_rx(db, uid, week, day_idx, names):
    """Seed a real COACH prescription for the slot. Required now that the coach
    no longer falls back to the static template (coach-or-nothing): a day with no
    prescription is 'unplanned', not a prescribed workout."""
    from models import WeeklyPrescription
    WeeklyPrescription.query.filter_by(user_id=uid, week=week, day_idx=day_idx).delete()
    for i, n in enumerate(names):
        db.session.add(WeeklyPrescription(
            user_id=uid, week=week, day_idx=day_idx, exercise_order=i,
            exercise_name=n, sets=4, reps="8", rest="90s", source="coach"))
    db.session.commit()


def test_build_today_status_in_progress_on_partial_log(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import User, SetLog, DayCompletion
    from flask_login import login_user
    # Apr 30 2026 is a Thursday (weekday 3) — phase-2 multi-exercise lift day.
    today = date(2026, 4, 30)
    assert today.weekday() == 3
    with app_.test_request_context():
        u = _login_fresh_user(db, "partial-progress@test.com")
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: 5)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        _seed_coach_rx(db, u.id, 5, 3, ["Barbell Bench Press", "Incline DB Press"])
        resolved = ca._resolve_workout_for_day(5, 3)  # post equipment-swap names
        names = [e.get("name") for e in (resolved or {}).get("exercises", []) if e.get("name")]
        assert len(names) >= 2, resolved
        # wipe slot, then log ONLY the first exercise (one done set) — a partial
        SetLog.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        DayCompletion.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        db.session.add(SetLog(user_id=u.id, week=5, day_idx=3,
                              exercise_name=names[0], set_number=0,
                              weight=100, reps=5, done=True, logged_date=today))
        db.session.commit()
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "in_progress", ts
        assert names[0] in (ts.get("workout_logged_exercises") or [])
        assert names[1] in (ts.get("workout_remaining_exercises") or [])


def test_build_today_status_complete_when_all_prescribed_sets_done(app_ctx, monkeypatch):
    # UPDATED for the canonical 3-state contract: "one set logged per exercise"
    # no longer reads complete — EVERY prescribed exercise needs its prescribed
    # number of sets performed (here 4 each, per _seed_coach_rx).
    app_, db = app_ctx
    import coach_assembler as ca
    from models import User, SetLog, DayCompletion
    from flask_login import login_user
    today = date(2026, 4, 30)
    with app_.test_request_context():
        u = _login_fresh_user(db, "complete-day@test.com")
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: 5)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        _seed_coach_rx(db, u.id, 5, 3, ["Barbell Bench Press", "Incline DB Press"])
        resolved = ca._resolve_workout_for_day(5, 3)  # post equipment-swap names
        names = [e.get("name") for e in (resolved or {}).get("exercises", []) if e.get("name")]
        SetLog.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        DayCompletion.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        for n in names:  # every prescribed exercise: ALL 4 prescribed sets done
            for sn in range(4):
                db.session.add(SetLog(user_id=u.id, week=5, day_idx=3,
                                      exercise_name=n, set_number=sn,
                                      weight=100, reps=5, done=True, logged_date=today))
        db.session.commit()
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "complete", ts


def test_build_today_status_in_progress_when_every_exercise_touched_but_sets_short(app_ctx, monkeypatch):
    # One done set on each prescribed exercise (4 prescribed each) is a PARTIAL
    # session — the old code called this complete. Must read in_progress.
    app_, db = app_ctx
    import coach_assembler as ca
    from models import User, SetLog, DayCompletion
    from flask_login import login_user
    today = date(2026, 4, 30)
    with app_.test_request_context():
        u = _login_fresh_user(db, "touched-not-done@test.com")
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: 5)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        _seed_coach_rx(db, u.id, 5, 3, ["Barbell Bench Press", "Incline DB Press"])
        resolved = ca._resolve_workout_for_day(5, 3)
        names = [e.get("name") for e in (resolved or {}).get("exercises", []) if e.get("name")]
        SetLog.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        DayCompletion.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        for n in names:  # only ONE of the 4 prescribed sets per exercise
            db.session.add(SetLog(user_id=u.id, week=5, day_idx=3,
                                  exercise_name=n, set_number=0,
                                  weight=100, reps=5, done=True, logged_date=today))
        db.session.commit()
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "in_progress", ts


def test_build_today_status_not_started_when_slot_sets_are_from_an_earlier_date(app_ctx, monkeypatch):
    """Erik's real failure (2026-06-29): the 12-week program ended June 21, so
    _current_week() clamps at 12 forever. On a later Monday (day_idx 0) the
    workout-done check queried SetLog by (week=12, day_idx=0) ONLY — with no date
    filter — and found his June 15 Monday session, then reported today as DONE.
    He had logged NOTHING today. A set logged on a prior calendar date must never
    count as today's workout. Mirror the run side, which already filters on date.
    """
    app_, db = app_ctx
    import coach_assembler as ca
    from models import User, SetLog, DayCompletion
    from flask_login import login_user
    today = date(2026, 6, 29)        # Monday — calendar is past the 12-week block
    assert today.weekday() == 0
    earlier = date(2026, 6, 15)      # the week-12 Monday he actually trained
    with app_.test_request_context():
        u = _login_fresh_user(db, "stale-slot@test.com")
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: 12)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        names = ["Barbell Back Squat", "Romanian Deadlift"]
        _seed_coach_rx(db, u.id, 12, 0, names)
        SetLog.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
        DayCompletion.query.filter_by(user_id=u.id, week=12, day_idx=0).delete()
        for n in names:  # a FULLY logged session — but on an EARLIER date
            db.session.add(SetLog(user_id=u.id, week=12, day_idx=0,
                                  exercise_name=n, set_number=0,
                                  weight=100, reps=5, done=True, logged_date=earlier))
        db.session.commit()
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "not_started", ts
        assert ts["sets_logged"] == 0, ts
        assert ts["workout_logged"] is False, ts


def test_build_today_status_not_started_when_nothing_logged(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import User, SetLog, DayCompletion
    from flask_login import login_user
    today = date(2026, 4, 30)
    with app_.test_request_context():
        u = _login_fresh_user(db, "not-started@test.com")
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: 5)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        _seed_coach_rx(db, u.id, 5, 3, ["Barbell Bench Press", "Incline DB Press"])
        SetLog.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        DayCompletion.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        db.session.commit()
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "not_started", ts
