"""Per-prompt orchestration. Coach call + heuristic + judge + persist."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .types import PromptCase, Finding
from .heuristics import check_heuristics


FINDINGS_ROOT = Path(__file__).parent / "findings"


def _findings_dir(run_id: str) -> Path:
    p = FINDINGS_ROOT / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_prompt(
    *,
    case: PromptCase,
    user_id: int,
    invoke_coach,                    # callable(user_message: str) -> str
    invoke_judge=None,               # callable(case, response) -> JudgeResult | None
    run_id: str,
) -> Finding:
    # `user_id` is bound by callers; the runner doesn't need it directly because
    # `invoke_coach` is already a closure over the seeded user. Recorded here
    # for traceability — future tasks may include it in the persisted Finding.
    _ = user_id
    response = invoke_coach(case.user_message)
    heuristic = check_heuristics(response, case)
    judge = invoke_judge(case, response) if invoke_judge else None

    finding = Finding(
        prompt_id=case.id,
        category=case.category,
        user_message=case.user_message,
        coach_response=response,
        heuristic=heuristic,
        judge=judge,
        timestamp_iso=datetime.now(timezone.utc).isoformat(),
        fixture=case.user_fixture,
    )
    out = _findings_dir(run_id) / f"{case.id}.json"
    out.write_text(json.dumps(finding.to_dict(), default=str, indent=2))
    return finding


def make_coach_invoker(app, user, agent_name: str = "conversation"):
    """Return a callable(user_message: str) -> str that runs the production
    coach pipeline against this user's seeded data.

    Uses `assemble_prompt` (full system prompt with athlete data block + full
    week injection) and `coach_chat` (tool-using loop)."""
    from coach_assembler import build_filtered_context, assemble_prompt
    from coach_with_tools import coach_chat
    from flask_login import login_user

    def invoke(user_message: str) -> str:
        with app.test_request_context():
            login_user(user, force=True)
            ctx = build_filtered_context(agent_name)
            system_prompt = assemble_prompt(agent_name, ctx)
            return coach_chat(
                user_id=user.id,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
    return invoke
