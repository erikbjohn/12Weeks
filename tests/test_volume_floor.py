"""Phase-3 progressive volume must not silently regress: on a non-deload week
every lifting day carries >= min_per_day movements. The coach under-prescribing
(or a re-derive ratcheting down) gets backfilled from last week's movements."""
from coach_planning_program import enforce_safety


def _prog():
    # Tuesday (day 1) has only 3 exercises — under the floor of 4.
    return {
        1: [
            {"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "weight": 145, "rest": "3 min", "why": "lead"},
            {"exercise": "Incline DB Press", "sets": 3, "reps": "8", "weight": 50, "rest": "2 min", "why": "x"},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "10", "weight": 70, "rest": "60s", "why": "x"},
        ],
    }


PREV = {
    1: [
        {"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "weight": 145, "rest": "3 min", "why": ""},
        {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15", "weight": 15, "rest": "45s", "why": ""},
        {"exercise": "Cable Face Pull", "sets": 3, "reps": "15", "weight": 50, "rest": "60s", "why": ""},
    ],
}


def test_floor_restores_missing_movement_on_non_deload():
    out, actions = enforce_safety(
        _prog(), rest_day_idx=6, ceiling=200,
        history_exercises={"Barbell Bench Press", "Incline DB Press",
                           "Cable Tricep Pushdown", "Cable Lateral Raise", "Cable Face Pull"},
        history_max_weight=200, history_top={},
        prev_by_day=PREV, min_per_day=4, deload=False)
    assert len(out[1]) >= 4, "non-deload day must be floored to >= 4 exercises"
    names = {it["exercise"] for it in out[1]}
    # backfilled an honest movement Tuesday ran last week (not a duplicate)
    assert "Cable Lateral Raise" in names or "Cable Face Pull" in names
    assert any("Floored day 1" in a for a in actions)
    # restored row carries a committed rest (write loop fails loud without it)
    for it in out[1]:
        assert it.get("rest")


def test_floor_skipped_on_deload_week():
    out, actions = enforce_safety(
        _prog(), rest_day_idx=6, ceiling=200,
        history_exercises=set(), history_max_weight=200, history_top={},
        prev_by_day=PREV, min_per_day=4, deload=True)
    assert len(out[1]) == 3, "deload week may legitimately run fewer exercises"
    assert not any("Floored" in a for a in actions)
