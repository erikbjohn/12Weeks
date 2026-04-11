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
            {"name": "Arm circles", "duration": "30s", "note": "15s forward, 15s backward"},
            {"name": "Band pull-aparts", "duration": "30s", "note": "20 reps, light band"},
            {"name": "Band dislocates", "duration": "30s", "note": "10 slow reps"},
            {"name": "Push-up to downward dog", "duration": "60s", "note": "8 reps, slow and controlled"},
            {"name": "Cat-cow stretch", "duration": "30s", "note": "8 reps, breathe"},
            {"name": "Empty bar bench press", "duration": "60s", "note": "15 reps, slow"},
            {"name": "Empty bar OHP", "duration": "60s", "note": "10 reps, feel the groove"},
        ],
    },
    "lower": {
        "label": "Lower Body Warm-Up",
        "time": "10 min",
        "steps": [
            {"name": "Bodyweight squats", "duration": "45s", "note": "15 reps, full depth"},
            {"name": "Leg swings (front-back)", "duration": "30s", "note": "10 each leg, hold something"},
            {"name": "Leg swings (side-side)", "duration": "30s", "note": "10 each leg"},
            {"name": "Hip circles", "duration": "30s", "note": "8 each direction"},
            {"name": "Walking lunges", "duration": "45s", "note": "8 each leg, bodyweight"},
            {"name": "Glute bridges", "duration": "30s", "note": "15 reps, squeeze at top"},
            {"name": "Empty bar squat", "duration": "60s", "note": "10 reps, below parallel"},
        ],
    },
    "full": {
        "label": "Full Body Warm-Up",
        "time": "10 min",
        "steps": [
            {"name": "Jumping jacks", "duration": "30s", "note": "Get the heart rate up"},
            {"name": "Arm circles + leg swings", "duration": "30s", "note": "Multitask"},
            {"name": "Bodyweight squats", "duration": "30s", "note": "10 reps"},
            {"name": "Push-ups", "duration": "30s", "note": "10 reps"},
            {"name": "Hip circles", "duration": "30s", "note": "8 each direction"},
            {"name": "Band pull-aparts", "duration": "30s", "note": "15 reps"},
            {"name": "Inchworms", "duration": "60s", "note": "5 reps, slow walk out"},
            {"name": "Empty bar complex", "duration": "60s", "note": "5 deadlifts + 5 rows + 5 hang cleans"},
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
    },
    2: {
        "label": "Phase 2 - Wks 5-8",
        "focus": "Strength + body recomposition",
        "lifting": "5x5 main lifts, 3x12 accessories",
        "deficit": "400-500 kcal below TDEE",
        "protein": "1g/lb bodyweight",
    },
    3: {
        "label": "Phase 3 - Wks 9-12",
        "focus": "Peak leanness + power retention",
        "lifting": "3-4x3-5 heavy, 3x15 pump",
        "deficit": "300-400 kcal (tighten up)",
        "protein": "1g/lb bodyweight",
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
    "Inverted Row": "Ring Row",
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


def resolve_name(name):
    """Resolve any exercise name variant to the canonical name."""
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
}


# ─── PHASE TEMPLATES ───────────────────────────────────────────────────────
# Restructured from _phase1_week, _phase2_week, _phase3_week, _deload_week,
# _test_week. Each phase maps day_idx (0=Mon) to a list of exercise dicts.
# Uses CANONICAL names. sets is an int, reps is a string.

PHASE_TEMPLATES = {
    # ── Phase 1: Hypertrophy (weeks 1-3) ──────────────────────────────────
    1: {
        0: [  # Monday — Upper A - Chest & Back
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Control the eccentric, 2 sec down"},
            {"exercise": "Cable Seated Row", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Elbows tight, squeeze at end"},
            {"exercise": "Incline DB Press", "sets": 4, "reps": "10", "rest": "60-90s", "note": "45 deg incline, full ROM"},
            {"exercise": "Lat Pulldown", "sets": 4, "reps": "8", "rest": "60-90s", "note": "Full stretch at top, pull to upper chest"},
            {"exercise": "Face Pull", "sets": 3, "reps": "15", "rest": "45-60s", "note": "External rotation, pull to forehead"},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Slow and controlled, no swinging"},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Full ROM, squeeze at top"},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Elbows locked, full extension"},
        ],
        1: [  # Tuesday — Lower A - Squat Focus
            {"exercise": "Barbell Back Squat", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Below parallel, controlled descent"},
            {"exercise": "Romanian Deadlift", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Hip hinge, feel the hamstring stretch"},
            {"exercise": "Leg Press", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Feet shoulder-width, full depth"},
            {"exercise": "Walking Lunge", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Each leg, maintain upright torso"},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Controlled, don't let hips rise"},
            {"exercise": "Standing Calf Raise", "sets": 4, "reps": "15", "rest": "45-60s", "note": "Full stretch at bottom, squeeze at top"},
        ],
        2: [  # Wednesday — Push & Pull - Chest, Shoulder, Back
            {"exercise": "Weighted Dips", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Forward lean for chest, upright for tri"},
            {"exercise": "Incline Cable Fly", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Slight bend in elbow, full stretch"},
            {"exercise": "Wide-Grip Lat Pulldown", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Pull to upper chest, lean back slightly"},
            {"exercise": "Single-Arm DB Row", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Each side, row to hip not chest"},
            {"exercise": "DB Overhead Press", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Standing or seated, controlled"},
            {"exercise": "DB Shrug", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Full elevation, 1 sec hold at top"},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Neutral grip, both arms alternate"},
            {"exercise": "Skull Crusher", "sets": 3, "reps": "12", "rest": "45-60s", "note": "EZ bar, elbows in, controlled"},
        ],
        3: [  # Thursday — Lower B - Hinge Focus
            {"exercise": "Conventional Deadlift", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Hip-width stance, bar over mid-foot"},
            {"exercise": "Barbell Hip Thrust", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Full extension, squeeze glutes at top"},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "10", "rest": "60-90s", "note": "Each leg. Rear foot elevated, upright torso."},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Controlled, don't let hips rise"},
            {"exercise": "Standing Calf Raise", "sets": 4, "reps": "15", "rest": "45-60s", "note": "Full stretch at bottom, squeeze at top"},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Brace hard - don't sag"},
        ],
        4: [  # Friday — Upper B - Shoulder & Arms
            {"exercise": "DB Overhead Press", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Standing or seated, controlled"},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Slow and controlled, no swinging"},
            {"exercise": "Face Pull", "sets": 3, "reps": "15", "rest": "45-60s", "note": "External rotation, pull to forehead"},
            {"exercise": "Lat Pulldown", "sets": 4, "reps": "8", "rest": "60-90s", "note": "Full stretch at top, pull to upper chest"},
            {"exercise": "Cable Seated Row", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Elbows tight, squeeze at end"},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Full ROM, squeeze at top"},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Neutral grip, both arms alternate"},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Elbows locked, full extension"},
            {"exercise": "Skull Crusher", "sets": 3, "reps": "12", "rest": "45-60s", "note": "EZ bar, elbows in, controlled"},
        ],
        5: [  # Saturday — Full Body - Compound Circuit
            {"exercise": "KB Swing", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Hip drive - not a squat. Explosive."},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "12", "rest": "60-90s", "note": "KB or DB at chest, upright torso"},
            {"exercise": "Ring Row", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Adjust angle for difficulty - more horizontal = harder"},
            {"exercise": "Push Press", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Leg drive to initiate, lock out overhead"},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Brace hard - don't sag"},
            {"exercise": "Conventional Deadlift", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Hip-width stance, bar over mid-foot"},
        ],
        6: [],  # Sunday — Rest
    },

    # ── Phase 2: Strength (weeks 5-7) ─────────────────────────────────────
    2: {
        0: [  # Monday — Lower Strength - Squat Focus
            {"exercise": "Barbell Back Squat", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "RPE 8-9. Heavy. Below parallel every rep."},
            {"exercise": "Barbell Hip Thrust", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Full extension, squeeze glutes at top"},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "10", "rest": "60-90s", "note": "Each leg. Rear foot elevated, upright torso."},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Controlled, don't let hips rise"},
            {"exercise": "Standing Calf Raise", "sets": 4, "reps": "15", "rest": "45-60s", "note": "Full stretch at bottom, squeeze at top"},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s", "note": "From knees or toes. Don't sag."},
        ],
        1: [  # Tuesday — Upper Strength - Pull Focus
            {"exercise": "Lat Pulldown", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "Heavy. Full stretch, controlled pull to chest."},
            {"exercise": "Barbell Bent-Over Row", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "45 deg torso, pull to belly button"},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Full stretch at top"},
            {"exercise": "Rear Delt Fly", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Bent over or cable, squeeze shoulder blades"},
            {"exercise": "EZ-Bar Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Full ROM, squeeze at top"},
            {"exercise": "Hammer Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Neutral grip, both arms alternate"},
        ],
        2: [  # Wednesday — Full Body - Power + Accessories
            {"exercise": "Power Clean", "sets": 4, "reps": "5", "rest": "2-3 min", "note": "From floor. Explosive pull, high elbows."},
            {"exercise": "Box Jump", "sets": 4, "reps": "5", "rest": "2-3 min", "note": "Max effort. Land soft. Reset each rep."},
            {"exercise": "Conventional Deadlift", "sets": 3, "reps": "5", "rest": "2-3 min", "note": "RPE 9. Top set of the week."},
            {"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "rest": "2-3 min", "note": "RPE 8. Push hard."},
            {"exercise": "Barbell Bent-Over Row", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Controlled, heavy-ish"},
            {"exercise": "Walking Lunge", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Each leg, weighted"},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s", "note": "From knees or toes. Don't sag."},
        ],
        3: [  # Thursday — Lower Strength - Hinge Focus
            {"exercise": "Conventional Deadlift", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "RPE 8-9. Heavy and controlled. No bouncing."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "10", "rest": "60-90s", "note": "Each leg. Rear foot elevated, upright torso."},
            {"exercise": "Leg Press", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Feet shoulder-width, full depth"},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Controlled, don't let hips rise"},
            {"exercise": "Standing Calf Raise", "sets": 4, "reps": "15", "rest": "45-60s", "note": "Full stretch at bottom, squeeze at top"},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Brace hard - don't sag"},
        ],
        4: [  # Friday — Upper Strength - Press Focus
            {"exercise": "Barbell Bench Press", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "RPE 8-9. Spotter or use safeties."},
            {"exercise": "Barbell OHP", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "Standing strict press. No leg drive."},
            {"exercise": "Cable Chest Fly", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Arms wide, squeeze hard at center"},
            {"exercise": "Tricep Dip", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Bodyweight or weighted"},
            {"exercise": "Face Pull", "sets": 3, "reps": "15", "rest": "45-60s", "note": "External rotation, pull to forehead"},
            {"exercise": "Lateral Raise", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Slow and controlled, no swinging"},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Elbows locked, full extension"},
        ],
        5: [  # Saturday — Full Body - Volume + Core
            {"exercise": "Barbell Back Squat", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Below parallel, controlled descent"},
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Control the eccentric, 2 sec down"},
            {"exercise": "Barbell Bent-Over Row", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "45 deg torso, pull to belly button"},
            {"exercise": "Push Press", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Leg drive to initiate, lock out overhead"},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s", "note": "From knees or toes. Don't sag."},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Brace hard - don't sag"},
            {"exercise": "Standing Calf Raise", "sets": 4, "reps": "15", "rest": "45-60s", "note": "Full stretch at bottom, squeeze at top"},
        ],
        6: [],  # Sunday — Rest
    },

    # ── Phase 3: Power (weeks 9-11) ───────────────────────────────────────
    3: {
        0: [  # Monday — Lower Power - Squat + Jumps
            {"exercise": "Box Jump", "sets": 4, "reps": "5", "rest": "2-3 min", "note": "Max height. Land quiet. Full reset."},
            {"exercise": "Barbell Back Squat", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9+. Max controllable speed on way up."},
            {"exercise": "Barbell Hip Thrust", "sets": 3, "reps": "5", "rest": "3-5 min", "note": "Heavy. Power through glutes."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Heavier than P2, explosive up"},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, controlled, feel the burn"},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "20", "rest": "45-60s", "note": "Full stretch, slow."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s", "note": "From knees or toes. Don't sag."},
        ],
        1: [  # Tuesday — Upper Power - Pull + Push
            {"exercise": "Power Clean", "sets": 4, "reps": "3", "rest": "2-3 min", "note": "Heaviest of the plan. Focus on speed off floor."},
            {"exercise": "Lat Pulldown", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "Heavy. Max weight you can do cleanly for 3."},
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9+. Explosive concentric."},
            {"exercise": "Barbell OHP", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9. Strict press, no leg drive."},
            {"exercise": "Cable Seated Row", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, full ROM, pause at end"},
            {"exercise": "DB Curl", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Controlled, squeeze at top"},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Full extension, controlled"},
        ],
        2: [  # Wednesday — Full Body Power - All Patterns
            {"exercise": "Med Ball Slam", "sets": 3, "reps": "10", "rest": "60-90s", "note": "Overhead to floor, explosive. 15-20 lb ball."},
            {"exercise": "Conventional Deadlift", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9+. Lock out hard. Re-set each rep."},
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9+. Explosive concentric."},
            {"exercise": "Lat Pulldown", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "Heavy. Max weight you can do cleanly for 3."},
            {"exercise": "Walking Lunge", "sets": 3, "reps": "12", "rest": "60-90s", "note": "Each leg, weighted"},
            {"exercise": "DB Bench Press", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, squeeze, slow eccentric"},
            {"exercise": "Cable Seated Row", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, full ROM, pause at end"},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Brace hard - don't sag"},
        ],
        3: [  # Thursday — Lower Power - Accessory + Pump
            {"exercise": "Barbell Hip Thrust", "sets": 3, "reps": "5", "rest": "3-5 min", "note": "Heavy. Power through glutes."},
            {"exercise": "Bulgarian Split Squat", "sets": 3, "reps": "8", "rest": "60-90s", "note": "Heavier than P2, explosive up"},
            {"exercise": "Leg Press", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light-moderate, full ROM"},
            {"exercise": "Lying Leg Curl", "sets": 3, "reps": "12", "rest": "45-60s", "note": "Controlled, don't let hips rise"},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, controlled, feel the burn"},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "20", "rest": "45-60s", "note": "Full stretch, slow."},
            {"exercise": "Ab Wheel Rollout", "sets": 3, "reps": "10", "rest": "60s", "note": "From knees or toes. Don't sag."},
        ],
        4: [  # Friday — Upper Power - Peak Press + Pump
            {"exercise": "Med Ball Slam", "sets": 3, "reps": "10", "rest": "60-90s", "note": "Overhead to floor, explosive. 15-20 lb ball."},
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9+. Explosive concentric."},
            {"exercise": "Barbell OHP", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9. Strict press, no leg drive."},
            {"exercise": "Lat Pulldown", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "Heavy. Max weight you can do cleanly for 3."},
            {"exercise": "DB Bench Press", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, squeeze, slow eccentric"},
            {"exercise": "Cable Seated Row", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, full ROM, pause at end"},
            {"exercise": "DB Curl", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Controlled, squeeze at top"},
            {"exercise": "Cable Tricep Pushdown", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Full extension, controlled"},
        ],
        5: [  # Saturday — Full Body - Volume + Aerobic
            {"exercise": "Barbell Back Squat", "sets": 4, "reps": "3", "rest": "3-5 min", "note": "RPE 9+. Max controllable speed on way up."},
            {"exercise": "Barbell Bench Press", "sets": 4, "reps": "10", "rest": "60-90s", "note": "Control the eccentric, 2 sec down"},
            {"exercise": "Barbell Bent-Over Row", "sets": 5, "reps": "5", "rest": "2-3 min", "note": "45 deg torso, pull to belly button"},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, controlled, feel the burn"},
            {"exercise": "DB Bench Press", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, squeeze, slow eccentric"},
            {"exercise": "Cable Seated Row", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, full ROM, pause at end"},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Brace hard - don't sag"},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "20", "rest": "45-60s", "note": "Full stretch, slow."},
        ],
        6: [],  # Sunday — Rest
    },

    # ── Deload (weeks 4, 8) ───────────────────────────────────────────────
    "deload": {
        0: [  # Monday — Deload Upper (60% load)
            {"exercise": "DB Bench Press", "sets": 3, "reps": "8", "rest": "60s", "note": "60% normal weight"},
            {"exercise": "Cable Seated Row", "sets": 3, "reps": "8", "rest": "60s", "note": "Light - focus on squeeze"},
            {"exercise": "DB Overhead Press", "sets": 3, "reps": "8", "rest": "60s", "note": "60% load"},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "6", "rest": "60s", "note": "Bodyweight equivalent, light"},
            {"exercise": "Face Pull", "sets": 2, "reps": "15", "rest": "60s", "note": "Shoulder health - feel it"},
        ],
        1: [  # Tuesday — Deload Lower (60% load)
            {"exercise": "Goblet Squat", "sets": 3, "reps": "8", "rest": "60s", "note": "Light KB or DB"},
            {"exercise": "Romanian Deadlift", "sets": 3, "reps": "8", "rest": "60s", "note": "60% load, feel the hamstrings"},
            {"exercise": "Leg Press", "sets": 3, "reps": "10", "rest": "60s", "note": "Light, full ROM"},
            {"exercise": "Lying Leg Curl", "sets": 2, "reps": "10", "rest": "60s", "note": "Controlled"},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12", "rest": "60s", "note": "Slow and controlled"},
        ],
        2: [  # Wednesday — Deload Full Body (60% load)
            {"exercise": "Conventional Deadlift", "sets": 2, "reps": "5", "rest": "60s", "note": "60% 1RM. Focus on setup."},
            {"exercise": "Barbell Bench Press", "sets": 2, "reps": "8", "rest": "60s", "note": "Light - move well"},
            {"exercise": "Barbell Bent-Over Row", "sets": 2, "reps": "8", "rest": "60s", "note": "Light, controlled"},
            {"exercise": "Plank", "sets": 2, "reps": "30s", "rest": "60s", "note": "Brace and breathe"},
        ],
        3: [],  # Thursday — Rest
        4: [  # Friday — Deload Upper Light
            {"exercise": "Push-Ups", "sets": 2, "reps": "15", "rest": "60s", "note": "Bodyweight. Just move."},
            {"exercise": "Ring Row", "sets": 2, "reps": "12", "rest": "60s", "note": "Bodyweight, controlled"},
            {"exercise": "Lateral Raise", "sets": 2, "reps": "15", "rest": "60s", "note": "Light"},
            {"exercise": "Hammer Curl", "sets": 2, "reps": "12", "rest": "60s", "note": "Light"},
        ],
        5: [],  # Saturday — Rest
        6: [],  # Sunday — Rest
    },

    # ── Test Week (week 12) ───────────────────────────────────────────────
    "test": {
        0: [  # Monday — Strength Test - Lower
            {"exercise": "Barbell Back Squat", "sets": 1, "reps": "1RM", "rest": "3-5 min", "note": "5->3->2->1 ladder. Rest fully between."},
            {"exercise": "Conventional Deadlift", "sets": 1, "reps": "1RM", "rest": "3-5 min", "note": "5->3->2->1 ladder."},
            {"exercise": "Goblet Squat", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, controlled, feel the burn"},
            {"exercise": "Standing Calf Raise", "sets": 3, "reps": "20", "rest": "45-60s", "note": "Full stretch, slow."},
        ],
        1: [  # Tuesday — Strength Test - Upper
            {"exercise": "Barbell Bench Press", "sets": 1, "reps": "1RM", "rest": "3-5 min", "note": "Use safeties. Spotter ideal."},
            {"exercise": "Lat Pulldown", "sets": 1, "reps": "1RM", "rest": "3-5 min", "note": "Find your max single rep weight."},
            {"exercise": "DB Bench Press", "sets": 3, "reps": "15", "rest": "60-90s", "note": "Light, squeeze, slow eccentric"},
            {"exercise": "DB Curl", "sets": 3, "reps": "15", "rest": "45-60s", "note": "Controlled, squeeze at top"},
        ],
        2: [  # Wednesday — Full Body - Moderate Finish
            {"exercise": "Goblet Squat", "sets": 3, "reps": "12", "rest": "60s", "note": "Moderate weight"},
            {"exercise": "DB Bench Press", "sets": 3, "reps": "12", "rest": "60s", "note": "Moderate"},
            {"exercise": "Single-Arm DB Row", "sets": 3, "reps": "12", "rest": "60s", "note": "Controlled"},
            {"exercise": "Plank", "sets": 3, "reps": "45s", "rest": "60s", "note": "Solid brace"},
        ],
        3: [],  # Thursday — Rest
        4: [  # Friday — Full Body - Final Session
            {"exercise": "Barbell Back Squat", "sets": 3, "reps": "5", "rest": "60s", "note": "Moderate - not max"},
            {"exercise": "Barbell Bench Press", "sets": 3, "reps": "5", "rest": "60s", "note": "Moderate"},
            {"exercise": "Lat Pulldown", "sets": 3, "reps": "5", "rest": "60s", "note": "Light to moderate weight"},
            {"exercise": "KB Swing", "sets": 3, "reps": "15", "rest": "60s", "note": "Explosive - feel the power"},
        ],
        5: [],  # Saturday — Rest
        6: [],  # Sunday — Rest
    },
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
    "lunge": {"name": "Walking Lunge", "sets": "3x12", "note": "Each leg, maintain upright torso", "rest": "60-90s", "video": "walking lunge proper form technique"},
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
    "split_sq": {"name": "Bulgarian Split Squat", "sets": "3x10", "note": "Each leg. Rear foot elevated, upright torso.", "rest": "60-90s", "video": "bulgarian split squat proper form tutorial"},
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
    "lunge_p2": {"name": "DB Walking Lunge", "sets": "3x12", "note": "Each leg, weighted", "rest": "60-90s", "video": "dumbbell walking lunge proper form"},
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


def get_workouts(week):
    """Return list of 7 day dicts for the given week number (1-12)."""
    is_deload = week in (4, 8)
    is_test = week == 12

    if is_test:
        days = _test_week()
    elif is_deload:
        days = _deload_week(week)
    else:
        phase = get_phase(week)
        if phase == 1:
            days = _phase1_week(week)
        elif phase == 2:
            days = _phase2_week(week)
        else:
            days = _phase3_week(week)

    # Inject meal plan and warmup data into each day
    for d in days:
        if is_deload:
            meal_type = "deload"
        else:
            meal_type = DAY_MEAL_TYPES.get(d["day"], "moderate")
        d["mealType"] = meal_type
        d["mealPlan"] = get_meal_plan(meal_type)

        warmup_type = DAY_WARMUP_TYPES.get(d["day"])
        if warmup_type and warmup_type in WARMUPS:
            d["warmup"] = WARMUPS[warmup_type]
        else:
            d["warmup"] = None

    return days


def _run(key):
    return dict(RUNS[key])


def _phase1_week(week):
    return [
        {
            "day": "Mon", "liftName": "Upper A - Chest & Back",
            "exercises": [_ex("bench"), _ex("cable_row"), _ex("incline_db"), _ex("pullup"), _ex("face_pull"), _ex("lat_raise"), _ex("curl_bar"), _ex("tri_ext")],
            "run": _run("z2_40"),
            "timing": ["6:00", "Lift - Upper A (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 40 min", ],
            "notes": "Bench with safeties or use DB if solo. Lat pulldown - increase weight if 10 reps is easy.",
        },
        {
            "day": "Tue", "liftName": "Lower A - Squat Focus",
            "exercises": [_ex("squat"), _ex("rdl"), _ex("leg_press"), _ex("lunge"), _ex("leg_curl"), _ex("calf_stand")],
            "run": _run("long60"),
            "timing": ["6:00", "Lift - Lower A (55 min)", "7:00", "5 min transition", "7:05", "Long run 60 min", ],
            "notes": "Long run right after legs will be uncomfortable - that's the adaptation. Keep HR honest.",
        },
        {
            "day": "Wed", "liftName": "Push & Pull - Chest, Shoulder, Back",
            "exercises": [_ex("dips"), _ex("inc_fly"), _ex("pull_down"), _ex("db_row"), _ex("ohp"), _ex("shrug"), _ex("hammer"), _ex("skull")],
            "run": _run("z2_35"),
            "timing": ["6:00", "Lift - Push/Pull (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 35 min", ],
            "notes": "Midweek volume day. Rest 60 sec between sets. Move with purpose.",
        },
        {
            "day": "Thu", "liftName": "Lower B - Hinge Focus",
            "exercises": [_ex("deadlift"), _ex("hip_thrust"), _ex("split_sq"), _ex("leg_curl"), _ex("calf_stand"), _ex("plank")],
            "run": _run("tempo25"),
            "timing": ["6:00", "Lift - Lower B (50 min)", "6:55", "5 min transition", "7:00", "Tempo run 25 min", ],
            "notes": "Deadlift heavy. Tempo run after heavy hinge work is hard - warm into it.",
        },
        {
            "day": "Fri", "liftName": "Upper B - Shoulder & Arms",
            "exercises": [_ex("ohp"), _ex("lat_raise"), _ex("face_pull"), _ex("pullup"), _ex("cable_row"), _ex("curl_bar"), _ex("hammer"), _ex("tri_ext"), _ex("skull")],
            "run": _run("hiit20"),
            "timing": ["6:00", "Lift - Upper B (50 min)", "6:55", "5 min transition", "7:00", "HIIT run 20 min", ],
            "notes": "Hardest metabolic day of the week. HIIT after lifting is serious CNS load. Eat well tonight. Sleep 8 hours.",
        },
        {
            "day": "Sat", "liftName": "Full Body - Compound Circuit",
            "exercises": [_ex("kb_swing"), _ex("goblet"), _ex("inv_row"), _ex("push_press"), _ex("plank"), _ex("deadlift")],
            "run": _run("z2_45"),
            "timing": ["6:00", "Lift - Full Body (50 min)", "6:55", "5 min transition", "7:00", "Zone 2 run 45 min", ],
            "notes": "Saturday full body is compound-focused and slightly lower intensity. Enjoy the Zone 2.",
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"],
            "notes": "Complete rest from lifting. One easy mile to honor the streak. Sub-HR 130.",
            "isRest": True,
        },
    ]


def _phase2_week(week):
    return [
        {
            "day": "Mon", "liftName": "Lower Strength - Squat Focus",
            "exercises": [_ex("squat5"), _ex("hip_thrust"), _ex("split_sq"), _ex("leg_curl"), _ex("calf_stand"), _ex("ab_wheel")],
            "run": _run("tempo30"),
            "timing": ["6:00", "Lift - Lower Strength (60 min)", "7:05", "5 min transition", "7:10", "Tempo run 30 min", ],
            "notes": "5x5 squat is the anchor. Rest 3 min between heavy sets. Don't rush it.",
        },
        {
            "day": "Tue", "liftName": "Upper Strength - Pull Focus",
            "exercises": [_ex("weighted_pu"), _ex("bb_row"), _ex("pull_down2"), _ex("rear_delt"), _ex("curl_bar"), _ex("hammer")],
            "run": _run("long75"),
            "timing": ["6:00", "Lift - Upper Pull (55 min)", "7:00", "5 min transition", "7:05", "Long run 75 min", ],
            "notes": "Long run day - lift is pull-focused. HR under 140 on the run. Eat 100-150 extra kcal today.",
        },
        {
            "day": "Wed", "liftName": "Full Body - Power + Accessories",
            "exercises": [_ex("clean"), _ex("box_jump"), _ex("deadlift_p2"), _ex("bench_p2"), _ex("row_p2"), _ex("lunge_p2"), _ex("ab_wheel")],
            "run": _run("hiit25"),
            "timing": ["6:00", "Lift - Full Body Power (60 min)", "7:05", "5 min transition", "7:10", "HIIT run 25 min", ],
            "notes": "Power clean first when CNS is fresh. HIIT after this is peak metabolic demand.",
        },
        {
            "day": "Thu", "liftName": "Lower Strength - Hinge Focus",
            "exercises": [_ex("deadlift5"), _ex("split_sq"), _ex("leg_press"), _ex("leg_curl"), _ex("calf_stand"), _ex("plank")],
            "run": _run("z2_40"),
            "timing": ["6:00", "Lift - Lower Hinge (60 min)", "7:05", "5 min transition", "7:10", "Zone 2 run 40 min", ],
            "notes": "5x5 deadlift is the centerpiece. Zone 2 after heavy pulls - keep it genuinely easy.",
        },
        {
            "day": "Fri", "liftName": "Upper Strength - Press Focus",
            "exercises": [_ex("bench5"), _ex("ohp5"), _ex("cable_fly2"), _ex("tri_dip"), _ex("face_pull"), _ex("lat_raise"), _ex("tri_ext")],
            "run": _run("tempo30"),
            "timing": ["6:00", "Lift - Upper Press (55 min)", "7:00", "5 min transition", "7:05", "Tempo run 30 min", ],
            "notes": "Double tempo week - Monday and Friday. Accelerates VO2max and fat oxidation.",
        },
        {
            "day": "Sat", "liftName": "Full Body - Volume + Core",
            "exercises": [_ex("squat"), _ex("bench"), _ex("bb_row"), _ex("push_press"), _ex("ab_wheel"), _ex("plank"), _ex("calf_stand")],
            "run": _run("z2_50"),
            "timing": ["6:00", "Lift - Full Body Volume (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 50 min", ],
            "notes": "Highest aerobic volume day. Lift is compound and moderate.",
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"],
            "notes": "Complete rest from lifting. One easy mile. Nothing else.",
            "isRest": True,
        },
    ]


def _phase3_week(week):
    return [
        {
            "day": "Mon", "liftName": "Lower Power - Squat + Jumps",
            "exercises": [_ex("box_jump3"), _ex("squat3"), _ex("hip_thrust3"), _ex("split_sq3"), _ex("pump_sq"), _ex("calf3"), _ex("ab_wheel")],
            "run": _run("hiit30"),
            "timing": ["6:00", "Lift - Lower Power (60 min)", "7:05", "5 min transition", "7:10", "HIIT run 30 min", ],
            "notes": "Box jumps first - always. CNS must be fresh for power work. 4x3 squat is the heaviest of the plan.",
        },
        {
            "day": "Tue", "liftName": "Upper Power - Pull + Push",
            "exercises": [_ex("power_clean3"), _ex("wpu3"), _ex("bench3"), _ex("ohp3"), _ex("pump_row"), _ex("pump_curl"), _ex("pump_tri")],
            "run": _run("long90"),
            "timing": ["6:00", "Lift - Upper Power (60 min)", "7:05", "5 min transition", "7:10", "Long run 90 min", ],
            "notes": "90 min long run. HR under 140. Bring fuel if needed. Add 150 kcal today.",
        },
        {
            "day": "Wed", "liftName": "Full Body Power - All Patterns",
            "exercises": [_ex("med_ball"), _ex("deadlift3"), _ex("bench3"), _ex("wpu3"), _ex("lunge_p2"), _ex("pump_press"), _ex("pump_row"), _ex("plank")],
            "run": _run("tempo35"),
            "timing": ["6:00", "Lift - Full Body Power (60 min)", "7:05", "5 min transition", "7:10", "Tempo run 35 min", ],
            "notes": "Med ball slams first to prime explosiveness. Longest tempo of the plan after this.",
        },
        {
            "day": "Thu", "liftName": "Lower Power - Accessory + Pump",
            "exercises": [_ex("hip_thrust3"), _ex("split_sq3"), _ex("leg_press3"), _ex("leg_curl"), _ex("pump_sq"), _ex("calf3"), _ex("ab_wheel")],
            "run": _run("z2_45"),
            "timing": ["6:00", "Lift - Lower Accessories (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 45 min", ],
            "notes": "Lower intensity day - intentional after Mon/Tue/Wed. Zone 2 is your friend.",
        },
        {
            "day": "Fri", "liftName": "Upper Power - Peak Press + Pump",
            "exercises": [_ex("med_ball"), _ex("bench3"), _ex("ohp3"), _ex("wpu3"), _ex("pump_press"), _ex("pump_row"), _ex("pump_curl"), _ex("pump_tri")],
            "run": _run("hiit30"),
            "timing": ["6:00", "Lift - Upper Power + Pump (60 min)", "7:05", "5 min transition", "7:10", "HIIT run 30 min", ],
            "notes": "Second HIIT of the week. You're in peak shape now. Hardest weeks are 10-11.",
        },
        {
            "day": "Sat", "liftName": "Full Body - Volume + Aerobic",
            "exercises": [_ex("squat3"), _ex("bench"), _ex("bb_row"), _ex("pump_sq"), _ex("pump_press"), _ex("pump_row"), _ex("plank"), _ex("calf3")],
            "run": _run("z2_55"),
            "timing": ["6:00", "Lift - Full Body (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 55 min", ],
            "notes": "Highest aerobic day. 55 min Zone 2 is the peak.",
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"],
            "notes": "Rest. One mile. That's it.",
            "isRest": True,
        },
    ]


def _deload_week(week):
    return [
        {
            "day": "Mon", "liftName": "Deload - Upper (60% load)",
            "exercises": [
                {"name": "DB Bench Press", "sets": "3x8", "note": "60% normal weight", "rest": "60s"},
                {"name": "Cable Row", "sets": "3x8", "note": "Light - focus on squeeze", "rest": "60s"},
                {"name": "DB OHP", "sets": "3x8", "note": "60% load", "rest": "60s"},
                {"name": "Lat Pulldown", "sets": "3x6", "note": "Bodyweight equivalent, light", "rest": "60s"},
                {"name": "Face Pull", "sets": "2x15", "note": "Shoulder health - feel it", "rest": "60s"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Upper (40 min)", "6:45", "Easy run 20 min", "7:05", "Done"],
            "notes": "Deload week. Everything at 60% of your working weight. This is where you consolidate adaptation.",
        },
        {
            "day": "Tue", "liftName": "Deload - Lower (60% load)",
            "exercises": [
                {"name": "Goblet Squat", "sets": "3x8", "note": "Light KB or DB", "rest": "60s"},
                {"name": "RDL", "sets": "3x8", "note": "60% load, feel the hamstrings", "rest": "60s"},
                {"name": "Leg Press", "sets": "3x10", "note": "Light, full ROM", "rest": "60s"},
                {"name": "Lying Leg Curl", "sets": "2x10", "note": "Controlled", "rest": "60s"},
                {"name": "Calf Raise", "sets": "3x12", "note": "Slow and controlled", "rest": "60s"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Lower (40 min)", "6:45", "Easy run 20 min", "7:05", "Done"],
            "notes": "Easy day. Flush the legs. Do not be tempted to go heavy.",
        },
        {
            "day": "Wed", "liftName": "Deload - Full Body (60% load)",
            "exercises": [
                {"name": "Deadlift", "sets": "2x5", "note": "60% 1RM. Focus on setup.", "rest": "60s"},
                {"name": "Bench Press", "sets": "2x8", "note": "Light - move well", "rest": "60s"},
                {"name": "Bent-Over Row", "sets": "2x8", "note": "Light, controlled", "rest": "60s"},
                {"name": "Plank", "sets": "2x30s", "note": "Brace and breathe", "rest": "60s"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Full Body (35 min)", "6:40", "Easy run 20 min", "7:00", "Done"],
            "notes": "Short and easy. The goal this week is active recovery, not training.",
        },
        {
            "day": "Thu", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile - easy", "-", "No lifting"],
            "notes": "Full rest from lifting. One mile to keep the streak alive.",
            "isRest": True,
        },
        {
            "day": "Fri", "liftName": "Deload - Upper Light",
            "exercises": [
                {"name": "Push-Up", "sets": "2x15", "note": "Bodyweight. Just move.", "rest": "60s"},
                {"name": "Inverted Row", "sets": "2x12", "note": "Bodyweight, controlled", "rest": "60s"},
                {"name": "DB Lateral Raise", "sets": "2x15", "note": "Light", "rest": "60s"},
                {"name": "Hammer Curl", "sets": "2x12", "note": "Light", "rest": "60s"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Upper light (30 min)", "6:35", "Easy run 20 min", "6:55", "Done"],
            "notes": "Very light. Barely a workout. Perfect for a deload day.",
        },
        {
            "day": "Sat", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile - easy", "-", "No lifting"],
            "notes": "Rest. Streak mile only. Eat at maintenance today.",
            "isRest": True,
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile - easy", "-", "No lifting"],
            "notes": "Rest. Come back Monday ready to work.",
            "isRest": True,
        },
    ]


def _test_week():
    return [
        {
            "day": "Mon", "liftName": "Strength Test - Lower",
            "exercises": [_ex("test_sq"), _ex("test_dl"), _ex("pump_sq"), _ex("calf3")],
            "run": _run("z2_20"),
            "timing": ["6:00", "Squat 1RM ladder (30 min)", "6:35", "Deadlift 1RM ladder (25 min)", "7:05", "Pump accessories (15 min)", "7:20", "Easy run 20 min", "7:40", "Done"],
            "notes": "Test week. Warm up thoroughly: 5x5, 3x3, 2x2, 1x1 approach to max. Rest 3-5 min between heavy singles.",
        },
        {
            "day": "Tue", "liftName": "Strength Test - Upper",
            "exercises": [_ex("test_bench"), _ex("test_pu"), _ex("pump_press"), _ex("pump_curl")],
            "run": _run("z2_20"),
            "timing": ["6:00", "Bench 1RM ladder (30 min)", "6:35", "Lat pulldown max weight (20 min)", "7:00", "Pump work (15 min)", "7:15", "Easy run 20 min", "7:35", "Done"],
            "notes": "Compare your bench and lat pulldown max to week 1. This is your 12-week progress marker.",
        },
        {
            "day": "Wed", "liftName": "Full Body - Moderate Finish",
            "exercises": [
                {"name": "Goblet Squat", "sets": "3x12", "note": "Moderate weight", "rest": "60s"},
                {"name": "DB Bench", "sets": "3x12", "note": "Moderate", "rest": "60s"},
                {"name": "DB Row", "sets": "3x12", "note": "Controlled", "rest": "60s"},
                {"name": "Plank", "sets": "3x45s", "note": "Solid brace", "rest": "60s"},
            ],
            "run": _run("z2_30"),
            "timing": ["6:00", "Full body moderate (45 min)", "6:50", "Zone 2 run 30 min", "7:20", "Done"],
            "notes": "Last real training session. No PRs today - just move well and feel good.",
        },
        {
            "day": "Thu", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile", "-", "Rest"],
            "notes": "Rest.",
            "isRest": True,
        },
        {
            "day": "Fri", "liftName": "Full Body - Final Session",
            "exercises": [
                {"name": "Squat", "sets": "3x5", "note": "Moderate - not max", "rest": "60s"},
                {"name": "Bench", "sets": "3x5", "note": "Moderate", "rest": "60s"},
                {"name": "Lat Pulldown", "sets": "3x5", "note": "Light to moderate weight", "rest": "60s"},
                {"name": "KB Swing", "sets": "3x15", "note": "Explosive - feel the power", "rest": "60s"},
            ],
            "run": _run("z2_30"),
            "timing": ["6:00", "Final session (40 min)", "6:45", "Zone 2 run 30 min", "7:15", "Done"],
            "notes": "Final workout of the 12 weeks. Finish clean. Note how this feels vs Week 1.",
        },
        {
            "day": "Sat", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile", "-", "Rest"],
            "notes": "Rest.",
            "isRest": True,
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile", "-", "Done - 12 weeks complete."],
            "notes": "You did it.",
            "isRest": True,
        },
    ]
