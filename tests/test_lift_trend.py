"""tests/test_lift_trend.py — TDD for the codified lift-decline detector
(Task 11): the recomp-goal "Line 2" tripwire. lift_trend.lift_decline is
the ONE shared definition; both the coach context (<lift_trend> block) and
weekly_report.compute_weekly_metrics must return identical numbers for the
same user/week — this is never LLM judgment.

Spec (section 5b): deload weeks (4/8/12) are excluded entirely (not
compared, not counted). Reference = best of the trailing 3 non-deload
weeks before the 2 most recent non-deload weeks. Trips on EITHER (a)
per-lift e1RM down >=5% on >=2 of 5 KEY_LIFTS for BOTH of the 2 most
recent non-deload weeks, OR (b) all-lift weekly tonnage down >=10% for
BOTH of those weeks vs the best-of-trailing-3 reference. Fewer than 3
prior non-deload weeks of data -> never trips.

Fixture pattern: SHORT-LIVED contexts (test_protocol_coach.py /
test_protocol_api.py style) — `app_ctx` only creates tables; every DB
write opens its own `with app_.app_context():` block, so nothing crosses
a session boundary.
"""
from datetime import date, timedelta

import pytest

import lift_trend


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _app_do(app_, fn):
    with app_.app_context():
        return fn()


def _make_user(app_, db, email):
    def _do():
        from models import User, SetLog
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="UTC")
            db.session.add(u)
            db.session.commit()
        SetLog.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _seed_sets(app_, db, user_id, week, exercise, weight, reps, n_sets=3, day_idx=1):
    """Log N working sets of `exercise` at (weight, reps) for `week` —
    each call appends after whatever sets already exist for that
    (user, week, exercise, day_idx), so a test can build up a session in
    more than one call without violating the SetLog unique constraint."""
    def _do():
        from models import SetLog
        logged_date = date(2026, 1, 5) + timedelta(weeks=week)
        existing = (SetLog.query
                    .filter_by(user_id=user_id, week=week, exercise_name=exercise, day_idx=day_idx)
                    .count())
        for i in range(n_sets):
            db.session.add(SetLog(
                user_id=user_id, week=week, day_idx=day_idx, set_number=existing + i,
                exercise_name=exercise, weight=weight, reps=reps, done=True,
                set_skipped=False, logged_date=logged_date,
            ))
        db.session.commit()
    return _app_do(app_, _do)


def _seed_all_key_lifts(app_, db, uid, week, weight, reps, n_sets=3, only=None):
    lifts = only if only is not None else lift_trend.KEY_LIFTS
    for lift in lifts:
        _seed_sets(app_, db, uid, week, lift, weight, reps, n_sets=n_sets)


# ── (a) e1RM path trips ──────────────────────────────────────────────────

def test_e1rm_path_trips_two_lifts_down_both_recent_weeks(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-e1rm-trip@test.com")

    # Reference: weeks 1,2,3 — all 5 key lifts at a stable baseline.
    for wk in (1, 2, 3):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=3)

    # Week 4 is a deload — deliberately NOT seeded (must never be needed).
    # Weeks 5,6 — the 2 most recent non-deload weeks. Bench + Squat drop
    # 10% (well past the 5% threshold); the other 3 lifts hold steady.
    for wk in (5, 6):
        _seed_sets(app_, db, uid, wk, "Barbell Bench Press", weight=90, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Barbell Back Squat", weight=90, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Conventional Deadlift", weight=100, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Barbell OHP", weight=100, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Barbell Bent-Over Row", weight=100, reps=5, n_sets=3)

    result = _app_do(app_, lambda: lift_trend.lift_decline(uid, 6))

    assert result["lift_decline_suspected"] is True
    assert result["e1rm_deltas"]["Barbell Bench Press"] <= -5
    assert result["e1rm_deltas"]["Barbell Back Squat"] <= -5
    assert result["e1rm_deltas"]["Conventional Deadlift"] == 0.0
    assert result["weeks_compared"] == [1, 2, 3, 5, 6]
    assert "Barbell Bench Press" in result["details"]
    assert "Barbell Back Squat" in result["details"]
    assert "LIFT DECLINE SUSPECTED" in result["details"]


# ── (b) tonnage path trips ───────────────────────────────────────────────

def test_tonnage_path_trips_all_lift_volume_down_both_recent_weeks(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-tonnage-trip@test.com")

    # Reference weeks 1,2,3: 5 key lifts + one NON-key lift, 5 sets each —
    # tonnage must aggregate across ALL logged lifts, not just the 5 key.
    for wk in (1, 2, 3):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=5)
        _seed_sets(app_, db, uid, wk, "Leg Press", weight=200, reps=8, n_sets=5)

    # Weeks 9,10 — the 2 most recent non-deload weeks. SAME weight/reps as
    # reference (so per-lift e1RM is UNCHANGED — isolates the tonnage
    # path), but fewer sets -> total volume down 20% (past the 10%
    # threshold) both weeks.
    for wk in (9, 10):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=4)
        _seed_sets(app_, db, uid, wk, "Leg Press", weight=200, reps=8, n_sets=4)

    result = _app_do(app_, lambda: lift_trend.lift_decline(uid, 10))

    assert result["lift_decline_suspected"] is True
    assert result["tonnage_delta_pct"] == -20.0
    # e1RM untouched (weight/reps identical) -> the e1RM path did NOT trip;
    # tonnage alone is responsible.
    for lift in lift_trend.KEY_LIFTS:
        assert result["e1rm_deltas"][lift] == 0.0
    assert "tonnage" in result["details"].lower()


# ── (c) does NOT trip on a single bad week followed by recovery ─────────

def test_one_bad_week_then_recovery_does_not_trip(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-recovery@test.com")

    for wk in (1, 2, 3):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=3)

    # Week 5: bad (2 lifts down hard). Week 6: fully recovered to baseline.
    _seed_sets(app_, db, uid, 5, "Barbell Bench Press", weight=85, reps=5, n_sets=3)
    _seed_sets(app_, db, uid, 5, "Barbell Back Squat", weight=85, reps=5, n_sets=3)
    _seed_sets(app_, db, uid, 5, "Conventional Deadlift", weight=100, reps=5, n_sets=3)
    _seed_sets(app_, db, uid, 5, "Barbell OHP", weight=100, reps=5, n_sets=3)
    _seed_sets(app_, db, uid, 5, "Barbell Bent-Over Row", weight=100, reps=5, n_sets=3)
    _seed_all_key_lifts(app_, db, uid, 6, weight=100, reps=5, n_sets=3)

    result = _app_do(app_, lambda: lift_trend.lift_decline(uid, 6))

    assert result["lift_decline_suspected"] is False
    assert "no decline detected" in result["details"]
    # Most-recent week (6) is fully recovered vs reference.
    for lift in lift_trend.KEY_LIFTS:
        assert result["e1rm_deltas"][lift] == 0.0


# ── (d) does NOT trip across a deload week (week 8 skipped, not counted) ──

def test_deload_week_in_the_window_is_skipped_not_counted(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-deload-skip@test.com")

    # Reference: weeks 5,6,7.
    for wk in (5, 6, 7):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=3)

    # Week 8 is a deload, LOGGED LOW on purpose (would look like a sharp
    # decline if the detector ever mistakes it for a real comparison week
    # — either as part of the reference or as one of the "2 most recent").
    _seed_all_key_lifts(app_, db, uid, 8, weight=50, reps=5, n_sets=3)

    def _flag_wk8():  # 2026-08-30: a deload is a coach-called flag, not a week number
        from models import WeeklyDaySchedule
        for d in range(7):
            db.session.add(WeeklyDaySchedule(user_id=uid, week=8, day_idx=d,
                                             lift_name="x", deload=True,
                                             deload_reason="coach call"))
        db.session.commit()
    _app_do(app_, _flag_wk8)

    # Weeks 9,10 — the true 2 most recent non-deload weeks, back at
    # baseline (no real decline).
    for wk in (9, 10):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=3)

    result = _app_do(app_, lambda: lift_trend.lift_decline(uid, 10))

    assert result["lift_decline_suspected"] is False
    assert 8 not in result["weeks_compared"]
    assert result["weeks_compared"] == [5, 6, 7, 9, 10]


# ── (e) fewer than 3 prior non-deload weeks -> never trips, honest weeks ──

def test_insufficient_reference_history_never_trips(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-insufficient@test.com")

    # Only 2 weeks of data ever logged, and both are LOW relative to
    # nothing (there's no reference at all) — must not trip regardless.
    _seed_all_key_lifts(app_, db, uid, 1, weight=100, reps=5, n_sets=3)
    _seed_all_key_lifts(app_, db, uid, 2, weight=50, reps=5, n_sets=3)

    result = _app_do(app_, lambda: lift_trend.lift_decline(uid, 2))

    assert result["lift_decline_suspected"] is False
    assert result["weeks_compared"] == [1, 2]  # honest: what existed
    assert result["tonnage_delta_pct"] is None
    for lift in lift_trend.KEY_LIFTS:
        assert result["e1rm_deltas"][lift] is None
    assert "no decline detected" in result["details"]


def test_zero_weeks_of_data_never_trips(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-zero@test.com")

    result = _app_do(app_, lambda: lift_trend.lift_decline(uid, 3))

    assert result["lift_decline_suspected"] is False
    assert result["weeks_compared"] == []
    assert all(v is None for v in result["e1rm_deltas"].values())
    assert result["tonnage_delta_pct"] is None


# ── (f) bodyweight sentinel rows (weight=0) excluded from tonnage ───────

def test_bodyweight_sentinel_rows_do_not_change_tonnage(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-sentinel@test.com")

    _seed_sets(app_, db, uid, 6, "Barbell Bench Press", weight=100, reps=5, n_sets=3)
    before = _app_do(app_, lambda: lift_trend._tonnage_for_week(uid, 6))

    # Bodyweight sentinel rows: weight=0, real reps logged (e.g. pull-ups).
    _seed_sets(app_, db, uid, 6, "Bodyweight Pull-up", weight=0, reps=10, n_sets=5)
    after = _app_do(app_, lambda: lift_trend._tonnage_for_week(uid, 6))

    assert before == 1500.0  # 100 * 5 * 3
    assert after == before  # sentinel rows contribute nothing


# ── (g) coach context builder and compute_weekly_metrics agree exactly ──

def test_coach_context_and_weekly_report_return_identical_dicts(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "lt-shared@test.com")

    for wk in (1, 2, 3):
        _seed_all_key_lifts(app_, db, uid, wk, weight=100, reps=5, n_sets=3)
    for wk in (5, 6):
        _seed_sets(app_, db, uid, wk, "Barbell Bench Press", weight=90, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Barbell Back Squat", weight=90, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Conventional Deadlift", weight=100, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Barbell OHP", weight=100, reps=5, n_sets=3)
        _seed_sets(app_, db, uid, wk, "Barbell Bent-Over Row", weight=100, reps=5, n_sets=3)

    def _via_coach():
        from flask_login import login_user
        from models import User
        import coach_assembler as ca
        with app_.test_request_context():
            u = User.query.get(uid)
            login_user(u, force=True)
            ca._current_week = ca._current_week  # no-op, keep default
            import unittest.mock as mock
            with mock.patch.object(ca, "_current_week", return_value=6):
                return ca._build_lift_trend()["lift_trend"]

    def _via_report():
        from weekly_report import compute_weekly_metrics
        return compute_weekly_metrics(6, user_id=uid)["lift_trend"]

    coach_dict = _via_coach()
    report_dict = _app_do(app_, _via_report)

    assert coach_dict == report_dict
    assert coach_dict["lift_decline_suspected"] is True


# ── (h) prompt injection: tripped vs not-tripped ─────────────────────────

def test_prompt_renders_lift_decline_suspected_line_when_tripped(app_ctx):
    app_, db = app_ctx
    from coach_assembler import assemble_prompt
    from flask_login import login_user
    from models import User
    uid = _make_user(app_, db, "lt-prompt-trip@test.com")
    u = _app_do(app_, lambda: User.query.get(uid))

    ctx = {
        "athlete_name": "Erik",
        "lift_trend": {
            "lift_decline_suspected": True,
            "e1rm_deltas": {"Barbell Bench Press": -9.5, "Barbell Back Squat": -6.1,
                             "Conventional Deadlift": None, "Barbell OHP": 0.0,
                             "Barbell Bent-Over Row": 0.0},
            "tonnage_delta_pct": -3.2,
            "weeks_compared": [1, 2, 3, 5, 6],
            "details": "LIFT DECLINE SUSPECTED: e1RM down on Barbell Bench Press, Barbell Back Squat",
        },
    }
    with app_.test_request_context():
        login_user(u, force=True)
        prompt = assemble_prompt("conversation", ctx)

    assert "<lift_trend>" in prompt
    assert "LIFT_DECLINE_SUSPECTED:" in prompt
    assert "Barbell Bench Press" in prompt
    assert "weeks_compared" in prompt or "[1, 2, 3, 5, 6]" in prompt


def test_prompt_renders_no_decline_one_liner_when_not_tripped(app_ctx):
    app_, db = app_ctx
    from coach_assembler import assemble_prompt
    from flask_login import login_user
    from models import User
    uid = _make_user(app_, db, "lt-prompt-notrip@test.com")
    u = _app_do(app_, lambda: User.query.get(uid))

    ctx = {
        "athlete_name": "Erik",
        "lift_trend": {
            "lift_decline_suspected": False,
            "e1rm_deltas": {lift: 0.0 for lift in lift_trend.KEY_LIFTS},
            "tonnage_delta_pct": 1.5,
            "weeks_compared": [1, 2, 3, 5, 6],
            "details": "no decline detected (weeks [5, 6] vs best of reference weeks [1, 2, 3])",
        },
    }
    with app_.test_request_context():
        login_user(u, force=True)
        prompt = assemble_prompt("conversation", ctx)

    assert "LIFT_DECLINE_SUSPECTED" not in prompt
    assert "lift_trend: no decline" in prompt
    assert "5/6" in prompt or "5, 6" in prompt


# ── agents wiring ─────────────────────────────────────────────────────────

def test_lift_trend_wired_into_expected_agents():
    """lift_trend goes to the same 4 agents that require protocol_status
    (conversation, morning_checkin, meals_complete, nutritionist — the
    cut-adjacent moments) PLUS strength_coach: the dedicated lifting
    specialist agent, whose requires already centers on workout_today /
    today_sets / exercise_history / exercise_analysis for exactly this
    kind of lift-performance judgment."""
    from coach_agents import AGENTS

    expected = {"conversation", "morning_checkin", "meals_complete", "nutritionist", "strength_coach"}
    for name in expected:
        assert "lift_trend" in AGENTS[name]["requires"], f"{name} missing lift_trend"

    # 2026-08-28: the old negative check here ("no other agent may see
    # lift_trend") was the opting-out pattern that blinded agents five times
    # over. Every athlete-facing agent now gets CORE_SECTIONS — see
    # tests/test_core_sections_every_agent.py.


# ── constants sanity ──────────────────────────────────────────────────────

def test_key_lifts_and_deload_weeks_constants():
    assert lift_trend.KEY_LIFTS == [
        "Barbell Bench Press", "Barbell Back Squat", "Conventional Deadlift",
        "Barbell OHP", "Barbell Bent-Over Row",
    ]
    assert not hasattr(lift_trend, "DELOAD_WEEKS")  # 2026-08-30: deloads are coach-called flags, not week numbers
