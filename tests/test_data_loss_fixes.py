"""Data-loss / destructive-path fixes (2026-07 whole-app audit, theme 6).

1. force_regen must NOT delete the existing coach plan before the coaches run:
   a total LLM failure keeps the old plan (atomic swap, not delete-first).
2. Past weeks are LOCKED: force_regen on a week < current week is refused.
3. Crisis routing must not false-positive on everyday fitness phrasing
   ("end my cut", "hurt my self esteem") while still catching real crisis.
4. Age extraction only accepts explicit age context — a stray number in free
   text ("I can run 15 miles") must never overwrite the age (age<18 silently
   forced minor handling: deficit removed, fasting stripped).
"""
import time

import pytest


# ─── crisis router ──────────────────────────────────────────────────────────

CRISIS_MESSAGES = [
    "I want to kill myself",
    "thinking about suicide",
    "feeling suicidal lately",
    "I want to end it all",
    "I want to end my life",
    "I want to hurt myself",
    "life is not worth living",
    "better off dead",
    "no reason to live",
]

FITNESS_MESSAGES = [
    "should I end my cut at 190?",
    "I want to end my run early today",
    "can I end my deload week now",
    "end my fast at noon?",
    "that hill climb might hurt my self esteem",
    "this hurts my self-esteem",
]


@pytest.mark.parametrize("msg", CRISIS_MESSAGES)
def test_real_crisis_still_routes_to_crisis_agent(msg):
    from coach_router import route_trigger
    r = route_trigger(msg)
    assert r["is_crisis"] and r["agent_name"] == "crisis", msg


@pytest.mark.parametrize("msg", FITNESS_MESSAGES)
def test_fitness_phrasing_never_routes_to_crisis(msg):
    from coach_router import route_trigger
    r = route_trigger(msg)
    assert not r["is_crisis"] and r["agent_name"] != "crisis", msg


# ─── age extraction ─────────────────────────────────────────────────────────

def test_age_from_explicit_context_only():
    from app import _age_from_message
    # Accepted: bare-number answer or explicit age phrasing
    assert _age_from_message("45") == 45
    assert _age_from_message("i'm 32 years old") == 32
    assert _age_from_message("I am 45") == 45
    assert _age_from_message("age: 52") == 52
    # Rejected: ordinary fitness numbers in free text (the misclassify-as-minor
    # / wrong-TDEE bug)
    assert _age_from_message("I can run 15 miles on Saturdays") is None
    assert _age_from_message("I train about 45 minutes") is None
    assert _age_from_message("i'm 20 weeks out") is None
    assert _age_from_message("my bench is 45 lbs") is None
    assert _age_from_message("I did 30 reps") is None
    # Out-of-range never accepted
    assert _age_from_message("8") is None
    assert _age_from_message("99") is None


# ─── weekly generation: atomic swap + past-week lock ───────────────────────

@pytest.fixture(scope="module")
def gen_ctx():
    from app import app, db
    from models import User
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="dataloss@test.com").first()
        if not u:
            u = User(email="dataloss@test.com", name="DataLoss",
                     role="user", email_verified=True)
            db.session.add(u)
            db.session.commit()
        uid = u.id
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return client, app, uid


def _generate_and_wait(client, payload, timeout=30):
    resp = client.post("/api/weekly-program/generate", json=payload)
    if resp.status_code != 200:
        return resp.status_code, resp.get_json()
    body = resp.get_json() or {}
    if body.get("status") != "started":
        return resp.status_code, body
    week = payload.get("week")
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(
            f"/api/weekly-program/generate-status?week={week}").get_json() or {}
        if j.get("status") in ("done", "error"):
            return 200, j
        time.sleep(0.2)
    return 200, {"status": "timeout"}


def test_force_regen_keeps_existing_plan_when_coaches_fail(gen_ctx, monkeypatch):
    """THE delete-first footgun: 'Plan this week' while the LLM is down must
    never destroy the existing coach plan. Old code deleted + committed before
    the coaches ran; now the swap happens atomically with the new inserts."""
    client, app, uid = gen_ctx
    from app import db
    from models import WeeklyPrescription, WeeklyRunPlan
    import coach_planning_program, coach_planning_runs, coach_planning_meals

    week = 7
    with app.app_context():
        WeeklyPrescription.query.filter_by(user_id=uid, week=week).delete()
        WeeklyRunPlan.query.filter_by(user_id=uid, week=week).delete()
        db.session.add(WeeklyPrescription(
            user_id=uid, week=week, day_idx=0, exercise_order=0,
            exercise_name="Barbell Back Squat", sets=4, reps="6",
            target_weight=185, rest="120s", source="coach",
            adjustment_reason="Existing good plan"))
        db.session.add(WeeklyRunPlan(
            user_id=uid, week=week, day_idx=1, run_type="z2",
            label="Zone 2", duration="40 min", detail="easy", source="coach"))
        db.session.commit()

    # Every coach fails (API outage)
    monkeypatch.setattr(coach_planning_program, "generate_week_program",
                        lambda **k: ({}, []))
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs",
                        lambda **k: {})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals",
                        lambda **k: {})

    status, body = _generate_and_wait(client, {"week": week, "force_regen": True})
    assert status == 200, body

    with app.app_context():
        rx = WeeklyPrescription.query.filter_by(
            user_id=uid, week=week, source="coach").all()
        runs = WeeklyRunPlan.query.filter_by(
            user_id=uid, week=week, source="coach").all()
        assert len(rx) == 1 and rx[0].exercise_name == "Barbell Back Squat", \
            "existing coach prescriptions were destroyed by a failed regen"
        assert len(runs) == 1 and runs[0].label == "Zone 2", \
            "existing coach run plan was destroyed by a failed regen"
        # cleanup
        WeeklyPrescription.query.filter_by(user_id=uid, week=week).delete()
        WeeklyRunPlan.query.filter_by(user_id=uid, week=week).delete()
        db.session.commit()


def test_force_regen_refuses_past_week(gen_ctx):
    """A stale tab / crafted request must never delete+regenerate a locked past
    week (the 2026-04-28 Week-5 overwrite class)."""
    client, app, uid = gen_ctx
    from datetime import date, timedelta
    from app import db
    from models import AppState

    with app.app_context():
        s = AppState.query.filter_by(user_id=uid).first()
        if not s:
            s = AppState(user_id=uid, current_week=1, baseline_done=True)
            db.session.add(s)
        # Start 4 weeks ago -> current week is 5 (±1 day of tz drift is
        # irrelevant at this margin)
        s.start_date = date.today() - timedelta(days=28)
        db.session.commit()

    try:
        resp = client.post("/api/weekly-program/generate",
                           json={"week": 2, "force_regen": True})
        assert resp.status_code == 409, resp.get_json()
        assert "locked" in (resp.get_json() or {}).get("error", "").lower()
    finally:
        with app.app_context():
            s = AppState.query.filter_by(user_id=uid).first()
            if s:
                s.start_date = None
                db.session.commit()


def test_generate_status_poll_is_a_pure_read(gen_ctx, monkeypatch):
    """The polling GET must never fire a synchronous coach LLM call (it did,
    via the read-branch run gap-fill + why enrichment)."""
    client, app, uid = gen_ctx
    from app import db
    from models import WeeklyPrescription, WeeklyRunPlan
    import app as appmod

    week = 9
    with app.app_context():
        WeeklyPrescription.query.filter_by(user_id=uid, week=week).delete()
        WeeklyRunPlan.query.filter_by(user_id=uid, week=week).delete()
        # Coach lifts present, NO runs — the state that used to trigger an
        # inline running-coach call on the request thread.
        db.session.add(WeeklyPrescription(
            user_id=uid, week=week, day_idx=0, exercise_order=0,
            exercise_name="Barbell Bench Press", sets=3, reps="8",
            target_weight=155, rest="90s", source="coach",
            adjustment_reason="short"))
        db.session.commit()
        with appmod._GEN_JOBS_LOCK:
            appmod._GEN_JOBS.pop((uid, week), None)

    def _boom(*a, **k):
        raise AssertionError("LLM called on the request thread")

    monkeypatch.setattr(appmod, "_fill_missing_week_runs", _boom)
    import coach_planning_why
    monkeypatch.setattr(coach_planning_why, "generate_week_whys", _boom)

    j = client.get(
        f"/api/weekly-program/generate-status?week={week}").get_json()
    assert j["status"] == "done", j
    assert j.get("program"), j

    with app.app_context():
        WeeklyPrescription.query.filter_by(user_id=uid, week=week).delete()
        db.session.commit()
