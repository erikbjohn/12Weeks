"""ONE place for the Anthropic client, the model ids and the JSON-fence
parser (S071). Eleven modules each built their own client (divergent
timeouts/retries), eight carried their own model literal — three of them
stale ids (claude-opus-4-20250514, claude-sonnet-4-20250514, claude-opus-4-7)
that the current API rejects — and six copied the fence stripper.

    from llm_client import client, OPUS, SONNET, HAIKU, parse_json_reply
"""
from __future__ import annotations

import json
import os
import re

# Model ids. CLAUDE_MODEL overrides the conversational coach only.
OPUS = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"


def record_usage(response, agent: str, model: str | None = None):
    """S104: persist response.usage (best effort, never raises). Safe outside
    an app context (returns silently)."""
    try:
        u = getattr(response, "usage", None)
        if not u:
            return
        from models import db, LlmUsage
        db.session.add(LlmUsage(agent=(agent or "?")[:40], model=(model or getattr(response, "model", None) or "?")[:60],
                                input_tokens=getattr(u, "input_tokens", None),
                                output_tokens=getattr(u, "output_tokens", None),
                                cache_read_tokens=getattr(u, "cache_read_input_tokens", None),
                                cache_write_tokens=getattr(u, "cache_creation_input_tokens", None)))
        db.session.commit()
    except Exception:
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass


def client(*, timeout: float = 60.0, max_retries: int = 1):
    """A configured Anthropic client. Timeout is REQUIRED thinking — the SDK
    default (600 s × 3 retries) wedged background jobs (S017)."""
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"),
                               timeout=timeout, max_retries=max_retries)


def text_of(response) -> str:
    """All text blocks of a messages.create response, joined."""
    return "".join(b.text for b in getattr(response, "content", []) or []
                   if getattr(b, "type", None) == "text").strip()


_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.S)


def strip_fence(text: str) -> str:
    """Remove a ```json … ``` fence if the reply is wrapped in one."""
    t = (text or "").strip()
    m = _FENCE.match(t)
    if m:
        return m.group(1).strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    return t.strip()


def parse_json_reply(text: str, *, find_object: bool = True):
    """Parse a model reply as JSON: fence stripped; optionally the first
    {...} / [...] span when the model added prose around it. Raises
    ValueError with the offending head when nothing parses."""
    t = strip_fence(text)
    try:
        return json.loads(t)
    except Exception:
        pass
    if find_object:
        for open_c, close_c in (("{", "}"), ("[", "]")):
            if open_c in t and close_c in t:
                try:
                    return json.loads(t[t.index(open_c): t.rindex(close_c) + 1])
                except Exception:
                    continue
    raise ValueError(f"no JSON in reply: {t[:120]!r}")
