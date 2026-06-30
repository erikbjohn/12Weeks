"""Per-lift session history computed from SetLog — the LIVE logging table.

The app half-migrated logging from ExerciseLog (per-exercise summary, written by
the old /api/log endpoint) to SetLog (per-set, written by /api/sets). The UI moved
to /api/sets ~April 2026, so ExerciseLog went stale while many readers (dashboard
charts, e1RM, weekly reports, coach tools) still query it — showing the athlete
empty/stale progress. This module is the single source of truth those readers
should use instead.

Equipment variants of the same lift are matched by movement key, so logged
"DB Bench Press" answers a query for "Barbell Bench Press"/"Bench Press" (exact-
name matching previously hid real data behind the equipment qualifier).
"""
from datetime import date


def lift_session_history(user_id, exercise_name, limit_sessions=None,
                         by_movement=True):
    """Chronological per-SESSION top-set history for a lift from SetLog.

    Returns a list (oldest first) of dicts:
      {date, week, day_idx, top_weight, top_reps, sets, e1rm, exercise_name}
    where top_weight/top_reps are the session's heaviest working set and e1rm is
    the Epley estimate. `limit_sessions` keeps the most recent N. `by_movement`
    matches equipment variants (DB/Barbell/etc.) of the same movement.
    """
    from models import SetLog
    from workout_data import resolve_name
    try:
        from coach_planning_program import _movement_key
    except Exception:  # pragma: no cover - fallback if import graph changes
        _movement_key = None

    rows = (SetLog.query
            .filter(SetLog.user_id == user_id, SetLog.weight.isnot(None))
            .all())

    if by_movement and _movement_key is not None:
        target = _movement_key(exercise_name)

        def _match(n):
            return _movement_key(n) == target
    else:
        target = resolve_name(exercise_name)

        def _match(n):
            return resolve_name(n) == target

    sessions = {}
    for s in rows:
        if not _match(s.exercise_name):
            continue
        skey = (s.week, s.day_idx, s.logged_date)
        e = sessions.get(skey)
        if e is None:
            e = {"date": s.logged_date, "week": s.week, "day_idx": s.day_idx,
                 "top_weight": 0.0, "top_reps": None, "sets": 0,
                 "exercise_name": s.exercise_name}
            sessions[skey] = e
        e["sets"] += 1
        if s.weight is not None and s.weight > e["top_weight"]:
            e["top_weight"] = s.weight
            e["top_reps"] = s.reps
            e["exercise_name"] = s.exercise_name

    out = sorted(sessions.values(),
                 key=lambda x: (x["date"] or date.min, x["week"] or 0, x["day_idx"] or 0))
    for e in out:
        tw, tr = e["top_weight"], e["top_reps"] or 0
        e["e1rm"] = round(tw * (1 + tr / 30.0), 1) if tw else None
    if limit_sessions:
        out = out[-int(limit_sessions):]
    return out
