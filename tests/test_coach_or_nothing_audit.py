"""Coach-or-nothing regression tests — 2026-07-01 whole-app audit, theme 3.

The static PHASE templates are the coach's INPUT scaffold, never the user's
plan. These tests pin the audit fixes:

  1. /api/prescription/seed no longer writes PHASE_TEMPLATES rows (the client
     called it on every load, silently converting an unplanned week into a
     'planned' template week).
  2. finalize_day_plan strips the template liftName (not just exercises) on
     unplanned days — matching the coach-side resolver.
  3. exercise_analysis is EMPTY for an unplanned week (no dead-ExerciseLog +
     live-engine fallback).
  4. The coach resolver strips the template RUN when no WeeklyRunPlan row
     exists (the lift side was already fixed; the run side leaked).
  5. coach_rules directives never emit garbled text ('Done. Tomorrow:  at
     6 AM.', 'Continue. Finish .') when a day is unplanned.
  6. /api/shopping-list returns an empty unplanned list instead of aggregating
     template meals.
  7. /api/workouts flags the meal domain unplanned when no WeeklyMealPlan rows
     exist (was hardcoded has_mealplan=True).
  8. weekly_report adherence uses the user's actual planned training days,
     not a hardcoded 6.
"""
from datetime import date, datetime

import pytest


# NOTE: unlike some sibling test modules, this fixture does NOT hold an app
# context open across the whole module. Flask REUSES an already-active app
# context for test-client requests, so `g._login_user` (and the SQLAlchemy
# session) leak between clients of different users — client B silently runs
# as user A. Each helper opens and closes its own context instead.
@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _fresh_user(db, email):
    """Create (or reset) a user inside a short-lived app context.
    Returns the user ID (int) — not the ORM object, which would be detached."""
    from app import app
    from models import (User, WeeklyPrescription, WeeklyRunPlan, WeeklyMealPlan,
                        WeeklyDaySchedule, DayCompletion, ExerciseLog)
    with app.app_context():
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u); db.session.commit()
        for model in (WeeklyPrescription, WeeklyRunPlan, WeeklyMealPlan,
                      WeeklyDaySchedule, DayCompletion, ExerciseLog):
            model.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id


def _add_rows(db, rows):
    from app import app
    with app.app_context():
        for r in rows:
            db.session.add(r)
        db.session.commit()


def _client_for(app_, uid):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    return client


def _login(uid):
    """Log the user in inside the CURRENT request context (fetch by id so the
    object is session-bound)."""
    from flask_login import login_user
    from models import User
    u = User.query.get(uid)
    login_user(u, force=True)


# ── 1. seed endpoint is a no-op ──────────────────────────────────────────

def test_seed_endpoint_never_creates_template_prescriptions(app_ctx):
    from models import WeeklyPrescription
    app_, db = app_ctx
    uid = _fresh_user(db, "seed-noop@test.com")
    client = _client_for(app_, uid)
    res = client.post("/api/prescription/seed", json={"week": 12})
    assert res.status_code == 200
    body = res.get_json()
    assert body.get("seeded") == 0
    with app_.app_context():
        rows = WeeklyPrescription.query.filter_by(user_id=uid, week=12).count()
    assert rows == 0, "seed endpoint must NOT write template prescriptions"
    # And the dashboard still shows the week as unplanned.
    wk = client.get("/api/workouts").get_json()["12"]["days"]
    for d in wk:
        assert d.get("liftStatus") in ("unplanned", "rest"), d


# ── 2. finalize_day_plan strips the template liftName ────────────────────

def test_finalize_strips_template_liftname_on_unplanned_day():
    from plan_overlay import finalize_day_plan
    day = {
        "liftName": "Upper A - Chest & Back",
        "isRest": False,
        "exercises": [{"name": "Front Squat", "sets": "4x8"}],
    }
    finalize_day_plan(day, has_prescriptions=False, has_runplan=False,
                      has_mealplan=False)
    assert day["liftStatus"] == "unplanned"
    assert day["liftName"] is None, "template workout NAME must not be served"


def test_finalize_keeps_liftname_when_planned():
    from plan_overlay import finalize_day_plan
    day = {"liftName": "Upper A", "isRest": False,
           "exercises": [{"name": "Bench", "sets": "4x8"}]}
    finalize_day_plan(day, has_prescriptions=True, has_runplan=True,
                      has_mealplan=True)
    assert day["liftName"] == "Upper A"


# ── 3. exercise_analysis empty on unplanned week ─────────────────────────

def test_exercise_analysis_empty_without_prescriptions(app_ctx):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import ExerciseLog
    uid = _fresh_user(db, "analysis-empty@test.com")
    # Even with legacy ExerciseLog rows on file, no engine targets may be
    # synthesized for a week with no prescriptions.
    _add_rows(db, [ExerciseLog(user_id=uid, exercise_name="Barbell Bench Press",
                               weight=145, logged_date=date(2026, 4, 1))])
    with app_.test_request_context():
        _login(uid)
        out = ca._build_exercise_analysis()["exercise_analysis"]
    assert out == {}, ("unplanned week must yield EMPTY analysis — no "
                       "ExerciseLog/engine fallback: %r" % out)


# ── 4. resolver strips the template run ──────────────────────────────────

def test_resolver_strips_template_run_when_no_runplan(app_ctx):
    app_, db = app_ctx
    import coach_assembler as ca
    uid = _fresh_user(db, "run-strip@test.com")
    with app_.test_request_context():
        _login(uid)
        for d in range(7):
            r = ca._resolve_workout_for_day(1, d)
            assert r is not None
            assert r.get("run") is None, (
                f"day {d}: template run leaked to the coach: {r.get('run')}")


def test_resolver_overlays_real_runplan(app_ctx):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import WeeklyRunPlan
    uid = _fresh_user(db, "run-overlay@test.com")
    _add_rows(db, [WeeklyRunPlan(user_id=uid, week=1, day_idx=2,
                                 run_type="z2", label="Zone 2 easy",
                                 duration="35 min", detail="HR under 140")])
    with app_.test_request_context():
        _login(uid)
        r = ca._resolve_workout_for_day(1, 2)
    assert r.get("run") == {"type": "z2", "label": "Zone 2 easy",
                            "time": "35 min", "detail": "HR under 140"}


def test_today_status_run_not_prescribed_without_runplan(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    uid = _fresh_user(db, "run-status@test.com")
    with app_.test_request_context():
        _login(uid)
        monkeypatch.setattr(ca, "_current_week", lambda: 1)
        monkeypatch.setattr(ca, "_user_today", lambda: date(2026, 1, 7))
        ts = ca._build_today_status()["today_status"]
    assert ts["run_prescribed"] is None, ts
    assert ts["run_label"] is None, ts


# ── 5. coach_rules directives never garble unplanned days ────────────────

def _mk_directive(**overrides):
    import coach_rules as cr
    kw = dict(
        now_local=datetime(2026, 1, 4, 19, 0),  # Sunday 7 PM
        workout_today=None, workout_today_scheduled_at=None,
        workout_today_status="rest",
        run_today=None, run_today_status="rest",
        workout_tomorrow=None, workout_tomorrow_scheduled_at=None,
        run_tomorrow=None,
        fasting_active=False, weekend_fast_active=False,
        is_pr_session=False, next_target_hint=None,
        refusal_required=False, phase_summary="Phase 1 (week 1)",
    )
    kw.update(overrides)
    return cr._compute_directive(**kw)


def test_rule11_tomorrow_unplanned_not_garbled():
    from coach_rules import WorkoutSummary, RunSummary
    unplanned = WorkoutSummary(lift_name="", exercise_names=[], is_rest=False,
                               lift_unplanned=True)
    d = _mk_directive(
        workout_today=WorkoutSummary("Upper A", ["Bench"], False),
        workout_today_status="complete",
        run_today=RunSummary("z2", "Zone 2", None, ""),
        run_today_status="logged",
        workout_tomorrow=unplanned,
    )
    assert "Tomorrow:  at" not in d.text, d.text
    assert "plan" in d.text.lower(), d.text


def test_rule2_in_progress_on_unplanned_day_not_garbled():
    from coach_rules import WorkoutSummary
    unplanned = WorkoutSummary(lift_name="", exercise_names=[], is_rest=False,
                               lift_unplanned=True)
    d = _mk_directive(workout_today=unplanned,
                      workout_today_status="in_progress")
    assert "Finish ." not in d.text, d.text


def test_rule13_sunday_eve_unplanned_monday():
    from coach_rules import WorkoutSummary
    unplanned = WorkoutSummary(lift_name="", exercise_names=[], is_rest=False,
                               lift_unplanned=True)
    d = _mk_directive(workout_tomorrow=unplanned)
    assert "Monday:  at" not in d.text, d.text


def test_prefilled_schedule_tomorrow_unplanned():
    import coach_rules as cr
    from coach_rules import WorkoutSummary
    unplanned = WorkoutSummary(lift_name="", exercise_names=[], is_rest=False,
                               lift_unplanned=True)
    sched = cr._render_prefilled_schedule(
        now_local=datetime(2026, 1, 4, 19, 0),
        workout_today=None, workout_today_scheduled_at=None, run_today=None,
        workout_tomorrow=unplanned, workout_tomorrow_scheduled_at=None,
        run_tomorrow=None)
    assert "Tomorrow workout: NOT PLANNED" in sched, sched


# ── 6. shopping list ─────────────────────────────────────────────────────

def test_shopping_list_empty_without_coach_meals(app_ctx):
    app_, db = app_ctx
    uid = _fresh_user(db, "shop-unplanned@test.com")
    client = _client_for(app_, uid)
    body = client.get("/api/shopping-list").get_json()
    assert body["categories"] == [], "template meals must not become a grocery list"
    assert body.get("unplanned") is True


# ── 7. meal domain unplanned in /api/workouts ────────────────────────────

def test_api_workouts_meals_unplanned_without_mealplan_rows(app_ctx):
    app_, db = app_ctx
    uid = _fresh_user(db, "meals-unplanned@test.com")
    client = _client_for(app_, uid)
    days = client.get("/api/workouts").get_json()["1"]["days"]
    for d in days:
        assert d.get("mealStatus") == "unplanned", d.get("mealStatus")
        assert d.get("mealPlan") is None, "template mealPlan leaked"


def test_api_workouts_meals_planned_with_mealplan_row(app_ctx):
    from models import WeeklyMealPlan
    app_, db = app_ctx
    uid = _fresh_user(db, "meals-planned@test.com")
    _add_rows(db, [WeeklyMealPlan(
        user_id=uid, week=1, day_idx=0,
        meal_data={"label": "cut", "targetCal": 1800, "meals": []})])
    client = _client_for(app_, uid)
    days = client.get("/api/workouts").get_json()["1"]["days"]
    assert days[0].get("mealStatus") == "planned"
    assert days[1].get("mealStatus") == "unplanned"


# ── 8. weekly report adherence uses the real planned-day count ───────────

def test_weekly_report_adherence_uses_planned_days(app_ctx):
    from models import WeeklyDaySchedule, DayCompletion
    from weekly_report import compute_weekly_metrics
    app_, db = app_ctx
    uid = _fresh_user(db, "report-adherence@test.com")
    # Coach designed a 5-training-day week (2 rest days).
    rows = [WeeklyDaySchedule(user_id=uid, week=3, day_idx=i,
                              lift_name=None if i >= 5 else f"Day {i}",
                              is_rest=(i >= 5))
            for i in range(7)]
    rows += [DayCompletion(user_id=uid, week=3, day_idx=i, done=True)
             for i in range(5)]
    _add_rows(db, rows)
    with app_.app_context():
        m = compute_weekly_metrics(3, user_id=uid)
    assert m["workouts_total"] == 5
    assert m["adherence_pct"] == 100, m


def test_weekly_report_no_plan_yields_no_denominator(app_ctx):
    from weekly_report import compute_weekly_metrics
    app_, db = app_ctx
    uid = _fresh_user(db, "report-noplan@test.com")
    with app_.app_context():
        m = compute_weekly_metrics(7, user_id=uid)
    assert m["workouts_total"] is None
    assert m["adherence_pct"] is None
