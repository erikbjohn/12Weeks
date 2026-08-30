"""tests/test_deload_coach_called.py — deloads are called by the coach from the
data, never by week number.

Erik, 2026-08-30 (week 4 of block 3, just started adding weight): the weekly
planner forced a deload he did not want and the coach could not override it,
because `week in (4, 8, 12)` was hardcoded in eight places. Decision: "Let the
coach call them from the data."

Contract:
1. deload.is_deload_week(user, week) is the ONLY source of truth — a persisted
   per-week flag on WeeklyDaySchedule. Week 4/8/12 with no flag = normal week.
2. The weekly set target climbs with no notches; a coach-called deload targets
   ~55% of that week's climb value.
3. Every rail that used the week number now uses the flag: volume floor anchor,
   auto-reconcile, run regression floor, seven-day run floor, marker guards,
   training_engine, lift_trend.
4. The strength coach returns {"deload": {"call": bool, "reason": str}} and the
   decision is persisted with its reason; it is served to the UI.
5. The athlete can veto/force via a codified [DELOAD: week=N, call=..] marker.
"""
import json
import time
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _user(app_, db, email):
    with app_.app_context():
        from models import User
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Indianapolis")
            db.session.add(u)
            db.session.commit()
        return u.id


def _schedule(app_, db, uid, week, deload=None, reason=None):
    with app_.app_context():
        from models import WeeklyDaySchedule
        WeeklyDaySchedule.query.filter_by(user_id=uid, week=week).delete()
        for d in range(7):
            row = WeeklyDaySchedule(user_id=uid, week=week, day_idx=d,
                                    lift_name="Upper A", is_rest=(d == 6), source="coach")
            if deload is not None:
                row.deload = deload
                row.deload_reason = reason
            db.session.add(row)
        db.session.commit()


# ── 1. the flag is the only truth ────────────────────────────────────────

def test_week_four_without_flag_is_not_a_deload(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-flag@test.com")
    _schedule(app_, db, uid, 4)
    from deload import is_deload_week
    with app_.app_context():
        assert is_deload_week(uid, 4) is False
        assert is_deload_week(uid, 8) is False
        assert is_deload_week(uid, 12) is False


def test_flagged_week_is_a_deload(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-flag2@test.com")
    _schedule(app_, db, uid, 6, deload=True, reason="HRV down 12% vs 28d, two compounds regressed")
    from deload import is_deload_week, deload_reason
    with app_.app_context():
        assert is_deload_week(uid, 6) is True
        assert "HRV" in deload_reason(uid, 6)


# ── 2. the curve climbs without notches ──────────────────────────────────

def test_target_weekly_sets_has_no_notches():
    from app import _target_weekly_sets
    vals = [_target_weekly_sets(w) for w in range(1, 13)]
    assert vals[:11] == sorted(vals[:11]) and len(set(vals[:11])) == 11, vals  # strictly up through wk 11
    assert vals[11] >= vals[10], vals  # week 12 never dips by schedule
    assert max(vals) == 106  # Erik's aggressive peak (2026-06-29)


def test_coach_called_deload_targets_55_percent():
    from app import _target_weekly_sets
    for w in (2, 4, 9):
        assert _target_weekly_sets(w, deload=True) == round(0.55 * _target_weekly_sets(w))


# ── 3. rails use the flag ────────────────────────────────────────────────

def test_prev_nondeload_total_skips_flagged_week_not_week_number(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-anchor@test.com")
    with app_.app_context():
        from models import WeeklyPrescription
        for w, sets in ((3, 9), (4, 12), (5, 4)):
            for i in range(sets // 4 + 1):
                pass
            # simple: one row per week carrying the total
            db.session.add(WeeklyPrescription(user_id=uid, week=w, day_idx=0, exercise_order=0,
                                              exercise_name="Barbell Bench Press", sets=sets,
                                              reps="5", target_weight=135, source="coach"))
        db.session.commit()
    _schedule(app_, db, uid, 4)                       # week 4 unflagged → counts
    _schedule(app_, db, uid, 5, deload=True, reason="coach call")
    from coach_planning_program import _prev_nondeload_total
    with app_.app_context():
        assert _prev_nondeload_total(uid, 6) == 12, "must anchor on week 4 (a real week now), skipping flagged week 5"


def test_autoreconcile_skips_flagged_week_not_week_twelve(app_ctx):
    app_, db = app_ctx
    from app import _reconcile_prescription_to_logged
    uid = _user(app_, db, "deload-recon@test.com")
    with app_.app_context():
        from models import WeeklyPrescription
        for w in (10, 11, 12):
            db.session.add(WeeklyPrescription(user_id=uid, week=w, day_idx=1, exercise_order=0,
                                              exercise_name="Barbell Bench Press", sets=4,
                                              reps="5", target_weight=145, source="coach"))
        db.session.commit()
    _schedule(app_, db, uid, 11, deload=True, reason="coach call")
    with app_.app_context():
        _reconcile_prescription_to_logged(uid, "Barbell Bench Press", 155, 10)
        from models import WeeklyPrescription
        t = {r.week: r.target_weight for r in WeeklyPrescription.query.filter_by(
            user_id=uid, exercise_name="Barbell Bench Press").all()}
    assert t[10] == 155 and t[12] == 155, "week 12 is a normal week unless flagged"
    assert t[11] == 145, "the flagged deload week stays light"


def test_run_regression_floor_uses_flag(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-runs@test.com")
    with app_.app_context():
        from models import WeeklyRunPlan
        WeeklyRunPlan.query.filter_by(user_id=uid, week=7).delete()
        db.session.add(WeeklyRunPlan(user_id=uid, week=7, day_idx=1, run_type="hiit",
                                     label="VO2", duration="40 min", detail="", source="coach"))
        db.session.commit()
    from coach_planning_runs import _apply_run_regression_floor
    plan = lambda: {1: {"type": "hiit", "label": "VO2", "duration": "28 min", "detail": ""}}
    with app_.app_context():
        held = _apply_run_regression_floor(plan(), uid, 8)                # week 8, no flag
        dropped = _apply_run_regression_floor(plan(), uid, 8, deload=True)
    assert held[1]["duration"] == "40 min", "week 8 is not a deload by number"
    assert dropped[1]["duration"] == "28 min", "a coach-called deload may reduce"


def test_seven_day_run_floor_uses_flag():
    from coach_planning_runs import _ensure_seven_day_runs
    assert _ensure_seven_day_runs({}, 4)[0]["duration"] == "28 min"
    assert _ensure_seven_day_runs({}, 4, deload=True)[0]["duration"] == "22 min"


def test_training_engine_has_no_week_number_deload():
    from training_engine import _is_deload
    assert _is_deload(4) is False and _is_deload(8) is False


def test_lift_trend_excludes_flagged_week(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-trend@test.com")
    _schedule(app_, db, uid, 3, deload=True, reason="coach call")
    from lift_trend import _weeks_with_data
    with app_.app_context():
        from models import SetLog
        from datetime import date
        for w in (2, 3, 4):
            db.session.add(SetLog(user_id=uid, week=w, day_idx=0, exercise_name="Barbell Bench Press",
                                  set_number=1, weight=135, reps=5, done=True,
                                  logged_date=date(2026, 8, 3 + 7 * w)))
        db.session.commit()
        weeks = _weeks_with_data(uid, 4)
    assert 3 not in weeks and 2 in weeks and 4 in weeks


# ── 4. the coach's decision is parsed, persisted, served ─────────────────

class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **kw):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)],
                               stop_reason="end_turn")


def test_generate_week_program_returns_coach_deload_decision(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_planning_program as cpp
    uid = _user(app_, db, "deload-coach@test.com")
    body = json.dumps({
        "deload": {"call": True, "reason": "HRV 7d 41 vs 28d 52; bench and squat e1RM down 6%"},
        "0": [{"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "weight": 135,
               "rest": "2 min", "why": "deload load, keep the pattern"}],
    })
    monkeypatch.setattr(cpp, "_anthropic_client",
                        lambda: SimpleNamespace(messages=_FakeMessages(body)))
    with app_.app_context():
        clean, notes, decision = cpp.generate_week_program(
            uid, 5, {"phase": 3, "goal_type": "cut", "target_weekly_sets": 96,
                     "current_weight": 210, "target_weight": 195, "train_days": 6})
    assert decision == {"deload": True, "reason": "HRV 7d 41 vs 28d 52; bench and squat e1RM down 6%",
                        "reduce_running": None}
    assert "deload" not in clean, "the decision key must not leak into the day map"


def test_generate_week_program_defaults_to_no_deload(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_planning_program as cpp
    uid = _user(app_, db, "deload-coach2@test.com")
    body = json.dumps({"0": [{"exercise": "Barbell Bench Press", "sets": 4, "reps": "5",
                              "weight": 135, "rest": "2 min", "why": "progress"}]})
    monkeypatch.setattr(cpp, "_anthropic_client",
                        lambda: SimpleNamespace(messages=_FakeMessages(body)))
    with app_.app_context():
        _, _, decision = cpp.generate_week_program(
            uid, 4, {"phase": 3, "goal_type": "cut", "target_weekly_sets": 93, "train_days": 6})
    assert decision["deload"] is False


def test_persist_and_serve_deload_decision(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-serve@test.com")
    _schedule(app_, db, uid, 4)
    from deload import persist_deload_decision, is_deload_week
    with app_.app_context():
        persist_deload_decision(uid, 4, {"deload": True, "reason": "coach: fatigue signals"})
        assert is_deload_week(uid, 4) is True
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    payload = client.get("/api/workouts").get_json()
    wk = payload["4"] if "4" in payload else payload[4]
    assert wk["deload"] is True
    assert wk["deload_reason"] == "coach: fatigue signals"
    wk3 = payload["3"] if "3" in payload else payload[3]
    assert wk3.get("deload") is False


# ── 5. the athlete's veto is codified ────────────────────────────────────

def test_deload_marker_flips_the_flag(app_ctx):
    app_, db = app_ctx
    from app import _parse_coach_markers
    uid = _user(app_, db, "deload-marker@test.com")
    _schedule(app_, db, uid, 5, deload=True, reason="coach call")
    from deload import is_deload_week, deload_reason
    with app_.app_context():
        _parse_coach_markers("Fine — no deload. [DELOAD: week=5, call=false, reason=athlete vetoed; adding weight this week]", uid, 5)
        assert is_deload_week(uid, 5) is False
        assert "vetoed" in deload_reason(uid, 5)
        _parse_coach_markers("[DELOAD: week=5, call=true, reason=three bad nights of sleep]", uid, 5)
        assert is_deload_week(uid, 5) is True


# ── 6. evidence the coach decides from ───────────────────────────────────

def test_deload_evidence_with_no_data_is_honest(app_ctx):
    app_, db = app_ctx
    uid = _user(app_, db, "deload-evidence@test.com")
    from deload import deload_evidence_text
    from datetime import date
    with app_.app_context():
        txt = deload_evidence_text(uid, 5, date(2026, 9, 6))
    assert "no deload" in txt.lower()
    assert "no data" in txt.lower() or "dark" in txt.lower()


# ── 7. the ceiling never undercuts the anti-taper floor ──────────────────

def test_volume_ceiling_never_below_the_floor():
    """2026-08-30: week 3 prescribed 105 sets; week 4's curve target was 93 so
    the ceiling (93+8=101) sat BELOW the floor (105) and the replan shipped 101
    — a 4-set taper Erik caught immediately. The floor always wins."""
    from coach_planning_program import _volume_rails
    floor, ceiling = _volume_rails(93, 105, deload=False)
    assert floor == 105, "anti-taper floor = last non-deload week"
    assert ceiling >= floor + 6, "room above the floor, never below it"
    floor2, ceiling2 = _volume_rails(93, 80, deload=False)
    assert floor2 == 86 and ceiling2 == 101  # 0.92*93 floor; normal ceiling
    floor3, ceiling3 = _volume_rails(93, 105, deload=True)
    assert floor3 == 0, "a coach-called deload has no floor"
