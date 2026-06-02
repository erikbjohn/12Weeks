"""Tests for the current coach_assembler (multi-agent design).

History: an earlier generation of this file tested an "envelope contract"
coach (<schedule>/<directive>/<motivation> sections, a rules-engine prefill,
per-section builders, uniform 0.6 temps, an ALL_SECTIONS set). That
architecture was replaced by the multi-agent design (coach_agents.AGENTS with
per-agent temps + tailored `requires`, coach_chat_multiagent, no envelope).
Those fossil tests were deleted; what remains here pins the invariants that
genuinely still matter for the LIVE assembler:

  * assemble_prompt(agent, ctx) produces a usable prompt for EVERY agent
    (dedicated protocol or freeform fallback) with no .format() KeyError;
  * empty athlete data is marked "(no data)" / "do not invent" so the coach
    cannot confabulate numbers (anti-confabulation guard);
  * coach memories are bounded so context can't blow up;
  * CORE_PROMPT keeps its banned-phrase guidance + format placeholders.

These mirror the live call path in app.py: build_filtered_context(agent) ->
assemble_prompt(agent, ctx).
"""
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


class TestAssemblePromptLiveContract:
    def test_assemble_prompt_produces_usable_prompt(self, app_ctx):
        from coach_assembler import assemble_prompt, build_filtered_context
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            ctx = build_filtered_context("conversation")
            prompt = assemble_prompt("conversation", ctx)
        assert prompt and len(prompt) > 200          # non-trivial
        assert "{athlete_data_block}" not in prompt   # all placeholders filled
        assert "{food_safety_block}" not in prompt

    def test_every_agent_resolves_to_a_usable_prompt(self, app_ctx):
        """No agent may crash for lack of a protocol — dedicated or freeform."""
        from coach_assembler import assemble_prompt, build_filtered_context
        from coach_agents import AGENTS
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            for agent in AGENTS:
                ctx = build_filtered_context(agent)
                prompt = assemble_prompt(agent, ctx)
                assert prompt and "<protocol" in prompt, \
                    f"agent {agent} produced no protocol block"

    def test_weekly_planning_injects_day_by_day_directive(self, app_ctx):
        """The weekly_planning prompt must carry the computed pacing directive
        (see test_weekly_planning_progress for the counting)."""
        from coach_assembler import assemble_prompt, build_filtered_context
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            ctx = build_filtered_context("weekly_planning")
            prompt = assemble_prompt("weekly_planning", ctx)
        assert "<planning_progress>" in prompt


class TestAntiConfabulationGuard:
    """The coach must never invent numbers. Two guards, both live:
    (1) the assembled prompt instructs the model to cite provided data and not
        invent; (2) genuinely-absent days are marked '(no data)', not fabricated.
    This is the live replacement for the old per-section 'NONE' sentinels."""

    def test_prompt_instructs_cite_not_invent(self, app_ctx):
        from coach_assembler import assemble_prompt, build_filtered_context
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            ctx = build_filtered_context("conversation")
            prompt = assemble_prompt("conversation", ctx).lower()
        assert "do not invent" in prompt or "cite from" in prompt

    def test_absent_days_marked_not_fabricated(self, app_ctx):
        """With no program rows, days read '(no data)' — never invented sets."""
        from coach_assembler import _format_athlete_data
        app, _ = app_ctx
        with app.app_context():
            ctx = {"week": 1, "phase": {"label": "Phase 1", "focus": "build"}}
            out = _format_athlete_data(ctx, ["base"])
        assert "(no data)" in out


class TestCoachMemoriesBounded:
    def test_memories_capped(self, app_ctx):
        from coach_assembler import _build_coach_memories
        from models import CoachMemory
        from app import db
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        for i in range(60):
            db.session.add(CoachMemory(
                user_id=u.id, content=f"memory {i}",
                memory_type="event", week=1,
            ))
        db.session.commit()
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_coach_memories()
        mems = out["coach_memories"]
        assert len(mems) <= 50, "coach memories must be bounded to protect context size"
        # shape contract used downstream
        assert set(mems[0].keys()) == {"type", "content", "week"}


class TestCorePromptGuards:
    def test_lists_banned_phrases(self):
        from coach_assembler import CORE_PROMPT
        low = CORE_PROMPT.lower()
        assert "your call" in low
        assert "great job" in low

    def test_keeps_format_placeholders(self):
        from coach_assembler import CORE_PROMPT
        assert "{athlete_data_block}" in CORE_PROMPT
        assert "{food_safety_block}" in CORE_PROMPT
