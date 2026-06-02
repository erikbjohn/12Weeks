"""Barbell loads must be buildable on a real bar, and the coach's `why` must
never narrate a number that isn't the prescribed weight.

- A 45-lb bar + 5-lb-and-up plates (no 2.5s) => every barbell total is 45+10k,
  i.e. it ALWAYS ENDS IN 5. A barbell bench is never 150.
- When code makes a load loadable (or the movement actually has history), the
  coach's reason is reconciled so it can't contradict the displayed number.
"""
import pytest


@pytest.mark.parametrize("name,raw,expected", [
    ("Barbell Bench Press", 147.5, 145.0),   # coach's +2.5 isn't loadable -> 145
    ("Barbell Bench Press", 150.0, 155.0),   # 150 ends in 0 -> not buildable
    ("Barbell Bench Press", 145.0, 145.0),   # already valid
    ("Barbell Back Squat", 152.5, 155.0),
    ("Barbell Bent-Over Row", 140.0, 145.0),
    ("Barbell Hip Thrust", 145.0, 145.0),
    ("Romanian Deadlift", 185.0, 185.0),
])
def test_barbell_weights_end_in_five(name, raw, expected):
    from app import _round_to_loadable
    out = _round_to_loadable(name, raw)
    assert out == expected
    assert int(out) % 10 == 5, f"{name} {out} must end in 5"


@pytest.mark.parametrize("name,raw,expected", [
    ("Incline DB Press", 55.0, 55.0),        # dumbbells move in 5s
    ("DB Overhead Press", 42.5, 45.0),
    ("Lat Pulldown", 150.0, 150.0),          # machine — may end in 0
    ("Cable Tricep Pushdown", 67.5, 70.0),
    ("Hollow Hold", 0.0, 0.0),               # bodyweight stays 0
])
def test_non_barbell_nearest_five(name, raw, expected):
    from app import _round_to_loadable
    assert _round_to_loadable(name, raw) == expected


def test_db_movements_are_not_treated_as_barbell():
    from app import _is_barbell_movement
    assert _is_barbell_movement("Barbell Bench Press") is True
    assert _is_barbell_movement("Incline DB Press") is False
    assert _is_barbell_movement("DB Overhead Press") is False  # has 'overhead press' but it's a DB
    assert _is_barbell_movement("Lat Pulldown") is False


def test_reason_reconciled_when_number_contradicts():
    from app import _reconcile_lift_reason
    # coach said "+2.5 from 145" (=147.5) but the loadable weight is 145
    out = _reconcile_lift_reason("Incremental +2.5 lb from last week's 145 lb.",
                                 145.0, 147.5, 145.0, False)
    assert "147.5" not in out and "+2.5" not in out
    assert "145" in out


def test_reason_reconciled_when_false_new():
    from app import _reconcile_lift_reason
    # claims a new/baseline movement but recent_top=35 proves history
    out = _reconcile_lift_reason("New movement introduced at a deliberately light load.",
                                 55.0, 55.0, 35.0, really_new=False)
    assert "new" not in out.lower() and "baseline" not in out.lower()
    assert "55" in out and "35" in out


def test_reason_reconciled_when_holding_wrong_number():
    from app import _reconcile_lift_reason
    out = _reconcile_lift_reason("Holding at 52.5 lb to continue prehab.",
                                 50.0, 50.0, 52.5, False)
    assert "52.5" not in out
    assert "50" in out


def test_clean_matching_reason_is_kept():
    from app import _reconcile_lift_reason
    txt = "Holding 150 lb to consolidate after a strong week; 2 min rest."
    assert _reconcile_lift_reason(txt, 150.0, 150.0, 150.0, False) == txt
