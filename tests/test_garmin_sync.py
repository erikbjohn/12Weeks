"""Garmin sync: prose parser, workout builder, pull/push DB logic.

Parser fixtures are REAL stored WeeklyRunPlan.detail strings from wk11/12
(produced by coach_planning_runs._segments_to_detail + appended rationale).
"""
from datetime import date, timedelta

import pytest


# ---------- parse_detail_to_segments ----------

def test_parse_vo2_intervals_with_rationale():
    from garmin_sync import parse_detail_to_segments
    detail = ("10 min warmup; 6×3 min hard @ HR ≥165 / 3 min easy; 7 min cooldown"
              " — Progressing from last week's 5×3 to 6×3 — extra rationale")
    segs = parse_detail_to_segments(detail)
    assert segs == [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "work", "minutes": 3, "reps": 6, "hr": "≥165"},
        {"kind": "recovery", "minutes": 3, "reps": 6},
        {"kind": "cooldown", "minutes": 7, "reps": 1},
    ]


def test_parse_steady_with_parenthesized_hr():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments("50 min steady (@ HR ≤135) — Stepping up from last week")
    assert segs == [{"kind": "steady", "minutes": 50, "reps": 1, "hr": "≤135"}]


def test_parse_long_run_three_blocks():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments(
        "10 min warmup; 65 min steady (@ HR ≤132); 10 min cooldown — Deload cuts back")
    assert segs == [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "steady", "minutes": 65, "reps": 1, "hr": "≤132"},
        {"kind": "cooldown", "minutes": 10, "reps": 1},
    ]


def test_parse_work_with_note_and_single_rep():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments("1×20 min hard @ HR 150-160 (tempo effort)")
    assert segs == [{"kind": "work", "minutes": 20, "reps": 1, "hr": "150-160", "note": "tempo effort"}]


def test_parse_steady_with_note_only():
    from garmin_sync import parse_detail_to_segments
    segs = parse_detail_to_segments("30 min steady (easy spin)")
    assert segs == [{"kind": "steady", "minutes": 30, "reps": 1, "note": "easy spin"}]


def test_parse_unrecognized_returns_none():
    from garmin_sync import parse_detail_to_segments
    assert parse_detail_to_segments("Run hard until you feel it") is None
    assert parse_detail_to_segments("") is None
    assert parse_detail_to_segments(None) is None


def test_parse_partial_garbage_returns_none():
    # One good part + one bad part → None (never push half-invented structure)
    from garmin_sync import parse_detail_to_segments
    assert parse_detail_to_segments("10 min warmup; whatever feels right") is None


def test_segments_total_minutes():
    from garmin_sync import segments_total_minutes
    segs = [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "work", "minutes": 3, "reps": 6},
        {"kind": "recovery", "minutes": 3, "reps": 6},
        {"kind": "cooldown", "minutes": 7, "reps": 1},
    ]
    assert segments_total_minutes(segs) == 53


# ---------- HR encoding + workout JSON builder ----------

def test_hr_bounds_encoding():
    from garmin_sync import _hr_bounds
    assert _hr_bounds("≥165") == (165, 190)
    assert _hr_bounds("≤135") == (90, 135)
    assert _hr_bounds("150-160") == (150, 160)
    assert _hr_bounds("142") == (137, 147)
    assert _hr_bounds("Z2") is None
    assert _hr_bounds(None) is None
    assert _hr_bounds("zone 2") is None
    assert _hr_bounds("165bpm") is None
    assert _hr_bounds("165 bpm") == (160, 170)
    assert _hr_bounds("≥200") is None
    assert _hr_bounds("≤80") is None


def test_build_workout_json_vo2_structure():
    from garmin_sync import build_workout_json
    segs = [
        {"kind": "warmup", "minutes": 10, "reps": 1},
        {"kind": "work", "minutes": 3, "reps": 6, "hr": "≥165"},
        {"kind": "recovery", "minutes": 3, "reps": 6},
        {"kind": "cooldown", "minutes": 7, "reps": 1},
    ]
    wj = build_workout_json("12W Wk11 Tue — VO2 53 min", segs)
    assert wj["workoutName"] == "12W Wk11 Tue — VO2 53 min"
    assert wj["sportType"]["sportTypeKey"] == "running"
    steps = wj["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 3  # warmup, repeat-group, cooldown
    warmup, repeat, cooldown = steps
    assert warmup["stepType"]["stepTypeKey"] == "warmup"
    assert warmup["endConditionValue"] == 600.0
    assert warmup["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 6
    work, rec = repeat["workoutSteps"]
    assert work["stepType"]["stepTypeKey"] == "interval"
    assert work["endConditionValue"] == 180.0
    assert work["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (work["targetValueOne"], work["targetValueTwo"]) == (165, 190)
    assert rec["stepType"]["stepTypeKey"] == "recovery"
    assert cooldown["stepType"]["stepTypeKey"] == "cooldown"
    # step orders strictly increasing and unique across nesting
    orders = [warmup["stepOrder"], repeat["stepOrder"], work["stepOrder"],
              rec["stepOrder"], cooldown["stepOrder"]]
    assert orders == sorted(orders) and len(set(orders)) == 5


def test_build_workout_json_steady_hr_ceiling():
    from garmin_sync import build_workout_json
    wj = build_workout_json("x", [{"kind": "steady", "minutes": 50, "reps": 1, "hr": "≤135"}])
    step = wj["workoutSegments"][0]["workoutSteps"][0]
    assert step["type"] == "ExecutableStepDTO"
    assert step["endConditionValue"] == 3000.0
    assert (step["targetValueOne"], step["targetValueTwo"]) == (90, 135)


def test_build_simple_timed_workout():
    from garmin_sync import build_simple_timed_workout
    wj = build_simple_timed_workout("12W Wk11 Wed — Zone 2 50 min", 50)
    steps = wj["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1
    assert steps[0]["endConditionValue"] == 3000.0
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_build_workout_json_solo_repeated_segment():
    from garmin_sync import build_workout_json
    wj = build_workout_json("x", [{"kind": "steady", "minutes": 5, "reps": 3}])
    steps = wj["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1
    assert steps[0]["type"] == "RepeatGroupDTO"
    assert steps[0]["numberOfIterations"] == 3
    assert len(steps[0]["workoutSteps"]) == 1
    assert steps[0]["workoutSteps"][0]["endConditionValue"] == 300.0


def test_structure_hash_changes_with_content_and_date():
    from garmin_sync import build_simple_timed_workout, structure_hash
    a = build_simple_timed_workout("n", 50)
    b = build_simple_timed_workout("n", 55)
    assert structure_hash(a, "2026-06-15") != structure_hash(b, "2026-06-15")
    assert structure_hash(a, "2026-06-15") != structure_hash(a, "2026-06-16")
    assert structure_hash(a, "2026-06-15") == structure_hash(a, "2026-06-15")


# ---------- date mapping + aggregation ----------

def test_week_day_for_date():
    from garmin_sync import week_day_for_date
    start = date(2026, 1, 5)  # Monday, week 1 day 0
    assert week_day_for_date(start, date(2026, 1, 5)) == (1, 0)
    assert week_day_for_date(start, date(2026, 1, 11)) == (1, 6)
    assert week_day_for_date(start, date(2026, 1, 12)) == (2, 0)
    assert week_day_for_date(start, date(2026, 1, 4)) == (None, None)    # before program
    assert week_day_for_date(start, date(2026, 3, 30)) == (None, None)   # week 13 — outside
    assert week_day_for_date(None, date(2026, 1, 5)) == (None, None)


def test_aggregate_day_doubles_weighted_hr():
    from garmin_sync import aggregate_day
    rows = [
        {"distance_miles": 4.0, "duration_min": 40, "avg_hr": 120, "elevation_ft": 100},
        {"distance_miles": 2.0, "duration_min": 20, "avg_hr": 150, "elevation_ft": 50},
    ]
    agg = aggregate_day(rows)
    assert agg["distance_miles"] == 6.0
    assert agg["duration_min"] == 60
    assert agg["avg_hr"] == 130  # (120*40 + 150*20) / 60
    assert agg["elevation_ft"] == 150


def test_aggregate_day_missing_hr_and_empty():
    from garmin_sync import aggregate_day
    rows = [{"distance_miles": 3.0, "duration_min": 30, "avg_hr": None, "elevation_ft": None}]
    agg = aggregate_day(rows)
    assert agg["avg_hr"] is None and agg["distance_miles"] == 3.0
    assert aggregate_day([]) is None
    assert aggregate_day([{"distance_miles": 0, "duration_min": 0, "avg_hr": None, "elevation_ft": 0}]) is None


# ---------- DB tests: sync_activities ----------

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _mk_user(db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    return u


def _mk_state(db, uid, start):
    from models import AppState
    s = AppState.query.filter_by(user_id=uid).first()
    if not s:
        s = AppState(user_id=uid)
        db.session.add(s)
    s.start_date = start
    db.session.commit()
    return s


class FakeGC:
    connected = True

    def __init__(self, activities=None):
        self.activities = activities or []
        self.uploaded, self.scheduled, self.deleted = [], [], []
        self._next_id = 1000

    def get_activities_between(self, start_iso, end_iso):
        return self.activities

    def upload_workout(self, wj):
        self._next_id += 1
        self.uploaded.append(wj)
        return {"workoutId": self._next_id}

    def schedule_workout(self, wid, date_str):
        self.scheduled.append((str(wid), date_str))
        return {}

    def delete_workout(self, wid):
        self.deleted.append(str(wid))
        return True


def _act(aid, day_iso, type_key="running", meters=8047, secs=3000, hr=140, elev_m=30):
    return {
        "activityId": aid,
        "activityName": "Morning Run",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": f"{day_iso} 06:10:00",
        "distance": meters,
        "duration": secs,
        "averageHR": hr,
        "elevationGain": elev_m,
    }


def test_sync_creates_garmin_runlog_and_audit_row(app_ctx):
    app_, db = app_ctx
    from models import RunLog, GarminActivity
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    gc = FakeGC([_act(101, "2026-01-06")])  # week 1, day 1
    res = sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 7))
    assert res["error"] is None
    assert "w1d1" in res["days_filled"]
    rl = RunLog.query.filter_by(user_id=u.id, week=1, day_idx=1).first()
    assert rl is not None and rl.source == "garmin"
    assert rl.distance_miles == 5.0 and rl.duration_min == 50 and rl.avg_hr == 140
    assert GarminActivity.query.filter_by(user_id=u.id, garmin_activity_id="101").count() == 1


def test_sync_never_overwrites_manual_log(app_ctx):
    app_, db = app_ctx
    from models import RunLog
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull2@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    db.session.add(RunLog(user_id=u.id, week=1, day_idx=2, distance_miles=5.2,
                          avg_hr=131, duration_min=48, source="manual",
                          log_date=date(2026, 1, 7)))
    db.session.commit()
    gc = FakeGC([_act(102, "2026-01-07", meters=8000, hr=145)])
    res = sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 8))
    assert "w1d2" in res["days_skipped_manual"]
    rl = RunLog.query.filter_by(user_id=u.id, week=1, day_idx=2).first()
    assert rl.distance_miles == 5.2 and rl.avg_hr == 131  # untouched


def test_sync_legacy_null_source_treated_as_manual(app_ctx):
    app_, db = app_ctx
    from models import RunLog
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull3@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    db.session.add(RunLog(user_id=u.id, week=1, day_idx=3, distance_miles=4.0,
                          source=None, log_date=date(2026, 1, 8)))
    db.session.commit()
    gc = FakeGC([_act(103, "2026-01-08")])
    res = sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 9))
    assert "w1d3" in res["days_skipped_manual"]
    assert RunLog.query.filter_by(user_id=u.id, week=1, day_idx=3).first().distance_miles == 4.0


def test_sync_doubles_aggregate_and_resync_idempotent(app_ctx):
    app_, db = app_ctx
    from models import RunLog, GarminActivity
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull4@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    gc = FakeGC([
        _act(104, "2026-01-09", meters=6437, secs=2400, hr=120, elev_m=20),  # 4mi 40min
        _act(105, "2026-01-09", meters=3219, secs=1200, hr=150, elev_m=10),  # 2mi 20min
    ])
    sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 10))
    rl = RunLog.query.filter_by(user_id=u.id, week=1, day_idx=4).first()
    assert rl.distance_miles == 6.0 and rl.duration_min == 60 and rl.avg_hr == 130
    # re-sync: no duplicate audit rows, log still correct (garmin rows updatable)
    sync_activities(gc, u.id, days_back=3, today=date(2026, 1, 10))
    assert GarminActivity.query.filter_by(user_id=u.id, week=1, day_idx=4).count() == 2
    assert RunLog.query.filter_by(user_id=u.id, week=1, day_idx=4).count() == 1


def test_sync_ignores_strength_and_out_of_program(app_ctx):
    app_, db = app_ctx
    from models import RunLog, GarminActivity
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull5@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    gc = FakeGC([
        _act(106, "2026-01-10", type_key="strength_training"),
        _act(107, "2026-01-01"),  # before program start
    ])
    res = sync_activities(gc, u.id, days_back=30, today=date(2026, 1, 10))
    assert res["ignored"] == 1
    row = GarminActivity.query.filter_by(garmin_activity_id="107").first()
    assert row is not None and row.week is None and row.day_idx is None
    assert RunLog.query.filter_by(user_id=u.id, week=None).count() == 0


def test_sync_fetch_failure_reports_error(app_ctx):
    app_, db = app_ctx
    from garmin_sync import sync_activities
    u = _mk_user(db, "pull6@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))

    class DeadGC(FakeGC):
        def get_activities_between(self, s, e):
            return None

    res = sync_activities(DeadGC(), u.id, days_back=3, today=date(2026, 1, 10))
    assert res["error"] is not None


# ---------- DB tests: push_week ----------

def _mk_run_plan(db, uid, week, day_idx, detail, duration, label="Run", run_type="z2", segments_json=None):
    from models import WeeklyRunPlan
    WeeklyRunPlan.query.filter_by(user_id=uid, week=week, day_idx=day_idx).delete()
    db.session.add(WeeklyRunPlan(
        user_id=uid, week=week, day_idx=day_idx, run_type=run_type, label=label,
        duration=duration, detail=detail, segments_json=segments_json, source="coach"))
    db.session.commit()


def test_push_week_uploads_and_schedules_future_days(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push1@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 2, 1, "10 min warmup; 6×3 min hard @ HR ≥165 / 3 min easy; 7 min cooldown — why",
                 "53 min", label="VO2", run_type="vo2")
    gc = FakeGC()
    res = push_week(gc, u.id, 2, today=date(2026, 1, 12))  # week 2 day 1 = Jan 13 (future)
    assert [p["day"] for p in res["pushed"]] == [1]
    assert len(gc.uploaded) == 1 and gc.scheduled[0][1] == "2026-01-13"
    # interval structure made it through
    steps = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"]
    assert any(s.get("type") == "RepeatGroupDTO" and s["numberOfIterations"] == 6 for s in steps)
    link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=2, day_idx=1).first()
    assert link.status == "ok" and link.garmin_workout_id and link.scheduled_date == date(2026, 1, 13)


def test_push_week_skips_past_days_and_unchanged(app_ctx):
    app_, db = app_ctx
    from garmin_sync import push_week
    u = _mk_user(db, "push2@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 2, 0, "30 min steady (@ HR ≤135) — why", "30 min")  # Jan 12
    _mk_run_plan(db, u.id, 2, 2, "40 min steady (@ HR ≤135) — why", "40 min")  # Jan 14
    gc = FakeGC()
    res = push_week(gc, u.id, 2, today=date(2026, 1, 13))
    assert {s["day"] for s in res["skipped"] if s["reason"] == "past"} == {0}
    assert [p["day"] for p in res["pushed"]] == [2]
    # second push: unchanged → no new uploads
    res2 = push_week(gc, u.id, 2, today=date(2026, 1, 13))
    assert {s["day"] for s in res2["skipped"] if s["reason"] == "unchanged"} == {2}
    assert len(gc.uploaded) == 1


def test_push_week_replaces_changed_day(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push3@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 3, 1, "30 min steady (@ HR ≤135) — why", "30 min")
    gc = FakeGC()
    push_week(gc, u.id, 3, today=date(2026, 1, 19))
    old_id = GarminWorkoutLink.query.filter_by(user_id=u.id, week=3, day_idx=1).first().garmin_workout_id
    _mk_run_plan(db, u.id, 3, 1, "45 min steady (@ HR ≤140) — why", "45 min")
    res = push_week(gc, u.id, 3, today=date(2026, 1, 19))
    assert [p["day"] for p in res["pushed"]] == [1]
    assert gc.deleted == [old_id]
    new_link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=3, day_idx=1).first()
    assert new_link.garmin_workout_id != old_id and new_link.status == "ok"


def test_push_duration_mismatch_falls_back_to_simple(app_ctx):
    # Parsed prose totals 53 min but stored duration says 60 → push simple timed
    app_, db = app_ctx
    from garmin_sync import push_week
    u = _mk_user(db, "push4@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 4, 1, "10 min warmup; 6×3 min hard / 3 min easy; 7 min cooldown — why",
                 "60 min", label="VO2")
    gc = FakeGC()
    res = push_week(gc, u.id, 4, today=date(2026, 1, 26))
    assert [p["day"] for p in res["pushed"]] == [1]
    steps = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1 and steps[0]["endConditionValue"] == 3600.0


def test_push_unparseable_and_no_duration_fails_loud(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push5@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 5, 1, "go by feel — why", None)
    gc = FakeGC()
    res = push_week(gc, u.id, 5, today=date(2026, 2, 2))
    assert [f["day"] for f in res["failed"]] == [1]
    assert GarminWorkoutLink.query.filter_by(user_id=u.id, week=5, day_idx=1).first().status == "failed"


def test_push_upload_error_marks_failed(app_ctx):
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push6@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 6, 1, "30 min steady — why", "30 min")

    class FailGC(FakeGC):
        def upload_workout(self, wj):
            raise RuntimeError("garmin 500")

    res = push_week(FailGC(), u.id, 6, today=date(2026, 2, 9))
    assert [f["day"] for f in res["failed"]] == [1]
    link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=6, day_idx=1).first()
    assert link.status == "failed" and "garmin 500" in (link.error or "")


def test_push_prefers_segments_json_over_prose(app_ctx):
    app_, db = app_ctx
    from garmin_sync import push_week
    u = _mk_user(db, "push7@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    import json as _json
    segs = [{"kind": "steady", "minutes": 42, "reps": 1, "hr": "≤138"}]
    _mk_run_plan(db, u.id, 7, 1, "UNPARSEABLE PROSE", "42 min", segments_json=_json.dumps(segs))
    gc = FakeGC()
    res = push_week(gc, u.id, 7, today=date(2026, 2, 16))
    assert [p["day"] for p in res["pushed"]] == [1]
    step = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"][0]
    assert step["endConditionValue"] == 2520.0 and step["targetValueTwo"] == 138


def test_push_stale_segments_json_mismatching_duration_falls_back(app_ctx):
    # segments_json says 40 min but duration says 45 (regression floor raised it)
    # → push the honest simple 45-min workout, never the stale intervals.
    app_, db = app_ctx
    from garmin_sync import push_week
    import json as _json
    u = _mk_user(db, "push9@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    segs = [{"kind": "steady", "minutes": 40, "reps": 1}]
    _mk_run_plan(db, u.id, 9, 1, "45 min steady — why", "45 min",
                 segments_json=_json.dumps(segs))
    gc = FakeGC()
    res = push_week(gc, u.id, 9, today=date(2026, 2, 23))
    assert [p["day"] for p in res["pushed"]] == [1]
    steps = gc.uploaded[0]["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1 and steps[0]["endConditionValue"] == 2700.0


def test_push_schedule_failure_keeps_workout_id_for_retry_cleanup(app_ctx):
    # Upload succeeds, schedule fails → link must keep the uploaded workout id
    # so the retry deletes the orphan instead of leaking one per attempt.
    app_, db = app_ctx
    from models import GarminWorkoutLink
    from garmin_sync import push_week
    u = _mk_user(db, "push8@test.com")
    _mk_state(db, u.id, date(2026, 1, 5))
    _mk_run_plan(db, u.id, 8, 1, "30 min steady — why", "30 min")

    class ScheduleFailGC(FakeGC):
        def __init__(self):
            super().__init__()
            self.fail_schedule = True

        def schedule_workout(self, wid, date_str):
            if self.fail_schedule:
                raise RuntimeError("garmin schedule 503")
            return super().schedule_workout(wid, date_str)

    gc = ScheduleFailGC()
    res = push_week(gc, u.id, 8, today=date(2026, 2, 16))
    assert [f["day"] for f in res["failed"]] == [1]
    link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=8, day_idx=1).first()
    assert link.status == "failed"
    orphan_id = link.garmin_workout_id
    assert orphan_id  # the uploaded id must be retained
    # retry with schedule working: orphan deleted, exactly one new workout, ok
    gc.fail_schedule = False
    res2 = push_week(gc, u.id, 8, today=date(2026, 2, 16))
    assert [p["day"] for p in res2["pushed"]] == [1]
    assert orphan_id in gc.deleted
    link = GarminWorkoutLink.query.filter_by(user_id=u.id, week=8, day_idx=1).first()
    assert link.status == "ok" and link.garmin_workout_id != orphan_id


# ---------- GarminClient.get_wellness_for_day ----------

class _FakeApi:
    """Stub of the garminconnect.Garmin object for per-day getters."""
    def get_hrv_data(self, day):
        return {"hrvSummary": {"lastNightAvg": 52, "weeklyAvg": 55, "status": "BALANCED",
                               "baseline": {"lowUpper": 45, "balancedHigh": 70}}}
    def get_sleep_data(self, day):
        return {"dailySleepDTO": {"sleepTimeSeconds": 26640, "deepSleepSeconds": 5000,
                                  "lightSleepSeconds": 15000, "remSleepSeconds": 6000,
                                  "awakeSleepSeconds": 640,
                                  "sleepScores": {"overall": {"value": 82},
                                                  "quality": {"qualifierKey": "GOOD"}}}}
    def get_body_battery(self, day):
        return [{"charged": 80, "drained": 22}]
    def get_training_readiness(self, day):
        return {"score": 71, "level": "HIGH"}
    def get_training_status(self, day):
        return {"trainingStatus": "PRODUCTIVE", "weeklyTrainingLoad": 500, "mostRecentVO2Max": 48.0}
    def get_stress_data(self, day):
        return {"overallStressLevel": 31, "restStressDuration": 30000, "highStressDuration": 1200}
    def get_rhr_day(self, day):
        return {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 47}]}}}


def _connected_client():
    from garmin_client import GarminClient
    gc = GarminClient(user_id=999)
    gc.api = _FakeApi()
    gc._connected = True
    return gc


def test_get_wellness_for_day_aggregates_all_metrics():
    gc = _connected_client()
    w = gc.get_wellness_for_day("2026-06-11")
    assert w["hrv"]["lastNight"] == 52 and w["hrv"]["weeklyAvg"] == 55
    assert w["sleep"]["durationSeconds"] == 26640 and w["sleep"]["score"] == 82
    assert w["bodyBattery"]["current"] == 58  # 80 charged - 22 drained
    assert w["trainingReadiness"]["score"] == 71
    assert w["trainingStatus"]["vo2max"] == 48.0
    assert w["stress"]["overall"] == 31
    assert w["restingHr"] == 47


def test_get_wellness_for_day_none_when_disconnected_or_rate_limited():
    import time as _time
    from garmin_client import GarminClient
    gc = GarminClient()
    assert gc.get_wellness_for_day("2026-06-11") is None  # not connected
    gc2 = _connected_client()
    gc2._rate_limited_until = _time.time() + 600
    assert gc2.get_wellness_for_day("2026-06-11") is None  # rate limited → fetch-failed, not 'no data'


def test_get_rhr_handles_missing_payload():
    gc = _connected_client()
    class NoRhrApi(_FakeApi):
        def get_rhr_day(self, day):
            return {"allMetrics": {"metricsMap": {}}}
    gc.api = NoRhrApi()
    gc._cache = {}
    w = gc.get_wellness_for_day("2026-06-10")
    assert w["restingHr"] is None


def test_get_wellness_for_day_none_on_midflight_rate_limit():
    # A 429 raised by a sub-fetch sets _rate_limited_until mid-call; the call
    # must return None (fetch failed), NOT a dict of Nones that would be
    # persisted as a permanent all-NULL day.
    gc = _connected_client()
    class RateLimitedApi(_FakeApi):
        def get_hrv_data(self, day):
            raise Exception("429 Too Many Requests")
    gc.api = RateLimitedApi()
    gc._cache = {}
    assert gc.get_wellness_for_day("2026-06-09") is None

# ---------- DB tests: sync_wellness ----------

def _wellness_payload(hrv=52, sleep_secs=26640, sleep_score=82, bb=58, ready=71,
                      vo2=48.0, stress=31, rhr=47):
    return {
        "hrv": {"lastNight": hrv, "weeklyAvg": 55, "status": "BALANCED"},
        "sleep": {"durationSeconds": sleep_secs, "score": sleep_score},
        "bodyBattery": {"current": bb},
        "trainingReadiness": {"score": ready},
        "trainingStatus": {"status": "PRODUCTIVE", "vo2max": vo2},
        "stress": {"overall": stress},
        "restingHr": rhr,
    }


class WellnessGC(FakeGC):
    def __init__(self, by_day=None, default=True):
        super().__init__()
        self.by_day = by_day or {}
        self.default = default
        self.fetched_days = []

    def get_wellness_for_day(self, day_iso):
        self.fetched_days.append(day_iso)
        if day_iso in self.by_day:
            return self.by_day[day_iso]
        return _wellness_payload() if self.default else None


def test_sync_wellness_creates_today_and_backfills(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well1@test.com")
    today = date(2026, 6, 12)
    res = sync_wellness(WellnessGC(), u.id, today=today)
    assert res["wellness_error"] is None
    row = GarminWellness.query.filter_by(user_id=u.id, date=today).first()
    assert row.sleep_seconds == 26640 and row.sleep_score == 82
    assert row.hrv_last_night == 52 and row.hrv_weekly_avg == 55
    assert row.body_battery == 58 and row.training_readiness == 71
    assert row.vo2max == 48.0 and row.stress_overall == 31 and row.resting_hr == 47
    # backfilled the full 14-day window on first sync
    assert GarminWellness.query.filter_by(user_id=u.id).count() == 15


def test_sync_wellness_refreshes_today_but_not_past(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well2@test.com")
    today = date(2026, 6, 12)
    sync_wellness(WellnessGC(), u.id, today=today)
    yesterday = today - timedelta(days=1)
    gc2 = WellnessGC(by_day={
        today.isoformat(): _wellness_payload(bb=23),
        yesterday.isoformat(): _wellness_payload(bb=99),
    })
    res2 = sync_wellness(gc2, u.id, today=today)
    assert GarminWellness.query.filter_by(user_id=u.id, date=today).first().body_battery == 23
    assert GarminWellness.query.filter_by(user_id=u.id, date=yesterday).first().body_battery == 58
    assert gc2.fetched_days == [today.isoformat()]  # past days not re-fetched
    assert GarminWellness.query.filter_by(user_id=u.id).count() == 15  # no dupes


def test_sync_wellness_null_metrics_and_zero_sleep(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well3@test.com")
    today = date(2026, 6, 12)
    payload = {"hrv": None, "sleep": {"durationSeconds": 0, "score": None},
               "bodyBattery": None, "trainingReadiness": None,
               "trainingStatus": None, "stress": None, "restingHr": None}
    gc = WellnessGC(by_day={(today - timedelta(days=i)).isoformat(): payload for i in range(15)})
    sync_wellness(gc, u.id, today=today)
    row = GarminWellness.query.filter_by(user_id=u.id, date=today).first()
    assert row is not None
    assert row.sleep_seconds is None  # 0 normalized to NULL, never falsy-zero
    assert row.hrv_last_night is None and row.body_battery is None


def test_sync_wellness_fetch_failure_reports_error_and_retries_later(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well4@test.com")
    today = date(2026, 6, 12)
    res = sync_wellness(WellnessGC(default=False), u.id, today=today)  # all fetches fail
    assert res["wellness_error"] is not None
    assert GarminWellness.query.filter_by(user_id=u.id).count() == 0  # nothing written → retried next sync
