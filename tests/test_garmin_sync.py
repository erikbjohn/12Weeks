"""Garmin sync: prose parser, workout builder, pull/push DB logic.

Parser fixtures are REAL stored WeeklyRunPlan.detail strings from wk11/12
(produced by coach_planning_runs._segments_to_detail + appended rationale).
"""
from datetime import date

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


def test_structure_hash_changes_with_content_and_date():
    from garmin_sync import build_simple_timed_workout, structure_hash
    a = build_simple_timed_workout("n", 50)
    b = build_simple_timed_workout("n", 55)
    assert structure_hash(a, "2026-06-15") != structure_hash(b, "2026-06-15")
    assert structure_hash(a, "2026-06-15") != structure_hash(a, "2026-06-16")
    assert structure_hash(a, "2026-06-15") == structure_hash(a, "2026-06-15")
