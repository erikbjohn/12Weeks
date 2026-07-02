"""Marker codification round-trip: every marker format TAUGHT in the
coach_assembler CORE_PROMPT <markers> block must be parseable by
app._parse_coach_markers and must persist to the tables the UI actually reads.

This is the 'Always Codify' guarantee: if the coach emits a marker in the
exact shape its own prompt teaches, the change MUST land in the DB. Before
this test existed the prompt taught formats the parser could never match
(e.g. [WEIGHT: ... new_weight=N] vs regex `adjustment=`), so coach-confirmed
changes were silently dropped — chat said one thing, the card another.
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
def user_factory(app_ctx):
    app, db = app_ctx
    from models import User, UserEquipment, PhysicalAssessment

    def make():
        _USER_SEQ[0] += 1
        u = User(email=f"marker-test-{_USER_SEQ[0]}@example.com", password_hash="x")
        db.session.add(u)
        db.session.commit()
        db.session.add(UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "flat_bench", "pull_up_bar",
        ]))
        db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
        db.session.commit()
        return u
    return make


def _parse(app, text, user_id, week=1):
    from app import _parse_coach_markers
    with app.test_request_context():
        _parse_coach_markers(text, user_id, week=week)


# ─── The prompt must teach EXACTLY what the parser parses ────────────────────

class TestPromptTeachesParseableFormats:
    def test_canonical_formats_present_in_core_prompt(self):
        from coach_assembler import CORE_PROMPT
        for taught in [
            "[SCHEDULE: day=N, time=3:00 PM, notes=text]",
            "[PRESCRIPTION: week=N, day=N, exercise=Name, sets=N, reps=N, rest=60-90s, weight=N, reason=text]",
            "[SWAP: day_idx=N, exercise_idx=N, old=Name, new=Name, reason=text]",
            "[WEIGHT: exercise=Name, new_weight=N, reason=text]",
            "[RUN: day=N, duration=40 min, type=zone2, reason=text]",
            "[NUTRITION: day=N, meal_type=fast_day, reason=text]",
            "[NUTRITION: daily_calories=N, reason=text]",
            "[BMR_UPDATE: new_bmr=N, reason=text]",
            "[LOCKOUT_WARNING: count=N, reason=text]",
        ]:
            assert taught in CORE_PROMPT, f"CORE_PROMPT no longer teaches {taught}"

    def test_unparseable_legacy_formats_gone_from_prompt(self):
        from coach_assembler import CORE_PROMPT
        for bad in [
            "[SCHEDULE: day_idx=N, change_description]",
            "[NUTRITION: change_description]",
            "[BMR_UPDATE: daily_calories=N",
            "[LOCKOUT_WARNING: violation_description]",
            "[RUN: day_idx=N, type=text, duration=text",
        ]:
            assert bad not in CORE_PROMPT, f"CORE_PROMPT still teaches unparseable {bad}"


# ─── Each taught format must persist ─────────────────────────────────────────

class TestScheduleMarker:
    def test_canonical_schedule_persists(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import WeeklyScheduleOverride
        u = user_factory()
        _parse(app, "[SCHEDULE: day=2, time=3:00 PM, notes=late meeting]", u.id)
        with app.app_context():
            row = WeeklyScheduleOverride.query.filter_by(user_id=u.id, week=1, day_idx=2).first()
        assert row is not None
        assert row.workout_time == "3:00 PM"
        assert row.notes == "late meeting"


class TestPrescriptionMarker:
    def test_canonical_prescription_writes_weekly_prescription(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import WeeklyPrescription
        u = user_factory()
        _parse(app, "[PRESCRIPTION: week=2, day=1, exercise=Barbell Bench Press, "
                    "sets=4, reps=8, rest=90s, weight=145, reason=athlete confirmed bump]", u.id)
        with app.app_context():
            row = WeeklyPrescription.query.filter_by(
                user_id=u.id, week=2, day_idx=1, exercise_name="Barbell Bench Press").first()
        assert row is not None
        assert row.sets == 4 and row.reps == "8"
        assert row.target_weight == 145
        assert row.source == "coach"
        assert row.adjustment_reason == "athlete confirmed bump"

    def test_day_idx_alias_without_week_uses_context_week(self, app_ctx, user_factory):
        # The shape the OLD prompt taught — must not be silently dropped.
        app, db = app_ctx
        from models import WeeklyPrescription
        u = user_factory()
        _parse(app, "[PRESCRIPTION: day_idx=3, exercise=Front Squat, sets=4, reps=5, "
                    "weight=150, reason=confirmed]", u.id, week=5)
        with app.app_context():
            row = WeeklyPrescription.query.filter_by(
                user_id=u.id, week=5, day_idx=3, exercise_name="Front Squat").first()
        assert row is not None
        assert row.target_weight == 150


class TestWeightMarker:
    def _seed_rx(self, app, db, user_id, weight=140.0, week=1):
        from models import WeeklyPrescription
        with app.app_context():
            db.session.add(WeeklyPrescription(
                user_id=user_id, week=week, day_idx=1, exercise_order=0,
                exercise_name="Barbell Bench Press", sets=4, reps="8",
                target_weight=weight, source="coach"))
            db.session.commit()

    def test_new_weight_updates_prescription_not_exerciselog(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import WeeklyPrescription, ExerciseLog
        u = user_factory()
        self._seed_rx(app, db, u.id)
        _parse(app, "[WEIGHT: exercise=Barbell Bench Press, new_weight=150, reason=athlete asked]", u.id)
        with app.app_context():
            row = WeeklyPrescription.query.filter_by(
                user_id=u.id, week=1, exercise_name="Barbell Bench Press").first()
            dead_rows = ExerciseLog.query.filter_by(user_id=u.id).all()
        assert row.target_weight == 150
        assert row.adjustment_reason == "athlete asked"
        # ExerciseLog is DEAD — the marker must never write to it.
        assert dead_rows == []

    def test_legacy_adjustment_form_still_applies(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import WeeklyPrescription
        u = user_factory()
        self._seed_rx(app, db, u.id, weight=140.0)
        _parse(app, "[WEIGHT: exercise=Barbell Bench Press, adjustment=+5, reason=progression]", u.id)
        with app.app_context():
            row = WeeklyPrescription.query.filter_by(
                user_id=u.id, week=1, exercise_name="Barbell Bench Press").first()
        assert row.target_weight == 145

    def test_guard_rejects_weight_below_proven_top_set(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import WeeklyPrescription, SetLog
        u = user_factory()
        self._seed_rx(app, db, u.id, weight=150.0)
        with app.app_context():
            db.session.add(SetLog(user_id=u.id, exercise_name="Barbell Bench Press",
                                  week=1, day_idx=1, set_number=0, weight=155,
                                  reps=8, done=True))
            db.session.commit()
        _parse(app, "[WEIGHT: exercise=Barbell Bench Press, new_weight=100, reason=hallucinated]", u.id)
        with app.app_context():
            row = WeeklyPrescription.query.filter_by(
                user_id=u.id, week=1, exercise_name="Barbell Bench Press").first()
        assert row.target_weight == 150  # unchanged — write refused

    def test_typed_but_not_done_set_is_not_a_proven_top(self, app_ctx, user_factory):
        # Falsy/ghost data: a weight typed into the UI but never completed must
        # not block a legitimate coach adjustment.
        app, db = app_ctx
        from models import WeeklyPrescription, SetLog
        u = user_factory()
        self._seed_rx(app, db, u.id, weight=140.0)
        with app.app_context():
            db.session.add(SetLog(user_id=u.id, exercise_name="Barbell Bench Press",
                                  week=1, day_idx=1, set_number=0, weight=200,
                                  reps=0, done=False))
            db.session.commit()
        _parse(app, "[WEIGHT: exercise=Barbell Bench Press, new_weight=145, reason=bump]", u.id)
        with app.app_context():
            row = WeeklyPrescription.query.filter_by(
                user_id=u.id, week=1, exercise_name="Barbell Bench Press").first()
        assert row.target_weight == 145

    def test_no_prescription_row_means_no_write_no_crash(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import ExerciseLog
        u = user_factory()
        _parse(app, "[WEIGHT: exercise=Barbell Bench Press, new_weight=150, reason=x]", u.id)
        with app.app_context():
            assert ExerciseLog.query.filter_by(user_id=u.id).all() == []


class TestRunMarker:
    def test_canonical_run_updates_run_plan(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import WeeklyRunPlan, RunOverride
        u = user_factory()
        _parse(app, "[RUN: day=3, duration=40 min, type=zone2, reason=hold volume]", u.id)
        with app.app_context():
            wrp = WeeklyRunPlan.query.filter_by(user_id=u.id, week=1, day_idx=3).first()
            ov = RunOverride.query.filter_by(user_id=u.id, week=1, day_idx=3).first()
        assert wrp is not None and wrp.duration == "40 min" and wrp.source == "coach"
        assert ov is not None and ov.run_type == "zone2"

    def test_old_prompt_order_type_before_duration_still_parses(self, app_ctx, user_factory):
        # The OLD prompt taught [RUN: day_idx=N, type=..., duration=...] —
        # the parser must tolerate that shape rather than silently drop it.
        app, db = app_ctx
        from models import WeeklyRunPlan
        u = user_factory()
        _parse(app, "[RUN: day_idx=4, type=hiit, duration=30 min, reason=intervals]", u.id)
        with app.app_context():
            wrp = WeeklyRunPlan.query.filter_by(user_id=u.id, week=1, day_idx=4).first()
        assert wrp is not None
        assert wrp.duration == "30 min"
        assert wrp.run_type == "hiit"


class TestNutritionBmrLockoutMarkers:
    def test_daily_calories_updates_training_goal(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import TrainingGoal
        u = user_factory()
        with app.app_context():
            db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", daily_calories=2400))
            db.session.commit()
        _parse(app, "[NUTRITION: daily_calories=2200, reason=cut stalled]", u.id)
        with app.app_context():
            goal = TrainingGoal.query.filter_by(user_id=u.id).first()
        assert goal.daily_calories == 2200

    def test_bmr_update_persists_to_assessment(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import PhysicalAssessment
        u = user_factory()
        _parse(app, "[BMR_UPDATE: new_bmr=1800, reason=recalc from weight-loss data]", u.id)
        with app.app_context():
            pa = PhysicalAssessment.query.filter_by(user_id=u.id).first()
        assert pa.actual_bmr == 1800

    def test_lockout_warning_persists_coach_memory(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import CoachMemory
        u = user_factory()
        _parse(app, "[LOCKOUT_WARNING: count=1, reason=skipped Monday workout]", u.id)
        with app.app_context():
            cm = CoachMemory.query.filter_by(user_id=u.id, memory_type="lockout_warning").first()
        assert cm is not None
        assert "skipped Monday workout" in cm.content
