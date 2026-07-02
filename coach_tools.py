"""Tools the coach can call mid-response to look up data.

Eliminates the hallucination class where the coach confidently invents
facts (e.g. "Monday is Back Squat 160×4×5" when Monday is actually Front
Squat 4×3) because the prompt didn't have the data and posture forbade
saying "I don't know."

The coach gets a small set of focused tools — workout/history/1RM/body —
calls them when needed, gets structured data back, then writes its reply.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)


# ─── Tool schemas (Anthropic format) ─────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_workout",
        "description": (
            "Get the exact prescribed workout for a specific week + day. "
            "Returns lift name, exercises (with sets/reps/target_weight/notes), "
            "and run plan. Use this whenever the athlete asks about a specific "
            "day's workout (Monday, Tuesday, tomorrow, this Friday, etc.). "
            "DO NOT guess; call this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "week": {
                    "type": "integer", "minimum": 1, "maximum": 12,
                    "description": "Program week (1-12)",
                },
                "day_idx": {
                    "type": "integer", "minimum": 0, "maximum": 6,
                    "description": "Day index: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun",
                },
            },
            "required": ["week", "day_idx"],
        },
    },
    {
        "name": "get_recent_sets",
        "description": (
            "Get the athlete's most recent logged sets for a specific exercise. "
            "Use when the athlete asks 'what did I do last [exercise]', or you "
            "need to check recent performance to suggest a weight."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string"},
                "limit": {"type": "integer", "default": 12, "minimum": 1, "maximum": 50},
            },
            "required": ["exercise_name"],
        },
    },
    {
        "name": "get_e1rm",
        "description": (
            "Get the athlete's estimated 1-rep max history for an exercise. "
            "Use when discussing strength, percentages, or progression goals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string"},
            },
            "required": ["exercise_name"],
        },
    },
    {
        "name": "get_body_state",
        "description": (
            "Get the athlete's current body weight, waist, recent body measurements, "
            "fasting state, and progress toward goal. Use for cut/recomp questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_today_status",
        "description": (
            "Summary of today: what workout/run is scheduled, what's been logged so far, "
            "what's still pending. Use for 'where am I today' / 'what's left' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "consult_nutritionist",
        "description": (
            "Consult the Nutritionist specialist. Use when the question "
            "involves macros, fasting, refeeds, glycogen, deficit math, "
            "electrolytes, supplement timing, or interpreting body weight "
            "trends. Brief should be 1-3 sentences naming the question + "
            "any cross-cutting context (e.g., 'athlete is week 6 of 12-wk "
            "cut, 207→185 target')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "description": "Focused question + context"},
            },
            "required": ["brief"],
        },
    },
    {
        "name": "consult_strength",
        "description": (
            "Consult the Strength Coach specialist. Use for lift "
            "programming, RPE-based autoregulation, swap logic, weight "
            "selection, deload calls, progression-in-deficit decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
            },
            "required": ["brief"],
        },
    },
    {
        "name": "consult_running",
        "description": (
            "Consult the Running Coach specialist. Use for run "
            "prescription, pace zones, fasted-run feasibility, "
            "long-run pacing, recovery-based intensity adjustments, "
            "ultra-specific concerns (50k preparation)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
            },
            "required": ["brief"],
        },
    },
]


# ─── Executors ───────────────────────────────────────────────────────────────


def _tool_get_workout(user_id: int, week: int, day_idx: int) -> str:
    """Resolve the day through the same chain as api_workouts, with the
    user's actual WeeklyRunPlan layered over the template's default run.
    """
    from coach_assembler import _resolve_workout_for_day
    from models import WeeklyRunPlan
    day = _resolve_workout_for_day(week, day_idx)
    if day is None:
        return json.dumps({
            "error": f"No data for week {week} day_idx {day_idx}",
            "user_id_arg": user_id,
        })

    # Overlay user's actual run from WeeklyRunPlan (template's run is just
    # default program guidance — user's plan can have a different run).
    template_run = day.get("run")
    user_run_row = WeeklyRunPlan.query.filter_by(
        user_id=user_id, week=week, day_idx=day_idx,
    ).first()
    if user_run_row and user_run_row.run_type:
        actual_run = {
            "type": user_run_row.run_type,
            "label": user_run_row.label,
            "duration": user_run_row.duration,
            "detail": user_run_row.detail,
            "source": user_run_row.source,
        }
    else:
        actual_run = template_run

    out = {
        "week": week,
        "day_idx": day_idx,
        "day_name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day_idx],
        "lift_name": day.get("liftName"),
        "is_rest": bool(day.get("isRest")),
        "exercises": [
            {
                "name": e.get("name"),
                "sets": e.get("sets"),
                "rest": e.get("rest"),
                "target_weight": e.get("target_weight"),
                "note": e.get("note"),
            }
            for e in (day.get("exercises") or [])
        ],
        "run": actual_run,
        "template_run": template_run if actual_run is not template_run else None,
        "notes": day.get("notes"),
        "_notes_caveat": (
            "The 'notes' field is program-default guidance and may not apply if "
            "the user's actual run (above) differs from template_run. "
            "Always cite the user's actual run, not the template note."
        ),
    }
    return json.dumps(out, default=str)


def _tool_get_recent_sets(user_id: int, exercise_name: str, limit: int = 12) -> str:
    """Look up recent SetLog rows for an exercise. Tries an exact-name match
    first; if that comes back empty, falls back to a case-insensitive
    substring match so the coach asking for 'Front Squat' still finds rows
    logged as 'Barbell Front Squat' (or vice versa) — exercise naming has
    drifted over the program's history and exact match was missing real data.
    """
    from models import SetLog
    base = SetLog.query.filter(
        SetLog.user_id == user_id, SetLog.done.is_(True),
    )
    rows = (base
            .filter(SetLog.exercise_name == exercise_name)
            .order_by(SetLog.logged_date.desc(), SetLog.set_number.asc())
            .limit(int(limit))
            .all())
    matched_name = exercise_name
    if not rows:
        rows = (base
                .filter(SetLog.exercise_name.ilike(f"%{exercise_name}%"))
                .order_by(SetLog.logged_date.desc(), SetLog.set_number.asc())
                .limit(int(limit))
                .all())
        if rows:
            # Use the first row's actual name so the coach sees what was logged.
            matched_name = rows[0].exercise_name
    if not rows:
        # Movement-key fallback: substring ilike is asymmetric — a longer query
        # name isn't a substring of a shorter logged name, so "Barbell Bench Press"
        # missed logged "DB Bench Press" and the coach hallucinated "no bench
        # logged" (judge prog_001). Match equipment variants by canonical movement.
        try:
            from coach_planning_program import _movement_key
            target_key = _movement_key(exercise_name)
            if target_key:
                names = [n for (n,) in base.with_entities(SetLog.exercise_name).distinct().all()]
                variants = [n for n in names if _movement_key(n) == target_key]
                if variants:
                    rows = (base
                            .filter(SetLog.exercise_name.in_(variants))
                            .order_by(SetLog.logged_date.desc(), SetLog.set_number.asc())
                            .limit(int(limit))
                            .all())
                    if rows:
                        matched_name = rows[0].exercise_name
        except Exception:
            pass
    if not rows:
        return json.dumps({
            "exercise": exercise_name,
            "sets": [],
            "note": f"No logged sets found for {exercise_name!r}.",
        })
    return json.dumps({
        "exercise": matched_name,
        "queried_as": exercise_name,
        "sets": [
            {
                "date": str(r.logged_date),
                "week": r.week,
                "day_idx": r.day_idx,
                "set": r.set_number,
                "weight": r.weight,
                "reps": r.reps,
            }
            for r in rows
        ],
    }, default=str)


def _tool_get_e1rm(user_id: int, exercise_name: str) -> str:
    """Estimated-1RM history from SetLog (the live table), not the dead
    ExerciseLog. e1RM is the Epley estimate of each session's top set. Matches
    equipment variants by movement (a logged 'DB Bench Press' answers a query for
    'Barbell Bench Press') so real history isn't hidden behind the equipment name.
    """
    from lift_history import lift_session_history
    hist = lift_session_history(user_id, exercise_name, limit_sessions=20)
    hist = [h for h in hist if h["e1rm"] is not None]
    if not hist:
        return json.dumps({
            "exercise": exercise_name,
            "e1rm_history": [],
            "note": f"No e1RM history for {exercise_name!r}.",
        })
    return json.dumps({
        "exercise": hist[-1]["exercise_name"],
        "queried_as": exercise_name,
        "current": hist[-1]["e1rm"],
        "e1rm_history": [
            {"date": str(h["date"]), "e1rm": h["e1rm"],
             "top_set": f"{h['top_weight']:g}x{h['top_reps']}"}
            for h in hist
        ],
    }, default=str)


def _tool_get_body_state(user_id: int) -> str:
    from models import BodyWeight, BodyMeasurement, TrainingGoal
    bw = (BodyWeight.query
          .filter_by(user_id=user_id)
          .order_by(BodyWeight.log_date.desc())
          .limit(14).all())
    measurements = (BodyMeasurement.query
                    .filter_by(user_id=user_id)
                    .order_by(BodyMeasurement.log_date.desc())
                    .limit(8).all())
    goal = TrainingGoal.query.filter_by(user_id=user_id).first()
    return json.dumps({
        "recent_weights": [
            {"date": str(b.log_date), "lbs": b.weight_lbs}
            for b in bw
        ],
        "recent_measurements": [
            {"date": str(m.log_date), "waist": m.waist_inches,
             "weight_lbs": m.weight_lbs}
            for m in measurements
        ],
        "goal": {
            "target_weight": goal.target_weight if goal else None,
            "goal_type": goal.goal_type if goal else None,
            "daily_calories": goal.daily_calories if goal else None,
            "fasting_protocol": goal.fasting_protocol if goal else None,
        } if goal else None,
    }, default=str)


def _user_local_today(user_id: int):
    """Today's date in THIS user's local timezone — never server-UTC.

    SetLog.logged_date / RunLog.log_date are written with the user-local date
    (app._user_today), so querying them with server-UTC date.today() made the
    coach see an empty/wrong 'today' every evening (on Render, UTC rolls over
    at ~4-5 PM PT). Tools get a user_id, not a request context, so this
    resolves the timezone from the User row instead of current_user.
    """
    from datetime import date as _date
    try:
        from models import User
        from utils_time import user_local_today
        u = User.query.get(user_id)
        tz = getattr(u, "timezone", None) if u else None
        return user_local_today(tz or "UTC")
    except Exception:
        return _date.today()


def _tool_get_today_status(user_id: int) -> str:
    from models import SetLog, RunLog, DayCompletion
    today = _user_local_today(user_id)
    sets_today = SetLog.query.filter_by(
        user_id=user_id, logged_date=today,
    ).all()
    runs_today = RunLog.query.filter_by(
        user_id=user_id, log_date=today,
    ).all()
    # Aggregate by exercise
    by_ex: dict = {}
    for s in sets_today:
        d = by_ex.setdefault(s.exercise_name, {
            "sets": 0, "done": 0, "top_weight": 0, "reps_seq": [],
        })
        d["sets"] += 1
        if s.done:
            d["done"] += 1
        if s.weight and s.weight > d["top_weight"]:
            d["top_weight"] = s.weight
        d["reps_seq"].append(s.reps)
    return json.dumps({
        "date": str(today),
        "weekday": today.strftime("%A"),
        "logged_exercises": by_ex,
        "runs_logged": [
            {"distance_miles": r.distance_miles, "avg_hr": r.avg_hr,
             "duration_min": r.duration_min, "notes": r.notes}
            for r in runs_today
        ],
        "day_completions_today": [
            {"week": dc.week, "day_idx": dc.day_idx, "done": dc.done}
            for dc in DayCompletion.query.filter_by(user_id=user_id).all()
            if (dc.workout_started_at or "")[:10] == str(today)
            or (dc.workout_ended_at or "")[:10] == str(today)
        ],
    }, default=str)


def _tool_consult_nutritionist(user_id: int, brief: str) -> str:
    from coach_specialists.nutritionist import consult
    return consult(brief=brief, user_id=user_id)


def _tool_consult_strength(user_id: int, brief: str) -> str:
    from coach_specialists.strength import consult
    return consult(brief=brief, user_id=user_id)


def _tool_consult_running(user_id: int, brief: str) -> str:
    from coach_specialists.running import consult
    return consult(brief=brief, user_id=user_id)


_DISPATCH = {
    "get_workout": _tool_get_workout,
    "get_recent_sets": _tool_get_recent_sets,
    "get_e1rm": _tool_get_e1rm,
    "get_body_state": _tool_get_body_state,
    "get_today_status": _tool_get_today_status,
    "consult_nutritionist": _tool_consult_nutritionist,
    "consult_strength": _tool_consult_strength,
    "consult_running": _tool_consult_running,
}


def execute_tool(tool_name: str, tool_input: dict, user_id: int) -> str:
    """Run a tool. Always returns a JSON string (never raises)."""
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool {tool_name!r}"})
    try:
        return fn(user_id=user_id, **tool_input)
    except Exception as e:
        log.warning("Tool %s failed: %s", tool_name, e, exc_info=True)
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
