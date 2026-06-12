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
