"""Aggregate findings/<run_id>/*.json into a markdown report."""
from __future__ import annotations
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import mean

from .runner import FINDINGS_ROOT


REPORTS_ROOT = Path(__file__).parent / "reports"


def _load_findings(run_id: str) -> list[dict]:
    d = FINDINGS_ROOT / run_id
    if not d.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]


def _by_category(findings: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "fails": []})
    for f in findings:
        h_pass = f.get("heuristic", {}).get("passed", False)
        j = f.get("judge") or {}
        j_pass = j.get("passed", False) if j else h_pass
        passed = h_pass and j_pass
        bucket = out[f["category"]]
        bucket["pass" if passed else "fail"] += 1
        if not passed:
            bucket["fails"].append(f["prompt_id"])
    return out


def _dimension_avgs(findings: list[dict]) -> dict[str, float]:
    dims: dict[str, list[float]] = defaultdict(list)
    for f in findings:
        scores = (f.get("judge") or {}).get("scores") or {}
        for k, v in scores.items():
            try:
                dims[k].append(float(v))
            except (TypeError, ValueError):
                pass
    return {k: round(mean(vs), 2) for k, vs in dims.items() if vs}


def _heuristic_vs_judge(findings: list[dict]) -> dict[str, list[str]]:
    only_judge_failed = []
    only_heuristic_failed = []
    for f in findings:
        h = f.get("heuristic", {}).get("passed", False)
        j = (f.get("judge") or {}).get("passed", False)
        if h and not j:
            only_judge_failed.append(f["prompt_id"])
        elif j and not h:
            only_heuristic_failed.append(f["prompt_id"])
    return {
        "judge_only_fail": only_judge_failed,
        "heuristic_only_fail": only_heuristic_failed,
    }


CLUSTER_SYSTEM = """You are analyzing failures from a coach AI test suite.
You will be shown a list of failures, each with prompt_id, category, and judge violations.

Cluster these into 1-6 named themes. For each theme, return:
- name: short label (≤60 chars)
- count: number of failures in this theme
- prompts: list of prompt_ids
- fix: one-sentence recommended fix

Respond with JSON only:
{ "themes": [{"name": "...", "count": N, "prompts": [...], "fix": "..."}] }
"""


def _call_clustering_llm(failures: list[dict]) -> list[dict]:
    if not failures:
        return []
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_payload = json.dumps([
        {
            "prompt_id": f["prompt_id"],
            "category": f["category"],
            "violations": (f.get("judge") or {}).get("violations", []),
        }
        for f in failures
    ], indent=2)
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=CLUSTER_SYSTEM,
        messages=[{"role": "user", "content": user_payload}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    text = text.strip()
    if text.startswith("```"):
        import re as _re
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except Exception:
        return []
    return list(data.get("themes") or [])


def cluster_patterns(failures: list[dict]) -> list[dict]:
    return _call_clustering_llm(failures)


def build_report(run_id: str) -> Path:
    findings = _load_findings(run_id)
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_ROOT / f"{run_id}.md"

    total = len(findings)
    passed = sum(
        1 for f in findings
        if f.get("heuristic", {}).get("passed")
        and (f.get("judge") or {}).get("passed", False)
    )
    fail = total - passed

    cats = _by_category(findings)
    dim_avgs = _dimension_avgs(findings)
    hvj = _heuristic_vs_judge(findings)

    lines: list[str] = [f"# Coach Audit Report — run {run_id}", ""]
    lines += [
        "## Summary",
        "",
        f"- Total prompts: **{total}**",
        f"- Passed: **{passed}** ({(lambda p: f'{int(p)}%' if p == int(p) else f'{round(p, 1)}%')(100 * passed / total) if total else '0%'})",
        f"- Failed: **{fail}**",
        "",
    ]

    lines += ["## Pass rate by category", "",
              "| Category | Pass | Fail | Rate |", "|---|---|---|---|"]
    for cat, vals in sorted(cats.items(), key=lambda kv: kv[1]["fail"], reverse=True):
        denom = vals["pass"] + vals["fail"]
        if denom:
            pct = 100 * vals["pass"] / denom
            rate = f"{int(pct)}%" if pct == int(pct) else f"{round(pct, 1)}%"
        else:
            rate = "-"
        lines.append(f"| {cat} | {vals['pass']} | {vals['fail']} | {rate} |")
    lines.append("")

    if dim_avgs:
        lines += ["## Judge dimension averages", ""]
        for k, v in sorted(dim_avgs.items()):
            mark = " ⚠" if v < 7 else ""
            lines.append(f"- {k}: **{v}**{mark}")
        lines.append("")

    if hvj["judge_only_fail"] or hvj["heuristic_only_fail"]:
        lines += ["## Heuristic vs judge breakdown", ""]
        if hvj["judge_only_fail"]:
            lines.append(
                f"- **Judge caught what heuristic missed** "
                f"({len(hvj['judge_only_fail'])} prompts): "
                + ", ".join(hvj["judge_only_fail"])
            )
        if hvj["heuristic_only_fail"]:
            lines.append(
                f"- **Heuristic caught what judge missed** "
                f"({len(hvj['heuristic_only_fail'])} prompts): "
                + ", ".join(hvj["heuristic_only_fail"])
            )
        lines.append("")

    if fail:
        lines += ["## Failures by prompt", ""]
        for f in findings:
            h = f.get("heuristic", {}).get("passed", False)
            j = (f.get("judge") or {}).get("passed", False)
            if h and j:
                continue
            lines.append(f"### {f['prompt_id']} — {f['category']}")
            lines.append(f"**Prompt:** {f['user_message']}")
            lines.append(f"**Response (truncated):** {f['coach_response'][:400]}")
            if not h:
                hh = f["heuristic"]
                lines.append(
                    f"**Heuristic:** missing={hh['missing_expected']} "
                    f"must_not={hh['matched_must_not']} banned={hh['matched_banned']}"
                )
            if f.get("judge") and not j:
                jj = f["judge"]
                lines.append(f"**Judge violations:** {jj['violations']}")
                lines.append(f"**Judge scores:** {jj['scores']}")
            lines.append("")

    lines += ["", f"*Findings dir:* `tests/coach_audit/findings/{run_id}/`"]

    failed_findings = [
        f for f in findings
        if not (f.get("heuristic", {}).get("passed")
                and (f.get("judge") or {}).get("passed", False))
    ]
    if failed_findings and os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("AUDIT_CLUSTER", "1") != "0":
        try:
            themes = cluster_patterns(failed_findings)
            if themes:
                lines += ["## Top failure patterns (clustered)", ""]
                for t in themes:
                    lines.append(f"### {t.get('name','(unnamed)')} ({t.get('count', 0)} occurrences)")
                    prompts = t.get("prompts") or []
                    if prompts:
                        lines.append(f"- Affected prompts: {', '.join(prompts)}")
                    fix = t.get("fix")
                    if fix:
                        lines.append(f"- Recommended fix: {fix}")
                    lines.append("")
        except Exception as e:
            lines += [f"_Pattern clustering failed: {e}_", ""]

    out_path.write_text("\n".join(lines))
    return out_path
