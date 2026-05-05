"""Multi-agent coach orchestrator. Doctor (Opus 4.7) parses athlete
messages, optionally consults Nutritionist/Strength/Running specialists
(Sonnet 4.6) as tools, synthesizes a single-voice response.

Used by the 4 chat-style trigger modes (conversation, weekly_planning,
chat_opened, weekly_review). Other 7 trigger modes stay on the
single-prompt path in coach_with_tools.py.
"""
from __future__ import annotations
import os
from coach_specialists.loader import load_agent_md

MAX_TOOL_TURNS = 6
DEFAULT_MAX_TOKENS = 2000


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=60.0,
    )


def coach_chat_multiagent(
    user_id: int,
    athlete_data: str,
    messages: list[dict],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Run a multi-agent conversation turn.

    user_id: athlete id, passed to consult tools so specialists can access data.
    athlete_data: the formatted <athlete_data> block (Doctor sees full).
    messages: chat history list of {role, content} dicts.

    Returns the Doctor's final synthesized text.
    """
    from coach_tools import TOOLS, execute_tool

    persona = load_agent_md("doctor")
    system = (
        persona["system_prompt"]
        + "\n\n<athlete_data>\n"
        + athlete_data
        + "\n</athlete_data>"
    )

    # Filter TOOLS to just the ones the Doctor's persona declares it can use.
    doctor_tool_names = set(persona["tools"])
    doctor_tools = [t for t in TOOLS if t["name"] in doctor_tool_names]

    client = _anthropic_client()
    convo = list(messages)

    for turn in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=persona["model"],
            max_tokens=max_tokens,
            system=system,
            messages=convo,
            tools=doctor_tools,
        )
        if resp.stop_reason == "tool_use":
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in resp.content],
            })
            results = []
            for b in resp.content:
                if getattr(b, "type", None) == "tool_use":
                    out = execute_tool(b.name, dict(b.input or {}), user_id)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": out,
                    })
            convo.append({"role": "user", "content": results})
            continue

        # end_turn — extract text
        return "\n".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()

    return "(multi-agent: hit max tool-call iterations)"
