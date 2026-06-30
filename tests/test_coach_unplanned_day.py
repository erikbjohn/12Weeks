"""The coach must respect coach-or-nothing on UNPLANNED days, like the dashboard.

Bug (2026-06-29, found by driving the app): on a day with NO prescription, the
EXERCISE card shows "your coach hasn't planned these lifts yet / Plan this week"
(plan_overlay.finalize_day_plan strips the static template). But the coach's
_resolve_workout_for_day fell back to the RAW TEMPLATE and the coach narrated those
exercises as the athlete's prescription — contradicting the card and violating
no-static-fallback. Erik plans week-by-week, so unplanned weeks are normal.

Fix: _resolve_workout_for_day strips template exercises and flags lift_unplanned
when no prescription exists; _build_today_status reports workout_state='unplanned'
(not 'not_started'/'rest') and workout_prescribed=False so the coach offers to plan
instead of describing template lifts.
"""
from datetime import date

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _fresh_user(db, email):
    from models import User, WeeklyPrescription
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    WeeklyPrescription.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return u


def test_resolver_strips_template_on_unplanned_lift_day(app_ctx):
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    u = _fresh_user(db, "unplanned-resolve@test.com")
    with app_.test_request_context():
        login_user(u, force=True)
        res = ca._resolve_workout_for_day(1, 0)  # week 1 Mon: a template lift day, no rx
        assert res is not None
        if not res.get("isRest"):
            assert res.get("lift_unplanned") is True
            assert len(res.get("exercises") or []) == 0, res.get("exercises")


def test_today_status_unplanned_when_no_prescription(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    u = _fresh_user(db, "unplanned-status@test.com")
    with app_.test_request_context():
        login_user(u, force=True)
        # find a non-rest template day so the test is meaningful
        target_day = None
        for d in range(7):
            r = ca._resolve_workout_for_day(1, d)
            if r and not r.get("isRest"):
                target_day = d
                break
        assert target_day is not None, "no template lift day found"
        monkeypatch.setattr(ca, "_current_week", lambda: 1)
        monkeypatch.setattr(ca, "_user_today",
                            lambda: date(2026, 1, 5) + __import__("datetime").timedelta(days=target_day))
        ts = ca._build_today_status()["today_status"]
        assert ts["workout_state"] == "unplanned", ts
        assert ts["workout_prescribed"] is False, ts


def test_unplanned_directive_tells_coach_to_plan_not_prescribe():
    from coach_assembler import _format_today_status_block
    block = "\n".join(_format_today_status_block({
        "weekday": "Monday", "date": "2026-01-05",
        "workout_prescribed": False, "workout_state": "unplanned",
        "workout_logged": False, "run_prescribed": None, "run_logged": False,
    })).lower()
    assert "not" in block and ("plan" in block or "unplanned" in block)
    # must NOT assert a workout is done or prescribe specific lifts
    assert "the lift is finished" not in block
