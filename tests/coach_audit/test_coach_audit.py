"""Audit suite test entry point. Parametrized over `ALL_PROMPTS`."""
import pytest
from .prompts import ALL_PROMPTS
from .runner import run_prompt


@pytest.mark.parametrize("case", [p for p in ALL_PROMPTS if p.category == "smoke"],
                         ids=lambda c: c.id)
def test_smoke(case, run_id):
    """Stub coach echoes 'pong' — proves harness wiring works end-to-end."""
    finding = run_prompt(
        case=case,
        user_id=0,
        invoke_coach=lambda _msg: "pong",
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"heuristic failed: missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}"
    )


def test_phase_2_fixture_seeds_setlog_history(phase_2_mid_program):
    """Fixture should create a user with at least 3 weeks of SetLog rows."""
    from models import SetLog
    user = phase_2_mid_program
    rows = SetLog.query.filter_by(user_id=user.id, done=True).all()
    assert len(rows) >= 30, f"expected ≥30 SetLog rows, got {len(rows)}"
    weeks = {r.week for r in rows}
    assert weeks >= {3, 4, 5}, f"expected weeks 3-5 in history, got {weeks}"
