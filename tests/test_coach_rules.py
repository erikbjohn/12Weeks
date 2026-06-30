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
        # Coach-or-nothing: the resolver no longer falls back to the static
        # template, so seed a real COACH prescription for this day.
        from app import db as _db
        from models import WeeklyPrescription
        WeeklyPrescription.query.filter_by(user_id=u.id, week=5, day_idx=3).delete()
        for i, nm in enumerate(["Barbell Bent-Over Row", "Weighted Pull-Up"]):
            _db.session.add(WeeklyPrescription(user_id=u.id, week=5, day_idx=3,
                                               exercise_order=i, exercise_name=nm, sets=4,
                                               reps="8", rest="90s", source="coach"))
        _db.session.commit()
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


class TestFastingState:
    def test_weekday_morning_in_16h_fast(self, app_ctx):
        # Wednesday 9 AM — fasting since Tue 7 PM = 14h into 16h IF
        from coach_rules import _compute_fasting_state
        from datetime import datetime
        from zoneinfo import ZoneInfo
        app, _ = app_ctx
        PACIFIC = ZoneInfo("America/Los_Angeles")
        wed_9am = datetime(2026, 4, 29, 9, 0, tzinfo=PACIFIC)
        with app.test_request_context():
            state = _compute_fasting_state(now_local=wed_9am)
        assert state.fasting_active is True
        assert state.fasting_target_hours == 16
        assert 13.5 <= state.fasting_hours <= 14.5
        # Break expected at 11 AM the same day
        assert state.fasting_break_at.hour == 11

    def test_weekday_eating_window(self, app_ctx):
        # Wednesday 1 PM — inside 11AM-7PM eating window
        from coach_rules import _compute_fasting_state
        from datetime import datetime
        from zoneinfo import ZoneInfo
        app, _ = app_ctx
        PACIFIC = ZoneInfo("America/Los_Angeles")
        wed_1pm = datetime(2026, 4, 29, 13, 0, tzinfo=PACIFIC)
        with app.test_request_context():
            state = _compute_fasting_state(now_local=wed_1pm)
        assert state.fasting_active is False
        assert state.fasting_hours is None

    def test_weekend_long_fast_active(self, app_ctx):
        # Sunday 10 AM — 15h into Sat-7PM-to-Mon-11AM fast
        from coach_rules import _compute_fasting_state
        from datetime import datetime
        from zoneinfo import ZoneInfo
        app, _ = app_ctx
        PACIFIC = ZoneInfo("America/Los_Angeles")
        sun_10am = datetime(2026, 5, 3, 10, 0, tzinfo=PACIFIC)
        with app.test_request_context():
            state = _compute_fasting_state(now_local=sun_10am)
        assert state.fasting_active is True
        assert state.fasting_target_hours == 40
        assert 14.5 <= state.fasting_hours <= 15.5
        # Break Monday 11 AM
        assert state.fasting_break_at.weekday() == 0  # Monday
        assert state.fasting_break_at.hour == 11


class TestRefusalDetection:
    @pytest.mark.parametrize("msg", [
        "I'm gonna skip Friday's lift",
        "thinking about resting tomorrow",
        "can I take it easy today",
        "what about doing it tonight instead",
        "should I do the run later",
        "do I really have to lift today",
        "maybe I'll just do the run and skip the lift",
        "I don't think I can lift today",
        "feeling drained",
        "too sore today",
        "do it tomorrow",
        "switch to a rest day",
        "need a break",
        "let me skip just this one",
    ])
    def test_refusal_triggered(self, msg):
        from coach_rules import _detect_refusal
        triggered, reason = _detect_refusal(msg)
        assert triggered is True
        assert reason  # non-empty

    @pytest.mark.parametrize("msg", [
        "just finished the lift, felt great",
        "logged my run, hr was 142",
        "what's tomorrow",
        "phase 2 thursday — what's the plan",
        "",
        None,
    ])
    def test_refusal_not_triggered(self, msg):
        from coach_rules import _detect_refusal
        triggered, reason = _detect_refusal(msg)
        assert triggered is False
        assert reason is None


PACIFIC = ZoneInfo("America/Los_Angeles")


class TestDirectiveComputation:
    """One test per rule in the 15-row directive table from the spec."""

    def _base_kwargs(self, **overrides):
        """Build the keyword args for _compute_directive with sensible defaults."""
        from datetime import datetime, time as dtime
        kwargs = {
            "now_local": datetime(2026, 4, 30, 6, 30, tzinfo=PACIFIC),  # Thu 6:30am
            "workout_today": None,
            "workout_today_scheduled_at": dtime(6, 0),
            "workout_today_status": "rest",
            "run_today": None,
            "run_today_status": "rest",
            "workout_tomorrow": None,
            "workout_tomorrow_scheduled_at": None,
            "run_tomorrow": None,
            "fasting_active": False,
            "weekend_fast_active": False,
            "is_pr_session": False,
            "next_target_hint": None,
            "refusal_required": False,
            "phase_summary": "Phase 2, week 5",
        }
        kwargs.update(overrides)
        return kwargs

    def _summary(self, lift="Front Squat"):
        from coach_rules import WorkoutSummary
        return WorkoutSummary(lift_name=lift, exercise_names=[lift], is_rest=False)

    def _run(self, label="Z2 30 min"):
        from coach_rules import RunSummary
        return RunSummary(run_type="z2", label=label, scheduled_at=None, detail="")

    def test_rule_1_refusal_overrides(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="not_started",
            refusal_required=True,
        ))
        assert "Train as planned" in d.text
        assert d.category == "refusal"

    def test_rule_2_in_progress(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="in_progress",
        ))
        assert "Continue" in d.text
        assert "Front Squat" in d.text

    def test_rule_3_workout_done_run_pending(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="complete",
            run_today=self._run("Z2 30 min"), run_today_status="not_started",
        ))
        assert "Run now" in d.text
        assert "Z2 30 min" in d.text

    def test_rule_4_in_window(self):
        from datetime import datetime, time as dtime
        from coach_rules import _compute_directive
        # Window is ±2h around 6 AM scheduled — 6:30 AM is in window
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 6, 30, tzinfo=PACIFIC),
            workout_today=self._summary(), workout_today_status="not_started",
            workout_today_scheduled_at=dtime(6, 0),
        ))
        assert "Lift now" in d.text
        assert "Front Squat" in d.text

    def test_rule_5_before_window(self):
        from datetime import datetime, time as dtime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 3, 30, tzinfo=PACIFIC),
            workout_today=self._summary(), workout_today_status="not_started",
            workout_today_scheduled_at=dtime(6, 0),
        ))
        assert "Lift at" in d.text or "06:00" in d.text

    def test_rule_6_after_window_missed(self):
        from datetime import datetime, time as dtime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 13, 0, tzinfo=PACIFIC),
            workout_today=self._summary(), workout_today_status="not_started",
            workout_today_scheduled_at=dtime(6, 0),
        ))
        assert "Missed" in d.text or "missed" in d.text

    def test_rule_7_sunday_long_run(self):
        from datetime import datetime
        from coach_rules import _compute_directive, RunSummary
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 5, 3, 7, 0, tzinfo=PACIFIC),  # Sunday
            workout_today=None, workout_today_status="rest",
            run_today=RunSummary(run_type="z2_long", label="Z2 long 75 min",
                                 scheduled_at=None, detail=""),
            run_today_status="not_started",
        ))
        assert "long run" in d.text.lower() or "Z2 long" in d.text

    def test_rule_8_run_pending_non_sunday(self):
        from datetime import datetime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 4, 30, 7, 0, tzinfo=PACIFIC),  # Thu
            workout_today=None, workout_today_status="rest",
            run_today=self._run("Z2 30 min"), run_today_status="not_started",
        ))
        assert "Run today" in d.text or "Run now" in d.text

    def test_rule_10_recovery_day(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=None, workout_today_status="rest",
            run_today=None, run_today_status="rest",
        ))
        assert "Recovery" in d.text or "recovery" in d.text

    def test_rule_11_both_complete(self):
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            workout_today=self._summary(), workout_today_status="complete",
            run_today=self._run(), run_today_status="logged",
            workout_tomorrow=self._summary(lift="DB Bench"),
        ))
        assert "Tomorrow" in d.text
        assert "DB Bench" in d.text

    def test_rule_12_weekend_fast(self):
        from datetime import datetime
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs(
            now_local=datetime(2026, 5, 3, 10, 0, tzinfo=PACIFIC),  # Sunday 10am
            workout_today=None, workout_today_status="rest",
            run_today=None, run_today_status="rest",
            weekend_fast_active=True,
        ))
        assert "Fast" in d.text or "fast" in d.text
        assert "Monday" in d.text or "11" in d.text

    def test_rule_15_generic_chat(self):
        # No refusal, no workout today, no run today → fallback
        from coach_rules import _compute_directive
        d = _compute_directive(**self._base_kwargs())
        assert d.text  # non-empty
        assert d.category in {"recovery", "generic_chat"}


class TestPrefillRendering:
    def test_schedule_includes_now_and_workout_and_run(self):
        from coach_rules import _render_prefilled_schedule, WorkoutSummary, RunSummary
        from datetime import datetime, time as dtime
        s = _render_prefilled_schedule(
            now_local=datetime(2026, 4, 30, 6, 30, tzinfo=PACIFIC),
            workout_today=WorkoutSummary(
                lift_name="Front Squat", exercise_names=["Front Squat"], is_rest=False,
            ),
            workout_today_scheduled_at=dtime(6, 0),
            run_today=RunSummary(run_type="z2", label="Z2 30 min",
                                 scheduled_at=dtime(6, 45), detail=""),
            workout_tomorrow=None,
            workout_tomorrow_scheduled_at=None,
            run_tomorrow=None,
        )
        assert s.startswith("<schedule>")
        assert s.endswith("</schedule>")
        assert "Thursday" in s
        assert "06:30" in s or "6:30" in s
        assert "Front Squat" in s
        assert "Z2 30 min" in s

    def test_directive_renders_clean(self):
        from coach_rules import _render_prefilled_directive, Directive
        s = _render_prefilled_directive(
            Directive(text="Lift now. Front Squat.", category="workout_in_window")
        )
        assert s == "<directive>Lift now. Front Squat.</directive>"


class TestComputeCoachRulesEnd:
    def _make_user(self, app_ctx):
        from models import User, UserEquipment, PhysicalAssessment
        app, db = app_ctx
        u = User(email=f"end-{id(self)}@example.com", password_hash="x")
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

    def test_end_to_end_thursday_morning(self, app_ctx):
        from coach_rules import compute_coach_rules
        from datetime import datetime
        from flask_login import login_user
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            rules = compute_coach_rules(
                user_id=u.id,
                now=datetime(2026, 4, 30, 13, 30),  # naive UTC → 06:30 PDT Thursday
                latest_user_message=None,
            )
        assert rules.local_weekday in {
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        }
        assert rules.prefilled_schedule.startswith("<schedule>")
        assert rules.prefilled_directive.startswith("<directive>")
        assert rules.directive.text  # non-empty
        assert rules.refusal_required is False

    def test_refusal_propagates_to_directive_and_flag(self, app_ctx):
        from coach_rules import compute_coach_rules
        from datetime import datetime
        from flask_login import login_user
        app, _ = app_ctx
        u = self._make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            rules = compute_coach_rules(
                user_id=u.id,
                now=datetime(2026, 4, 30, 13, 30),
                latest_user_message="thinking about resting tomorrow",
            )
        assert rules.refusal_required is True
        assert rules.refusal_reason
        assert "Train as planned" in rules.directive.text


class TestWorkoutStatusVsCompletion:
    def test_partial_logging_returns_in_progress(self, app_ctx):
        # User logs 2 sets but never marks DayCompletion.done — should be in_progress, NOT complete
        from coach_rules import _compute_workout_status
        from models import SetLog
        from datetime import date
        from app import db
        app_obj, _ = app_ctx
        from models import User
        u = User(email=f"status-test-{id(self)}@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
        for i in range(2):
            db.session.add(SetLog(
                user_id=u.id, exercise_name="Front Squat", week=5, day_idx=0,
                set_number=i+1, weight=175, reps=5, done=True, logged_date=date.today(),
            ))
        db.session.commit()
        with app_obj.test_request_context():
            s = _compute_workout_status(
                user_id=u.id, week=5, day_idx=0,
                today_date=date.today(), is_rest=False,
            )
        assert s == "in_progress", f"expected in_progress (no DayCompletion.done), got {s}"

    def test_day_completion_flag_returns_complete(self, app_ctx):
        # An explicit DayCompletion.done marks the day complete — but ONLY when it
        # was completed TODAY (C5 date-gate). api_toggle_day now stamps
        # completed_at, so a real same-day "mark done" carries today's date. A
        # bare flag from a prior cycle no longer reads complete (see
        # test_phantom_done_durable for the stale case).
        from coach_rules import _compute_workout_status
        from models import DayCompletion
        from datetime import date
        from app import db
        app_obj, _ = app_ctx
        from models import User
        u = User(email=f"dc-test-{id(self)}@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
        db.session.add(DayCompletion(user_id=u.id, week=5, day_idx=0, done=True,
                                     completed_at=date.today().isoformat()))
        db.session.commit()
        with app_obj.test_request_context():
            s = _compute_workout_status(
                user_id=u.id, week=5, day_idx=0,
                today_date=date.today(), is_rest=False,
            )
        assert s == "complete"
