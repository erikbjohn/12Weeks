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
