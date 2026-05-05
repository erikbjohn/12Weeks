"""Tests for the .claude/agents/*.md loader."""
import os
from pathlib import Path
import pytest


def test_loader_parses_frontmatter_and_body(tmp_path, monkeypatch):
    """The loader returns a dict with model, tools, system_prompt parsed from
    a markdown file's YAML frontmatter + body."""
    from coach_specialists.loader import load_agent_md

    # Point loader at a fixture dir
    fixture = tmp_path / "agents"
    fixture.mkdir()
    (fixture / "tester.md").write_text(
        "---\n"
        "name: Tester\n"
        "model: claude-sonnet-4-6\n"
        "tools:\n"
        "  - get_workout\n"
        "  - get_recent_sets\n"
        "---\n"
        "You are the Tester. Test things.\n"
    )
    monkeypatch.setattr(
        "coach_specialists.loader.AGENTS_DIR", fixture,
    )

    cfg = load_agent_md("tester")

    assert cfg["name"] == "Tester"
    assert cfg["model"] == "claude-sonnet-4-6"
    assert cfg["tools"] == ["get_workout", "get_recent_sets"]
    assert "You are the Tester" in cfg["system_prompt"]


def test_loader_raises_on_missing_file(tmp_path, monkeypatch):
    from coach_specialists.loader import load_agent_md
    monkeypatch.setattr("coach_specialists.loader.AGENTS_DIR", tmp_path / "agents")
    with pytest.raises(FileNotFoundError):
        load_agent_md("does-not-exist")


def test_all_four_persona_files_load():
    """Smoke test — all 4 specialist persona files exist and parse."""
    from coach_specialists.loader import load_agent_md
    for name in ("doctor", "nutritionist", "strength-coach", "running-coach"):
        cfg = load_agent_md(name)
        assert cfg["name"]
        assert cfg["model"]
        assert cfg["system_prompt"]
        # Doctor has consult tools; specialists have domain tools
        assert isinstance(cfg["tools"], list) and len(cfg["tools"]) >= 1
