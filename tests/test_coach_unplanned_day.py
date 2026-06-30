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


def test_resolver_strips_liftname_on_unplanned(app_ctx):
    """The resolver must blank the template lift NAME too, not just exercises —
    else it leaks through the workout summary and the claims table."""
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    u = _fresh_user(db, "unplanned-liftname@test.com")
    with app_.test_request_context():
        login_user(u, force=True)
        for d in range(7):
            r = ca._resolve_workout_for_day(1, d)
            if r and not r.get("isRest"):
                assert r.get("lift_unplanned") is True
                assert r.get("liftName") is None, r.get("liftName")
                return
        pytest.skip("no template lift day found")


def test_logged_workout_on_unplanned_day_is_not_rest_in_directive():
    """An unplanned day with LOGGED sets has workout_prescribed=False but state
    in_progress/complete — the directive must acknowledge the training, NOT emit
    'REST DAY' (the old `not workout_prescribed` check fired first)."""
    from coach_assembler import _format_today_status_block
    block = "\n".join(_format_today_status_block({
        "weekday": "Monday", "date": "2026-01-05",
        "workout_prescribed": False, "workout_unplanned": True,
        "workout_state": "in_progress", "workout_logged": True,
        "workout_logged_exercises": ["Barbell Back Squat"],
        "workout_remaining_exercises": ["Romanian Deadlift"],
        "sets_done": 2, "sets_logged": 4,
        "run_prescribed": None, "run_logged": False,
    })).lower()
    assert "rest day" not in block, block
    assert "in progress" in block, block


def test_coach_and_dashboard_agree_on_lift_planned_state(app_ctx):
    """Pin the coach (_resolve_workout_for_day.lift_unplanned) and the dashboard
    (/api/workouts liftStatus) together so the 'is this day planned' definition
    can't silently drift apart (review finding: two sources of truth). They
    legitimately differ on liftName handling, but MUST agree on planned/unplanned.
    """
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    from models import WeeklyPrescription
    u = _fresh_user(db, "agree@test.com")  # no prescriptions
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id); s["_fresh"] = True

    def _coach_unplanned(d):
        with app_.test_request_context():
            login_user(u, force=True)
            r = ca._resolve_workout_for_day(1, d)
        return bool(r and r.get("lift_unplanned"))

    def _dash_status(d):
        return client.get("/api/workouts").get_json()["1"]["days"][d].get("liftStatus")

    target = None
    for d in range(7):
        with app_.test_request_context():
            login_user(u, force=True)
            r = ca._resolve_workout_for_day(1, d)
        if r and not r.get("isRest"):
            target = d
            break
    assert target is not None, "no template lift day found"

    # UNPLANNED (no prescription): both must agree it's unplanned.
    assert _dash_status(target) == "unplanned"
    assert _coach_unplanned(target) is True

    # PLANNED (seed a coach prescription): both must agree it's planned.
    for i, n in enumerate(["Barbell Back Squat", "Romanian Deadlift"]):
        db.session.add(WeeklyPrescription(user_id=u.id, week=1, day_idx=target,
                                          exercise_order=i, exercise_name=n, sets=4,
                                          reps="8", rest="90s", source="coach"))
    db.session.commit()
    assert _dash_status(target) == "planned"
    assert _coach_unplanned(target) is False


def test_coach_rules_unplanned_does_not_prescribe_template(app_ctx):
    """coach_rules (the validated-pipeline path) must also treat a no-prescription
    day as unplanned: the summary carries lift_unplanned, the prefilled schedule
    says NOT PLANNED, and the directive offers to plan instead of 'Lift now {lift}'.
    """
    from datetime import datetime
    from flask_login import login_user
    import coach_rules as cr
    app_, db = app_ctx
    u = _fresh_user(db, "cr-unplanned@test.com")
    with app_.test_request_context():
        login_user(u, force=True)
        summ = None
        for d in range(7):
            s = cr._resolve_workout_for_day_summary(u.id, 1, d)
            if s and not s.is_rest:
                summ = s
                break
    assert summ is not None
    assert summ.lift_unplanned is True
    assert summ.lift_name == ""  # template name NOT leaked

    sched = cr._render_prefilled_schedule(
        now_local=datetime(2026, 1, 5, 10, 0), workout_today=summ,
        workout_today_scheduled_at=None, run_today=None,
        workout_tomorrow=None, workout_tomorrow_scheduled_at=None, run_tomorrow=None)
    sched_txt = sched if isinstance(sched, str) else "\n".join(sched)
    assert "Today workout: NOT PLANNED" in sched_txt

    d = cr._compute_directive(
        now_local=datetime(2026, 1, 5, 10, 0),
        workout_today=summ, workout_today_scheduled_at=None,
        workout_today_status="unplanned",
        run_today=None, run_today_status="none",
        workout_tomorrow=None, workout_tomorrow_scheduled_at=None, run_tomorrow=None,
        fasting_active=False, weekend_fast_active=False,
        is_pr_session=False, next_target_hint=None,
        refusal_required=False, phase_summary="Phase 1 (week 1)")
    assert "plan the week" in d.text.lower()
    assert "lift now" not in d.text.lower()


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
