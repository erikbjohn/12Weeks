"""Integration tests for the full coach pipeline with mocked LLM."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_E2E_SEQ = [0]


def _make_user(app_ctx):
    from models import User, UserEquipment, PhysicalAssessment
    app, db = app_ctx
    _E2E_SEQ[0] += 1
    u = User(email=f"e2e-{_E2E_SEQ[0]}@example.com", password_hash="x")
    db.session.add(u); db.session.commit()
    eq = UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells"])
    pa = PhysicalAssessment(user_id=u.id, has_gym=True)
    db.session.add(eq); db.session.add(pa); db.session.commit()
    return u


def _stub_rules():
    """Build a CoachRules with predictable pre-fills for mock-LLM round-trip."""
    from coach_rules import CoachRules, Directive
    from datetime import datetime, timezone, time as dtime
    from zoneinfo import ZoneInfo
    PACIFIC = ZoneInfo("America/Los_Angeles")
    return CoachRules(
        now_utc=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
        now_local=datetime(2026, 4, 30, 10, 0, tzinfo=PACIFIC),
        local_date_iso="2026-04-30",
        local_weekday="Thursday",
        local_time_hhmm="10:00",
        workout_today=None,
        workout_today_scheduled_at=None,
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
        directive=Directive(text="Recovery day.", category="recovery"),
        refusal_required=False,
        refusal_reason=None,
        prefilled_schedule="<schedule>SCHED</schedule>",
        prefilled_directive="<directive>DIR</directive>",
    )


class TestCoachRespond:
    def test_valid_first_call_renders_clean(self, app_ctx):
        from coach_assembler import coach_respond
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Lift now. Front Squat 5x5.</motivation>"
            )

        with app.test_request_context():
            login_user(u, force=True)
            out = coach_respond(
                user_id=u.id,
                agent_name="conversation",
                user_message="hey",
                rules=_stub_rules(),
                llm_fn=fake_llm,
            )
        assert "SCHED" in out
        assert "DIR" in out
        assert "Lift now" in out
        assert "<schedule>" not in out  # tags stripped

    def test_retry_then_succeed(self, app_ctx):
        from coach_assembler import coach_respond
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        call_count = [0]

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            call_count[0] += 1
            if call_count[0] == 1:
                # banned phrase
                return (
                    "<schedule>SCHED</schedule>\n"
                    "<directive>DIR</directive>\n"
                    "<motivation>Great job today!</motivation>"
                )
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Logged. Recovery day.</motivation>"
            )

        with app.test_request_context():
            login_user(u, force=True)
            out = coach_respond(
                user_id=u.id, agent_name="conversation",
                user_message="hey", rules=_stub_rules(), llm_fn=fake_llm,
            )
        assert call_count[0] == 2
        assert "Great job" not in out
        assert "Logged" in out

    def test_double_failure_falls_back(self, app_ctx):
        from coach_assembler import coach_respond
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Your call!</motivation>"
            )

        with app.test_request_context():
            login_user(u, force=True)
            out = coach_respond(
                user_id=u.id, agent_name="conversation",
                user_message="hey", rules=_stub_rules(), llm_fn=fake_llm,
            )
        # Fallback content: pre-filled + "Logged."
        assert "SCHED" in out
        assert "DIR" in out
        assert "Your call" not in out
        assert "Logged" in out


class TestCoachRespondStreaming:
    def test_streaming_yields_validated_chunks(self, app_ctx):
        from coach_assembler import coach_respond_streaming
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Lift now. Front Squat 5x5.</motivation>"
            )

        with app.test_request_context():
            login_user(u, force=True)
            chunks = list(coach_respond_streaming(
                user_id=u.id, agent_name="conversation",
                user_message="hey", rules=_stub_rules(), llm_fn=fake_llm,
                chunk_size=10,  # small enough to guarantee multiple chunks
            ))
        full = " ".join(chunks)
        assert "SCHED" in full
        assert "DIR" in full
        assert "Lift now" in full
        # Chunks should be smaller than the full text
        assert len(chunks) >= 2

    def test_streaming_runs_validator(self, app_ctx):
        from coach_assembler import coach_respond_streaming
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)

        def fake_llm(system_prompt, messages, temperature, max_tokens):
            return (
                "<schedule>SCHED</schedule>\n"
                "<directive>DIR</directive>\n"
                "<motivation>Your call!</motivation>"
            )

        with app.test_request_context():
            login_user(u, force=True)
            chunks = list(coach_respond_streaming(
                user_id=u.id, agent_name="conversation",
                user_message="hey", rules=_stub_rules(), llm_fn=fake_llm,
            ))
        full = " ".join(chunks)
        # Banned phrase blocked → fallback path
        assert "Your call" not in full
        assert "Logged" in full or "SCHED" in full
