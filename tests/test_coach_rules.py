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
