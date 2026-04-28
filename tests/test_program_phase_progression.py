"""Per-phase progression rules from the spec at
docs/superpowers/specs/2026-04-28-12-week-program-rebuild-design.md §1.

Rules:
- Phase 1 (wks 1-3): reps build 8→12, weight pinned. At cap → +5 lb upper /
  +10 lb lower, reps reset to 8.
- Phase 2 (wks 5-7): weight bumps each session, reps pinned, sets pinned.
- Phase 3 (wks 9-11): weights HOLD. Optional bump only if RPE 6 confirmed
  in two consecutive sessions.
- Week 12: HOLD everything. Mini-taper.
"""
import pytest
from datetime import date, timedelta


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


@pytest.fixture
def user_with_history(app_ctx):
    """Build a user with one logged session for an exercise."""
    app, db = app_ctx
    from models import User, UserEquipment, PhysicalAssessment, SetLog

    def make(exercise, week, day_idx, last_weight, last_reps,
             set_count=4, days_ago=2, prev_weight=None):
        _USER_SEQ[0] += 1
        u = User(email=f"phase-test-{_USER_SEQ[0]}@example.com",
                 password_hash="x")
        db.session.add(u); db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "ez_bar", "kettlebells", "lat_pulldown",
            "cable_machine", "leg_press", "leg_curl_ext", "flat_bench",
            "incline_bench", "pull_up_bar", "weight_plates",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq); db.session.add(pa); db.session.commit()
        # Most-recent session
        recent = date.today() - timedelta(days=days_ago)
        for i in range(set_count):
            db.session.add(SetLog(
                user_id=u.id, exercise_name=exercise, week=week,
                day_idx=day_idx, set_number=i + 1,
                weight=last_weight, reps=last_reps,
                done=True, logged_date=recent,
            ))
        # Optional prior session for "user_increased" detection
        if prev_weight is not None:
            prior = recent - timedelta(days=7)
            for i in range(set_count):
                db.session.add(SetLog(
                    user_id=u.id, exercise_name=exercise, week=max(week - 1, 1),
                    day_idx=day_idx, set_number=i + 1,
                    weight=prev_weight, reps=last_reps,
                    done=True, logged_date=prior,
                ))
        db.session.commit()
        return u
    return make


class TestPhase2WeightProgression:
    def test_phase_2_bumps_weight_when_clean(self, app_ctx, user_with_history):
        # Phase 2 wk 6, Lat Pulldown heavy 5x5 at 100 lb. Last session hit
        # prescribed reps cleanly. Engine should bump weight ~5 lb upper.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_history(
            "Lat Pulldown", week=6, day_idx=1,
            last_weight=100, last_reps=5, set_count=5,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Lat Pulldown", week=6, day_idx=1, exercise_order=0,
            )
        assert t["target_reps"] == 5, "Phase 2 reps must stay pinned at 5"
        assert t["target_sets"] == 5, "Phase 2 sets must stay pinned at 5"
        assert t["target_weight"] is not None
        assert t["target_weight"] >= 105, (
            f"Phase 2 should bump weight from 100; got {t['target_weight']}"
        )


class TestPhase3Hold:
    def test_phase_3_holds_weight_by_default(self, app_ctx, user_with_history):
        # Phase 3 wk 10, Back Squat at 200 lb. Last session at RPE 8 (clean
        # but hard). Spec §1: Phase 3 holds. NO bump.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        u = user_with_history(
            "Back Squat", week=10, day_idx=4,
            last_weight=200, last_reps=3, set_count=3,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Back Squat", week=10, day_idx=4, exercise_order=0,
            )
        # Note: target_weight could be slightly higher only if engine
        # detects RPE-6 confirmed twice. Default behavior = hold = 200.
        assert t["target_weight"] == 200, (
            f"Phase 3 must default-hold; got bump to {t['target_weight']}"
        )
        assert t["progression_indicator"] == "hold", (
            f"Phase 3 default must indicate hold; got "
            f"{t['progression_indicator']}"
        )

    def test_phase_3_drops_when_top_set_rpe_high(
        self, app_ctx, user_with_history
    ):
        # Phase 3 wk 10, Back Squat 200 lb, user logged a SHORT session
        # (missed reps — proxy for RPE >8). Engine should drop 5%.
        app, _db = app_ctx
        from training_engine import compute_next_targets
        # Simulate "missed top set" via short session: last_reps=2 of
        # prescribed 3. last_set_count low.
        u = user_with_history(
            "Back Squat", week=10, day_idx=4,
            last_weight=200, last_reps=2, set_count=2,
        )
        with app.test_request_context():
            t = compute_next_targets(
                u.id, "Back Squat", week=10, day_idx=4, exercise_order=0,
            )
        # 5% drop from 200 = 190
        assert t["target_weight"] <= 195, (
            f"Phase 3 should drop weight when last session missed reps; "
            f"got {t['target_weight']}"
        )
