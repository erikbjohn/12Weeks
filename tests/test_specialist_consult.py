"""Tests for specialist consult functions."""
import pytest
from unittest.mock import MagicMock, patch


def test_nutritionist_consult_loads_prompt_and_calls_anthropic():
    """consult() should load nutritionist.md, build the system prompt with
    athlete_data slice, call Anthropic, return the response text."""
    from coach_specialists import nutritionist

    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="Recommendation: refeed 30g.")]

    with patch("coach_specialists.nutritionist._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_specialists.nutritionist._build_athlete_slice", return_value="<slice/>"):
            result = nutritionist.consult(
                brief="Should the athlete eat carbs today?",
                user_id=1,
            )

    assert "refeed" in result
    # Verify the nutritionist persona was loaded (system prompt was passed)
    call_kwargs = mc.return_value.messages.create.call_args.kwargs
    assert "Nutritionist" in call_kwargs["system"]
    assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_strength_consult_uses_strength_persona():
    from coach_specialists import strength
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="Recommendation: 4x3 @ 165.")]
    with patch("coach_specialists.strength._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_specialists.strength._build_athlete_slice", return_value="<slice/>"):
            result = strength.consult(brief="What weight today?", user_id=1)
    call_kwargs = mc.return_value.messages.create.call_args.kwargs
    assert "Strength Coach" in call_kwargs["system"]


def test_running_consult_uses_running_persona():
    from coach_specialists import running
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="Recommendation: Z2 35 min.")]
    with patch("coach_specialists.running._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_response
        with patch("coach_specialists.running._build_athlete_slice", return_value="<slice/>"):
            result = running.consult(brief="Run today?", user_id=1)
    call_kwargs = mc.return_value.messages.create.call_args.kwargs
    assert "Running Coach" in call_kwargs["system"]
