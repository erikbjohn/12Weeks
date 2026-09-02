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
# Multi-agent (Doctor + specialists) is the analytical/synthesis path —
# Doctor persona requires JSON-with-cites output for cite validation. That
# format is wrong for conversational flows (weekly_planning, weekly_review,
# chat_opened) where the protocol specifies prose/markdown. Keep those on
# the simple tool-loop path so their protocol's format wins.
MULTIAGENT_TRIGGERS = {"conversation"}


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
- "How did I sleep?" / "Read my Garmin" / any HRV or recovery question → get_garmin_wellness() — sleep, HRV, body battery are auto-synced; NEVER ask the athlete for them and never say you can't access Garmin.
- Athlete says a number you quoted is wrong or invented → re-check with the matching tool BEFORE conceding.
- "Scale said 211.4 this morning" → log_bodyweight(weight_lbs=211.4) — a weight told to you in chat is NOT saved anywhere unless you call this; then acknowledge the logged number.
- "Waist 38, neck 15" / any tape number → log_measurements(waist=38, neck=15) — same rule: chat does NOT save it; saying "logged" without calling this is a lie (it happened 2026-08-29 and the athlete's tape vanished).

If you call a tool, write a brief response after the data comes back — don't just dump the JSON. Cite the specific number from the tool result.

If you don't know what week the athlete is in, call get_today_status first to find out.

NEVER fabricate a weight, set count, or workout for a day you haven't looked up. If the answer needs data not in your prompt, the tool exists for a reason."""


def _log_usage(response, *, agent: str, model: str, turn: int = 0):
    """S104: LLM usage telemetry. response.usage was never read anywhere, so
    cost per action and cache hit rate were unmeasurable. One INFO line per
    call — grep '[LLM]' in Render logs."""
    try:
        u = getattr(response, "usage", None)
        if not u:
            return
        log.info("[LLM] agent=%s model=%s turn=%s in=%s out=%s cache_read=%s cache_write=%s",
                 agent, model, turn,
                 getattr(u, "input_tokens", None), getattr(u, "output_tokens", None),
                 getattr(u, "cache_read_input_tokens", None),
                 getattr(u, "cache_creation_input_tokens", None))
    except Exception:
        pass


def _execute_tools_parallel(tool_use_blocks, user_id):
    """S163: Opus may emit several tool_use blocks in one turn (three of the
    eleven tools are Sonnet calls); running them serially added their
    latencies. Each worker gets its own app + request context and login.
    Order of results matches the blocks (the API pairs by tool_use_id)."""
    from coach_tools import execute_tool
    if len(tool_use_blocks) <= 1:
        return [execute_tool(b.name, dict(b.input or {}), user_id) for b in tool_use_blocks]
    from concurrent.futures import ThreadPoolExecutor
    try:
        from flask import current_app
        flask_app = current_app._get_current_object()
    except Exception:
        flask_app = None

    def _run(b):
        if flask_app is None:
            return execute_tool(b.name, dict(b.input or {}), user_id)
        with flask_app.app_context(), flask_app.test_request_context():
            try:
                from flask_login import login_user
                from models import User, db
                u = db.session.get(User, user_id)
                if u:
                    login_user(u, force=True)
            except Exception:
                pass
            return execute_tool(b.name, dict(b.input or {}), user_id)

    with ThreadPoolExecutor(max_workers=min(4, len(tool_use_blocks))) as ex:
        return list(ex.map(_run, tool_use_blocks))


def _forced_final_text(client, *, model, max_tokens, system, messages, tools, temperature=None) -> str:
    """One text-only turn (tool_choice=none) after the tool loop exhausted
    MAX_TOOL_TURNS. The last response was a tool_use — streaming/returning it
    would ship the model's tool-call preamble ('Let me pull Friday next.') as
    the coach's final answer. Returns '' if the forced turn fails, so callers
    can substitute an athlete-safe fallback."""
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,  # history contains tool blocks — tools must stay defined
            tool_choice={"type": "none"},
            **({"temperature": temperature} if temperature is not None else {}),
        )
        _log_usage(resp, agent="forced_final", model=model)
        return "\n".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
    except Exception:
        log.warning("forced final text turn failed after max tool turns", exc_info=True)
        return ""


def _run_loop(
    *,
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float | None = None,
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
            **({"temperature": temperature} if temperature is not None else {}),
        )
        _log_usage(response, agent="tool_loop", model=model, turn=turn)

        stop_reason = response.stop_reason
        blocks = response.content

        if stop_reason == "tool_use":
            # Append the assistant's tool-call message verbatim
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in blocks],
            })
            # Execute every tool_use block, build tool_result message
            tool_use_blocks = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
            tool_results = []
            _results = _execute_tools_parallel(tool_use_blocks, user_id)  # S163
            for b, result_str in zip(tool_use_blocks, _results):
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": result_str,
                })
            # Reroute tool failures to a system directive so the model doesn't
            # narrate raw plumbing errors ("RuntimeError: Working outside of
            # application context") to the athlete. Same defense the streaming
            # twin and the multi-agent path already apply.
            try:
                from coach_multi_agent import _reroute_tool_failures
                tool_results = _reroute_tool_failures(tool_results, tool_use_blocks)
            except Exception:
                pass  # If reroute helper unavailable, fall back to raw results
            convo.append({"role": "user", "content": tool_results})
            continue

        # End of conversation — extract text
        text_parts = []
        for b in blocks:
            if getattr(b, "type", None) == "text":
                text_parts.append(b.text)
        return "\n".join(text_parts).strip()

    # Hit max turns without end_turn — force ONE text-only answer from the
    # data gathered so far instead of leaking a plumbing sentinel to chat.
    text = _forced_final_text(
        client, model=model, max_tokens=max_tokens,
        system=full_system, messages=convo, tools=TOOLS,
        temperature=temperature,
    )
    return text or "I didn't get a complete answer put together on that one. Ask me again."


def coach_chat(
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    agent_name: str = "conversation",
    temperature: float | None = None,
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
        model=model or os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        max_tokens=max_tokens,
        temperature=temperature,
    )


def coach_chat_stream(
    user_id: int,
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float | None = None,
):
    """Streaming entry. Runs the tool loop server-side (no streaming during
    tool calls), then streams the FINAL assistant text token by token.

    The user perceives: ~2-5s pause (tool loop), then text streams normally.
    """
    from coach_tools import TOOLS, execute_tool

    client = _client()
    convo = list(messages)
    full_system = system_prompt + _tool_addendum()
    chosen_model = model or os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

    # Tool loop — non-streaming until we know there are no more tool calls.
    for turn in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=chosen_model,
            max_tokens=max_tokens,
            system=full_system,
            messages=convo,
            tools=TOOLS,
            **({"temperature": temperature} if temperature is not None else {}),
        )
        _log_usage(response, agent="stream_tool_loop", model=chosen_model, turn=turn)
        stop_reason = response.stop_reason
        blocks = response.content

        if stop_reason == "tool_use":
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in blocks],
            })
            tool_use_blocks = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
            tool_results = []
            _results = _execute_tools_parallel(tool_use_blocks, user_id)  # S163
            for b, result_str in zip(tool_use_blocks, _results):
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
    else:
        # Loop exhausted MAX_TOOL_TURNS still in tool_use: `blocks` is the last
        # tool-call response, whose only text is preamble ("Let me pull Friday
        # next.") — streaming that would ship a fragment as the coach's final
        # answer AND persist it to chat history. Force one text-only turn.
        forced = _forced_final_text(
            client, model=chosen_model, max_tokens=max_tokens,
            system=full_system, messages=convo, tools=TOOLS,
            temperature=temperature,
        )
        yield forced or ("I didn't get a complete answer put together on "
                         "that one. Ask me again.")
        return

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
