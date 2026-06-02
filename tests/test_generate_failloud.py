"""Generate path must FAIL LOUD: coach-or-nothing. When a planning coach
returns nothing, the endpoint must NOT silently write engine/template rows —
it writes no row for that domain and surfaces the failure.
"""
import pytest


def _generate_and_wait(client, payload, timeout=30):
    """POST /generate and resolve the async job. force_regen / fresh-week
    generation now runs in a background thread and returns {status:'started'};
    the client polls /generate-status. Returns (http_status, final_body)."""
    import time
    resp = client.post("/api/weekly-program/generate", json=payload)
    if resp.status_code != 200:
        return resp.status_code, resp.get_json()
    body = resp.get_json() or {}
    if body.get("status") != "started":
        return resp.status_code, body  # synchronous fast-read path
    week = payload.get("week")
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/weekly-program/generate-status?week={week}").get_json() or {}
        if j.get("status") in ("done", "error"):
            return 200, j
        time.sleep(0.2)
    return 200, {"status": "timeout"}


@pytest.fixture(scope="module")
def ctx():
    from app import app, db
    from models import User
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="genfailloud@test.com").first()
        if not u:
            u = User(email="genfailloud@test.com", name="Gen",
                     role="user", email_verified=True)
            db.session.add(u)
            db.session.commit()
        uid = u.id
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return client, app, uid


def test_coach_failure_writes_no_engine_or_template_rows(ctx, monkeypatch):
    client, app, uid = ctx
    import coach_planning_program, coach_planning_runs, coach_planning_meals
    # All coaches "fail" (return empty). Program coach returns (prog, notes).
    monkeypatch.setattr(coach_planning_program, "generate_week_program",
                        lambda **k: ({}, []))
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs",
                        lambda **k: {})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals",
                        lambda **k: {})

    status, body = _generate_and_wait(client, {"week": 6, "force_regen": True})
    assert status == 200, body

    from models import WeeklyPrescription, WeeklyRunPlan
    with app.app_context():
        rx = WeeklyPrescription.query.filter_by(user_id=uid, week=6).all()
        runs = WeeklyRunPlan.query.filter_by(user_id=uid, week=6).all()
        # No engine/template fallback rows may exist.
        assert all(r.source == "coach" for r in rx), \
            f"non-coach lift rows leaked: {[r.source for r in rx]}"
        assert runs == [], \
            f"engine run-plan rows leaked on coach failure: {[r.source for r in runs]}"

    # The failure must be surfaced, not swallowed.
    assert body.get("coach_failures"), "coach failure must be reported in response"


def test_coach_success_writes_coach_rows(ctx, monkeypatch):
    client, app, uid = ctx
    import coach_planning_program, coach_planning_runs, coach_planning_meals

    def fake_program(**k):
        # B designs the whole week: {day: [{exercise, sets, reps, weight, why}]}.
        from workout_data import get_workouts, resolve_name
        days = get_workouts(k["week"])
        prog = {}
        for di in range(7):
            items = [{"exercise": resolve_name(ex["name"]), "sets": 3, "reps": "5",
                      "weight": 100, "rest": "90s", "why": "test", "new": False}
                     for ex in (days[di].get("exercises", []) or [])]
            if items:
                prog[di] = items
        return (prog, [])

    def fake_runs(**k):
        return {6: {"type": "z2", "label": "Z2 base", "duration": "60 min",
                    "detail": "HR <= 140"}}

    monkeypatch.setattr(coach_planning_program, "generate_week_program", fake_program)
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs", fake_runs)
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals", lambda **k: {})

    status, body = _generate_and_wait(client, {"week": 6, "force_regen": True})
    assert status == 200, body

    from models import WeeklyRunPlan
    with app.app_context():
        runs = WeeklyRunPlan.query.filter_by(user_id=uid, week=6).all()
        assert any(r.source == "coach" and r.duration == "60 min" for r in runs)


def test_history_week_with_no_runs_gets_runs_filled(ctx, monkeypatch):
    """The early-return guard (week has logged history) must still fill a
    MISSING run plan via the coach instead of leaving the run unplanned —
    this is the exact bug that leaked the static template on weeks 9/10.
    """
    client, app, uid = ctx
    from datetime import date
    from app import db
    from models import SetLog, WeeklyRunPlan
    with app.app_context():
        WeeklyRunPlan.query.filter_by(user_id=uid, week=7).delete()
        SetLog.query.filter_by(user_id=uid, week=7).delete()
        # Logged history for week 7 -> triggers the early-return guard.
        db.session.add(SetLog(
            user_id=uid, week=7, day_idx=0, exercise_name="Front Squat",
            set_number=1, weight=135, reps=3, done=True, logged_date=date.today(),
        ))
        db.session.commit()

    import coach_planning_runs
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs",
                        lambda **k: {d: {"type": "z2", "label": "Z2",
                                         "duration": "55 min", "detail": "easy"}
                                     for d in range(7)})

    resp = client.post("/api/weekly-program/generate", json={"week": 7})
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json().get("regenerated") is False  # guard still in effect

    with app.app_context():
        runs = WeeklyRunPlan.query.filter_by(user_id=uid, week=7).all()
        assert runs, "missing runs must be filled even on a history week"
        assert all(r.source == "coach" for r in runs)
        # Lift history must be untouched.
        sets = SetLog.query.filter_by(user_id=uid, week=7, done=True).all()
        assert len(sets) == 1


def test_rest_of_week_regen_preserves_today_and_earlier(ctx, monkeypatch):
    """preserve_through_day=N regenerates only day_idx > N. Today (N) and every
    earlier day keep their exact prescriptions/runs; later days are replaced.
    """
    client, app, uid = ctx
    from app import db
    from models import WeeklyPrescription, WeeklyRunPlan
    from workout_data import get_workouts, resolve_name
    WEEK = 11
    with app.app_context():
        WeeklyPrescription.query.filter_by(user_id=uid, week=WEEK).delete()
        WeeklyRunPlan.query.filter_by(user_id=uid, week=WEEK).delete()
        days = get_workouts(WEEK)
        for di in (0, 1):  # seed OLD rows for today (0) and tomorrow (1)
            for order, ex in enumerate(days[di].get("exercises", []) or []):
                db.session.add(WeeklyPrescription(
                    user_id=uid, week=WEEK, day_idx=di, exercise_order=order,
                    exercise_name=resolve_name(ex["name"]), sets=3, reps="3",
                    rest="2 min", note="", source="coach", target_weight=999.0))
            tr = days[di].get("run")
            if tr:
                db.session.add(WeeklyRunPlan(
                    user_id=uid, week=WEEK, day_idx=di, run_type=tr["type"],
                    label=tr["label"], duration="OLD", detail="old", source="coach"))
        db.session.commit()

    import coach_planning_program, coach_planning_runs, coach_planning_meals

    def fake_program(**k):
        prog = {}
        for di in range(7):
            items = [{"exercise": resolve_name(ex["name"]), "sets": 3, "reps": "5",
                      "weight": 220, "rest": "90s", "why": "fresh", "new": False}
                     for ex in (get_workouts(k["week"])[di].get("exercises", []) or [])]
            if items:
                prog[di] = items
        return (prog, [])

    monkeypatch.setattr(coach_planning_program, "generate_week_program", fake_program)
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs",
                        lambda **k: {di: {"type": "z2", "label": "Z2",
                                          "duration": "44 min", "detail": "fresh"}
                                     for di in range(7)})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals", lambda **k: {})

    status, body = _generate_and_wait(
        client, {"week": WEEK, "force_regen": True, "preserve_through_day": 0})
    assert status == 200, body

    with app.app_context():
        d0 = WeeklyPrescription.query.filter_by(user_id=uid, week=WEEK, day_idx=0).all()
        assert d0 and all(r.target_weight == 999.0 for r in d0), "today's lifts must be preserved"
        r0 = WeeklyRunPlan.query.filter_by(user_id=uid, week=WEEK, day_idx=0).all()
        assert r0 and all(r.duration == "OLD" for r in r0), "today's run must be preserved"
        d1 = WeeklyPrescription.query.filter_by(user_id=uid, week=WEEK, day_idx=1).all()
        # Regenerated (not the old 999) AND rounded to a loadable weight — a
        # barbell at 220 is not buildable (ends in 0); it becomes 225 (45+10k).
        from app import _round_to_loadable
        assert d1 and all(r.target_weight != 999.0 for r in d1), "tomorrow's lifts must be regenerated"
        assert all(r.target_weight == _round_to_loadable(r.exercise_name, 220.0) for r in d1), \
            "regenerated lifts must be rounded to a loadable weight"
        r1 = WeeklyRunPlan.query.filter_by(user_id=uid, week=WEEK, day_idx=1).all()
        assert r1 and all(r.duration == "44 min" for r in r1), "tomorrow's run must be regenerated"
