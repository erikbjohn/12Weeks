"""Parse .claude/agents/<name>.md files into runtime configs.

Each agent file has YAML frontmatter (model, tools list, name) and a
body that becomes the system prompt. This module is the only place
that knows the .claude/agents/ format — runtime modules just call
load_agent_md(name) and get a dict back.
"""
from __future__ import annotations
from pathlib import Path
import re
import yaml

AGENTS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "agents"

_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def load_agent_md(name: str) -> dict:
    """Load .claude/agents/<name>.md and return {name, model, tools, system_prompt}.

    Raises FileNotFoundError if the file is missing. Raises ValueError if
    the file lacks YAML frontmatter or the frontmatter doesn't parse.
    """
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        raise ValueError(f"Agent file {path} has no YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()
    return {
        "name": fm.get("name", name),
        "model": fm.get("model", "claude-sonnet-4-6"),
        "tools": list(fm.get("tools") or []),
        "system_prompt": body,
    }
