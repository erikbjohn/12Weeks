"""tests/test_block3_transition.py — the block-2 -> block-3 transactional
transition and its ordered rollback (transition_block3.py).

Integration-style against a prod-shaped fixture: real block-1 history at
weeks 13-24 (including a full 7/7 RunLog+SetLog week, exercising the
unique-constrained tables across the shift), real block-2 history at weeks
1-7 with TODAY's (2026-08-10) week-7 day-0 row, a cut TrainingGoal, and
AppState(start_date=2026-06-29, current_week=7) — the exact prod shape
described in transition_block3.py's module docstring.

Covers:
  (a) dry_run mutates nothing (histogram counts unchanged, no flags written).
  (b) transition: block-1 intact at 25-36, block-2 at 13-18, today's
      run+sets re-homed to week 1 day 0, zero rows at week 7 or 19,
      AppState/TrainingGoal/flags/BodyWeight/LabReminders all set,
      weight_projection == build_block3_projection(anchor, start).
  (c) destination-not-empty guard: a stray week-30 row -> 409, nothing
      changed.
  (d) block-3 work logged post-transition, then rollback -> prestate
      histograms exactly restored (log tables, incl. today's rows back at
      week 7), block-3 work PARKED at week>=100 (never deleted), the new
      plan row gone, TrainingGoal/AppState restored, flags cleared,
      protocol tables empty.
  (e) transition on a user with no cut goal -> 409.
  (f) idempotency guard: running transition twice -> second call 409.
"""
from datetime import date, timedelta

import pytest

ANCHOR = 220.0
TRANSITION_DATE = date(2026, 8, 10)
BLOCK2_START = date(2026, 6, 29)  # Monday; week 1 day 0 == this date


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _do(app_, fn):
    """Run fn() inside a fresh, short-lived app context."""
    with app_.app_context():
        return fn()


@pytest.fixture()
def clean_block3_flags(app_ctx):
    """SystemFlag is global — reset before AND after each test so one
    test's transitioned state never leaks into the next (e.g. the
    idempotency-guard test)."""
    app_, db = app_ctx

    def _clear():
        from models import SystemFlag
        SystemFlag.query.filter(
            SystemFlag.key.in_(["projection_mode", "block3_anchor", "block3_prestate"])
        ).delete(synchronize_session=False)
        db.session.commit()

    _do(app_, _clear)
    yield
    _do(app_, _clear)


def _log_date(week, day_idx, start=BLOCK2_START):
    return start + timedelta(days=(week - 1) * 7 + day_idx)


# ── Fixture builders ────────────────────────────────────────────────────

def _seed_day(db, user_id, week, day_idx, log_date, tag):
    """One row in EVERY day-grain shifted table (18 of the 21) at
    (week, day_idx)."""
    from models import (
        SessionAnalysis, ExerciseLog, SetLog, ExerciseSwap, ExerciseCompletion,
        WarmupCompletion, RunLog, DayCompletion, GarminActivity, GarminWorkoutLink,
        WeeklyScheduleOverride, MealPlanOverride, RunOverride, WeeklyPrescription,
        WeeklyMealPlan, WeeklyRunPlan, WeeklyWarmup, WeeklyDaySchedule,
    )
    db.session.add(SessionAnalysis(user_id=user_id, week=week, day_idx=day_idx,
                                    log_date=log_date, overall_compliance=0.9))
    db.session.add(ExerciseLog(user_id=user_id, exercise_name=f"Bench-{tag}", weight=135,
                                week=week, day_idx=day_idx, logged_date=log_date))
    db.session.add(SetLog(user_id=user_id, exercise_name="Bench Press", week=week,
                           day_idx=day_idx, set_number=0, weight=135, reps=8, logged_date=log_date))
    db.session.add(SetLog(user_id=user_id, exercise_name="Bench Press", week=week,
                           day_idx=day_idx, set_number=1, weight=135, reps=8, logged_date=log_date))
    db.session.add(SetLog(user_id=user_id, exercise_name="Squat", week=week,
                           day_idx=day_idx, set_number=0, weight=185, reps=6, logged_date=log_date))
    db.session.add(ExerciseSwap(user_id=user_id, week=week, day_idx=day_idx,
                                 exercise_idx=0, swapped_to="Incline Press"))
    db.session.add(ExerciseCompletion(user_id=user_id, week=week, day_idx=day_idx,
                                       exercise_idx=0, done=True))
    db.session.add(WarmupCompletion(user_id=user_id, week=week, day_idx=day_idx,
                                     step_idx=0, done=True))
    db.session.add(RunLog(user_id=user_id, week=week, day_idx=day_idx, log_date=log_date,
                           distance_miles=3.1, duration_min=28, source="manual"))
    db.session.add(DayCompletion(user_id=user_id, week=week, day_idx=day_idx, done=True,
                                  completed_at=log_date.isoformat()))
    db.session.add(GarminActivity(user_id=user_id, garmin_activity_id=f"gid-{tag}",
                                   week=week, day_idx=day_idx, activity_date=log_date,
                                   distance_miles=3.1))
    db.session.add(GarminWorkoutLink(user_id=user_id, week=week, day_idx=day_idx,
                                      garmin_workout_id=f"wid-{tag}", scheduled_date=log_date))
    db.session.add(WeeklyScheduleOverride(user_id=user_id, week=week, day_idx=day_idx,
                                           workout_time="6:00am"))
    db.session.add(MealPlanOverride(user_id=user_id, week=week, day_idx=day_idx,
                                     meal_type="fast_day", daily_calories=1800))
    db.session.add(RunOverride(user_id=user_id, week=week, day_idx=day_idx,
                                duration="30 min", run_type="easy"))
    db.session.add(WeeklyPrescription(user_id=user_id, week=week, day_idx=day_idx,
                                       exercise_order=0, exercise_name="Bench Press",
                                       sets=3, reps="8-10"))
    db.session.add(WeeklyMealPlan(user_id=user_id, week=week, day_idx=day_idx,
                                   meal_data={"meals": []}, daily_calories=1800))
    db.session.add(WeeklyRunPlan(user_id=user_id, week=week, day_idx=day_idx,
                                  run_type="z2", label="Zone 2", duration="30 min"))
    db.session.add(WeeklyWarmup(user_id=user_id, week=week, day_idx=day_idx,
                                 warmup_data=[{"name": "Arm circles"}]))
    db.session.add(WeeklyDaySchedule(user_id=user_id, week=week, day_idx=day_idx,
                                      lift_name="Upper A", muscle_groups=["chest", "back"]))


def _seed_week(db, user_id, week, log_date):
    """One row in each of the 3 week-grain shifted tables (no day_idx)."""
    from models import ProgressPhoto, WeeklyCheckIn, WeeklyReport
    db.session.add(ProgressPhoto(user_id=user_id, week=week, log_date=log_date,
                                  photo_data="base64stub", pose="front"))
    db.session.add(WeeklyCheckIn(user_id=user_id, week=week, check_in_date=log_date,
                                  energy_level=7, sleep_quality=7, adherence_pct=90))
    db.session.add(WeeklyReport(user_id=user_id, week=week, report_date=log_date,
                                 workouts_completed=6, workouts_total=6))


def _seed_run_and_set(db, user_id, week, day_idx, log_date, tag):
    """Extra RunLog + SetLog rows only — used to fill a week to a full 7/7
    without reseeding all 18 day-grain tables, stressing exactly the
    unique-constrained tables the spec calls out."""
    from models import RunLog, SetLog
    db.session.add(RunLog(user_id=user_id, week=week, day_idx=day_idx, log_date=log_date,
                           distance_miles=2.5, duration_min=24, source="manual"))
    db.session.add(SetLog(user_id=user_id, exercise_name="Bench Press", week=week,
                           day_idx=day_idx, set_number=0, weight=135, reps=8, logged_date=log_date))


def _clear_user_data(db, user_id):
    """Wipe every SHIFTED_TABLES row + goal/state/protocol data so a test
    can reuse an email across suite runs without stale rows."""
    from transition_block3 import SHIFTED_TABLES
    from models import TrainingGoal, AppState, BodyWeight, PeptideDose, PeptideVial, LabReminder
    for model in SHIFTED_TABLES:
        model.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    TrainingGoal.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    AppState.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    BodyWeight.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PeptideDose.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PeptideVial.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    LabReminder.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    db.session.commit()


def _get_or_create_user(email):
    from models import User
    from app import db
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    return u


def _seed_full_fixture(app_, db, email, goal_target=185.0):
    """The prod-shaped fixture: block-1 at weeks 13-24 (incl. a full 7/7
    RunLog+SetLog week), block-2 at weeks 1-7 with TODAY's week-7 day-0
    row (incl. a full 7/7 week), a cut TrainingGoal(target=185), and
    AppState(start_date=2026-06-29, current_week=7). Returns user_id."""
    def _do_it():
        from models import TrainingGoal, AppState

        u = _get_or_create_user(email)
        _clear_user_data(db, u.id)

        # Block-1: weeks 13-24, 2 days/week baseline; week 13 goes full 7/7
        # (RunLog + SetLog) to stress the unique constraints across the shift.
        for week in range(13, 25):
            for day_idx in range(2):
                ld = _log_date(week, day_idx)
                _seed_day(db, u.id, week, day_idx, ld, tag=f"b1-{week}-{day_idx}")
            _seed_week(db, u.id, week, _log_date(week, 6))
        for day_idx in range(2, 7):
            _seed_run_and_set(db, u.id, 13, day_idx, _log_date(13, day_idx), tag=f"b1full-{day_idx}")

        # Block-2: weeks 1-6, 2 days/week baseline; week 1 goes full 7/7.
        # Week 7 gets ONLY day 0 (today — the week just started).
        for week in range(1, 7):
            for day_idx in range(2):
                ld = _log_date(week, day_idx)
                _seed_day(db, u.id, week, day_idx, ld, tag=f"b2-{week}-{day_idx}")
            _seed_week(db, u.id, week, _log_date(week, 6))
        for day_idx in range(2, 7):
            _seed_run_and_set(db, u.id, 1, day_idx, _log_date(1, day_idx), tag=f"b2full-{day_idx}")
        _seed_day(db, u.id, 7, 0, TRANSITION_DATE, tag="today")

        goal = TrainingGoal(
            user_id=u.id, goal_type="cut", target_weight=goal_target,
            target_bf_pct=18.0, daily_calories=1800, protein_grams=180,
            carb_grams=150, fat_grams=50, tdee=2500,
            phase_plan=[{"phase": 2, "weeks": [1, 12]}],
            weight_projection=[{"week": w, "planned_weight": 220 - w} for w in range(1, 13)],
        )
        db.session.add(goal)
        db.session.add(AppState(user_id=u.id, start_date=BLOCK2_START, current_week=7))
        db.session.commit()
        return u.id

    return _do(app_, _do_it)


# ── HTTP + DB helpers ────────────────────────────────────────────────────

def _post_transition(app_, email, anchor, dry_run=False, admin_key="test-key"):
    with app_.test_client() as c:
        return c.post("/api/admin/block3-transition", json={
            "email": email, "anchor_weight": anchor, "dry_run": dry_run,
        }, headers={"X-Admin-Key": admin_key})


def _post_rollback(app_, email, admin_key="test-key"):
    with app_.test_client() as c:
        return c.post("/api/admin/block3-rollback", json={"email": email},
                       headers={"X-Admin-Key": admin_key})


def _snapshot_histograms(app_, uid):
    def _do_it():
        from transition_block3 import SHIFTED_TABLES, _histogram
        return {m.__name__: _histogram(m, uid) for m in SHIFTED_TABLES}
    return _do(app_, _do_it)


def _flag_count(app_):
    def _do_it():
        from models import SystemFlag
        return SystemFlag.query.filter(SystemFlag.key.in_(
            ["projection_mode", "block3_anchor", "block3_prestate"])).count()
    return _do(app_, _do_it)


def _week_count(app_, model_name, uid, week):
    def _do_it():
        import transition_block3 as tb
        model = next(m for m in tb.SHIFTED_TABLES if m.__name__ == model_name)
        return model.query.filter_by(user_id=uid, week=week).count()
    return _do(app_, _do_it)


def _range_count(app_, model_name, uid, lo, hi):
    def _do_it():
        import transition_block3 as tb
        model = next(m for m in tb.SHIFTED_TABLES if m.__name__ == model_name)
        return model.query.filter(model.user_id == uid, model.week.between(lo, hi)).count()
    return _do(app_, _do_it)


# ── (a) dry_run mutates nothing ──────────────────────────────────────────

def test_dry_run_mutates_nothing(app_ctx, monkeypatch, clean_block3_flags):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-dryrun@test.com"
    uid = _seed_full_fixture(app_, db, email)

    before = _snapshot_histograms(app_, uid)

    r = _post_transition(app_, email, ANCHOR, dry_run=True)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["dry_run"] is True
    assert "histograms" in body
    assert "would_shift" in body
    assert body["would_shift"]["SetLog"]["block1_to_shift"] > 0

    after = _snapshot_histograms(app_, uid)
    assert before == after
    assert _flag_count(app_) == 0


# ── (b) real transition ──────────────────────────────────────────────────

def test_transition_shifts_blocks_and_rehomes_today(app_ctx, monkeypatch, clean_block3_flags):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-main@test.com"
    uid = _seed_full_fixture(app_, db, email)

    pre_setlog_week13 = _week_count(app_, "SetLog", uid, 13)
    pre_runlog_week13 = _week_count(app_, "RunLog", uid, 13)
    assert pre_runlog_week13 == 7  # the full 7/7 week seeded above
    pre_setlog_week1 = _week_count(app_, "SetLog", uid, 1)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["ok"] is True
    assert body["labs_created"] == 2
    assert set(body["flags_set"]) == {"projection_mode", "block3_anchor"}
    assert body["rehomed"] > 0

    # Block-1 intact at 25-36 — spot-check the known week-13 row now at 25.
    assert _week_count(app_, "SetLog", uid, 25) == pre_setlog_week13
    assert _week_count(app_, "RunLog", uid, 25) == 7

    # Block-2 at 13-18 (block-2's original week 1 -> 13; week 13 now holds
    # block-2's data, NOT empty — block-1 already vacated it in the prior
    # step and moved on to 25-36). Week 1 is checked separately below — it
    # is NOT empty either, since the re-home step lands today's data there.
    assert _week_count(app_, "SetLog", uid, 13) == pre_setlog_week1

    # Zero rows at week 7 or 19 in EVERY shifted table (no phantom week-19,
    # no leftover week-7).
    def _all_zero_at(week):
        def _do_it():
            import transition_block3 as tb
            return {m.__name__: m.query.filter_by(user_id=uid, week=week).count()
                    for m in tb.SHIFTED_TABLES}
        return _do(app_, _do_it)

    zeros_7 = _all_zero_at(7)
    zeros_19 = _all_zero_at(19)
    assert all(v == 0 for v in zeros_7.values()), zeros_7
    assert all(v == 0 for v in zeros_19.values()), zeros_19

    # Today's rehomed rows land at week=1, day_idx=0 — only today's row.
    assert _week_count(app_, "RunLog", uid, 1) == 1
    assert _week_count(app_, "SetLog", uid, 1) == 3  # Bench x2 + Squat x1 seeded for "today"

    def _check_state():
        from models import TrainingGoal, AppState, BodyWeight, LabReminder
        goal = TrainingGoal.query.filter_by(user_id=uid).first()
        state = AppState.query.filter_by(user_id=uid).first()
        bw = BodyWeight.query.filter_by(user_id=uid, log_date=TRANSITION_DATE).first()
        labs = sorted(
            (l.label, l.due_date.isoformat())
            for l in LabReminder.query.filter_by(user_id=uid).all()
        )
        return {
            "goal_type": goal.goal_type,
            "target_weight": goal.target_weight,
            "weight_projection": goal.weight_projection,
            "start_date": state.start_date.isoformat(),
            "current_week": state.current_week,
            "bw": bw.weight_lbs if bw else None,
            "labs": labs,
        }

    result = _do(app_, _check_state)
    assert result["goal_type"] == "cut"
    assert result["target_weight"] == 195.0
    assert result["start_date"] == "2026-08-10"
    assert result["current_week"] == 1
    assert result["bw"] == ANCHOR
    assert result["labs"] == sorted([
        ("Baseline labs: T/E2, IGF-1, fasting glucose/A1c, lipids", "2026-08-10"),
        ("Week-8 labs: T/E2, IGF-1, fasting glucose/A1c, lipids", "2026-09-28"),
    ])

    from goal_engine import build_block3_projection
    assert result["weight_projection"] == build_block3_projection(ANCHOR, TRANSITION_DATE)


# ── (c) destination-not-empty guard ──────────────────────────────────────

def test_destination_not_empty_guard(app_ctx, monkeypatch, clean_block3_flags):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-conflict@test.com"
    uid = _seed_full_fixture(app_, db, email)

    def _seed_stray():
        from models import SetLog
        db.session.add(SetLog(user_id=uid, exercise_name="Stray", week=30, day_idx=0,
                               set_number=0, weight=100, reps=5,
                               logged_date=date(2026, 12, 1)))
        db.session.commit()
    _do(app_, _seed_stray)

    pre = _snapshot_histograms(app_, uid)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 409, r.get_json()
    body = r.get_json()
    assert "detail" in body
    assert "SetLog" in body["detail"]

    post = _snapshot_histograms(app_, uid)
    assert pre == post
    assert _flag_count(app_) == 0


# ── week-7 day-purity guard (fix round 1, CRITICAL) ─────────────────────
#
# The re-home step force-collapses EVERY week-7 row onto week=1, day_idx=0.
# That's only correct if week 7's sole occupant is today (day 0 — the week
# just started). A stray week-7 day!=0 row would otherwise get merged into
# day 0: for an UNCONSTRAINED table (ExerciseSwap) that's a silent 200 that
# corrupts data; for a UNIQUE-constrained table (RunLog) it's a mid-shift
# IntegrityError (safe, but late and ugly). The pre-flight purity assert
# catches both BEFORE any write — verified for one table of each kind.

def test_week7_purity_guard_unconstrained_table(app_ctx, monkeypatch, clean_block3_flags):
    """A stray week-7, day_idx=1 row in ExerciseSwap (no unique constraint
    on week/day_idx — the silent-merge risk) must abort with 409 before
    any write, not silently succeed with two days merged into one."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-week7-unconstrained@test.com"
    uid = _seed_full_fixture(app_, db, email)

    def _seed_stray():
        from models import ExerciseSwap
        db.session.add(ExerciseSwap(user_id=uid, week=7, day_idx=1,
                                     exercise_idx=0, swapped_to="Stray Swap"))
        db.session.commit()
    _do(app_, _seed_stray)

    pre = _snapshot_histograms(app_, uid)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 409, r.get_json()
    body = r.get_json()
    assert "detail" in body
    assert "ExerciseSwap" in body["detail"]
    assert "day 0" in body["error"].lower()

    post = _snapshot_histograms(app_, uid)
    assert pre == post
    assert _flag_count(app_) == 0


def test_week7_purity_guard_constrained_table(app_ctx, monkeypatch, clean_block3_flags):
    """A stray week-7, day_idx=1 row in RunLog (unique on user/week/day_idx
    — the mid-transaction IntegrityError risk) must abort with a clean 409
    from the pre-flight assert, never reach the re-home UPDATE at all."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-week7-constrained@test.com"
    uid = _seed_full_fixture(app_, db, email)

    def _seed_stray():
        from models import RunLog
        db.session.add(RunLog(user_id=uid, week=7, day_idx=1, log_date=date(2026, 8, 11),
                               distance_miles=2.0, duration_min=20, source="manual"))
        db.session.commit()
    _do(app_, _seed_stray)

    pre = _snapshot_histograms(app_, uid)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 409, r.get_json()
    body = r.get_json()
    assert "detail" in body
    assert "RunLog" in body["detail"]

    post = _snapshot_histograms(app_, uid)
    assert pre == post
    assert _flag_count(app_) == 0


def test_week7_purity_guard_happy_path_still_rehomes(app_ctx, monkeypatch, clean_block3_flags):
    """No stray non-zero-day week-7 rows -> transition proceeds normally
    and today's day-0 rows still re-home to week 1, day 0 (the scoped
    re-home filter doesn't regress the happy path)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-week7-happy@test.com"
    uid = _seed_full_fixture(app_, db, email)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 200, r.get_json()

    assert _week_count(app_, "RunLog", uid, 1) == 1
    assert _week_count(app_, "SetLog", uid, 1) == 3
    assert _week_count(app_, "ExerciseSwap", uid, 1) == 1
    assert _week_count(app_, "ExerciseSwap", uid, 7) == 0


# ── (d) block-3 work then rollback ───────────────────────────────────────

def test_block3_work_then_rollback_restores_prestate(app_ctx, monkeypatch, clean_block3_flags):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-rollback@test.com"
    uid = _seed_full_fixture(app_, db, email)

    pre_histograms = _snapshot_histograms(app_, uid)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 200, r.get_json()

    # Log new block-3 work: two sets at week 1 (a day AFTER today, so the
    # rollback's date discriminator correctly identifies it as new
    # training, not the just-restored today row) + a week-1 plan row.
    def _log_block3_work():
        from models import SetLog, WeeklyPrescription
        db.session.add(SetLog(user_id=uid, exercise_name="NewBlock3Lift", week=1,
                               day_idx=2, set_number=0, weight=100, reps=5,
                               logged_date=date(2026, 8, 12)))
        db.session.add(SetLog(user_id=uid, exercise_name="NewBlock3Lift", week=1,
                               day_idx=2, set_number=1, weight=100, reps=5,
                               logged_date=date(2026, 8, 12)))
        db.session.add(WeeklyPrescription(user_id=uid, week=1, day_idx=2,
                                           exercise_order=0, exercise_name="NewBlock3Lift",
                                           sets=3, reps="5-5"))
        db.session.commit()
    _do(app_, _log_block3_work)

    r2 = _post_rollback(app_, email)
    assert r2.status_code == 200, r2.get_json()
    body = r2.get_json()
    assert body["ok"] is True
    assert body["restored"] > 0
    assert body["parked"] > 0

    post_histograms = _snapshot_histograms(app_, uid)

    # Log tables: EVERY pre-transition week count is restored EXACTLY,
    # including today's rows landing back at week 7. (The new parked
    # NewBlock3Lift rows add an EXTRA week>=100 entry that pre-transition
    # never had — compare per-week on pre's own weeks, not full-dict
    # equality, so that legitimate extra entry doesn't fail the check.)
    from transition_block3 import LOG_TABLES, PLAN_TABLES
    for name in (m.__name__ for m in LOG_TABLES):
        pre_by_week = {wc["week"]: wc["count"] for wc in pre_histograms[name]["week_counts"]}
        post_by_week = {wc["week"]: wc["count"] for wc in post_histograms[name]["week_counts"]}
        for week, count in pre_by_week.items():
            assert post_by_week.get(week, 0) == count, (name, week)
    assert _week_count(app_, "RunLog", uid, 7) == 1
    assert _week_count(app_, "SetLog", uid, 7) == 3

    # Plan tables: completed-week history (1-6, 13-24) is restored; only
    # the in-flight week-7 plan row is intentionally NOT restored (it's
    # regenerable via /api/admin/replan-week per the runbook).
    for name in (m.__name__ for m in PLAN_TABLES):
        pre_by_week = {wc["week"]: wc["count"] for wc in pre_histograms[name]["week_counts"]}
        post_by_week = {wc["week"]: wc["count"] for wc in post_histograms[name]["week_counts"]}
        for week, count in pre_by_week.items():
            if week == 7:
                continue
            assert post_by_week.get(week, 0) == count, (name, week)

    # The new block-3 set is PARKED at week>=100 — never deleted.
    def _find_new_setlog():
        from models import SetLog
        rows = SetLog.query.filter_by(user_id=uid, exercise_name="NewBlock3Lift").all()
        return [(row.week, row.day_idx) for row in rows]
    parked_rows = _do(app_, _find_new_setlog)
    assert len(parked_rows) == 2
    assert all(week >= 100 for week, _di in parked_rows), parked_rows

    # The new plan row is GONE (deleted, regenerable).
    def _find_new_plan():
        from models import WeeklyPrescription
        return WeeklyPrescription.query.filter_by(user_id=uid, exercise_name="NewBlock3Lift").count()
    assert _do(app_, _find_new_plan) == 0

    # TrainingGoal / AppState restored; flags cleared; protocol tables empty.
    def _check_restored_state():
        from models import TrainingGoal, AppState, SystemFlag, PeptideDose, PeptideVial, LabReminder
        goal = TrainingGoal.query.filter_by(user_id=uid).first()
        state = AppState.query.filter_by(user_id=uid).first()
        return {
            "target_weight": goal.target_weight,
            "goal_type": goal.goal_type,
            "start_date": state.start_date.isoformat(),
            "current_week": state.current_week,
            "flags": SystemFlag.query.filter(SystemFlag.key.in_(
                ["projection_mode", "block3_anchor", "block3_prestate"])).count(),
            "doses": PeptideDose.query.filter_by(user_id=uid).count(),
            "vials": PeptideVial.query.filter_by(user_id=uid).count(),
            "labs": LabReminder.query.filter_by(user_id=uid).count(),
        }
    result = _do(app_, _check_restored_state)
    assert result["target_weight"] == 185.0
    assert result["goal_type"] == "cut"
    assert result["start_date"] == "2026-06-29"
    assert result["current_week"] == 7
    assert result["flags"] == 0
    assert result["doses"] == 0
    assert result["vials"] == 0
    assert result["labs"] == 0


# ── (e) no cut goal -> 409 ────────────────────────────────────────────────

def test_transition_requires_cut_goal(app_ctx, monkeypatch, clean_block3_flags):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-nogoal@test.com"

    def _seed_no_goal():
        u = _get_or_create_user(email)
        _clear_user_data(db, u.id)
        return u.id
    _do(app_, _seed_no_goal)

    r = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r.status_code == 409, r.get_json()
    assert "cut" in r.get_json().get("error", "").lower()
    assert _flag_count(app_) == 0


# ── (f) idempotency guard ─────────────────────────────────────────────────

def test_transition_idempotency_guard(app_ctx, monkeypatch, clean_block3_flags):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    email = "block3-idempotent@test.com"
    _seed_full_fixture(app_, db, email)

    r1 = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r1.status_code == 200, r1.get_json()

    r2 = _post_transition(app_, email, ANCHOR, dry_run=False)
    assert r2.status_code == 409, r2.get_json()
    assert "already transitioned" in r2.get_json().get("error", "").lower()
