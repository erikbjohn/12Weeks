"""tests/test_scoreboard.py — TDD for the block-3 recomp scoreboard served on
GET /api/progress/dashboard under key "scoreboard" (block-3 mode only).

The scoreboard is a served-values-only panel: every field is computed
server-side by reusing the SAME code paths the existing dashboard badges
already call —

  - goal_engine.curve_value / pace_status, fed the SAME despiked weight
    (cut_guard.detect_water_spike via app._despiked_current_weight) and the
    SAME anchor/start (cut_guard._block3_anchor_and_start) the dashboard's
    own on_pace badge and coach_assembler._build_cut_status's cut_status.on_curve
    badge already use — so the scoreboard can never disagree with either
    (no-UI-contradiction rule).
  - lift_trend.lift_decline for the lift-trend tripwire.
  - body_stats.estimate_body_fat_navy for the Navy body-fat formula (the
    ONE implementation in this repo; the formula is pinned by hand below).

App-context handling: SHORT-LIVED contexts only (matches
tests/test_protocol_api.py's and tests/test_projection_surfaces.py's
documented pattern) — every DB touch opens its own
`with app_.app_context():` block and returns plain values, never attached
ORM objects; client.get/post calls always run with no app context held
open so Flask pushes a correct, fresh one and flask-login's current_user
caching on `g` can't leak between different logged-in test clients.
"""
from datetime import date, timedelta

import pytest

ANCHOR = 220.0
START = date(2026, 8, 10)
WEEK1_DATE = START + timedelta(days=6)  # 2026-08-16


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _do(app_, fn):
    """Run fn() inside a fresh, short-lived app context (pushed and popped
    immediately) so flask.g never survives past this call."""
    with app_.app_context():
        return fn()


@pytest.fixture()
def clean_block3_flags(app_ctx):
    """SystemFlag is a GLOBAL table (not per-user) — must be reset between
    tests so the flag-present and flag-absent scenarios never leak."""
    app_, db = app_ctx

    def _clear():
        from models import SystemFlag
        SystemFlag.query.filter(
            SystemFlag.key.in_(["projection_mode", "block3_anchor"])
        ).delete(synchronize_session=False)
        db.session.commit()

    _do(app_, _clear)
    yield
    _do(app_, _clear)


def _set_block3_flags(app_, db, anchor=ANCHOR):
    def _do_it():
        from models import SystemFlag
        db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
        db.session.add(SystemFlag(key="block3_anchor", value=str(anchor)))
        db.session.commit()
    _do(app_, _do_it)


def _login(app_, db, email):
    def _do_it():
        from models import User
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        return u.id, u.email
    uid, uemail = _do(app_, _do_it)
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    return uid, uemail, client


def _seed_goal_and_state(app_, db, uid, start_date=START, goal_type="recomp", target_weight=195.0):
    def _do_it():
        from models import TrainingGoal, AppState
        TrainingGoal.query.filter_by(user_id=uid).delete()
        AppState.query.filter_by(user_id=uid).delete()
        db.session.commit()
        db.session.add(TrainingGoal(
            user_id=uid, goal_type=goal_type, target_weight=target_weight,
            daily_calories=1800, tdee=2800,
        ))
        db.session.add(AppState(user_id=uid, current_week=1, start_date=start_date))
        db.session.commit()
    _do(app_, _do_it)


def _set_weights(app_, db, uid, pairs):
    """pairs: [(date, weight), ...] oldest-first."""
    def _do_it():
        from models import BodyWeight
        BodyWeight.query.filter_by(user_id=uid).delete()
        db.session.commit()
        for d, w in pairs:
            db.session.add(BodyWeight(user_id=uid, weight_lbs=w, log_date=d))
        db.session.commit()
    _do(app_, _do_it)


def _set_measurements(app_, db, uid, rows):
    """rows: [(date, waist_or_None, neck_or_None), ...] oldest-first."""
    def _do_it():
        from models import BodyMeasurement
        BodyMeasurement.query.filter_by(user_id=uid).delete()
        db.session.commit()
        for d, waist, neck in rows:
            db.session.add(BodyMeasurement(user_id=uid, log_date=d, waist_inches=waist, neck=neck))
        db.session.commit()
    _do(app_, _do_it)


def _set_height(app_, db, uid, height_inches):
    def _do_it():
        from models import PhysicalAssessment
        PhysicalAssessment.query.filter_by(user_id=uid).delete()
        db.session.commit()
        db.session.add(PhysicalAssessment(user_id=uid, height_inches=height_inches))
        db.session.commit()
    _do(app_, _do_it)


def _add_sets(app_, db, uid, week, exercise, weight, reps, n_sets, day_idx=0):
    def _do_it():
        from models import SetLog
        for i in range(n_sets):
            db.session.add(SetLog(
                user_id=uid, exercise_name=exercise, week=week, day_idx=day_idx,
                set_number=i, weight=weight, reps=reps, done=True,
                logged_date=START,
            ))
        db.session.commit()
    _do(app_, _do_it)


# ── (a) block-3 user: hand-computed curve_target_today, despiked weight, ───
#     waist delta, Navy BF ────────────────────────────────────────────────
#
# curve_value(220.0, 2026-08-10, 2026-08-16): elapsed=6 days, all in week 1
# (rate 1.25 lb/wk) -> 220.0 - 6*(1.25/7) = 218.928571... -> round(.,4) = 218.9286
# pace_status(218.9, target=218.9286, tol=1.5): |218.9 - 218.9286| < 1.5 -> "on_pace"
#
# Navy BF (male) on the LATEST measurement row (waist=41.0, neck=15.0), height=69.0:
#   86.010*log10(41.0-15.0) - 70.041*log10(69.0) + 36.76
#   = 86.010*log10(26.0) - 70.041*log10(69.0) + 36.76
#   = 86.010*1.414973... - 70.041*1.838849... + 36.76
#   = 121.6985... - 128.7948... + 36.76 = 29.664... -> round(.,1) = 29.7

def test_block3_scoreboard_hand_computed_values(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-a@test.com")
    _seed_goal_and_state(app_, db, uid)
    _set_weights(app_, db, uid, [(START, 220.0), (WEEK1_DATE, 218.9)])
    _set_measurements(app_, db, uid, [(START, 42.0, 15.0), (WEEK1_DATE, 41.0, 15.0)])
    _set_height(app_, db, uid, 69.0)
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: WEEK1_DATE)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    sb = r.get_json()["scoreboard"]

    assert sb["curve_target_today"] == pytest.approx(218.5, abs=0.0001)  # 220 - 6*1.75/7; 218.9 is within 1.5 lb -> on_pace
    assert sb["on_curve"] == "on_pace"
    assert sb["current_weight_despiked"] == 218.9
    assert sb["waist"]["day0"] == 42.0
    assert sb["waist"]["latest"] == 41.0
    assert sb["waist"]["delta"] == pytest.approx(-1.0, abs=0.001)
    assert sb["bf_estimate_pct"] == pytest.approx(29.7, abs=0.05)
    # No lift data seeded -> lift-trend has insufficient history, not a false trip.
    assert sb["lift"]["suspected"] is False
    assert sb["lift"]["tonnage_delta_pct"] is None
    assert isinstance(sb["lift"]["details"], str) and sb["lift"]["details"]


# ── (b) on_curve agrees with the existing dashboard on_pace badge ──────────

def test_on_curve_agrees_with_dashboard_on_pace_badge(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-b-dash@test.com")
    _seed_goal_and_state(app_, db, uid)
    _set_weights(app_, db, uid, [(START, 220.0), (WEEK1_DATE, 218.9)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: WEEK1_DATE)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    on_pace = data["projections"]["on_pace"]
    on_curve = data["scoreboard"]["on_curve"]
    assert (on_curve != "behind") == on_pace


def test_on_curve_agrees_with_coach_cut_status_badge(app_ctx, clean_block3_flags, monkeypatch):
    """The OTHER existing badge — coach_assembler._build_cut_status's
    cut_status.on_curve — must read the identical value for the identical
    seeded state (requires goal_type == "cut" since _build_cut_status
    short-circuits to {"cut_status": None} for non-cut goals)."""
    app_, db = app_ctx
    import app as appmod
    import coach_assembler as ca
    from flask_login import login_user

    uid, email, client = _login(app_, db, "sb-b-coach@test.com")
    _seed_goal_and_state(app_, db, uid, goal_type="cut")
    _set_weights(app_, db, uid, [(START, 220.0), (WEEK1_DATE, 218.9)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: WEEK1_DATE)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    sb_on_curve = r.get_json()["scoreboard"]["on_curve"]

    def _do_it():
        from models import User
        u = User.query.get(uid)
        monkeypatch.setattr(ca, "_user_today", lambda: WEEK1_DATE)
        with app_.test_request_context():
            login_user(u, force=True)
            return ca._build_cut_status()["cut_status"]
    cs = _do(app_, _do_it)

    assert cs["on_curve"] == sb_on_curve


# ── (c) missing components -> nulls, never a crash ─────────────────────────

def test_missing_neck_yields_null_bf_but_rest_present(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-c-neck@test.com")
    _seed_goal_and_state(app_, db, uid)
    _set_weights(app_, db, uid, [(START, 220.0)])
    _set_measurements(app_, db, uid, [(START, 41.0, None)])  # waist present, neck absent
    _set_height(app_, db, uid, 69.0)
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: START)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    sb = r.get_json()["scoreboard"]

    assert sb["bf_estimate_pct"] is None
    # Rest of the panel still serves real values.
    assert sb["waist"]["day0"] == 41.0
    assert sb["waist"]["latest"] == 41.0
    assert sb["curve_target_today"] is not None
    assert sb["on_curve"] in ("behind", "ahead", "on_pace")
    assert sb["current_weight_despiked"] == 220.0


def test_missing_all_measurements_waist_nulls_no_crash(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-c-none@test.com")
    _seed_goal_and_state(app_, db, uid)
    _set_weights(app_, db, uid, [(START, 220.0)])
    _set_measurements(app_, db, uid, [])  # zero BodyMeasurement rows in-block
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: START)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    sb = r.get_json()["scoreboard"]

    assert sb["waist"] == {"day0": None, "latest": None, "delta": None}
    assert sb["bf_estimate_pct"] is None
    # Curve/pace fields are independent of measurements and still compute.
    assert sb["curve_target_today"] is not None
    assert sb["current_weight_despiked"] == 220.0


# ── (d) non-block-3 user -> no scoreboard key at all ────────────────────────

def test_non_block3_user_gets_no_scoreboard_key(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-d@test.com")
    _seed_goal_and_state(app_, db, uid, goal_type="cut")
    _set_weights(app_, db, uid, [(START, 220.0)])
    _set_measurements(app_, db, uid, [(START, 42.0, 15.0)])
    _set_height(app_, db, uid, 69.0)
    # Deliberately do NOT set the block-3 SystemFlags.
    monkeypatch.setattr(appmod, "_user_today", lambda: START)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["projections"]["projection_mode"] is None
    assert "scoreboard" not in data


# ── (e) falsy-zero trap: a 0.0 waist delta must survive, not be dropped ────

def test_zero_waist_delta_survives_falsy_check(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-e@test.com")
    _seed_goal_and_state(app_, db, uid)
    _set_weights(app_, db, uid, [(START, 220.0), (WEEK1_DATE, 220.0)])
    _set_measurements(app_, db, uid, [(START, 42.0, 15.0), (WEEK1_DATE, 42.0, 15.0)])
    _set_height(app_, db, uid, 69.0)
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: WEEK1_DATE)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    sb = r.get_json()["scoreboard"]

    assert sb["waist"]["day0"] == 42.0
    assert sb["waist"]["latest"] == 42.0
    # A falsy 0.0 must be served as 0.0, never dropped/None'd by a truthy check.
    assert sb["waist"]["delta"] is not None
    assert sb["waist"]["delta"] == 0.0


# ── (f) lift block agreement: scoreboard.lift matches lift_trend.lift_decline
#     directly, seeded with a real tonnage decline (>=10% down both recent
#     weeks vs best-of-reference) so "suspected" surfaces True, not just the
#     default-empty-history False path exercised in test (a) ───────────────

def test_lift_block_matches_lift_trend_output_on_a_real_decline(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "sb-f@test.com")
    _seed_goal_and_state(app_, db, uid)
    _set_weights(app_, db, uid, [(START, 220.0)])
    _set_block3_flags(app_, db)
    # Reference weeks 1-3: 3 sets x 200 x 5 = 3000 tonnage/week.
    for wk in (1, 2, 3):
        _add_sets(app_, db, uid, wk, "Barbell Bench Press", 200.0, 5, 3)
    # Week 4 is a COACH-CALLED deload (flag, not week number — 2026-08-30):
    # EXCLUDED entirely; give it a huge tonnage to prove it is never picked up
    # as "recent" or as part of the reference.
    _add_sets(app_, db, uid, 4, "Barbell Bench Press", 500.0, 10, 5)

    def _flag_wk4():
        from models import WeeklyDaySchedule
        for d in range(7):
            db.session.add(WeeklyDaySchedule(user_id=uid, week=4, day_idx=d,
                                             lift_name="x", deload=True,
                                             deload_reason="coach call"))
        db.session.commit()
    _do(app_, _flag_wk4)
    # Recent weeks 5-6: 3 sets x 150 x 5 = 2250 tonnage/week -> -25% vs 3000.
    for wk in (5, 6):
        _add_sets(app_, db, uid, wk, "Barbell Bench Press", 150.0, 5, 3)

    # today -> week 7 (elapsed 45 days from START) so _current_week()/upto_week
    # covers weeks 1-6.
    today = START + timedelta(days=45)
    monkeypatch.setattr(appmod, "_user_today", lambda: today)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    served_week = data["projections"]["current_week"]
    sb_lift = data["scoreboard"]["lift"]

    def _do_it():
        from lift_trend import lift_decline
        return lift_decline(uid, served_week)
    expected = _do(app_, _do_it)

    assert sb_lift["suspected"] == expected["lift_decline_suspected"]
    assert sb_lift["tonnage_delta_pct"] == expected["tonnage_delta_pct"]
    assert sb_lift["details"] == expected["details"]
    # Hand-verified: a real -25% tonnage decline across both recent weeks.
    assert sb_lift["suspected"] is True
    assert sb_lift["tonnage_delta_pct"] == pytest.approx(-25.0, abs=0.1)
