"""Nutritionist specialist runtime. Loads .claude/agents/nutritionist.md
on import, exposes consult(brief, user_id) -> str."""
from __future__ import annotations
import os
from .loader import load_agent_md

_PERSONA = load_agent_md("nutritionist")


def _anthropic_client():
    import anthropic
    # max_retries=5 (vs SDK default 2) so a single 529 'overloaded' from
    # Anthropic during a Doctor-initiated consult doesn't surface as
    # "Nutritionist couldn't pull data" to the athlete.
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=5,
    )


def _build_athlete_slice(user_id: int) -> str:
    """Build the Nutritionist's athlete_data slice. Pulls only the sections
    relevant to nutrition: cut_status, body_weight, meals_today, weekly_meals,
    food_safety, food_selections, fasting state, today_status, goal."""
    from coach_assembler import build_filtered_context, _format_athlete_data
    ctx = build_filtered_context("nutritionist")
    return _format_athlete_data(ctx, ctx.get("_requires", []))


def consult(brief: str, user_id: int) -> str:
    """Call the Nutritionist with the Doctor's brief + athlete data slice.
    Returns the recommendation text (2-4 sentences per the persona)."""
    slice_block = _build_athlete_slice(user_id)
    system = (
        _PERSONA["system_prompt"]
        + "\n\n<athlete_data>\n"
        + slice_block
        + "\n</athlete_data>"
    )
    user_msg = f"DOCTOR BRIEF:\n{brief}"

    client = _anthropic_client()
    resp = client.messages.create(
        model=_PERSONA["model"],
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
