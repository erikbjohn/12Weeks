"""Test the report generator with synthetic findings."""
import json
from pathlib import Path
import pytest


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    from tests.coach_audit import runner as runner_module
    findings_root = tmp_path / "findings"
    monkeypatch.setattr(runner_module, "FINDINGS_ROOT", findings_root)

    from tests.coach_audit import report as report_module
    monkeypatch.setattr(report_module, "FINDINGS_ROOT", findings_root)
    monkeypatch.setattr(report_module, "REPORTS_ROOT", tmp_path / "reports")

    run_id = "20260501-120000"
    d = findings_root / run_id
    d.mkdir(parents=True)

    findings = [
        {
            "prompt_id": "cross_day_001", "category": "cross_day_hallucination",
            "user_message": "What's Monday?", "coach_response": "Front Squat 4x3",
            "heuristic": {"passed": True, "missing_expected": [],
                          "matched_must_not": [], "matched_banned": []},
            "judge": {"passed": True,
                      "scores": {"accuracy": 9, "tone": 8, "no_hallucination": 9, "follows_must_not": 10},
                      "violations": [], "evidence": ""},
            "fixture": "phase_2_mid_program",
            "timestamp_iso": "2026-05-01T12:00:00+00:00",
        },
        {
            "prompt_id": "cross_day_002", "category": "cross_day_hallucination",
            "user_message": "Friday?", "coach_response": "Deadlift 5x5",
            "heuristic": {"passed": False, "missing_expected": ["back squat", "4x5"],
                          "matched_must_not": [], "matched_banned": []},
            "judge": {"passed": False,
                      "scores": {"accuracy": 2, "tone": 7, "no_hallucination": 1, "follows_must_not": 8},
                      "violations": ["Hallucinated deadlift; Friday is Back Squat 4x5"],
                      "evidence": "Deadlift 5x5"},
            "fixture": "phase_2_mid_program",
            "timestamp_iso": "2026-05-01T12:01:00+00:00",
        },
    ]
    for f in findings:
        (d / f"{f['prompt_id']}.json").write_text(json.dumps(f, indent=2))
    return run_id, tmp_path


def test_build_report_emits_summary(fake_run):
    from tests.coach_audit.report import build_report
    run_id, root = fake_run
    out = build_report(run_id)
    assert out.exists()
    text = out.read_text()
    assert "Summary" in text
    assert "Pass rate by category" in text
    assert "cross_day_hallucination" in text
    assert "50%" in text or "1 / 2" in text


def test_cluster_patterns_returns_themes(monkeypatch):
    from tests.coach_audit import report as report_module

    fake_response = {
        "themes": [
            {"name": "Cross-day workout confusion", "count": 4,
             "prompts": ["cross_day_001", "cross_day_002"],
             "fix": "Tighten full-week injection in athlete_data"}
        ]
    }

    def fake_call(failures):
        return fake_response["themes"]
    monkeypatch.setattr(report_module, "_call_clustering_llm", fake_call)

    failures = [
        {"prompt_id": "cross_day_001", "category": "cross_day_hallucination",
         "judge": {"violations": ["Said Back Squat for Monday"]}},
        {"prompt_id": "cross_day_002", "category": "cross_day_hallucination",
         "judge": {"violations": ["Said Deadlift for Friday"]}},
    ]
    themes = report_module.cluster_patterns(failures)
    assert themes == fake_response["themes"]
