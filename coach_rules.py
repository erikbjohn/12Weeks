"""Coach rules engine.

Pure function (user_id, now, latest_user_message) -> CoachRules.

No LLM. No external I/O beyond DB reads. Deterministic, fast.
The output is the *facts* the coach speaks — schedule, directive,
time, refusal triggers. The LLM only authors voice on top of these.

This eliminates the failure modes documented in
docs/superpowers/research/2026-04-30-coach-audit.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_WORKOUT_TIME = dtime(6, 0)   # Erik's AM-stacked default


def _user_local_now(now: Optional[datetime] = None) -> datetime:
    """Return Pacific-local time. Pass `now` (UTC, tz-aware) to override
    for testing. The override path is the only way the rules engine
    ever sees a non-real clock — production never passes `now`."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(PACIFIC)


@dataclass(frozen=True)
class WorkoutSummary:
    lift_name: str
    exercise_names: list[str]
    is_rest: bool


@dataclass(frozen=True)
class RunSummary:
    run_type: str          # "z2" | "hiit" | "z2_long"
    label: str             # human-facing, e.g. "Z2 30 min" or "HIIT 6x400m"
    scheduled_at: Optional[dtime]
    detail: str


@dataclass(frozen=True)
class Directive:
    text: str
    category: str          # rule key from the directive table for telemetry


@dataclass(frozen=True)
class CoachRules:
    now_utc: datetime
    now_local: datetime
    local_date_iso: str
    local_weekday: str
    local_time_hhmm: str

    workout_today: Optional[WorkoutSummary]
    workout_today_scheduled_at: Optional[dtime]
    workout_today_status: str           # "not_started" | "in_progress" | "complete" | "rest"

    run_today: Optional[RunSummary]
    run_today_status: str               # "not_started" | "logged" | "skipped" | "rest"

    workout_tomorrow: Optional[WorkoutSummary]
    workout_tomorrow_scheduled_at: Optional[dtime]
    run_tomorrow: Optional[RunSummary]

    fasting_active: bool
    fasting_hours: Optional[float]
    fasting_target_hours: Optional[float]
    fasting_break_at: Optional[datetime]

    directive: Directive
    refusal_required: bool
    refusal_reason: Optional[str]

    prefilled_schedule: str             # Rendered <schedule>...</schedule>
    prefilled_directive: str            # Rendered <directive>...</directive>


def _resolve_workout_for_day_summary(user_id: int, week: int, day_idx: int) -> Optional[WorkoutSummary]:
    """Resolve the user's workout for (week, day_idx) through the same chain
    as api_workouts: PHASE_TEMPLATES → WeeklyPrescription → auto_swap → ExerciseSwap.

    Returns a lean WorkoutSummary (lift_name + exercise names), or None if the
    week/day cannot be resolved at all. Returns is_rest=True with empty exercises
    for rest days.

    NOTE: `user_id` is currently unused — the underlying
    `coach_assembler._resolve_workout_for_day` reads `current_user` from
    Flask-Login. Callers MUST establish an authenticated session (e.g.
    `login_user(user, force=True)` inside a `test_request_context`) for
    this function to return that user's data. The `user_id` parameter is
    kept in the signature so callers can be explicit about whose data is
    being requested, anticipating a future decoupling."""
    from coach_assembler import _resolve_workout_for_day
    day = _resolve_workout_for_day(week, day_idx)
    if day is None:
        return None
    if day.get("isRest"):
        return WorkoutSummary(
            lift_name=day.get("liftName", "Rest"),
            exercise_names=[],
            is_rest=True,
        )
    exercises = day.get("exercises", []) or []
    return WorkoutSummary(
        lift_name=day.get("liftName", ""),
        exercise_names=[e.get("name", "") for e in exercises if e.get("name")],
        is_rest=False,
    )


def _compute_workout_status(
    user_id: int,
    week: int,
    day_idx: int,
    today_date: date,
    is_rest: bool,
) -> str:
    """Returns one of: not_started | in_progress | complete | rest.

    Rest takes precedence. For non-rest days:
    - not_started: zero SetLog rows for this user/week/day_idx today.
    - in_progress: at least one SetLog row today, but not all configured sets done.
    - complete: every prescribed set has done=True.
    """
    if is_rest:
        return "rest"
    from models import SetLog
    sets_today = SetLog.query.filter_by(
        user_id=user_id, week=week, day_idx=day_idx,
        logged_date=today_date,
    ).all()
    if not sets_today:
        return "not_started"
    done_count = sum(1 for s in sets_today if s.done)
    # If any logged sets exist but not all done → in_progress.
    # We don't try to compute the "expected total" precisely — coach treats
    # any logged-but-incomplete session as in_progress.
    if done_count == 0:
        return "in_progress"
    # Heuristic: if the user logged any sets and stopped, treat as in_progress
    # unless the day's known exercise count appears all-completed. Keep it
    # simple — engine and api_workouts are the source of truth for "complete";
    # rules engine just needs a 4-bucket signal.
    if done_count >= len(sets_today):
        return "complete"
    return "in_progress"


def _compute_workout_scheduled_at(user_id: int, is_rest: bool) -> Optional[dtime]:
    """Return the user's preferred workout time for the day, or None on rest.

    v1: hardcoded 6 AM default. UserPreferences override deferred to v2 —
    no users have a different preference today.

    NOTE: `user_id` is currently unused — all users get the same default.
    Kept in the signature for consistency with _compute_workout_status and
    to anticipate per-user preferences in v2.
    """
    if is_rest:
        return None
    return DEFAULT_WORKOUT_TIME


def _resolve_run_for_day(week: int, day_idx: int) -> Optional[RunSummary]:
    """Read the day's run dict from PHASE_TEMPLATES and project to RunSummary.

    Run dict shape: {"type": "z2"|"hiit"|"z2_long", "label": str,
                    "time": str, "detail": str}. None if no run scheduled.
    """
    from workout_data import get_workouts
    days = get_workouts(week)
    if day_idx >= len(days):
        return None
    run = days[day_idx].get("run")
    if not run:
        return None
    # Time may be e.g. "6:45 AM" — parse loosely; rules engine only needs a dtime.
    scheduled_at: Optional[dtime] = None
    raw_time = run.get("time", "")
    if raw_time:
        scheduled_at = _parse_time_loose(raw_time)
    return RunSummary(
        run_type=run.get("type", "z2"),
        label=run.get("label", ""),
        scheduled_at=scheduled_at,
        detail=run.get("detail", ""),
    )


def _parse_time_loose(raw: str) -> Optional[dtime]:
    """Parse loose time strings like '6:45 AM' or '6 AM' or '06:45'.
    Returns None if unparseable — rules engine treats None as 'unscheduled'."""
    import re
    s = raw.strip().upper()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", s)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2) or 0)
    suffix = m.group(3)
    if suffix == "PM" and h < 12:
        h += 12
    if suffix == "AM" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mm < 60):
        return None
    return dtime(h, mm)


def _compute_run_status(user_id: int, today_date: date, run_planned: bool) -> str:
    """Returns one of: not_started | logged | skipped | rest.

    rest: no run planned for today.
    not_started: run planned, no RunLog for today.
    logged: RunLog row exists for today.
    skipped: not used in v1 — would require explicit skip signal.
    """
    if not run_planned:
        return "rest"
    from models import RunLog
    log = RunLog.query.filter_by(
        user_id=user_id, log_date=today_date,
    ).first()
    return "logged" if log else "not_started"
