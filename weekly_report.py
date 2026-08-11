"""Weekly progress report — computed metrics + Claude narrative."""

import os
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

CLAUDE_OPUS = "claude-opus-4-20250514"

REPORT_PROMPT = """You are Erik — high-performance coach. Lombardi voice. Direct. Invested. Blunt. Never cruel.

Write a 3-5 sentence weekly review for your athlete. Address them as "you." Reference specific numbers from the data below. Structure:
1. Lead with the headline (weight trend, PR, or adherence)
2. One thing they did well — be specific
3. One thing that needs work — be honest
4. Set up the coming week — one sentence of forward momentum

No fluff. No generic motivation. Use their actual numbers."""


def compute_week_wellness(week_num, user_id, today=None):
    """Wellness (RHR/HRV/sleep) for a SPECIFIC report week — anchored on
    AppState.start_date so "week N" always maps to the same calendar week
    the coach/UI show, never "today" (a report for week 3 run in week 9
    must still describe week 3's dates). Block starts are always Mondays
    by transition design, so week_monday is genuinely that week's Monday.

    This is the ONE shared path for "what did week N's wellness look
    like" — used by compute_weekly_metrics (persisted at generate-time)
    AND by GET /api/weekly-report/<week> (recomputed at read-time, since
    WeeklyReport has no wellness column and GarminWellness rows are
    immutable per-date, so recomputing is stable and avoids a migration
    for a value that's always re-derivable from the same source rows).
    """
    from models import AppState, GarminWellness
    from coach_assembler import wellness_trends

    today = today or date.today()
    wellness_window = None
    if user_id is not None:
        state = AppState.query.filter_by(user_id=user_id).first()
        if state and state.start_date:
            week_monday = state.start_date + timedelta(days=(week_num - 1) * 7)
            wellness_window = (week_monday, week_monday + timedelta(days=6))
    wellness_rows = (
        GarminWellness.query.filter_by(user_id=user_id).all()
        if user_id is not None else []
    )
    return wellness_trends(wellness_rows, today, window=wellness_window)


def compute_weekly_metrics(week_num, user_id=None):
    """Compute all metrics for a given week. Returns dict."""
    from models import (
        db, DayCompletion, ExerciseLog, BodyWeight,
        MorningCheckIn, MealLog, TrainingGoal,
    )

    today = date.today()
    # Approximate week boundaries (week_num weeks ago from program start)
    # For simplicity, use the last 7 days ending today (for current week)
    week_end = today
    week_start = today - timedelta(days=6)

    # Workouts completed
    q = DayCompletion.query.filter(
        DayCompletion.done == True,
        DayCompletion.week == week_num,
    )
    if user_id is not None:
        q = q.filter(DayCompletion.user_id == user_id)
    completions = q.count()

    # Weight trend
    q = BodyWeight.query.filter(
        BodyWeight.log_date >= week_start,
        BodyWeight.log_date <= week_end,
    )
    if user_id is not None:
        q = q.filter(BodyWeight.user_id == user_id)
    weights = q.order_by(BodyWeight.log_date).all()

    weight_start = weights[0].weight_lbs if weights else None
    weight_end = weights[-1].weight_lbs if weights else None
    weight_change = round(weight_end - weight_start, 1) if weight_start and weight_end else None
    weight_trend = "down" if weight_change and weight_change < -0.5 else "up" if weight_change and weight_change > 0.5 else "flat"

    # Weight vs projection
    weight_vs_projected = "on_track"
    weight_projection_target = None
    goal = TrainingGoal.query.filter_by(user_id=user_id).first() if user_id is not None else TrainingGoal.query.first()
    if goal and goal.weight_projection:
        proj = goal.weight_projection
        week_proj = next((p for p in proj if p.get("week") == week_num), None)
        # Exposed as-is (raw stored projection value for this week — block-3
        # mode stores the piecewise curve here, see goal_engine.build_block3_projection)
        # so callers like weekly_report.build_sunday_recap can show the
        # target WITHOUT a second weight/curve computation of their own.
        if week_proj:
            weight_projection_target = week_proj.get("projected")
        if week_proj and weight_end:
            diff = weight_end - week_proj.get("projected", weight_end)
            if diff < -1:
                weight_vs_projected = "ahead"
            elif diff > 1:
                weight_vs_projected = "behind"

    # Key lifts — find PRs this week
    key_lift_names = [
        "Barbell Bench Press", "Barbell Back Squat", "Conventional Deadlift",
        "Barbell OHP", "Barbell Bent-Over Row",
    ]
    # PRs from SetLog (the live table), matched by movement so a logged
    # "DB Bench Press" counts for "Barbell Bench Press". The old ExerciseLog +
    # exact-name query returned nothing (table dead since April) so weekly reports
    # showed no lifts.
    lifts_summary = {}
    if user_id is not None:
        from lift_history import lift_session_history
        for name in key_lift_names:
            hist = lift_session_history(user_id, name)
            this_week = [h["top_weight"] for h in hist if h["week"] == week_num]
            if not this_week:
                continue
            max_weight = max(this_week)
            prev_max = max((h["top_weight"] for h in hist
                            if (h["week"] or 0) < week_num), default=0)
            lifts_summary[name] = {
                "weight": max_weight,
                "is_pr": max_weight > prev_max and prev_max > 0,
            }

    # Morning check-in averages
    q = MorningCheckIn.query.filter(
        MorningCheckIn.log_date >= week_start,
        MorningCheckIn.log_date <= week_end,
    )
    if user_id is not None:
        q = q.filter(MorningCheckIn.user_id == user_id)
    checkins = q.all()
    checkin_avg = {}
    if checkins:
        for field in ["mood", "sleep_quality", "stress_level", "soreness", "motivation", "anxiety"]:
            vals = [getattr(c, field) for c in checkins if getattr(c, field) is not None]
            if vals:
                checkin_avg[field] = round(sum(vals) / len(vals), 1)

    # Meals logged this week (informational)
    q = MealLog.query.filter(
        MealLog.log_date >= week_start,
        MealLog.log_date <= week_end,
    )
    if user_id is not None:
        q = q.filter(MealLog.user_id == user_id)
    meals_logged = q.count()

    # Planned training days for THIS user's THIS week — the coach designs the
    # program (including rest days), so the denominator comes from the user's
    # actual plan, never a hardcoded template value. The old fixed "6" made a
    # perfectly-executed 5-day week read 83% and a 7-day week read 117%.
    workouts_total = None
    if user_id is not None:
        try:
            from models import WeeklyDaySchedule, WeeklyPrescription
            sched = WeeklyDaySchedule.query.filter_by(
                user_id=user_id, week=week_num
            ).all()
            if sched:
                workouts_total = sum(1 for ds in sched if not ds.is_rest)
            else:
                rx_days = {
                    rx.day_idx for rx in WeeklyPrescription.query.filter_by(
                        user_id=user_id, week=week_num
                    ).all()
                }
                workouts_total = len(rx_days) if rx_days else None
        except Exception:
            workouts_total = None
    adherence = (
        round((completions / workouts_total) * 100)
        if (workouts_total and completions) else (0 if workouts_total else None)
    )

    # Wellness (RHR/HRV/sleep) for THIS report week — see compute_week_wellness
    # (the shared path also used by GET /api/weekly-report/<week>).
    wellness = compute_week_wellness(week_num, user_id, today=today)

    # Codified lift-decline detector (recomp "Line 2" tripwire) — the SAME
    # function the coach context (<lift_trend>) calls, so the two surfaces
    # can never disagree about whether a decline is real.
    from lift_trend import lift_decline
    lift_trend_result = lift_decline(user_id, week_num)

    return {
        "week": week_num,
        "workouts_completed": completions,
        "workouts_total": workouts_total,
        "weight_start": weight_start,
        "weight_end": weight_end,
        "weight_change": weight_change,
        "weight_trend": weight_trend,
        "weight_vs_projected": weight_vs_projected,
        "weight_projection_target": weight_projection_target,
        "key_lifts": lifts_summary,
        "checkin_avg": checkin_avg,
        "adherence_pct": adherence,
        "meals_logged": meals_logged,
        "wellness": wellness,
        "lift_trend": lift_trend_result,
    }


def _fmt_num(x):
    """Trim a float to its shortest readable form for the recap line —
    220.0 -> "220", 218.9 -> "218.9", 209.5 -> "209.5". Display-only,
    never used for comparisons."""
    return f"{x:g}"


def build_sunday_recap(uid, local_date):
    """One-line Sunday recap for `uid`'s CURRENT block week (the week
    containing `local_date` — the push scheduler's recap slot
    (app._sunday_recap_push) and GET /api/sunday-recap both call this with
    the user's local Sunday, so the push text and the check-in card read
    the IDENTICAL dict and can never disagree — one source of truth).

    Returns {"text": str, "data": {...}} or None when there's no current
    block week to summarize (no AppState.start_date for this user). Never
    raises — every internal failure is logged and turned into None,
    because a broken recap must not break the Sunday push tick or the
    check-in overlay (same contract as
    app._morning_brief_body/_dose_night_body).

    Reuses compute_weekly_metrics for weight/curve/lift-trend — NO second
    weight/curve computation lives here; `curve_target` is read straight
    from compute_weekly_metrics's own `weight_projection_target` (which is
    itself just the SAME TrainingGoal.weight_projection lookup that
    function already does internally for `weight_vs_projected`, now also
    returned). This function only adds the pieces compute_weekly_metrics
    doesn't carry at all — run miles, dose adherence (with held-dose
    exclusion), and average sleep hours — all scoped to the SAME
    Monday-Sunday week compute_weekly_metrics' week_num identifies.
    """
    try:
        return _build_sunday_recap_inner(uid, local_date)
    except Exception:
        log.exception("build_sunday_recap failed user=%s local_date=%s", uid, local_date)
        return None


def _build_sunday_recap_inner(uid, local_date):
    from models import AppState, PeptideDose, RunLog, GarminWellness

    state = AppState.query.filter_by(user_id=uid).first()
    if not state or not state.start_date:
        return None

    # Same start_date-based week resolution as app._week_for()/_current_week
    # (clamped 1..12) — never date.today(), so this stays correct however
    # far `local_date` is from the server's own clock.
    diff_days = (local_date - state.start_date).days
    week_num = min(12, max(1, diff_days // 7 + 1))
    week_monday = state.start_date + timedelta(days=(week_num - 1) * 7)
    week_sunday = week_monday + timedelta(days=6)

    metrics = compute_weekly_metrics(week_num, user_id=uid)

    # ── Dose adherence for THIS week. Held doses (dose_mg<=0) were never
    # scheduled — excluded from both numerator and denominator. A
    # LATE-taken dose still counts as taken (is_late is irrelevant here;
    # only `taken_at is not None` matters, per protocol.py's "date-authority
    # semantics" — taken_at is audit trail, not a gating field).
    dose_rows = PeptideDose.query.filter(
        PeptideDose.user_id == uid,
        PeptideDose.date >= week_monday,
        PeptideDose.date <= week_sunday,
    ).all()
    scheduled_doses = [d for d in dose_rows if d.dose_mg is not None and d.dose_mg > 0]
    if scheduled_doses:
        doses_scheduled = len(scheduled_doses)
        doses_taken = sum(1 for d in scheduled_doses if d.taken_at is not None)
    else:
        doses_scheduled = None
        doses_taken = None

    # ── Run miles for THIS week — shown whenever any RunLog row exists
    # (even a real 0.0-mile week: falsy-zero discipline), omitted only when
    # there are no rows at all (nothing logged, not "zero miles logged").
    run_rows = RunLog.query.filter(
        RunLog.user_id == uid,
        RunLog.log_date >= week_monday,
        RunLog.log_date <= week_sunday,
    ).all()
    miles = sum((r.distance_miles or 0.0) for r in run_rows) if run_rows else None

    # ── Average sleep hours for THIS week — from the same GarminWellness
    # rows compute_week_wellness reads, converted seconds->hours with the
    # SAME round(.,1) convention GET /api/garmin/wellness already uses.
    wellness_rows = GarminWellness.query.filter(
        GarminWellness.user_id == uid,
        GarminWellness.date >= week_monday,
        GarminWellness.date <= week_sunday,
    ).all()
    sleep_hours = [r.sleep_seconds / 3600.0 for r in wellness_rows if r.sleep_seconds]
    sleep_avg_h = round(sum(sleep_hours) / len(sleep_hours), 1) if sleep_hours else None

    lift_trend_pct = (metrics.get("lift_trend") or {}).get("tonnage_delta_pct")

    data = {
        "week": week_num,
        "weight_start": metrics.get("weight_start"),
        "weight_end": metrics.get("weight_end"),
        "curve_target": metrics.get("weight_projection_target"),
        "lift_trend": lift_trend_pct,
        "miles": miles,
        "doses_taken": doses_taken,
        "doses_scheduled": doses_scheduled,
        "sleep_avg_h": sleep_avg_h,
    }

    # RULE: a segment whose data is missing is OMITTED — never "None",
    # never a fabricated 0. Present-but-genuinely-zero values (0.0 miles
    # with runs logged, 0/N doses taken) DO render — see the falsy-zero
    # notes on `miles`/doses above.
    segments = []
    if data["weight_start"] is not None and data["weight_end"] is not None:
        seg = f"{_fmt_num(data['weight_start'])}→{_fmt_num(data['weight_end'])}"
        if data["curve_target"] is not None:
            seg += f" (curve {_fmt_num(data['curve_target'])})"
        segments.append(seg)

    if data["lift_trend"] is not None:
        segments.append(f"lifts {data['lift_trend']:+g}%")

    if data["miles"] is not None:
        segments.append(f"{_fmt_num(data['miles'])} mi")

    if data["doses_scheduled"]:
        segments.append(f"doses {data['doses_taken']}/{data['doses_scheduled']}")

    if data["sleep_avg_h"] is not None:
        segments.append(f"sleep {_fmt_num(data['sleep_avg_h'])}h avg")

    text = f"Wk {week_num}"
    if segments:
        text += ": " + " · ".join(segments)

    return {"text": text, "data": data}


def _build_narrative_data_lines(metrics):
    """Build the plain-text data summary handed to Claude as the narrative
    prompt's user message. Pure/testable — split out from
    generate_report_narrative so the exact prompt text (incl. the wellness
    line) can be asserted without mocking the Anthropic client."""
    data_lines = [f"Week {metrics['week']} Summary:"]
    if metrics.get("workouts_total") is not None:
        data_lines.append(f"Workouts: {metrics['workouts_completed']}/{metrics['workouts_total']}")
    else:
        data_lines.append(f"Workouts completed: {metrics['workouts_completed']} (week had no coach plan)")

    if metrics.get("weight_change") is not None:
        direction = "lost" if metrics["weight_change"] < 0 else "gained"
        weight_line = f"Weight: {direction} {abs(metrics['weight_change'])} lbs"
        if metrics.get("weight_end") is not None:
            weight_line += f" ({metrics['weight_end']} lbs)"
        data_lines.append(weight_line)
        if metrics.get("weight_vs_projected") is not None:
            data_lines.append(f"vs projection: {metrics['weight_vs_projected']}")

    if metrics.get("key_lifts"):
        for name, info in metrics["key_lifts"].items():
            pr_tag = " (PR!)" if info.get("is_pr") else ""
            data_lines.append(f"{name}: {info['weight']} lbs{pr_tag}")

    if metrics.get("checkin_avg"):
        avg = metrics["checkin_avg"]
        data_lines.append(f"Avg mood: {avg.get('mood', '?')}, sleep: {avg.get('sleep_quality', '?')}, motivation: {avg.get('motivation', '?')}")

    if metrics.get("adherence_pct") is not None:
        data_lines.append(f"Adherence: {metrics['adherence_pct']}%")

    # Wellness (RHR/HRV/sleep) — same shared formatter the coach prompt
    # uses (coach_assembler.format_wellness_line): dark_line verbatim when
    # sparse, numbers-only line when lit. The narrative MODEL does the
    # interpreting (headline framing etc.) — this is data, not commentary.
    if metrics.get("wellness"):
        from coach_assembler import format_wellness_line
        wellness_line = format_wellness_line(metrics["wellness"])
        if wellness_line:
            data_lines.append(wellness_line)

    return data_lines


def generate_report_narrative(metrics):
    """Generate a coach narrative from metrics using Claude. Returns text or None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
    except Exception:
        return None

    # Build the data summary for Claude
    data_lines = _build_narrative_data_lines(metrics)

    try:
        full_text = ""
        with client.messages.stream(
            model=CLAUDE_OPUS,
            max_tokens=300,
            system=REPORT_PROMPT,
            messages=[{"role": "user", "content": "\n".join(data_lines)}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
        return full_text
    except Exception as e:
        log.error("Report narrative error: %s", e)
        return None
