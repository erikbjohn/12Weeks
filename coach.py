"""AI Coach powered by Claude - full context training + mental health coaching."""

import os
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


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


def _format_meals_today(meals, meal_plan=None):
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
                now = user_local_now(None)  # uses current request context
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
            model="claude-sonnet-4-20250514",
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

    system_prompt = _build_system_prompt(context)
    messages = _build_messages(user_message, context.get("chat_history", []))

    try:
        response = client.messages.create(
            model="claude-opus-4-20250514",
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


def _format_meals_today_xml(meals, meal_plan, meal_plan_type):
    """Format meals with explicit fasting day callouts."""
    if meal_plan_type == 'fast_day':
        return "THIS IS A FASTING DAY. There are ZERO regular meals. Protein shake + water only. Do not ask about meals. Do not count meals. Do not say the athlete missed meals."
    return _format_meals_today(meals, meal_plan)


def _compute_template_vars(ctx):
    """Pre-compute all variables needed by the Jinja2 template."""

    # Recent check-in trends
    checkin_summary = _summarize_checkins(ctx.get("checkins", []))

    # Session analysis
    _sa = ctx.get('session_analysis')
    session_analysis_str = ''
    if _sa:
        session_analysis_str = f"LAST SESSION ({_sa.get('date', '?')}): Compliance {_sa.get('compliance', '?')}%. {_sa.get('summary', '')}\nMuscle groups: {', '.join(_sa.get('muscles', []))}"

    _ws = ctx.get('weekly_summary')
    weekly_summary_str = ''
    if _ws and _ws.get('sessions', 0) > 0:
        weekly_summary_str = f"WEEKLY SUMMARY (Week {_ws.get('week', '?')}): {_ws.get('summary', '')}"

    # Body weight trend — full program history (weekly weigh-ins)
    bw = ctx.get("bodyweight", [])
    bw_summary = ""
    if bw:
        latest = bw[-1]
        first = bw[0]
        bw_summary = f"Latest weight: {latest['weight']} lb ({latest['date']})."
        total_delta = latest['weight'] - first['weight']
        if len(bw) >= 2:
            direction = "down" if total_delta < 0 else "up" if total_delta > 0 else "flat"
            bw_summary += f" Program total: {direction} {abs(total_delta):.1f} lb (started at {first['weight']} lb)."
            # Week-over-week change
            prev = bw[-2]
            weekly_delta = latest['weight'] - prev['weight']
            wk_dir = "down" if weekly_delta < 0 else "up" if weekly_delta > 0 else "flat"
            bw_summary += f" Last weigh-in: {wk_dir} {abs(weekly_delta):.1f} lb vs previous ({prev['date']})."
        # Full history for pattern analysis
        if len(bw) >= 3:
            weights_str = " \u2192 ".join(f"{e['weight']}" for e in bw[-6:])
            bw_summary += f"\n  Weight history (recent): {weights_str}"

    # Today's workout
    workout_summary = ""
    w = ctx.get("workout_today")
    if w:
        workout_summary = f"Today's workout: {w.get('liftName', 'Rest')}. Run: {w.get('run', {}).get('label', '?')} {w.get('run', {}).get('time', '')}."
        if w.get("isRest"):
            workout_summary = "Today is a rest day (streak mile only)."

    # Garmin data
    garmin_summary = ""
    g = ctx.get("garmin")
    if g:
        parts = []
        if g.get("hrv") and g["hrv"].get("lastNight") is not None:
            parts.append(f"HRV {g['hrv']['lastNight']} (avg {g['hrv'].get('weeklyAvg', '?')})")
        if g.get("sleep") and g["sleep"].get("score") is not None:
            parts.append(f"Sleep score {g['sleep']['score']} ({g['sleep'].get('durationHours', '?')}h)")
        if g.get("bodyBattery") and g["bodyBattery"].get("current") is not None:
            parts.append(f"Body battery {g['bodyBattery']['current']}")
        if g.get("stress") and g["stress"].get("overall") is not None:
            parts.append(f"Stress {g['stress']['overall']}")
        if parts:
            garmin_summary = "Garmin today: " + ", ".join(parts) + "."

    # Readiness
    readiness_summary = ""
    r = ctx.get("readiness")
    if r and r.get("score") is not None:
        readiness_summary = f"Readiness score: {r['score']}/100 ({r['risk_level']} risk)."
        if r.get("flags"):
            readiness_summary += f" Flags: {', '.join(r['flags'])}."

    # Phase info
    phase = ctx.get("phase", {})
    week = ctx.get("week", 1)

    # Supplement compliance
    supps = ctx.get("supplements_today", {})
    supp_taken = [k for k, v in supps.get("taken", {}).items() if v]

    # Build food safety section
    food_restrictions = ctx.get("food_restrictions", [])
    custom_allergies = ctx.get("custom_allergies", "")
    selected_foods = ctx.get("selected_foods")
    fasting_protocol = ctx.get("fasting_protocol")

    food_safety = ""
    if food_restrictions or custom_allergies:
        allergen_list = ", ".join(food_restrictions) if food_restrictions else "None"
        custom = f"\nCustom allergies/intolerances: {custom_allergies}" if custom_allergies else ""
        food_safety = f"\nDIETARY RESTRICTIONS: {allergen_list}{custom}\n"

    # Resolve food IDs to human-readable names
    _FOOD_ID_TO_NAME = {
        "chicken_breast": "Chicken Breast", "ground_turkey_93": "Ground Turkey", "ground_beef_90": "Ground Beef",
        "salmon": "Salmon", "tilapia": "Tilapia", "shrimp": "Shrimp", "tuna_canned": "Canned Tuna",
        "eggs": "Eggs", "egg_whites": "Egg Whites", "greek_yogurt": "Greek Yogurt",
        "cottage_cheese": "Cottage Cheese", "tofu_firm": "Tofu", "tempeh": "Tempeh",
        "whey_protein": "Whey Protein", "plant_protein": "Plant Protein",
        "white_rice": "White Rice", "brown_rice": "Brown Rice", "oats": "Oats",
        "sweet_potato": "Sweet Potato", "white_potato": "White Potato", "quinoa": "Quinoa",
        "whole_wheat_bread": "Whole Wheat Bread", "whole_wheat_pasta": "Whole Wheat Pasta",
        "black_beans": "Black Beans", "lentils": "Lentils", "banana": "Banana", "blueberries": "Blueberries",
        "broccoli": "Broccoli", "spinach": "Spinach", "kale": "Kale", "asparagus": "Asparagus",
        "green_beans": "Green Beans", "bell_pepper": "Bell Pepper", "zucchini": "Zucchini",
        "cauliflower": "Cauliflower", "mixed_greens": "Mixed Greens", "cherry_tomatoes": "Cherry Tomatoes",
        "olive_oil": "Olive Oil", "coconut_oil": "Coconut Oil", "avocado": "Avocado",
        "almonds": "Almonds", "walnuts": "Walnuts", "peanut_butter": "Peanut Butter",
        "almond_butter": "Almond Butter", "chia_seeds": "Chia Seeds", "flax_seeds": "Flax Seeds",
        "cheddar_cheese": "Cheddar Cheese",
    }

    selected_food_summary = ""
    if selected_foods:
        names = []
        for cat, food_ids in selected_foods.items():
            for fid in food_ids:
                names.append(_FOOD_ID_TO_NAME.get(fid, fid))
        selected_food_summary = (
            "\nTHIS IS THE COMPLETE LIST OF APPROVED FOODS. There are NO other approved foods:\n"
            f"{', '.join(sorted(names))}\n\n"
            "If a food is NOT on this list, it DOES NOT EXIST for this athlete. Do not mention it.\n"
            "Do not suggest it. Do not reference it. Not corn tortillas, not bread (unless Whole Wheat Bread\n"
            "is listed), not pasta (unless Whole Wheat Pasta is listed), not any food not explicitly named above.\n"
        )

    fasting_section = ""
    _fasting_state = ctx.get("fasting_state")
    if _fasting_state:
        fasting_section += (
            "\n<fasting_state>\n"
            f"CURRENT FASTING STATE: {_fasting_state['hours_fasted']} hours fasted (since {_fasting_state['last_meal_day']} {_fasting_state['last_meal_time']}).\n"
            "YOU PRESCRIBED THIS FAST. Sunday is a fast day in the program YOU created.\n"
            f"Saturday {_fasting_state['last_meal_time']} to Monday {_fasting_state['eating_window_opens']} = ~40 hours. This is YOUR program, not freelancing.\n"
            "NEVER call this \"freelancing\" or \"going rogue\" or \"creating your own protocol.\"\n"
            f"Eating window opens at {_fasting_state['eating_window_opens']} today.\n"
            "</fasting_state>\n"
        )
    if fasting_protocol:
        fasting_section += f"\nFASTING PROTOCOL: {fasting_protocol}\n"
        if "16:8" in fasting_protocol or "16_8" in fasting_protocol:
            fasting_section += (
                "The athlete follows 16:8 intermittent fasting. Eating window is approximately 11am-7pm.\n"
                "NEVER suggest eating, consuming protein, having a shake, or ingesting ANY calories outside the eating window.\n"
                "Before 11am: ONLY black coffee, water, or zero-calorie drinks are acceptable.\n"
                "After 7pm: NO food. Period.\n"
                "Post-workout nutrition advice must respect the fasting window. If the workout ends before 11am,\n"
                "the athlete waits until 11am to eat. Do NOT tell them to \"get some protein\" after an early workout.\n"
            )
        elif "omad" in fasting_protocol.lower() or "one_meal" in fasting_protocol.lower():
            fasting_section += "The athlete eats ONE meal per day. Do NOT suggest eating at any other time.\n"

    # Check if athlete is a minor
    goal_data = ctx.get("goal")
    is_minor = False
    if goal_data and goal_data.get("goal_type") == "recomp":
        pa = ctx.get("physical_assessment")
        if goal_data.get("fasting_protocol") == "none":
            is_minor = True

    minor_warning = is_minor

    # Fixed coaching tone — anger_level will replace this in the new architecture
    tone = "Direct, process-focused coaching. Name what happened. State what's next. No drama."

    # Determine meal plan type explicitly for XML attribute
    meal_plan = ctx.get('meal_plan_today')
    meal_plan_type = "unknown"
    if meal_plan:
        raw_type = meal_plan.get('type', '').lower()
        if 'fast' in raw_type or 'protein-sparing' in raw_type:
            meal_plan_type = "fast_day"
        elif 'heavy' in raw_type or 'lift' in raw_type:
            meal_plan_type = "heavy_lift"
        elif 'rest' in raw_type:
            meal_plan_type = "rest_day"
        else:
            meal_plan_type = raw_type or "standard"

    athlete_name = ctx.get('athlete_name', 'Athlete')

    # Pre-compute all formatted text blocks
    day_name = _get_day_name(ctx)
    date_str = _get_date_str(ctx)
    today_text = _format_today(ctx)
    phase_label = phase.get('label', '?')
    phase_focus = phase.get('focus', '?')
    phase_deficit = phase.get('deficit', '?')
    meal_plan_target_cal = meal_plan.get('target_cal', '?') if meal_plan else '?'
    meal_plan_target_protein = meal_plan.get('target_protein', '?') if meal_plan else '?'
    meals_today_xml = _format_meals_today_xml(ctx.get('meals_today'), meal_plan, meal_plan_type)
    weekly_meals_text = _format_weekly_meals(ctx.get('weekly_meals_summary', []))
    physical_assessment_text = _format_physical(ctx.get('physical_assessment'))
    body_measurements_text = _format_measurements(ctx.get('body_measurements'))
    goal_text = _format_goal(ctx.get('goal'))
    exercise_history_text = _format_exercise_history(ctx.get('exercise_history', {}))
    exercise_analysis_text = _format_exercise_analysis(ctx.get('exercise_analysis', {}))
    today_sets_text = _format_today_sets(ctx.get('today_sets', {}))
    run_history_text = _format_runs(ctx.get('run_history', []))
    week_schedule_text = _format_week_schedule(ctx.get('week_schedule', []), ctx.get('completed_days_this_week', []))
    schedule_notes = ctx.get('schedule_notes', '')
    next_week_text = _format_next_week_prescriptions(ctx.get('next_week_prescriptions', []))
    supplements_text = ', '.join(supp_taken) if supp_taken else 'None logged'
    equipment_text = ', '.join(ctx.get('equipment', [])) or 'Not specified'
    intake_report = ctx.get('intake_report', 'No intake completed yet.') or 'No intake completed yet.'
    scheduled_activities = ctx.get('scheduled_activities', '')
    coach_memories_text = _format_memories(ctx.get('coach_memories', []))
    missed_checkin_today = bool(ctx.get('missed_checkin_today'))

    # Load user rules from CoachRule
    from models import CoachRule
    user_id = ctx.get('user_id')
    user_rules = []
    if user_id:
        rules = CoachRule.query.filter_by(user_id=user_id, active=True).order_by(CoachRule.created_at).limit(25).all()
        user_rules = [{"rule_text": r.rule_text, "category": r.category} for r in rules]

    return {
        "minor_warning": minor_warning,
        "athlete_name": athlete_name,
        "tone": tone,
        "day_name": day_name,
        "date_str": date_str,
        "today_text": today_text,
        "week": week,
        "phase_label": phase_label,
        "phase_focus": phase_focus,
        "phase_deficit": phase_deficit,
        "meal_plan_type": meal_plan_type,
        "meal_plan_target_cal": meal_plan_target_cal,
        "meal_plan_target_protein": meal_plan_target_protein,
        "meals_today_xml": meals_today_xml,
        "weekly_meals_text": weekly_meals_text,
        "workout_summary": workout_summary,
        "bw_summary": bw_summary,
        "physical_assessment_text": physical_assessment_text,
        "body_measurements_text": body_measurements_text,
        "garmin_summary": garmin_summary,
        "readiness_summary": readiness_summary,
        "checkin_summary": checkin_summary,
        "missed_checkin_today": missed_checkin_today,
        "goal_text": goal_text,
        "exercise_history_text": exercise_history_text,
        "exercise_analysis_text": exercise_analysis_text,
        "today_sets_text": today_sets_text,
        "session_analysis_str": session_analysis_str,
        "weekly_summary_str": weekly_summary_str,
        "run_history_text": run_history_text,
        "week_schedule_text": week_schedule_text,
        "schedule_notes": schedule_notes,
        "next_week_text": next_week_text,
        "supplements_text": supplements_text,
        "equipment_text": equipment_text,
        "intake_report": intake_report,
        "scheduled_activities": scheduled_activities,
        "coach_memories_text": coach_memories_text,
        "food_safety": food_safety,
        "fasting_section": fasting_section,
        "selected_food_summary": selected_food_summary,
        "user_rules": user_rules,
    }


def _render_prompt_template(template_vars):
    """Load and render the Jinja2 coach prompt template."""
    from jinja2 import Environment, FileSystemLoader, Undefined
    prompt_dir = os.path.join(os.path.dirname(__file__), 'prompts')
    env = Environment(loader=FileSystemLoader(prompt_dir), autoescape=False, undefined=Undefined)
    template = env.get_template('coach_system.jinja2')
    return template.render(**template_vars)


def _build_system_prompt(ctx):
    """Build the full system prompt."""
    try:
        template_vars = _compute_template_vars(ctx)
        result = _render_prompt_template(template_vars)
        if not result or len(result) < 100:
            print(f"[COACH] WARNING: Prompt too short ({len(result) if result else 0} chars)")
        return result
    except Exception as e:
        import traceback
        print(f"[COACH] FATAL: Prompt template failed: {e}")
        traceback.print_exc()
        # Emergency fallback — basic coach identity so the response isn't blank
        return f"You are Coach Erik. The athlete's name is {ctx.get('athlete_name', 'Athlete')}. Be direct, data-driven, and coach them through their 12-week program."


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

    # Include last 40 messages (was 20 — too few for weekly context)
    for msg in filtered[-40:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
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
