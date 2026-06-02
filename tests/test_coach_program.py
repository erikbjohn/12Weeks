"""Guardrails for the full-program strength coach (Option B): the coach designs
exercises + sets + reps + loads weekly, but its output is HARD-validated so it
can never prescribe a movement the athlete lacks equipment for or that isn't a
real catalog exercise.
"""
from coach_planning_program import validate_program

CATALOG = {
    "Barbell Bench Press": {"equipment": ["barbell", "flat_bench"], "muscle_group": "chest"},
    "Push-Ups": {"equipment": [], "muscle_group": "chest"},
    "Leg Press": {"equipment": ["leg_press"], "muscle_group": "quads"},
    "Box Jump": {"equipment": [], "muscle_group": "power"},
}


def test_keeps_valid_equipment_exercise():
    clean, dropped = validate_program(
        {0: [{"exercise": "Barbell Bench Press", "sets": 4, "reps": "5", "weight": 185, "rest": "2 min", "why": "main"}]},
        CATALOG, {"barbell", "flat_bench", "dumbbells"})
    assert clean[0][0]["exercise"] == "Barbell Bench Press"
    assert clean[0][0]["rest"] == "2 min"
    assert not dropped


def test_drops_unknown_exercise():
    clean, dropped = validate_program(
        {0: [{"exercise": "Jefferson Curl", "sets": 3, "reps": "8", "weight": 50, "why": "x"}]},
        CATALOG, {"barbell"})
    assert clean.get(0, []) == []
    assert any("Jefferson Curl" in d for d in dropped)


def test_drops_exercise_without_equipment():
    clean, dropped = validate_program(
        {0: [{"exercise": "Leg Press", "sets": 3, "reps": "10", "weight": 200, "why": "x"}]},
        CATALOG, {"barbell"})  # athlete has no leg_press
    assert clean.get(0, []) == []
    assert any("Leg Press" in d for d in dropped)


def test_keeps_bodyweight_regardless_of_equipment():
    clean, dropped = validate_program(
        {0: [{"exercise": "Push-Ups", "sets": 3, "reps": "15", "weight": None, "rest": "60s", "why": "x"}]},
        CATALOG, set())
    assert clean[0][0]["exercise"] == "Push-Ups"


def test_clamps_insane_set_counts():
    clean, _ = validate_program(
        {0: [{"exercise": "Push-Ups", "sets": 99, "reps": "10", "weight": None, "rest": "60s", "why": "x"}]},
        CATALOG, set())
    assert 1 <= clean[0][0]["sets"] <= 6


def test_day_index_coerced_to_int():
    clean, _ = validate_program(
        {"4": [{"exercise": "Box Jump", "sets": 3, "reps": "5", "weight": 0, "rest": "90s", "why": "x"}]},
        CATALOG, set())
    assert 4 in clean and clean[4][0]["exercise"] == "Box Jump"


def test_rest_day_placeholder_zero_reps_dropped():
    # The LLM sometimes emits a "Burpees 3x0" placeholder on the rest/run day.
    clean, _ = validate_program(
        {6: [{"exercise": "Box Jump", "sets": 3, "reps": "0", "weight": 0, "why": "rest day"}]},
        CATALOG, set())
    assert clean.get(6, []) == []


def test_empty_or_garbage_entries_dropped():
    clean, dropped = validate_program(
        {0: [{"exercise": "", "sets": 3, "reps": "5", "weight": 1, "why": "x"},
             {"sets": 3, "reps": "5"}]},
        CATALOG, {"barbell"})
    assert clean.get(0, []) == []


# ── Rest is the coach's: required, single value, never a range ───────────────

def test_drops_item_missing_rest():
    # Coach-or-nothing: no hardcoded default is substituted for a missing rest.
    clean, dropped = validate_program(
        {0: [{"exercise": "Barbell Bench Press", "sets": 4, "reps": "5", "weight": 185, "why": "no rest"}]},
        CATALOG, {"barbell", "flat_bench"})
    assert clean.get(0, []) == []
    assert any("missing rest" in d for d in dropped)


def test_drops_range_rest():
    clean, dropped = validate_program(
        {0: [{"exercise": "Barbell Bench Press", "sets": 4, "reps": "5", "weight": 185,
              "rest": "90s-2 min", "why": "range rest"}]},
        CATALOG, {"barbell", "flat_bench"})
    assert clean.get(0, []) == []
    assert any("range" in d for d in dropped)


def test_keeps_single_committed_rest():
    clean, dropped = validate_program(
        {0: [{"exercise": "Push-Ups", "sets": 3, "reps": "15", "weight": None,
              "rest": "75s", "why": "ok"}]},
        CATALOG, set())
    assert clean[0][0]["rest"] == "75s"
    assert not dropped
