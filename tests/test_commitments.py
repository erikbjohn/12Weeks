"""S080: standing commitments with cadence land on the right week and both
planners treat them as fixed."""
from datetime import date
from commitments import fixed_days_for_week, describe


def test_biweekly_anchor_lands_every_other_saturday():
    acts = [{"day": "Saturday", "activity": "El Cajon Mountain trail run", "duration_min": 150,
             "kind": "trail_long_run", "cadence": "biweekly", "anchor_date": "2026-08-29"}]
    assert 5 in fixed_days_for_week(acts, date(2026, 8, 24))     # week of Aug 29
    assert 5 not in fixed_days_for_week(acts, date(2026, 8, 31))  # Sep 5 — off week
    assert 5 in fixed_days_for_week(acts, date(2026, 9, 7))      # Sep 12
    text = describe(acts, date(2026, 9, 7))
    assert "2026-09-12" in text and "FIXED" in text


def test_run_planner_pins_the_committed_day():
    from coach_planning_runs import _apply_fixed_commitments
    out = {5: {"type": "hiit", "label": "Hill repeats", "duration": "40 min", "detail": "x"}}
    out = _apply_fixed_commitments(out, {"fixed_commitments": {5: {"activity": "El Cajon trail", "duration_min": 150, "kind": "trail_long_run"}}})
    assert out[5]["fixed"] and out[5]["type"] == "z2_long" and out[5]["duration"] == "150 min"


def test_strength_rail_strips_lower_body_on_a_committed_day():
    from coach_planning_program import enforce_safety
    program = {5: [{"exercise": "Barbell Back Squat", "sets": 4, "reps": 6, "weight": 200},
                   {"exercise": "DB Overhead Press", "sets": 3, "reps": 8, "weight": 40},
                   {"exercise": "Lat Pulldown", "sets": 3, "reps": 10, "weight": 120}]}
    out, actions = enforce_safety(program, rest_day_idx=6, ceiling=100, history_exercises=set(),
                                  history_max_weight=300, min_per_day=1, fixed_days=[5])
    names = [i["exercise"] for i in out.get(5, [])]
    assert "Barbell Back Squat" not in names and "DB Overhead Press" in names
    assert any("committed" in a for a in actions)
