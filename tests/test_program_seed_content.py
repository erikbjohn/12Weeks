"""Pin the program template content to spec sections §2-§7. These tests
fail today because PHASE_TEMPLATES still has the old prescriptions; they
pass after Tasks 5–10 rewrite the dict per spec.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


class TestPhase1Content:
    """Spec §2: Phase 1 (wks 1-3) hypertrophy / adaptation."""

    def test_phase_1_monday_is_lower_power_with_front_squat(self, app_ctx):
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=1)
        mon = days[0]
        names = [e["name"] for e in mon.get("exercises", [])]
        assert "Front Squat" in names, (
            f"Phase 1 Mon should lead with Front Squat per spec §2; "
            f"got {names}"
        )
        # Spec §2 prescribes 4×8-12 for Front Squat in Phase 1.
        front_squat = next(e for e in mon["exercises"]
                           if e["name"] == "Front Squat")
        assert "4x" in front_squat["sets"], (
            f"Phase 1 Mon Front Squat should be 4 sets; got "
            f"{front_squat['sets']}"
        )

    def test_phase_1_tuesday_has_landmine_press(self, app_ctx):
        # Spec §2: Tue Press + Shoulder uses Landmine Press as
        # shoulder-friendly OHP substitute.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=1)
        tue = days[1]
        names = [e["name"] for e in tue.get("exercises", [])]
        assert "Landmine Press" in names, (
            f"Phase 1 Tue should include Landmine Press per spec §2 "
            f"(shoulder-friendly OHP); got {names}"
        )

    def test_phase_1_friday_back_squat_4x8(self, app_ctx):
        # Spec §2: Fri Heavy Lower hypertrophy = Back Squat 4×8 @ ~70%.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=1)
        fri = days[4]
        bs = next((e for e in fri.get("exercises", [])
                   if "Back Squat" in e["name"]), None)
        assert bs is not None, "Phase 1 Fri must have Back Squat"
        assert bs["sets"] == "4x8", (
            f"Phase 1 Fri Back Squat should be 4×8 per spec §2; "
            f"got {bs['sets']}"
        )
