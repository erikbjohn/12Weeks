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


def completed_day_keys(schedule, toggled, prescribed, set_rows, run_days):
    """EVIDENCE-based set of (week, day_idx) slots that count as trained.

    schedule:   ordered list of (week, day_idx) slots up to today.
    toggled:    set of slots whose DayCompletion row says done.
    prescribed: {slot: [ {name, sets}, ... ]} — the resolved lifting
                prescription; an empty list / missing key = no lifting
                prescribed that day (rest / long-run day).
    set_rows:   {slot: [SetLog-like rows]} for the slot (callers scope by block).
    run_days:   set of slots with a logged run.

    A slot is done when ANY of:
      - it is toggled done;
      - every prescribed set is performed (workout_state_from_rows == complete);
      - no lifting is prescribed and a run is logged (a run-only day — Sunday's
        long run counts; it is not "rest").
    A lifting day where only a run was logged is NOT done (lifting skipped).
    """
    done = set()
    for slot in schedule:
        if slot in toggled:
            done.add(slot)
            continue
        rx = prescribed.get(slot) or []
        if rx:
            if workout_state_from_rows(rx, set_rows.get(slot) or []) == "complete":
                done.add(slot)
        elif slot in run_days:
            done.add(slot)
    return done


def streak_stats(schedule, done):
    """{current_streak, best_streak} over an ORDERED schedule of slots.

    current_streak anchors on the LATEST done slot (today may simply not be
    logged yet — that must not zero the streak) and counts consecutive done
    slots backwards. best_streak is the longest consecutive done run anywhere.
    """
    current = 0
    latest = -1
    for i in range(len(schedule) - 1, -1, -1):
        if schedule[i] in done:
            latest = i
            break
    if latest >= 0:
        for i in range(latest, -1, -1):
            if schedule[i] in done:
                current += 1
            else:
                break
    best = running = 0
    for slot in schedule:
        if slot in done:
            running += 1
            best = max(best, running)
        else:
            running = 0
    return {"current_streak": current, "best_streak": best}


def evidence_done_slots(user_id, block_start, slots, resolve_day):
    """S076: evidence-based done slots for `slots` (list of (week, day_idx)),
    block-scoped like the dashboard streak — toggle OR every prescribed set
    OR a run on a run-only day. `resolve_day(week, day_idx)` returns the
    resolved day dict (coach_assembler._resolve_workout_for_day). Shared by
    the dashboard and the weekly report so 'Workouts: X/Y' can't disagree
    with the streak."""
    from models import DayCompletion, SetLog, RunLog
    slots = list(slots)
    weeks = {w for w, _ in slots}
    toggled = {(d.week, d.day_idx) for d in DayCompletion.query.filter_by(user_id=user_id, done=True).all()
               if d.week in weeks}
    sq = SetLog.query.filter(SetLog.user_id == user_id, SetLog.week.in_(weeks))
    rq = RunLog.query.filter(RunLog.user_id == user_id, RunLog.week.in_(weeks))
    if block_start is not None:
        sq = sq.filter(SetLog.logged_date >= block_start)
        rq = rq.filter(RunLog.log_date >= block_start)
    set_rows = {}
    for r in sq.all():
        set_rows.setdefault((r.week, r.day_idx), []).append(r)
    run_days = {(r.week, r.day_idx) for r in rq.all() if r.week is not None and r.day_idx is not None}
    prescribed = {}
    for slot in slots:
        if slot in toggled or (slot not in set_rows and slot not in run_days):
            continue
        try:
            prescribed[slot] = (resolve_day(*slot) or {}).get("exercises") or []
        except Exception:
            prescribed[slot] = []
    return completed_day_keys(slots, toggled, prescribed, set_rows, run_days)


def aerobic_efficiency_weeks(runs, hr_lo=118, hr_hi=140):
    """S136: calendar-week (Monday-start) easy-pace-at-HR series from RunLog-
    like rows (log_date, distance_miles, duration_min, avg_hr). Distance-
    weighted pace, duration-weighted HR; weeks with no qualifying run are
    omitted. Shared by the Progress chart and the run planner's prompt."""
    from datetime import timedelta
    buckets = {}
    for r in runs:
        d = getattr(r, "log_date", None); mi = getattr(r, "distance_miles", None)
        mn = getattr(r, "duration_min", None); hr = getattr(r, "avg_hr", None)
        if not d or not mi or not mn or hr is None or mi <= 0 or mn <= 0 or not (hr_lo <= hr <= hr_hi):
            continue
        ws = d - timedelta(days=d.weekday())
        b = buckets.setdefault(ws, {"sec": 0.0, "miles": 0.0, "hr_sec": 0.0, "n": 0})
        sec = mn * 60.0
        b["sec"] += sec; b["miles"] += mi; b["hr_sec"] += hr * sec; b["n"] += 1
    out = []
    for ws in sorted(buckets):
        b = buckets[ws]
        if b["miles"] <= 0 or b["sec"] <= 0:
            continue
        out.append({"week_start": ws.isoformat(), "pace_sec_per_mi": round(b["sec"] / b["miles"]),
                    "avg_hr": round(b["hr_sec"] / b["sec"], 1), "n_runs": b["n"], "miles": round(b["miles"], 2)})
    return out
