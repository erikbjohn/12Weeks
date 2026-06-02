"""Code-enforced safety rails for the program coach. The LLM picks the program;
these deterministic rails GUARANTEE the limits the prompt can't be trusted to
hold: no lifting on the rest/long-run day, a hard weekly-volume ceiling, and
new (no-history) movements forced to a genuinely light start.
"""
from coach_planning_program import enforce_safety


def _prog():
    return {
        0: [{"exercise": "Back Squat", "sets": 4, "reps": "4", "weight": 160, "why": "x"},
            {"exercise": "Curl", "sets": 3, "reps": "10", "weight": 40, "why": "x"}],
        5: [{"exercise": "Bench", "sets": 4, "reps": "5", "weight": 150, "why": "x"}],
        6: [{"exercise": "Box Jump", "sets": 4, "reps": "5", "weight": 0, "why": "x"}],
    }


def test_drops_lifting_on_rest_day():
    out, actions = enforce_safety(_prog(), rest_day_idx=6, ceiling=50,
                                  history_exercises={"Back Squat", "Curl", "Bench"},
                                  history_max_weight=160)
    assert 6 not in out
    assert any("rest day" in a.lower() for a in actions)


def test_caps_total_volume_to_ceiling():
    # 4+3+4 = 11 sets across days 0 and 5; ceiling 8 must trim to <= 8.
    out, actions = enforce_safety(_prog(), rest_day_idx=6, ceiling=8,
                                  history_exercises={"Back Squat", "Curl", "Bench"},
                                  history_max_weight=160)
    total = sum(it["sets"] for items in out.values() for it in items)
    assert total <= 8, f"volume not capped: {total}"
    assert any("volume" in a.lower() or "ceiling" in a.lower() for a in actions)


def test_compounds_survive_volume_trim_over_accessories():
    out, _ = enforce_safety(_prog(), rest_day_idx=6, ceiling=8,
                            history_exercises={"Back Squat", "Curl", "Bench"},
                            history_max_weight=160)
    # Back Squat (compound) must still be present after trimming.
    assert any(it["exercise"] == "Back Squat" for it in out.get(0, []))


def test_new_movement_load_forced_light():
    prog = {2: [{"exercise": "Conventional Deadlift", "sets": 4, "reps": "4",
                 "weight": 225, "why": "new lift, 'light'"}]}
    out, actions = enforce_safety(prog, rest_day_idx=6, ceiling=50,
                                  history_exercises={"Back Squat"},  # no DL history
                                  history_max_weight=160)
    dl = out[2][0]
    assert dl["weight"] <= 160 * 0.6 + 0.01, f"new lift not capped light: {dl['weight']}"
    assert dl.get("new") is True
    assert any("Conventional Deadlift" in a for a in actions)


def test_equipment_and_grip_variants_match_history():
    # "Barbell Hip Thrust" / "Wide-Grip Lat Pulldown" are the SAME movements as
    # logged "Hip Thrust" / "Lat Pulldown" — must NOT be treated as new/capped.
    prog = {0: [
        {"exercise": "Barbell Hip Thrust", "sets": 4, "reps": "5", "weight": 135, "why": "x"},
        {"exercise": "Wide-Grip Lat Pulldown", "sets": 3, "reps": "6", "weight": 140, "why": "x"},
        {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8", "weight": 65, "why": "x"},
    ]}
    out, actions = enforce_safety(prog, rest_day_idx=6, ceiling=50,
                                  history_exercises={"Hip Thrust", "Lat Pulldown", "Single-Arm DB Row"},
                                  history_max_weight=160)
    by = {i["exercise"]: i for i in out[0]}
    assert by["Barbell Hip Thrust"]["weight"] == 135 and not by["Barbell Hip Thrust"].get("new")
    assert by["Wide-Grip Lat Pulldown"]["weight"] == 140 and not by["Wide-Grip Lat Pulldown"].get("new")
    assert not any("Hip Thrust" in a or "Lat Pulldown" in a for a in actions)


def test_genuinely_new_movement_still_capped_after_canonicalization():
    prog = {0: [{"exercise": "Conventional Deadlift", "sets": 4, "reps": "4", "weight": 225, "why": "x"}]}
    out, _ = enforce_safety(prog, rest_day_idx=6, ceiling=50,
                            history_exercises={"Back Squat", "Romanian Deadlift"},
                            history_max_weight=160)
    assert out[0][0]["weight"] <= 96.01 and out[0][0].get("new") is True


def test_existing_movement_load_untouched():
    out, _ = enforce_safety(_prog(), rest_day_idx=6, ceiling=50,
                            history_exercises={"Back Squat", "Curl", "Bench"},
                            history_max_weight=160)
    bs = next(it for it in out[0] if it["exercise"] == "Back Squat")
    assert bs["weight"] == 160  # has history -> not capped
