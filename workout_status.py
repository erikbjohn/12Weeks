"""Canonical 3-state workout completion — the ONE definition of "done".

States: not_started | in_progress | complete

The invariant (audit theme 5-three-state): a day/workout is COMPLETE only when
EVERY prescribed exercise has its prescribed number of sets actually performed
(SetLog.done == True and not set_skipped), matched name-aware via resolve_name.
A name-agnostic COUNT of done rows must never substitute — extra sets on one
exercise (or stale rows from a replaced plan) must not stand in for a skipped
movement. Some-but-not-all done = in_progress. A partial must NEVER read
complete.

Every completion decision (app.py auto-complete, coach_assembler today_status /
completed_days, coach_rules._compute_workout_status) must route through
workout_state_from_rows so the engines can never disagree. An authoritative,
date-gated DayCompletion.done flag may still be OR'd in by callers — that is a
human/coach decision, not a heuristic.
"""

import re

__all__ = ["parse_sets_count", "workout_state_from_rows"]


def parse_sets_count(val):
    """Prescribed set count from an int (4), numeric string ("4"), or a
    "SETSxREPS" display string ("4x8", "3 x 12"). Unknown/absent -> 1 (at
    least one performed set is required — never 0, which would auto-satisfy)."""
    if isinstance(val, bool):  # bool is an int subclass; reject explicitly
        return 1
    if isinstance(val, (int, float)):
        return max(int(val), 1)
    if isinstance(val, str):
        m = re.match(r"\s*(\d+)", val)
        if m:
            return max(int(m.group(1)), 1)
    return 1


def _norm(name):
    """Canonical, case-insensitive exercise-name key."""
    from workout_data import resolve_name
    return resolve_name((name or "").strip()).strip().lower()


def workout_state_from_rows(prescribed_exercises, set_rows):
    """PURE 3-state computation for one (week, day_idx) slot.

    prescribed_exercises: iterable of dicts with "name" and "sets" (int or
        "4x8"-style string) — e.g. coach_assembler._resolve_workout_for_day's
        day["exercises"], which already carries manual/equipment swaps so
        logged names line up with prescribed names.
    set_rows: SetLog rows (or any objects with .exercise_name/.done/
        .set_skipped) for the slot. Callers decide date scoping.

    Rules:
      - no rows at all               -> not_started
      - rows, no prescription        -> in_progress (an UNPLANNED day can never
        read complete from set counts; only an explicit DayCompletion — which
        callers OR in themselves — can complete it)
      - every prescribed exercise has >= its prescribed sets PERFORMED
        (done and not set_skipped, name-aware)   -> complete
      - anything less                -> in_progress
    """
    performed = {}
    any_rows = False
    for r in set_rows or []:
        any_rows = True
        done = bool(getattr(r, "done", False))
        skipped = bool(getattr(r, "set_skipped", False))
        if done and not skipped:
            key = _norm(getattr(r, "exercise_name", None))
            performed[key] = performed.get(key, 0) + 1

    if not any_rows:
        return "not_started"

    required = {}
    for ex in prescribed_exercises or []:
        name = (ex or {}).get("name")
        if not name:
            continue
        key = _norm(name)
        required[key] = required.get(key, 0) + parse_sets_count(ex.get("sets"))

    if not required:
        return "in_progress"

    for key, need in required.items():
        if performed.get(key, 0) < need:
            return "in_progress"
    return "complete"
