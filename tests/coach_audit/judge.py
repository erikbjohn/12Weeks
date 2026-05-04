"""Opus 4.7 LLM-as-judge."""
from __future__ import annotations
import json
import os
import re
from .types import PromptCase, JudgeResult


JUDGE_MODEL = "claude-opus-4-7"
MAX_TOKENS = 800

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
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _extract_json(text: str) -> dict:
    """Extract first JSON object from a response, tolerating accidental prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    raw = m.group(0) if m else text
    return json.loads(raw)


def judge_response(case: PromptCase, response: str, archetype_desc: str) -> JudgeResult:
    user_block = f"""ARCHETYPE:
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
    client = _client()
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=MAX_TOKENS,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_block}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        data = _extract_json(text)
    except Exception as e:
        return JudgeResult(
            passed=False,
            scores={},
            violations=[f"judge JSON parse error: {e}"],
            evidence=text[:500],
        )
    return JudgeResult(
        passed=bool(data.get("pass", False)),
        scores=data.get("scores", {}),
        violations=list(data.get("violations") or []),
        evidence=str(data.get("evidence") or ""),
    )
