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
    goal = TrainingGoal.query.filter_by(user_id=user_id).first() if user_id is not None else TrainingGoal.query.first()
    if goal and goal.weight_projection and weight_end:
        proj = goal.weight_projection
        week_proj = next((p for p in proj if p.get("week") == week_num), None)
        if week_proj:
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

    return {
        "week": week_num,
        "workouts_completed": completions,
        "workouts_total": workouts_total,
        "weight_start": weight_start,
        "weight_end": weight_end,
        "weight_change": weight_change,
        "weight_trend": weight_trend,
        "weight_vs_projected": weight_vs_projected,
        "key_lifts": lifts_summary,
        "checkin_avg": checkin_avg,
        "adherence_pct": adherence,
        "meals_logged": meals_logged,
    }


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
