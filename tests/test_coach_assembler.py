"""Tests for the rewritten coach_assembler section builders."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


def _make_user(app_ctx):
    from models import User, UserEquipment, PhysicalAssessment
    app, db = app_ctx
    _USER_SEQ[0] += 1
    u = User(email=f"asm-{_USER_SEQ[0]}@example.com", password_hash="x")
    db.session.add(u); db.session.commit()
    eq = UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells"])
    pa = PhysicalAssessment(user_id=u.id, has_gym=True)
    db.session.add(eq); db.session.add(pa); db.session.commit()
    return u


class TestEventTimeline:
    def test_empty_timeline_returns_sentinel(self, app_ctx):
        from coach_assembler import _build_event_timeline
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_event_timeline()
        assert "event_timeline" in out
        assert "<event_timeline>" in out["event_timeline"]
        assert "NONE" in out["event_timeline"]

    def test_includes_set_log_events(self, app_ctx):
        from coach_assembler import _build_event_timeline
        from models import SetLog
        from datetime import date
        from app import db
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        db.session.add(SetLog(
            user_id=u.id, exercise_name="Front Squat", week=5, day_idx=0,
            set_number=1, weight=175, reps=5, done=True, logged_date=date.today(),
        ))
        db.session.commit()
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_event_timeline()
        assert "Front Squat" in out["event_timeline"]
        assert "175" in out["event_timeline"]


class TestRecentCoachDirectives:
    def test_returns_sentinel_when_no_messages(self, app_ctx):
        from coach_assembler import _build_recent_coach_directives
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_recent_coach_directives()
        assert "recent_coach_directives" in out
        assert "<recent_coach_directives>" in out["recent_coach_directives"]
        assert "NONE" in out["recent_coach_directives"]


class TestCoachMemoriesWindow:
    def test_filters_to_last_21_days(self, app_ctx):
        from coach_assembler import _build_coach_memories
        from models import CoachMemory
        from datetime import datetime, timedelta
        from app import db
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        # Old memory (40 days ago) — must be excluded
        old = CoachMemory(
            user_id=u.id, content="old memory",
            memory_type="event", week=1,
        )
        old.created_at = datetime.utcnow() - timedelta(days=40)
        # Recent memory (5 days ago)
        new = CoachMemory(
            user_id=u.id, content="recent memory",
            memory_type="event", week=5,
        )
        new.created_at = datetime.utcnow() - timedelta(days=5)
        db.session.add(old); db.session.add(new); db.session.commit()
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_coach_memories()
        memories = out["coach_memories"]
        contents = [m["content"] for m in memories]
        assert "recent memory" in contents
        assert "old memory" not in contents


class TestAthleteDataSentinels:
    def test_empty_garmin_emits_sentinel(self):
        from coach_assembler import _format_athlete_data
        ctx = {"week": 1, "phase": {"label": "Phase 1", "focus": "build"}}
        out = _format_athlete_data(ctx, ["base"])
        # Should have a Garmin sentinel since ctx has no garmin key
        assert "Garmin" in out and "NONE" in out

    def test_empty_runs_emits_sentinel(self):
        from coach_assembler import _format_athlete_data
        ctx = {"week": 1, "phase": {"label": "Phase 1", "focus": "build"}}
        out = _format_athlete_data(ctx, ["base"])
        # Should have a recent-runs sentinel
        assert "runs" in out.lower() and "NONE" in out

    def test_empty_meals_emits_sentinel(self):
        from coach_assembler import _format_athlete_data
        ctx = {"week": 1, "phase": {"label": "Phase 1", "focus": "build"}}
        out = _format_athlete_data(ctx, ["base"])
        assert "Meals" in out and "NONE" in out

    def test_empty_coach_memories_emits_sentinel(self):
        from coach_assembler import _format_athlete_data
        ctx = {"week": 1, "phase": {"label": "Phase 1", "focus": "build"}}
        out = _format_athlete_data(ctx, ["base"])
        assert "memories" in out.lower() and "NONE" in out

    def test_empty_exercise_history_emits_sentinel(self):
        from coach_assembler import _format_athlete_data
        ctx = {"week": 1, "phase": {"label": "Phase 1", "focus": "build"}}
        out = _format_athlete_data(ctx, ["base"])
        assert "Exercise history" in out and "NONE" in out


class TestCorePromptRewrite:
    def test_includes_envelope_contract(self):
        from coach_assembler import CORE_PROMPT
        # The new prompt MUST instruct the LLM to emit sectioned responses
        assert "<schedule>" in CORE_PROMPT
        assert "<directive>" in CORE_PROMPT
        assert "<motivation>" in CORE_PROMPT
        assert "<refusal>" in CORE_PROMPT

    def test_includes_byte_identical_instruction(self):
        from coach_assembler import CORE_PROMPT
        assert "byte" in CORE_PROMPT.lower() or "echo" in CORE_PROMPT.lower()

    def test_no_ask_questions_instruction(self):
        from coach_assembler import CORE_PROMPT
        # The new CORE_PROMPT must not instruct the LLM to ask questions
        forbidden = ["ask the athlete", "ask one question", "ask what they"]
        for phrase in forbidden:
            assert phrase not in CORE_PROMPT.lower(), f"forbidden phrase present: {phrase}"

    def test_includes_banned_phrase_list(self):
        from coach_assembler import CORE_PROMPT
        # The prompt should list banned phrases inline
        assert "your call" in CORE_PROMPT.lower()
        assert "great job" in CORE_PROMPT.lower()

    def test_keeps_required_placeholders_for_format(self):
        from coach_assembler import CORE_PROMPT
        # Until Task 15 rewrites assemble_prompt, these placeholders must stay
        # so the existing .format() call doesn't fail.
        assert "{athlete_data_block}" in CORE_PROMPT
        assert "{food_safety_block}" in CORE_PROMPT

    def test_assemble_prompt_still_works(self, app_ctx):
        from coach_assembler import assemble_prompt
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            ctx = {
                "athlete_name": "Erik",
                "week": 5,
                "phase": {"label": "Phase 2", "focus": "build"},
                "requires": ["base"],
            }
            prompt = assemble_prompt("conversation", ctx)
        # No KeyError from .format() means the placeholders match
        assert "<schedule>" in prompt
        assert "<directive>" in prompt


class TestProtocolMapRewrite:
    def test_no_protocol_asks_questions(self):
        from coach_assembler import PROTOCOL_MAP
        forbidden = ["ask one question", "ask the athlete", "ask what they"]
        for agent, protocol in PROTOCOL_MAP.items():
            for phrase in forbidden:
                assert phrase not in protocol.lower(), \
                    f"agent {agent} still contains forbidden phrase: {phrase}"

    def test_all_agents_have_protocol(self):
        from coach_assembler import PROTOCOL_MAP
        from coach_agents import AGENTS
        for agent in AGENTS:
            assert agent in PROTOCOL_MAP, f"missing protocol for {agent}"


class TestCoachAgentsConfig:
    def test_all_temps_are_06_except_crisis(self):
        from coach_agents import AGENTS
        for agent, cfg in AGENTS.items():
            if agent == "crisis":
                continue
            assert cfg["temperature"] == 0.6, \
                f"{agent} has temp {cfg['temperature']} (expected 0.6)"

    def test_all_agents_use_all_sections(self):
        from coach_agents import AGENTS, ALL_SECTIONS
        for agent, cfg in AGENTS.items():
            assert cfg["requires"] == ALL_SECTIONS, \
                f"{agent} requires != ALL_SECTIONS"

    def test_all_sections_includes_event_timeline(self):
        from coach_agents import ALL_SECTIONS
        assert "event_timeline" in ALL_SECTIONS
        assert "recent_coach_directives" in ALL_SECTIONS
        # chat_history is intentionally absent — being phased out
        assert "chat_history" not in ALL_SECTIONS

    def test_all_sections_match_registered_builders(self):
        from coach_agents import ALL_SECTIONS
        from coach_assembler import _SECTION_BUILDERS
        # Every name in ALL_SECTIONS must have a registered builder
        for name in ALL_SECTIONS:
            assert name in _SECTION_BUILDERS, \
                f"ALL_SECTIONS includes '{name}' but no @section_builder is registered"
