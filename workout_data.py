"""All 12 weeks of workout data."""

# ─── MEAL PLANS ─────────────────────────────────────────────────────────────
# Day types: heavy_lift, long_run, moderate, rest, deload, fast_day
# Default timing: 16:8 intermittent fasting, eating window 11am-7pm
# Fasted training at 5:30am with black coffee

MEAL_PLANS = {
    "heavy_lift": {
        "label": "Heavy Lift Day",
        "targetCal": 1800,
        "targetProtein": 155,
        "targetCarbs": 100,
        "targetFat": 80,
        "note": "High protein, moderate carbs. Fuel recovery from heavy lifting.",
        "meals": [
            {
                "time": "5:30am",
                "name": "Pre-Workout",
                "optional": False,
                "foods": [
                    {"item": "Black coffee", "portion": "12 oz", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                ],
            },
            {
                "time": "9:00am",
                "name": "Post-Workout Shake",
                "optional": False,
                "foods": [
                    {"item": "Whey protein shake", "portion": "1 scoop + water", "cal": 130, "protein": 25, "carbs": 3, "fat": 2},
                ],
            },
            {
                "time": "11:00am",
                "name": "Break Fast - Chicken Salad",
                "optional": False,
                "foods": [
                    {"item": "Grilled chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "Mixed greens", "portion": "2 cups", "cal": 15, "protein": 2, "carbs": 2, "fat": 0},
                    {"item": "Avocado", "portion": "1/2", "cal": 120, "protein": 1, "carbs": 6, "fat": 11},
                    {"item": "Olive oil + lemon dressing", "portion": "1 tbsp", "cal": 120, "protein": 0, "carbs": 0, "fat": 14},
                    {"item": "Cherry tomatoes", "portion": "1/2 cup", "cal": 15, "protein": 0, "carbs": 3, "fat": 0},
                ],
            },
            {
                "time": "2:30pm",
                "name": "Eggs + Greens",
                "optional": False,
                "foods": [
                    {"item": "Eggs, scrambled", "portion": "4 large", "cal": 280, "protein": 24, "carbs": 2, "fat": 20},
                    {"item": "Spinach", "portion": "1 cup", "cal": 7, "protein": 1, "carbs": 1, "fat": 0},
                    {"item": "Salsa", "portion": "2 tbsp", "cal": 10, "protein": 0, "carbs": 2, "fat": 0},
                    {"item": "Almonds", "portion": "1 oz (23 nuts)", "cal": 164, "protein": 6, "carbs": 6, "fat": 14},
                ],
            },
            {
                "time": "6:30pm",
                "name": "Dinner - Chicken + Rice",
                "optional": False,
                "foods": [
                    {"item": "Baked chicken breast", "portion": "8 oz", "cal": 370, "protein": 70, "carbs": 0, "fat": 8},
                    {"item": "White rice", "portion": "1 cup cooked", "cal": 205, "protein": 4, "carbs": 45, "fat": 0},
                    {"item": "Steamed broccoli", "portion": "1 cup", "cal": 55, "protein": 4, "carbs": 11, "fat": 0},
                ],
            },
        ],
    },
    "long_run": {
        "label": "Long Run Day",
        "targetCal": 2050,
        "targetProtein": 160,
        "targetCarbs": 130,
        "targetFat": 75,
        "note": "More carbs to fuel the long run. Break fast earlier if needed.",
        "meals": [
            {
                "time": "5:30am",
                "name": "Pre-Workout",
                "optional": False,
                "foods": [
                    {"item": "Black coffee", "portion": "12 oz", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                ],
            },
            {
                "time": "9:00am",
                "name": "Post-Workout Shake + Banana",
                "optional": False,
                "foods": [
                    {"item": "Whey protein shake", "portion": "1 scoop + water", "cal": 130, "protein": 25, "carbs": 3, "fat": 2},
                    {"item": "Banana", "portion": "1 medium", "cal": 105, "protein": 1, "carbs": 27, "fat": 0},
                ],
            },
            {
                "time": "11:00am",
                "name": "Break Fast - Omelette + Salad",
                "optional": False,
                "foods": [
                    {"item": "Eggs, omelette", "portion": "4 large", "cal": 280, "protein": 24, "carbs": 2, "fat": 20},
                    {"item": "Spinach (in omelette)", "portion": "1 cup", "cal": 7, "protein": 1, "carbs": 1, "fat": 0},
                    {"item": "Cheddar cheese", "portion": "1 oz", "cal": 113, "protein": 7, "carbs": 0, "fat": 9},
                    {"item": "Side salad (mixed greens)", "portion": "1 cup", "cal": 10, "protein": 1, "carbs": 1, "fat": 0},
                    {"item": "Olive oil dressing", "portion": "1 tbsp", "cal": 120, "protein": 0, "carbs": 0, "fat": 14},
                ],
            },
            {
                "time": "2:30pm",
                "name": "Chicken + Sweet Potato",
                "optional": False,
                "foods": [
                    {"item": "Grilled chicken breast", "portion": "8 oz", "cal": 370, "protein": 70, "carbs": 0, "fat": 8},
                    {"item": "Sweet potato", "portion": "1 medium", "cal": 103, "protein": 2, "carbs": 24, "fat": 0},
                    {"item": "Mixed greens", "portion": "1 cup", "cal": 10, "protein": 1, "carbs": 1, "fat": 0},
                ],
            },
            {
                "time": "6:30pm",
                "name": "Dinner - Chicken Salad Bowl",
                "optional": False,
                "foods": [
                    {"item": "Grilled chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "Quinoa", "portion": "1/2 cup cooked", "cal": 111, "protein": 4, "carbs": 20, "fat": 2},
                    {"item": "Mixed greens", "portion": "2 cups", "cal": 15, "protein": 2, "carbs": 2, "fat": 0},
                    {"item": "Avocado", "portion": "1/2", "cal": 120, "protein": 1, "carbs": 6, "fat": 11},
                    {"item": "Olive oil dressing", "portion": "1/2 tbsp", "cal": 60, "protein": 0, "carbs": 0, "fat": 7},
                ],
            },
        ],
    },
    "moderate": {
        "label": "Moderate Day",
        "targetCal": 1700,
        "targetProtein": 145,
        "targetCarbs": 90,
        "targetFat": 75,
        "note": "Moderate intensity day. Standard portions, lean protein focus.",
        "meals": [
            {
                "time": "5:30am",
                "name": "Pre-Workout",
                "optional": False,
                "foods": [
                    {"item": "Black coffee", "portion": "12 oz", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                ],
            },
            {
                "time": "11:00am",
                "name": "Break Fast - Eggs + Greens",
                "optional": False,
                "foods": [
                    {"item": "Eggs, scrambled", "portion": "3 large", "cal": 210, "protein": 18, "carbs": 1, "fat": 15},
                    {"item": "Spinach", "portion": "2 cups", "cal": 14, "protein": 2, "carbs": 2, "fat": 0},
                    {"item": "Avocado", "portion": "1/3", "cal": 80, "protein": 1, "carbs": 4, "fat": 7},
                    {"item": "Salsa", "portion": "2 tbsp", "cal": 10, "protein": 0, "carbs": 2, "fat": 0},
                ],
            },
            {
                "time": "2:30pm",
                "name": "Chicken + Greens",
                "optional": False,
                "foods": [
                    {"item": "Grilled chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "Mixed greens", "portion": "2 cups", "cal": 15, "protein": 2, "carbs": 2, "fat": 0},
                    {"item": "Olive oil dressing", "portion": "1 tbsp", "cal": 120, "protein": 0, "carbs": 0, "fat": 14},
                    {"item": "Hard boiled egg", "portion": "1 large", "cal": 70, "protein": 6, "carbs": 0, "fat": 5},
                ],
            },
            {
                "time": "6:30pm",
                "name": "Dinner - Chicken + Veggies",
                "optional": False,
                "foods": [
                    {"item": "Baked chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "White rice", "portion": "3/4 cup cooked", "cal": 154, "protein": 3, "carbs": 34, "fat": 0},
                    {"item": "Steamed asparagus", "portion": "1 cup", "cal": 27, "protein": 3, "carbs": 5, "fat": 0},
                    {"item": "Greek yogurt", "portion": "1/2 cup (plain)", "cal": 65, "protein": 9, "carbs": 4, "fat": 2},
                ],
            },
        ],
    },
    "rest": {
        "label": "Rest Day (16:8)",
        "targetCal": 1500,
        "targetProtein": 130,
        "targetCarbs": 70,
        "targetFat": 70,
        "note": "Rest day. Lower calories, maintain protein. Option to do a 24h fast instead (toggle below).",
        "meals": [
            {
                "time": "Morning",
                "name": "Hydration",
                "optional": False,
                "foods": [
                    {"item": "Black coffee", "portion": "12 oz", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                    {"item": "Water", "portion": "16 oz", "cal": 0, "protein": 0, "carbs": 0, "fat": 0},
                ],
            },
            {
                "time": "11:00am",
                "name": "Break Fast - Light Chicken Salad",
                "optional": False,
                "foods": [
                    {"item": "Grilled chicken breast", "portion": "5 oz", "cal": 233, "protein": 43, "carbs": 0, "fat": 5},
                    {"item": "Mixed greens", "portion": "2 cups", "cal": 15, "protein": 2, "carbs": 2, "fat": 0},
                    {"item": "Avocado", "portion": "1/3", "cal": 80, "protein": 1, "carbs": 4, "fat": 7},
                    {"item": "Olive oil dressing", "portion": "1/2 tbsp", "cal": 60, "protein": 0, "carbs": 0, "fat": 7},
                ],
            },
            {
                "time": "2:30pm",
                "name": "Eggs + Almonds",
                "optional": False,
                "foods": [
                    {"item": "Hard boiled eggs", "portion": "3 large", "cal": 210, "protein": 18, "carbs": 1, "fat": 15},
                    {"item": "Almonds", "portion": "1 oz", "cal": 164, "protein": 6, "carbs": 6, "fat": 14},
                ],
            },
            {
                "time": "6:30pm",
                "name": "Dinner - Chicken + Greens",
                "optional": False,
                "foods": [
                    {"item": "Baked chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "Steamed broccoli", "portion": "1 cup", "cal": 55, "protein": 4, "carbs": 11, "fat": 0},
                    {"item": "Spinach side salad", "portion": "1 cup", "cal": 7, "protein": 1, "carbs": 1, "fat": 0},
                    {"item": "Greek yogurt", "portion": "1/2 cup (plain)", "cal": 65, "protein": 9, "carbs": 4, "fat": 2},
                ],
            },
        ],
    },
    "fast_day": {
        "label": "Protein-Sparing Fast Day",
        "targetCal": 130,
        "targetProtein": 30,
        "targetCarbs": 2,
        "targetFat": 1,
        "note": "Protein-sparing modified fast. One whey shake to protect muscle, otherwise water/coffee/electrolytes only. No workout today — rest and recover. Break fast Monday at 11am. Max 1x/week. Only do this if training readiness is good and sleep has been solid.",
        "meals": [
            {
                "time": "All Day",
                "name": "Fast - Liquids Only + Protein",
                "optional": False,
                "foods": [
                    {"item": "Whey protein shake (water)", "portion": "1 scoop", "cal": 130, "protein": 30, "carbs": 2, "fat": 1},
                    {"item": "Water", "portion": "Unlimited", "cal": 0, "protein": 0, "carbs": 0, "fat": 0},
                    {"item": "Black coffee", "portion": "As needed", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                    {"item": "Electrolytes (salt, potassium)", "portion": "As needed", "cal": 0, "protein": 0, "carbs": 0, "fat": 0},
                ],
            },
        ],
    },
    "deload": {
        "label": "Deload Day",
        "targetCal": 1800,
        "targetProtein": 140,
        "targetCarbs": 120,
        "targetFat": 70,
        "note": "Deload week. Slightly more carbs for recovery and adaptation. Eat closer to maintenance.",
        "meals": [
            {
                "time": "5:30am",
                "name": "Pre-Workout",
                "optional": False,
                "foods": [
                    {"item": "Black coffee", "portion": "12 oz", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                ],
            },
            {
                "time": "11:00am",
                "name": "Break Fast - Omelette + Toast",
                "optional": False,
                "foods": [
                    {"item": "Eggs, omelette", "portion": "3 large", "cal": 210, "protein": 18, "carbs": 1, "fat": 15},
                    {"item": "Spinach (in omelette)", "portion": "1 cup", "cal": 7, "protein": 1, "carbs": 1, "fat": 0},
                    {"item": "Cheddar cheese", "portion": "1 oz", "cal": 113, "protein": 7, "carbs": 0, "fat": 9},
                    {"item": "Whole wheat toast", "portion": "1 slice", "cal": 80, "protein": 4, "carbs": 14, "fat": 1},
                    {"item": "Avocado", "portion": "1/3", "cal": 80, "protein": 1, "carbs": 4, "fat": 7},
                ],
            },
            {
                "time": "2:30pm",
                "name": "Chicken + Sweet Potato",
                "optional": False,
                "foods": [
                    {"item": "Grilled chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "Sweet potato", "portion": "1 medium", "cal": 103, "protein": 2, "carbs": 24, "fat": 0},
                    {"item": "Mixed greens", "portion": "1 cup", "cal": 10, "protein": 1, "carbs": 1, "fat": 0},
                ],
            },
            {
                "time": "6:30pm",
                "name": "Dinner - Chicken + Rice + Veggies",
                "optional": False,
                "foods": [
                    {"item": "Baked chicken breast", "portion": "6 oz", "cal": 280, "protein": 52, "carbs": 0, "fat": 6},
                    {"item": "White rice", "portion": "1 cup cooked", "cal": 205, "protein": 4, "carbs": 45, "fat": 0},
                    {"item": "Steamed broccoli", "portion": "1 cup", "cal": 55, "protein": 4, "carbs": 11, "fat": 0},
                    {"item": "Greek yogurt", "portion": "1/2 cup (plain)", "cal": 65, "protein": 9, "carbs": 4, "fat": 2},
                ],
            },
        ],
    },
}

# Day-of-week to meal type mapping
DAY_MEAL_TYPES = {
    "Mon": "heavy_lift",
    "Tue": "long_run",
    "Wed": "heavy_lift",
    "Thu": "moderate",
    "Fri": "heavy_lift",
    "Sat": "moderate",
    "Sun": "fast_day",
}


def derive_meal_type(day_dict, weekday):
    """Derive meal-day type from a day's actual run + lift content rather
    than the weekday alone. DAY_MEAL_TYPES is a stale-by-design fallback;
    when the program rotates a long run from Tuesday to Sunday (Phase 2 did
    exactly this), the weekday map keeps carb-loading Tuesday for an
    intervals workout that doesn't need it. Real fix: read the day's run
    type and liftName.

    Returns one of: long_run, heavy_lift, moderate, fast_day, rest, deload.
    Falls back to DAY_MEAL_TYPES[weekday] when no run+lift signal is
    available (preserves Sunday=fast_day, etc.)."""
    run = (day_dict or {}).get("run") or {}
    rtype = (run.get("type") or "").lower()
    is_rest = bool((day_dict or {}).get("isRest"))
    lift_name = ((day_dict or {}).get("liftName") or "").strip().lower()
    # "Rest (Long Fasted Run)" reads as has_lift=True under a strict-equality
    # check; broaden to any liftName containing 'rest' so the long-fasted-run
    # day stays fast_day instead of getting reclassified as long_run.
    has_lift = bool(lift_name and "rest" not in lift_name)

    if is_rest:
        # No lifting day — defer to the weekday rotation default. Sunday is
        # fast_day even when paired with a fasted long run (the fast IS the
        # point — carb-loading like a non-fasted long_run day defeats it).
        return DAY_MEAL_TYPES.get(weekday, "rest")
    if rtype in ("z2_long", "long"):  # running coach emits "long", template "z2_long"
        return "long_run"
    # Heavy lift only when the liftName names it explicitly. Phase 2 marks
    # the two real strength sessions as 'Lower POWER' and 'HEAVY Lower';
    # everything else (volume, hypertrophy, accessory, full-body lighter)
    # is moderate. Reserving heavy_lift for true max-strength days keeps
    # the calorie/carb bump where it actually matters.
    is_heavy = any(kw in lift_name for kw in ("power", "heavy", "max"))
    if rtype in ("hiit", "vo2", "threshold", "tempo", "hill"):
        # Intervals/quality: short high-intensity. Fuel, but not endurance carbs.
        return "heavy_lift" if is_heavy else "moderate"
    if rtype in ("z2", "streak"):
        return "heavy_lift" if is_heavy else "moderate"
    if has_lift:
        return "heavy_lift" if is_heavy else "moderate"
    return DAY_MEAL_TYPES.get(weekday, "moderate")


def get_meal_plan(meal_type):
    """Return the full meal plan dict for a given meal type."""
    return dict(MEAL_PLANS.get(meal_type, MEAL_PLANS["moderate"]))


# ─── WARM-UP PROTOCOLS ─────────────────────────────────────────────────────
# 5-minute warm-ups by session type. Do these before touching a barbell.

WARMUPS = {
    "upper": {
        "label": "Upper Body Warm-Up",
        "time": "10 min",
        "steps": [
            {"name": "Arm circles", "reps": "10 each direction", "note": "Forward then backward"},
            {"name": "Band pull-aparts", "reps": "20", "note": "Light band"},
            {"name": "Band dislocates", "reps": "10", "note": "Slow"},
            {"name": "Push-up to downward dog", "reps": "8", "note": "Slow and controlled"},
            {"name": "Cat-cow stretch", "reps": "8", "note": "Breathe deep"},
            {"name": "Empty bar bench press", "reps": "15", "note": "Slow"},
            {"name": "Empty bar OHP", "reps": "10", "note": "Feel the groove"},
        ],
    },
    "lower": {
        "label": "Lower Body Warm-Up",
        "time": "10 min",
        "steps": [
            {"name": "Bodyweight squats", "reps": "15", "note": "Full depth"},
            {"name": "Leg swings (front-back)", "reps": "10 per leg", "note": "Hold something"},
            {"name": "Leg swings (side-side)", "reps": "10 per leg", "note": ""},
            {"name": "Hip circles", "reps": "8 each direction", "note": ""},
            {"name": "Walking lunges", "reps": "8 per leg", "note": "Bodyweight"},
            {"name": "Glute bridges", "reps": "15", "note": "Squeeze at top"},
            {"name": "Empty bar squat", "reps": "10", "note": "Below parallel"},
        ],
    },
    "full": {
        "label": "Full Body Warm-Up",
        "time": "10 min",
        "steps": [
            {"name": "Jumping jacks", "reps": "30", "note": "Get the heart rate up"},
            {"name": "Arm circles + leg swings", "reps": "10 each", "note": "Multitask"},
            {"name": "Bodyweight squats", "reps": "10", "note": "Full depth"},
            {"name": "Push-ups", "reps": "10", "note": ""},
            {"name": "Hip circles", "reps": "8 each direction", "note": ""},
            {"name": "Band pull-aparts", "reps": "15", "note": "Light band"},
            {"name": "Inchworms", "reps": "5", "note": "Slow walk out"},
            {"name": "Empty bar complex", "reps": "5 each", "note": "Deadlifts + rows + hang cleans"},
        ],
    },
}

# Map day names to warm-up type
DAY_WARMUP_TYPES = {
    "Mon": "upper",  # Phase 1, changes by phase but upper is safe default
    "Tue": "lower",
    "Wed": "upper",
    "Thu": "lower",
    "Fri": "upper",
    "Sat": "full",
    "Sun": None,  # Rest day
}


# ─── SUPPLEMENTS ────────────────────────────────────────────────────────────

SUPPLEMENTS = [
    {"name": "Creatine 5g", "timing": "Any time, daily", "required": True},
    {"name": "Whey Protein", "timing": "Post-workout or with meals", "required": False},
    {"name": "Multivitamin", "timing": "With first meal", "required": False},
    {"name": "Fish Oil", "timing": "With meal", "required": False},
    {"name": "Vitamin D3", "timing": "With first meal", "required": False},
    {"name": "Electrolytes", "timing": "During fasting window or with training", "required": False},
]


# ─── TRAVEL BODYWEIGHT WORKOUTS ─────────────────────────────────────────────
# When no gym is available, swap the day's workout for bodyweight equivalents

TRAVEL_WORKOUTS = {
    "upper": {
        "liftName": "Travel - Upper Body (Bodyweight)",
        "exercises": [
            {"name": "Push-Ups", "sets": "4x15-20", "rest": "60s", "note": "Slow eccentric, full ROM"},
            {"name": "Diamond Push-Ups", "sets": "3x10-12", "rest": "60s", "note": "Hands together, elbows tight"},
            {"name": "Pike Push-Ups", "sets": "3x10", "rest": "60s", "note": "Hips high, shoulders are the prime mover"},
            {"name": "Inverted Row (table/ledge)", "sets": "4x12", "rest": "60s", "note": "Find a sturdy table, bar, or ledge. Pull chest to it."},
            {"name": "Band Pull-Aparts", "sets": "3x20", "rest": "45s", "note": "If you have a band. Skip if not."},
            {"name": "Plank Shoulder Taps", "sets": "3x20", "rest": "45s", "note": "Controlled, don't rotate hips"},
            {"name": "Tricep Dips (chair/bench)", "sets": "3x15", "rest": "45s", "note": "Feet extended, go deep"},
            {"name": "Isometric Curl Hold", "sets": "3x30s", "rest": "45s", "note": "Towel over foot, curl and hold at 90 deg"},
        ],
        "notes": "No gym? No problem. Focus on tempo: 3 seconds down, 1 second up. The slow eccentric makes bodyweight work.",
    },
    "lower": {
        "liftName": "Travel - Lower Body (Bodyweight)",
        "exercises": [
            {"name": "Pistol Squat (or assisted)", "sets": "4x6-8 each", "rest": "90s", "note": "Hold a doorframe or chair for balance if needed"},
            {"name": "Bulgarian Split Squat", "sets": "4x12 each", "rest": "60s", "note": "Rear foot on bed/chair. Add backpack for weight."},
            {"name": "Single-Leg Romanian Deadlift", "sets": "3x10 each", "rest": "60s", "note": "Slow, feel the hamstring stretch. Hold anything for weight."},
            {"name": "Jump Squats", "sets": "3x15", "rest": "60s", "note": "Explosive up, soft landing. Power work."},
            {"name": "Walking Lunges", "sets": "3x12 each", "rest": "60s", "note": "Long stride, upright torso"},
            {"name": "Glute Bridge (single leg)", "sets": "3x15 each", "rest": "45s", "note": "Shoulders on bed/couch, squeeze hard at top"},
            {"name": "Calf Raises (step)", "sets": "4x20", "rest": "45s", "note": "Find a step. Full stretch at bottom, squeeze at top."},
            {"name": "Wall Sit", "sets": "3x45s", "rest": "60s", "note": "Thighs parallel to floor. Suffer."},
        ],
        "notes": "Go slow on single-leg work. The balance challenge IS the load. Add a backpack with books/water bottles for extra resistance.",
    },
    "full": {
        "liftName": "Travel - Full Body (Bodyweight)",
        "exercises": [
            {"name": "Burpees", "sets": "4x10", "rest": "60s", "note": "Full push-up at bottom, jump at top"},
            {"name": "Push-Ups", "sets": "3x15-20", "rest": "60s", "note": "Controlled tempo"},
            {"name": "Jump Squats", "sets": "3x15", "rest": "60s", "note": "Explosive"},
            {"name": "Inverted Row (table/ledge)", "sets": "3x12", "rest": "60s", "note": "Find something to pull on"},
            {"name": "Walking Lunges", "sets": "3x12 each", "rest": "60s", "note": "Weighted if possible"},
            {"name": "Pike Push-Ups", "sets": "3x10", "rest": "60s", "note": "Shoulder focus"},
            {"name": "Single-Leg RDL", "sets": "3x10 each", "rest": "60s", "note": "Balance + hamstrings"},
            {"name": "Plank", "sets": "3x60s", "rest": "45s", "note": "Brace hard, breathe"},
        ],
        "notes": "Full body travel circuit. Move with intent. Rest periods are short - keep your heart rate up. This doubles as cardio.",
    },
    "rest": None,
}

# Map day of week to travel workout type
TRAVEL_DAY_MAP = {
    "Mon": "upper", "Tue": "lower", "Wed": "full",
    "Thu": "lower", "Fri": "upper", "Sat": "full", "Sun": "rest",
}


PHASES = {
    1: {
        "label": "Phase 1 - Wks 1-4",
        "focus": "Hypertrophy base + fat loss foundation",
        "lifting": "4x10-12, RPE 7-8",
        "deficit": "400-500 kcal below TDEE",
        "protein": "1g/lb bodyweight",
        "lift_days_per_week": 6,
        "weekly_structure": (
            "Mon Upper A (chest/back), Tue Lower A (squat focus) + long run, "
            "Wed Push/Pull, Thu Lower B (hinge focus), Fri Upper B (shoulders/arms) + HIIT, "
            "Sat Full-Body Compound + Z2, Sun streak mile only."
        ),
    },
    2: {
        "label": "Phase 2 - Wks 5-8",
        "focus": "Strength + body recomposition",
        "lifting": "5x5 main lifts, 3x12 accessories",
        "deficit": "400-500 kcal below TDEE",
        "protein": "1g/lb bodyweight",
        "lift_days_per_week": 6,
        "weekly_structure": (
            "Mon Lower Strength (5x5 squat), Tue Upper Pull + long run, "
            "Wed Full-Body Power + HIIT, Thu Lower Hinge (5x5 deadlift), "
            "Fri Upper Press, Sat Full-Body Volume + Z2, Sun streak mile only. "
            "Same 6-day frequency as Phase 1; the shift is heavier loads and 5x5 work, NOT fewer days."
        ),
    },
    3: {
        "label": "Phase 3 - Wks 9-12",
        # Live program (2026-06-01): heavier strength while leaning out, FULL
        # volume, loads CLIMB — NOT a peak/power-retention deload-phase taper.
        "focus": "Heavier strength, leaner — full volume, loads climbing",
        "lifting": "heavy 3-6 reps, full accessory volume (trending up)",
        "deficit": "300-400 kcal (tighten up)",
        "protein": "1g/lb bodyweight",
        "lift_days_per_week": 6,
        "weekly_structure": (
            "Coach-designed each week: heavy compounds (3-6 reps) lead every day, "
            "full accessory volume that trends UP, ~6 lifting days. Loads climb "
            "week over week — this is NOT a taper or a peak/hold phase."
        ),
    },
}

RUNS = {
    "z2_40": {"type": "z2", "label": "Zone 2", "time": "40 min", "detail": "HR 130-145. Conversational pace. Easy - you can hold a sentence."},
    "z2_35": {"type": "z2", "label": "Zone 2", "time": "35 min", "detail": "HR 130-145. Conversational pace. Aerobic base work."},
    "z2_45": {"type": "z2", "label": "Zone 2", "time": "45 min", "detail": "HR 130-145. Steady aerobic. Fat oxidation zone."},
    "z2_50": {"type": "z2", "label": "Zone 2", "time": "50 min", "detail": "HR 130-145. Longest Zone 2 of the week. Keep it honest."},
    "z2_55": {"type": "z2", "label": "Zone 2", "time": "55 min", "detail": "HR 130-145. Aerobic volume building."},
    "z2_30": {"type": "z2", "label": "Zone 2", "time": "30 min", "detail": "HR 130-145. Easy aerobic. Deload / taper run."},
    "z2_20": {"type": "z2", "label": "Zone 2", "time": "20 min", "detail": "HR 130-145. Short easy aerobic. Deload week."},
    "tempo25": {"type": "tempo", "label": "Tempo", "time": "25 min", "detail": "HR 155-165. Comfortably hard. 5 min easy warmup, 15 min at tempo, 5 min cooldown."},
    "tempo30": {"type": "tempo", "label": "Tempo", "time": "30 min", "detail": "HR 155-165. 5 min easy, 20 min sustained tempo, 5 min cooldown."},
    "tempo35": {"type": "tempo", "label": "Tempo", "time": "35 min", "detail": "HR 155-165. 5 min easy, 25 min tempo, 5 min cooldown. Hardest tempo of the plan."},
    "hiit20": {"type": "hiit", "label": "HIIT", "time": "26 min", "detail": "5 min warmup, 8x 30:90, 5 min cooldown."},
    "hiit25": {"type": "hiit", "label": "HIIT", "time": "30 min", "detail": "5 min warmup, 10x 30:90, 5 min cooldown."},
    "hiit30": {"type": "hiit", "label": "HIIT", "time": "34 min", "detail": "5 min warmup, 12x 30:90, 5 min cooldown."},
    "long60": {"type": "long", "label": "Long", "time": "60 min", "detail": "HR under 140. Easy conversational. Your aerobic base is your asset - don't push it."},
    "long75": {"type": "long", "label": "Long", "time": "75 min", "detail": "HR under 140. Build the run slightly - still aerobic, not a race."},
    "long90": {"type": "long", "label": "Long", "time": "90 min", "detail": "HR under 140. Peak long run. Take fuel if you go over 75 min."},
    "easy20": {"type": "easy", "label": "Easy", "time": "20 min", "detail": "HR under 130. Deload week. Shuffle if you need to - just move."},
    "easy30": {"type": "easy", "label": "Easy", "time": "30 min", "detail": "HR under 130. Easy and honest. Deload week."},
    "min": {"type": "min", "label": "Min mile", "time": "1+ mile", "detail": "Easy, sub-HR 130. Streak day. This is the only obligation."},
}

# ─── NAME ALIASES ──────────────────────────────────────────────────────────
# Maps variant / short names to canonical exercise names.
# Every exercise in the program should resolve to exactly one canonical name.

NAME_ALIASES = {
    "Bench Press": "Barbell Bench Press",
    "Back Squat": "Barbell Back Squat",
    "Deadlift": "Conventional Deadlift",
    "DB OHP": "DB Overhead Press",
    "Cable Row": "Cable Seated Row",
    "RDL": "Romanian Deadlift",
    "Calf Raise": "Standing Calf Raise",
    "Push-Up": "Push-Ups",
    "DB Lateral Raise": "Lateral Raise",
    "Heavy Lat Pulldown": "Lat Pulldown",
    "Bent-Over Row": "Barbell Bent-Over Row",
    "DB Row": "Single-Arm DB Row",
    "DB Walking Lunge": "Walking Lunge",
    "Bench Press - 1RM test": "Barbell Bench Press",
    "Back Squat - 1RM test": "Barbell Back Squat",
    "Deadlift - 1RM test": "Conventional Deadlift",
    "Lat Pulldown - max weight": "Lat Pulldown",
    "Inverted Row (table edge)": "Inverted Row (table/ledge)",
    "Inverted Row (table)": "Inverted Row (table/ledge)",
    "Tricep Dips (chair)": "Tricep Dips (chair/bench)",
    "Tricep Dips (bench)": "Tricep Dips (chair/bench)",
    "DB Bench Press": "DB Bench Press",  # Keep as-is (different from Barbell Bench)
    "DB Bench": "DB Bench Press",
    "Bench": "Barbell Bench Press",
    "Squat": "Barbell Back Squat",
    # Pump / test variants → canonical base exercise
    "Goblet Squat (pump)": "Goblet Squat",
    "DB Bench (pump)": "DB Bench Press",
    "Cable Row (pump)": "Cable Seated Row",
    "DB Curl (pump)": "DB Curl",
    "Tricep Pushdown (pump)": "Cable Tricep Pushdown",
    "Leg Press (pump)": "Leg Press",
    "Calf Raise (pump)": "Standing Calf Raise",
    "Kettlebell Swing": "KB Swing",
    "Kettlebell Swings": "KB Swing",
    "KB Swings": "KB Swing",
}


def resolve_name(name: str) -> str:
    """Resolve any exercise name variant to the canonical name."""
    if not name:
        return ""
    return NAME_ALIASES.get(name, name)


# ─── EXERCISES CATALOG ─────────────────────────────────────────────────────
# One entry per canonical exercise. Source of truth for muscle group, category,
# equipment, and video search cue. ~40 exercises.

EXERCISES = {
    # ─── CHEST ─────────────────────────────────────────────
    "Barbell Bench Press": {
        "muscle_group": "chest",
        "category": "compound",
        "equipment": ["barbell", "flat_bench"],
        "video": "barbell bench press form tutorial",
    },
    "Incline DB Press": {
        "muscle_group": "chest",
        "category": "compound",
        "equipment": ["dumbbells", "incline_bench"],
        "video": "incline dumbbell press form tutorial",
    },
    "DB Bench Press": {
        "muscle_group": "chest",
        "category": "compound",
        "equipment": ["dumbbells", "flat_bench"],
        "video": "dumbbell bench press form tutorial",
    },
    "Incline Cable Fly": {
        "muscle_group": "chest",
        "category": "isolation",
        "equipment": ["cable_machine"],
        "video": "incline cable fly chest form tutorial",
    },
    "Cable Chest Fly": {
        "muscle_group": "chest",
        "category": "isolation",
        "equipment": ["cable_machine"],
        "video": "cable chest fly form tutorial pec squeeze",
    },
    "Push-Ups": {
        "muscle_group": "chest",
        "category": "compound",
        "equipment": [],
        "video": "push up proper form tutorial full ROM",
    },
    "Weighted Dips": {
        "muscle_group": "chest_triceps",
        "category": "compound",
        "equipment": ["dip_station"],
        "video": "weighted dips chest tricep form tutorial",
    },
    # ─── BACK ──────────────────────────────────────────────
    "Cable Seated Row": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["cable_machine"],
        "video": "seated cable row proper form technique",
    },
    "Lat Pulldown": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["lat_pulldown"],
        "video": "lat pulldown proper form tutorial",
    },
    "Wide-Grip Lat Pulldown": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["lat_pulldown"],
        "video": "wide grip lat pulldown proper form tutorial",
    },
    "Barbell Bent-Over Row": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["barbell"],
        "video": "barbell bent over row proper form technique",
    },
    "Single-Arm DB Row": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["dumbbells", "flat_bench"],
        "video": "single arm dumbbell row proper form",
    },
    "Ring Row": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["trx"],
        "video": "ring row form tutorial",
    },
    "DB Shrug": {
        "muscle_group": "traps",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "dumbbell shrug proper form trap exercise",
    },
    # ─── SHOULDERS ─────────────────────────────────────────
    "DB Overhead Press": {
        "muscle_group": "shoulders",
        "category": "compound",
        "equipment": ["dumbbells"],
        "video": "dumbbell overhead press form tutorial",
    },
    "Barbell OHP": {
        "muscle_group": "shoulders",
        "category": "compound",
        "equipment": ["barbell"],
        "video": "barbell overhead press strict form tutorial",
    },
    "Push Press": {
        "muscle_group": "shoulders",
        "category": "compound",
        "equipment": ["barbell"],
        "video": "barbell push press technique tutorial",
    },
    "Lateral Raise": {
        "muscle_group": "shoulders",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "dumbbell lateral raise proper form",
    },
    "Face Pull": {
        "muscle_group": "rear_delts",
        "category": "isolation",
        "equipment": ["cable_machine"],
        "video": "face pull cable exercise form tutorial",
    },
    "Rear Delt Fly": {
        "muscle_group": "rear_delts",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "rear delt fly form tutorial shoulder",
    },
    # ─── LEGS ──────────────────────────────────────────────
    "Barbell Back Squat": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": ["barbell"],
        "video": "barbell back squat proper form tutorial",
    },
    "Conventional Deadlift": {
        "muscle_group": "posterior_chain",
        "category": "compound",
        "equipment": ["barbell"],
        "video": "conventional deadlift form tutorial technique",
    },
    "Romanian Deadlift": {
        "muscle_group": "hamstrings",
        "category": "compound",
        "equipment": ["barbell"],
        "video": "romanian deadlift form guide technique",
    },
    "Barbell Hip Thrust": {
        "muscle_group": "glutes",
        "category": "compound",
        "equipment": ["barbell", "flat_bench"],
        "video": "barbell hip thrust glute form tutorial",
    },
    "Bulgarian Split Squat": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": ["dumbbells"],
        "video": "bulgarian split squat proper form tutorial",
    },
    "Walking Lunge": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": ["dumbbells"],
        "video": "walking lunge proper form technique",
    },
    "Goblet Squat": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": ["dumbbells"],
        "video": "goblet squat form tutorial beginner",
    },
    "Leg Press": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": ["leg_press"],
        "video": "leg press machine proper form foot placement",
    },
    "Lying Leg Curl": {
        "muscle_group": "hamstrings",
        "category": "isolation",
        "equipment": ["leg_curl_ext"],
        "video": "lying leg curl machine form tutorial",
    },
    "Standing Calf Raise": {
        "muscle_group": "calves",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "standing calf raise proper form full ROM",
    },
    # ─── ARMS ──────────────────────────────────────────────
    "EZ-Bar Curl": {
        "muscle_group": "biceps",
        "category": "isolation",
        "equipment": ["ez_bar"],
        "video": "ez bar curl proper form bicep tutorial",
    },
    "Hammer Curl": {
        "muscle_group": "biceps",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "hammer curl proper form bicep tutorial",
    },
    "DB Curl": {
        "muscle_group": "biceps",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "dumbbell bicep curl proper form tutorial",
    },
    "Cable Tricep Pushdown": {
        "muscle_group": "triceps",
        "category": "isolation",
        "equipment": ["cable_machine"],
        "video": "cable tricep pushdown form tutorial",
    },
    "Skull Crusher": {
        "muscle_group": "triceps",
        "category": "isolation",
        "equipment": ["ez_bar", "flat_bench"],
        "video": "skull crusher ez bar tricep form tutorial",
    },
    "Tricep Dip": {
        "muscle_group": "triceps",
        "category": "compound",
        "equipment": ["dip_station"],
        "video": "tricep dip proper form bodyweight tutorial",
    },
    "Overhead Tricep Extension": {
        "muscle_group": "triceps",
        "category": "isolation",
        "equipment": ["dumbbells"],
        "video": "overhead dumbbell tricep extension form tutorial",
    },
    # ─── POWER ─────────────────────────────────────────────
    "Power Clean": {
        "muscle_group": "full_body",
        "category": "power",
        "equipment": ["barbell"],
        "video": "power clean technique tutorial beginner",
    },
    "Box Jump": {
        "muscle_group": "power",
        "category": "power",
        "equipment": [],
        "video": "box jump proper form landing technique",
        # Tracked in box height (inches), not load (lb). UI swaps the weight
        # input for a height input. Power work isn't loaded — it's a plyometric.
        "tracked_metric": "height",
    },
    "Med Ball Slam": {
        "muscle_group": "power",
        "category": "power",
        "equipment": ["medicine_ball"],
        "video": "medicine ball slam form tutorial explosive",
    },
    "KB Swing": {
        "muscle_group": "posterior_chain",
        "category": "power",
        "equipment": ["kettlebells"],
        "video": "kettlebell swing form tutorial hip hinge",
    },
    # ─── CORE ──────────────────────────────────────────────
    "Plank": {
        "muscle_group": "core",
        "category": "core",
        "equipment": [],
        "video": "plank proper form core bracing tutorial",
    },
    "Ab Wheel Rollout": {
        "muscle_group": "core",
        "category": "core",
        "equipment": ["ab_wheel"],
        "video": "ab wheel rollout form tutorial beginner",
    },
    # ─── BODYWEIGHT / BAND EXERCISES (for no-gym users) ───────
    "Diamond Push-Ups": {
        "muscle_group": "triceps",
        "category": "compound",
        "equipment": [],
        "video": "diamond push ups tricep form tutorial",
    },
    "Dips": {
        "muscle_group": "chest_triceps",
        "category": "compound",
        "equipment": ["dip_station"],
        "video": "bodyweight dips form tutorial chest tricep",
    },
    "Inverted Row": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": [],
        "video": "inverted row bodyweight back exercise tutorial",
    },
    "Band Pull-Apart": {
        "muscle_group": "rear_delts",
        "category": "isolation",
        "equipment": ["resistance_band"],
        "video": "band pull apart rear delt form tutorial",
    },
    "Band Curl": {
        "muscle_group": "biceps",
        "category": "isolation",
        "equipment": ["resistance_band"],
        "video": "resistance band bicep curl form tutorial",
    },
    "Bodyweight Squats": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": [],
        "video": "bodyweight squat proper form tutorial",
    },
    "Single-Leg Glute Bridge": {
        "muscle_group": "glutes",
        "category": "isolation",
        "equipment": [],
        "video": "single leg glute bridge form tutorial",
    },
    "Nordic Hamstring Curl": {
        "muscle_group": "hamstrings",
        "category": "compound",
        "equipment": [],
        "video": "nordic hamstring curl eccentric form tutorial",
    },
    "Pike Push-Ups": {
        "muscle_group": "shoulders",
        "category": "compound",
        "equipment": [],
        "video": "pike push ups shoulder press bodyweight tutorial",
    },
    "Decline Push-Ups": {
        "muscle_group": "chest",
        "category": "compound",
        "equipment": ["flat_bench"],
        "video": "decline push ups chest form tutorial",
    },
    "Band Lateral Raise": {
        "muscle_group": "shoulders",
        "category": "isolation",
        "equipment": ["resistance_band"],
        "video": "resistance band lateral raise shoulder tutorial",
    },
    "Dead Bug": {
        "muscle_group": "core",
        "category": "core",
        "equipment": [],
        "video": "dead bug core exercise proper form tutorial",
    },
    "Mountain Climbers": {
        "muscle_group": "core",
        "category": "core",
        "equipment": [],
        "video": "mountain climbers exercise form tutorial",
    },
    "Hollow Hold": {
        "muscle_group": "core",
        "category": "core",
        "equipment": [],
        "video": "hollow hold core exercise proper form tutorial",
    },
    "Step-Up": {
        "muscle_group": "quads",
        "category": "compound",
        "equipment": ["flat_bench"],
        "video": "step up exercise proper form tutorial",
    },
    "Hip Thrust": {
        "muscle_group": "glutes",
        "category": "compound",
        "equipment": ["flat_bench"],
        "video": "bodyweight hip thrust glute form tutorial",
    },
    "Band Row": {
        "muscle_group": "back",
        "category": "compound",
        "equipment": ["resistance_band"],
        "video": "resistance band row back exercise tutorial",
    },
    "Band Face Pull": {
        "muscle_group": "rear_delts",
        "category": "isolation",
        "equipment": ["resistance_band"],
        "video": "resistance band face pull form tutorial",
    },
    "Band Tricep Extension": {
        "muscle_group": "triceps",
        "category": "isolation",
        "equipment": ["resistance_band"],
        "video": "resistance band tricep extension form tutorial",
    },
    "Burpees": {
        "muscle_group": "full_body",
        "category": "compound",
        "equipment": [],
        "video": "burpee proper form full body exercise tutorial",
    },
}


# ─── PHASE TEMPLATES ───────────────────────────────────────────────────────
# Restructured from _phase1_week, _phase2_week, _phase3_week, _deload_week,
# _test_week. Each phase maps day_idx (0=Mon) to a list of exercise dicts.
# Uses CANONICAL names. sets is an int, reps is a string.

PHASE_TEMPLATES = {
    # ── Phase 1: Hypertrophy / adaptation (weeks 1-3) per spec §2 ─────────
    1: {
        0: [  # Mon - Lower Hypertrophy - Quad/Glute Focus
            {"exercise": "Front Squat", "sets": 4, "reps": "8",
             "rest": "2-3 min",
             "note": "Build reps to 12 across all sets; then bump weight."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8",
             "rest": "60-90s",
             "note": "Each leg. Unilateral, leg power transfer."},
            {"exercise": "Romanian Deadlift", "sets": 3, "reps": "8",
             "rest": "60-90s", "note": "RPE 7. Hamstring + glute hinge."},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Full ROM, slow eccentric."},
        ],
        1: [  # Tue - Upper Press - Shoulder Build
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "8",
             "rest": "2 min",
             "note": "Build to 10 reps. Pause at chest."},
            {"exercise": "Landmine Press", "sets": 3, "reps": "8",
             "rest": "90s",
             "note": "Each side. Shoulder-friendly OHP."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "60s",
             "note": "Constant tension. Shoulder rebuild priority."},
            {"exercise": "Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
        2: [  # Wed - Shoulder Volume + Arms
            {"exercise": "Cable Lateral Raise", "sets": 4, "reps": "15",
             "rest": "45-60s", "note": "More lateral delt volume."},
            {"exercise": "Reverse Pec Deck", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Rear delt isolation."},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Brachialis + biceps."},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Biceps direct."},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"exercise": "Overhead Tricep Extension", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Long-head tricep."},
        ],
        3: [  # Thu - Upper Pull - Lat Focus
            {"exercise": "Weighted Pull-Up", "sets": 4, "reps": "6",
             "rest": "2 min", "note": "Build to 8 reps. BW if not yet weighted."},
            {"exercise": "Barbell Bent-Over Row", "sets": 4, "reps": "8",
             "rest": "90s-2 min",
             "note": "45-deg torso, pull to belly button."},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Neutral grip."},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8",
             "rest": "60s", "note": "Each arm."},
            {"exercise": "Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Postural."},
        ],
        4: [  # Fri - Heavy Lower hypertrophy
            {"exercise": "Back Squat", "sets": 4, "reps": "8",
             "rest": "2-3 min",
             "note": "~70%. Below parallel. The strength session."},
            {"exercise": "Hip Thrust", "sets": 4, "reps": "10",
             "rest": "90s", "note": "Squeeze glutes hard at top."},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Hamstring isolation."},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Second calf session of week."},
        ],
        5: [  # Sat - Full Body Cleanup
            {"exercise": "Hip Thrust", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Glute volume."},
            {"exercise": "Cable Chest Fly", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Chest accessory."},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8",
             "rest": "60s", "note": "Each arm."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Lateral volume."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10",
             "rest": "60s", "note": "Core anti-extension."},
        ],
        6: [],  # Sun rest from iron
    },

    # ── Phase 2: Strength (weeks 5-7) per spec §4 ─────────────────────────
    2: {
        0: [  # Mon - Lower POWER + RDL
            {"exercise": "Box Jump", "sets": 3, "reps": "5",
             "rest": "60-90s",
             "note": "CNS primer. Max height, full reset between reps."},
            {"exercise": "Front Squat", "sets": 4, "reps": "3",
             "rest": "2-3 min",
             "note": "Speed-focused. ~70-76% wave (wk5/6/7)."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8",
             "rest": "60-90s",
             "note": "Each leg. Heavier than P1, explosive up."},
            {"exercise": "Romanian Deadlift", "sets": 3, "reps": "8",
             "rest": "60-90s",
             "note": "RPE 7. Hamstring + glute hinge."},
        ],
        1: [  # Tue - Upper PRESS + Shoulder Strength
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "5",
             "rest": "2-3 min",
             "note": "75-82% wave. Pause at chest."},
            {"exercise": "Landmine Press", "sets": 3, "reps": "6",
             "rest": "90s",
             "note": "Each side. Heavier P2 progression."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "12",
             "rest": "60s",
             "note": "Constant tension. Lateral delt strength."},
            {"exercise": "Cable Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
        2: [  # Wed - Shoulder Volume + Arms
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Lateral delt volume."},
            {"exercise": "Reverse Pec Deck", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Rear delt isolation."},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Brachialis + biceps."},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Biceps direct."},
        ],
        3: [  # Thu - Upper PULL + Lat
            {"exercise": "Weighted Pull-Up", "sets": 4, "reps": "5",
             "rest": "2-3 min",
             "note": "Heavier P2. BW 4×6-10 if not yet weighted."},
            {"exercise": "Barbell Bent-Over Row", "sets": 4, "reps": "6",
             "rest": "2 min",
             "note": "75-82% wave. 45-deg torso, pull to belly button."},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Neutral grip. Different angle."},
            {"exercise": "Cable Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Postural."},
        ],
        4: [  # Fri - HEAVY Lower
            {"exercise": "Back Squat", "sets": 4, "reps": "5",
             "rest": "3-5 min",
             "note": "78% wk5; engine waves to 82% wk6, 87% wk7."},
            {"exercise": "Hip Thrust", "sets": 4, "reps": "8",
             "rest": "90s",
             "note": "RPE 7. Squeeze glutes hard at top."},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "10",
             "rest": "60s", "note": "Hamstring isolation."},
        ],
        5: [  # Sat - Full Body / Glute Volume
            {"exercise": "Hip Thrust", "sets": 3, "reps": "10",
             "rest": "60-90s",
             "note": "RPE 6. Lighter Sat — second hip thrust of week."},
            {"exercise": "Cable Chest Fly", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Chest accessory."},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8",
             "rest": "60s", "note": "Each arm. Unilateral back."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Lateral volume."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10",
             "rest": "60s", "note": "Core anti-extension."},
        ],
        6: [],  # Sun rest from iron
    },

    # ── Phase 3: Cut climax (weeks 9-11) — FULL strength volume, loads CLIMB.
    #    Rebuilt 2026-06-01 (Erik): no deload-phase taper, no HOLD. Volume
    #    matches Phase 2 (~81 sets); deload only on WEEKS (4/8/12). ──────────
    3: {
        0: [  # Mon - Lower (heavy)
            {"exercise": "Box Jump", "sets": 3, "reps": "5", "rest": "90s",
             "note": "RPE 7. Preserve power."},
            {"exercise": "Front Squat", "sets": 4, "reps": "3", "rest": "2 min",
             "note": "Heavy triples — progress when RPE <= 6 confirmed."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "6",
             "rest": "60-90s", "note": "Each leg. Progress when clean."},
            {"exercise": "Romanian Deadlift", "sets": 3, "reps": "6",
             "rest": "60-90s", "note": "RPE 7. Hinge volume restored."},
        ],
        1: [  # Tue - Press + Shoulder
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "5", "rest": "3 min",
             "note": "Progress when reps clean."},
            {"exercise": "Landmine Press", "sets": 3, "reps": "6", "rest": "90s",
             "note": "Each side."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Shoulder priority."},
            {"exercise": "Cable Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Postural."},
        ],
        2: [  # Wed - Shoulder/Arms
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Lateral delt volume."},
            {"exercise": "Reverse Pec Deck", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Rear delt."},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Brachialis + biceps."},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "10",
             "rest": "45-60s", "note": "Biceps direct — restored."},
        ],
        3: [  # Thu - Pull + Lat
            {"exercise": "Weighted Pull-Up", "sets": 4, "reps": "5",
             "rest": "2 min", "note": "Progress when clean."},
            {"exercise": "Barbell Bent-Over Row", "sets": 4, "reps": "6",
             "rest": "90s-2 min", "note": "Progress when clean."},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Neutral grip."},
            {"exercise": "Cable Face Pull", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "Postural."},
        ],
        4: [  # Fri - HEAVY Lower
            {"exercise": "Back Squat", "sets": 4, "reps": "3", "rest": "4 min",
             "note": "Heavy triples — progress when RPE <= 8."},
            {"exercise": "Hip Thrust", "sets": 4, "reps": "8", "rest": "90s",
             "note": "RPE 7. Squeeze at top."},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "10",
             "rest": "60s", "note": "Hamstring (knee flexion) — restored."},
        ],
        5: [  # Sat - Full Body
            {"exercise": "Hip Thrust", "sets": 3, "reps": "10",
             "rest": "60-90s", "note": "Second glute session."},
            {"exercise": "Cable Chest Fly", "sets": 3, "reps": "12",
             "rest": "60s", "note": "Chest accessory."},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "8",
             "rest": "60s", "note": "Each arm."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "12",
             "rest": "45-60s", "note": "Shoulder priority."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10",
             "rest": "60s", "note": "Core anti-extension — restored."},
        ],
        6: [],  # Sun rest from iron
    },

    # ── Deload (weeks 4, 8) per spec §3 / §5 ──────────────────────────────
    "deload": {
        0: [  # Monday — Deload Lower
            {"exercise": "Box Jump", "sets": 2, "reps": "5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset."},
            {"exercise": "Front Squat", "sets": 3, "reps": "3", "rest": "2 min",
             "note": "65% of working weight."},
            {"exercise": "Bulgarian Split Squat", "sets": 2, "reps": "8",
             "rest": "60-90s", "note": "Each leg. Volume cut 50%."},
        ],
        1: [  # Tuesday — Deload Press + Shoulder
            {"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "rest": "2 min",
             "note": "70% of working weight."},
            {"exercise": "Landmine Press", "sets": 2, "reps": "6", "rest": "90s",
             "note": "Each side. Volume cut."},
            {"exercise": "Cable Lateral Raise", "sets": 2, "reps": "12",
             "rest": "60s", "note": "Constant tension, light."},
            {"exercise": "Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Postural — keep doing this."},
        ],
        2: [  # Wednesday — Deload Shoulder/Arms (light)
            {"exercise": "Cable Lateral Raise", "sets": 2, "reps": "15",
             "rest": "45-60s", "note": "Light. Lateral delt volume cut."},
            {"exercise": "Reverse Pec Deck", "sets": 2, "reps": "12",
             "rest": "45-60s", "note": "Light. Rear delt isolation."},
            {"exercise": "Cable Tricep Pushdown", "sets": 2, "reps": "12",
             "rest": "45-60s", "note": "Or curl — pick one."},
        ],
        3: [  # Thursday — Deload Pull
            {"exercise": "Weighted Pull-Up", "sets": 3, "reps": "5", "rest": "2 min",
             "note": "Bodyweight only. No added weight in deload."},
            {"exercise": "Barbell Bent-Over Row", "sets": 3, "reps": "6",
             "rest": "90s-2 min", "note": "70% of working weight."},
            {"exercise": "Lat Pulldown", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Light. Volume cut."},
            {"exercise": "Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Postural."},
        ],
        4: [  # Friday — Deload Heavy Lower (light)
            {"exercise": "Back Squat", "sets": 3, "reps": "5", "rest": "2-3 min",
             "note": "65% of working weight. Move well."},
            {"exercise": "Hip Thrust", "sets": 3, "reps": "8", "rest": "90s",
             "note": "RPE 6. Light, squeeze glutes."},
        ],
        5: [  # Saturday — Deload Full Body Light
            {"exercise": "Hip Thrust", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"exercise": "Cable Chest Fly", "sets": 2, "reps": "12", "rest": "60s",
             "note": "Light. Chest accessory."},
            {"exercise": "Single-Arm DB Row", "sets": 2, "reps": "8", "rest": "60s",
             "note": "Each arm. Light."},
            {"exercise": "Cable Lateral Raise", "sets": 2, "reps": "12",
             "rest": "45-60s", "note": "Light lateral volume."},
        ],
        6: [],  # Sunday — Rest from iron (long fasted run)
    },

    # ── Deload BW (weeks 4, 8) — mirrors gym deload structure ──────────────
    "deload_bw": {
        0: [  # Mon — Deload Lower BW
            {"exercise": "Squat Jump", "sets": 2, "reps": "5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset."},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "3", "rest": "2 min",
             "note": "Light DB. ~65% of working tempo. Move well."},
            {"exercise": "Bulgarian Split Squat", "sets": 2, "reps": "8", "rest": "60-90s",
             "note": "Each leg. Bodyweight, easy tempo. Volume cut 50%."},
        ],
        1: [  # Tue — Deload Press + Shoulder BW
            {"exercise": "Push-Ups", "sets": 3, "reps": "5", "rest": "2 min",
             "note": "Bodyweight only — no decline/weighted pack in deload."},
            {"exercise": "Pike Push-Ups", "sets": 2, "reps": "6", "rest": "90s",
             "note": "Easy shoulder work. Volume cut."},
            {"exercise": "Lateral Raise", "sets": 2, "reps": "12", "rest": "60s",
             "note": "Light DB. Constant tension, light."},
            {"exercise": "Band Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Postural — keep doing this."},
        ],
        2: [  # Wed — Deload Shoulder/Arms BW (light)
            {"exercise": "Lateral Raise", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Light DB. Lateral delt volume cut."},
            {"exercise": "Band Reverse Fly", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Light. Rear delt isolation."},
            {"exercise": "Diamond Push-Up", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Or DB curl — pick one."},
        ],
        3: [  # Thu — Deload Pull BW
            {"exercise": "Pull-Ups", "sets": 3, "reps": "5", "rest": "2 min",
             "note": "Bodyweight only. No added load in deload."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 3, "reps": "6", "rest": "90s-2 min",
             "note": "Light tempo. Pull chest to bar."},
            {"exercise": "Pull-Ups", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Lat sub. Light. Volume cut."},
            {"exercise": "Band Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Postural."},
        ],
        4: [  # Fri — Deload Heavy Lower BW (light)
            {"exercise": "Bodyweight Squats", "sets": 3, "reps": "5", "rest": "2-3 min",
             "note": "Pistol progression assisted. ~65% effort. Move well."},
            {"exercise": "Single-Leg Glute Bridge", "sets": 3, "reps": "8", "rest": "90s",
             "note": "Each leg. RPE 6. Light, squeeze glutes."},
        ],
        5: [  # Sat — Deload Full Body Light BW
            {"exercise": "Single-Leg Glute Bridge", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"exercise": "DB Fly", "sets": 2, "reps": "12", "rest": "60s",
             "note": "Light DB. Chest accessory."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 2, "reps": "8", "rest": "60s",
             "note": "Light. Unilateral progression OK."},
            {"exercise": "Lateral Raise", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Light DB. Lateral volume."},
        ],
        6: [],  # Sun — Rest from iron (long fasted run)
    },

    # ── Week 12 BW — peak finish (mini-taper, mirrors gym test) ──────────
    "test_bw": {
        0: [  # Mon — Wk12 Lower BW (taper)
            {"exercise": "Squat Jump", "sets": 2, "reps": "5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset."},
            {"exercise": "Goblet Squat", "sets": 2, "reps": "3", "rest": "2-3 min",
             "note": "Light DB. Single working set, feel it."},
            {"exercise": "Bulgarian Split Squat", "sets": 1, "reps": "6", "rest": "60-90s",
             "note": "Each leg. Volume cut from P3."},
        ],
        1: [  # Tue — Wk12 Press + Shoulder BW (taper)
            {"exercise": "Push-Ups", "sets": 2, "reps": "5", "rest": "2-3 min",
             "note": "Decline if BW too easy. Single working set."},
            {"exercise": "Pike Push-Ups", "sets": 1, "reps": "6", "rest": "90s",
             "note": "Single working set."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "12", "rest": "60s",
             "note": "Light DB. KEEP — makes the look."},
            {"exercise": "Band Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "KEEP — postural."},
        ],
        2: [  # Wed — Wk12 Shoulder Volume Only BW
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Light DB. KEEP — shoulder volume for the look."},
            {"exercise": "Band Reverse Fly", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Rear delt isolation."},
        ],
        3: [  # Thu — Wk12 Pull BW (taper)
            {"exercise": "Pull-Ups", "sets": 2, "reps": "5", "rest": "2 min",
             "note": "Single working set."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 2, "reps": "6", "rest": "90s-2 min",
             "note": "Single working set."},
            {"exercise": "Pull-Ups", "sets": 1, "reps": "10", "rest": "60-90s",
             "note": "Single working set."},
            {"exercise": "Band Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Postural."},
        ],
        4: [  # Fri — Wk12 Heavy Lower BW (taper)
            {"exercise": "Bodyweight Squats", "sets": 2, "reps": "3", "rest": "3-5 min",
             "note": "Pistol progression. Single working set, just to feel it."},
            {"exercise": "Single-Leg Glute Bridge", "sets": 2, "reps": "8", "rest": "90s",
             "note": "Each leg. Glute volume."},
        ],
        5: [  # Sat — Wk12 Full Body BW (taper)
            {"exercise": "Single-Leg Glute Bridge", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"exercise": "DB Fly", "sets": 2, "reps": "12", "rest": "60s",
             "note": "Light DB. Chest accessory."},
            {"exercise": "Lateral Raise", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Light DB. Lateral volume — final week."},
        ],
        6: [],  # Sun — Rest from iron (long fasted run)
    },

    # ── Week 12 — peak finish per spec §7 (mini-taper, NOT 1RM test) ──────
    "test": {
        0: [  # Monday — Wk12 Lower (taper)
            {"exercise": "Box Jump", "sets": 2, "reps": "5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset."},
            {"exercise": "Front Squat", "sets": 2, "reps": "3", "rest": "2-3 min",
             "note": "73% — single working set."},
            {"exercise": "Bulgarian Split Squat", "sets": 1, "reps": "6",
             "rest": "60-90s", "note": "Each leg. Volume cut from P3."},
        ],
        1: [  # Tuesday — Wk12 Press + Shoulder (taper)
            {"exercise": "Barbell Bench Press", "sets": 2, "reps": "5", "rest": "2-3 min",
             "note": "80% — single working set."},
            {"exercise": "Landmine Press", "sets": 1, "reps": "6", "rest": "90s",
             "note": "Each side. Single working set."},
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "12", "rest": "60s",
             "note": "KEEP — makes the look."},
            {"exercise": "Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "KEEP — postural."},
        ],
        2: [  # Wednesday — Wk12 Shoulder Volume Only
            {"exercise": "Cable Lateral Raise", "sets": 3, "reps": "15",
             "rest": "45-60s", "note": "KEEP — shoulder volume for the look."},
            {"exercise": "Reverse Pec Deck", "sets": 2, "reps": "12",
             "rest": "45-60s", "note": "Rear delt isolation."},
        ],
        3: [  # Thursday — Wk12 Pull (taper)
            {"exercise": "Weighted Pull-Up", "sets": 2, "reps": "5", "rest": "2 min",
             "note": "Single working set."},
            {"exercise": "Barbell Bent-Over Row", "sets": 2, "reps": "6",
             "rest": "90s-2 min", "note": "80% — single working set."},
            {"exercise": "Lat Pulldown", "sets": 1, "reps": "10", "rest": "60-90s",
             "note": "Single working set."},
            {"exercise": "Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Postural."},
        ],
        4: [  # Friday — Wk12 Heavy Lower (taper)
            {"exercise": "Back Squat", "sets": 2, "reps": "3", "rest": "3-5 min",
             "note": "87% — single working set, just to feel it."},
            {"exercise": "Hip Thrust", "sets": 2, "reps": "8", "rest": "90s",
             "note": "Glute volume."},
        ],
        5: [  # Saturday — Wk12 Full Body (taper)
            {"exercise": "Hip Thrust", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"exercise": "Cable Chest Fly", "sets": 2, "reps": "12", "rest": "60s",
             "note": "Chest accessory."},
            {"exercise": "Cable Lateral Raise", "sets": 2, "reps": "12",
             "rest": "45-60s", "note": "Lateral volume — final week."},
        ],
        6: [],  # Sunday — Rest from iron (long fasted run)
    },
}

# ─── BODYWEIGHT PHASE TEMPLATES ───────────────────────────────────────────
# For users with has_gym=False. Mirrors PHASE_TEMPLATES day structure:
#   Mon=Lower, Tue=Upper Press, Wed=Volume Arms, Thu=Upper Pull,
#   Fri=Heavy Lower, Sat=Full Body, Sun=Rest.
# Equipment assumed: bodyweight, light DB pair (~30 lb), bench/chair,
# pull-up bar, resistance bands, ab wheel. NO barbell, NO cables, NO machines.

BW_PHASE_TEMPLATES = {
    # ── Phase 1: Hypertrophy / adaptation (weeks 1-3) — BW subs of spec §2 ──
    1: {
        0: [  # Mon — Lower Hypertrophy (Front Squat → Goblet/Bulgarian)
            {"exercise": "Goblet Squat", "sets": 4, "reps": "8", "rest": "2-3 min",
             "note": "Hold light DB at chest. Build reps to 12, then progress depth/tempo."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8", "rest": "60-90s",
             "note": "Each leg. Rear foot on bench, slow eccentric."},
            {"exercise": "Single-Leg Romanian Deadlift", "sets": 3, "reps": "8", "rest": "60-90s",
             "note": "Each leg. Light DB, RPE 7. Hamstring + glute hinge."},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "On step edge. Full ROM, slow eccentric."},
        ],
        1: [  # Tue — Upper Press (DB Bench → Push-Up, Landmine → Pike)
            {"exercise": "Push-Ups", "sets": 4, "reps": "8", "rest": "2 min",
             "note": "Decline (feet on bench) if too easy. Build to 10-12."},
            {"exercise": "Pike Push-Ups", "sets": 3, "reps": "8", "rest": "90s",
             "note": "Feet elevated. Vertical press substitute for landmine."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "60s",
             "note": "Light DB. Constant tension. Shoulder rebuild priority."},
            {"exercise": "Band Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Anchor band overhead. Postural — every press/pull day."},
        ],
        2: [  # Wed — Shoulder Volume + Arms
            {"exercise": "Lateral Raise", "sets": 4, "reps": "15", "rest": "45-60s",
             "note": "Light DB. More lateral delt volume."},
            {"exercise": "Band Reverse Fly", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Or bent-over DB reverse fly. Rear delt isolation."},
            {"exercise": "DB Hammer Curl", "sets": 3, "reps": "10", "rest": "45-60s",
             "note": "Light DB. Brachialis + biceps."},
            {"exercise": "DB Curl", "sets": 3, "reps": "10", "rest": "45-60s",
             "note": "Light DB. Biceps direct."},
            {"exercise": "Diamond Push-Up", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Tricep focus. Substitute for cable pushdown."},
            {"exercise": "Overhead Tricep Extension", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Light DB or band. Long-head tricep."},
        ],
        3: [  # Thu — Upper Pull (Weighted Pull-Up → Pull-Up, BB Row → Inverted Row)
            {"exercise": "Pull-Ups", "sets": 4, "reps": "6", "rest": "2 min",
             "note": "Build to 8 reps. Bands or assisted if not yet bodyweight."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 4, "reps": "8", "rest": "90s-2 min",
             "note": "Row substitute. 45-deg torso, pull chest to bar."},
            {"exercise": "Pull-Ups", "sets": 3, "reps": "10", "rest": "60-90s",
             "note": "Lat pulldown sub — neutral or wide grip variation."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 3, "reps": "8", "rest": "60s",
             "note": "Single-arm progression or staggered grip. Unilateral back."},
            {"exercise": "Band Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Postural."},
        ],
        4: [  # Fri — Heavy Lower (Back Squat → BW Squat / pistol, Hip Thrust → SL Glute Bridge)
            {"exercise": "Bodyweight Squats", "sets": 4, "reps": "8", "rest": "2-3 min",
             "note": "Pistol progression (assisted if needed). Below parallel — the strength session."},
            {"exercise": "Single-Leg Glute Bridge", "sets": 4, "reps": "10", "rest": "90s",
             "note": "Each leg. Hip thrust sub. Squeeze glutes hard at top."},
            {"exercise": "Nordic Hamstring Curl", "sets": 3, "reps": "6", "rest": "60s",
             "note": "Eccentric focus. Hamstring isolation sub for Lying Leg Curl."},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Second calf session of the week."},
        ],
        5: [  # Sat — Full Body Cleanup
            {"exercise": "Single-Leg Glute Bridge", "sets": 3, "reps": "10", "rest": "60-90s",
             "note": "Each leg. Glute volume (hip thrust sub)."},
            {"exercise": "DB Fly", "sets": 3, "reps": "12", "rest": "60s",
             "note": "Light DB on bench. Chest accessory (cable fly sub)."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 3, "reps": "8", "rest": "60s",
             "note": "Single-arm progression. Unilateral back."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Light DB. Lateral volume."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s",
             "note": "Core anti-extension. Plank substitute if no wheel."},
        ],
        6: [],  # Sun — rest from iron, long fasted run only
    },

    # ── Phase 2: Strength (weeks 5-7) — BW subs of spec §4 ────────────────
    2: {
        0: [  # Mon — Lower POWER + RDL (Box Jump → Squat Jump, Front Squat → Goblet)
            {"exercise": "Squat Jump", "sets": 3, "reps": "5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset between reps."},
            {"exercise": "Goblet Squat", "sets": 4, "reps": "3", "rest": "2-3 min",
             "note": "Speed-focused. Light DB at chest. Explosive concentric."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8", "rest": "60-90s",
             "note": "Each leg. Heavier than P1, explosive up."},
            {"exercise": "Single-Leg Romanian Deadlift", "sets": 3, "reps": "8", "rest": "60-90s",
             "note": "Each leg. Light DB, RPE 7. Hamstring + glute hinge."},
        ],
        1: [  # Tue — Upper PRESS + Shoulder Strength
            {"exercise": "Push-Ups", "sets": 4, "reps": "5", "rest": "2-3 min",
             "note": "Decline / weighted pack if too easy. 5-rep strength tempo."},
            {"exercise": "Pike Push-Ups", "sets": 3, "reps": "6", "rest": "90s",
             "note": "Feet elevated. Heavier P2 progression. Vertical press."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "12", "rest": "60s",
             "note": "Light DB. Constant tension. Lateral delt strength."},
            {"exercise": "Band Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
        2: [  # Wed — Shoulder Volume + Arms
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Light DB. Lateral delt volume."},
            {"exercise": "Band Reverse Fly", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Or bent-over DB reverse fly. Rear delt isolation."},
            {"exercise": "DB Hammer Curl", "sets": 3, "reps": "10", "rest": "45-60s",
             "note": "Light DB. Brachialis + biceps."},
            {"exercise": "Diamond Push-Up", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Tricep iso (cable pushdown sub)."},
            {"exercise": "DB Curl", "sets": 3, "reps": "10", "rest": "45-60s",
             "note": "Light DB. Biceps direct."},
        ],
        3: [  # Thu — Upper PULL + Lat
            {"exercise": "Pull-Ups", "sets": 4, "reps": "5", "rest": "2-3 min",
             "note": "Heavier P2. Add pack if BW is easy. Bands if not yet BW."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 4, "reps": "6", "rest": "2 min",
             "note": "Most horizontal you can manage. Pull chest to bar."},
            {"exercise": "Pull-Ups", "sets": 3, "reps": "10", "rest": "60-90s",
             "note": "Lat pulldown sub — different grip variation."},
            {"exercise": "Band Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Postural."},
        ],
        4: [  # Fri — HEAVY Lower (Back Squat → BW Squat / pistol)
            {"exercise": "Bodyweight Squats", "sets": 4, "reps": "5", "rest": "3-5 min",
             "note": "Pistol progression. 5-rep tempo: 3s down, explosive up. THE strength session."},
            {"exercise": "Single-Leg Glute Bridge", "sets": 4, "reps": "8", "rest": "90s",
             "note": "Each leg. Hip thrust sub. RPE 7. Squeeze hard at top."},
            {"exercise": "Nordic Hamstring Curl", "sets": 3, "reps": "6", "rest": "60s",
             "note": "Eccentric focus. Hamstring isolation sub."},
        ],
        5: [  # Sat — Full Body / Glute Volume
            {"exercise": "Single-Leg Glute Bridge", "sets": 3, "reps": "10", "rest": "60-90s",
             "note": "Each leg. RPE 6. Lighter Sat — second glute session."},
            {"exercise": "DB Fly", "sets": 3, "reps": "12", "rest": "60s",
             "note": "Light DB on bench. Chest accessory."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 3, "reps": "8", "rest": "60s",
             "note": "Single-arm progression. Unilateral back."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Light DB. Lateral volume."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s",
             "note": "Core anti-extension."},
        ],
        6: [],  # Sun — rest from iron, long fasted run only
    },

    # ── Phase 3: Cut climax (weeks 9-11) — BW subs of spec §6, HOLD volume ─
    3: {
        0: [  # Mon — Lower POWER (HOLD)
            {"exercise": "Squat Jump", "sets": 3, "reps": "5", "rest": "90s",
             "note": "RPE 7. Preserve power even when cutting."},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "3", "rest": "2 min",
             "note": "HOLD light DB load all 3 wks. Bump only if RPE 6 confirmed twice."},
            {"exercise": "Bulgarian Split Squat", "sets": 2, "reps": "6", "rest": "60-90s",
             "note": "Each leg. Volume cut from Phase 2."},
            {"exercise": "Single-Leg Romanian Deadlift", "sets": 2, "reps": "6", "rest": "60-90s",
             "note": "Each leg. Light DB, RPE 6. Volume cut."},
        ],
        1: [  # Tue — Press + Shoulder (HOLD)
            {"exercise": "Push-Ups", "sets": 3, "reps": "5", "rest": "3 min",
             "note": "Decline/weighted pack HOLD. Same load all 3 wks."},
            {"exercise": "Pike Push-Ups", "sets": 2, "reps": "6", "rest": "90s",
             "note": "Volume cut."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "12", "rest": "60s",
             "note": "Light DB. KEEP — shoulder priority preserved."},
            {"exercise": "Band Face Pull", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "KEEP — postural."},
        ],
        2: [  # Wed — Shoulder/Arms (cut volume)
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s",
             "note": "Light DB. KEEP."},
            {"exercise": "Band Reverse Fly", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Volume cut."},
            {"exercise": "DB Hammer Curl", "sets": 2, "reps": "10", "rest": "45-60s",
             "note": "Volume cut."},
            {"exercise": "Diamond Push-Up", "sets": 2, "reps": "12", "rest": "45-60s",
             "note": "Volume cut."},
        ],
        3: [  # Thu — Pull + Lat (HOLD)
            {"exercise": "Pull-Ups", "sets": 3, "reps": "5", "rest": "2 min",
             "note": "Same load all 3 wks. Volume cut."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 3, "reps": "6", "rest": "90s-2 min",
             "note": "HOLD — most horizontal angle."},
            {"exercise": "Pull-Ups", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Lat pulldown sub. Volume cut."},
            {"exercise": "Band Face Pull", "sets": 2, "reps": "15", "rest": "45-60s",
             "note": "Volume cut but KEPT."},
        ],
        4: [  # Fri — HEAVY Lower (HOLD)
            {"exercise": "Bodyweight Squats", "sets": 3, "reps": "3", "rest": "4 min",
             "note": "Pistol progression HOLD all 3 wks. RPE 8 cap. NO bumps."},
            {"exercise": "Single-Leg Glute Bridge", "sets": 3, "reps": "8", "rest": "90s",
             "note": "Each leg. RPE 7. Volume slightly cut."},
        ],
        5: [  # Sat — Full Body (volume cut)
            {"exercise": "Single-Leg Glute Bridge", "sets": 2, "reps": "10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"exercise": "DB Fly", "sets": 2, "reps": "12", "rest": "60s",
             "note": "Light DB. Volume cut."},
            {"exercise": "Inverted Row (table/ledge)", "sets": 2, "reps": "8", "rest": "60s",
             "note": "Single-arm progression. Volume cut."},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "12", "rest": "45-60s",
             "note": "Light DB. KEEP shoulder."},
        ],
        6: [],  # Sun — rest from iron, long fasted run only
    },

    # BW deload/test reference PHASE_TEMPLATES BW variants
    "deload": PHASE_TEMPLATES["deload_bw"],
    "test": PHASE_TEMPLATES["test_bw"],
}


# Exercise definitions
EX = {
    # UPPER A
    "bench": {"name": "Barbell Bench Press", "sets": "4x10", "note": "Control the eccentric, 2 sec down", "rest": "60-90s", "video": "barbell bench press form tutorial"},
    "incline_db": {"name": "Incline DB Press", "sets": "4x10", "note": "45 deg incline, full ROM", "rest": "60-90s", "video": "incline dumbbell press form tutorial"},
    "cable_row": {"name": "Cable Seated Row", "sets": "4x10", "note": "Elbows tight, squeeze at end", "rest": "60-90s", "video": "seated cable row proper form technique"},
    "pullup": {"name": "Lat Pulldown", "sets": "4x8", "note": "Full stretch at top, pull to upper chest", "rest": "60-90s", "video": "lat pulldown proper form tutorial"},
    "ohp": {"name": "DB Overhead Press", "sets": "3x12", "note": "Standing or seated, controlled", "rest": "60-90s", "video": "dumbbell overhead press form tutorial"},
    "face_pull": {"name": "Face Pull", "sets": "3x15", "note": "External rotation, pull to forehead", "rest": "45-60s", "video": "face pull cable exercise form tutorial"},
    "lat_raise": {"name": "Lateral Raise", "sets": "3x15", "note": "Slow and controlled, no swinging", "rest": "45-60s", "video": "dumbbell lateral raise proper form"},
    "curl_bar": {"name": "EZ-Bar Curl", "sets": "3x12", "note": "Full ROM, squeeze at top", "rest": "45-60s", "video": "ez bar curl proper form bicep tutorial"},
    "tri_ext": {"name": "Cable Tricep Pushdown", "sets": "3x12", "note": "Elbows locked, full extension", "rest": "45-60s", "video": "cable tricep pushdown form tutorial"},
    # LOWER A
    "squat": {"name": "Barbell Back Squat", "sets": "4x10", "note": "Below parallel, controlled descent", "rest": "60-90s", "video": "barbell back squat proper form tutorial"},
    "rdl": {"name": "Romanian Deadlift", "sets": "4x10", "note": "Hip hinge, feel the hamstring stretch", "rest": "60-90s", "video": "romanian deadlift form guide technique"},
    "leg_press": {"name": "Leg Press", "sets": "3x12", "note": "Feet shoulder-width, full depth", "rest": "60-90s", "video": "leg press machine proper form foot placement"},
    "lunge": {"name": "Walking Lunge", "sets": "3x12", "note": "Per leg, maintain upright torso", "rest": "60-90s", "video": "walking lunge proper form technique"},
    "leg_curl": {"name": "Lying Leg Curl", "sets": "3x12", "note": "Controlled, don't let hips rise", "rest": "45-60s", "video": "lying leg curl machine form tutorial"},
    "calf_stand": {"name": "Standing Calf Raise", "sets": "4x15", "note": "Full stretch at bottom, squeeze at top", "rest": "45-60s", "video": "standing calf raise proper form full ROM"},
    # PUSH/PULL
    "dips": {"name": "Weighted Dips", "sets": "4x10", "note": "Forward lean for chest, upright for tri", "rest": "60-90s", "video": "weighted dips chest tricep form tutorial"},
    "inc_fly": {"name": "Incline Cable Fly", "sets": "3x12", "note": "Slight bend in elbow, full stretch", "rest": "60-90s", "video": "incline cable fly chest form tutorial"},
    "pull_down": {"name": "Wide-Grip Lat Pulldown", "sets": "4x10", "note": "Pull to upper chest, lean back slightly", "rest": "60-90s", "video": "wide grip lat pulldown proper form tutorial"},
    "db_row": {"name": "Single-Arm DB Row", "sets": "4x10", "note": "Each side, row to hip not chest", "rest": "60-90s", "video": "single arm dumbbell row proper form"},
    "shrug": {"name": "DB Shrug", "sets": "3x15", "note": "Full elevation, 1 sec hold at top", "rest": "45-60s", "video": "dumbbell shrug proper form trap exercise"},
    "hammer": {"name": "Hammer Curl", "sets": "3x12", "note": "Neutral grip, both arms alternate", "rest": "45-60s", "video": "hammer curl proper form bicep tutorial"},
    "skull": {"name": "Skull Crusher", "sets": "3x12", "note": "EZ bar, elbows in, controlled", "rest": "45-60s", "video": "skull crusher ez bar tricep form tutorial"},
    # FULL BODY
    "deadlift": {"name": "Conventional Deadlift", "sets": "3x8", "note": "Hip-width stance, bar over mid-foot", "rest": "60-90s", "video": "conventional deadlift form tutorial technique"},
    "hip_thrust": {"name": "Barbell Hip Thrust", "sets": "4x10", "note": "Full extension, squeeze glutes at top", "rest": "60-90s", "video": "barbell hip thrust glute form tutorial"},
    "split_sq": {"name": "Bulgarian Split Squat", "sets": "3x10", "note": "Per leg. Rear foot elevated, upright torso.", "rest": "60-90s", "video": "bulgarian split squat proper form tutorial"},
    "kb_swing": {"name": "KB Swing", "sets": "3x15", "note": "Hip drive - not a squat. Explosive.", "rest": "60-90s", "video": "kettlebell swing form tutorial hip hinge"},
    "push_press": {"name": "Push Press", "sets": "3x8", "note": "Leg drive to initiate, lock out overhead", "rest": "60-90s", "video": "barbell push press technique tutorial"},
    "goblet": {"name": "Goblet Squat", "sets": "3x12", "note": "KB or DB at chest, upright torso", "rest": "60-90s", "video": "goblet squat form tutorial beginner"},
    "inv_row": {"name": "Ring Row", "sets": "3x12", "note": "Adjust angle for difficulty — more horizontal = harder", "rest": "60-90s", "video": "ring row form tutorial"},
    "plank": {"name": "Plank", "sets": "3x45s", "note": "Brace hard - don't sag", "rest": "60s", "video": "plank proper form core bracing tutorial"},
    # PHASE 2
    "deadlift5": {"name": "Conventional Deadlift", "sets": "5x5", "note": "RPE 8-9. Heavy and controlled. No bouncing.", "rest": "2-3 min", "video": "conventional deadlift form tutorial technique"},
    "squat5": {"name": "Barbell Back Squat", "sets": "5x5", "note": "RPE 8-9. Heavy. Below parallel every rep.", "rest": "2-3 min", "video": "barbell back squat proper form tutorial"},
    "bench5": {"name": "Barbell Bench Press", "sets": "5x5", "note": "RPE 8-9. Spotter or use safeties.", "rest": "2-3 min", "video": "barbell bench press form tutorial"},
    "weighted_pu": {"name": "Heavy Lat Pulldown", "sets": "5x5", "note": "Heavy. Full stretch, controlled pull to chest.", "rest": "2-3 min", "video": "lat pulldown heavy proper form tutorial"},
    "bb_row": {"name": "Barbell Bent-Over Row", "sets": "5x5", "note": "45 deg torso, pull to belly button", "rest": "2-3 min", "video": "barbell bent over row proper form technique"},
    "cable_fly2": {"name": "Cable Chest Fly", "sets": "3x12", "note": "Arms wide, squeeze hard at center", "rest": "60-90s", "video": "cable chest fly form tutorial pec squeeze"},
    "pull_down2": {"name": "Lat Pulldown", "sets": "3x12", "note": "Full stretch at top", "rest": "60-90s", "video": "lat pulldown proper form tutorial"},
    "rear_delt": {"name": "Rear Delt Fly", "sets": "3x15", "note": "Bent over or cable, squeeze shoulder blades", "rest": "45-60s", "video": "rear delt fly form tutorial shoulder"},
    "tri_dip": {"name": "Tricep Dip", "sets": "3x12", "note": "Bodyweight or weighted", "rest": "60-90s", "video": "tricep dip proper form bodyweight tutorial"},
    "ohp5": {"name": "Barbell OHP", "sets": "5x5", "note": "Standing strict press. No leg drive.", "rest": "2-3 min", "video": "barbell overhead press strict form tutorial"},
    "clean": {"name": "Power Clean", "sets": "4x5", "note": "From floor. Explosive pull, high elbows.", "rest": "2-3 min", "video": "power clean technique tutorial beginner"},
    "box_jump": {"name": "Box Jump", "sets": "4x5", "note": "Max effort. Land soft. Reset each rep.", "rest": "2-3 min", "video": "box jump proper form landing technique"},
    "deadlift_p2": {"name": "Deadlift", "sets": "3x5", "note": "RPE 9. Top set of the week.", "rest": "2-3 min", "video": "conventional deadlift form tutorial technique"},
    "bench_p2": {"name": "Bench Press", "sets": "3x5", "note": "RPE 8. Push hard.", "rest": "2-3 min", "video": "barbell bench press form tutorial"},
    "row_p2": {"name": "Bent-Over Row", "sets": "3x8", "note": "Controlled, heavy-ish", "rest": "60-90s", "video": "barbell bent over row proper form technique"},
    "lunge_p2": {"name": "DB Walking Lunge", "sets": "3x12", "note": "Per leg, weighted", "rest": "60-90s", "video": "dumbbell walking lunge proper form"},
    "push_ups": {"name": "Push-Ups", "sets": "2x20", "note": "Controlled, full ROM. Flush set.", "rest": "45-60s", "video": "push up proper form tutorial full ROM"},
    "ab_wheel": {"name": "Ab Wheel Rollout", "sets": "3x10", "note": "From knees or toes. Don't sag.", "rest": "60s", "video": "ab wheel rollout form tutorial beginner"},
    # PHASE 3
    "squat3": {"name": "Back Squat", "sets": "4x3", "note": "RPE 9+. Max controllable speed on way up.", "rest": "3-5 min", "video": "barbell back squat proper form tutorial"},
    "deadlift3": {"name": "Deadlift", "sets": "4x3", "note": "RPE 9+. Lock out hard. Re-set each rep.", "rest": "3-5 min", "video": "conventional deadlift form tutorial technique"},
    "bench3": {"name": "Bench Press", "sets": "4x3", "note": "RPE 9+. Explosive concentric.", "rest": "3-5 min", "video": "barbell bench press form tutorial"},
    "wpu3": {"name": "Heavy Lat Pulldown", "sets": "4x3", "note": "Heavy. Max weight you can do cleanly for 3.", "rest": "3-5 min", "video": "lat pulldown heavy proper form tutorial"},
    "box_jump3": {"name": "Box Jump", "sets": "4x5", "note": "Max height. Land quiet. Full reset.", "rest": "2-3 min", "video": "box jump proper form landing technique"},
    "med_ball": {"name": "Med Ball Slam", "sets": "3x10", "note": "Overhead to floor, explosive. 15-20 lb ball.", "rest": "60-90s", "video": "medicine ball slam form tutorial explosive"},
    "power_clean3": {"name": "Power Clean", "sets": "4x3", "note": "Heaviest of the plan. Focus on speed off floor.", "rest": "2-3 min", "video": "power clean technique tutorial beginner"},
    "pump_sq": {"name": "Goblet Squat (pump)", "sets": "3x15", "note": "Light, controlled, feel the burn", "rest": "60-90s", "video": "goblet squat form tutorial beginner"},
    "pump_press": {"name": "DB Bench (pump)", "sets": "3x15", "note": "Light, squeeze, slow eccentric", "rest": "60-90s", "video": "dumbbell bench press form tutorial"},
    "pump_row": {"name": "Cable Row (pump)", "sets": "3x15", "note": "Light, full ROM, pause at end", "rest": "60-90s", "video": "seated cable row proper form technique"},
    "pump_curl": {"name": "DB Curl (pump)", "sets": "3x15", "note": "Controlled, squeeze at top", "rest": "45-60s", "video": "dumbbell bicep curl proper form tutorial"},
    "pump_tri": {"name": "Tricep Pushdown (pump)", "sets": "3x15", "note": "Full extension, controlled", "rest": "45-60s", "video": "cable tricep pushdown form tutorial"},
    "hip_thrust3": {"name": "Barbell Hip Thrust", "sets": "3x5", "note": "Heavy. Power through glutes.", "rest": "3-5 min", "video": "barbell hip thrust glute form tutorial"},
    "split_sq3": {"name": "Bulgarian Split Squat", "sets": "3x8", "note": "Heavier than P2, explosive up", "rest": "60-90s", "video": "bulgarian split squat proper form tutorial"},
    "ohp3": {"name": "Barbell OHP", "sets": "4x3", "note": "RPE 9. Strict press, no leg drive.", "rest": "3-5 min", "video": "barbell overhead press strict form tutorial"},
    "db_row3": {"name": "DB Row", "sets": "3x8", "note": "Heavy, explosive pull", "rest": "60-90s", "video": "single arm dumbbell row proper form"},
    "leg_press3": {"name": "Leg Press (pump)", "sets": "3x15", "note": "Light-moderate, full ROM", "rest": "60-90s", "video": "leg press machine proper form foot placement"},
    "calf3": {"name": "Calf Raise (pump)", "sets": "3x20", "note": "Full stretch, slow.", "rest": "45-60s", "video": "standing calf raise proper form full ROM"},
    # TEST WEEK
    "test_sq": {"name": "Back Squat - 1RM test", "sets": "Work to 1RM", "note": "5->3->2->1 ladder. Rest fully between.", "rest": "3-5 min", "video": "squat one rep max test protocol technique"},
    "test_dl": {"name": "Deadlift - 1RM test", "sets": "Work to 1RM", "note": "5->3->2->1 ladder.", "rest": "3-5 min", "video": "deadlift one rep max test protocol technique"},
    "test_bench": {"name": "Bench Press - 1RM test", "sets": "Work to 1RM", "note": "Use safeties. Spotter ideal.", "rest": "3-5 min", "video": "bench press one rep max test protocol safety"},
    "test_pu": {"name": "Lat Pulldown - max weight", "sets": "Max weight x 1", "note": "Find your max single rep weight.", "rest": "3-5 min", "video": "lat pulldown heavy proper form tutorial"},
}


def _ex(key):
    return dict(EX[key])


def get_phase(week):
    if week <= 4:
        return 1
    if week <= 8:
        return 2
    return 3


def _run_time_from_detail(detail):
    """Sum a run's structure from its detail text so the headline time can't
    contradict it (the "35 min" on a 38-min 4x4 VO2 bug). Returns minutes, or
    None if there's no interval structure to sum (steady/tempo runs keep their
    own headline). Handles 'N min warm-up/cool-down' + intervals 'Kx M:SS / M:SS'
    (minutes) or 'Kx WW:RR' (seconds, e.g. 8x 30:90)."""
    import re as _re
    if not detail:
        return None
    d = str(detail).lower()
    mA = _re.search(r'(\d+)\s*[x×]\s*(\d+):(\d{2})\b.*?/\s*(\d+):(\d{2})', d)
    mB = _re.search(r'(\d+)\s*[x×]\s*(\d+):(\d+)\b', d)
    if mA:
        k = int(mA.group(1))
        work = int(mA.group(2)) * 60 + int(mA.group(3))
        rest = int(mA.group(4)) * 60 + int(mA.group(5))
    elif mB:
        k, work, rest = int(mB.group(1)), int(mB.group(2)), int(mB.group(3))
    else:
        return None  # no interval block — don't second-guess a steady/tempo time
    total = k * (work + rest) / 60.0
    for m in _re.finditer(
            r'(\d+)\s*min[^,.;]*?(?:warm-?up|cool-?down)'
            r'|(?:warm-?up|cool-?down)[^0-9,.;]{0,15}(\d+)\s*min', d):
        n = m.group(1) or m.group(2)
        if n:
            total += int(n)
    return int(round(total))


_LOWER_MG = {"quads", "glutes", "hamstrings", "calves", "posterior_chain", "power"}
_UPPER_MG = {"back", "biceps", "chest", "chest_triceps", "shoulders",
             "triceps", "rear_delts", "traps"}


def _warmup_type_for_day(day_dict):
    """Pick the warmup (upper/lower/full) from the day's ACTUAL exercises, not
    the weekday — DAY_WARMUP_TYPES keyed off weekday and mismatched the real
    lift on 5 of 6 days (e.g. an upper-press Tuesday got a lower warmup)."""
    exs = (day_dict or {}).get("exercises") or []
    nl = nu = 0
    for e in exs:
        mg = (EXERCISES.get(resolve_name(e.get("name", ""))) or {}).get("muscle_group") or ""
        if mg in _LOWER_MG:
            nl += 1
        elif mg in _UPPER_MG:
            nu += 1
    if nl and nu:
        return "full"
    if nl:
        return "lower"
    if nu:
        return "upper"
    return None


def get_workouts(week):
    """Return list of 7 day dicts for the given week number (1-12)."""
    # Deload WEEKS on a 4-week cadence (4, 8, 12) — the recovery valve. wk12 is
    # a deload week, NOT a volume taper (rebuilt 2026-06-01 per Erik: sawtooth
    # that trends up; deload weeks only, never a deload phase).
    is_deload = week in (4, 8, 12)

    if is_deload:
        days = _deload_week()
    else:
        phase = get_phase(week)
        if phase == 1:
            days = _phase1_week()
        elif phase == 2:
            days = _phase2_week()
        else:
            days = _phase3_week()

    # Inject meal plan and warmup data into each day
    for d in days:
        if is_deload:
            meal_type = "deload"
        else:
            meal_type = derive_meal_type(d, d.get("day", "Mon"))
        d["mealType"] = meal_type
        d["mealPlan"] = get_meal_plan(meal_type)

        # Keep the run's headline time consistent with its interval structure.
        _r = d.get("run")
        if _r and _r.get("detail"):
            _t = _run_time_from_detail(_r["detail"])
            if _t:
                _r["time"] = f"{_t} min"

        warmup_type = _warmup_type_for_day(d) or DAY_WARMUP_TYPES.get(d["day"])
        if warmup_type and warmup_type in WARMUPS:
            d["warmup"] = WARMUPS[warmup_type]
        else:
            d["warmup"] = None

    return days


def get_workouts_for_user(week, has_gym=True):
    """Get workouts using BW templates if user has no gym.

    For gym users, delegates to get_workouts(). For no-gym users,
    builds day dicts from BW_PHASE_TEMPLATES with the same meal plan
    and warmup injection.
    """
    if has_gym:
        return get_workouts(week)

    is_deload = week in (4, 8)
    is_test = week == 12
    phase = get_phase(week)

    if is_test:
        template = PHASE_TEMPLATES.get("test_bw", BW_PHASE_TEMPLATES.get(1, {}))
    elif is_deload:
        template = PHASE_TEMPLATES.get("deload_bw", BW_PHASE_TEMPLATES.get(1, {}))
    else:
        template = BW_PHASE_TEMPLATES.get(phase, BW_PHASE_TEMPLATES.get(1, {}))

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    bw_day_labels = {
        0: "Lower Hypertrophy" if phase == 1 else ("Lower POWER" if phase == 2 else "Lower POWER (HOLD)"),
        1: "Upper Press" if phase == 1 else ("Upper PRESS" if phase == 2 else "Press + Shoulder (HOLD)"),
        2: "Shoulder Volume + Arms",
        3: "Upper Pull" if phase == 1 else ("Upper PULL" if phase == 2 else "Pull + Lat (HOLD)"),
        4: "Heavy Lower" if phase == 1 else ("HEAVY Lower" if phase == 2 else "HEAVY Lower (HOLD)"),
        5: "Full Body Cleanup" if phase == 1 else ("Full Body / Glute Volume" if phase == 2 else "Full Body (volume cut)"),
        6: "Rest",
    }

    days = []
    for day_idx in range(7):
        exercises = template.get(day_idx, [])
        day_name = day_names[day_idx]
        is_rest = len(exercises) == 0

        label = bw_day_labels.get(day_idx, "Bodyweight")
        if is_deload:
            label = f"Deload BW - {label}"
        elif is_test:
            label = f"Test BW - {label}"

        # Convert template format (exercise/sets/reps) to display format (name/sets)
        display_exercises = []
        for e in exercises:
            de = {"name": e["exercise"], "rest": e.get("rest", "60s"), "note": e.get("note", "")}
            de["sets"] = f"{e['sets']}x{e['reps']}"
            display_exercises.append(de)

        d = {
            "day": day_name,
            "liftName": label if not is_rest else "Rest - Streak Day Only",
            "exercises": display_exercises,
            "run": _run("min") if is_rest else _run("z2_40"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"] if is_rest else [],
            "notes": "Rest day." if is_rest else "",
        }
        if is_rest:
            d["isRest"] = True

        # Inject meal plan and warmup
        if is_deload:
            meal_type = "deload"
        else:
            meal_type = derive_meal_type(d, day_name)
        d["mealType"] = meal_type
        d["mealPlan"] = get_meal_plan(meal_type)

        warmup_type = _warmup_type_for_day(d) or DAY_WARMUP_TYPES.get(day_name)
        if warmup_type and warmup_type in WARMUPS:
            d["warmup"] = WARMUPS[warmup_type]
        else:
            d["warmup"] = None

        days.append(d)

    return days


def _run(key):
    return dict(RUNS[key])


def _empty_day(day_idx):
    """Default skeleton for a day in a phase template."""
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "day": DAY_NAMES[day_idx] if day_idx < 7 else "?",
        "day_idx": day_idx,
        "liftName": "Rest",
        "isRest": False,
        "exercises": [],
    }


def _phase1_week():
    """Phase 1 (wks 1-3): Hypertrophy / adaptation per spec §2.

    Each day dict carries the keys the front-end consumes unguarded:
      - run: {type, label, time, detail}
      - timing: list of [time, label, time, label, ...] strings
      - notes: day-level coach note string
    """
    days = [_empty_day(i) for i in range(7)]
    # Mon — Lower hypertrophy
    days[0] = {
        **days[0],
        "liftName": "Lower Hypertrophy — Quad/Glute Focus",
        "exercises": [
            {"name": "Front Squat", "sets": "4x8", "rest": "2-3 min",
             "note": "Build reps to 12 across all sets; then bump weight."},
            {"name": "Bulgarian Split Squat", "sets": "3x8",
             "rest": "60-90s",
             "note": "Each leg. Unilateral, leg power transfer."},
            {"name": "Romanian Deadlift", "sets": "3x8", "rest": "60-90s",
             "note": "RPE 7. Hamstring + glute hinge."},
            {"name": "Standing Calf Raise", "sets": "3x12",
             "rest": "45-60s", "note": "Full ROM, slow eccentric."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "35 min",
                "detail": "HR 130-145. Conversational pace. Easy aerobic."},
        "timing": ["6:00", "Lift - Lower Hypertrophy (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "Zone 2 easy 35 min"],
        "notes": "Front Squat lead. Build reps 8→12, then bump weight.",
    }
    # Tue — Press + Shoulder
    days[1] = {
        **days[1],
        "liftName": "Upper Press — Shoulder Build",
        "exercises": [
            {"name": "Barbell Bench Press", "sets": "4x8",
             "rest": "2 min",
             "note": "Build to 10 reps. Pause at chest."},
            {"name": "Landmine Press", "sets": "3x8", "rest": "90s",
             "note": "Each side. Shoulder-friendly OHP."},
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "60s",
             "note": "Constant tension. Shoulder rebuild priority."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
        "run": {"type": "hiit", "label": "Threshold intervals", "time": "35 min",
                "detail": "5 min warmup, 8x 2:00 at threshold / 1:00 easy, 5 min cooldown."},
        "timing": ["6:00", "Lift - Upper Press (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Threshold intervals 35 min"],
        "notes": "Shoulder warm-up mandatory. Band pull-aparts + face pulls before pressing.",
    }
    # Wed — Shoulder volume + Arms
    days[2] = {
        **days[2],
        "liftName": "Shoulder Volume + Arms",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "4x15", "rest": "45-60s",
             "note": "More lateral delt volume."},
            {"name": "Reverse Pec Deck", "sets": "3x12", "rest": "45-60s",
             "note": "Rear delt isolation."},
            {"name": "Hammer Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Brachialis + biceps."},
            {"name": "EZ-Bar Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Biceps direct."},
            {"name": "Cable Tricep Pushdown", "sets": "3x12",
             "rest": "45-60s", "note": "Tricep iso."},
            {"name": "Overhead Tricep Extension", "sets": "3x12",
             "rest": "45-60s", "note": "Long-head tricep."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "45 min",
                "detail": "HR 130-145. Aerobic volume building."},
        "timing": ["6:00", "Lift - Shoulder/Arms (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 45 min"],
        "notes": "High-volume isolation, low CNS day. Aerobic emphasis on the run.",
    }
    # Thu — Pull + Lat
    days[3] = {
        **days[3],
        "liftName": "Upper Pull — Lat Focus",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "4x6", "rest": "2 min",
             "note": "Build to 8 reps. BW 4×8-12 if not yet weighted."},
            {"name": "Barbell Bent-Over Row", "sets": "4x8",
             "rest": "90s-2 min",
             "note": "45-deg torso, pull to belly button."},
            {"name": "Lat Pulldown", "sets": "3x10", "rest": "60-90s",
             "note": "Neutral grip. Different angle."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm. Unilateral back."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural."},
        ],
        "run": {"type": "hiit", "label": "Threshold or hill repeats", "time": "35 min",
                "detail": "5 min warmup, 6-8x hill repeats or 4-min threshold blocks, 5 min cooldown."},
        "timing": ["6:00", "Lift - Upper Pull (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "Threshold/hill repeats 35 min"],
        "notes": "Heavy pull day. Hill repeats hit posterior chain — keep the lift volume honest.",
    }
    # Fri — Heavy Lower hypertrophy
    days[4] = {
        **days[4],
        "liftName": "Heavy Lower — Squat Focus",
        "exercises": [
            {"name": "Back Squat", "sets": "4x8", "rest": "2-3 min",
             "note": "~70%. Below parallel. The hypertrophy strength session."},
            {"name": "Hip Thrust", "sets": "4x10", "rest": "90s",
             "note": "Squeeze glutes hard at top."},
            {"name": "Lying Leg Curl", "sets": "3x12", "rest": "60s",
             "note": "Hamstring isolation."},
            {"name": "Standing Calf Raise", "sets": "3x12", "rest": "45-60s",
             "note": "Second calf session of the week."},
        ],
        "run": {"type": "z2", "label": "Recovery jog", "time": "20 min",
                "detail": "HR under 130. Easy shuffle to flush legs after heavy squats."},
        "timing": ["6:00", "Lift - Heavy Lower (60 min)",
                   "7:05", "5 min transition",
                   "7:10", "Recovery jog 20 min"],
        "notes": "This is THE strength session of the week. Squat heavy. Recovery jog only — keep HR low.",
    }
    # Sat — Full Body
    days[5] = {
        **days[5],
        "liftName": "Full Body Cleanup",
        "exercises": [
            {"name": "Hip Thrust", "sets": "3x10", "rest": "60-90s",
             "note": "Glute volume."},
            {"name": "Cable Chest Fly", "sets": "3x12", "rest": "60s",
             "note": "Chest accessory."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm."},
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s",
             "note": "Lateral volume."},
            {"name": "Ab Wheel Rollout", "sets": "3x10", "rest": "60s",
             "note": "Core anti-extension."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "30 min",
                "detail": "HR 130-145. Aerobic. Honest, conversational pace."},
        "timing": ["6:00", "Lift - Full Body (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 30 min"],
        "notes": "Full-body cleanup of weak points. Aerobic emphasis on the run.",
    }
    # Sun (idx 6) — rest from iron, long fasted run is the only activity
    days[6] = {
        **days[6],
        "liftName": "Rest (Long Fasted Run)",
        "isRest": True,
        "run": {"type": "z2_long", "label": "Long fasted easy run",
                "time": "90 min",
                "detail": "Fasted state, fat-ox bias. HR under 140. Conversational."},
        "timing": ["6:00", "Long fasted run 60-90 min",
                   "8:00", "Refuel"],
        "notes": "Sunday — deepest fast. Long aerobic only.",
    }
    return days


def _phase2_week():
    """Phase 2 (wks 5-7): Strength block per spec §4.

    Each day dict carries the keys the front-end consumes unguarded:
      - run: {type, label, time, detail}
      - timing: list of [time, label, time, label, ...] strings
      - notes: day-level coach note string
    """
    days = [_empty_day(i) for i in range(7)]
    # Mon — Lower POWER + RDL
    days[0] = {
        **days[0],
        "liftName": "Lower POWER + RDL",
        "exercises": [
            {"name": "Box Jump", "sets": "3x5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset between reps."},
            {"name": "Front Squat", "sets": "4x3", "rest": "2-3 min",
             "note": "Speed-focused. ~70-76% wave (wk5/6/7)."},
            {"name": "Bulgarian Split Squat", "sets": "3x8", "rest": "60-90s",
             "note": "Each leg. Heavier than P1, explosive up."},
            {"name": "Romanian Deadlift", "sets": "3x8", "rest": "60-90s",
             "note": "RPE 7. Hamstring + glute hinge."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "35 min",
                "detail": "HR 130-145. Conversational. Easy aerobic after power lower."},
        "timing": ["6:00", "Lift - Lower POWER (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "Zone 2 easy 35 min"],
        "notes": "Box jumps first when CNS is fresh. Front squat speed, not grind.",
    }
    # Tue — Upper PRESS + Shoulder Strength
    days[1] = {
        **days[1],
        "liftName": "Upper PRESS + Shoulder Strength",
        "exercises": [
            {"name": "Barbell Bench Press", "sets": "4x5", "rest": "2-3 min",
             "note": "75-82% wave (wk5/6/7). Pause at chest."},
            {"name": "Landmine Press", "sets": "3x6", "rest": "90s",
             "note": "Each side. Heavier P2 progression."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "60s",
             "note": "Constant tension. Lateral delt strength."},
            {"name": "Cable Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural — mandatory each press/pull day."},
        ],
        "run": {"type": "hiit", "label": "VO2 4x4 intervals", "time": "35 min",
                "detail": "5 min warmup, 4x 4:00 hard / 3:00 easy, 5 min cooldown. VO2max work."},
        "timing": ["6:00", "Lift - Upper Press (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "VO2 4x4 intervals 35 min"],
        "notes": "Shoulder warm-up mandatory. VO2 4x4 is hard — pace the first interval honestly.",
    }
    # Wed — Shoulder Volume + Arms
    days[2] = {
        **days[2],
        "liftName": "Shoulder Volume + Arms",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s",
             "note": "Lateral delt volume."},
            {"name": "Reverse Pec Deck", "sets": "3x12", "rest": "45-60s",
             "note": "Rear delt isolation."},
            {"name": "Hammer Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Brachialis + biceps."},
            {"name": "Cable Tricep Pushdown", "sets": "3x12", "rest": "45-60s",
             "note": "Tricep iso."},
            {"name": "EZ-Bar Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Biceps direct."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "45 min",
                "detail": "HR 130-145. Aerobic volume building."},
        "timing": ["6:00", "Lift - Shoulder/Arms (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 45 min"],
        "notes": "Low CNS day. High-volume isolation, aerobic emphasis on the run.",
    }
    # Thu — Upper PULL + Lat
    days[3] = {
        **days[3],
        "liftName": "Upper PULL + Lat",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "4x5", "rest": "2-3 min",
             "note": "Heavier P2. BW 4×6-10 if not yet weighted."},
            {"name": "Barbell Bent-Over Row", "sets": "4x6", "rest": "2 min",
             "note": "75-82% wave. 45-deg torso, pull to belly button."},
            {"name": "Lat Pulldown", "sets": "3x10", "rest": "60-90s",
             "note": "Neutral grip. Different angle."},
            {"name": "Cable Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural."},
        ],
        "run": {"type": "hiit", "label": "VO2 4x4 intervals", "time": "35 min",
                "detail": "5 min warmup, 4x 4:00 hard / 3:00 easy, 5 min cooldown. VO2max work."},
        "timing": ["6:00", "Lift - Upper Pull (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "VO2 4x4 intervals 35 min"],
        "notes": "Heavy pull day. Second VO2 session — keep first interval honest.",
    }
    # Fri — HEAVY Lower
    days[4] = {
        **days[4],
        "liftName": "HEAVY Lower — THE Strength Session",
        "exercises": [
            {"name": "Back Squat", "sets": "4x5", "rest": "3-5 min",
             "note": "78% wk5; engine waves to 82% wk6, 87% wk7. Below parallel."},
            {"name": "Hip Thrust", "sets": "4x8", "rest": "90s",
             "note": "RPE 7. Squeeze glutes hard at top."},
            {"name": "Lying Leg Curl", "sets": "3x10", "rest": "60s",
             "note": "Hamstring isolation."},
        ],
        "run": {"type": "z2", "label": "Recovery jog", "time": "20 min",
                "detail": "HR under 130. Easy shuffle to flush legs after heavy squats."},
        "timing": ["6:00", "Lift - Heavy Lower (60 min)",
                   "7:05", "5 min transition",
                   "7:10", "Recovery jog 20 min"],
        "notes": "THE strength session of the week. Squat heavy. Recovery jog only — keep HR low.",
    }
    # Sat — Full Body / Glute Volume
    days[5] = {
        **days[5],
        "liftName": "Full Body / Glute Volume",
        "exercises": [
            {"name": "Hip Thrust", "sets": "3x10", "rest": "60-90s",
             "note": "RPE 6. Lighter Sat — second hip thrust of the week."},
            {"name": "Cable Chest Fly", "sets": "3x12", "rest": "60s",
             "note": "Chest accessory."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm. Unilateral back."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "45-60s",
             "note": "Lateral volume."},
            {"name": "Ab Wheel Rollout", "sets": "3x10", "rest": "60s",
             "note": "Core anti-extension."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "30 min",
                "detail": "HR 130-145. Aerobic. Honest, conversational pace."},
        "timing": ["6:00", "Lift - Full Body / Glutes (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 30 min"],
        "notes": "Lighter Sat. Glute volume + accessory. Aerobic emphasis on the run.",
    }
    # Sun (idx 6) — rest from iron, long fasted run is the only activity
    days[6] = {
        **days[6],
        "liftName": "Rest (Long Fasted Run)",
        "isRest": True,
        "run": {"type": "z2_long", "label": "Long fasted easy run",
                "time": "90 min",
                "detail": "Fasted state, fat-ox bias. HR under 140. Conversational."},
        "timing": ["6:00", "Long fasted run 60-90 min",
                   "8:00", "Refuel"],
        "notes": "Sunday — deepest fast. Long aerobic only.",
    }
    return days


def _phase3_week():
    """Phase 3 (wks 9-11): FULL strength volume, loads CLIMB.

    Rebuilt 2026-06-01 (Erik): the old "cut climax" was a deload PHASE (~55
    sets, weights HELD). Bad coaching. Volume now matches Phase 2 (~81 sets),
    loads progress, no HOLD. Deload happens only on WEEKS (4/8/12). The run
    progression (VO2 4x3, threshold, etc.) is kept.

    Each day dict carries the keys the front-end consumes unguarded:
      - run: {type, label, time, detail}
      - timing: list of [time, label, time, label, ...] strings
      - notes: day-level coach note string
    """
    days = [_empty_day(i) for i in range(7)]
    # Mon — Lower (heavy)
    days[0] = {
        **days[0],
        "liftName": "Lower (heavy)",
        "exercises": [
            {"name": "Box Jump", "sets": "3x5", "rest": "90s",
             "note": "RPE 7. Preserve power."},
            {"name": "Front Squat", "sets": "4x3", "rest": "2 min",
             "note": "Heavy triples — progress when RPE <= 6 confirmed."},
            {"name": "Bulgarian Split Squat", "sets": "3x6", "rest": "60-90s",
             "note": "Each leg. Progress when clean."},
            {"name": "Romanian Deadlift", "sets": "3x6", "rest": "60-90s",
             "note": "RPE 7. Hinge volume restored."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "30 min",
                "detail": "HR 130-145. Conversational pace. Easy aerobic."},
        "timing": ["6:00", "Lift - Lower heavy (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 30 min"],
        "notes": "Box jumps first when CNS is fresh. Front squat heavy triples — push loads when reps are clean.",
    }
    # Tue — Press + Shoulder
    days[1] = {
        **days[1],
        "liftName": "Press + Shoulder",
        "exercises": [
            {"name": "Barbell Bench Press", "sets": "4x5", "rest": "3 min",
             "note": "Progress when reps clean."},
            {"name": "Landmine Press", "sets": "3x6", "rest": "90s",
             "note": "Each side."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "60s",
             "note": "Shoulder priority."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural."},
        ],
        "run": {"type": "hiit", "label": "VO2 4x3 intervals", "time": "35 min",
                "detail": "5 min warmup, 4x 3:00 hard / 3:00 easy, 5 min cooldown."},
        "timing": ["6:00", "Lift - Press + Shoulder (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "VO2 4x3 intervals 35 min"],
        "notes": "Bench progresses when clean. Lateral raise + face pull every press/pull day.",
    }
    # Wed — Shoulder/Arms
    days[2] = {
        **days[2],
        "liftName": "Shoulder/Arms",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "3x15", "rest": "45-60s",
             "note": "Lateral delt volume."},
            {"name": "Reverse Pec Deck", "sets": "3x12", "rest": "45-60s",
             "note": "Rear delt."},
            {"name": "Hammer Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Brachialis + biceps."},
            {"name": "Cable Tricep Pushdown", "sets": "3x12", "rest": "45-60s",
             "note": "Tricep iso."},
            {"name": "EZ-Bar Curl", "sets": "3x10", "rest": "45-60s",
             "note": "Biceps direct — restored."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "35 min",
                "detail": "HR 130-145. Aerobic — fat-ox bias."},
        "timing": ["6:00", "Lift - Shoulder/Arms (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 35 min"],
        "notes": "Full accessory volume. Lateral raises are the shoulder priority.",
    }
    # Thu — Pull + Lat
    days[3] = {
        **days[3],
        "liftName": "Pull + Lat",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "4x5", "rest": "2 min",
             "note": "Progress when clean."},
            {"name": "Barbell Bent-Over Row", "sets": "4x6", "rest": "90s-2 min",
             "note": "Progress when clean."},
            {"name": "Lat Pulldown", "sets": "3x10", "rest": "60-90s",
             "note": "Neutral grip."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "Postural."},
        ],
        "run": {"type": "hiit", "label": "Threshold intervals", "time": "35 min",
                "detail": "5 min warmup, 8x 2:00 at threshold / 1:00 easy, 5 min cooldown."},
        "timing": ["6:00", "Lift - Pull + Lat (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "Threshold intervals 35 min"],
        "notes": "Heavy pull day. Pull-up + Row progress when clean.",
    }
    # Fri — HEAVY Lower
    days[4] = {
        **days[4],
        "liftName": "HEAVY Lower",
        "exercises": [
            {"name": "Back Squat", "sets": "4x3", "rest": "4 min",
             "note": "Heavy triples — progress when RPE <= 8."},
            {"name": "Hip Thrust", "sets": "4x8", "rest": "90s",
             "note": "RPE 7. Squeeze at top."},
            {"name": "Lying Leg Curl", "sets": "3x10", "rest": "60s",
             "note": "Hamstring (knee flexion) — restored."},
        ],
        "run": {"type": "z2", "label": "Recovery jog", "time": "15 min",
                "detail": "HR under 130. Easy shuffle to flush legs after heavy squats."},
        "timing": ["6:00", "Lift - HEAVY Lower (55 min)",
                   "7:00", "5 min transition",
                   "7:05", "Recovery jog 15 min"],
        "notes": "THE strength session. Back Squat heavy triples — push loads when bar speed holds.",
    }
    # Sat — Full Body
    days[5] = {
        **days[5],
        "liftName": "Full Body",
        "exercises": [
            {"name": "Hip Thrust", "sets": "3x10", "rest": "60-90s",
             "note": "Second glute session."},
            {"name": "Cable Chest Fly", "sets": "3x12", "rest": "60s",
             "note": "Chest accessory."},
            {"name": "Single-Arm DB Row", "sets": "3x8", "rest": "60s",
             "note": "Each arm."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "45-60s",
             "note": "Shoulder priority."},
            {"name": "Ab Wheel Rollout", "sets": "3x10", "rest": "60s",
             "note": "Core anti-extension — restored."},
        ],
        "run": {"type": "z2", "label": "Zone 2 easy", "time": "25 min",
                "detail": "HR 130-145. Aerobic. Honest, conversational pace."},
        "timing": ["6:00", "Lift - Full Body (50 min)",
                   "6:55", "5 min transition",
                   "7:00", "Zone 2 easy 25 min"],
        "notes": "Full accessory volume. Lateral raises kept as shoulder priority.",
    }
    # Sun (idx 6) — rest from iron, long fasted run is the only activity
    days[6] = {
        **days[6],
        "liftName": "Rest (Long Fasted Run)",
        "isRest": True,
        "run": {"type": "z2_long", "label": "Long fasted easy run",
                "time": "90 min",
                "detail": "Fasted state, fat-ox bias. HR under 140. Conversational."},
        "timing": ["6:00", "Long fasted run 60-90 min",
                   "8:00", "Refuel"],
        "notes": "Sunday — deepest fast. Long aerobic only.",
    }
    return days


def _deload_week():
    """Deload weeks (4, 8) per spec §3 / §5.

    Volume cut 50%, intensity ~70%. NO HIIT — Tue/Thu HIIT slots become
    easy zone-2. Sessions cap at 30 min. Long run drops to 60 min Sun.

    Each day dict carries the keys the front-end consumes unguarded:
      - run: {type, label, time, detail}
      - timing: list of [time, label, time, label, ...] strings
      - notes: day-level coach note string
    """
    days = [_empty_day(i) for i in range(7)]
    # Mon — Deload Lower
    days[0] = {
        **days[0],
        "liftName": "Deload — Lower",
        "exercises": [
            {"name": "Box Jump", "sets": "2x5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset between reps."},
            {"name": "Front Squat", "sets": "3x3", "rest": "2 min",
             "note": "65% of working weight. Move well, feel light."},
            {"name": "Bulgarian Split Squat", "sets": "2x8",
             "rest": "60-90s", "note": "Each leg. Volume cut 50%."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2", "time": "25 min",
                "detail": "HR 130-145. Conversational. Deload — keep it honest."},
        "timing": ["6:00", "Deload lift - Lower (30 min)",
                   "6:35", "5 min transition",
                   "6:40", "Easy zone-2 25 min"],
        "notes": "Deload. 50% volume cut, ~70% intensity. Move well, recover.",
    }
    # Tue — Deload Press + Shoulder (NO HIIT)
    days[1] = {
        **days[1],
        "liftName": "Deload — Press + Shoulder",
        "exercises": [
            {"name": "Barbell Bench Press", "sets": "3x5", "rest": "2 min",
             "note": "70% of working weight. Controlled."},
            {"name": "Landmine Press", "sets": "2x6", "rest": "90s",
             "note": "Each side. Volume cut."},
            {"name": "Cable Lateral Raise", "sets": "2x12",
             "rest": "60s", "note": "Constant tension, light."},
            {"name": "Face Pull", "sets": "2x15", "rest": "45-60s",
             "note": "Postural — keep doing this."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2 (NO HIIT)", "time": "35 min",
                "detail": "HR 130-145. Conversational. Deload drops HIIT — easy aerobic only."},
        "timing": ["6:00", "Deload lift - Press + Shoulder (30 min)",
                   "6:35", "5 min transition",
                   "6:40", "Easy zone-2 35 min"],
        "notes": "Deload. NO HIIT this week — easy aerobic. 70% intensity on press.",
    }
    # Wed — Deload Shoulder/Arms (light)
    days[2] = {
        **days[2],
        "liftName": "Deload — Shoulder/Arms (light)",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "2x15",
             "rest": "45-60s", "note": "Light. Lateral delt volume cut."},
            {"name": "Reverse Pec Deck", "sets": "2x12",
             "rest": "45-60s", "note": "Light. Rear delt isolation."},
            {"name": "Cable Tricep Pushdown", "sets": "2x12",
             "rest": "45-60s", "note": "Or curl — pick one. Volume cut."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2", "time": "35 min",
                "detail": "HR 130-145. Aerobic recovery during deload."},
        "timing": ["6:00", "Deload lift - Shoulder/Arms (25 min)",
                   "6:30", "5 min transition",
                   "6:35", "Easy zone-2 35 min"],
        "notes": "Deload. Pick triceps or curls — not both. Just feel the muscle.",
    }
    # Thu — Deload Pull (NO HIIT)
    days[3] = {
        **days[3],
        "liftName": "Deload — Pull",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "3x5", "rest": "2 min",
             "note": "Bodyweight only. No added weight in deload."},
            {"name": "Barbell Bent-Over Row", "sets": "3x6",
             "rest": "90s-2 min",
             "note": "70% of working weight. Pull to belly button."},
            {"name": "Lat Pulldown", "sets": "2x10",
             "rest": "60-90s", "note": "Light. Volume cut."},
            {"name": "Face Pull", "sets": "2x15",
             "rest": "45-60s", "note": "Postural."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2 (NO HIIT)", "time": "35 min",
                "detail": "HR 130-145. Conversational. Deload drops HIIT — easy aerobic only."},
        "timing": ["6:00", "Deload lift - Pull (30 min)",
                   "6:35", "5 min transition",
                   "6:40", "Easy zone-2 35 min"],
        "notes": "Deload. NO HIIT. Pull-up at bodyweight only. 70% on row.",
    }
    # Fri — Deload Heavy Lower (light)
    days[4] = {
        **days[4],
        "liftName": "Deload — Heavy Lower (light)",
        "exercises": [
            {"name": "Back Squat", "sets": "3x5", "rest": "2-3 min",
             "note": "65% of working weight. Move well — this is the deload Fri."},
            {"name": "Hip Thrust", "sets": "3x8", "rest": "90s",
             "note": "RPE 6. Light, squeeze glutes."},
        ],
        "run": {"type": "z2", "label": "Easy recovery", "time": "20 min",
                "detail": "HR under 130. Easy shuffle to flush legs."},
        "timing": ["6:00", "Deload lift - Heavy Lower light (25 min)",
                   "6:30", "5 min transition",
                   "6:35", "Easy recovery 20 min"],
        "notes": "Deload Fri. Back Squat 3x5 @ 65% — move well, no grind.",
    }
    # Sat — Deload Full Body Light
    days[5] = {
        **days[5],
        "liftName": "Deload — Full Body Light",
        "exercises": [
            {"name": "Hip Thrust", "sets": "2x10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"name": "Cable Chest Fly", "sets": "2x12",
             "rest": "60s", "note": "Light. Chest accessory."},
            {"name": "Single-Arm DB Row", "sets": "2x8",
             "rest": "60s", "note": "Each arm. Light."},
            {"name": "Cable Lateral Raise", "sets": "2x12",
             "rest": "45-60s", "note": "Light lateral volume."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2", "time": "25 min",
                "detail": "HR 130-145. Honest, conversational pace."},
        "timing": ["6:00", "Deload lift - Full Body light (25 min)",
                   "6:30", "5 min transition",
                   "6:35", "Easy zone-2 25 min"],
        "notes": "Deload Sat. Light full body cleanup. Recover for next phase.",
    }
    # Sun (idx 6) — long fasted run only, deload duration
    days[6] = {
        **days[6],
        "liftName": "Rest (Long Fasted Run, 60 min)",
        "isRest": True,
        "run": {"type": "z2_long", "label": "Long fasted easy run",
                "time": "60 min",
                "detail": "Fasted. HR under 140. Conversational. Deload — short long run."},
        "timing": ["6:00", "Long fasted run 60 min",
                   "7:00", "Refuel"],
        "notes": "Deload Sun. 60-min long run only. Recover.",
    }
    return days


def _test_week():
    """Week 12 = peak finish per spec §7 (mini-taper, scale + look,
    NOT 1RM test). Volume cut another ~25% from Phase 3. Intensity held
    on compounds (single working set each). Drop direct arm work. NO HIIT.

    Each day dict carries the keys the front-end consumes unguarded:
      - run: {type, label, time, detail}
      - timing: list of [time, label, time, label, ...] strings
      - notes: day-level coach note string
    """
    days = [_empty_day(i) for i in range(7)]
    # Mon — Wk12 Lower (taper)
    days[0] = {
        **days[0],
        "liftName": "Wk12 — Lower (taper)",
        "exercises": [
            {"name": "Box Jump", "sets": "2x5", "rest": "60-90s",
             "note": "CNS primer. Max height, full reset between reps."},
            {"name": "Front Squat", "sets": "2x3", "rest": "2-3 min",
             "note": "73% — single working set. Speed-focused."},
            {"name": "Bulgarian Split Squat", "sets": "1x6",
             "rest": "60-90s", "note": "Each leg. Volume cut from P3."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2", "time": "20 min",
                "detail": "HR 130-145. Mini-taper — short and easy."},
        "timing": ["6:00", "Lift - Lower taper (25 min)",
                   "6:30", "5 min transition",
                   "6:35", "Easy zone-2 20 min"],
        "notes": "Wk12 mini-taper. Single working set on Front Squat. Look + scale, not 1RM.",
    }
    # Tue — Wk12 Press + Shoulder (taper, NO HIIT)
    days[1] = {
        **days[1],
        "liftName": "Wk12 — Press + Shoulder (taper)",
        "exercises": [
            {"name": "Barbell Bench Press", "sets": "2x5", "rest": "2-3 min",
             "note": "80% — single working set."},
            {"name": "Landmine Press", "sets": "1x6", "rest": "90s",
             "note": "Each side. Single working set."},
            {"name": "Cable Lateral Raise", "sets": "3x12", "rest": "60s",
             "note": "KEEP — makes the look."},
            {"name": "Face Pull", "sets": "3x15", "rest": "45-60s",
             "note": "KEEP — postural, mandatory."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2 (NO HIIT)", "time": "35 min",
                "detail": "HR 130-145. Peak taper drops HIIT — easy aerobic only."},
        "timing": ["6:00", "Lift - Press + Shoulder taper (30 min)",
                   "6:35", "5 min transition",
                   "6:40", "Easy zone-2 35 min"],
        "notes": "Wk12 taper. NO HIIT. Lateral + face pull volume KEPT — they make the look.",
    }
    # Wed — Wk12 Shoulder Volume Only
    days[2] = {
        **days[2],
        "liftName": "Wk12 — Shoulder Volume Only",
        "exercises": [
            {"name": "Cable Lateral Raise", "sets": "3x15",
             "rest": "45-60s", "note": "KEEP — shoulder volume for the look."},
            {"name": "Reverse Pec Deck", "sets": "2x12",
             "rest": "45-60s", "note": "Rear delt isolation."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2", "time": "30 min",
                "detail": "HR 130-145. Aerobic recovery during peak taper."},
        "timing": ["6:00", "Lift - Shoulder volume only (15 min)",
                   "6:20", "5 min transition",
                   "6:25", "Easy zone-2 30 min"],
        "notes": "Wk12 taper. Direct arms dropped. Shoulder volume KEPT for the look.",
    }
    # Thu — Wk12 Pull (taper, NO HIIT)
    days[3] = {
        **days[3],
        "liftName": "Wk12 — Pull (taper)",
        "exercises": [
            {"name": "Weighted Pull-Up", "sets": "2x5", "rest": "2 min",
             "note": "Single working set. Same load as P3."},
            {"name": "Barbell Bent-Over Row", "sets": "2x6",
             "rest": "90s-2 min",
             "note": "80% — single working set."},
            {"name": "Lat Pulldown", "sets": "1x10",
             "rest": "60-90s", "note": "Single working set."},
            {"name": "Face Pull", "sets": "2x15",
             "rest": "45-60s", "note": "Postural."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2 (NO HIIT)", "time": "30 min",
                "detail": "HR 130-145. Peak taper drops HIIT — easy aerobic only."},
        "timing": ["6:00", "Lift - Pull taper (25 min)",
                   "6:30", "5 min transition",
                   "6:35", "Easy zone-2 30 min"],
        "notes": "Wk12 taper. NO HIIT. Single working set on each compound.",
    }
    # Fri — Wk12 Heavy Lower (taper)
    days[4] = {
        **days[4],
        "liftName": "Wk12 — Heavy Lower (taper)",
        "exercises": [
            {"name": "Back Squat", "sets": "2x3", "rest": "3-5 min",
             "note": "87% — single working set, just to feel it."},
            {"name": "Hip Thrust", "sets": "2x8", "rest": "90s",
             "note": "Glute volume."},
        ],
        "run": {"type": "z2", "label": "Easy recovery", "time": "15 min",
                "detail": "HR under 130. Easy shuffle. Mini-taper."},
        "timing": ["6:00", "Lift - Heavy Lower taper (20 min)",
                   "6:25", "5 min transition",
                   "6:30", "Easy recovery 15 min"],
        "notes": "Wk12 Fri. Back Squat 2x3 @ 87% single working set — feel it, not test it.",
    }
    # Sat — Wk12 Full Body (taper)
    days[5] = {
        **days[5],
        "liftName": "Wk12 — Full Body (taper)",
        "exercises": [
            {"name": "Hip Thrust", "sets": "2x10", "rest": "60-90s",
             "note": "Light. Twice/week glute."},
            {"name": "Cable Chest Fly", "sets": "2x12",
             "rest": "60s", "note": "Chest accessory."},
            {"name": "Cable Lateral Raise", "sets": "2x12",
             "rest": "45-60s", "note": "Lateral volume — final week."},
        ],
        "run": {"type": "z2", "label": "Easy zone-2", "time": "20 min",
                "detail": "HR 130-145. Final aerobic of the program."},
        "timing": ["6:00", "Lift - Full Body taper (20 min)",
                   "6:25", "5 min transition",
                   "6:30", "Easy zone-2 20 min"],
        "notes": "Wk12 Sat. Final lift. Finish clean — note how this feels vs week 1.",
    }
    # Sun (idx 6) — long fasted run only, taper duration
    days[6] = {
        **days[6],
        "liftName": "Rest (Long Fasted Run, 60 min)",
        "isRest": True,
        "run": {"type": "z2_long", "label": "Long fasted easy run",
                "time": "60 min",
                "detail": "Fasted. HR under 140. Conversational. Final long run."},
        "timing": ["6:00", "Long fasted run 60 min",
                   "7:00", "Refuel"],
        "notes": "Wk12 Sun. 60-min long run. 12 weeks done.",
    }
    return days
