"""Strength Coach specialist runtime. Loads .claude/agents/strength-coach.md
on import, exposes consult(brief, user_id) -> str."""
from __future__ import annotations
from llm_client import create as _llm_create
import os
from .loader import load_agent_md

_PERSONA = load_agent_md("strength-coach")


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=1, timeout=75.0,   # S163
    )


def _build_athlete_slice(user_id: int) -> str:
    from coach_assembler import build_filtered_context, _format_athlete_data
    ctx = build_filtered_context("strength_coach")
    return _format_athlete_data(ctx, ctx.get("_requires", []))


def consult(brief: str, user_id: int) -> str:
    slice_block = _build_athlete_slice(user_id)
    system = (
        _PERSONA["system_prompt"]
        + "\n\n<athlete_data>\n"
        + slice_block
        + "\n</athlete_data>"
    )
    user_msg = f"DOCTOR BRIEF:\n{brief}"

    client = _anthropic_client()
    resp = _llm_create(client, 
        model=_PERSONA["model"],
        **({"temperature": _PERSONA["temperature"]} if _PERSONA.get("temperature") is not None else {}),
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    __import__('llm_client').record_usage(resp, 'specialist_strength')   # S104
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
