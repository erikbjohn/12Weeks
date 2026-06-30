"""The app must not make blocking LLM calls at import/startup.

Bug (2026-06-29): app.py's module-level "ONE-TIME" target_weight backfill runs at
every import inside `with app.app_context()`, calling compute_next_targets ->
lifting_agent.prescribe_starting_weight (a blocking Anthropic call) for every
null-target prescription whose exercise has no history. With the API key set, a
freshly-generated week (many no-history prescriptions) floods the network at boot
and HANGS startup — proven by a faulthandler stack trace stuck in ssl.read during
`import app`. On prod (gunicorn) every worker boot would make LLM calls and the
app fails to start if Anthropic is slow/down.

Fix: compute_next_targets gains allow_llm (default True); the startup backfill
passes allow_llm=False so it never blocks boot on the network.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_compute_next_targets_allow_llm_false_never_calls_agent(app_ctx, monkeypatch):
    import lifting_agent
    from training_engine import compute_next_targets

    def _boom(*a, **k):
        raise AssertionError("prescribe_starting_weight (LLM) called on the no-LLM path")

    monkeypatch.setattr(lifting_agent, "prescribe_starting_weight", _boom)
    # user/exercise with no SetLog history -> the no-history branch, which would
    # normally call the LLM. allow_llm=False must skip it and return a baseline.
    res = compute_next_targets(user_id=987654321, exercise_name="Barbell Back Squat",
                               week=1, day_idx=0, allow_llm=False)
    assert res["target_weight"] is None  # no history, no LLM -> establish baseline
    assert "target_sets" in res and "target_reps" in res
