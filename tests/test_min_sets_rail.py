"""Every prescribed exercise carries at least 3 working sets — always, deload
weeks included (Erik, 2026-08-24: "I can never have less than three sets of an
exercise; a two-set thing is crazy"). Deload = lighter loads / fewer movements,
never 1-2 set stubs.
"""
from coach_planning_program import MIN_SETS, enforce_safety, validate_program

CATALOG = {"Bench": {"equipment": [], "muscle_group": "chest"},
           "Curl": {"equipment": [], "muscle_group": "arms"},
           "Back Squat": {"equipment": [], "muscle_group": "legs"}}


def test_min_sets_is_three():
    assert MIN_SETS == 3


def test_validate_raises_low_set_counts_to_floor():
    clean, _ = validate_program(
        {"0": [{"exercise": "Bench", "sets": 2, "reps": "8", "rest": "90s"},
               {"exercise": "Curl", "sets": 1, "reps": "12", "rest": "60s"}]},
        CATALOG, [])
    assert [it["sets"] for it in clean[0]] == [3, 3]


def _prog():
    return {
        0: [{"exercise": "Back Squat", "sets": 4, "reps": "4", "weight": 160,
             "rest": "2 min", "why": "x"},
            {"exercise": "Curl", "sets": 3, "reps": "10", "weight": 40,
             "rest": "60s", "why": "x"}],
        5: [{"exercise": "Bench", "sets": 4, "reps": "5", "weight": 150,
             "rest": "2 min", "why": "x"},
            {"exercise": "Curl", "sets": 3, "reps": "10", "weight": 40,
             "rest": "60s", "why": "x"}],
    }


def _assert_floor(out):
    for d, items in out.items():
        for it in items:
            assert it["sets"] >= MIN_SETS, f"day{d} {it['exercise']} has {it['sets']} sets"


def test_ceiling_trim_never_leaves_two_set_stub():
    # 14 sets; ceiling 9 forces a hard trim. Before: accessories decremented to
    # 2 then 1. After: an exercise at the floor is dropped whole, never stubbed.
    out, actions = enforce_safety(_prog(), rest_day_idx=6, ceiling=9,
                                  history_exercises={"Back Squat", "Curl", "Bench"},
                                  history_max_weight=160)
    total = sum(it["sets"] for items in out.values() for it in items)
    assert total <= 9, total
    _assert_floor(out)
    assert any("ceiling" in a.lower() for a in actions)


def test_ceiling_trim_drops_accessory_before_stubbing_lead():
    # Only leads left at ceiling 6: must drop a whole lead rather than leave 2+2+2.
    out, _ = enforce_safety(_prog(), rest_day_idx=6, ceiling=6,
                            history_exercises={"Back Squat", "Curl", "Bench"},
                            history_max_weight=160)
    total = sum(it["sets"] for items in out.values() for it in items)
    assert total <= 6, total
    _assert_floor(out)


def test_deload_week_still_holds_three_set_floor():
    prog = _prog()
    prog[0][1]["sets"] = 2  # coach tried a 2-set deload accessory
    out, _ = enforce_safety(prog, rest_day_idx=6, ceiling=50,
                            history_exercises={"Back Squat", "Curl", "Bench"},
                            history_max_weight=160, deload=True)
    _assert_floor(out)
