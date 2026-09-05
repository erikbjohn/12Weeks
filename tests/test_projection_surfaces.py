"""tests/test_projection_surfaces.py — every weight-projection surface reads
the SAME canonical block-3 curve (goal_engine.build_block3_projection /
curve_value / pace_status), gated on SystemFlag(key="projection_mode",
value="piecewise_block3") + SystemFlag(key="block3_anchor").

Covers (see task-13-brief.md fates 1-12):
  (a) dashboard payload: linear_plan == curve rows, projection_mode present.
  (b) on_pace: True at week-1 (218.9 on-curve weigh-in), False at a week-8
      stall (weight stuck at 210 vs curve ~204.5, tolerance 1.5).
  (c) /api/goal/recalibrate + /api/deficit-plan are retired -> 410.
  (d) coach_assembler cut_status.curve_target_today / on_curve agree with
      the dashboard's on_pace for identical inputs.
  (e) weekly_report.weight_vs_projected == "on_track" for a week-1 weigh-in
      close to the curve's week-1 target (218.75).
  (f) /api/admin/debug/regenerate-projection rebuilds the SAME 12 rows from
      the stored anchor when block-3 mode is on.
  (g) _compute_goal_for_user (via /api/goal/compute) preserves the stored
      curve under the flag; override_projection_mode=true lets it overwrite.
  (h) FLAG-ABSENT REGRESSION: without the SystemFlags, every surface above
      falls back to its legacy (pre-curve) behavior, unchanged.

SystemFlag handoff note: the transition (Task 15) must write BOTH flags —
SystemFlag(key="projection_mode", value="piecewise_block3") AND
SystemFlag(key="block3_anchor", value="<float as str>") — the anchor flag is
what lets every consumer (app.py, coach_assembler.py) rebuild the curve
without recomputing it from TrainingGoal.weight_projection[0].

App-context handling: SHORT-LIVED contexts only (matches
tests/test_protocol_api.py and tests/test_protocol_ui_payload.py's documented
pattern, NOT the module-scoped held-open `app_ctx` most other test files
use) — this module needs BOTH plain `client.get/post()` calls AND direct
`login_user(force=True)` + coach_assembler calls, and flask-login caches
current_user on the active app context's `g`; a held-open context leaks one
call's identity into the next unless every context is pushed and popped
per-operation.
"""
from datetime import date, timedelta

import pytest

ANCHOR = 220.0
START = date(2026, 8, 10)


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
    tests so the flag-present and flag-absent scenarios never leak into each
    other."""
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


def _seed_goal_and_state(app_, db, uid, weight_projection, target_weight=195.0,
                          start_date=START, goal_type="cut"):
    def _do_it():
        from models import TrainingGoal, AppState
        TrainingGoal.query.filter_by(user_id=uid).delete()
        AppState.query.filter_by(user_id=uid).delete()
        db.session.commit()
        db.session.add(TrainingGoal(
            user_id=uid, goal_type=goal_type, target_weight=target_weight,
            daily_calories=1800, tdee=2800, weight_projection=weight_projection,
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


def _get_goal(app_, db, uid):
    def _do_it():
        from models import TrainingGoal
        g = TrainingGoal.query.filter_by(user_id=uid).first()
        return g.weight_projection
    return _do(app_, _do_it)


# ── (a) dashboard: linear_plan == curve rows, projection_mode present ──────

def test_dashboard_linear_plan_is_curve_rows_under_block3_flag(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-dash-a@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    _set_weights(app_, db, uid, [(START, ANCHOR)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: START)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    linear_plan = data["projections"]["linear_plan"]
    assert linear_plan == [{"week": row["week"], "planned_weight": row["projected"]} for row in proj]
    assert data["projections"]["projection_mode"] == "piecewise_block3"


# ── (b) on_pace: True at week-1 on-curve, False at week-8 stall ────────────

def test_on_pace_true_at_week1_near_curve(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-onpace-w1@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    # curve_value(220, Aug10, Aug16) == 220 - 6*1.25/7 == 218.93 -> 218.9 is on-curve.
    week1_date = START + timedelta(days=6)
    _set_weights(app_, db, uid, [(START, ANCHOR), (week1_date, 218.9)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: week1_date)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["projections"]["on_pace"] is True


def test_on_pace_false_at_week8_stall(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from goal_engine import build_block3_projection, curve_value

    uid, email, client = _login(app_, db, "b3-onpace-w8@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    stall_date = date(2026, 10, 5)  # START + 56 days == exactly 8 curve weeks
    target = curve_value(ANCHOR, START, stall_date)
    assert target == pytest.approx(198.3)  # 220 - (2*1.75 + 4*2.8 + 2*3.5)
    # Weight logged weeks ago and never updated since -- a stall.
    _set_weights(app_, db, uid, [(START, ANCHOR), (START + timedelta(days=41), 210.0)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: stall_date)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["projections"]["on_pace"] is False


# ── (c) recalibrate + deficit-plan are retired ──────────────────────────────

def test_goal_recalibrate_is_retired(app_ctx, clean_block3_flags):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "b3-retired-recal@test.com")
    r = client.post("/api/goal/recalibrate", json={"weight": 200, "week": 3})
    assert r.status_code == 410, r.get_data(as_text=True)
    assert "error" in (r.get_json() or {})


def test_deficit_plan_is_retired(app_ctx, clean_block3_flags):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "b3-retired-deficit@test.com")
    r = client.post("/api/deficit-plan", json={})
    assert r.status_code == 410, r.get_data(as_text=True)
    assert "error" in (r.get_json() or {})


def test_recalibrate_projection_deleted_from_goal_engine():
    import goal_engine
    assert not hasattr(goal_engine, "recalibrate_projection")


# ── (d) coach_assembler cut_status agrees with dashboard on_pace ───────────

def test_cut_status_curve_fields_agree_with_dashboard_on_pace(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import coach_assembler as ca
    from flask_login import login_user
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-cutstatus@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    week1_date = START + timedelta(days=6)
    _set_weights(app_, db, uid, [(START, ANCHOR), (week1_date, 218.9)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: week1_date)

    r = client.get("/api/progress/dashboard")
    dash_on_pace = r.get_json()["projections"]["on_pace"]

    def _do_it():
        from models import User
        u = User.query.get(uid)
        monkeypatch.setattr(ca, "_user_today", lambda: week1_date)
        with app_.test_request_context():
            login_user(u, force=True)
            return ca._build_cut_status()["cut_status"]
    cs = _do(app_, _do_it)

    assert cs["curve_target_today"] == pytest.approx(218.5, abs=0.01)  # 220 - 6*1.75/7
    assert cs["on_curve"] in ("behind", "ahead", "on_pace")
    assert (cs["on_curve"] != "behind") == dash_on_pace
    # Existing keys still present (fate 5: never drop existing keys).
    for key in ("current_weight", "target_weight", "pace_per_week",
                "water_spike_suspected", "weekly_deficit_estimate", "tdee"):
        assert key in cs


def test_despike_window_matches_across_dashboard_and_cutstatus(app_ctx, clean_block3_flags, monkeypatch):
    """Fix-round-1 reviewer repro (CRITICAL #1): app._despiked_current_weight
    used to read a GLOBAL (all-time) BodyWeight window while cut_status's bws
    is BLOCK-SCOPED (>= AppState.start_date). With pre-block history present
    (228 @ Jul28, 220.5 @ Aug5 -- both before start_date Aug10) and a single
    in-block weigh-in (227 @ Aug10), the dashboard could despike off the
    cross-block rows (spike detected: latest 227 vs prior 220.5, adjusted
    step ~7.4 lb -> anchors on 220.5 -> on_pace True/green) while cut_status's
    block-scoped window sees only the raw 227 with <3 rows (can't confirm a
    spike -> judges 227 raw -> on_curve "behind") -- a same-instant,
    same-user contradiction. Both now read the SAME block-scoped window: with
    only ONE in-block row, NEITHER surface can spike-check, so both judge the
    raw 227 against the curve and AGREE ("behind"-consistent)."""
    app_, db = app_ctx
    import app as appmod
    import coach_assembler as ca
    from flask_login import login_user
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-despike-window@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    _set_weights(app_, db, uid, [
        (date(2026, 7, 28), 228.0),   # pre-block (before AppState.start_date)
        (date(2026, 8, 5), 220.5),    # pre-block
        (START, 227.0),               # the ONLY in-block row
    ])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: START)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    dash_on_pace = r.get_json()["projections"]["on_pace"]

    def _do_it():
        from models import User
        u = User.query.get(uid)
        monkeypatch.setattr(ca, "_user_today", lambda: START)
        with app_.test_request_context():
            login_user(u, force=True)
            return ca._build_cut_status()["cut_status"]
    cs = _do(app_, _do_it)

    # Curve target at elapsed=0 is the anchor (220.0); the raw 227 is 7 lb
    # over tolerance (1.5) on BOTH surfaces -- "behind" on both sides.
    assert cs["on_curve"] == "behind"
    assert dash_on_pace is False


# ── (e) weekly_report weight_vs_projected agrees at week-1 ──────────────────

def test_weekly_report_on_track_at_week1_curve_target(app_ctx, clean_block3_flags):
    app_, db = app_ctx
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-weeklyreport@test.com")
    proj = build_block3_projection(ANCHOR, START)  # week 1 -> 218.75
    _seed_goal_and_state(app_, db, uid, proj)
    _set_block3_flags(app_, db)

    def _do_it():
        from models import BodyWeight
        BodyWeight.query.filter_by(user_id=uid).delete()
        db.session.add(BodyWeight(user_id=uid, weight_lbs=218.5, log_date=date.today()))
        db.session.commit()
        import weekly_report
        return weekly_report.compute_weekly_metrics(1, user_id=uid)
    metrics = _do(app_, _do_it)
    assert metrics["weight_vs_projected"] == "on_track"


# ── (f) regenerate-projection rebuilds the same 12 rows from stored anchor ─

def test_regenerate_projection_rebuilds_curve_from_stored_anchor(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-regen@test.com")
    proj = build_block3_projection(ANCHOR, START)
    # Seed a DIFFERENT (stale) projection to prove regenerate rebuilds it.
    stale = [{"week": w, "projected": 999.0} for w in range(1, 13)]
    _seed_goal_and_state(app_, db, uid, stale)
    _set_block3_flags(app_, db)

    admin_key = "test-admin-key-b3-long-enough-for-guard"
    monkeypatch.setenv("ADMIN_API_KEY", admin_key)
    r = client.post(
        "/api/admin/debug/regenerate-projection",
        json={"email": email, "starting_weight": 12345},  # must be IGNORED in block3 mode
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["after"] == proj
    assert _get_goal(app_, db, uid) == proj


# ── (g) _compute_goal_for_user preserves the curve; override writes fresh ──

def test_goal_compute_preserves_curve_under_flag(app_ctx, clean_block3_flags):
    app_, db = app_ctx
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-preserve@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    _set_weights(app_, db, uid, [(START, ANCHOR)])
    _set_block3_flags(app_, db)

    r = client.post("/api/goal/compute", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _get_goal(app_, db, uid) == proj  # untouched


def test_goal_compute_overwrites_with_explicit_override(app_ctx, clean_block3_flags):
    app_, db = app_ctx
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-override@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    _set_weights(app_, db, uid, [(START, ANCHOR)])
    _set_block3_flags(app_, db)

    # S113: the USER endpoint no longer forwards override_projection_mode —
    # the block-3 curve is preserved no matter what a client sends.
    r = client.post("/api/goal/compute", json={"override_projection_mode": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _get_goal(app_, db, uid) == proj

    # The override is an ADMIN action (server-side call with the flag).
    import app as appmod
    from models import User
    with app_.app_context():
        u = User.query.get(uid)
        with app_.test_request_context():
            from flask_login import login_user
            login_user(u, force=True)
            appmod._compute_goal_for_user(u, overrides={"override_projection_mode": True})
    new_proj = _get_goal(app_, db, uid)
    assert new_proj != proj
    # Legacy project_weight_curve rows carry a "tdee" key; curve rows don't.
    assert "tdee" in new_proj[0]


def test_goal_compute_writes_canonical_curve_for_fresh_user_under_flag(app_ctx, clean_block3_flags):
    """Fix-round-1 reviewer repro (IMPORTANT #2): a user's FIRST-EVER goal
    compute while the flag is set has existing_goal is None, which used to
    bypass the preserve-guard entirely and fall through to the LEGACY
    project_weight_curve shape. The canonical curve must be the default
    output everywhere the flag is set -- never the legacy re-simulation --
    so a brand-new user onboarded after the block-3 transition gets the same
    curve every other surface reads, from their very first compute."""
    app_, db = app_ctx
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "b3-fresh-goal@test.com")

    def _seed_fresh():
        from models import PsychIntake, PhysicalAssessment, AppState, BodyWeight, TrainingGoal
        TrainingGoal.query.filter_by(user_id=uid).delete()
        PsychIntake.query.filter_by(user_id=uid).delete()
        PhysicalAssessment.query.filter_by(user_id=uid).delete()
        AppState.query.filter_by(user_id=uid).delete()
        BodyWeight.query.filter_by(user_id=uid).delete()
        db.session.commit()
        db.session.add(PsychIntake(user_id=uid, conversation=[]))
        db.session.add(PhysicalAssessment(user_id=uid, height_inches=70, bodyweight_lbs=220.0))
        db.session.add(AppState(user_id=uid, current_week=1, start_date=START))
        db.session.add(BodyWeight(user_id=uid, weight_lbs=220.0, log_date=START))
        db.session.commit()
    _do(app_, _seed_fresh)
    _set_block3_flags(app_, db)  # anchor == ANCHOR == 220.0

    r = client.post("/api/goal/compute", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()

    expected = build_block3_projection(ANCHOR, START)
    assert body["weight_projection"] == expected
    assert "tdee" not in body["weight_projection"][0]  # never the legacy shape
    assert _get_goal(app_, db, uid) == expected


# ── (h) FLAG-ABSENT REGRESSION: every surface falls back to legacy ─────────

def test_regression_dashboard_legacy_straight_line_without_flag(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid, email, client = _login(app_, db, "legacy-dash@test.com")
    _seed_goal_and_state(app_, db, uid, weight_projection=None, target_weight=195.0)
    _set_weights(app_, db, uid, [(START, 220.0), (START + timedelta(days=7), 217.0)])
    monkeypatch.setattr(appmod, "_user_today", lambda: START + timedelta(days=7))

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    linear_plan = data["projections"]["linear_plan"]
    # Legacy straight line: ALL 12 weeks, not just the endpoints -- a partial
    # (first/last only) check could hide a broken interior formula.
    expected = [{"week": w, "planned_weight": round(220.0 + (195.0 - 220.0) * ((w - 1) / 11.0), 1)}
                for w in range(1, 13)]
    assert linear_plan == expected
    assert data["projections"].get("projection_mode") is None


def test_regression_recalibrate_and_deficit_plan_still_retired_without_flag(app_ctx, clean_block3_flags):
    # Retirement (fate 8/9) is unconditional -- not gated on the flag at all.
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "legacy-retired@test.com")
    assert client.post("/api/goal/recalibrate", json={"weight": 200, "week": 3}).status_code == 410
    assert client.post("/api/deficit-plan", json={}).status_code == 410


def test_regression_goal_compute_overwrites_projection_without_flag(app_ctx, clean_block3_flags):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "legacy-goalcompute@test.com")
    stale = [{"week": w, "projected": 999.0} for w in range(1, 13)]
    _seed_goal_and_state(app_, db, uid, stale, target_weight=185.0)
    _set_weights(app_, db, uid, [(START, 220.0)])

    r = client.post("/api/goal/compute", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _get_goal(app_, db, uid) != stale  # legacy path recomputed it, as before


def test_regression_cut_status_has_no_curve_fields_without_flag(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user

    uid, email, client = _login(app_, db, "legacy-cutstatus@test.com")
    _seed_goal_and_state(app_, db, uid, weight_projection=None, target_weight=185.0)
    later = START + timedelta(days=7)
    _set_weights(app_, db, uid, [(START, 220.0), (later, 217.0)])

    def _do_it():
        from models import User
        u = User.query.get(uid)
        monkeypatch.setattr(ca, "_user_today", lambda: later)
        with app_.test_request_context():
            login_user(u, force=True)
            return ca._build_cut_status()["cut_status"]
    cs = _do(app_, _do_it)

    assert cs.get("curve_target_today") is None
    assert cs.get("on_curve") is None


# ── fate 12: weekly-gen required_weekly uses the curve's next-week delta ───

def _generate_and_wait(client, payload, timeout=30):
    import time
    resp = client.post("/api/weekly-program/generate", json=payload)
    if resp.status_code != 200:
        return resp.status_code, resp.get_json()
    body = resp.get_json() or {}
    if body.get("status") != "started":
        return resp.status_code, body
    week = payload.get("week")
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/weekly-program/generate-status?week={week}").get_json() or {}
        if j.get("status") in ("done", "error"):
            return 200, j
        time.sleep(0.2)
    return 200, {"status": "timeout"}


def test_weekly_gen_required_weekly_uses_curve_delta_under_block3_flag(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import coach_planning_program, coach_planning_runs, coach_planning_meals
    from goal_engine import build_block3_projection, curve_value

    uid, email, client = _login(app_, db, "b3-weeklygen@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj)
    today = START + timedelta(days=6)  # Aug16 -- still week 1
    _set_weights(app_, db, uid, [(START, ANCHOR), (today, 218.9)])
    _set_block3_flags(app_, db)
    monkeypatch.setattr(appmod, "_user_today", lambda: today)
    # No real LLM calls -- deterministic empty coach output.
    monkeypatch.setattr(coach_planning_program, "generate_week_program", lambda **k: ({}, [], {"deload": False, "reason": None}))
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs", lambda **k: {})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals", lambda **k: {})

    status, body = _generate_and_wait(client, {"week": 1, "force_regen": True})
    assert status == 200 and body.get("status") == "done", body

    expected = curve_value(ANCHOR, START, today) - curve_value(ANCHOR, START, today + timedelta(days=7))
    assert body["deficit"]["required_weekly_loss"] == round(expected, 1)


def test_regression_weekly_gen_required_weekly_is_legacy_without_flag(app_ctx, clean_block3_flags, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import coach_planning_program, coach_planning_runs, coach_planning_meals

    uid, email, client = _login(app_, db, "legacy-weeklygen@test.com")
    _seed_goal_and_state(app_, db, uid, weight_projection=None, target_weight=185.0)
    today = START + timedelta(days=6)
    _set_weights(app_, db, uid, [(START, 220.0), (today, 218.0)])
    monkeypatch.setattr(appmod, "_user_today", lambda: today)
    monkeypatch.setattr(coach_planning_program, "generate_week_program", lambda **k: ({}, [], {"deload": False, "reason": None}))
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs", lambda **k: {})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals", lambda **k: {})

    status, body = _generate_and_wait(client, {"week": 1, "force_regen": True})
    assert status == 200 and body.get("status") == "done", body

    weeks_remaining = max(1, 12 - 1 + 1)
    expected = (218.0 - 185.0) / weeks_remaining
    assert body["deficit"]["required_weekly_loss"] == round(expected, 1)
