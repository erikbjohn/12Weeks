"""Tests for cite-validation: every numeric in response prose must
either be cited (cites=[claim_id...]) AND match the claim's value, OR
be a result of inline arithmetic on cited inputs."""
import pytest
from coach_claims import Claim
from coach_validator import (
    validate_cited_response,
    CiteViolation,
)


def _claim(claim_id, value, predicate=None, source="src#1"):
    return Claim(
        claim_id=claim_id,
        predicate=predicate or claim_id,
        value=value,
        source=source,
    )


def test_response_with_correct_cite_passes():
    response = {
        "lead": {"text": "You're at 207.2 lb.",
                 "cites": ["body.weight.current"]},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.current", 207.2)]
    out = validate_cited_response(response, claims)
    assert out == []


def test_response_with_unknown_claim_id_fails():
    response = {
        "lead": {"text": "You're at 207.2 lb.",
                 "cites": ["body.weight.imaginary"]},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.current", 207.2)]
    out = validate_cited_response(response, claims)
    assert any("body.weight.imaginary" in v.message for v in out)


def test_value_in_prose_must_match_cited_claim():
    """If prose says '207.2 lb' but cited claim is body.weight.target=185,
    the value-string-match fails."""
    response = {
        "lead": {"text": "You're at 207.2 lb.",
                 "cites": ["body.weight.target"]},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.target", 185.0),
              _claim("body.weight.current", 207.2)]
    out = validate_cited_response(response, claims)
    assert any("207.2" in v.message and "match" in v.message.lower() for v in out)


def test_uncited_number_in_prose_fails():
    """Numbers in prose must be cited (or come from inline derivation)."""
    response = {
        "lead": {"text": "You're 22.2 lb to target.", "cites": []},
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.lb_to_target", 22.2)]
    out = validate_cited_response(response, claims)
    assert any("22.2" in v.message and "cite" in v.message.lower() for v in out)


def test_inline_arithmetic_with_cited_inputs_passes():
    """If response shows '207.2 - 185 = 22.2' AND both 207.2 and 185 are
    cited, the resulting 22.2 is verified."""
    response = {
        "lead": {
            "text": "207.2 - 185 = 22.2 lb to target.",
            "cites": ["body.weight.current", "body.weight.target"],
        },
        "reasoning": [],
        "caveats": [],
    }
    claims = [_claim("body.weight.current", 207.2),
              _claim("body.weight.target", 185.0)]
    out = validate_cited_response(response, claims)
    assert out == []


def test_trivial_numbers_skipped():
    response = {
        "lead": {"text": "You have 1 goal and 2 weeks of options.",
                 "cites": []},
        "reasoning": [], "caveats": [],
    }
    claims = []
    out = validate_cited_response(response, claims)
    # 1 and 2 should be ignored
    assert out == []
