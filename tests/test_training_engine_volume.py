"""Tests for the volume floor in compute_next_targets.

The bug: every branch of compute_next_targets prescribed target_sets =
last_set_count (the number of sets in the user's most recent logged session).
A user who logged 2 sets once got prescribed 2 sets forever — Phase 2's 5x5
template silently collapsed to 2x5 in the user's plan view. The "Volume is
sacred — never reduce sets" comment was aspirational; the code did the
opposite. The fix: configured_sets from the program template is the floor;
last_set_count only applies when the template is silent.
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
    """Build a user who logged a 2-set session for the given exercise on
    `last_date` at `last_weight` and `last_reps`. The exercise/week/day_idx
    are chosen so the program template prescribes a higher set count."""
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
        # contract, not a floor for max. (If we ever want a ceiling that
        # honours user effort, that's a separate feature.)
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


class TestHealPrescriptionVolumeFloor:
    """Lazy heal on /api/workouts read: legacy WeeklyPrescription rows written
    before the engine fix carried under-volume schemes (e.g. 2x12 instead of
    5x5). These tests pin the heal's contract: lift engine/template rows up
    to the configured floor; never touch coach-authored rows."""

    def _make_user(self, app_ctx):
        app, db = app_ctx
        from models import User, UserEquipment, PhysicalAssessment
        _USER_SEQ[0] += 1
        u = User(email=f"heal-test-{_USER_SEQ[0]}@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
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
        return u

    def test_heals_engine_authored_under_volume(self, app_ctx):
        # The smoking-gun row from the screenshot: 2x12 stored where the
        # template prescribes 5x5. The heal must rewrite both dimensions
        # because the row was written by the old engine and can't be trusted
        # in any field — and clear target_weight so the next engine pass
        # picks a weight matching the corrected rep scheme.
        app, db = app_ctx
        from app import _heal_prescription_volume_floor
        from models import WeeklyPrescription
        u = self._make_user(app_ctx)
        with app.test_request_context():
            db.session.add(WeeklyPrescription(
                user_id=u.id, week=5, day_idx=1, exercise_order=0,
                exercise_name="Barbell Bent-Over Row",
                sets=2, reps="12", rest="2-3 min",
                target_weight=100.0,
                source="engine",
            ))
            db.session.commit()
            _heal_prescription_volume_floor(u.id, week=5)
            row = WeeklyPrescription.query.filter_by(user_id=u.id, week=5).first()
        assert row.sets == 5
        assert row.reps == "5"
        assert row.target_weight is None, (
            "target_weight must be cleared so the engine recomputes for the "
            "corrected rep scheme on next generation"
        )

    def test_does_not_touch_coach_authored_row(self, app_ctx):
        app, db = app_ctx
        from app import _heal_prescription_volume_floor
        from models import WeeklyPrescription
        u = self._make_user(app_ctx)
        with app.test_request_context():
            db.session.add(WeeklyPrescription(
                user_id=u.id, week=5, day_idx=1, exercise_order=0,
                exercise_name="Barbell Bent-Over Row",
                sets=2, reps="12", source="coach",
            ))
            db.session.commit()
            _heal_prescription_volume_floor(u.id, week=5)
            row = WeeklyPrescription.query.filter_by(user_id=u.id, week=5).first()
        assert row.sets == 2, "coach intentions are sacred; heal must skip"

    def test_does_not_widen_above_configured(self, app_ctx):
        # If a user/coach previously bumped sets HIGHER than configured, leave
        # it alone. Heal is a floor, not an equality.
        app, db = app_ctx
        from app import _heal_prescription_volume_floor
        from models import WeeklyPrescription
        u = self._make_user(app_ctx)
        with app.test_request_context():
            db.session.add(WeeklyPrescription(
                user_id=u.id, week=5, day_idx=1, exercise_order=0,
                exercise_name="Barbell Bent-Over Row",
                sets=7, reps="5", source="engine",
            ))
            db.session.commit()
            _heal_prescription_volume_floor(u.id, week=5)
            row = WeeklyPrescription.query.filter_by(user_id=u.id, week=5).first()
        assert row.sets == 7
