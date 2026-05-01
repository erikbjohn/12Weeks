"""Unit tests for the coach rules engine.

The rules engine is a pure function (user_id, now, latest_user_message)
-> CoachRules. No LLM. Deterministic. The cornerstone of the coach
rewrite — every fact the LLM sees about schedule, directive, time, and
refusal must come from here.
"""
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


class TestTimeHelpers:
    def test_user_local_now_has_pacific_tz(self):
        from coach_rules import _user_local_now
        n = _user_local_now()
        assert n.tzinfo is not None
        assert "Los_Angeles" in str(n.tzinfo)

    def test_user_local_now_accepts_override(self):
        from coach_rules import _user_local_now
        fixed = datetime(2026, 4, 30, 10, 30, tzinfo=timezone.utc)
        n = _user_local_now(now=fixed)
        # 10:30 UTC = 03:30 PDT
        assert n.hour == 3
        assert n.minute == 30


class TestDataclassesShape:
    def test_workout_summary_fields(self):
        from coach_rules import WorkoutSummary
        w = WorkoutSummary(
            lift_name="Front Squat",
            exercise_names=["Front Squat", "RDL"],
            is_rest=False,
        )
        assert w.lift_name == "Front Squat"
        assert w.exercise_names == ["Front Squat", "RDL"]
        assert w.is_rest is False

    def test_run_summary_fields(self):
        from coach_rules import RunSummary
        r = RunSummary(
            run_type="z2",
            label="Z2 30 min",
            scheduled_at=dtime(6, 45),
            detail="Easy effort, HR < 150",
        )
        assert r.run_type == "z2"
        assert r.label == "Z2 30 min"
        assert r.scheduled_at == dtime(6, 45)

    def test_directive_fields(self):
        from coach_rules import Directive
        d = Directive(text="Lift now. Front Squat.", category="workout_in_window")
        assert d.text == "Lift now. Front Squat."
        assert d.category == "workout_in_window"

    def test_coach_rules_is_frozen(self):
        from coach_rules import CoachRules, Directive
        # Try to construct with all required fields
        from datetime import datetime, timezone, time as dtime
        r = CoachRules(
            now_utc=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
            now_local=datetime(2026, 4, 30, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            local_date_iso="2026-04-30",
            local_weekday="Thursday",
            local_time_hhmm="10:00",
            workout_today=None,
            workout_today_scheduled_at=dtime(6, 0),
            workout_today_status="rest",
            run_today=None,
            run_today_status="rest",
            workout_tomorrow=None,
            workout_tomorrow_scheduled_at=None,
            run_tomorrow=None,
            fasting_active=False,
            fasting_hours=None,
            fasting_target_hours=None,
            fasting_break_at=None,
            directive=Directive(text="Recovery day.", category="rest"),
            refusal_required=False,
            refusal_reason=None,
            prefilled_schedule="<schedule>...</schedule>",
            prefilled_directive="<directive>Recovery day.</directive>",
        )
        # Frozen — should raise FrozenInstanceError
        with pytest.raises(Exception):
            r.local_weekday = "Friday"


class TestWorkoutResolution:
    def _make_user(self, app_ctx):
        from models import User, UserEquipment, PhysicalAssessment
        app, db = app_ctx
        u = User(email=f"rules-{id(self)}@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "lat_pulldown", "cable_machine",
            "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
            "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
            "dip_station", "ab_machine", "smith_machine",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq); db.session.add(pa); db.session.commit()
        return u

    def test_workout_today_resolves_for_phase_2_thursday(self, app_ctx):
        # Phase 2, Thursday (day_idx=3) — Erik's deadlift/back-side day.
        from coach_rules import _resolve_workout_for_day_summary
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            from flask_login import login_user
            login_user(u)
            summary = _resolve_workout_for_day_summary(u.id, week=5, day_idx=3)
        assert summary is not None
        assert summary.is_rest is False
        # Phase 2 Thu has Weighted Pull-Up + BB Row per spec §4
        assert any("Row" in n or "Pull-Up" in n for n in summary.exercise_names)

    def test_workout_today_rest_day(self, app_ctx):
        # Phase 1 Sunday (day_idx=6) is rest in the new program.
        from coach_rules import _resolve_workout_for_day_summary
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            from flask_login import login_user
            login_user(u)
            summary = _resolve_workout_for_day_summary(u.id, week=1, day_idx=6)
        assert summary is not None
        assert summary.is_rest is True
        assert summary.exercise_names == []


class TestWorkoutStatus:
    def test_status_not_started_when_no_sets_logged(self, app_ctx):
        from coach_rules import _compute_workout_status
        from datetime import date
        app, _ = app_ctx
        # No sets — status is "not_started" for a non-rest day
        with app.test_request_context():
            s = _compute_workout_status(
                user_id=999_999, week=5, day_idx=3,
                today_date=date.today(), is_rest=False,
            )
        assert s == "not_started"

    def test_status_rest_when_is_rest(self, app_ctx):
        from coach_rules import _compute_workout_status
        from datetime import date
        app, _ = app_ctx
        with app.test_request_context():
            s = _compute_workout_status(
                user_id=999_999, week=5, day_idx=6,
                today_date=date.today(), is_rest=True,
            )
        assert s == "rest"


class TestWorkoutScheduledAt:
    def test_default_6am_for_non_rest(self, app_ctx):
        from coach_rules import _compute_workout_scheduled_at
        app, _ = app_ctx
        with app.test_request_context():
            t = _compute_workout_scheduled_at(user_id=999, is_rest=False)
        assert t == dtime(6, 0)

    def test_none_for_rest(self, app_ctx):
        from coach_rules import _compute_workout_scheduled_at
        app, _ = app_ctx
        with app.test_request_context():
            t = _compute_workout_scheduled_at(user_id=999, is_rest=True)
        assert t is None


class TestRunResolution:
    def test_run_today_phase_2_thursday_is_hiit(self, app_ctx):
        from coach_rules import _resolve_run_for_day
        app, _ = app_ctx
        with app.test_request_context():
            r = _resolve_run_for_day(week=5, day_idx=3)
        assert r is not None
        assert r.run_type == "hiit"

    def test_run_today_sunday_is_long(self, app_ctx):
        from coach_rules import _resolve_run_for_day
        app, _ = app_ctx
        with app.test_request_context():
            r = _resolve_run_for_day(week=5, day_idx=6)
        assert r is not None
        assert r.run_type == "z2_long"


class TestRunStatus:
    def test_status_not_started_when_no_log(self, app_ctx):
        from coach_rules import _compute_run_status
        from datetime import date
        app, _ = app_ctx
        with app.test_request_context():
            s = _compute_run_status(
                user_id=999_999,
                today_date=date.today(),
                run_planned=True,
            )
        assert s == "not_started"

    def test_status_rest_when_no_run_planned(self, app_ctx):
        from coach_rules import _compute_run_status
        from datetime import date
        app, _ = app_ctx
        with app.test_request_context():
            s = _compute_run_status(
                user_id=999_999,
                today_date=date.today(),
                run_planned=False,
            )
        assert s == "rest"
