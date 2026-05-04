"""Fast string/regex checks. No LLM calls."""
from __future__ import annotations
import re
from .types import HeuristicResult, PromptCase


# Phrases the coach must NEVER emit. Maintained reactively as we find slips.
# Stored lowercase; matched against normalized response so case + ×/x folding
# stays consistent.
BANNED_PHRASES: list[str] = [
    "what's on your mind",
    "get after it",            # catches both "get after it" and "let's get after it"
    "speak.",
    "great work",
    "done. tomorrow:",
    "you've got this",
    "crushing it",
    "keep grinding",
]


def _norm(s: str) -> str:
    """Lowercase + fold the two common Unicode ×'s to ASCII 'x' so
    '4×3' (U+00D7), '4✕3' (U+2715), and '4x3' all compare equal."""
    return s.lower().replace("×", "x").replace("✕", "x")


def _has(haystack_norm: str, needle: str) -> bool:
    n = _norm(needle)
    if n.startswith("/") and n.endswith("/") and len(n) > 2:
        return re.search(n[1:-1], haystack_norm) is not None
    return n in haystack_norm


def check_heuristics(response: str, case: PromptCase) -> HeuristicResult:
    norm = _norm(response)
    missing = [s for s in case.expected_behavior if not _has(norm, s)]
    bad = [s for s in case.must_not if _has(norm, s)]
    overrides = {_norm(p) for p in case.banned_phrase_overrides}
    active_banned = [p for p in BANNED_PHRASES if _norm(p) not in overrides]
    banned = [p for p in active_banned if _has(norm, p)]
    passed = not missing and not bad and not banned
    return HeuristicResult(
        passed=passed,
        missing_expected=missing,
        matched_must_not=bad,
        matched_banned=banned,
    )
