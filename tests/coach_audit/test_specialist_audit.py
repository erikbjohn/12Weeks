"""Smoke test that the per-specialist audit path works."""
import pytest
import os


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY for live specialist call",
)
def test_nutritionist_specialist_invoker_smoke(phase_2_mid_program, app_ctx):
    from tests.coach_audit.runner import make_specialist_invoker
    app, _ = app_ctx
    invoke = make_specialist_invoker("nutritionist", app, phase_2_mid_program)
    out = invoke("Should the athlete eat 30g carbs at break-fast tomorrow?")
    # Just verify we got a response that mentions a recommendation
    low = out.lower()
    assert "recommendation" in low or "rec:" in low
