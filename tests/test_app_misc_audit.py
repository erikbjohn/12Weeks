"""Audit theme 9c-app-misc regression tests.

Covers:
- wk12 no-gym is a DELOAD week (not the removed test/taper) with deload labels
  and deload meals — no POWER (HOLD) header over deload content.
- Inverted-row / diamond push-up name variants unify to one movement key so
  SetLog lift history never fragments across template vs catalog names.
- target_weight=0 (bodyweight prescription) is honored by the /api/sets
  modification check — adding load reads increased_weight, never judged
  against an engine weight the user was never shown (falsy-zero class).
- Editing a past day's set preserves its original logged_date (no phantom
  trained-today / split sessions).
- /api/workouts/<week> applies the same ExerciseSwap overlay as /api/workouts.
- /api/morning-checkin/extract returns a structured error (not a Flask 500
  from returning None) when the model reply contains no JSON.
- /api/deficit-plan reads BodyWeight.weight_lbs (bw.weight was AttributeError).
"""
import datetime

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login(app_, db, email="misc-audit@test.com"):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)
        s["_fresh"] = True
    return u, client


# ── wk12 no-gym = deload week ────────────────────────────────────────────────

def test_wk12_no_gym_is_deload_week_not_taper():
    from workout_data import get_workouts_for_user, get_workouts
    days = get_workouts_for_user(12, has_gym=False)
    gym_days = get_workouts(12)
    for d, g in zip(days, gym_days):
        # No POWER/HOLD/Test headers on a deload card — the old test_bw path
        # put 'Test BW - Lower POWER (HOLD)' over taper content.
        assert "HOLD" not in d["liftName"], d["liftName"]
        assert "Test BW" not in d["liftName"], d["liftName"]
        if not d.get("isRest"):
            assert d["liftName"].startswith("Deload BW"), d["liftName"]
            # Meals agree with the gym path's deload week — not heavy_lift.
            assert d["mealType"] == "deload", (d["liftName"], d["mealType"])
            assert g["mealType"] == "deload"


def test_bw_deload_cadence_matches_gym_4_8_12():
    from workout_data import get_workouts_for_user
    for wk in (4, 8, 12):
        d0 = get_workouts_for_user(wk, has_gym=False)[0]
        assert d0["liftName"].startswith("Deload BW"), (wk, d0["liftName"])
        assert d0["mealType"] == "deload"
    # Non-deload weeks keep phase labels/meals.
    d0 = get_workouts_for_user(5, has_gym=False)[0]
    assert not d0["liftName"].startswith("Deload"), d0["liftName"]


# ── name-variant unification (SetLog history fragmentation) ────────────────

def test_inverted_row_and_diamond_variants_share_movement_key():
    from coach_planning_program import _movement_key
    from workout_data import resolve_name, EXERCISES
    assert (_movement_key("Inverted Row (table/ledge)")
            == _movement_key("Inverted Row (table)")
            == _movement_key("Inverted Row (table edge)")
            == _movement_key("Inverted Row"))
    assert _movement_key("Diamond Push-Up") == _movement_key("Diamond Push-Ups")
    # Canonical alias targets must be real EXERCISES catalog keys.
    for variant in ("Inverted Row (table/ledge)", "Diamond Push-Up"):
        assert resolve_name(variant) in EXERCISES, variant


# ── falsy-zero: bodyweight prescription target_weight=0 ────────────────────

def test_zero_target_prescription_added_load_reads_increased(app_ctx):
    app_, db = app_ctx
    from models import SetLog, WeeklyPrescription
    u, client = _login(app_, db)
    WeeklyPrescription.query.filter_by(user_id=u.id).delete()
    SetLog.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    db.session.add(WeeklyPrescription(
        user_id=u.id, week=2, day_idx=0, exercise_order=0,
        exercise_name="Push-Ups", sets=3, reps="10",
        target_weight=0, source="coach"))
    db.session.commit()

    r = client.post("/api/sets", json={
        "exercise": "Push-Ups", "week": 2, "day_idx": 0,
        "set_number": 0, "weight": 25, "reps": 10, "done": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    row = SetLog.query.filter_by(user_id=u.id, week=2, day_idx=0,
                                 exercise_name="Push-Ups").first()
    # Athlete ADDED 25 lb over a bodyweight (0) prescription. The old `or`
    # dropped the 0 and judged against the engine's number -> decreased_weight.
    assert row.modification_direction == "increased_weight", \
        row.modification_direction
    assert row.user_modified is True


# ── editing a past set preserves logged_date ────────────────────────────────

def test_editing_past_set_preserves_logged_date(app_ctx):
    app_, db = app_ctx
    from models import SetLog
    u, client = _login(app_, db)
    r = client.post("/api/sets", json={
        "exercise": "Front Squat", "week": 2, "day_idx": 1,
        "set_number": 0, "weight": 135, "reps": 8, "done": True})
    assert r.status_code == 200
    row = SetLog.query.filter_by(user_id=u.id, week=2, day_idx=1,
                                 exercise_name="Front Squat").first()
    past = datetime.date.today() - datetime.timedelta(days=3)
    row.logged_date = past
    db.session.commit()

    # Fix a mistyped weight days later — the set's date must NOT move to today.
    r = client.post("/api/sets", json={
        "exercise": "Front Squat", "week": 2, "day_idx": 1,
        "set_number": 0, "weight": 145, "reps": 8, "done": True})
    assert r.status_code == 200
    db.session.expire_all()
    row = SetLog.query.filter_by(user_id=u.id, week=2, day_idx=1,
                                 exercise_name="Front Squat").first()
    assert row.weight == 145
    assert row.logged_date == past, \
        f"edit moved logged_date {past} -> {row.logged_date}"


# ── /api/workouts/<week> applies the ExerciseSwap overlay ───────────────────

def test_api_week_applies_exercise_swap_overlay(app_ctx):
    app_, db = app_ctx
    from models import ExerciseSwap, WeeklyPrescription
    u, client = _login(app_, db)
    WeeklyPrescription.query.filter_by(user_id=u.id, week=3).delete()
    ExerciseSwap.query.filter_by(user_id=u.id, week=3).delete()
    db.session.commit()
    for order, name in enumerate(["Front Squat", "Romanian Deadlift"]):
        db.session.add(WeeklyPrescription(
            user_id=u.id, week=3, day_idx=0, exercise_order=order,
            exercise_name=name, sets=3, reps="8", source="coach"))
    db.session.add(ExerciseSwap(
        user_id=u.id, week=3, day_idx=0, exercise_idx=1,
        swapped_to="Single-Leg Romanian Deadlift",
        original_name="Romanian Deadlift"))
    db.session.commit()

    r = client.get("/api/workouts/3")
    assert r.status_code == 200, r.get_data(as_text=True)
    day0 = r.get_json()["days"][0]
    names = [e["name"] for e in day0["exercises"]]
    # The per-week endpoint used to skip the ExerciseSwap overlay entirely,
    # disagreeing with /api/workouts on the same slot.
    assert names[1] == "Single-Leg Romanian Deadlift", names
    # swapped_from records the DISPLAYED original (post-auto_swap) — assert it
    # is present, not its exact value (equipment-dependent).
    assert day0["exercises"][1].get("swapped_from"), day0["exercises"][1]


# ── morning-checkin extract: no JSON in model reply ─────────────────────────

def test_extract_checkin_no_json_returns_structured_error(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db)
    import anthropic

    class _Msg:
        content = [type("T", (), {"text": "I cannot extract those values."})()]

    class _Fake:
        def __init__(self, *a, **k):
            self.messages = type("M", (), {"create": staticmethod(
                lambda **kw: _Msg())})()

    monkeypatch.setattr(anthropic, "Anthropic", _Fake)
    r = client.post("/api/morning-checkin/extract",
                    json={"conversation": "coach: how did you sleep?"})
    # Old code fell off the end of the view (None) -> TypeError/500 crash page.
    assert r.status_code == 502, (r.status_code, r.get_data(as_text=True))
    assert "error" in (r.get_json() or {})


# ── deficit-plan reads weight_lbs ───────────────────────────────────────────

def test_deficit_plan_reads_weight_lbs(app_ctx):
    app_, db = app_ctx
    from models import BodyWeight, TrainingGoal
    u, client = _login(app_, db)
    if not TrainingGoal.query.filter_by(user_id=u.id).first():
        db.session.add(TrainingGoal(user_id=u.id, goal_type="cut",
                                    target_weight=185, daily_calories=2000))
    db.session.add(BodyWeight(user_id=u.id, weight_lbs=212,
                              log_date=datetime.date.today()))
    db.session.commit()
    r = client.post("/api/deficit-plan", json={})
    # bw.weight raised AttributeError -> 500 for every user with weight data.
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    if not body.get("on_pace"):
        assert body.get("current_weight") == 212
