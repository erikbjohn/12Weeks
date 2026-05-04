"""Top-level audit suite. Parametrized over `ALL_PROMPTS`."""
import pytest
from tests.coach_audit.prompts import ALL_PROMPTS
from tests.coach_audit.runner import run_prompt


@pytest.mark.parametrize("case", [p for p in ALL_PROMPTS if p.category == "smoke"],
                         ids=lambda c: c.id)
def test_smoke(case, run_id):
    """Stub coach echoes 'pong' — proves harness wiring works end-to-end."""
    finding = run_prompt(
        case=case,
        user_id=0,
        invoke_coach=lambda msg: "pong",
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"heuristic failed: missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}"
    )
