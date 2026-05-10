"""Tool-using coach orchestration.

Wraps the Anthropic API call in a tool-use loop: the model can call any of
the tools defined in coach_tools.py to look up workout/history/body data,
then writes its final reply. This eliminates the hallucination class where
the coach confidently invents Monday's workout because it wasn't in the
prompt context.

Two entry points:
  - coach_chat(user_id, system_prompt, messages) -> str
      Non-streaming. Runs tool loop, returns final assistant text.
  - coach_chat_stream(user_id, system_prompt, messages) -> generator
      Streams the FINAL assistant text after tool calls complete. (Tool
      calls themselves don't stream — they happen between bursts.)
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

MAX_TOOL_TURNS = 6
DEFAULT_MAX_TOKENS = 2000

# Agents whose persona is "Doctor + 3 specialists" rather than a single
# monolithic prompt. When MULTIAGENT_ENABLED=1, coach_chat routes these
# through coach_multi_agent.coach_chat_multiagent. Other agent_names stay
# on the single-prompt _run_loop path regardless of the flag.
MULTIAGENT_TRIGGERS = {"conversation", "weekly_planning", "chat_opened", "weekly_review"}


def _client(timeout: float = 60.0):
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=timeout,
    )


def _tool_addendum() -> str:
    """Appended to whatever system prompt the caller sends in. Tells the
    model HOW to use tools and WHEN."""
    return """\

# TOOLS — USE THEM, DON'T GUESS

You have tools to look up the athlete's actual data. Call them whenever the answer depends on a fact you don't already see in your context.

Examples — call a tool:
- "What's on Monday?" → get_workout(week=current, day_idx=0)
- "What did I lift last bench?" → get_recent_sets("Barbell Bench Press")
- "What's my squat 1RM?" → get_e1rm("Barbell Back Squat")
- "How's the cut going?" → get_body_state()
- "What's left today?" → get_today_status()

If you call a tool, write a brief response after the data comes back — don't just dump the JSON. Cite the specific number from the tool result.

If you don't know what week the athlete is in, call get_today_status first to find out.

NEVER fabricate a weight, set count, or workout for a day you haven't looked up. If the answer needs data not in your prompt, the tool exists for a reason."""


def _run_loop(
    *,
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str,
    max_tokens: int,
) -> str:
    """Run the tool-use loop. Returns the final assistant text."""
    from coach_tools import TOOLS, execute_tool

    client = _client()
    convo = list(messages)
    full_system = system_prompt + _tool_addendum()

    for turn in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=full_system,
            messages=convo,
            tools=TOOLS,
        )

        stop_reason = response.stop_reason
        blocks = response.content

        if stop_reason == "tool_use":
            # Append the assistant's tool-call message verbatim
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in blocks],
            })
            # Execute every tool_use block, build tool_result message
            tool_results = []
            for b in blocks:
                if getattr(b, "type", None) == "tool_use":
                    result_str = execute_tool(b.name, dict(b.input or {}), user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": result_str,
                    })
            convo.append({"role": "user", "content": tool_results})
            continue

        # End of conversation — extract text
        text_parts = []
        for b in blocks:
            if getattr(b, "type", None) == "text":
                text_parts.append(b.text)
        return "\n".join(text_parts).strip()

    # Hit max turns without end_turn — pull whatever text we have
    return "(coach hit max tool-call iterations; check server logs)"


def coach_chat(
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    agent_name: str = "conversation",
) -> str:
    """Non-streaming entry. Returns final assistant text.

    When MULTIAGENT_ENABLED=1 AND agent_name is a chat-style trigger,
    routes through coach_multi_agent. Otherwise uses the existing
    single-prompt tool-loop.
    """
    if (
        os.environ.get("MULTIAGENT_ENABLED") == "1"
        and agent_name in MULTIAGENT_TRIGGERS
    ):
        from coach_multi_agent import coach_chat_multiagent
        return coach_chat_multiagent(
            user_id=user_id,
            athlete_data=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        )

    return _run_loop(
        user_id=user_id,
        system_prompt=system_prompt,
        messages=messages,
        model=model or os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        max_tokens=max_tokens,
    )


def coach_chat_stream(
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
):
    """Streaming entry. Runs the tool loop server-side (no streaming during
    tool calls), then streams the FINAL assistant text token by token.

    The user perceives: ~2-5s pause (tool loop), then text streams normally.
    """
    from coach_tools import TOOLS, execute_tool

    client = _client()
    convo = list(messages)
    full_system = system_prompt + _tool_addendum()
    chosen_model = model or os.environ.get("CLAUDE_MODEL", "claude-opus-4-7")

    # Tool loop — non-streaming until we know there are no more tool calls.
    for turn in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=chosen_model,
            max_tokens=max_tokens,
            system=full_system,
            messages=convo,
            tools=TOOLS,
        )
        stop_reason = response.stop_reason
        blocks = response.content

        if stop_reason == "tool_use":
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in blocks],
            })
            tool_use_blocks = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
            tool_results = []
            for b in tool_use_blocks:
                result_str = execute_tool(b.name, dict(b.input or {}), user_id)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": result_str,
                })
            # Reroute any tool failures to a system directive so the model
            # doesn't surface raw plumbing errors ("RuntimeError: Working
            # outside of application context") to the athlete. Same defense
            # as the multi-agent path uses via _reroute_tool_failures.
            try:
                from coach_multi_agent import _reroute_tool_failures
                tool_results = _reroute_tool_failures(tool_results, tool_use_blocks)
            except Exception:
                pass  # If reroute helper unavailable, fall back to raw results
            convo.append({"role": "user", "content": tool_results})
            continue
        break  # end_turn

    # Now stream the FINAL response. The tool loop above ran to end_turn;
    # we need to do one more streaming call without tools to get token-level
    # streaming for the final text. Strip the last assistant message we just
    # got (already complete) and ask the model to repeat it as the final
    # streaming output. Cleaner: just stream the same call WITHOUT tools.
    #
    # Practical compromise: emit the already-generated text in chunks. The
    # tool loop just produced a final 'end_turn' response containing the
    # text. Emit it word-by-word for SSE.
    final_text = ""
    for b in blocks:
        if getattr(b, "type", None) == "text":
            final_text += b.text

    if not final_text.strip():
        yield "(coach produced no text after tool calls)"
        return

    # Word-boundary chunking
    words = final_text.split(" ")
    buf = ""
    for word in words:
        if len(buf) + len(word) + 1 > 50:
            yield buf
            buf = word
        else:
            buf = (buf + " " + word).strip() if buf else word
    if buf:
        yield buf
