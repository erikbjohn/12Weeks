"""Tests that consult_* tools wire to the specialist runtime modules."""
from unittest.mock import patch


def test_consult_nutritionist_tool_dispatches_to_specialist():
    from coach_tools import execute_tool
    with patch("coach_specialists.nutritionist.consult", return_value="REC: refeed.") as mc:
        result_str = execute_tool(
            "consult_nutritionist",
            {"brief": "Should athlete eat carbs?"},
            user_id=1,
        )
    mc.assert_called_once_with(brief="Should athlete eat carbs?", user_id=1)
    assert "refeed" in result_str


def test_consult_strength_tool_dispatches():
    from coach_tools import execute_tool
    with patch("coach_specialists.strength.consult", return_value="REC: 4x3.") as mc:
        result_str = execute_tool(
            "consult_strength",
            {"brief": "What weight today?"},
            user_id=1,
        )
    mc.assert_called_once_with(brief="What weight today?", user_id=1)
    assert "4x3" in result_str


def test_consult_running_tool_dispatches():
    from coach_tools import execute_tool
    with patch("coach_specialists.running.consult", return_value="REC: Z2 35 min.") as mc:
        result_str = execute_tool(
            "consult_running",
            {"brief": "Run today?"},
            user_id=1,
        )
    mc.assert_called_once_with(brief="Run today?", user_id=1)
    assert "Z2" in result_str
