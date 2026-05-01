"""Coach response validator.

Parses the LLM's sectioned response, byte-compares pre-filled sections,
scans banned phrases and questions, returns a ValidationResult.

The retry logic + deterministic fallback are also defined here so the
orchestrator (coach_assembler.coach_respond) can call them cleanly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Hand-curated. Update via PR — never auto-add.
BANNED_PHRASES: list[str] = [
    # Capitulation
    "your call", "if you feel up to it", "if you want", "feel free to",
    "no pressure", "up to you", "whatever works", "however you want",
    # Cheerleading
    "great job", "amazing work", "you're doing great", "proud of you",
    "love it", "crushing it", "killing it", "way to go", "fantastic", "incredible",
    # Collaborative questions
    "would you like", "do you want", "should we", "ready to", "shall we",
    "want me to", "how about",
    # Future-tense softening
    "we could", "we might", "you might consider", "perhaps", "maybe try",
    # Negotiation
    "if that works", "let's see how", "see how you feel", "play it by ear",
    "if you're up for it",
]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    sections: dict = field(default_factory=dict)
    failure_reason: Optional[str] = None


_SECTION_RE = re.compile(
    r"<(schedule|directive|motivation|refusal)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)


def parse_envelope(raw: str) -> dict[str, str]:
    """Extract section name -> content from the LLM's response.

    Returns {} on garbage. Newlines and surrounding whitespace inside each
    section are preserved, but stripped of leading/trailing whitespace.
    """
    out: dict[str, str] = {}
    for m in _SECTION_RE.finditer(raw or ""):
        name = m.group(1).lower()
        out[name] = m.group(2).strip()
    return out


def scan_banned_phrases(text: str) -> Optional[str]:
    """Return the first matching banned phrase (case-insensitive) or None."""
    if not text:
        return None
    lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            return phrase
    return None


def scan_questions(text: str) -> bool:
    """True if `text` contains a question mark. Cheap and aggressive."""
    return "?" in (text or "")


def validate_response(
    *,
    raw: str,
    prefilled_schedule: str,
    prefilled_directive: str,
    refusal_required: bool,
) -> ValidationResult:
    """Validate a single LLM response against the rules contract.

    Returns ValidationResult(ok=True, sections=...) on success,
    or ValidationResult(ok=False, failure_reason=...) on first failure.
    """
    sections = parse_envelope(raw)

    # 1. Required sections present
    missing = [k for k in ("schedule", "directive", "motivation") if k not in sections]
    if missing:
        return ValidationResult(ok=False, failure_reason=f"missing section(s): {missing}")

    # 2. Pre-filled byte equality (strip the outer tags before comparing inner content)
    schedule_inner = _strip_outer_tag(prefilled_schedule, "schedule")
    directive_inner = _strip_outer_tag(prefilled_directive, "directive")
    if sections["schedule"].strip() != schedule_inner.strip():
        return ValidationResult(ok=False, failure_reason="schedule altered from pre-fill")
    if sections["directive"].strip() != directive_inner.strip():
        return ValidationResult(ok=False, failure_reason="directive altered from pre-fill")

    # 3. Banned-phrase scan
    bp = scan_banned_phrases(sections.get("motivation", ""))
    if bp:
        return ValidationResult(ok=False, failure_reason=f"banned phrase in motivation: '{bp}'")
    bp = scan_banned_phrases(sections.get("refusal", ""))
    if bp:
        return ValidationResult(ok=False, failure_reason=f"banned phrase in refusal: '{bp}'")

    # 4. Question-mark scan
    if scan_questions(sections.get("motivation", "")):
        return ValidationResult(ok=False, failure_reason="motivation contains a question mark")
    if scan_questions(sections.get("refusal", "")):
        return ValidationResult(ok=False, failure_reason="refusal contains a question mark")

    # 5. Refusal required iff section present
    if refusal_required and "refusal" not in sections:
        return ValidationResult(ok=False, failure_reason="refusal required but not provided")

    return ValidationResult(ok=True, sections=sections)


def deterministic_fallback(
    *,
    prefilled_schedule: str,
    prefilled_directive: str,
    refusal_required: bool,
) -> str:
    """Austere fallback when the LLM fails validation twice. Pure rules
    output, no motivation, no flourish. Better than capitulation."""
    schedule_inner = _strip_outer_tag(prefilled_schedule, "schedule")
    directive_inner = _strip_outer_tag(prefilled_directive, "directive")
    parts = [schedule_inner.strip(), directive_inner.strip(), "Logged."]
    if refusal_required:
        parts.append("Plan stands.")
    return "\n\n".join(parts)


def _strip_outer_tag(s: str, tag: str) -> str:
    """Remove leading <tag> and trailing </tag>, preserving inner content."""
    s = s.strip()
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    if s.startswith(open_tag):
        s = s[len(open_tag):]
    if s.endswith(close_tag):
        s = s[:-len(close_tag)]
    return s
