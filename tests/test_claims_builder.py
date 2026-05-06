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
