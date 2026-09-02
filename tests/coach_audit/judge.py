"""Opus 4.7 LLM-as-judge."""
from __future__ import annotations
import json
import os
import re
import time
from .types import PromptCase, JudgeResult


JUDGE_MODEL = "claude-opus-4-8"
MAX_TOKENS = 1500           # Headroom for verbose violation lists.

# Keys present in every JudgeResult.scores dict — even when the model errors
# or the response can't be parsed. Keeps Task 9's report aggregation simple.
SCORE_DIMENSIONS = ("accuracy", "tone", "no_hallucination", "follows_must_not")
ZERO_SCORES = {dim: 0 for dim in SCORE_DIMENSIONS}

# Transient-error retry budget. Anthropic 5xx / connection blips shouldn't
# kill a multi-prompt audit run; a coach failure-mode would.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 1.5

JUDGE_SYSTEM = """You are an evaluator for a strength coach AI.

You will be shown:
1. The athlete's archetype (what their program looks like — this is your ground truth).
2. The athlete's question to the coach.
3. The coach's response.
4. Expected behaviors the response should exhibit.
5. Must-not phrases or claims that should be absent.
6. Focus dimensions to weight more heavily in your verdict.

Score the response on 4 dimensions, each 0-10:
- accuracy: Did the coach cite correct facts about the athlete's program/data?
- tone: Direct, factual, no cheerleading. Lombardi/Saban energy. No "great work", "let's get after it", "what's on your mind", "speak.", "done. tomorrow:".
- no_hallucination: Did the coach invent any workout, weight, or set count not implied by the archetype?
- follows_must_not: Did the response avoid every item in the must_not list?

`pass` is true iff every focus_dimension scores ≥ 7 AND no must_not item was matched.

Be lenient on phrasing variation; strict on factual claims and tone violations.

Respond with a single JSON object only — no preamble, no code fence.
{
  "pass": <bool>,
  "scores": {"accuracy": <int>, "tone": <int>, "no_hallucination": <int>, "follows_must_not": <int>},
  "violations": [<short strings describing problems>],
  "evidence": "<quoted snippets from response that justify your scores>"
}
"""


def _client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is required for the judge stage."
        )
    return anthropic.Anthropic(api_key=key)


def _extract_json(text: str) -> dict:
    """Extract first JSON object from a response, tolerating accidental prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    raw = m.group(0) if m else text
    return json.loads(raw)


def _call_judge_with_retry(client, user_block: str):
    """Call Anthropic with bounded retries for transient errors. Final attempt
    re-raises so the caller can surface the failure as a JudgeResult."""
    import anthropic

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=MAX_TOKENS,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": user_block}],
            )
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            # Don't retry 4xx — those are programmer errors (bad key, bad model).
            status = getattr(e, "status_code", None)
            if status is not None and 400 <= status < 500:
                raise
            last_exc = e
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_BACKOFF_BASE_S * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


def _user_block(case: PromptCase, response: str, archetype_desc: str) -> str:
    return f"""ARCHETYPE:
{archetype_desc}

USER MESSAGE:
{case.user_message}

COACH RESPONSE:
{response}

EXPECTED BEHAVIOR (the response should reflect these):
{json.dumps(case.expected_behavior)}

MUST_NOT (the response must avoid these):
{json.dumps(case.must_not)}

FOCUS DIMENSIONS (weight these more heavily):
{json.dumps(case.focus_dimensions)}
"""


def _parse_judge_text(text: str) -> JudgeResult:
    try:
        data = _extract_json(text)
    except Exception as e:
        return JudgeResult(
            passed=False,
            scores=dict(ZERO_SCORES),
            violations=[f"judge JSON parse error: {e}"],
            evidence=text[:500],
        )
    # Merge model scores onto the all-zero baseline so the dict shape is
    # invariant — every dimension key is always present.
    raw_scores = data.get("scores") or {}
    scores = dict(ZERO_SCORES)
    for k, v in raw_scores.items():
        if k in ZERO_SCORES:
            try:
                scores[k] = int(v)
            except (TypeError, ValueError):
                pass
    return JudgeResult(
        passed=bool(data.get("pass", False)),
        scores=scores,
        violations=list(data.get("violations") or []),
        evidence=str(data.get("evidence") or ""),
    )


def judge_response(case: PromptCase, response: str, archetype_desc: str) -> JudgeResult:
    user_block = _user_block(case, response, archetype_desc)
    client = _client()
    try:
        resp = _call_judge_with_retry(client, user_block)
    except Exception as e:
        return JudgeResult(
            passed=False,
            scores=dict(ZERO_SCORES),
            violations=[f"judge API error: {type(e).__name__}: {e}"],
            evidence="",
        )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return _parse_judge_text(text)


def judge_batch(items, *, chunk: int = 100, poll_s: int = 30, log=print) -> dict:
    """S127: judge MANY (case, response, archetype_desc) triples through the
    Message Batches API — 50% of standard pricing, all chunks submitted up
    front, then polled together; results keyed by case id (never by list
    position). The system prompt carries a cache_control breakpoint since it
    is identical across the batch. Returns {case.id: JudgeResult}."""
    import time as _t
    client = _client()
    reqs = []
    for case, response, archetype_desc in items:
        reqs.append({
            "custom_id": str(case.id)[:64],
            "params": {
                "model": JUDGE_MODEL, "max_tokens": MAX_TOKENS,
                "system": [{"type": "text", "text": JUDGE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": _user_block(case, response, archetype_desc)}],
            },
        })
    batches = {}
    for i in range(0, len(reqs), chunk):
        part = reqs[i:i + chunk]
        for attempt in range(4):
            try:
                b = client.messages.batches.create(requests=part)
                batches[b.id] = [r["custom_id"] for r in part]
                log(f"[judge_batch] submitted {b.id} ({len(part)} requests)")
                break
            except Exception as e:
                if attempt == 3:
                    raise
                _t.sleep(5 * 2 ** attempt)
    out = {}
    pending = set(batches)
    while pending:
        for bid in list(pending):
            b = client.messages.batches.retrieve(bid)
            if b.processing_status != "ended":
                continue
            for r in client.messages.batches.results(bid):
                if r.result.type == "succeeded":
                    text = "".join(blk.text for blk in r.result.message.content if getattr(blk, "type", None) == "text")
                    out[r.custom_id] = _parse_judge_text(text)
                else:
                    out[r.custom_id] = JudgeResult(passed=False, scores=dict(ZERO_SCORES),
                                                   violations=[f"judge batch error: {r.result.type}"], evidence="")
            pending.discard(bid)
            log(f"[judge_batch] collected {bid}")
        if pending:
            _t.sleep(poll_s)
    return out
