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
    lift_unplanned: bool = False  # training day with no coach/engine prescription


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
    fasting_target_hours: Optional[int]
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
        lift_name=day.get("liftName") or "",
        exercise_names=[e.get("name", "") for e in exercises if e.get("name")],
        is_rest=False,
        lift_unplanned=bool(day.get("lift_unplanned")),
    )


def _compute_workout_status(
    user_id: int,
    week: int,
    day_idx: int,
    today_date: date,
    is_rest: bool,
) -> str:
    """Returns one of: not_started | in_progress | complete | rest.

    Rest takes precedence. Otherwise:
    - complete: DayCompletion.done (date-gated to today) for ANY (week, day_idx)
      that wrote sets today, OR the canonical name-aware check passes: every
      prescribed exercise for a slot logged today has its prescribed sets
      performed (workout_status.workout_state_from_rows). A partial log must
      NEVER read complete.
    - not_started: zero SetLog rows for today across ALL weeks.
    - in_progress: at least one SetLog row today but not a finished session.

    NOTE: query is INTENTIONALLY week-agnostic. The UI's `AppState.current_week`
    can drift from the rules engine's start_date computation (Erik's UI showed
    week 6 while rules engine computed week 5 from start_date). When the user
    logs sets, they're stored under whatever week the UI thinks it is. The
    status query must therefore look at logged_date alone — otherwise the
    coach falsely reports "Lift now" when the lift is already done.
    """
    if is_rest:
        return "rest"
    from models import SetLog, DayCompletion

    # Authoritative complete (passed week, day_idx) — DATE-GATED. Honor dc.done
    # only if it was recorded today; a stale flag from a prior cycle (week clamps
    # at 12 once the block ends) must not read "complete" today. Legacy rows have
    # null completed_at -> fall through to the date-keyed sets_today logic below.
    from utils_time import parse_completion_date
    dc = DayCompletion.query.filter_by(
        user_id=user_id, week=week, day_idx=day_idx,
    ).first()
    if dc and dc.done and parse_completion_date(dc.completed_at) == today_date:
        return "complete"

    # Any sets logged today across ANY (week, day_idx) — covers UI/engine
    # week drift (UI says wk6, engine says wk5; sets stored under wk6).
    sets_today = (SetLog.query
                  .filter_by(user_id=user_id, logged_date=today_date)
                  .all())
    if not sets_today:
        return "not_started"

    # Authoritative complete on alternate (week, day_idx) the user actually
    # logged sets to today.
    keys = {(s.week, s.day_idx) for s in sets_today}
    for w, d in keys:
        if (w, d) == (week, day_idx):
            continue  # already checked above
        dc = DayCompletion.query.filter_by(
            user_id=user_id, week=w, day_idx=d,
        ).first()
        if dc and dc.done and parse_completion_date(dc.completed_at) == today_date:
            return "complete"

    # Canonical name-aware completion (replaces the old "6+ sets / 3 done"
    # heuristic, which marked a partially-logged session complete — 7 sets into
    # a 17-set day read DONE and the coach told the athlete to move on). A slot
    # is complete only when EVERY prescribed exercise has its prescribed sets
    # performed (workout_status.workout_state_from_rows — same definition as
    # coach_assembler and app.py's auto-complete). Check each (week, day_idx)
    # slot the athlete actually logged sets to today, to tolerate UI/engine
    # week drift.
    from coach_assembler import _resolve_workout_for_day
    from workout_status import workout_state_from_rows
    slot_rows: dict = {}
    for s in sets_today:
        slot_rows.setdefault((s.week, s.day_idx), []).append(s)
    for (w, d), rows in slot_rows.items():
        resolved = _resolve_workout_for_day(w, d) or {}
        if workout_state_from_rows(resolved.get("exercises") or [], rows) == "complete":
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


def _resolve_run_for_day(week: int, day_idx: int, user_id: Optional[int] = None) -> Optional[RunSummary]:
    """Resolve the day's run for a user.

    Resolution chain (matches what api_workouts shows the UI):
      WeeklyRunPlan (per-user override) → PHASE_TEMPLATES day["run"]
    The override path is critical: users see whatever WeeklyRunPlan stores,
    so the coach must reference the same run, not the raw template. Without
    this, the coach said "Recovery jog" while the UI displayed "Tempo run".
    """
    # 1. Per-user WeeklyRunPlan — COACH-OR-NOTHING for real users: when the
    # query SUCCEEDS and finds no row, the run is NOT planned; never fall back
    # to the static template's run (the dashboard strips it as 'unplanned').
    # Only a transient query error falls through to the template path below
    # (which also serves legacy user_id=None callers/tests).
    if user_id is not None:
        try:
            from models import WeeklyRunPlan
            plan = WeeklyRunPlan.query.filter_by(
                user_id=user_id, week=week, day_idx=day_idx,
            ).first()
            if plan and plan.run_type:
                return RunSummary(
                    run_type=plan.run_type,
                    label=plan.label or plan.run_type.title(),
                    scheduled_at=None,
                    detail=plan.detail or "",
                )
            return None  # known-empty: no coach-planned run for this day
        except Exception:
            pass  # transient error only — fall through

    # 2. Template
    from workout_data import get_workouts
    days = get_workouts(week)
    if day_idx >= len(days):
        return None
    run = days[day_idx].get("run")
    if not run:
        return None
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
    (re.compile(r"\b(too sore|wiped|drained|exhausted|wrecked|beat up|wiped out|not feeling it|don't think i can|can't lift|can't run)\b", re.I),
     "somatic-complaint"),
    (re.compile(r"\b(do it tomorrow|do them tomorrow|tomorrow instead|push (it|this) to tomorrow)\b", re.I),
     "tomorrow-postponement"),
    (re.compile(r"\b(switch to (a |an )?(rest|easy|recovery)|swap to (a |an )?(rest|easy|recovery)|need (a )?break|take (a )?(break|day off|the day off))\b", re.I),
     "switch-to-rest"),
    (re.compile(r"\b(let me skip|skip just this|skip today|just rest)\b", re.I),
     "soft-skip"),
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

    # Rule 1 — refusal overrides everything. Never quote the lift name on an
    # unplanned day (it's stripped to "" — coach-or-nothing).
    if refusal_required:
        if (workout_today and not workout_today.is_rest
                and not getattr(workout_today, "lift_unplanned", False)
                and workout_today.lift_name):
            prescribed = workout_today.lift_name
        elif run_today:
            prescribed = run_today.label
        else:
            prescribed = "Recovery day"
        return Directive(
            text=f"Train as planned. {prescribed}.",
            category="refusal",
        )

    # Rule 2 — workout in progress. On an unplanned day the lift name is
    # stripped ("") — don't emit the garbled "Continue. Finish ."
    if workout_today_status == "in_progress" and workout_today:
        if workout_today.lift_name:
            return Directive(
                text=f"Continue. Finish {workout_today.lift_name}.",
                category="workout_in_progress",
            )
        return Directive(
            text="Continue. Finish the session you started.",
            category="workout_in_progress",
        )

    # Rule 3 — workout complete, run pending
    if workout_today_status == "complete" and run_today_status == "not_started" and run_today:
        return Directive(
            text=f"Run now. {run_today.label}.",
            category="workout_done_run_pending",
        )

    # Rule 3b — workout UNPLANNED: no coach prescription. Never prescribe the
    # (stripped) template lift; tell the athlete to plan the week.
    if workout_today_status == "unplanned":
        return Directive(
            text="Today's lifts aren't planned. Plan the week.",
            category="workout_unplanned",
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
            # Unplanned tomorrow: the lift name is stripped ("") — say so
            # instead of the garbled "Done. Tomorrow:  at 6 AM."
            if getattr(workout_tomorrow, "lift_unplanned", False) or not workout_tomorrow.lift_name:
                return Directive(
                    text="Done. Tomorrow isn't planned yet — plan the week.",
                    category="day_done_tomorrow_unplanned",
                )
            sched = (
                workout_tomorrow_scheduled_at.strftime("%-I:%M %p")
                if workout_tomorrow_scheduled_at else "6 AM"
            )
            run_clause = f" + {run_tomorrow.label}" if run_tomorrow else ""
            return Directive(
                text=f"Done. Tomorrow: {workout_tomorrow.lift_name} at {sched}{run_clause}.",
                category="day_done_lift_tomorrow",
            )
        if run_tomorrow:
            return Directive(
                text=f"Done. Tomorrow: rest + {run_tomorrow.label}.",
                category="day_done_rest_tomorrow",
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
            # Unplanned Monday (Erik plans week-by-week, so this is the common
            # Sunday-evening case): prompt to plan, don't emit "Monday:  at 6 AM."
            if getattr(workout_tomorrow, "lift_unplanned", False) or not workout_tomorrow.lift_name:
                return Directive(
                    text="Monday isn't planned yet. Plan the week tonight.",
                    category="sunday_eve_unplanned",
                )
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
    elif getattr(workout_today, "lift_unplanned", False):
        lines.append("Today workout: NOT PLANNED (plan the week)")
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
    elif getattr(workout_tomorrow, "lift_unplanned", False) or not workout_tomorrow.lift_name:
        lines.append("Tomorrow workout: NOT PLANNED (plan the week)")
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


def _current_week_for_user(user_id: int, today_local) -> int:
    """Return the user's current 12-week phase week from AppState.

    Calendar (start_date) is authoritative. AppState.current_week is a
    mutable field that gets bumped by various flows and has been observed
    to drift ahead of the calendar — using MAX of the two locks in the
    drift. start_date math wins; current_week is fallback only when
    start_date is missing.
    """
    from models import AppState
    state = AppState.query.filter_by(user_id=user_id).first()
    if state is None:
        return 1
    if state.start_date:
        diff_days = (today_local - state.start_date).days
        return max(1, min(12, (diff_days // 7) + 1))
    return state.current_week or 1


def _phase_summary_for_week(week: int) -> str:
    """Phase label matching workout_data.get_phase + deload semantics.
    Weeks 4 and 8 are intra-phase deload weeks; week 12 is the test/peak week."""
    if week == 12:
        return "Phase 3 / test week (week 12)"
    if week == 4:
        return "Phase 1 deload (week 4)"
    if week == 8:
        return "Phase 2 deload (week 8)"
    if week <= 4:
        return f"Phase 1 (week {week})"
    if week <= 8:
        return f"Phase 2 (week {week})"
    return f"Phase 3 (week {week})"


def compute_coach_rules(
    user_id: int,
    now: Optional[datetime] = None,
    latest_user_message: Optional[str] = None,
) -> CoachRules:
    """Top-level entry. Pure function (modulo DB reads).

    Args:
        user_id: The athlete's user ID.
        now: Override clock (UTC, tz-aware OR naive treated as UTC). Production passes None.
        latest_user_message: The user's latest chat message (for refusal scan).
    """
    now_local = _user_local_now(now)
    today = now_local.date()
    weekday_idx = now_local.weekday()  # Mon=0
    tomorrow_idx = (weekday_idx + 1) % 7
    week = _current_week_for_user(user_id, today)
    next_week = week + 1 if tomorrow_idx == 0 else week  # rolls Sunday→Monday

    # Workout today
    workout_today = _resolve_workout_for_day_summary(user_id, week, weekday_idx)
    is_rest_today = bool(workout_today and workout_today.is_rest) or workout_today is None
    workout_today_scheduled_at = _compute_workout_scheduled_at(user_id, is_rest_today)
    workout_today_status = _compute_workout_status(
        user_id, week, weekday_idx, today, is_rest_today,
    )
    # Coach-or-nothing: a training day with no prescription is UNPLANNED, not
    # 'not_started' — never prescribe the (stripped) template lift; offer to plan.
    if (workout_today and getattr(workout_today, "lift_unplanned", False)
            and not is_rest_today and workout_today_status == "not_started"):
        workout_today_status = "unplanned"

    # Workout tomorrow (clamp to week 12)
    next_week_clamped = min(12, next_week)
    workout_tomorrow = _resolve_workout_for_day_summary(user_id, next_week_clamped, tomorrow_idx)
    is_rest_tomorrow = bool(workout_tomorrow and workout_tomorrow.is_rest) or workout_tomorrow is None
    workout_tomorrow_scheduled_at = _compute_workout_scheduled_at(user_id, is_rest_tomorrow)

    # Run today / tomorrow
    run_today = _resolve_run_for_day(week, weekday_idx, user_id=user_id)
    run_today_status = _compute_run_status(user_id, today, run_planned=run_today is not None)
    run_tomorrow = _resolve_run_for_day(next_week_clamped, tomorrow_idx, user_id=user_id)

    # Fasting
    fasting = _compute_fasting_state(now_local)

    # Refusal
    refusal_required, refusal_reason = _detect_refusal(latest_user_message)

    # Directive
    directive = _compute_directive(
        now_local=now_local,
        workout_today=workout_today,
        workout_today_scheduled_at=workout_today_scheduled_at,
        workout_today_status=workout_today_status,
        run_today=run_today,
        run_today_status=run_today_status,
        workout_tomorrow=workout_tomorrow,
        workout_tomorrow_scheduled_at=workout_tomorrow_scheduled_at,
        run_tomorrow=run_tomorrow,
        fasting_active=fasting.fasting_active,
        weekend_fast_active=(fasting.fasting_active and fasting.fasting_target_hours == 40),
        is_pr_session=False,  # v1 — wire PR detection in v2
        next_target_hint=None,
        refusal_required=refusal_required,
        phase_summary=_phase_summary_for_week(week),
    )

    prefilled_schedule = _render_prefilled_schedule(
        now_local=now_local,
        workout_today=workout_today,
        workout_today_scheduled_at=workout_today_scheduled_at,
        run_today=run_today,
        workout_tomorrow=workout_tomorrow,
        workout_tomorrow_scheduled_at=workout_tomorrow_scheduled_at,
        run_tomorrow=run_tomorrow,
    )
    prefilled_directive = _render_prefilled_directive(directive)

    return CoachRules(
        now_utc=now_local.astimezone(timezone.utc),
        now_local=now_local,
        local_date_iso=now_local.strftime("%Y-%m-%d"),
        local_weekday=now_local.strftime("%A"),
        local_time_hhmm=now_local.strftime("%H:%M"),
        workout_today=workout_today,
        workout_today_scheduled_at=workout_today_scheduled_at,
        workout_today_status=workout_today_status,
        run_today=run_today,
        run_today_status=run_today_status,
        workout_tomorrow=workout_tomorrow,
        workout_tomorrow_scheduled_at=workout_tomorrow_scheduled_at,
        run_tomorrow=run_tomorrow,
        fasting_active=fasting.fasting_active,
        fasting_hours=fasting.fasting_hours,
        fasting_target_hours=fasting.fasting_target_hours,
        fasting_break_at=fasting.fasting_break_at,
        directive=directive,
        refusal_required=refusal_required,
        refusal_reason=refusal_reason,
        prefilled_schedule=prefilled_schedule,
        prefilled_directive=prefilled_directive,
    )
