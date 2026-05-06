"""Numeric fact-checker for multi-agent responses."""
from coach_multi_agent import _verify_response_numbers


def test_number_in_source_is_verified():
    src = "Daily calories: 1700 kcal. Weight 207.2 lb."
    resp = "You're at 207.2 lb on 1700 kcal."
    assert _verify_response_numbers(resp, src) == []


def test_fabricated_number_is_flagged():
    src = "Daily calories: 1700 kcal. Weight 207.2 lb."
    resp = "You're cycling 1700/1500 kcal."
    out = _verify_response_numbers(resp, src)
    assert "1500" in out


def test_inline_derivation_is_verified():
    """If the response shows X - Y = Z and X, Y are in source, Z is verified."""
    src = "Weight 207.2 lb. Target weight: 185 lb."
    resp = "You're at 22.2 lb to target (207.2 - 185 = 22.2)."
    assert _verify_response_numbers(resp, src) == []


def test_comma_normalization():
    src = "Weekly deficit: 9,401 kcal."
    resp = "Deficit is 9401 weekly."
    assert _verify_response_numbers(resp, src) == []


def test_trivial_numbers_skipped():
    """Bare 0/1/2/3 are too common; don't bother flagging."""
    src = "Weight 207.2"
    resp = "You have 1 goal and 2 weeks left."
    out = _verify_response_numbers(resp, src)
    assert "1" not in out
    assert "2" not in out


def test_set_rep_schemes_pass_via_components():
    """4x5 extracts as 4 and 5 separately; both should appear in any non-trivial slice."""
    src = "Barbell Back Squat: 4x5 @ 145.0lb"
    resp = "Squat 4x5 at 145 holds."
    assert _verify_response_numbers(resp, src) == []


def test_misattribution_NOT_caught():
    """The 5-vs-6-weeks-left error: '5' IS in source (as '5-6 weeks before 50k')
    but used in wrong context. The simple checker can't catch this — documented
    limitation."""
    src = "Week 6/12. 5-6 weeks before the 50k race."
    resp = "5 weeks left in the cut."
    # Number 5 is in source — verifier passes it. Real fix would need
    # noun-association checks.
    assert _verify_response_numbers(resp, src) == []


def test_decimal_normalization():
    src = "Pace: -3.87 lb/wk"
    resp = "Pace is -3.870 lb/wk"  # trailing zero
    assert _verify_response_numbers(resp, src) == []
