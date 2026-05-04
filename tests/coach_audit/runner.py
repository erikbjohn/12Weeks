"""Per-prompt orchestration. Coach call + heuristic + judge + persist."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .types import PromptCase, Finding, HeuristicResult, JudgeResult
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
