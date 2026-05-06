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


def test_exercise_name_triggers_recent_sets_and_e1rm():
    out = classify_required_tools("How heavy was last bench?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_recent_sets" in names
    assert "get_e1rm" in names
    # exercise_name kwarg should be normalized
    rs = next(c for c in out if c.tool_name == "get_recent_sets")
    assert "bench" in rs.kwargs.get("exercise_name", "").lower()


def test_squat_keyword_triggers_recent_sets():
    out = classify_required_tools("What's my squat target?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_recent_sets" in names


def test_weight_query_triggers_get_body_state():
    out = classify_required_tools("How's my weight tracking?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_body_state" in names


def test_calorie_query_triggers_get_body_state():
    out = classify_required_tools("Should I drop calories?", agent_name="conversation")
    names = [c.tool_name for c in out]
    assert "get_body_state" in names


def test_multiple_patterns_dedupe_tools():
    """When multiple patterns trigger, the same tool name should appear
    at most once in the output."""
    out = classify_required_tools("How heavy was bench today?", agent_name="conversation")
    names = [c.tool_name for c in out]
    # get_today_status should appear once even though "today" + a
    # potential "today" implication both could trigger
    assert names.count("get_today_status") == 1
