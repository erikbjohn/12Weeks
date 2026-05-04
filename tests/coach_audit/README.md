# Coach Audit Suite

Parametrized pytest harness that runs ~50 prompts through the production
coach (`coach_chat`), evaluates each response with heuristics + Opus 4.7
LLM-as-judge, persists findings, and emits a ranked-failure markdown report.

## Run modes

### CI mode (synthetic users only — safe, fast, ~$30/run)

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY venv/bin/pytest tests/coach_audit/ -n 8
```

### Full audit (real-Erik fixture too — slower, hits prod read-only)

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
ADMIN_API_KEY=$ADMIN_API_KEY \
venv/bin/pytest tests/coach_audit/ -n 8 --audit-mode=full
```

## Output

- `tests/coach_audit/findings/<run_id>/<prompt_id>.json` — per-prompt findings
- `tests/coach_audit/reports/<run_id>.md` — aggregated markdown report

Reports include: summary stats, pass-rate-by-category, judge dimension
averages, heuristic-vs-judge breakdown, clustered failure patterns
(via final Opus call), and a ranked recommended-fixes list.

## Adding a new prompt

Append a `PromptCase` to `tests/coach_audit/prompts.py`. Pick:
- `id`: stable string, used as filename
- `category`: one of the 12 categories (or add a new one + severity in `report.py`)
- `user_fixture`: name of pytest fixture (e.g., `phase_2_mid_program`)
- `expected_behavior`: substrings that must appear in response (lowercased; `×` ↔ `x`)
- `must_not`: substrings that must NOT appear
- `focus_dimensions`: judge weights these heavily

A module-import-time check (`_validate_corpus()`) verifies your `user_fixture`
string maps to one of the registered fixtures.

## Adding a new fixture

Add a factory to `tests/coach_audit/users.py`, register a fixture in
`tests/coach_audit/conftest.py`, and add an archetype description to
`ARCHETYPE_DESCRIPTIONS` (used by the judge). Reuse helpers
`_seed_progressive_setlog` and `_seed_bodyweight_trend`.

## Cost

~$0.50/prompt with current Opus 4.7 pricing (1 coach call + 1 judge call).
50 prompts ≈ $25. Add ~$0.15 for final clustering. Run on demand or weekly.

The judge has bounded retry on Anthropic 5xx and connection errors so a
single hiccup doesn't kill a multi-prompt run. Set `AUDIT_CLUSTER=0` to
skip the final clustering call (useful for spot checks).

## Spec & plan

- Spec: `docs/superpowers/specs/2026-05-01-coach-audit-design.md`
- Plan: `docs/superpowers/plans/2026-05-01-coach-audit-implementation.md`
