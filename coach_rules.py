"""Coach rules engine.

Pure function (user_id, now, latest_user_message) -> CoachRules.

No LLM. No external I/O beyond DB reads. Deterministic, fast.
The output is the *facts* the coach speaks — schedule, directive,
time, refusal triggers. The LLM only authors voice on top of these.

This eliminates the failure modes documented in
docs/superpowers/research/2026-04-30-coach-audit.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import NamedTuple, Optional
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


class FastingState(NamedTuple):
    fasting_active: bool
    fasting_hours: Optional[float]
    fasting_target_hours: Optional[int]
    fasting_break_at: Optional[datetime]


# Erik's fixed protocol — codified here. If we add per-user protocols later,
# move these to UserPreferences and pass them into compute_coach_rules.
EATING_WINDOW_START = dtime(11, 0)   # 11 AM
EATING_WINDOW_END = dtime(19, 0)     # 7 PM
WEEKEND_FAST_START_DAY = 5            # Saturday (Mon=0)
WEEKEND_FAST_START_TIME = dtime(19, 0)
WEEKEND_FAST_BREAK_DAY = 0            # Monday
WEEKEND_FAST_BREAK_TIME = dtime(11, 0)


def _compute_fasting_state(now_local: datetime) -> FastingState:
    """Compute current fasting state from local time alone.

    Protocol:
    - Mon 11 AM through Sat 7 PM: 16:8 IF — eat 11 AM to 7 PM, fast 7 PM to 11 AM.
    - Sat 7 PM through Mon 11 AM: 40-hour weekend fast.
    """
    weekday = now_local.weekday()
    today = now_local.date()
    t = now_local.time()

    weekend_start = datetime.combine(
        today - timedelta(days=(weekday - WEEKEND_FAST_START_DAY) % 7),
        WEEKEND_FAST_START_TIME,
        tzinfo=PACIFIC,
    )
    weekend_break = weekend_start + timedelta(hours=40)

    # Are we inside the weekend fast window?
    if weekend_start <= now_local < weekend_break:
        hours = (now_local - weekend_start).total_seconds() / 3600.0
        return FastingState(
            fasting_active=True,
            fasting_hours=round(hours, 2),
            fasting_target_hours=40,
            fasting_break_at=weekend_break,
        )

    # Inside weekday eating window?
    if EATING_WINDOW_START <= t < EATING_WINDOW_END:
        return FastingState(
            fasting_active=False,
            fasting_hours=None,
            fasting_target_hours=None,
            fasting_break_at=None,
        )

    # Otherwise: in 16:8 IF fast.
    if t >= EATING_WINDOW_END:
        # Fast started today at 7 PM
        fast_start = datetime.combine(today, EATING_WINDOW_END, tzinfo=PACIFIC)
        break_at = datetime.combine(today + timedelta(days=1), EATING_WINDOW_START, tzinfo=PACIFIC)
    else:
        # Fast started yesterday at 7 PM
        fast_start = datetime.combine(today - timedelta(days=1), EATING_WINDOW_END, tzinfo=PACIFIC)
        break_at = datetime.combine(today, EATING_WINDOW_START, tzinfo=PACIFIC)

    hours = (now_local - fast_start).total_seconds() / 3600.0
    return FastingState(
        fasting_active=True,
        fasting_hours=round(hours, 2),
        fasting_target_hours=16,
        fasting_break_at=break_at,
    )


# Each pattern is a (regex, reason) tuple. Order matters — first match wins.
_REFUSAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(skip|skipping|skipped)\b.*\b(lift|workout|run|train)", re.I),
     "future-tense skip request"),
    (re.compile(r"\b(rest|resting|take it easy|easy day)\b.*\b(today|tomorrow|tonight)\b", re.I),
     "rest/easy-day request"),
    (re.compile(r"\b(can|could|should)\s+i\b.*\b(rest|skip|wait|delay)\b", re.I),
     "permission-to-skip"),
    (re.compile(r"\b(later|tonight|tomorrow|move it|push it|reschedule)\b.*\b(workout|run|lift|session)\b", re.I),
     "time-renegotiation"),
    (re.compile(r"\b(do i (really )?have to|do i need to|is it ok to skip)\b", re.I),
     "questioning-prescription"),
    (re.compile(r"\bshould i\b.*\b(lift|run|train|workout|do it)\b", re.I),
     "should-i-asking"),
    (re.compile(r"\bjust (do|skip)\b.*\b(the run|the lift|today|tomorrow)\b", re.I),
     "partial-compliance proposal"),
    (re.compile(r"\bmaybe i('ll| will)\b.*\b(skip|rest|just)\b", re.I),
     "soft-future skip"),
    (re.compile(r"\b(what about|how about)\b.*\b(later|tonight|tomorrow|after work|this evening|the morning)\b.*\binstead\b", re.I),
     "what-about renegotiation"),
]


def _detect_refusal(latest_user_message: Optional[str]) -> tuple[bool, Optional[str]]:
    """Scan the latest user message for refusal/renegotiation patterns.

    Returns (triggered, reason). The reason is logged for telemetry and
    fed back to the LLM in the <refusal> section of the prompt.
    """
    if not latest_user_message:
        return (False, None)
    for pattern, reason in _REFUSAL_PATTERNS:
        if pattern.search(latest_user_message):
            return (True, reason)
    return (False, None)


WORKOUT_WINDOW_HOURS = 2  # ±2h around scheduled time = "in window"


def _in_workout_window(now_local: datetime, scheduled_at: Optional[dtime]) -> str:
    """Return 'before' | 'in' | 'after' relative to ±2h window."""
    if scheduled_at is None:
        return "in"
    sched_dt = datetime.combine(now_local.date(), scheduled_at, tzinfo=PACIFIC)
    delta = (now_local - sched_dt).total_seconds() / 3600.0
    if delta < -WORKOUT_WINDOW_HOURS:
        return "before"
    if delta > WORKOUT_WINDOW_HOURS:
        return "after"
    return "in"


def _compute_directive(
    *,
    now_local: datetime,
    workout_today: Optional[WorkoutSummary],
    workout_today_scheduled_at: Optional[dtime],
    workout_today_status: str,
    run_today: Optional[RunSummary],
    run_today_status: str,
    workout_tomorrow: Optional[WorkoutSummary],
    workout_tomorrow_scheduled_at: Optional[dtime],
    run_tomorrow: Optional[RunSummary],
    fasting_active: bool,
    weekend_fast_active: bool,
    is_pr_session: bool,
    next_target_hint: Optional[str],
    refusal_required: bool,
    phase_summary: str,
) -> Directive:
    """The 15-rule directive table from the spec. First match wins."""

    # Rule 1 — refusal overrides everything
    if refusal_required:
        prescribed = (
            workout_today.lift_name if workout_today and not workout_today.is_rest
            else (run_today.label if run_today else "Recovery day")
        )
        return Directive(
            text=f"Train as planned. {prescribed}.",
            category="refusal",
        )

    # Rule 2 — workout in progress
    if workout_today_status == "in_progress" and workout_today:
        return Directive(
            text=f"Continue. Finish {workout_today.lift_name}.",
            category="workout_in_progress",
        )

    # Rule 3 — workout complete, run pending
    if workout_today_status == "complete" and run_today_status == "not_started" and run_today:
        return Directive(
            text=f"Run now. {run_today.label}.",
            category="workout_done_run_pending",
        )

    # Rule 4 — workout pending, in window
    if workout_today_status == "not_started" and workout_today and not workout_today.is_rest:
        window = _in_workout_window(now_local, workout_today_scheduled_at)
        if window == "in":
            return Directive(
                text=f"Lift now. {workout_today.lift_name}.",
                category="workout_in_window",
            )
        # Rule 5 — before window
        if window == "before":
            sched = workout_today_scheduled_at.strftime("%-I:%M %p") if workout_today_scheduled_at else ""
            return Directive(
                text=f"Lift at {sched}. {workout_today.lift_name}.",
                category="workout_before_window",
            )
        # Rule 6 — after window (missed)
        sched = workout_today_scheduled_at.strftime("%-I:%M %p") if workout_today_scheduled_at else ""
        return Directive(
            text=f"Missed the {sched} window. Lift now or move to evening. Log it.",
            category="workout_missed_window",
        )

    # Rule 7 — Sunday long run pending
    if (
        run_today
        and run_today.run_type == "z2_long"
        and run_today_status == "not_started"
    ):
        return Directive(
            text=f"Sunday long run. {run_today.label}. Fasted.",
            category="sunday_long_run",
        )

    # Rule 8 — generic run pending (non-Sunday)
    if (
        run_today
        and run_today_status == "not_started"
        and (workout_today is None or workout_today.is_rest)
    ):
        sched = (
            run_today.scheduled_at.strftime("%-I:%M %p")
            if run_today.scheduled_at else ""
        )
        suffix = f" at {sched}" if sched else ""
        return Directive(
            text=f"Run today. {run_today.label}{suffix}.",
            category="run_pending",
        )

    # Rule 11 — both complete (subsumes rule 9)
    if (
        (workout_today_status in ("complete", "rest"))
        and (run_today_status in ("logged", "rest"))
        and (workout_today_status == "complete" or run_today_status == "logged")
    ):
        if workout_tomorrow and not workout_tomorrow.is_rest:
            sched = (
                workout_tomorrow_scheduled_at.strftime("%-I:%M %p")
                if workout_tomorrow_scheduled_at else "6 AM"
            )
            return Directive(
                text=f"Done. Tomorrow: {workout_tomorrow.lift_name} at {sched}.",
                category="day_done_lift_tomorrow",
            )
        return Directive(text="Done. Recovery day tomorrow.", category="day_done_rest_tomorrow")

    # Rule 12 — weekend fast active
    if weekend_fast_active:
        return Directive(
            text="Fast holds. Break Monday 11 AM.",
            category="weekend_fast",
        )

    # Rule 13 — Sunday evening planning (only if no run pending — rule 7 caught that)
    if now_local.weekday() == 6 and now_local.hour >= 18:  # Sunday 6 PM+
        if workout_tomorrow and not workout_tomorrow.is_rest:
            sched = (
                workout_tomorrow_scheduled_at.strftime("%-I:%M %p")
                if workout_tomorrow_scheduled_at else "6 AM"
            )
            return Directive(
                text=f"Monday: {workout_tomorrow.lift_name} at {sched}. Be on the platform.",
                category="sunday_eve_plan",
            )

    # Rule 14 — PR / weight bump cue
    if is_pr_session and next_target_hint:
        return Directive(
            text=f"PR logged. Next session: {next_target_hint}.",
            category="pr_logged",
        )

    # Rule 10 — recovery day fallback
    if (
        (workout_today is None or workout_today.is_rest)
        and (run_today is None)
    ):
        return Directive(
            text="Recovery day. Eat clean, sleep early.",
            category="recovery",
        )

    # Rule 15 — generic chat
    return Directive(
        text=f"{phase_summary}. Stay on plan.",
        category="generic_chat",
    )


def _render_prefilled_schedule(
    *,
    now_local: datetime,
    workout_today: Optional[WorkoutSummary],
    workout_today_scheduled_at: Optional[dtime],
    run_today: Optional[RunSummary],
    workout_tomorrow: Optional[WorkoutSummary],
    workout_tomorrow_scheduled_at: Optional[dtime],
    run_tomorrow: Optional[RunSummary],
) -> str:
    """Build the <schedule>...</schedule> block. Echoed byte-identical
    by the LLM. Validator rejects any drift."""
    lines = ["<schedule>"]
    weekday = now_local.strftime("%A")
    date_str = now_local.strftime("%Y-%m-%d")
    time_str = now_local.strftime("%H:%M")
    lines.append(f"Now: {weekday} {date_str} {time_str} Pacific")

    if workout_today is None:
        lines.append("Today workout: (none)")
    elif workout_today.is_rest:
        lines.append("Today workout: REST")
    else:
        sched = workout_today_scheduled_at.strftime("%H:%M") if workout_today_scheduled_at else "(unscheduled)"
        lines.append(f"Today workout: {workout_today.lift_name} at {sched}")

    if run_today is None:
        lines.append("Today run: (none)")
    else:
        sched = run_today.scheduled_at.strftime("%H:%M") if run_today.scheduled_at else "(unscheduled)"
        lines.append(f"Today run: {run_today.label} at {sched}")

    if workout_tomorrow is None:
        lines.append("Tomorrow workout: (none)")
    elif workout_tomorrow.is_rest:
        lines.append("Tomorrow workout: REST")
    else:
        sched = workout_tomorrow_scheduled_at.strftime("%H:%M") if workout_tomorrow_scheduled_at else "(unscheduled)"
        lines.append(f"Tomorrow workout: {workout_tomorrow.lift_name} at {sched}")

    if run_tomorrow is None:
        lines.append("Tomorrow run: (none)")
    else:
        sched = run_tomorrow.scheduled_at.strftime("%H:%M") if run_tomorrow.scheduled_at else "(unscheduled)"
        lines.append(f"Tomorrow run: {run_tomorrow.label} at {sched}")

    lines.append("</schedule>")
    return "\n".join(lines)


def _render_prefilled_directive(directive: Directive) -> str:
    """Build the <directive>...</directive> block on a single line."""
    return f"<directive>{directive.text}</directive>"
