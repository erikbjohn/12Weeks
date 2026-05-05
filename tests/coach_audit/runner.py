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


def make_judge_invoker(app, user):
    """Return a judge function bound to (app, user). The judge gets the
    user's archetype description PLUS the actual prescribed full-week
    program block (so it doesn't over-flag accessories the coarse archetype
    didn't enumerate) PLUS the last ~50 SetLog rows (so it doesn't flag
    the coach citing real seeded numbers as 'hallucinated')."""
    from .judge import judge_response
    from .users import ARCHETYPE_DESCRIPTIONS
    from coach_assembler import _format_full_week_program
    from flask_login import login_user
    from models import AppState, SetLog

    uid = user.id
    with app.test_request_context():
        login_user(user, force=True)
        state = AppState.query.filter_by(user_id=uid).first()
        week = state.current_week if state else 1
        program_block = _format_full_week_program(week)
        recent_sets = (
            SetLog.query
            .filter(SetLog.user_id == uid, SetLog.done.is_(True))
            .order_by(SetLog.logged_date.desc(), SetLog.set_number.asc())
            .limit(50).all()
        )
        if recent_sets:
            history_lines = ["RECENT LOGGED SETS (cite from this — these are real, not hallucinated):"]
            for s in recent_sets:
                history_lines.append(
                    f"  {s.logged_date} wk{s.week} day{s.day_idx} "
                    f"{s.exercise_name}: set {s.set_number} {s.weight}lb x {s.reps}"
                )
            history_block = "\n".join(history_lines)
        else:
            history_block = "RECENT LOGGED SETS: none on file."

    def invoke(case, response):
        archetype_desc = ARCHETYPE_DESCRIPTIONS.get(case.user_fixture, "")
        ground_truth = (
            f"{archetype_desc}\n\n"
            "ACTUAL PRESCRIBED PROGRAM (cite from this — anything matching "
            "this is NOT a hallucination):\n\n"
            f"{program_block}\n\n"
            f"{history_block}"
        )
        return judge_response(case, response, ground_truth)
    return invoke


def make_coach_invoker(app, user, agent_name: str = "conversation"):
    """Return a callable(user_message: str) -> str that runs the production
    coach pipeline against this user's seeded data.

    Uses `assemble_prompt` (full system prompt with athlete data block + full
    week injection) and `coach_chat` (tool-using loop)."""
    from coach_assembler import build_filtered_context, assemble_prompt
    from coach_with_tools import coach_chat
    from flask_login import login_user

    # Capture the primary key now so the closure stays valid even if `user`
    # later detaches from its session (e.g. session-scoped fixtures in Task 6+).
    uid = user.id

    def invoke(user_message: str) -> str:
        with app.test_request_context():
            login_user(user, force=True)
            ctx = build_filtered_context(agent_name)
            system_prompt = assemble_prompt(agent_name, ctx)
            return coach_chat(
                user_id=uid,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                agent_name=agent_name,
            )
    return invoke


def make_specialist_invoker(specialist_name: str, app, user):
    """Return a callable(user_message: str) -> str that calls the specialist
    DIRECTLY (bypassing the Doctor). Used by the audit to test specialists
    in isolation.

    specialist_name: 'nutritionist' | 'strength' | 'running'
    """
    from flask_login import login_user

    SPEC_MOD = {
        "nutritionist": "coach_specialists.nutritionist",
        "strength":     "coach_specialists.strength",
        "running":      "coach_specialists.running",
    }
    if specialist_name not in SPEC_MOD:
        raise ValueError(f"Unknown specialist: {specialist_name}")

    import importlib
    mod = importlib.import_module(SPEC_MOD[specialist_name])
    uid = user.id

    def invoke(user_message: str) -> str:
        with app.test_request_context():
            login_user(user, force=True)
            # The audit's user_message becomes the Doctor's brief here.
            return mod.consult(brief=user_message, user_id=uid)
    return invoke
