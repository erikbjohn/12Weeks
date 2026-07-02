"""Coach-guard regression tests — 2026-07-01 whole-app audit, theme 9a.

Pins the fixes for:
  1. coach_tools._tool_get_today_status queries 'today' in the USER's local
     timezone (SetLog/RunLog are written with user-local dates) — server-UTC
     date.today() made the coach see an empty/wrong 'today' every evening.
  2. lift_history.lift_session_history counts ONLY performed sets
     (done=True, not skipped) — a weight typed but never lifted is not a PR.
  3. Derivation validation actually computes the arithmetic: "A op B = C"
     with cited inputs no longer whitelists a fabricated C.
  4. Predicate mis-attribution: "you're at 185" citing the TARGET claim is a
     violation even though the number matches the cited value.
  5. _build_today_sets is date-gated: once _current_week clamps at 12, a
     prior cycle's same-slot sets can't render as "TODAY'S SETS".
  6. cut_status weekly deficit counts only days with meals actually logged —
     no more full-compliance fabricated deficit (the old filter was a
     tautology and intake_by_day was never read).
  7. classifier routes "romanian deadlift" to Romanian Deadlift history, not
     Conventional Deadlift.
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _fresh_user(db, email, timezone=None):
    from app import app
    from models import (User, SetLog, RunLog, WeeklyPrescription,
                        WeeklyMealPlan, MealLog, TrainingGoal, BodyWeight)
    with app.app_context():
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u); db.session.commit()
        if timezone is not None:
            u.timezone = timezone
        for model in (SetLog, RunLog, WeeklyPrescription, WeeklyMealPlan,
                      MealLog, TrainingGoal, BodyWeight):
            model.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id


def _login(uid):
    from flask_login import login_user
    from models import User
    login_user(User.query.get(uid), force=True)


# ── 1. tool 'today' is user-local, not server-UTC ─────────────────────────

def test_tool_today_status_uses_user_local_date(app_ctx):
    from app import app
    from models import SetLog
    from utils_time import user_local_today
    import json
    # UTC+14 — maximally likely to differ from the server's date, proving the
    # tool anchors on the USER's calendar, not the server's.
    uid = _fresh_user(app_ctx[1], "tz-today@test.com", timezone="Pacific/Kiritimati")
    local_today = user_local_today("Pacific/Kiritimati")
    with app.app_context():
        db = app_ctx[1]
        db.session.add(SetLog(user_id=uid, exercise_name="Barbell Bench Press",
                              week=1, day_idx=local_today.weekday(), set_number=0,
                              weight=155, reps=5, done=True,
                              logged_date=local_today))
        db.session.commit()
        from coach_tools import _tool_get_today_status
        data = json.loads(_tool_get_today_status(uid))
    assert data["date"] == str(local_today), (
        "tool 'today' must be the user's local date, not server date.today()")
    assert data["weekday"] == local_today.strftime("%A")
    assert "Barbell Bench Press" in data["logged_exercises"], (
        "a set logged on the user-local 'today' must be visible to the coach")


# ── 2. lift history counts only performed sets ────────────────────────────

def test_lift_history_ignores_undone_and_skipped_sets(app_ctx):
    from app import app
    from models import SetLog
    from lift_history import lift_session_history
    uid = _fresh_user(app_ctx[1], "lh-done@test.com")
    d = date(2026, 6, 22)
    with app.app_context():
        db = app_ctx[1]
        rows = [
            # performed set — the only legitimate history
            dict(set_number=0, weight=135, reps=5, done=True, set_skipped=False),
            # typed 185 into the input, never completed (blur-save shape)
            dict(set_number=1, weight=185, reps=5, done=False, set_skipped=False),
            # explicitly skipped
            dict(set_number=2, weight=200, reps=3, done=True, set_skipped=True),
        ]
        for r in rows:
            db.session.add(SetLog(user_id=uid, exercise_name="Barbell Bench Press",
                                  week=10, day_idx=0, logged_date=d, **r))
        db.session.commit()
        h = lift_session_history(uid, "Barbell Bench Press")
    assert len(h) == 1
    assert h[0]["top_weight"] == 135, (
        "an un-completed (done=False) or skipped set must never become the "
        "session top set / e1RM")
    assert h[0]["sets"] == 1


# ── 3. derivation arithmetic is actually computed ─────────────────────────

def test_fact_check_rejects_wrong_inline_math():
    from coach_multi_agent import _verify_response_numbers
    src = "current weight 207.2 lb, target 185 lb"
    # fabricated result with cited-looking inputs
    assert "15" in _verify_response_numbers("207.2 - 185 = 15.0 lb to go.", src)
    # correct math passes
    assert _verify_response_numbers("207.2 - 185 = 22.2 lb to go.", src) == []
    # result rounded to its displayed precision passes
    assert _verify_response_numbers("207.2 - 185 = 22 lb to go.", src) == []


def test_cite_validation_rejects_wrong_inline_math():
    from coach_claims import Claim
    from coach_validator import validate_cited_response
    claims = [
        Claim("body.weight.current", "athlete.current_weight_lb", 207.2, "BodyWeight#1"),
        Claim("body.weight.target", "athlete.target_weight_lb", 185.0, "TrainingGoal#1"),
    ]
    bad = {"lead": {"text": "You're at 207.2, target 185. 207.2 - 185 = 15.0 lb to go.",
                    "cites": ["body.weight.current", "body.weight.target"]}}
    violations = validate_cited_response(bad, claims)
    assert any("15" in v.message for v in violations), (
        "a derivation whose result is NOT a op b must stay a violation")
    good = {"lead": {"text": "You're at 207.2, target 185. 207.2 - 185 = 22.2 lb to go.",
                     "cites": ["body.weight.current", "body.weight.target"]}}
    assert validate_cited_response(good, claims) == []


# ── 4. predicate mis-attribution (right number, wrong fact) ───────────────

def test_predicate_mismatch_current_phrasing_backed_by_target_claim():
    from coach_claims import Claim
    from coach_validator import validate_cited_response
    claims = [
        Claim("body.weight.current", "athlete.current_weight_lb", 207.2, "BodyWeight#1"),
        Claim("body.weight.target", "athlete.target_weight_lb", 185.0, "TrainingGoal#1"),
    ]
    resp = {"lead": {"text": "You're at 185 right now — hold calories.",
                     "cites": ["body.weight.target"]}}
    violations = validate_cited_response(resp, claims)
    assert any(v.kind == "predicate_mismatch" for v in violations), (
        "'you're at <target value>' citing the target claim is the wrong fact")
    # Correct attribution stays clean.
    ok = {"lead": {"text": "Target is 185.", "cites": ["body.weight.target"]}}
    assert validate_cited_response(ok, claims) == []


# ── 5. TODAY'S SETS is date-gated ─────────────────────────────────────────

def test_today_sets_excludes_prior_cycle_same_slot(app_ctx):
    from app import app
    from models import SetLog
    import coach_assembler
    uid = _fresh_user(app_ctx[1], "today-sets@test.com")
    with app.test_request_context("/"):
        _login(uid)
        db = app_ctx[1]
        today = coach_assembler._user_today()
        week = coach_assembler._current_week()
        stale = today - timedelta(days=21)  # prior cycle, SAME (week, day_idx)
        db.session.add(SetLog(user_id=uid, exercise_name="Barbell Back Squat",
                              week=week, day_idx=today.weekday(), set_number=0,
                              weight=225, reps=5, done=True, logged_date=stale))
        db.session.add(SetLog(user_id=uid, exercise_name="Barbell Back Squat",
                              week=week, day_idx=today.weekday(), set_number=1,
                              weight=135, reps=5, done=True, logged_date=today))
        db.session.commit()
        out = coach_assembler._build_today_sets()["today_sets"]
    sets = out.get("Barbell Back Squat", [])
    weights = [s["weight"] for s in sets]
    assert 135 in weights
    assert 225 not in weights, (
        "a prior cycle's set in the same (week, day_idx) slot must not render "
        "as TODAY'S SETS after the week clamps")


# ── 6. cut deficit counts only days with meals actually logged ────────────

def test_cut_deficit_none_when_no_meals_logged(app_ctx):
    from app import app
    from models import TrainingGoal, WeeklyMealPlan, BodyWeight
    import coach_assembler
    uid = _fresh_user(app_ctx[1], "cut-deficit@test.com")
    with app.test_request_context("/"):
        _login(uid)
        db = app_ctx[1]
        today = coach_assembler._user_today()
        week = coach_assembler._current_week()
        db.session.add(TrainingGoal(user_id=uid, goal_type="cut",
                                    target_weight=185, daily_calories=1700,
                                    tdee=3000))
        db.session.add(BodyWeight(user_id=uid, weight_lbs=207.2, log_date=today))
        for d in range(7):
            db.session.add(WeeklyMealPlan(user_id=uid, week=week, day_idx=d,
                                          meal_data={}, daily_calories=1700))
        db.session.commit()
        cs = coach_assembler._build_cut_status()["cut_status"]
    assert cs["weekly_deficit_estimate"] is None, (
        "zero meals logged must yield NO deficit estimate — the old tautology "
        "fabricated a full-compliance 7-day deficit")
    assert cs["deficit_days_logged"] == 0


def test_cut_deficit_counts_logged_days_only(app_ctx):
    from app import app
    from models import TrainingGoal, WeeklyMealPlan, BodyWeight, MealLog
    import coach_assembler
    uid = _fresh_user(app_ctx[1], "cut-deficit-2@test.com")
    with app.test_request_context("/"):
        _login(uid)
        db = app_ctx[1]
        today = coach_assembler._user_today()
        week = coach_assembler._current_week()
        db.session.add(TrainingGoal(user_id=uid, goal_type="cut",
                                    target_weight=185, daily_calories=1700,
                                    tdee=3000))
        db.session.add(BodyWeight(user_id=uid, weight_lbs=207.2, log_date=today))
        for d in range(7):
            db.session.add(WeeklyMealPlan(user_id=uid, week=week, day_idx=d,
                                          meal_data={}, daily_calories=1700))
        # exactly ONE day with meals actually eaten
        db.session.add(MealLog(user_id=uid, log_date=today, eaten=[0, 1]))
        # a day with a MealLog row but nothing eaten does NOT count
        db.session.add(MealLog(user_id=uid, log_date=today - timedelta(days=1),
                               eaten=[]))
        db.session.commit()
        cs = coach_assembler._build_cut_status()["cut_status"]
    assert cs["deficit_days_logged"] == 1
    assert cs["weekly_deficit_estimate"] == 3000 - 1700


# ── 7. classifier: RDL routes to Romanian Deadlift ────────────────────────

def test_classifier_romanian_deadlift_not_conventional():
    from coach_router_classifier import classify_required_tools
    calls = classify_required_tools("romanian deadlift felt heavy, what am I at?",
                                    agent_name="conversation")
    ex_calls = [c for c in calls if c.tool_name == "get_recent_sets"]
    assert ex_calls and ex_calls[0].kwargs["exercise_name"] == "Romanian Deadlift"
    # bare 'deadlift' still resolves to conventional
    calls = classify_required_tools("deadlift day tomorrow?", agent_name="conversation")
    ex_calls = [c for c in calls if c.tool_name == "get_recent_sets"]
    assert ex_calls and ex_calls[0].kwargs["exercise_name"] == "Conventional Deadlift"
