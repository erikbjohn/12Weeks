"""Tests for the typed-claim builder that backs cited output (Step 3).

Each Claim is (claim_id, predicate, value, source, derivation). The model
will cite claim_ids in its response; the validator will check existence
and value-string-match. So claims must be:
  - Stable IDs across calls (deterministic)
  - Predicate strings short and unique enough to detect mis-attribution
  - Values typed (int/float/str) for value-match enforcement
"""
import pytest
from unittest.mock import MagicMock, patch
from coach_claims import Claim, build_claims


def test_claim_dataclass_shape():
    c = Claim(
        claim_id="body.weight.current",
        predicate="athlete.current_weight_lb",
        value=207.2,
        source="BodyWeight#4821",
        derivation=None,
    )
    assert c.claim_id == "body.weight.current"
    assert c.value == 207.2


def test_build_claims_emits_current_weight_when_bodyweight_present():
    """Mock a user with one BodyWeight row; expect a body.weight.current claim."""
    bw = MagicMock(weight_lbs=207.2, log_date=MagicMock(isoformat=lambda: "2026-05-03"))
    with patch("coach_claims._fetch_latest_bodyweight", return_value=bw):
        with patch("coach_claims._fetch_training_goal", return_value=None):
            claims = build_claims(user_id=1, scope=("body_weight",))
    by_id = {c.claim_id: c for c in claims}
    assert "body.weight.current" in by_id
    assert by_id["body.weight.current"].value == 207.2
    assert "BodyWeight" in by_id["body.weight.current"].source


def test_build_claims_emits_target_weight_from_training_goal():
    goal = MagicMock(target_weight=185.0, daily_calories=1700, goal_type="cut")
    with patch("coach_claims._fetch_latest_bodyweight", return_value=None):
        with patch("coach_claims._fetch_training_goal", return_value=goal):
            claims = build_claims(user_id=1, scope=("goal",))
    by_id = {c.claim_id: c for c in claims}
    assert "body.weight.target" in by_id
    assert by_id["body.weight.target"].value == 185.0
    assert "goal.daily_calories" in by_id
    assert by_id["goal.daily_calories"].value == 1700


def test_build_claims_emits_lb_to_target_as_derived_claim():
    """When both current weight and target are present, lb_to_target is a
    derived claim with source='derived' and a derivation chain."""
    bw = MagicMock(weight_lbs=207.2, log_date=MagicMock(isoformat=lambda: "2026-05-03"))
    goal = MagicMock(target_weight=185.0, daily_calories=1700, goal_type="cut")
    with patch("coach_claims._fetch_latest_bodyweight", return_value=bw):
        with patch("coach_claims._fetch_training_goal", return_value=goal):
            claims = build_claims(user_id=1, scope=("body_weight", "goal"))
    by_id = {c.claim_id: c for c in claims}
    assert "body.weight.lb_to_target" in by_id
    assert by_id["body.weight.lb_to_target"].value == 22.2
    assert by_id["body.weight.lb_to_target"].source == "derived"
    assert by_id["body.weight.lb_to_target"].derivation


def test_today_status_emits_workout_and_run_prescribed_claims():
    """today_status scope produces claims for today's prescribed workout
    name and prescribed run type, both pinned to specific source rows."""
    today_status = {
        "date": "2026-05-06",
        "weekday": "Wednesday",
        "day_idx": 2,
        "week": 6,
        "workout_prescribed": True,
        "workout_lift_name": "Core + Mobility (Active Recovery)",
        "run_prescribed": "z2",
        "run_label": "Zone 2 easy",
        "run_duration": "60 min",
    }
    with patch("coach_claims._fetch_today_status", return_value=today_status):
        claims = build_claims(user_id=1, scope=("today_status",))
    by_id = {c.claim_id: c for c in claims}
    assert "today.weekday" in by_id
    assert by_id["today.weekday"].value == "Wednesday"
    assert "today.workout.lift_name" in by_id
    assert by_id["today.workout.lift_name"].value == "Core + Mobility (Active Recovery)"
    assert "today.run.label" in by_id
    assert by_id["today.run.label"].value == "Zone 2 easy"
    assert "today.run.duration" in by_id


def test_today_status_no_workout_emits_explicit_rest_claim():
    today_status = {
        "date": "2026-05-06",
        "weekday": "Sunday",
        "day_idx": 6,
        "week": 6,
        "workout_prescribed": False,
        "run_prescribed": "z2_long",
        "run_label": "Long fasted easy run",
        "run_duration": "90 min",
    }
    with patch("coach_claims._fetch_today_status", return_value=today_status):
        claims = build_claims(user_id=1, scope=("today_status",))
    by_id = {c.claim_id: c for c in claims}
    assert "today.workout.is_rest" in by_id
    assert by_id["today.workout.is_rest"].value is True


def test_week_program_emits_claim_per_day_run_and_lift():
    """week_program scope emits one claim per day for run type and lift name."""
    week_program = [
        {"day_idx": 0, "weekday": "Mon", "lift_name": "Lower POWER + RDL",
         "run_type": "z2", "run_label": "Easy Z2 streak", "run_duration": "35 min"},
        {"day_idx": 1, "weekday": "Tue", "lift_name": "Upper PRESS",
         "run_type": "hiit", "run_label": "VO2 4x4 intervals", "run_duration": "35 min"},
        {"day_idx": 3, "weekday": "Thu", "lift_name": "Upper PULL",
         "run_type": "z2", "run_label": "Easy Z2 streak", "run_duration": "35 min"},
    ]
    with patch("coach_claims._fetch_week_program", return_value=(6, week_program)):
        claims = build_claims(user_id=1, scope=("week_program",))
    by_id = {c.claim_id: c for c in claims}
    # Per-day run type
    assert "week6.tue.run.type" in by_id
    assert by_id["week6.tue.run.type"].value == "hiit"
    # The Thu run that the Doctor missed in the screenshot bug
    assert "week6.thu.run.label" in by_id
    assert by_id["week6.thu.run.label"].value == "Easy Z2 streak"
    # Lift name per day
    assert "week6.mon.lift.name" in by_id
    assert by_id["week6.mon.lift.name"].value == "Lower POWER + RDL"
