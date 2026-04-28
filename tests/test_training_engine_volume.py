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
        # Phase 2 (week 5), Tuesday (day_idx=1), Barbell Bent-Over Row template
        # is 5x5 per workout_data.py:1035. User did 2 sets last week. Engine
        # must still prescribe 5 sets — not collapse to the user's bad day.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_sets("Barbell Bent-Over Row", week=5, day_idx=1,
                           last_weight=95, last_reps=5, set_count=2)
        with app.test_request_context():
            t = compute_next_targets(u.id, "Barbell Bent-Over Row", week=5, day_idx=1)
        assert t["target_sets"] == 5, (
            f"Expected 5 sets (template floor), got {t['target_sets']}. "
            "Engine is letting last_set_count collapse the program's volume."
        )

    def test_user_logged_six_sets_template_says_five(self, app_ctx, user_with_sets):
        # The "max" interpretation is wrong — if the user OVER-delivered,
        # we still hold them to the configured volume. The template is the
        # contract, not a floor for max.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_sets("Barbell Bent-Over Row", week=5, day_idx=1,
                           last_weight=95, last_reps=5, set_count=6)
        with app.test_request_context():
            t = compute_next_targets(u.id, "Barbell Bent-Over Row", week=5, day_idx=1)
        assert t["target_sets"] == 5

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
    """exercise_order disambiguates exercises that appear twice in the same
    day's template (Phase 2 Tuesday: heavy Lat Pulldown 5x5 at order 0 AND
    pump Lat Pulldown 3x12 at order 2). Without it, the engine reads the
    first match and the pump row gets the heavy row's rep-drop compensation.
    """

    def test_phase_1_to_2_transition_pump_row_keeps_pump_weight(
        self, app_ctx, user_with_sets
    ):
        # The bug: transitioning Phase 1 → Phase 2 produced 105 lb → 140 lb
        # (33%) on the pump Lat Pulldown. Root cause: engine called
        # _get_configured_reps without exercise_order, which returned the
        # heavy 5x5's reps=5 even when computing for the pump 3x12 row.
        # With last_reps=8 from Phase 1, rep-drop compensation
        # (5 < 8*0.7) wrongly fired. With exercise_order threaded through,
        # the pump row sees its own configured_reps=12 and rep-drop stays
        # off — base + inc only.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_sets("Lat Pulldown", week=3, day_idx=2,
                           last_weight=105, last_reps=8, set_count=4)
        with app.test_request_context():
            # Pump row at Phase 2 Tue (week 5, day_idx=1, order=2).
            t_pump = compute_next_targets(
                u.id, "Lat Pulldown", week=5, day_idx=1, exercise_order=2,
            )
            # Heavy row at Phase 2 Tue (week 5, day_idx=1, order=0).
            t_heavy = compute_next_targets(
                u.id, "Lat Pulldown", week=5, day_idx=1, exercise_order=0,
            )
        # Pump: configured_reps=12, last_reps=8 → 12 < 8*0.7=5.6 is FALSE
        # → no rep drop bump → base = last_weight + inc = 105 + 5 = 110.
        assert t_pump["target_reps"] == 12, (
            f"pump row should target 12 reps from its own template, "
            f"got {t_pump['target_reps']}"
        )
        assert t_pump["target_sets"] == 3, (
            f"pump row should target 3 sets from its own template, "
            f"got {t_pump['target_sets']}"
        )
        assert t_pump["target_weight"] <= 115, (
            f"pump row should not get aggressive bump, expected ~110, "
            f"got {t_pump['target_weight']}"
        )
        # Heavy: configured_reps=5, last_reps=8 → 5 < 5.6 is TRUE → rep
        # drop fires legitimately. base = 105*1.10=115.5, +inc=120.5 → 125.
        assert t_heavy["target_reps"] == 5
        assert t_heavy["target_sets"] == 5
        assert t_heavy["target_weight"] is not None


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
