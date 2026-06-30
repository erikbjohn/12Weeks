"""C6 — Erik runs ALL 7 days; no day may be left runless (least of all Monday,
the heavy-lower day, which the generator historically left blank — wk11 bug).
The _ensure_seven_day_runs backstop fills any gap with an easy Z2 recovery run.
"""


def test_fills_every_missing_day():
    from coach_planning_runs import _ensure_seven_day_runs
    out = _ensure_seven_day_runs({}, week=5)  # coach produced nothing
    assert set(out.keys()) == set(range(7))
    for d in range(7):
        assert out[d]["type"] and out[d]["duration"]


def test_monday_never_runless():
    from coach_planning_runs import _ensure_seven_day_runs
    # coach gave runs Tue-Sun but skipped Monday (day 0) — the exact wk11 bug.
    partial = {d: {"type": "z2", "label": "x", "duration": "30 min",
                   "detail": "", "segments": None} for d in range(1, 7)}
    out = _ensure_seven_day_runs(partial, week=6)
    assert 0 in out and out[0]["duration"]


def test_does_not_overwrite_existing_runs():
    from coach_planning_runs import _ensure_seven_day_runs
    existing = {2: {"type": "vo2", "label": "VO2 4x3", "duration": "41 min",
                    "detail": "intervals", "segments": [{"kind": "work", "minutes": 3}]}}
    out = _ensure_seven_day_runs(dict(existing), week=5)
    assert out[2]["type"] == "vo2" and out[2]["duration"] == "41 min"  # untouched
    assert len(out) == 7
