"""
goal_engine.py - Core engine for 12Weeks fitness app.

Computes personalized training goals, calorie targets, weight projections,
and phase plans. This is NOT a reasonable plan. The person committed to
12 weeks of no excuses, no alcohol, 5:30am daily. We compute exactly
what it takes to hit the goal.
"""

import math

CLAUDE_SONNET = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Actor lookup table
# ---------------------------------------------------------------------------

_ACTOR_GOALS = {
    # Generic descriptions as fallback — AI classification is primary
    "athletic": "recomp", "lean": "recomp", "fit": "recomp", "toned": "recomp",
    "muscular": "bulk", "jacked": "bulk", "huge": "bulk", "big": "bulk",
    "shredded": "cut", "ripped": "cut", "six pack": "cut", "abs": "cut",
}


def classify_physique_goal(actor_answer):
    """Use AI to classify a physique reference into cut/bulk/recomp.
    Called during intake when the user names their goal physique."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=10.0)
        response = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=10,
            system="Classify the physique goal into exactly one word: cut, bulk, or recomp.\n\ncut = lean, low body fat, defined muscles, visible abs (Brad Pitt Fight Club, Bruce Lee, Daniel Craig)\nbulk = big, massive, powerful, heavy muscle (The Rock, Thor, Arnold, Hulk)\nrecomp = athletic, balanced, functional muscle without extreme leanness or mass (Captain America, Iron Man, Spider-Man, Batman)\n\nRespond with ONLY one word: cut, bulk, or recomp",
            messages=[{"role": "user", "content": f"Physique goal: {actor_answer}"}],
        )
        result = response.content[0].text.strip().lower()
        if result in ("cut", "bulk", "recomp"):
            return result
    except Exception:
        pass
    return None

# Target body fat percentages by goal and sex
_TARGET_BF = {
    "cut":   {"male": 0.08, "female": 0.16},
    "bulk":  {"male": 0.13, "female": 0.22},
    "recomp": {"male": 0.11, "female": 0.19},
}


def detect_goal(actor_answer, sex="male", current_weight=None, current_bf_estimate=None):
    """Detect goal type from actor/physique answer.

    Looks up the actor in a table of known physique references and returns
    the goal type plus target body composition numbers.

    Args:
        actor_answer: Free-text answer naming a physique goal (actor name).
        sex: "male" or "female". Defaults to "male".
        current_weight: Current weight in lbs (used to estimate target weight).
        current_bf_estimate: Current estimated body fat as a decimal (e.g. 0.25).

    Returns:
        dict with keys:
            goal_type: "cut", "bulk", or "recomp"
            target_bf: target body fat as decimal
            target_weight: estimated target weight in lbs (or None if
                           current_weight/current_bf not provided)
    """
    normalized = actor_answer.strip().lower()

    # Try generic keyword matches first (athletic, muscular, shredded, etc.)
    goal_type = _ACTOR_GOALS.get(normalized)
    if goal_type is None:
        for key, val in _ACTOR_GOALS.items():
            if key in normalized or normalized in key:
                goal_type = val
                break

    # If no keyword match, classify on the fly with AI
    if goal_type is None and normalized:
        goal_type = classify_physique_goal(actor_answer)

    # Default to recomp — safest when we don't know the user's intent
    if goal_type is None:
        goal_type = "recomp"

    target_bf = _TARGET_BF[goal_type][sex]

    target_weight = None
    if current_weight is not None and current_bf_estimate is not None:
        lean_mass = current_weight * (1 - current_bf_estimate)
        if goal_type == "cut":
            target_weight = round(lean_mass / (1 - target_bf), 1)
        elif goal_type == "recomp":
            target_weight = round(lean_mass / (1 - target_bf), 1)
        elif goal_type == "bulk":
            # Bulk: target is current lean mass + expected gains at target bf
            # Estimate ~8-12 lbs lean mass gain possible in 12 weeks for
            # a dedicated trainee, use 10 as midpoint
            estimated_lean_gain = 10
            target_weight = round((lean_mass + estimated_lean_gain) / (1 - target_bf), 1)

    return {
        "goal_type": goal_type,
        "target_bf": target_bf,
        "target_weight": target_weight,
    }


def compute_tdee(weight_lbs, height_in, age, sex, activity_multiplier=1.55):
    """Compute TDEE using Mifflin-St Jeor equation.

    Default activity multiplier of 1.55 assumes moderate activity
    (desk job + 4-6 training sessions/week).

    Args:
        weight_lbs: Body weight in pounds.
        height_in: Height in inches.
        age: Age in years.
        sex: "male" or "female".
        activity_multiplier: Activity factor. Default 1.7.

    Returns:
        dict: {"bmr": int, "tdee": int}
    """
    weight_kg = weight_lbs / 2.205
    height_cm = height_in * 2.54

    if sex == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    tdee = bmr * activity_multiplier

    return {"bmr": int(round(bmr)), "tdee": int(round(tdee))}


def compute_targets(tdee, goal_type, weight_lbs, age=None, target_weight=None, weeks=12):
    """Compute daily macro targets based on goal type.

    For CUT: deficit computed from weight loss goal, not a fixed percentage.
    For BULK: moderate surplus, solid protein, higher carbs for fuel.
    For RECOMP: slight deficit, high protein, balanced macros.

    Args:
        tdee: Total daily energy expenditure in calories.
        goal_type: "cut", "bulk", or "recomp".
        weight_lbs: Current body weight in pounds.
        target_weight: Goal weight in lbs (used to compute deficit for cuts).
        weeks: Weeks remaining in program (default 12).

    Returns:
        dict: {"calories": int, "protein": int, "carbs": int, "fat": int}
            Protein, carbs, fat are in grams.
    """
    if goal_type == "cut":
        # Use 1.0g/lb for aggressive cuts, 1.2g/lb for moderate cuts
        protein = round(1.0 * weight_lbs)
        fat = round(0.3 * weight_lbs)
        # Compute deficit from actual weight loss goal
        if target_weight and target_weight < weight_lbs and weeks > 0:
            weight_to_lose = weight_lbs - target_weight
            required_weekly = weight_to_lose / weeks
            required_daily_deficit = (required_weekly * 3500) / 7
            calories = max(int(round(tdee - required_daily_deficit)), 1200)
        else:
            # Fallback: 35% deficit
            calories = max(int(round(tdee * 0.65)), 1200)
        protein_cal = protein * 4
        fat_cal = fat * 9
        remaining_cal = max(calories - protein_cal - fat_cal, 0)
        carbs = max(int(remaining_cal / 4), 20)
    elif goal_type == "bulk":
        calories = int(round(tdee + 400))
        protein = round(1.0 * weight_lbs)
        fat = round(0.4 * weight_lbs)
        protein_cal = protein * 4
        fat_cal = fat * 9
        remaining_cal = max(calories - protein_cal - fat_cal, 0)
        carbs = int(remaining_cal / 4)
    elif goal_type == "recomp":
        calories = int(round(tdee - 100))
        protein = round(1.2 * weight_lbs)
        fat = round(0.35 * weight_lbs)
        protein_cal = protein * 4
        fat_cal = fat * 9
        remaining_cal = max(calories - protein_cal - fat_cal, 0)
        carbs = int(remaining_cal / 4)
    else:
        # Fallback to cut
        return compute_targets(tdee, "cut", weight_lbs)

    return {
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
    }


def compute_phase_plan(goal_type, starting_weight, target_weight, starting_bf_estimate=None):
    """Compute the phase split for the 12-week program.

    The AI decides whether to run a straight 12-week phase or split into
    sub-phases depending on how aggressive the transformation needs to be.

    Args:
        goal_type: "cut", "bulk", or "recomp".
        starting_weight: Current weight in lbs.
        target_weight: Goal weight in lbs.
        starting_bf_estimate: Estimated starting body fat as decimal (e.g. 0.25).
            Optional but improves planning.

    Returns:
        list of phase dicts, e.g.:
            [{"weeks": "1-12", "type": "cut", "weekly_rate": 2.5, "notes": "..."}]
    """
    total_change = target_weight - starting_weight  # negative for cut
    weekly_rate = abs(total_change) / 12

    phases = []

    if goal_type == "cut":
        if weekly_rate <= 3.0:
            # Manageable deficit -- straight 12-week cut
            phases.append({
                "weeks": "1-12",
                "type": "cut",
                "weekly_rate": round(weekly_rate, 1),
                "notes": f"Straight cut: {abs(total_change):.0f} lbs in 12 weeks "
                         f"({weekly_rate:.1f} lbs/week).",
            })
        else:
            # Extreme deficit -- break into aggressive phases
            # Phase 1: aggressive fasting cut (weeks 1-4)
            # Phase 2: moderate cut with refeed (weeks 5-8)
            # Phase 3: final push (weeks 9-12)
            p1_rate = weekly_rate * 1.3  # front-load the loss
            p3_rate = weekly_rate * 1.1
            p2_rate = weekly_rate * 0.7  # slower middle for recovery
            phases.append({
                "weeks": "1-4",
                "type": "aggressive_cut",
                "weekly_rate": round(p1_rate, 1),
                "notes": "Aggressive fasting phase. OMAD or 20:4. "
                         "Electrolyte supplementation required. "
                         "High protein to preserve muscle.",
            })
            phases.append({
                "weeks": "5-8",
                "type": "cut",
                "weekly_rate": round(p2_rate, 1),
                "notes": "Moderate cut with weekly refeed day. "
                         "18:6 fasting. Prevents metabolic adaptation.",
            })
            phases.append({
                "weeks": "9-12",
                "type": "aggressive_cut",
                "weekly_rate": round(p3_rate, 1),
                "notes": "Final push. Tighten up for the finish. "
                         "20:4 fasting. Visual results lock in here.",
            })

    elif goal_type == "bulk":
        if starting_bf_estimate is not None and starting_bf_estimate > 0.20:
            # Too fat to bulk right away -- mini cut first
            cut_weeks = 4
            bulk_weeks = 8
            phases.append({
                "weeks": "1-4",
                "type": "cut",
                "weekly_rate": 2.0,
                "notes": f"Mini-cut first. Starting BF {starting_bf_estimate*100:.0f}% "
                         "is too high to bulk cleanly. Drop to ~18% then bulk.",
            })
            phases.append({
                "weeks": "5-12",
                "type": "bulk",
                "weekly_rate": round(abs(total_change) / bulk_weeks, 1) if total_change > 0 else 0.5,
                "notes": "Clean bulk phase. Surplus of 300-500 cal. "
                         "Progressive overload focus.",
            })
        else:
            phases.append({
                "weeks": "1-12",
                "type": "bulk",
                "weekly_rate": round(weekly_rate, 1),
                "notes": f"Straight bulk: {total_change:.0f} lbs in 12 weeks. "
                         "Controlled surplus, progressive overload.",
            })

    elif goal_type == "recomp":
        phases.append({
            "weeks": "1-12",
            "type": "recomp",
            "weekly_rate": round(weekly_rate, 1),
            "notes": "12-week recomp. Slight deficit on rest days, "
                     "maintenance on training days. Body composition "
                     "shifts without dramatic scale change.",
        })

    return phases


def compute_day_calories(base_calories, goal_type, day_type, weight_lbs=None):
    """Vary calories based on training day type.

    Different day types get different calorie and macro allocations to
    optimize performance and recovery.

    Args:
        base_calories: Base daily calorie target.
        goal_type: "cut", "bulk", or "recomp".
        day_type: "training", "rest", "heavy", or "long_run".
        weight_lbs: Current weight in lbs (needed for macro calculation).
            If None, macros are estimated from calorie target.

    Returns:
        dict: {"calories": int, "protein": int, "carbs": int, "fat": int}
    """
    if weight_lbs is None:
        raise ValueError("weight_lbs is required — never default to a hardcoded value")

    if goal_type == "cut":
        protein = round(1.2 * weight_lbs)
        fat = round(0.35 * weight_lbs)
        if day_type == "fast_day":
            # Full fast — zero calories. Water, black coffee, electrolytes only.
            return {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
        elif day_type == "training":
            calories = base_calories
        elif day_type == "rest":
            calories = base_calories - 200
        elif day_type in ("heavy", "long_run"):
            calories = base_calories
            # +100 carbs for heavy/long days (accounted below)
        else:
            calories = base_calories
    elif goal_type == "bulk":
        protein = round(1.0 * weight_lbs)
        fat = round(0.4 * weight_lbs)
        if day_type == "fast_day":
            return {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
        elif day_type == "training":
            calories = base_calories + 200
        elif day_type == "rest":
            calories = base_calories
        elif day_type in ("heavy", "long_run"):
            calories = base_calories + 200
        else:
            calories = base_calories
    else:  # recomp
        protein = round(1.2 * weight_lbs)
        fat = round(0.35 * weight_lbs)
        if day_type == "fast_day":
            return {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
        elif day_type == "training":
            calories = base_calories + 50
        elif day_type == "rest":
            calories = base_calories - 150
        elif day_type in ("heavy", "long_run"):
            calories = base_calories + 50
        else:
            calories = base_calories

    protein_cal = protein * 4
    fat_cal = fat * 9
    remaining_cal = max(calories - protein_cal - fat_cal, 0)
    carbs = max(int(remaining_cal / 4), 20)

    # For cuts: flat calories across all eating days to maximize deficit
    # For bulk/recomp: heavy days get extra carbs for training fuel
    if goal_type != "cut" and day_type in ("heavy", "long_run"):
        carbs += 100
        calories += 400  # 100 carbs * 4 cal/g

    return {
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
    }


def determine_fasting_protocol(goal_type, daily_calories):
    """Determine the appropriate intermittent fasting protocol.

    Matched to calorie target: lower calories need tighter eating windows
    to make meals satisfying. Aggressive deficits trigger electrolyte
    supplementation to prevent cramping and fatigue.

    Args:
        goal_type: "cut", "bulk", or "recomp".
        daily_calories: Target daily calorie intake.

    Returns:
        dict: {
            "protocol": "16_8" | "18_6" | "20_4" | "omad" | "none",
            "eating_window_hours": int,
            "electrolytes": bool,
            "notes": str
        }
    """
    if daily_calories >= 2500:
        return {
            "protocol": "none",
            "eating_window_hours": 16,
            "electrolytes": False,
            "notes": "Calorie target high enough that fasting is optional. "
                     "Eat across a normal window.",
        }
    elif daily_calories >= 1500:
        return {
            "protocol": "16_8",
            "eating_window_hours": 8,
            "electrolytes": False,
            "notes": "16:8 fasting. Eat noon-8pm. Coffee and water in the morning. "
                     "Two to three meals in the window.",
        }
    elif daily_calories >= 1200:
        return {
            "protocol": "18_6",
            "eating_window_hours": 6,
            "electrolytes": True,
            "notes": "18:6 fasting. "
                     "Electrolyte supplementation required: sodium, potassium, "
                     "magnesium. Black coffee ok. Keeps meals dense and satisfying "
                     "at low calorie targets.",
        }
    else:
        return {
            "protocol": "omad",
            "eating_window_hours": 1,
            "electrolytes": True,
            "notes": "OMAD (one meal a day) or alternate day fasting. "
                     "Extreme deficit -- electrolytes are NON-NEGOTIABLE. "
                     "2-3g sodium, 1g potassium, 400mg magnesium minimum. "
                     "This is temporary and aggressive. Monitor energy levels.",
        }


def project_weight_curve(starting_weight, target_weight, tdee, daily_calories,
                          weeks=12, height_in=70, age=30, sex="male"):
    """Project week-by-week weight change with metabolic modeling.

    Models water/glycogen effects in weeks 1-2, recalculates BMR as weight
    drops, and factors in training adaptation.

    Args:
        starting_weight: Starting weight in lbs.
        target_weight: Target weight in lbs.
        tdee: Starting TDEE in calories.
        daily_calories: Daily calorie intake target.
        weeks: Number of weeks to project (default 12).
        height_in: Height in inches (for BMR recalc).
        age: Age in years (for BMR recalc).
        sex: "male" or "female" (for BMR recalc).

    Returns:
        list of dicts: [{"week": 1, "projected": 215.2, "tdee": 2800}, ...]
    """
    projection = []
    current_weight = starting_weight
    current_tdee = tdee
    gaining = daily_calories > tdee  # bulk mode

    for week in range(1, weeks + 1):
        # Daily deficit/surplus
        daily_delta_cal = daily_calories - current_tdee

        # Convert to lbs: 3500 cal = 1 lb of fat
        weekly_delta_lbs = (daily_delta_cal * 7) / 3500

        # Week 1-2: water/glycogen effect (1.5x rate for cuts, 1.3x for bulk)
        if week <= 2:
            if not gaining:
                weekly_delta_lbs *= 1.5
            else:
                weekly_delta_lbs *= 1.3

        # Training adaptation: TDEE bump from increased fitness
        # Ramps up from week 3, peaks at week 6
        if week >= 3:
            adaptation_bump = min((week - 2) * 20, 100)  # up to +100 cal/day
        else:
            adaptation_bump = 0

        # For bulk: cap lean mass gain at 0.5 lb/week
        if gaining and weekly_delta_lbs > 0.5:
            # Excess above 0.5 lb/week is fat -- still count it but note it
            pass

        current_weight += weekly_delta_lbs
        current_weight = round(current_weight, 1)

        # Recalculate TDEE based on new weight
        new_bmr_data = compute_tdee(current_weight, height_in, age, sex)
        current_tdee = new_bmr_data["tdee"] + adaptation_bump

        projection.append({
            "week": week,
            "projected": current_weight,
            "tdee": current_tdee,
        })

    return projection


def recalibrate_projection(current_weight, current_week, original_projection,
                            tdee_params):
    """Recalibrate weight projection after a real weigh-in.

    Called every Sunday. Compares actual weight to projected, adjusts
    TDEE and calorie targets for remaining weeks.

    Args:
        current_weight: Actual weigh-in weight in lbs.
        current_week: Which week just completed (1-12).
        original_projection: The original projection list from
            project_weight_curve().
        tdee_params: Dict with keys needed to recompute TDEE:
            {"height_in", "age", "sex", "daily_calories", "target_weight"}

    Returns:
        dict: {
            "updated_projection": [...],
            "new_daily_calories": int,
            "status": "ahead" | "on_track" | "behind",
            "adjustment_note": str
        }
    """
    # Find projected weight for this week
    projected_entry = None
    for entry in original_projection:
        if entry["week"] == current_week:
            projected_entry = entry
            break

    if projected_entry is None:
        projected_weight = current_weight
    else:
        projected_weight = projected_entry["projected"]

    delta = current_weight - projected_weight  # negative = ahead of schedule

    # Determine status
    tolerance = 1.0  # lbs
    if delta < -tolerance:
        status = "ahead"
    elif delta > tolerance:
        status = "behind"
    else:
        status = "on_track"

    # Recalculate TDEE from actual weight
    height_in = tdee_params.get("height_in", 70)
    age = tdee_params.get("age", 30)
    sex = tdee_params.get("sex", "male")
    daily_calories = tdee_params.get("daily_calories")
    target_weight = tdee_params.get("target_weight")

    new_tdee_data = compute_tdee(current_weight, height_in, age, sex)
    new_tdee = new_tdee_data["tdee"]

    remaining_weeks = 12 - current_week
    if remaining_weeks <= 0:
        remaining_weeks = 1

    # Adjust calories based on status
    adjustment_note = ""
    new_daily_calories = daily_calories

    if status == "ahead":
        # Ahead of schedule -- consider adding calories to preserve muscle
        cal_bump = min(int(abs(delta) * 50), 200)
        new_daily_calories = daily_calories + cal_bump
        adjustment_note = (
            f"Ahead of projection by {abs(delta):.1f} lbs. "
            f"Adding {cal_bump} cal/day to preserve muscle mass. "
            f"New target: {new_daily_calories} cal/day."
        )
    elif status == "behind":
        # Behind schedule -- tighten deficit
        weight_to_lose = current_weight - target_weight
        required_weekly = weight_to_lose / remaining_weeks
        required_daily_deficit = (required_weekly * 3500) / 7
        new_daily_calories = max(int(new_tdee - required_daily_deficit), 1000)
        adjustment_note = (
            f"Behind projection by {delta:.1f} lbs. "
            f"Need {required_weekly:.1f} lbs/week for remaining {remaining_weeks} weeks. "
            f"Tightening to {new_daily_calories} cal/day. "
            f"FLAG FOR COACH REVIEW."
        )
    else:
        adjustment_note = (
            f"On track. Delta {delta:+.1f} lbs from projection. "
            f"Maintaining {daily_calories} cal/day."
        )
        new_daily_calories = daily_calories

    # Project remaining weeks from current actual weight
    gaining = new_daily_calories > new_tdee
    updated_projection = []
    weight = current_weight

    for week in range(current_week + 1, 13):
        daily_delta_cal = new_daily_calories - new_tdee
        weekly_delta_lbs = (daily_delta_cal * 7) / 3500

        if gaining and weekly_delta_lbs > 0.5:
            pass  # still track it

        weight += weekly_delta_lbs
        weight = round(weight, 1)

        # Recalc TDEE
        recalc = compute_tdee(weight, height_in, age, sex)
        new_tdee = recalc["tdee"]

        updated_projection.append({
            "week": week,
            "projected": weight,
            "tdee": new_tdee,
        })

    return {
        "updated_projection": updated_projection,
        "new_daily_calories": new_daily_calories,
        "status": status,
        "adjustment_note": adjustment_note,
    }


def adjust_workout(base_workout, goal_type, constraints=None):
    """Modify workout structure based on goal type and constraints.

    Adjusts volume, rest periods, cardio, and exercise selection to match
    the current training goal. Applies equipment and time constraints.

    Args:
        base_workout: Dict representing a workout. Expected structure:
            {
                "name": "Upper Body A",
                "exercises": [
                    {
                        "name": "Bench Press",
                        "sets": 4,
                        "reps": "8-10",
                        "rest_seconds": 90,
                        "equipment": "barbell",
                        "category": "compound" | "isolation" | "cardio",
                    },
                    ...
                ],
                "cardio": {"type": "HIIT", "duration_min": 20},
            }
        goal_type: "cut", "bulk", or "recomp".
        constraints: Optional dict:
            {
                "available_equipment": ["dumbbells", "pull_up_bar", "bands", ...],
                "max_duration_min": 60,
                "injuries": ["shoulder", ...],
            }

    Returns:
        dict: Modified workout in the same structure as input.
    """
    if constraints is None:
        constraints = {}

    import copy
    workout = copy.deepcopy(base_workout)

    available_equipment = constraints.get("available_equipment")
    max_duration = constraints.get("max_duration_min")
    injuries = constraints.get("injuries", [])

    exercises = workout.get("exercises", [])

    # Equipment swap table
    _EQUIPMENT_SWAPS = {
        "barbell": "dumbbells",
        "cable_machine": "bands",
        "leg_press": "dumbbells",
        "smith_machine": "dumbbells",
    }

    for ex in exercises:
        # --- Goal-based adjustments ---
        if goal_type == "bulk":
            # Increase volume: +1 set, keep reps moderate
            ex["sets"] = min(ex.get("sets", 4) + 1, 6)
            if ex.get("reps") == "8-10":
                ex["reps"] = "8-10"
            elif isinstance(ex.get("reps"), str) and "12" in ex.get("reps", ""):
                ex["reps"] = "8-10"
            # Longer rest for strength
            ex["rest_seconds"] = max(ex.get("rest_seconds", 90), 120)

        elif goal_type == "cut":
            # Keep program as-is (designed for cutting), shorter rest
            ex["rest_seconds"] = min(ex.get("rest_seconds", 90), 90)

        elif goal_type == "recomp":
            # Moderate volume, maintain strength
            ex["rest_seconds"] = min(ex.get("rest_seconds", 90), 105)

        # --- Equipment constraints ---
        if available_equipment is not None:
            eq = ex.get("equipment", "")
            if eq and eq not in available_equipment:
                swap = _EQUIPMENT_SWAPS.get(eq)
                if swap and swap in available_equipment:
                    ex["equipment"] = swap
                    ex["name"] = ex["name"] + f" (DB)" if swap == "dumbbells" else ex["name"]
                elif "bands" in available_equipment:
                    ex["equipment"] = "bands"
                    ex["name"] = ex["name"] + " (banded)"

        # --- Injury constraints ---
        if injuries:
            for injury in injuries:
                injury_lower = injury.lower()
                name_lower = ex.get("name", "").lower()
                if injury_lower == "shoulder" and any(
                    kw in name_lower for kw in ["overhead", "press", "lateral raise", "upright row"]
                ):
                    ex["notes"] = ex.get("notes", "") + " MODIFY: shoulder constraint. Reduce ROM or substitute."
                if injury_lower == "knee" and any(
                    kw in name_lower for kw in ["squat", "lunge", "leg press", "jump"]
                ):
                    ex["notes"] = ex.get("notes", "") + " MODIFY: knee constraint. Reduce depth or substitute."
                if injury_lower == "back" and any(
                    kw in name_lower for kw in ["deadlift", "row", "good morning"]
                ):
                    ex["notes"] = ex.get("notes", "") + " MODIFY: back constraint. Reduce load or substitute."

    # --- Cardio adjustments ---
    cardio = workout.get("cardio", {})
    if goal_type == "bulk":
        # Reduce HIIT, add steady-state
        if cardio.get("type") == "HIIT":
            cardio["type"] = "steady_state"
            cardio["duration_min"] = 25
            cardio["notes"] = "Switched from HIIT to steady-state to support recovery during bulk."
    elif goal_type == "cut":
        # Keep HIIT, potentially add evening session for extreme deficit
        if cardio.get("duration_min", 0) < 20:
            cardio["duration_min"] = 20
        cardio.setdefault("notes", "")
        cardio["notes"] += " Consider adding a 20-min evening walk for additional calorie burn."
    elif goal_type == "recomp":
        # Moderate cardio
        cardio["duration_min"] = min(cardio.get("duration_min", 20), 25)

    workout["cardio"] = cardio
    workout["exercises"] = exercises

    # --- Time constraints ---
    if max_duration is not None:
        # Estimate time: ~4 min per set (including rest) + cardio
        total_sets = sum(ex.get("sets", 3) for ex in exercises)
        estimated_min = total_sets * 4 + cardio.get("duration_min", 0)
        if estimated_min > max_duration:
            # Drop isolation exercises first, then reduce sets
            compound = [e for e in exercises if e.get("category") == "compound"]
            isolation = [e for e in exercises if e.get("category") != "compound"]
            # Keep all compounds, trim isolation
            while isolation and estimated_min > max_duration:
                isolation.pop()
                total_sets = sum(e.get("sets", 3) for e in compound + isolation)
                estimated_min = total_sets * 4 + cardio.get("duration_min", 0)
            exercises = compound + isolation
            workout["exercises"] = exercises

    return workout
