"""Audit suite test entry point. Parametrized over `ALL_PROMPTS`."""
import os
import pytest
from .prompts import ALL_PROMPTS
from .runner import run_prompt, make_coach_invoker, make_judge_invoker


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


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY for live coach + judge",
)
@pytest.mark.parametrize(
    "case",
    [p for p in ALL_PROMPTS if p.category not in ("smoke",)],
    ids=lambda c: c.id,
)
def test_audit_case(case, fixture_by_name, app_ctx, run_id, audit_mode):
    if case.requires_real_data and audit_mode != "full":
        pytest.skip("requires --audit-mode=full")

    user = fixture_by_name(case.user_fixture)
    app, _ = app_ctx
    invoke = make_coach_invoker(app, user)
    judge = make_judge_invoker(app, user)
    finding = run_prompt(
        case=case,
        user_id=user.id,
        invoke_coach=invoke,
        invoke_judge=judge,
        run_id=run_id,
    )
    assert finding.heuristic.passed, (
        f"[{case.id}] heuristic: "
        f"missing={finding.heuristic.missing_expected} "
        f"must_not={finding.heuristic.matched_must_not} "
        f"banned={finding.heuristic.matched_banned}\n"
        f"--- response ---\n{finding.coach_response}"
    )
    assert finding.judge.passed, (
        f"[{case.id}] judge: violations={finding.judge.violations}\n"
        f"scores={finding.judge.scores}\n"
        f"evidence={finding.judge.evidence}\n"
        f"--- response ---\n{finding.coach_response}"
    )


def test_phase_1_newbie_has_no_history(phase_1_newbie):
    from models import SetLog, AppState
    user = phase_1_newbie
    rows = SetLog.query.filter_by(user_id=user.id).all()
    assert len(rows) == 0, "phase_1_newbie should have no SetLog history"
    state = AppState.query.filter_by(user_id=user.id).first()
    assert state.current_week == 2


def test_phase_3_cut_has_plateau_pattern(phase_3_cut):
    from models import SetLog
    bench_rows = SetLog.query.filter_by(
        user_id=phase_3_cut.id,
        exercise_name="Barbell Bench Press",
    ).all()
    weights = sorted({r.weight for r in bench_rows})
    # Plateau invariant: ALL bench sets at 165 — adding a fourth week at a
    # different weight would silently break the deload-prescription test case.
    assert weights == [165], (
        f"phase_3_cut bench weights must be a flat plateau at 165, got {weights}"
    )


def test_no_gym_bw_lacks_barbell(no_gym_bw):
    from models import UserEquipment
    eq = UserEquipment.query.filter_by(user_id=no_gym_bw.id).first()
    assert "barbell" not in (eq.available_equipment or [])
    assert "kettlebells" in (eq.available_equipment or [])


@pytest.mark.real_data
def test_real_erik_fixture_loads(real_erik, audit_mode):
    if audit_mode != "full":
        pytest.skip("requires --audit-mode=full")
    from models import AppState
    state = AppState.query.filter_by(user_id=real_erik.id).first()
    assert state is not None
    assert state.current_week >= 1
