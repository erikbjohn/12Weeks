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


# Day-name patterns (Mon/Monday/etc.) — case-insensitive.
_DAY_RE = re.compile(
    r"\b(today|tomorrow|yesterday|"
    r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|"
    r"fri(day)?|sat(urday)?|sun(day)?)\b",
    re.IGNORECASE,
)


def classify_required_tools(message: str, agent_name: str) -> list[ForcedCall]:
    """Return tools to pre-execute before the model's first turn.

    Conservative: only triggers on patterns we're confident about. Returns
    an empty list when no patterns match — the model still has slice +
    tool-use available, just no forced pre-execution.
    """
    if not message:
        return []
    out: list[ForcedCall] = []
    if _DAY_RE.search(message):
        out.append(ForcedCall("get_today_status"))
    return out
