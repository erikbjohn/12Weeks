"""Sex and age from the psych-intake conversation — ONE implementation (S099).

app.py carried seven copies with two different rules (a word-list rule with
explicit age context, and a bare `content in ('male','female','m','f')` +
`int(content)` rule that let "I can run 15 miles" become age 15). Every
caller now uses this.
"""
from __future__ import annotations

import re

_AGE_UNIT_LOOKAHEAD = (r'(?!\s*(?:min(?:ute)?s?|miles?|mi\b|k\b|km\b|lbs?|'
                       r'pounds?|kgs?|%|percent|weeks?|days?|hours?|hrs?|'
                       r'reps?|sets?|feet|foot|ft\b|inch(?:es)?|in\b|'
                       r'cal(?:orie)?s?)\b)')
_AGE_CONTEXT_RES = [
    re.compile(r"\b(\d{1,2})\s*(?:years?[\s-]*old|y/?o\b|yrs?[\s-]*old|year[\s-]old)", re.IGNORECASE),
    re.compile(r"\b(?:i'?m|i\s+am|my\s+age\s+is|age\s*(?:is|:)|turning|turned)\s+(\d{1,2})\b"
               + _AGE_UNIT_LOOKAHEAD, re.IGNORECASE),
]
_MALE = {"male", "m", "man", "guy", "dude"}
_FEMALE = {"female", "f", "woman", "girl", "lady"}


def age_from_message(content) -> int | None:
    """An age (13-80) ONLY when the message states it in age context (or is a
    bare number answer); otherwise None. A stray number in free text is never
    the age."""
    if content is None:
        return None
    text = str(content).strip()
    if re.fullmatch(r"\d{1,2}", text):
        num = int(text)
        return num if 13 <= num <= 80 else None
    for rx in _AGE_CONTEXT_RES:
        m = rx.search(text)
        if m:
            num = int(m.group(1))
            if 13 <= num <= 80:
                return num
    return None


def sex_and_age_from_intake(conversation, default_sex: str = "male", default_age: int = 30) -> tuple[str, int]:
    """Walk the user turns of a PsychIntake.conversation list; the LAST
    explicit statement wins."""
    sex, age = default_sex, default_age
    for msg in (conversation if isinstance(conversation, list) else []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        raw = msg.get("content", "") or ""
        words = set(str(raw).lower().split())
        if words & _MALE:
            sex = "male"
        elif words & _FEMALE:
            sex = "female"
        a = age_from_message(raw)
        if a is not None:
            age = a
    return sex, age
