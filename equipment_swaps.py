"""Equipment catalog and exercise swap map for the 12Weeks program."""

EQUIPMENT_CATALOG = {
    "free_weights": {
        "label": "Free Weights",
        "items": [
            {"id": "barbell", "name": "Barbell + Squat Rack"},
            {"id": "dumbbells", "name": "Dumbbells"},
            {"id": "ez_bar", "name": "EZ-Bar"},
            {"id": "kettlebells", "name": "Kettlebells"},
            {"id": "weight_plates", "name": "Weight Plates"},
        ],
    },
    "machines": {
        "label": "Machines",
        "items": [
            {"id": "lat_pulldown", "name": "Lat Pulldown Machine"},
            {"id": "cable_machine", "name": "Cable Machine (adjustable)"},
            {"id": "leg_press", "name": "Leg Press"},
            {"id": "leg_curl_ext", "name": "Leg Curl / Leg Extension"},
            {"id": "chest_press_machine", "name": "Chest Press Machine"},
            {"id": "seated_row_machine", "name": "Seated Row Machine"},
            {"id": "smith_machine", "name": "Smith Machine"},
        ],
    },
    "bars_racks": {
        "label": "Bars & Racks",
        "items": [
            {"id": "pull_up_bar", "name": "Pull-up Bar"},
            {"id": "dip_station", "name": "Dip Station"},
            {"id": "flat_bench", "name": "Flat Bench"},
            {"id": "incline_bench", "name": "Incline Bench"},
            {"id": "decline_bench", "name": "Decline Bench"},
        ],
    },
    "bodyweight_other": {
        "label": "Bodyweight & Other",
        "items": [
            {"id": "resistance_bands", "name": "Resistance Bands"},
            {"id": "trx", "name": "TRX / Suspension Trainer"},
            {"id": "medicine_ball", "name": "Medicine Ball"},
            {"id": "foam_roller", "name": "Foam Roller"},
            {"id": "ab_wheel", "name": "Ab Wheel"},
        ],
    },
}

# Every exercise in the program mapped to equipment requirement + alternatives
EXERCISE_SWAPS = {
    # ─── CHEST ─────────────────────────────────────────────
    "Barbell Bench Press": {
        "muscle_group": "chest",
        "requires": ["barbell", "flat_bench"],
        "alternatives": [
            {"name": "Dumbbell Bench Press", "requires": ["dumbbells", "flat_bench"], "note": "More ROM, stabilizer work"},
            {"name": "Push-Ups", "requires": [], "note": "Bodyweight, add weight plate on back for load"},
            {"name": "Chest Press Machine", "requires": ["chest_press_machine"], "note": "Guided path, safer solo"},
            {"name": "Floor Press (Dumbbells)", "requires": ["dumbbells"], "note": "No bench needed, limited ROM"},
        ],
    },
    "Incline DB Press": {
        "muscle_group": "chest",
        "requires": ["dumbbells", "incline_bench"],
        "alternatives": [
            {"name": "Incline Barbell Press", "requires": ["barbell", "incline_bench"], "note": "Heavier loading"},
            {"name": "Incline Push-Ups (feet elevated)", "requires": [], "note": "Bodyweight, elevate feet on bench"},
            {"name": "Landmine Press", "requires": ["barbell"], "note": "Angled press, shoulder-friendly"},
        ],
    },

    # ─── BACK ──────────────────────────────────────────────
    "Cable Seated Row": {
        "muscle_group": "back",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Barbell Bent-Over Row", "requires": ["barbell"], "note": "Heavier, more lower back demand"},
            {"name": "Dumbbell Row (single arm)", "requires": ["dumbbells", "flat_bench"], "note": "Unilateral, great for imbalances"},
            {"name": "Band Seated Row", "requires": ["resistance_bands"], "note": "Lighter, higher reps, loop around feet"},
            {"name": "Inverted Row", "requires": ["pull_up_bar"], "note": "Bodyweight, adjust angle for difficulty"},
            {"name": "Seated Row Machine", "requires": ["seated_row_machine"], "note": "Guided path, easy setup"},
        ],
    },
    "Lat Pulldown": {
        "muscle_group": "back",
        "requires": ["lat_pulldown"],
        "alternatives": [
            {"name": "Pull-Ups", "requires": ["pull_up_bar"], "note": "Harder, use band for assistance if needed"},
            {"name": "Band Lat Pulldown", "requires": ["resistance_bands", "pull_up_bar"], "note": "Loop band over bar, pull down"},
            {"name": "Dumbbell Pullover", "requires": ["dumbbells", "flat_bench"], "note": "Different angle, same lats"},
            {"name": "Barbell Bent-Over Row (underhand)", "requires": ["barbell"], "note": "Targets lats with supinated grip"},
        ],
    },
    "Barbell Bent-Over Row": {
        "muscle_group": "back",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Dumbbell Row (single arm)", "requires": ["dumbbells", "flat_bench"], "note": "Unilateral, easier on lower back"},
            {"name": "Cable Seated Row", "requires": ["cable_machine"], "note": "Seated, no lower back load"},
            {"name": "Band Row", "requires": ["resistance_bands"], "note": "Standing or seated, loop around anchor"},
            {"name": "Inverted Row", "requires": ["pull_up_bar"], "note": "Bodyweight horizontal pull"},
        ],
    },

    # ─── SHOULDERS ─────────────────────────────────────────
    "DB Overhead Press": {
        "muscle_group": "shoulders",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Barbell OHP", "requires": ["barbell"], "note": "Standing, heavier loading"},
            {"name": "Pike Push-Ups", "requires": [], "note": "Bodyweight, hips high"},
            {"name": "Band Overhead Press", "requires": ["resistance_bands"], "note": "Stand on band, press up"},
            {"name": "Landmine Press", "requires": ["barbell"], "note": "Angled press, shoulder-friendly"},
        ],
    },
    "Barbell OHP": {
        "muscle_group": "shoulders",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "DB Overhead Press", "requires": ["dumbbells"], "note": "More ROM, easier on shoulders"},
            {"name": "Pike Push-Ups", "requires": [], "note": "Bodyweight overhead pressing"},
            {"name": "Arnold Press", "requires": ["dumbbells"], "note": "Rotation adds front delt work"},
        ],
    },
    "Lateral Raise": {
        "muscle_group": "shoulders",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Cable Lateral Raise", "requires": ["cable_machine"], "note": "Constant tension"},
            {"name": "Band Lateral Raise", "requires": ["resistance_bands"], "note": "Step on band, raise out"},
            {"name": "Plate Raise", "requires": ["weight_plates"], "note": "Hold plate, raise to shoulder height"},
        ],
    },
    "Face Pull": {
        "muscle_group": "rear_delts",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Band Face Pull", "requires": ["resistance_bands"], "note": "Anchor at face height"},
            {"name": "Rear Delt Fly (Dumbbells)", "requires": ["dumbbells"], "note": "Bent over, palms facing"},
            {"name": "Prone Y-Raise", "requires": ["flat_bench"], "note": "Lie face down on incline bench"},
        ],
    },

    # ─── LEGS ──────────────────────────────────────────────
    "Barbell Back Squat": {
        "muscle_group": "quads",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Hold dumbbell at chest, great depth"},
            {"name": "Leg Press", "requires": ["leg_press"], "note": "No spinal load, push heavy"},
            {"name": "Bulgarian Split Squat", "requires": ["dumbbells"], "note": "Unilateral, crushes quads"},
            {"name": "Bodyweight Squats", "requires": [], "note": "High reps, add jump for intensity"},
            {"name": "Smith Machine Squat", "requires": ["smith_machine"], "note": "Guided path, safer solo"},
        ],
    },
    "Conventional Deadlift": {
        "muscle_group": "posterior_chain",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Dumbbell Romanian Deadlift", "requires": ["dumbbells"], "note": "Hip hinge, hamstring focus"},
            {"name": "Kettlebell Deadlift", "requires": ["kettlebells"], "note": "Lighter, good form practice"},
            {"name": "Single Leg Deadlift (DB)", "requires": ["dumbbells"], "note": "Balance + posterior chain"},
            {"name": "Hip Thrust", "requires": ["barbell", "flat_bench"], "note": "Glute dominant hip extension"},
        ],
    },
    "Barbell Hip Thrust": {
        "muscle_group": "glutes",
        "requires": ["barbell", "flat_bench"],
        "alternatives": [
            {"name": "Glute Bridge (weighted)", "requires": ["dumbbells"], "note": "DB on hips, floor based"},
            {"name": "Single Leg Glute Bridge", "requires": [], "note": "Bodyweight, unilateral"},
            {"name": "Kettlebell Swing", "requires": ["kettlebells"], "note": "Explosive hip extension"},
            {"name": "Leg Press (high foot placement)", "requires": ["leg_press"], "note": "High feet = more glute"},
        ],
    },

    # ─── ARMS ──────────────────────────────────────────────
    "EZ-Bar Curl": {
        "muscle_group": "biceps",
        "requires": ["ez_bar"],
        "alternatives": [
            {"name": "Dumbbell Curl", "requires": ["dumbbells"], "note": "Standard, alternating or together"},
            {"name": "Barbell Curl", "requires": ["barbell"], "note": "Heavier loading, straight bar"},
            {"name": "Band Curl", "requires": ["resistance_bands"], "note": "Step on band, curl up"},
            {"name": "Hammer Curl", "requires": ["dumbbells"], "note": "Neutral grip, brachialis focus"},
        ],
    },
    "Cable Tricep Pushdown": {
        "muscle_group": "triceps",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Overhead Dumbbell Tricep Extension", "requires": ["dumbbells"], "note": "Long head stretch"},
            {"name": "Dips", "requires": ["dip_station"], "note": "Heavy bodyweight, lean forward for chest too"},
            {"name": "Diamond Push-Ups", "requires": [], "note": "Bodyweight, hands together"},
            {"name": "Band Tricep Pushdown", "requires": ["resistance_bands"], "note": "Anchor high, push down"},
            {"name": "Skull Crushers (EZ-Bar)", "requires": ["ez_bar", "flat_bench"], "note": "Lying tricep extension"},
        ],
    },

    # ─── MISC ──────────────────────────────────────────────
    "Cable Fly": {
        "muscle_group": "chest",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Dumbbell Fly", "requires": ["dumbbells", "flat_bench"], "note": "Free weight, stretch at bottom"},
            {"name": "Band Fly", "requires": ["resistance_bands"], "note": "Anchor behind, press and squeeze"},
            {"name": "Pec Deck Machine", "requires": ["chest_press_machine"], "note": "If gym has one"},
        ],
    },
    "Leg Extension": {
        "muscle_group": "quads",
        "requires": ["leg_curl_ext"],
        "alternatives": [
            {"name": "Sissy Squat", "requires": [], "note": "Bodyweight quad isolation"},
            {"name": "Front Foot Elevated Split Squat", "requires": ["dumbbells"], "note": "DB in hands, front foot on plate"},
            {"name": "Wall Sit", "requires": [], "note": "Isometric, burn city"},
        ],
    },
    "Leg Curl": {
        "muscle_group": "hamstrings",
        "requires": ["leg_curl_ext"],
        "alternatives": [
            {"name": "Nordic Hamstring Curl", "requires": [], "note": "Bodyweight, brutal, use pad under knees"},
            {"name": "Dumbbell Leg Curl", "requires": ["dumbbells", "flat_bench"], "note": "Lie prone, DB between feet"},
            {"name": "Swiss Ball Hamstring Curl", "requires": [], "note": "Need a stability ball"},
            {"name": "Romanian Deadlift", "requires": ["barbell"], "note": "Compound hamstring + glute"},
        ],
    },
}


def get_alternatives(exercise_name, user_equipment):
    """Get swap options for an exercise based on available equipment.

    Args:
        exercise_name: Name of the exercise to swap
        user_equipment: list of equipment IDs the user has

    Returns:
        list of alternative dicts, or empty list if no swaps needed/available
    """
    swap = EXERCISE_SWAPS.get(exercise_name)
    if not swap:
        return []

    equipment_set = set(user_equipment or [])
    alternatives = []

    for alt in swap["alternatives"]:
        required = set(alt["requires"])
        # Bodyweight exercises (empty requires) are always available
        if not required or required.issubset(equipment_set):
            alternatives.append({
                "name": alt["name"],
                "note": alt["note"],
                "muscle_group": swap["muscle_group"],
            })

    return alternatives


def check_exercise_available(exercise_name, user_equipment):
    """Check if a user has the equipment for a given exercise.

    Returns True if equipment is available or exercise is not in the swap map.
    """
    swap = EXERCISE_SWAPS.get(exercise_name)
    if not swap:
        return True  # Unknown exercise, assume available
    required = set(swap["requires"])
    if not required:
        return True  # Bodyweight, always available
    return required.issubset(set(user_equipment or []))


def auto_swap_workout(exercises, user_equipment):
    """Auto-swap exercises the user can't do with the best available alternative.

    Args:
        exercises: list of exercise dicts from workout_data
        user_equipment: list of equipment IDs

    Returns:
        modified exercises list with swaps applied
    """
    result = []
    for ex in exercises:
        if check_exercise_available(ex["name"], user_equipment):
            result.append(ex)
        else:
            alts = get_alternatives(ex["name"], user_equipment)
            if alts:
                swapped = dict(ex)
                swapped["name"] = alts[0]["name"]
                swapped["note"] = alts[0]["note"] + f" (replaces {ex['name']})"
                swapped["_swapped_from"] = ex["name"]
                result.append(swapped)
            else:
                # No alternatives available, keep original
                result.append(ex)
    return result
