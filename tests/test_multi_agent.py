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

    # Turn 1: Doctor calls consult_nutritionist
    tool_use = MagicMock(type="tool_use", id="t1", name="consult_nutritionist",
                         input={"brief": "carbs today?"})
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
