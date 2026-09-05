"""§5 canonical curve: pinned boundary values, exact 185 landing (2026-09-05 retarget), tolerance."""
from datetime import date
import pytest

START = date(2026, 8, 10)
ANCHOR = 220.0

def test_projection_lands_exactly_on_185_and_sums_35():
    from goal_engine import build_block3_projection
    proj = build_block3_projection(ANCHOR, START)
    assert len(proj) == 12
    assert proj[11] == {"week": 12, "projected": 185.0}
    assert proj[0] == {"week": 1, "projected": 218.25}
    assert proj[5] == {"week": 6, "projected": 205.3}
    assert proj[10] == {"week": 11, "projected": 187.8}

def test_slope_table_pins_no_week5_boundary():
    from goal_engine import BLOCK3_WEEKLY_RATES
    assert BLOCK3_WEEKLY_RATES[5] == BLOCK3_WEEKLY_RATES[4]  # Sep-10 frequency doubling is NOT a curve boundary
    assert BLOCK3_WEEKLY_RATES == {1: 1.75, 2: 1.75, 3: 2.8, 4: 2.8, 5: 2.8,
                                   6: 2.8, 7: 3.5, 8: 3.5, 9: 3.5, 10: 3.5,
                                   11: 3.5, 12: 2.8}

def test_curve_value_pinned_boundaries():
    from goal_engine import curve_value
    # Morning-weigh-in convention: curve(D) = target at the MORNING of D
    # (loss accrued over elapsed days BEFORE D). Day 0 = the anchor exactly.
    assert curve_value(ANCHOR, START, START) == pytest.approx(220.0)
    assert curve_value(ANCHOR, START, date(2026, 8, 23)) == pytest.approx(220.0 - 13 * 1.75 / 7)
    # Week-2 target lands the morning AFTER week 2 completes:
    assert curve_value(ANCHOR, START, date(2026, 8, 24)) == pytest.approx(216.5)
    # Aug 25 accrues at the NEW 2.8/7 rate (NOT 1.75/7)
    assert curve_value(ANCHOR, START, date(2026, 8, 25)) == pytest.approx(216.5 - 2.8 / 7)
    assert curve_value(ANCHOR, START, date(2026, 9, 21)) == pytest.approx(205.3)
    assert curve_value(ANCHOR, START, date(2026, 9, 22)) == pytest.approx(205.3 - 3.5 / 7)
    # Final day's loss is in progress on the Nov 1 morning; 185.0 is reached
    # at the Nov 2 morning (completion of Nov 1) and clamps thereafter.
    assert curve_value(ANCHOR, START, date(2026, 11, 1)) == pytest.approx(185.0 + 2.8 / 7)
    assert curve_value(ANCHOR, START, date(2026, 11, 2)) == pytest.approx(185.0)
    assert curve_value(ANCHOR, START, date(2026, 12, 25)) == pytest.approx(185.0)
    assert curve_value(ANCHOR, START, date(2026, 8, 1)) == pytest.approx(220.0)  # pre-block clamp

def test_curve_continuous_at_phase_boundaries():
    from goal_engine import curve_value
    for boundary in (date(2026, 8, 25), date(2026, 9, 22)):
        before = curve_value(ANCHOR, START, boundary.replace(day=boundary.day - 1))
        after = curve_value(ANCHOR, START, boundary)
        assert abs(before - after) <= 3.5 / 7 + 1e-9  # one day's accrual at the steepest rate, no jump

def test_pace_status_three_state():
    from goal_engine import pace_status, curve_value, CURVE_TOLERANCE_LB
    d = date(2026, 9, 30)  # mid-phase Wednesday
    on_curve = curve_value(ANCHOR, START, d)
    assert pace_status(on_curve, ANCHOR, START, d) == "on_pace"
    assert pace_status(on_curve + CURVE_TOLERANCE_LB + 0.1, ANCHOR, START, d) == "behind"
    assert pace_status(on_curve - CURVE_TOLERANCE_LB - 0.1, ANCHOR, START, d) == "ahead"
