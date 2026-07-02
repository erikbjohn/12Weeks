"""Pre-execute tools based on message-pattern matching, before the
multi-agent Doctor's first turn. Eliminates the "model summarizes
without reading the slice" failure mode by ensuring relevant tool
results are already in the conversation when the model gets the
message.

Pattern rules are conservative — false positives (calling a tool
the model doesn't need) are harmless; false negatives (failing to
call a tool the model needs) are how class-B hallucinations happen.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class ForcedCall:
    """A tool call to pre-execute before the model sees the message."""
    tool_name: str
    kwargs: dict = field(default_factory=dict)


_DAY_RE = re.compile(
    r"\b(today|tomorrow|yesterday|"
    r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|"
    r"fri(day)?|sat(urday)?|sun(day)?)\b",
    re.IGNORECASE,
)

# Map a free-text exercise reference to a canonical name for the tool's
# exercise_name kwarg. Order matters (longer matches first when ambiguous).
_EXERCISE_MAP = [
    (re.compile(r"\bback\s*squat\b", re.I),     "Barbell Back Squat"),
    (re.compile(r"\bfront\s*squat\b", re.I),    "Front Squat"),
    (re.compile(r"\bbench\s*press\b", re.I),    "Barbell Bench Press"),
    (re.compile(r"\bbench\b", re.I),            "Barbell Bench Press"),
    (re.compile(r"\bsquat\b", re.I),            "Barbell Back Squat"),
    # Romanian BEFORE the bare \bdeadlift\b — the loop breaks on first match,
    # so listing the substring pattern first sent "romanian deadlift" questions
    # to Conventional Deadlift history (the wrong lift, pre-fetched as fact).
    (re.compile(r"\b(rdl|romanian\s*deadlift)\b", re.I), "Romanian Deadlift"),
    (re.compile(r"\bdeadlift\b", re.I),         "Conventional Deadlift"),
    (re.compile(r"\bbent.?over\s*row\b", re.I), "Barbell Bent-Over Row"),
    (re.compile(r"\brow\b", re.I),              "Barbell Bent-Over Row"),
    (re.compile(r"\bpull.?up\b", re.I),         "Weighted Pull-Up"),
    (re.compile(r"\bhip\s*thrust\b", re.I),     "Hip Thrust"),
    (re.compile(r"\bovh?p\b|\boverhead\s*press\b|\bohp\b", re.I), "Overhead Press"),
]

# Free-text body/cut keywords → trigger get_body_state.
# Plural-tolerant via optional trailing s: calorie(s), macro(s), carb(s), etc.
_BODY_RE = re.compile(
    r"\b(weight|cut(ting)?|deficit|calories?|kcal|macros?|protein|carbs?|fat|"
    r"body\s*comp|bodyfat|bf|tdee|projection|target|lose|gain|gaining|losing)\b",
    re.IGNORECASE,
)


def classify_required_tools(message: str, agent_name: str) -> list[ForcedCall]:
    """Return tools to pre-execute before the model's first turn.

    Returns at most one ForcedCall per distinct tool name (dedup by
    tool_name) — we don't pre-execute the same tool twice in one turn.
    """
    if not message:
        return []
    seen_tools: set[str] = set()
    out: list[ForcedCall] = []

    def add(call: ForcedCall) -> None:
        if call.tool_name in seen_tools:
            return
        seen_tools.add(call.tool_name)
        out.append(call)

    if _DAY_RE.search(message):
        add(ForcedCall("get_today_status"))

    for ex_re, canonical in _EXERCISE_MAP:
        if ex_re.search(message):
            add(ForcedCall("get_recent_sets",
                           kwargs={"exercise_name": canonical, "limit": 8}))
            add(ForcedCall("get_e1rm",
                           kwargs={"exercise_name": canonical}))
            break  # one exercise per turn is plenty; first match wins

    if _BODY_RE.search(message):
        add(ForcedCall("get_body_state"))

    return out
