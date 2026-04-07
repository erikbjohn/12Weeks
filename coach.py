"""AI Coach powered by Claude - full context training + mental health coaching."""

import os
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

CLAUDE_OPUS = "claude-opus-4-20250514"
CLAUDE_SONNET = "claude-sonnet-4-20250514"


def _format_goal(goal):
    if not goal:
        return ""
    parts = [f"TRAINING GOAL: {goal.get('goal_type', '?')}"]
    if goal.get('target_weight'):
        parts.append(f"Target weight: {goal['target_weight']} lbs")
    if goal.get('daily_calories'):
        parts.append(f"Daily calories: {goal['daily_calories']} kcal")
    if goal.get('protein_grams'):
        parts.append(f"Macros: {goal['protein_grams']}P / {goal.get('carb_grams', '?')}C / {goal.get('fat_grams', '?')}F")
    if goal.get('fasting_protocol'):
        parts.append(f"Fasting: {goal['fasting_protocol']}")
    if goal.get('calorie_by_day_type'):
        cals = goal['calorie_by_day_type']
        parts.append(f"Cals by day type: {', '.join(f'{k}={v}' for k,v in cals.items())}")
    return '\n'.join(parts)


def _format_exercise_history(history):
    if not history:
        return "EXERCISE HISTORY: No lifts logged yet."
    lines = ["EXERCISE HISTORY (raw log for reference — see EXERCISE ANALYSIS for authoritative interpretation):"]
    for name, entries in sorted(history.items()):
        if isinstance(entries, dict):
            entries = [entries]  # Legacy single-entry format
        session_strs = []
        for e in reversed(entries):  # Oldest first
            rpe_str = f"({e['rpe']})" if e.get('rpe') else ""
            wt = e.get('weight', 0)
            reps = e.get('reps_completed', '')
            session_strs.append(f"wk{e.get('week','?')}:{wt}lb{'x'+str(reps) if reps else ''}{rpe_str}")
        lines.append(f"  {name}: {' → '.join(session_strs)}")
    return '\n'.join(lines[:30])  # Cap to prevent prompt bloat


def _format_exercise_analysis(analysis):
    """Format the training engine's pre-computed analysis for each exercise."""
    if not analysis:
        return ""
    lines = ["EXERCISE ANALYSIS (from training engine — authoritative, do NOT re-interpret raw data):"]
    indicators = {"up": "PROGRESS", "hold": "HOLD", "deload": "DELOAD", "weak": "CAUTIOUS", "down": "REDUCE"}
    for name, data in sorted(analysis.items()):
        ind = indicators.get(data.get("progression_indicator", "hold"), "HOLD")
        weight_str = f"{data['target_weight']}lb" if data.get('target_weight') else "TBD"
        reps = data.get('target_reps', '?')
        sets = data.get('target_sets', '?')
        reason = data.get('adjustment_reason', '')
        alert = f" [ALERT: {data['coach_alert']}]" if data.get('coach_alert') else ""
        lines.append(f"  {name}: [{ind}] target {weight_str} {sets}x{reps} — {reason}{alert}")
    return '\n'.join(lines)


def _format_today_sets(sets):
    if not sets:
        return ""
    lines = ["TODAY'S SETS (per-set data — DO NOT sum reps across sets):"]
    for ex_name, set_list in sets.items():
        weights = [s.get('weight', 0) for s in set_list]
        reps_list = [s.get('reps', 0) for s in set_list]
        num_sets = len(set_list)
        avg_reps = round(sum(r for r in reps_list if r) / max(num_sets, 1))
        last_wt = weights[-1] if weights else 0
        # Show summary format to prevent LLM from summing reps
        target_wt = set_list[0].get('target_weight') if set_list else None
        target_reps = set_list[0].get('target_reps') if set_list else None
        target_str = f" (target: {target_wt}lb×{target_reps}/set)" if target_wt else ""
        mod = set_list[-1].get('modification_direction', '') if set_list else ''
        marker = '\u2713' if mod == 'as_prescribed' else '\u2191' if mod == 'increased_weight' else '\u2193' if 'decreased' in (mod or '') else ''
        lines.append(f"  {ex_name}: {last_wt}lb, {num_sets} sets, {avg_reps} reps/set{target_str} {marker}")
    return "\n".join(lines)


def _format_runs(runs):
    if not runs:
        return ""
    lines = ["RUN HISTORY (recent):"]
    for r in runs[:7]:
        parts = []
        if r.get('distance_miles'):
            parts.append(f"{r['distance_miles']}mi")
        if r.get('avg_hr'):
            parts.append(f"HR:{r['avg_hr']}")
        if r.get('elevation_ft'):
            parts.append(f"elev:{r['elevation_ft']}ft")
        lines.append(f"  {r.get('date','?')}: {' '.join(parts) or 'logged'}")
    return '\n'.join(lines)


def _format_physical(pa):
    if not pa:
        return ""
    lines = ["BASELINE PHYSICAL ASSESSMENT:"]
    if pa.get('height_inches'):
        ft = pa['height_inches'] // 12
        inch = pa['height_inches'] % 12
        lines.append(f"  Height: {ft}'{inch}\"  Weight: {pa.get('bodyweight_lbs', '?')} lbs")
    measures = []
    for k in ['waist', 'chest', 'bicep', 'thigh', 'neck', 'hips']:
        if pa.get(k):
            measures.append(f"{k}:{pa[k]}\"")
    if measures:
        lines.append(f"  Measurements: {', '.join(measures)}")
    tests = []
    if pa.get('pushups'):
        tests.append(f"pushups:{pa['pushups']}")
    if pa.get('plank_sec'):
        tests.append(f"plank:{pa['plank_sec']}s")
    if pa.get('squats'):
        tests.append(f"squats:{pa['squats']}")
    if pa.get('pullups') is not None:
        tests.append(f"pullups:{pa['pullups']}")
    if tests:
        lines.append(f"  Fitness tests: {', '.join(tests)}")
    return '\n'.join(lines)


def _format_measurements(m):
    if not m:
        return ""
    # Support both list (new: last 4) and dict (legacy: single)
    if isinstance(m, dict):
        return f"LATEST MEASUREMENTS ({m.get('date', '?')}): waist {m.get('waist', '?')}\""
    if not isinstance(m, list) or len(m) == 0:
        return ""
    lines = ["BODY MEASUREMENTS (recent trend):"]
    for entry in reversed(m):  # Oldest first for trend readability
        lines.append(f"  {entry.get('date', '?')}: waist {entry.get('waist', '?')}\"")
    return '\n'.join(lines)


def _format_next_week_prescriptions(prescriptions):
    if not prescriptions:
        return ""
    lines = ["NEXT WEEK'S PLAN (engine-computed targets — announce these, do not re-derive):"]
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    current_day = -1
    for rx in prescriptions:
        if rx['day_idx'] != current_day:
            current_day = rx['day_idx']
            lines.append(f"\n  {day_names[current_day]}:")
        weight_str = f" @ {rx['target_weight']}lb" if rx.get('target_weight') else ""
        reason_str = f" — {rx['adjustment_reason']}" if rx.get('adjustment_reason') else ""
        lines.append(f"    {rx['exercise']}: {rx['sets']}x{rx['reps']}{weight_str}{reason_str}")
    return "\n".join(lines)


def _format_weekly_meals(weekly_meals):
    if not weekly_meals:
        return ""
    lines = ["MEALS LOGGED THIS WEEK:"]
    for m in weekly_meals:
        lines.append(f"  {m.get('day', '?')} ({m.get('date', '?')}): {m.get('meals_logged', 0)} meals logged")
    if not weekly_meals:
        lines.append("  No meals logged this week")
    return "\n".join(lines)


def _format_meals_today(meals, meal_plan=None, user_timezone=None):
    parts = []
    if meal_plan:
        plan_meals = meal_plan.get("meals", [])
        parts.append(f"TODAY'S MEAL PLAN ({meal_plan.get('type', '?')}, target {meal_plan.get('target_cal', '?')} cal, {meal_plan.get('target_protein', '?')}g protein):")
        for m in plan_meals:
            foods = ", ".join(m.get("foods", []))
            parts.append(f"  {m.get('time', '?')} {m.get('name', '')}: {foods}")

        # Pre-compute next meal so the coach doesn't have to do time math
        try:
            from datetime import datetime
            now = datetime.now()
            try:
                from utils_time import user_local_now
                now = user_local_now(user_timezone or 'America/Los_Angeles')
            except Exception:
                pass
            now_minutes = now.hour * 60 + now.minute
            next_meal = None
            for m in plan_meals:
                t = m.get("time", "")
                t_lower = t.lower().replace("am", "").replace("pm", "")
                try:
                    h, mn = t_lower.split(":")
                    h = int(h)
                    mn = int(mn)
                    if "pm" in t.lower() and h != 12:
                        h += 12
                    if "am" in t.lower() and h == 12:
                        h = 0
                    meal_min = h * 60 + mn
                    if meal_min > now_minutes:
                        next_meal = m
                        break
                except Exception:
                    pass
            if next_meal:
                parts.append(f"  NEXT MEAL: {next_meal.get('time', '?')} — {next_meal.get('name', '')}. Athlete is ON SCHEDULE between meals.")
            else:
                parts.append(f"  All meals for today are past their scheduled time.")
        except Exception:
            pass

    if not meals:
        is_fast = meal_plan and ('fast' in meal_plan.get('type', '').lower() or 'Protein-Sparing' in meal_plan.get('type', ''))
        if is_fast:
            parts.append("Meal tracking: FASTING DAY — protein shake + water only. This is correct.")
        else:
            parts.append("Meal tracking: Not logged today")
    else:
        eaten = meals.get('eaten', [])
        fasting = meals.get('fasting', False)
        if fasting:
            parts.append("Status: FASTING DAY")
        elif eaten:
            parts.append(f"Meals eaten: {len(eaten)} of {len(meal_plan.get('meals', [])) if meal_plan else '?'}")
        else:
            parts.append("Meals eaten: None yet")
    return '\n'.join(parts) if parts else "Meals today: Not tracked"


def _format_memories(memories):
    if not memories:
        return ""
    lines = ["COACH MEMORY (persistent observations — survive across conversations):"]
    # Show exceptions and victories first (most important for consistency)
    priority = [m for m in memories if m.get('type') in ('exception', 'victory', 'commitment')]
    others = [m for m in memories if m.get('type') not in ('exception', 'victory', 'commitment')]
    if priority:
        lines.append("  CRITICAL — CHECK THESE BEFORE ANY COMPLIANCE JUDGMENT:")
        for m in priority:
            prefix = f"[wk{m.get('week', '?')}]" if m.get('week') else ""
            lines.append(f"  {prefix} [{m.get('type', 'note').upper()}] {m['content']}")
    for m in others:
        prefix = f"[wk{m.get('week', '?')}]" if m.get('week') else ""
        mtype = m.get('type', 'note')
        lines.append(f"  {prefix} [{mtype}] {m['content']}")
    return '\n'.join(lines)


def extract_memories(user_message, coach_response, context):
    """Extract memory-worthy observations from the exchange.
    Returns a list of dicts: [{"type": str, "content": str}] or empty list.
    Called after every coach response to decide if anything should be persisted."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    # Run on every message — memories are critical for coach consistency

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
        response = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=300,
            system="""You extract coaching memories from athlete conversations. Return ONLY observations worth remembering across future sessions. If nothing is notable, return exactly: NONE

Format each memory on its own line as: TYPE: content
Types: injury, commitment, preference, observation, milestone, exception, victory, rule

CRITICAL TYPES:
exception: Coach GRANTED permission to deviate from the plan (holiday meals, schedule change, etc.)
  Example: exception: Granted Passover exception — eat with family Thursday, back on plan Friday
victory: Athlete resisted temptation or made a strong decision with coach help
  Example: victory: Wanted ice cream Wednesday, coach talked through it, athlete chose discipline
commitment: Athlete made a specific promise or the coach set a specific expectation
  Example: commitment: Promised no more late-night snacking for the rest of the program
rule: A CORRECTION the athlete made to the coach's behavior. The athlete told the coach it was wrong, or instructed the coach to stop doing something. Convert to an imperative directive.
  Example: rule: Sunday fast is prescribed protocol — never call it freelancing
  Example: rule: Do not mention post-workout shakes — not in the meal plan
  Example: rule: Between-meal gaps are normal — do not nag about eating

Other types:
injury: Physical issue to monitor
preference: Training/food preference
observation: Behavioral pattern worth noting
milestone: Achievement or PR""",
            messages=[{
                "role": "user",
                "content": f"Athlete said: {user_message}\n\nCoach responded: {coach_response}\n\nExtract memories (or NONE):",
            }],
        )
        text = response.content[0].text.strip()
        if text == "NONE" or not text:
            return []

        memories = []
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line and line.split(":")[0].strip().lower() in ("injury", "commitment", "preference", "observation", "milestone", "exception", "victory", "rule"):
                parts = line.split(":", 1)
                memories.append({"type": parts[0].strip().lower(), "content": parts[1].strip()})
        return memories
    except Exception as e:
        log.warning("Memory extraction failed: %s", e)
        return []


def get_coach_response(user_message, context):
    """
    Send a message to Claude with full training context.
    Returns the assistant's response text.

    context dict should contain:
        - checkins: list of recent MorningCheckIn dicts
        - chat_history: list of recent ChatMessage dicts
        - garmin: today's garmin summary (or None)
        - readiness: overtraining assessment (or None)
        - bodyweight: recent body weight entries
        - workout_today: today's planned workout
        - week: current week number
        - phase: current phase info
        - weights: exercise weight history (key lifts)
        - completions: recent completion data
        - meals_today: today's meal log
        - supplements_today: today's supplement status
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "System error. We'll be back."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
    except Exception as e:
        log.error("Failed to init Anthropic client: %s", e)
        return "Technical issue. Try again in 60 seconds."

    from coach_assembler import assemble_prompt
    system_prompt = assemble_prompt("conversation", context)
    messages = _build_messages(user_message, context.get("chat_history", []))

    try:
        response = client.messages.create(
            model=CLAUDE_OPUS,
            max_tokens=800,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        log.error("Claude API error: %s", e)
        return "Erik stepped away. He'll be back in a moment."


def _format_today(ctx):
    """Format today's date and time in user's local timezone."""
    user_tz = ctx.get('user_timezone', 'UTC')
    try:
        from utils_time import user_local_now, format_user_local
        from datetime import datetime, timezone
        local_now = user_local_now(user_tz)
        day_name = local_now.strftime('%A')
        date_str = local_now.strftime('%B %d, %Y')
        time_str = local_now.strftime('%I:%M %p').lstrip('0')
        return f"{day_name}, {date_str} at {time_str} ({user_tz}). Day {local_now.weekday()} of training week (Mon=0)."
    except Exception:
        return f"{date.today().strftime('%A, %B %d, %Y')} (timezone unknown)"


def _format_week_schedule(schedule, completed):
    """Format weekly schedule showing what's done and what's ahead."""
    if not schedule:
        return "Week schedule: Not available"
    completed_indices = set()
    for d in completed:
        if isinstance(d, dict):
            completed_indices.add(d.get('day_idx', -1))
        else:
            completed_indices.add(d)
    lines = ["WEEK SCHEDULE:"]
    for day in schedule:
        idx = day['day_idx']
        name = day.get('day', '?')
        lift = day.get('liftName', 'Rest')
        done = idx in completed_indices
        marker = "[DONE]" if done else "[    ]"
        lines.append(f"  {marker} {name}: {lift}")
    return "\n".join(lines)


def _get_day_name(ctx):
    """Get just the day name (e.g., 'Wednesday') from context."""
    try:
        from utils_time import user_local_now
        tz = ctx.get('user_timezone', 'UTC')
        return user_local_now(tz).strftime('%A')
    except Exception:
        from datetime import date
        return date.today().strftime('%A')


def _get_date_str(ctx):
    """Get ISO date string from context."""
    try:
        from utils_time import user_local_now
        tz = ctx.get('user_timezone', 'UTC')
        return user_local_now(tz).strftime('%Y-%m-%d')
    except Exception:
        from datetime import date
        return date.today().isoformat()


def _format_meals_today_xml(meals, meal_plan, meal_plan_type, user_timezone=None):
    """Format meals with explicit fasting day callouts."""
    if meal_plan_type == 'fast_day':
        return "THIS IS A FASTING DAY. There are ZERO regular meals. Protein shake + water only. Do not ask about meals. Do not count meals. Do not say the athlete missed meals."
    return _format_meals_today(meals, meal_plan, user_timezone=user_timezone)


def _summarize_checkins(checkins):
    """Summarize recent morning check-ins for the system prompt."""
    if not checkins:
        return "No morning check-ins recorded yet."

    recent = checkins[-7:]  # last 7 days
    lines = ["Recent morning check-ins (last {} days):".format(len(recent))]

    for ci in recent:
        parts = []
        if ci.get("mood") is not None:
            parts.append(f"mood:{ci['mood']}")
        if ci.get("sleep_quality") is not None:
            parts.append(f"sleep:{ci['sleep_quality']}")
        if ci.get("stress_level") is not None:
            parts.append(f"stress:{ci['stress_level']}")
        if ci.get("soreness") is not None:
            parts.append(f"sore:{ci['soreness']}")
        if ci.get("motivation") is not None:
            parts.append(f"motivation:{ci['motivation']}")
        if ci.get("anxiety") is not None:
            parts.append(f"anxiety:{ci['anxiety']}")
        note = f" \"{ci['notes']}\"" if ci.get("notes") else ""
        lines.append(f"  {ci.get('date', '?')}: {', '.join(parts)}{note}")

    # Trend analysis
    if len(recent) >= 3:
        moods = [c["mood"] for c in recent if c.get("mood") is not None]
        if moods:
            avg_mood = sum(moods) / len(moods)
            trend = "stable"
            if len(moods) >= 3:
                first_half = sum(moods[:len(moods)//2]) / max(len(moods)//2, 1)
                second_half = sum(moods[len(moods)//2:]) / max(len(moods) - len(moods)//2, 1)
                if second_half < first_half - 1:
                    trend = "DECLINING"
                elif second_half > first_half + 1:
                    trend = "improving"
            lines.append(f"  Mood trend: {trend} (avg {avg_mood:.1f}/10)")

        anxiety_vals = [c["anxiety"] for c in recent if c.get("anxiety") is not None]
        if anxiety_vals and sum(anxiety_vals) / len(anxiety_vals) > 6:
            lines.append("  WARNING: Elevated anxiety pattern detected.")

        sleep_vals = [c["sleep_quality"] for c in recent if c.get("sleep_quality") is not None]
        if sleep_vals and sum(sleep_vals) / len(sleep_vals) < 4:
            lines.append("  WARNING: Poor sleep pattern detected.")

    return "\n".join(lines)


def _build_messages(user_message, chat_history):
    """Build the messages array from chat history + new message."""
    messages = []

    # Filter out system trigger messages — they eat context slots
    # Keep real conversation, skip [MORNING_CHECKIN], [CHAT_OPENED], etc.
    filtered = []
    for msg in chat_history:
        content = msg.get("content", "")
        # Skip system triggers (user-role messages that start with [TAG])
        if msg["role"] == "user" and content.startswith("[") and "] " in content[:50]:
            continue
        filtered.append(msg)

    # Include last 40 messages with timestamps so coach knows WHEN things happened
    for msg in filtered[-40:]:
        content = msg["content"]
        # Prepend timestamp if available so coach understands time ordering
        msg_time = msg.get("time")
        if msg_time:
            try:
                from datetime import datetime as _dt
                t = _dt.fromisoformat(msg_time.replace('Z', '+00:00'))
                time_label = t.strftime('%b %d %I:%M %p').lstrip('0')
                content = f"[{time_label}] {content}"
            except Exception:
                pass
        messages.append({
            "role": msg["role"],
            "content": content,
        })

    # Deduplicate: chat_history (from DB) may already contain the just-committed
    # user message. Only append if it's not already the last entry.
    already_present = (
        messages
        and messages[-1]["role"] == "user"
        and messages[-1]["content"] == user_message
    )
    if not already_present:
        messages.append({
            "role": "user",
            "content": user_message,
        })

    return messages
