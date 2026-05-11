"""Nutritionist: per-day calorie and macro prescriptions for the week.

Replaces deficit-calculator + fixed macro templates with an agent call
that reads the athlete's weight trend, fasting compliance, recent
day-type pattern, and goal trajectory. Returns per-day target calories
+ macros + day_type rationale.

The downstream meal_generator still builds actual food items to fit
these targets — this agent only sets the numbers and the day pattern.
"""
from __future__ import annotations
import os
import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=3,
    )


def _build_weight_trend_block(user_id: int, lookback_weeks: int = 6) -> str:
    """Recent body-weight log so the coach sees trajectory."""
    from models import BodyWeight
    from datetime import timedelta
    from coach_assembler import _user_today
    cutoff = _user_today() - timedelta(weeks=lookback_weeks)
    rows = (BodyWeight.query
            .filter(BodyWeight.user_id == user_id)
            .filter(BodyWeight.log_date >= cutoff)
            .order_by(BodyWeight.log_date.desc())
            .all())
    if not rows:
        return "(no body weight log)"
    return "\n".join(f"  {r.log_date}: {r.weight_lbs} lb" for r in rows[:14])


def _build_recent_macros_block(user_id: int) -> str:
    """Last week's day_type pattern + targets — coach uses this to see
    what's been working."""
    from models import WeeklyMealPlan
    rows = (WeeklyMealPlan.query
            .filter(WeeklyMealPlan.user_id == user_id)
            .order_by(WeeklyMealPlan.week.desc(), WeeklyMealPlan.day_idx)
            .limit(14).all())
    if not rows:
        return "(no recent meal plans)"
    lines = []
    for r in rows:
        bits = [f"wk {r.week} day {r.day_idx}"]
        if r.day_type: bits.append(f"type={r.day_type}")
        if r.daily_calories: bits.append(f"{r.daily_calories} kcal")
        if r.daily_protein: bits.append(f"{r.daily_protein}g P")
        lines.append("  " + " | ".join(bits))
    return "\n".join(lines)


def generate_week_meals(
    user_id: int,
    week: int,
    workout_pattern: dict,
    user_context: dict,
) -> dict[int, dict]:
    """Generate per-day calorie/macro/day-type prescriptions via the
    nutritionist.

    workout_pattern: {day_idx: 'heavy'|'rest'|'pull'|'run_long'|...} —
      what kind of training the day requires, so the nutritionist can
      pair fueling appropriately (heavy lift = more carbs, rest = lower
      calories, long run = fasted or carb-up depending on context).
    user_context: {goal_type, current_weight, target_weight,
                   weeks_remaining, tdee, fasting_protocol}

    Returns: {day_idx: {day_type, calories, protein, carbs, fat,
                        rationale}}
    """
    weight_block = _build_weight_trend_block(user_id)
    macros_block = _build_recent_macros_block(user_id)

    workout_lines = "\n".join(
        f"  {_DAY_NAMES[d]}: {pattern}"
        for d, pattern in sorted(workout_pattern.items())
    ) if workout_pattern else "(no workout pattern data)"

    goal_type = user_context.get("goal_type", "recomp")
    current_wt = user_context.get("current_weight")
    target_wt = user_context.get("target_weight")
    weeks_rem = user_context.get("weeks_remaining")
    tdee = user_context.get("tdee")
    fasting = user_context.get("fasting_protocol", "")

    system = (
        "You are a sports nutritionist prescribing per-day calorie and macro "
        "targets for the athlete's week. You see their weight trend, the day's "
        "training demand, and the goal trajectory. Pair fueling to the day.\n\n"
        "RULES:\n"
        "1. Heavy lifting days: higher calories + carbs (e.g. cut: TDEE - 300, "
        "   recomp: TDEE flat, build: TDEE + 200).\n"
        "2. Rest / recovery days: lower calories (cut: TDEE - 500-700, "
        "   recomp: TDEE - 300, build: TDEE).\n"
        "3. Long run days: carbs front-loaded if not fasted; if fasted, lower "
        "   calories overall with refeed post-run.\n"
        "4. Fast days (if the athlete fasts): zero or very low calories during "
        "   the fasting window, normal afterwards.\n"
        "5. Protein floor: 1.0 g/lb bodyweight minimum every day.\n"
        "6. If the athlete is on pace for goal weight loss, hold deficit. If "
        "   ahead of pace, ease deficit by 100 kcal. If behind, deepen by 100.\n"
        "7. Match the recent successful day_type pattern unless data argues "
        "   for change (e.g. weight stalled → deeper deficit).\n\n"
        "Output: JSON mapping `<day_idx>` to "
        '{"day_type": "<heavy|rest|fast|carb_up|recovery|...>", '
        '"calories": <int>, "protein": <g>, "carbs": <g>, "fat": <g>, '
        '"rationale": "<1 sentence why this fueling for this day>"}. '
        "JSON only.\n\n"
        "Example:\n"
        '{\n'
        '  "0": {"day_type": "heavy", "calories": 2000, "protein": 200, '
        '"carbs": 200, "fat": 60, "rationale": "Lower POWER + RDL — carbs '
        'support heavy compound work, hold protein high"},\n'
        '  "2": {"day_type": "rest", "calories": 1500, "protein": 200, '
        '"carbs": 100, "fat": 65, "rationale": "Rest day — drop carbs, hold '
        'protein, deeper deficit for cut"}\n'
        '}'
    )

    user_prompt = (
        f"ATHLETE CONTEXT:\n"
        f"- Goal: {goal_type}, currently {current_wt} lb → target {target_wt} lb, "
        f"{weeks_rem} weeks remaining\n"
        f"- TDEE estimate: {tdee or 'unspecified'}\n"
        f"- Fasting protocol: {fasting or 'none'}\n"
        f"- Week being prescribed: {week}\n\n"
        f"WORKOUT PATTERN FOR THE WEEK:\n{workout_lines}\n\n"
        f"WEIGHT TREND (recent):\n{weight_block}\n\n"
        f"RECENT MEAL PLANS (last 2 weeks):\n{macros_block}\n\n"
        "Prescribe the per-day calories and macros. JSON only."
    )

    try:
        client = _anthropic_client()
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("generate_week_meals failed: %s", e)
        return {}

    out: dict[int, dict] = {}
    for k, v in parsed.items():
        try:
            day_idx = int(k)
        except ValueError:
            continue
        if not isinstance(v, dict):
            continue
        out[day_idx] = {
            "day_type": v.get("day_type") or "normal",
            "calories": int(v.get("calories") or 0),
            "protein": int(v.get("protein") or 0),
            "carbs": int(v.get("carbs") or 0),
            "fat": int(v.get("fat") or 0),
            "rationale": v.get("rationale") or "",
        }
    return out
