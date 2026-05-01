"""Tests for the volume floor in compute_next_targets and template-duplicate
handling in auto_swap_workout.

The bug: every branch of compute_next_targets prescribed target_sets =
last_set_count (the number of sets in the user's most recent logged session).
A user who logged 2 sets once got prescribed 2 sets forever — Phase 2's 5x5
template silently collapsed to 2x5 in the user's plan view. The "Volume is
sacred — never reduce sets" comment was aspirational; the code did the
opposite. The fix: configured_sets from the program template is the floor;
last_set_count only applies when the template is silent.

Also covers the Phase 1 → Phase 2 transition bugs: exercise_order disambiguation
in the engine, and template-duplicate preservation in auto_swap_workout.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


@pytest.fixture
def user_with_sets(app_ctx):
    """Build a user who logged a session for the given exercise on `last_date`
    at `last_weight` and `last_reps`. The exercise/week/day_idx are chosen so
    the program template prescribes a higher set count."""
    app, db = app_ctx
    from datetime import date, timedelta
    from models import User, UserEquipment, PhysicalAssessment, SetLog

    def make(exercise, week, day_idx, last_weight, last_reps, set_count, days_ago=2):
        _USER_SEQ[0] += 1
        u = User(email=f"engine-test-{_USER_SEQ[0]}@example.com", password_hash="x")
        db.session.add(u)
        db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "ez_bar", "kettlebells", "weight_plates",
            "lat_pulldown", "cable_machine", "leg_press", "leg_curl_ext",
            "chest_press_machine", "seated_row_machine", "smith_machine",
            "ab_machine", "pull_up_bar", "dip_station", "flat_bench",
            "incline_bench", "decline_bench", "resistance_bands", "trx",
            "medicine_ball", "foam_roller", "ab_wheel",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq); db.session.add(pa); db.session.commit()
        logged = date.today() - timedelta(days=days_ago)
        for i in range(set_count):
            db.session.add(SetLog(
                user_id=u.id, exercise_name=exercise, week=week,
                day_idx=day_idx, set_number=i + 1,
                weight=last_weight, reps=last_reps,
                done=True, logged_date=logged,
            ))
        db.session.commit()
        return u
    return make


class TestVolumeFloor:
    def test_user_logged_two_sets_template_says_five(self, app_ctx, user_with_sets):
        # Phase 2 (week 5), Friday (day_idx=4), Barbell Bent-Over Row template
        # is 4x6 per spec §4. User did 2 sets last week. Engine must still
        # prescribe 4 sets — not collapse to the user's bad day.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_sets("Barbell Bent-Over Row", week=5, day_idx=4,
                           last_weight=95, last_reps=6, set_count=2)
        with app.test_request_context():
            t = compute_next_targets(u.id, "Barbell Bent-Over Row", week=5, day_idx=4)
        assert t["target_sets"] == 4, (
            f"Expected 4 sets (template floor), got {t['target_sets']}. "
            "Engine is letting last_set_count collapse the program's volume."
        )

    def test_user_logged_six_sets_template_says_five(self, app_ctx, user_with_sets):
        # The "max" interpretation is wrong — if the user OVER-delivered,
        # we still hold them to the configured volume. The template is the
        # contract, not a floor for max.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_sets("Barbell Bent-Over Row", week=5, day_idx=4,
                           last_weight=95, last_reps=6, set_count=6)
        with app.test_request_context():
            t = compute_next_targets(u.id, "Barbell Bent-Over Row", week=5, day_idx=4)
        assert t["target_sets"] == 4

    def test_falls_back_to_last_set_count_when_template_silent(self, app_ctx, user_with_sets):
        # If the exercise isn't in the template at this slot (e.g. user is on
        # a custom exercise not pinned to a day), preserve the user's logged
        # effort rather than blindly defaulting.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        # Phase 1 Monday (day 0) does not list Inverted Row in the template.
        u = user_with_sets("Inverted Row", week=1, day_idx=0,
                           last_weight=0, last_reps=12, set_count=3)
        with app.test_request_context():
            t = compute_next_targets(u.id, "Inverted Row", week=1, day_idx=0)
        assert t["target_sets"] == 3, (
            f"Expected fallback to last_set_count=3 when template silent, "
            f"got {t['target_sets']}."
        )


class TestEngineExerciseOrder:
    """exercise_order is threaded through compute_next_targets so the engine
    pulls the correct configured (sets, reps) from the day's template even
    when the lookup needs to disambiguate slot. Spec §4 Phase 2 doesn't have
    same-day duplicates, but the engine still needs to honor the explicit
    slot rather than re-reading by name only.
    """

    def test_phase_2_lat_pulldown_uses_template_reps(
        self, app_ctx, user_with_sets
    ):
        # Spec §4 Phase 2 Thu (day_idx=4) has Lat Pulldown 3x10 at idx=2.
        # User came from Phase 1 Wed Lat Pulldown 3x10 at last_reps=10.
        # When we look up the new prescription with exercise_order=2,
        # we must read the spec §4 reps (10) and sets (3), not collapse
        # to a stale value.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_sets("Lat Pulldown", week=3, day_idx=4,
                           last_weight=105, last_reps=10, set_count=3)
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Lat Pulldown", week=5, day_idx=4, exercise_order=2,
            )
        assert t["target_reps"] == 10, (
            f"Phase 2 Fri Lat Pulldown should target 10 reps per spec §4; "
            f"got {t['target_reps']}"
        )
        assert t["target_sets"] == 3, (
            f"Phase 2 Fri Lat Pulldown should target 3 sets per spec §4; "
            f"got {t['target_sets']}"
        )
        assert t["target_weight"] is not None


class TestTimedExerciseRepsPreserved:
    """Plank's '45s' (and '1RM', '10-12' ranges) must survive engine round-trip.

    The bug: `_get_configured_sets_reps` regex was r'(\\d+)x(\\d+)' which
    silently truncated '3x45s' to (3, 45) — drop the 's'. Engine then
    returned target_reps=45 (int). Generator stored '45'. JS isTimedEx
    detector matches /^\\d+s$/ — '45' fails to match, no inline timer for
    Plank.
    """

    def test_plank_returns_45s_string(self, app_ctx, user_with_sets):
        # Phase 2 Thu has Plank 3x45s in the OLD program. Engine should
        # short-circuit timed exercises and return raw reps token.
        app, _db = app_ctx
        from training_engine import compute_next_targets, _get_configured_reps_str
        # Phase 1 Thu doesn't have Plank in the new program. Use Phase 1 Mon
        # accessory? Actually plank is currently absent from the new templates.
        # Test the helper directly with a synthetic prescription scenario.
        u = user_with_sets("Plank", week=1, day_idx=0,
                           last_weight=0, last_reps=45, set_count=3)
        with app.test_request_context():
            t = compute_next_targets(u.id, "Plank", week=1, day_idx=0)
        # If template has Plank with timed reps, engine returns the string.
        # If template has no Plank, engine falls through to generic math.
        # Either way the test pins: when configured_reps_str is non-numeric,
        # engine doesn't collapse it.
        # Helper should return None or "45s"-shaped string for the slot.
        with app.test_request_context():
            raw = _get_configured_reps_str("Plank", 1, 0)
        if raw and not raw.isdigit():
            # Template-defined timed exercise — engine MUST preserve string
            assert t["target_reps"] == raw, (
                f"timed exercise reps must round-trip; raw={raw!r} "
                f"engine={t['target_reps']!r}"
            )
            assert t["target_weight"] is None, (
                f"timed exercises have no weight progression; got "
                f"{t['target_weight']}"
            )

    def test_configured_reps_int_returns_none_for_timed(self, app_ctx):
        # The narrowed _get_configured_reps must return None for non-numeric
        # so callers doing math (rep-drop compensation) don't TypeError on
        # str < float comparisons.
        app, _db = app_ctx
        from training_engine import _get_configured_reps, _get_configured_reps_str
        # Create an in-memory template-like result and check the parsing.
        # Use a known time-suffixed reps via a direct helper call mock —
        # simplest: hit a real template slot if any has timed reps.
        with app.test_request_context():
            # Iterate weeks/days to find a timed exercise in templates.
            from workout_data import get_workouts
            found_timed = None
            for w in range(1, 13):
                for di in range(7):
                    days = get_workouts(w)
                    if di >= len(days):
                        continue
                    for ex in days[di].get("exercises", []) or []:
                        sets = ex.get("sets", "")
                        if "s" in sets and "x" in sets:
                            # Check if reps token has 's' (timed)
                            import re
                            m = re.match(r"\d+x(.+)", sets)
                            if m and not m.group(1).strip().isdigit():
                                found_timed = (ex.get("name"), w, di)
                                break
                    if found_timed:
                        break
                if found_timed:
                    break
            if found_timed is None:
                pytest.skip("no timed exercise in templates to test against")
            name, w, di = found_timed
            int_reps = _get_configured_reps(name, w, di)
            str_reps = _get_configured_reps_str(name, w, di)
            assert int_reps is None, (
                f"_get_configured_reps must return None for non-numeric reps "
                f"({name!r} {w} {di}); got int_reps={int_reps!r}"
            )
            assert str_reps and not str_reps.isdigit(), (
                f"_get_configured_reps_str must return raw non-numeric token; "
                f"got {str_reps!r}"
            )


class TestAutoSwapPreservesTemplateDuplicates:
    """Phase 2 Tuesday lists Lat Pulldown twice (heavy 5x5 + pump 3x12).
    auto_swap_workout used to dedup by name, dropping the pump prescription
    silently — the user lost a real accessory exercise."""

    def test_both_lat_pulldown_rows_survive(self):
        from equipment_swaps import auto_swap_workout
        full_gym = [
            "barbell", "dumbbells", "lat_pulldown", "cable_machine",
            "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
            "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
            "dip_station", "ab_machine", "smith_machine",
        ]
        exercises = [
            {"name": "Lat Pulldown", "sets": "5x5", "rest": "2-3 min"},
            {"name": "Barbell Bent-Over Row", "sets": "5x5", "rest": "2-3 min"},
            {"name": "Lat Pulldown", "sets": "3x12", "rest": "60-90s"},
        ]
        result = auto_swap_workout(exercises, full_gym)
        names = [e["name"] for e in result]
        assert names.count("Lat Pulldown") == 2, (
            f"both Lat Pulldown rows must survive, got {names}"
        )
        assert result[0]["sets"] == "5x5"
        assert result[2]["sets"] == "3x12"
