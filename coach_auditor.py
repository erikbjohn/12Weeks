"""Sonnet-backed single-claim auditor for Step 4 of the zero-hallucination
architecture. Each call audits ONE claim against ONE or more source rows;
returns supported / not-supported + reason. Cheap (~$0.005/audit) and
parallel-friendly.

Architectural intent: the orchestrator calls audit_claim for each cited
claim in the response after the response is generated. If any audit
returns not-supported, the orchestrator either (a) re-prompts the
Doctor with the violations, or (b) emits a follow-up correction
message 3-5s after the original response (async pattern, lower
perceived latency).
"""
from __future__ import annotations
from dataclasses import dataclass
import os


@dataclass
class AuditResult:
    supported: bool
    reason: str = ""


_AUDIT_PROMPT = """You audit single coach claims for support.

CLAIM:
{claim}

SOURCE ROWS (the claim must be supported by these — and ONLY these):
{rows}

Respond with EXACTLY one of:
  supported
  not supported: <one short sentence why>

Rules:
- "supported" means: every fact in the claim is present in or directly derivable from the source rows.
- A predicate-context mismatch is "not supported" — e.g. claim says "5 weeks left in cut" but source rows are about "5 weeks before 50k race". The number is real but the noun is wrong.
- Inline arithmetic is OK if both inputs are in source rows.
- One short answer. No preamble. No explanation beyond the reason."""


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=20.0,
        max_retries=3,
    )


def audit_claim(claim_text: str, source_rows: list[str]) -> AuditResult:
    """Audit a single claim against source rows. Returns AuditResult."""
    client = _anthropic_client()
    rows_block = "\n".join(f"  - {r}" for r in source_rows) if source_rows else "  (none)"
    user_msg = _AUDIT_PROMPT.format(claim=claim_text, rows=rows_block)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=120,
        system="You are a precise fact-check auditor.",
        messages=[{"role": "user", "content": user_msg}],
    )
    out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip().lower()
    if out.startswith("supported"):
        return AuditResult(supported=True)
    if out.startswith("not supported"):
        # Strip the "not supported:" prefix
        reason = out.replace("not supported", "", 1).lstrip(":").strip()
        return AuditResult(supported=False, reason=reason or out)
    # Defensive: ambiguous response — treat as supported to avoid blocking
    # legitimate output, but include the raw text as the reason for logging.
    return AuditResult(supported=True, reason=f"ambiguous_audit_response: {out!r}")


@dataclass
class PostureResult:
    ok: bool
    reason: str = ""


_POSTURE_PROMPT = """You audit coach response posture, NOT facts.

USER MESSAGE (most recent):
{user_msg}

COACH RESPONSE:
{response}

Question: did the user assert a fact about their schedule or program? If yes,
did the coach (a) accept it and re-read the data, or (b) challenge the user
asking what they're seeing?

Respond with EXACTLY one of:
  ok
  defensive: <one short sentence describing the failure>

Rules:
- "ok" is the default — only flag clear-cut defensive pushback.
- The user is the source of ground truth about what they see in the UI.
  Asking "what are you seeing" / "where does it say X" is the failure
  pattern.
- Genuine clarifying questions ("when did you log that run?") are fine.
- One short answer. No preamble."""


def audit_posture(user_message: str, response_text: str) -> PostureResult:
    client = _anthropic_client()
    msg = _POSTURE_PROMPT.format(user_msg=user_message, response=response_text)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=80,
        system="You audit conversational posture, not facts.",
        messages=[{"role": "user", "content": msg}],
    )
    out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip().lower()
    if out.startswith("ok"):
        return PostureResult(ok=True)
    if out.startswith("defensive"):
        reason = out.replace("defensive", "", 1).lstrip(":").strip()
        return PostureResult(ok=False, reason=reason or out)
    return PostureResult(ok=True, reason=f"ambiguous: {out!r}")


def audit_response_async(
    user_message: str,
    response_text: str,
    cited_claims: list,
) -> tuple:
    """Run all per-claim audits + posture audit in parallel.

    cited_claims: list of (claim_text, source_rows) pairs — one per
    claim that needs auditing.

    Returns (claim_results, posture_result). Caller decides how to act
    on failures (re-prompt vs. follow-up correction).
    """
    import asyncio

    async def run_one_claim(text, rows):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, audit_claim, text, rows)

    async def run_posture():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, audit_posture, user_message, response_text)

    async def run_all():
        claim_tasks = [run_one_claim(t, r) for t, r in cited_claims]
        posture_task = run_posture()
        claim_results = await asyncio.gather(*claim_tasks)
        posture_result = await posture_task
        return claim_results, posture_result

    try:
        return asyncio.run(run_all())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, run_all()).result()
