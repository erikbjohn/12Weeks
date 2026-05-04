"""Fast string/regex checks. No LLM calls."""
from __future__ import annotations
import re
from .types import HeuristicResult, PromptCase


# Phrases the coach must NEVER emit. Maintained reactively as we find slips.
BANNED_PHRASES: list[str] = [
    "what's on your mind",
    "let's get after it",
    "speak.",
    "great work",
    "done. tomorrow:",
    "you've got this",
    "crushing it",
    "keep grinding",
]


def _norm(s: str) -> str:
    """Lowercase + replace × with x so '4×3' and '4x3' compare equal."""
    return s.lower().replace("×", "x").replace("×", "x")


def _has(haystack_norm: str, needle: str) -> bool:
    n = _norm(needle)
    if n.startswith("/") and n.endswith("/") and len(n) > 2:
        return re.search(n[1:-1], haystack_norm) is not None
    return n in haystack_norm


def check_heuristics(response: str, case: PromptCase) -> HeuristicResult:
    norm = _norm(response)
    missing = [s for s in case.expected_behavior if not _has(norm, s)]
    bad = [s for s in case.must_not if _has(norm, s)]
    banned = [p for p in BANNED_PHRASES if p in norm]
    passed = not missing and not bad and not banned
    return HeuristicResult(
        passed=passed,
        missing_expected=missing,
        matched_must_not=bad,
        matched_banned=banned,
    )
