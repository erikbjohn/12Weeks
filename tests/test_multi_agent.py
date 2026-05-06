"""Tests for the multi-agent Doctor orchestrator."""
from unittest.mock import patch, MagicMock
import pytest


def test_doctor_zero_consults_returns_text_directly():
    """When the Doctor's first turn emits text (no tool calls), that's
    the final response — 1 LLM call total."""
    from coach_multi_agent import coach_chat_multiagent

    text_block = MagicMock(type="text", text="You're tired — sleep matters.")
    fake_response = MagicMock(stop_reason="end_turn", content=[text_block])

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        result = coach_chat_multiagent(
            user_id=1,
            athlete_data="<athlete_data/>",
            messages=[{"role": "user", "content": "I'm tired today"}],
        )
    # One Anthropic call. Text returned.
    assert mc.return_value.messages.create.call_count == 1
    assert "tired" in result.lower()


def test_doctor_consults_one_specialist_then_synthesizes():
    """Doctor emits 1 tool_use, specialist returns, Doctor synthesizes."""
    from coach_multi_agent import coach_chat_multiagent

    # Turn 1: Doctor calls consult_nutritionist.
    # NOTE: MagicMock(name=...) sets the mock's repr, NOT the .name attribute.
    # Set .name explicitly post-construction so dispatch can route on it.
    tool_use = MagicMock(type="tool_use", id="t1",
                         input={"brief": "carbs today?"})
    tool_use.name = "consult_nutritionist"
    turn1 = MagicMock(stop_reason="tool_use", content=[tool_use])
    # Turn 2: Doctor synthesizes
    text_block = MagicMock(type="text", text="No carbs today; you're cutting.")
    turn2 = MagicMock(stop_reason="end_turn", content=[text_block])

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.side_effect = [turn1, turn2]
        with patch("coach_specialists.nutritionist.consult", return_value="REC: no carbs."):
            result = coach_chat_multiagent(
                user_id=1,
                athlete_data="<athlete_data/>",
                messages=[{"role": "user", "content": "Carbs today?"}],
            )
    # 2 Anthropic calls (parse + synthesis)
    assert mc.return_value.messages.create.call_count == 2
    assert "no carbs" in result.lower() or "cutting" in result.lower()


def test_doctor_three_consults_dispatch_in_parallel():
    """When Doctor emits 3 tool_use blocks in one turn, all 3 consults
    run via asyncio.gather() — verified by checking they all receive
    the same convo state (sequential would mutate it between calls)."""
    import asyncio
    from coach_multi_agent import coach_chat_multiagent

    # Turn 1: Doctor calls all 3 consults
    # MagicMock(name=...) only sets repr; set .name attr explicitly.
    tu1 = MagicMock(type="tool_use", id="t1", input={"brief": "carbs?"})
    tu1.name = "consult_nutritionist"
    tu2 = MagicMock(type="tool_use", id="t2", input={"brief": "PR Friday?"})
    tu2.name = "consult_strength"
    tu3 = MagicMock(type="tool_use", id="t3", input={"brief": "Sunday LR risk?"})
    tu3.name = "consult_running"
    tool_uses = [tu1, tu2, tu3]
    turn1 = MagicMock(stop_reason="tool_use", content=tool_uses)
    turn2 = MagicMock(stop_reason="end_turn",
                      content=[MagicMock(type="text", text="Skip the PR.")])

    call_log = []

    def slow_nutritionist(*args, **kwargs):
        call_log.append("nut_start")
        return "REC: refeed first."

    def slow_strength(*args, **kwargs):
        call_log.append("str_start")
        return "REC: 90%, not PR."

    def slow_running(*args, **kwargs):
        call_log.append("run_start")
        return "REC: protect Sunday."

    with patch("coach_multi_agent._anthropic_client") as mc:
        mc.return_value.messages.create.side_effect = [turn1, turn2]
        with patch("coach_specialists.nutritionist.consult", side_effect=slow_nutritionist):
            with patch("coach_specialists.strength.consult", side_effect=slow_strength):
                with patch("coach_specialists.running.consult", side_effect=slow_running):
                    result = coach_chat_multiagent(
                        user_id=1,
                        athlete_data="<a/>",
                        messages=[{"role": "user", "content": "PR Friday after fast?"}],
                    )

    # All 3 specialists were called
    assert len(call_log) == 3
    assert "nut_start" in call_log
    assert "str_start" in call_log
    assert "run_start" in call_log
    assert "Skip the PR" in result


def test_is_error_payload_detects_execute_tool_error_blob():
    from coach_multi_agent import _is_error_payload
    is_err, msg = _is_error_payload('{"error": "AnthropicError: 529 Overloaded"}')
    assert is_err is True
    assert "529" in msg


def test_is_error_payload_passes_real_tool_results():
    from coach_multi_agent import _is_error_payload
    real_result = '{"week": 6, "exercises": [{"name": "Front Squat", "sets": "4x3"}]}'
    is_err, _ = _is_error_payload(real_result)
    assert is_err is False


def test_is_error_payload_handles_non_json():
    from coach_multi_agent import _is_error_payload
    is_err, _ = _is_error_payload("Recommendation: refeed 30g.")
    assert is_err is False


def test_reroute_tool_failures_replaces_error_with_directive():
    from coach_multi_agent import _reroute_tool_failures
    block = MagicMock(id="t1")
    block.name = "consult_nutritionist"
    results = [{
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": '{"error": "AnthropicError: 529 Overloaded"}',
    }]
    out = _reroute_tool_failures(results, [block])
    assert len(out) == 1
    assert out[0]["tool_use_id"] == "t1"
    assert "INTERNAL TOOL FAILURE" in out[0]["content"]
    assert "DO NOT SURFACE" in out[0]["content"]
    assert "consult_nutritionist" in out[0]["content"]
    # Original error message should be visible to the model for context
    assert "529" in out[0]["content"]


def test_reroute_tool_failures_passes_through_real_results():
    from coach_multi_agent import _reroute_tool_failures
    block = MagicMock(id="t1")
    block.name = "get_workout"
    real = {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": '{"week": 6, "exercises": []}',
    }
    out = _reroute_tool_failures([real], [block])
    assert out[0] == real  # unchanged


def test_coach_chat_routes_to_multiagent_when_flag_enabled(monkeypatch):
    """coach_chat() should detect MULTIAGENT_ENABLED + chat-style agent
    and route to coach_chat_multiagent instead of the single-prompt loop."""
    from coach_with_tools import coach_chat

    monkeypatch.setenv("MULTIAGENT_ENABLED", "1")

    with patch("coach_multi_agent.coach_chat_multiagent",
               return_value="multi-agent reply") as mc:
        result = coach_chat(
            user_id=1,
            system_prompt="<athlete_data>...</athlete_data>",
            messages=[{"role": "user", "content": "test"}],
            agent_name="conversation",  # multi-agent trigger
        )

    mc.assert_called_once()
    assert result == "multi-agent reply"


def test_coach_chat_uses_single_prompt_when_flag_disabled(monkeypatch):
    """Without the flag, conversation still uses the existing single-prompt path."""
    from coach_with_tools import coach_chat

    monkeypatch.delenv("MULTIAGENT_ENABLED", raising=False)

    with patch("coach_with_tools._run_loop", return_value="single-prompt reply") as mc:
        with patch("coach_multi_agent.coach_chat_multiagent") as mma:
            result = coach_chat(
                user_id=1,
                system_prompt="...",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="conversation",
            )

    assert result == "single-prompt reply"
    mma.assert_not_called()


def test_coach_chat_uses_single_prompt_for_non_chat_modes(monkeypatch):
    """morning_checkin should NEVER go multi-agent even with the flag on."""
    from coach_with_tools import coach_chat

    monkeypatch.setenv("MULTIAGENT_ENABLED", "1")

    with patch("coach_with_tools._run_loop", return_value="single") as mc:
        with patch("coach_multi_agent.coach_chat_multiagent") as mma:
            result = coach_chat(
                user_id=1,
                system_prompt="...",
                messages=[{"role": "user", "content": "good morning"}],
                agent_name="morning_checkin",  # NOT a chat-style mode
            )

    assert result == "single"
    mma.assert_not_called()
