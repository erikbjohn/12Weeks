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


class TestPhase2Content:
    """Spec §4: Phase 2 (wks 5-7) Strength block."""

    def test_phase_2_thursday_has_lat_pulldown_and_pullup(self, app_ctx):
        # Spec §4 Thu: Pull + Lat day. Weighted Pull-Up + BB Row + Lat Pulldown.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        thu = days[3]
        names = [e["name"] for e in thu.get("exercises", [])]
        assert "Weighted Pull-Up" in names, (
            f"Phase 2 Thu should have Weighted Pull-Up; got {names}"
        )
        assert "Lat Pulldown" in names, (
            f"Phase 2 Thu should have Lat Pulldown; got {names}"
        )
        assert "Barbell Bent-Over Row" in names, (
            f"Phase 2 Thu should have BB Row; got {names}"
        )

    def test_phase_2_friday_back_squat_4x5(self, app_ctx):
        # Spec §4: Fri = Heavy Lower, Back Squat top set + back-off,
        # week 5 starts at 4x5 @ 78%. Template stores the wk-5 seed.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        fri = days[4]
        bs = next((e for e in fri["exercises"]
                   if "Back Squat" in e["name"]), None)
        assert bs is not None
        assert bs["sets"] == "4x5", (
            f"Phase 2 Fri Back Squat wk5 should be 4×5; got {bs['sets']}"
        )

    def test_phase_2_monday_front_squat_4x3(self, app_ctx):
        # Spec §4: Mon Lower POWER. Front Squat 4x3 (speed-focused).
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        mon = days[0]
        fs = next((e for e in mon["exercises"]
                   if e["name"] == "Front Squat"), None)
        assert fs is not None
        assert fs["sets"] == "4x3", (
            f"Phase 2 Mon Front Squat = 4×3 (speed); got {fs['sets']}"
        )

    def test_phase_2_tuesday_db_bench_4x5(self, app_ctx):
        # Spec §4 Tue: DB Bench 4x5 strength wave.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=5)
        tue = days[1]
        dbb = next((e for e in tue["exercises"]
                    if e["name"] == "DB Bench Press"), None)
        assert dbb is not None
        assert dbb["sets"] == "4x5"


class TestPhase3Content:
    """Spec §6: Phase 3 (wks 9-11) Cut Climax."""

    def test_phase_3_friday_back_squat_3x3(self, app_ctx):
        # Spec §6: Fri = Heavy Lower, 3×3 @ 87%, HOLD all 3 weeks.
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=9)
        fri = days[4]
        bs = next((e for e in fri["exercises"]
                   if "Back Squat" in e["name"]), None)
        assert bs is not None
        assert bs["sets"] == "3x3", (
            f"Phase 3 Fri Back Squat = 3×3 (HOLD); got {bs['sets']}"
        )

    def test_phase_3_monday_front_squat_3x3(self, app_ctx):
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=9)
        mon = days[0]
        fs = next((e for e in mon["exercises"]
                   if e["name"] == "Front Squat"), None)
        assert fs is not None
        assert fs["sets"] == "3x3"

    def test_phase_3_wednesday_no_ezbar_curl(self, app_ctx):
        # Spec §6 Phase 3 Wed drops EZ-Bar Curl (volume cut on accessories).
        app, _ = app_ctx
        from workout_data import get_workouts
        with app.app_context():
            days = get_workouts(week=9)
        wed = days[2]
        names = [e["name"] for e in wed.get("exercises", [])]
        assert "EZ-Bar Curl" not in names, (
            f"Phase 3 Wed should drop EZ-Bar Curl per spec §6; got {names}"
        )
