"""Tests for the message-pattern classifier that pre-executes tools
before the multi-agent Doctor's first turn."""
from coach_router_classifier import classify_required_tools, ForcedCall


def test_today_keyword_triggers_today_status():
    out = classify_required_tools("What's on my plate today?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_today_status" in names


def test_tomorrow_keyword_triggers_today_status_too():
    """Tomorrow questions need today_status to anchor 'today' first, then
    workout for tomorrow's day_idx."""
    out = classify_required_tools("How heavy is bench tomorrow?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_today_status" in names
    # workout call may also be present; tested separately


def test_no_match_returns_empty_list():
    out = classify_required_tools("How are you?", agent_name="conversation")
    assert out == []


def test_returns_forced_call_dataclass_not_dicts():
    out = classify_required_tools("What's today?", agent_name="conversation")
    assert all(isinstance(c, ForcedCall) for c in out)
    assert all(hasattr(c, "tool_name") and hasattr(c, "kwargs") for c in out)
