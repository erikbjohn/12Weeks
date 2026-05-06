"""Multi-agent coach orchestrator. Doctor (Opus 4.7) parses athlete
messages, optionally consults Nutritionist/Strength/Running specialists
(Sonnet 4.6) as tools, synthesizes a single-voice response.

Used by the 4 chat-style trigger modes (conversation, weekly_planning,
chat_opened, weekly_review). Other 7 trigger modes stay on the
single-prompt path in coach_with_tools.py.
"""
from __future__ import annotations
import os
import re
from coach_specialists.loader import load_agent_md

MAX_TOOL_TURNS = 6
DEFAULT_MAX_TOKENS = 2000

# Numbers we never bother flagging — too common to be meaningful claims.
_TRIVIAL_NUMBERS = {"0", "1", "2", "3"}

# Match decimal numbers (with optional comma thousands-separators).
_NUMBER_RE = re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b")

# Match inline arithmetic derivations: "X op Y = Z" where op is - + * / × ÷
_DERIVATION_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"[-+*/×÷]\s*"
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"=\s*"
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
)


def _normalize_number(s: str) -> str:
    """1,700 → 1700; 207.20 → 207.2; 207. → 207."""
    s = s.replace(",", "").strip()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _extract_numbers(text: str) -> set[str]:
    return {_normalize_number(m) for m in _NUMBER_RE.findall(text)}


def _verify_response_numbers(response: str, source: str) -> list[str]:
    """Return list of numbers in response that don't appear in source.

    A number is verified if:
      (a) it appears in source text directly (with comma/decimal normalization), OR
      (b) it's the result of an inline derivation (X op Y = Z) where X and Y
          are both in source — encourages the 'show your math' pattern.

    Trivial numbers (0/1/2/3) are skipped — too common to be meaningful claims.
    """
    src_nums = _extract_numbers(source)
    response_nums = _extract_numbers(response)

    # Inline derivations the response itself shows. If the inputs are in
    # source and the response shows the math, accept the result.
    derived_results: set[str] = set()
    for m in _DERIVATION_RE.finditer(response):
        a, b, c = (_normalize_number(g) for g in m.groups())
        if a in src_nums and b in src_nums:
            derived_results.add(c)

    unverified = []
    for n in response_nums:
        if n in _TRIVIAL_NUMBERS:
            continue
        if n in src_nums:
            continue
        if n in derived_results:
            continue
        unverified.append(n)
    return unverified


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=60.0,
        max_retries=5,
    )


def _execute_tools_parallel(tool_blocks: list, user_id: int) -> list[dict]:
    """Run tool_use blocks in parallel via asyncio.gather. For tool sets
    that include multiple consult_* calls, this gives ~3x wall-clock
    speedup (3 specialists run concurrently). Non-consult tools also
    parallelize, which is harmless — they just don't benefit much.

    Worker threads need the Flask app context AND a logged-in user
    (specialists build their athlete_data slices via current_user). We
    capture both from the calling thread and re-enter them inside each
    executor task — without this, every consult tool fails silently
    with `Working outside of application context` and the Doctor
    synthesizes from its own slice alone.
    """
    import asyncio
    from coach_tools import execute_tool

    # Snapshot the calling thread's Flask app + user so worker threads
    # can re-enter them. Specialists build their athlete_data slices via
    # current_user, so without this every consult fails silently with
    # `Working outside of application context`.
    #
    # Defensive: in unit tests this helper runs without a Flask context.
    # When that happens we skip the wrapping and call execute_tool
    # directly — tests mock out the downstream calls anyway.
    flask_app = None
    user_obj = None
    try:
        from flask import current_app
        flask_app = current_app._get_current_object()
        from models import User
        user_obj = User.query.get(user_id)
    except Exception:
        pass

    def _execute_with_context(name, tool_input, uid):
        if flask_app is None:
            return execute_tool(name, tool_input, uid)
        from flask_login import login_user
        with flask_app.app_context():
            with flask_app.test_request_context():
                if user_obj is not None:
                    login_user(user_obj, force=True)
                return execute_tool(name, tool_input, uid)

    async def run_one(b):
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(
            None, _execute_with_context, b.name, dict(b.input or {}), user_id,
        )
        return {
            "type": "tool_result",
            "tool_use_id": b.id,
            "content": out,
        }

    async def run_all():
        return await asyncio.gather(*(run_one(b) for b in tool_blocks))

    try:
        return asyncio.run(run_all())
    except RuntimeError:
        # Already inside an event loop (Flask + threaded server). Fall back
        # to a fresh event loop in a worker thread.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, run_all())
            return future.result()


def _is_error_payload(content: str) -> tuple[bool, str]:
    """Return (is_error, error_message) by detecting the {"error": ...}
    shape that coach_tools.execute_tool emits on exception.

    Detects both the json.dumps result and any reasonable error string —
    we only consume what we recognize, conservatively.
    """
    if not isinstance(content, str):
        return False, ""
    s = content.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return False, ""
    import json as _json
    try:
        parsed = _json.loads(s)
    except Exception:
        return False, ""
    if isinstance(parsed, dict) and "error" in parsed and len(parsed) <= 2:
        return True, str(parsed.get("error", ""))
    return False, ""


def _reroute_tool_failures(results: list[dict], tool_blocks: list) -> list[dict]:
    """Replace {"error": ...} tool_results with system directives that tell
    the Doctor what to do without leaking the failure to the athlete.

    Returns a new list (same length, same tool_use_id mapping) — Anthropic
    requires a tool_result for every tool_use block, so we don't drop any.
    """
    block_by_id = {getattr(b, "id", None): b for b in tool_blocks}
    rewritten = []
    for r in results:
        is_err, err_msg = _is_error_payload(r.get("content", ""))
        if not is_err:
            rewritten.append(r)
            continue
        tu_id = r.get("tool_use_id")
        tool_name = getattr(block_by_id.get(tu_id), "name", "<unknown>")
        directive = (
            f"INTERNAL TOOL FAILURE — DO NOT SURFACE TO THE ATHLETE.\n"
            f"Tool: {tool_name}\n"
            f"Error: {err_msg}\n\n"
            f"Your options (pick the best one for this turn):\n"
            f"  1. Retry the same tool with the same or refined input.\n"
            f"  2. Consult a different specialist if the question allows.\n"
            f"  3. Answer from the athlete_data block alone, without "
            f"mentioning that any tool failed.\n\n"
            f"Do NOT write 'Nutritionist couldn't pull data' / 'tool was "
            f"overloaded' / 'consult failed' / similar plumbing leak in "
            f"your final response. The athlete sees only the answer; "
            f"failures are an internal concern."
        )
        rewritten.append({
            "type": "tool_result",
            "tool_use_id": tu_id,
            "content": directive,
        })
    return rewritten


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
    from coach_tools import TOOLS

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
    tool_results_collected: list[str] = []  # for fact-check source
    fact_check_retries_used = 0
    MAX_FACT_CHECK_RETRIES = 1  # one shot at fixing unverified numbers

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
            tool_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            results = _execute_tools_parallel(tool_blocks, user_id)

            # Detect and reroute tool failures so the Doctor doesn't surface
            # internal plumbing (e.g. "Nutritionist couldn't pull data") to
            # the athlete. The execute_tool wrapper returns JSON like
            # {"error": "..."} on exception — convert that into a system
            # directive the Doctor will read but won't echo verbatim.
            results = _reroute_tool_failures(results, tool_blocks)

            convo.append({"role": "user", "content": results})
            for r in results:
                content = r.get("content")
                if isinstance(content, str):
                    tool_results_collected.append(content)
            continue

        # end_turn — extract text, then fact-check before returning.
        text = "\n".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()

        fact_check_source = system + "\n" + "\n".join(tool_results_collected)
        unverified = _verify_response_numbers(text, fact_check_source)

        if unverified and fact_check_retries_used < MAX_FACT_CHECK_RETRIES and turn < MAX_TOOL_TURNS - 1:
            # Append the failed response and ask the Doctor to fix it.
            convo.append({
                "role": "assistant",
                "content": [b.model_dump() for b in resp.content],
            })
            convo.append({
                "role": "user",
                "content": (
                    "FACT-CHECK FAILED. The following numbers in your response "
                    "do not appear in the athlete_data, any tool result, or as "
                    "an inline derivation:\n"
                    f"  {', '.join(sorted(unverified))}\n\n"
                    "Either:\n"
                    "  (a) Remove these numbers and rewrite without them, or\n"
                    "  (b) Show the derivation inline (e.g., '207.2 - 185 = 22.2', "
                    "'TDEE 3043 - 1700 = 1343/day').\n\n"
                    "Re-issue your full response with this fix. Do not apologize "
                    "for the prior version — just emit the corrected one."
                ),
            })
            fact_check_retries_used += 1
            continue

        return text

    return "(multi-agent: hit max tool-call iterations)"
