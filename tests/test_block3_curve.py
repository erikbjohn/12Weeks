"""§5 canonical curve: pinned boundary values, exact 195 landing, tolerance."""
from datetime import date
import pytest

START = date(2026, 8, 10)
ANCHOR = 220.0

def test_projection_lands_exactly_on_195_and_sums_25():
    from goal_engine import build_block3_projection
    proj = build_block3_projection(ANCHOR, START)
    assert len(proj) == 12
    assert proj[11] == {"week": 12, "projected": 195.0}
    assert proj[0] == {"week": 1, "projected": 218.75}
    assert proj[5] == {"week": 6, "projected": 209.5}
    assert proj[10] == {"week": 11, "projected": 197.0}

def test_slope_table_pins_no_week5_boundary():
    from goal_engine import BLOCK3_WEEKLY_RATES
    assert BLOCK3_WEEKLY_RATES[5] == 2.0  # Sep-10 frequency doubling is NOT a curve boundary
    assert BLOCK3_WEEKLY_RATES == {1: 1.25, 2: 1.25, 3: 2.0, 4: 2.0, 5: 2.0,
                                   6: 2.0, 7: 2.5, 8: 2.5, 9: 2.5, 10: 2.5,
                                   11: 2.5, 12: 2.0}

def test_curve_value_pinned_boundaries():
    from goal_engine import curve_value
    assert curve_value(ANCHOR, START, date(2026, 8, 23)) == pytest.approx(217.5)
    # Aug 24 = week-3 day 1: accrues at the NEW 2.0/7 rate (NOT 1.25/7)
    assert curve_value(ANCHOR, START, date(2026, 8, 24)) == pytest.approx(217.5 - 2.0 / 7)
    assert curve_value(ANCHOR, START, date(2026, 9, 20)) == pytest.approx(209.5)
    assert curve_value(ANCHOR, START, date(2026, 9, 21)) == pytest.approx(209.5 - 2.5 / 7)
    assert curve_value(ANCHOR, START, date(2026, 11, 1)) == pytest.approx(195.0)

def test_curve_continuous_at_phase_boundaries():
    from goal_engine import curve_value
    for boundary in (date(2026, 8, 24), date(2026, 9, 21)):
        before = curve_value(ANCHOR, START, boundary.replace(day=boundary.day - 1))
        after = curve_value(ANCHOR, START, boundary)
        assert abs(before - after) < 0.5  # one day's accrual, no jump

def test_pace_status_three_state():
    from goal_engine import pace_status, curve_value, CURVE_TOLERANCE_LB
    d = date(2026, 9, 30)  # mid-phase Wednesday
    on_curve = curve_value(ANCHOR, START, d)
    assert pace_status(on_curve, ANCHOR, START, d) == "on_pace"
    assert pace_status(on_curve + CURVE_TOLERANCE_LB + 0.1, ANCHOR, START, d) == "behind"
    assert pace_status(on_curve - CURVE_TOLERANCE_LB - 0.1, ANCHOR, START, d) == "ahead"
