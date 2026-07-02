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
    # Soft conversational openers (questions disguised as statements)
    "what's on your mind", "whats on your mind", "anything else",
    "anything on your mind", "tell me more", "let me know",
    "talk to me", "what's up with", "how's it going",
    "let's hear it", "fill me in", "how do you feel",
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

    # 1. Required sections present (and non-empty)
    missing = [k for k in ("schedule", "directive", "motivation") if k not in sections]
    if missing:
        return ValidationResult(ok=False, failure_reason=f"missing section(s): {missing}")
    # Fix C: sections present but with empty content also fail. An LLM that emits
    # <motivation></motivation> would pass the key-presence check above but produce
    # an empty rendered response. Catch that here so the retry/fallback fires.
    empty_sections = [k for k in ("motivation",) if not sections[k].strip()]
    if empty_sections:
        return ValidationResult(ok=False, failure_reason=f"section(s) present but empty: {empty_sections}")

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


# === Cite-validation for the multi-agent claims architecture (Step 3) ===
#
# A response is a JSON object like:
#     {
#       "lead": {"text": "...", "cites": ["claim_id_1", "claim_id_2"]},
#       "reasoning": [{"text": "...", "cites": [...]}],
#       "caveats": [],
#     }
#
# Validation checks:
#   1. Every claim_id cited exists in the claims table
#   2. Every numeric in prose is either:
#      (a) the value of a cited claim (string-match), OR
#      (b) the result of inline arithmetic where the inputs are cited claims

from dataclasses import dataclass as _cite_dataclass


@_cite_dataclass
class CiteViolation:
    """A specific cite-validation failure with enough detail to feed back
    to the model in a retry prompt."""
    kind: str        # "unknown_claim_id" | "value_mismatch" | "uncited_number" | "predicate_mismatch"
    message: str


def _iter_text_blocks(response: dict):
    """Yield (text, cites) pairs from response sections that may contain
    prose with citations: lead, each reasoning entry, each caveat."""
    lead = response.get("lead") or {}
    if isinstance(lead, dict) and lead.get("text"):
        yield lead.get("text", ""), list(lead.get("cites") or [])
    for r in response.get("reasoning") or []:
        if isinstance(r, dict):
            yield r.get("text", ""), list(r.get("cites") or [])
    for c in response.get("caveats") or []:
        if isinstance(c, dict):
            yield c.get("text", ""), list(c.get("cites") or [])
        elif isinstance(c, str):
            yield c, []


def validate_cited_response(response: dict, claims: list) -> list:
    """Return list of CiteViolation (empty list = clean)."""
    from coach_multi_agent import (
        _NUMBER_RE,
        _DERIVATION_RE,
        _derivation_result_ok,
        _normalize_number,
        _TRIVIAL_NUMBERS,
    )

    violations: list = []
    by_id = {c.claim_id: c for c in claims}

    for text, cites in _iter_text_blocks(response):
        # 1. unknown claim_id
        for cid in cites:
            if cid not in by_id:
                violations.append(CiteViolation(
                    kind="unknown_claim_id",
                    message=f"Cited unknown claim_id: {cid!r}. Not in claims table.",
                ))

        # 2. numbers in prose
        cited_values = {_normalize_number(str(by_id[c].value)) for c in cites if c in by_id}
        # Inline-derivation results acceptable when inputs are cited AND the
        # arithmetic is actually correct — a derivation whose result C doesn't
        # equal `A op B` is a fabricated number wearing a math costume
        # ("207.2 - 185 = 15.0" used to pass), so it stays a violation.
        derived_results: set = set()
        for m in _DERIVATION_RE.finditer(text):
            a_raw, op, b_raw, c_raw = m.groups()
            a, b, c = (_normalize_number(g) for g in (a_raw, b_raw, c_raw))
            if a in cited_values and b in cited_values and _derivation_result_ok(a, op, b, c):
                derived_results.add(c)

        for raw in _NUMBER_RE.findall(text):
            n = _normalize_number(raw)
            if n in _TRIVIAL_NUMBERS:
                continue
            if n in cited_values:
                continue
            if n in derived_results:
                continue
            if cites:
                # Cites are present but the number doesn't match any cited
                # claim's value — this is a mismatch, not a simple uncited
                # number. The model picked the wrong claim_id for the
                # number it wrote.
                cited_pairs = ", ".join(f"{c}={by_id[c].value!r}" for c in cites if c in by_id)
                violations.append(CiteViolation(
                    kind="value_mismatch",
                    message=(
                        f"Number {n!r} in prose does not match any cited "
                        f"claim's value (cites: {cited_pairs}). Either "
                        f"replace the cite with one whose value is {n}, "
                        f"or remove the number."
                    ),
                ))
            else:
                violations.append(CiteViolation(
                    kind="uncited_number",
                    message=(
                        f"Number {n!r} in prose is not cited and not derived "
                        f"from cited inputs. Either add a cite or remove the number."
                    ),
                ))

        # 3. value-match: at least one cited claim's value should appear
        # in the prose if the cite is numeric.
        for cid in cites:
            if cid not in by_id:
                continue
            value_str = _normalize_number(str(by_id[cid].value))
            try:
                float(value_str)
            except ValueError:
                continue
            response_nums = {_normalize_number(m) for m in _NUMBER_RE.findall(text)}
            if value_str not in response_nums and value_str not in derived_results:
                violations.append(CiteViolation(
                    kind="value_mismatch",
                    message=(
                        f"Cited claim {cid} has value {value_str!r} but it "
                        f"does not appear in the prose. Either remove the cite "
                        f"or include the value."
                    ),
                ))

        # 4. predicate mis-attribution (right number, WRONG fact): the Claim
        # docstring promises the validator uses `predicate` to catch this, and
        # value-matching alone let "you're at 185 right now" pass while citing
        # body.weight.target (185) — a direct user-visible contradiction.
        # Deterministic lexical check for the current-vs-target weight class:
        # phrasing that asserts CURRENT state must be backed by a cited claim
        # whose predicate says current; phrasing that asserts the TARGET must
        # be backed by a target/goal predicate.
        violations.extend(_check_predicate_attribution(
            text, [by_id[c] for c in cites if c in by_id], _normalize_number))

    return violations


# Phrase patterns for predicate attribution — conservative: only phrasings
# that unambiguously assert WHICH fact the number is.
_PRED_NUM = r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
_CURRENT_PHRASE_RE = re.compile(
    r"(?:you'?re\s+(?:at|sitting\s+at)|currently\s+(?:at\s+)?|current\s+weight\s+(?:is\s+|of\s+)?|"
    r"weigh(?:ed|ing)?\s+(?:in\s+)?(?:at\s+)?|this\s+morning\s+(?:you\s+were\s+)?(?:at\s+)?)\s*"
    + _PRED_NUM, re.IGNORECASE)
_TARGET_PHRASE_RE = re.compile(
    r"(?:target\s+(?:weight\s+)?(?:is\s+|of\s+)?|goal\s+(?:weight\s+)?(?:is\s+|of\s+)?)\s*"
    + _PRED_NUM, re.IGNORECASE)


def _predicate_phrase_patterns():
    """(regex with a <num> group, predicate keyword(s) that must back it)."""
    return [(_CURRENT_PHRASE_RE, ("current",)),
            (_TARGET_PHRASE_RE, ("target", "goal"))]


def _check_predicate_attribution(text: str, cited_claims: list, normalize) -> list:
    """Flag numbers asserted with current/target phrasing whose ONLY cited
    backing is a claim of the opposite predicate. Skips numbers that no cited
    claim matches (checks 2/3 already handle those)."""
    out = []
    for phrase_re, keywords in _predicate_phrase_patterns():
        for m in phrase_re.finditer(text):
            n = normalize(m.group("num"))
            backing = [c for c in cited_claims if normalize(str(c.value)) == n]
            if not backing:
                continue  # not a cited value — other checks own this number
            if any(any(k in (c.predicate or "").lower() for k in keywords)
                   for c in backing):
                continue  # some cited claim's predicate matches the phrasing
            preds = ", ".join(f"{c.claim_id} (pred={c.predicate})" for c in backing)
            out.append(CiteViolation(
                kind="predicate_mismatch",
                message=(
                    f"Prose asserts {m.group(0).strip()!r} but the cited "
                    f"claim(s) matching {n!r} are {preds} — the wrong fact "
                    f"for that phrasing. Cite the claim whose predicate "
                    f"matches what the sentence asserts, or fix the sentence."
                ),
            ))
    return out
