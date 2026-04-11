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

    # ─── DIPS ─────────────────────────────────────────────
    "Weighted Dips": {
        "muscle_group": "chest_triceps",
        "requires": ["dip_station"],
        "alternatives": [
            {"name": "Decline Push-Ups", "requires": [], "note": "Bodyweight, feet elevated — mimics dip angle for chest"},
            {"name": "Close-Grip Bench Press", "requires": ["barbell", "flat_bench"], "note": "Chest + triceps compound"},
            {"name": "Machine Dip", "requires": ["chest_press_machine"], "note": "Guided path, chest focus with forward lean"},
            {"name": "Diamond Push-Ups", "requires": [], "note": "Bodyweight, chest + triceps"},
            {"name": "DB Bench Press", "requires": ["dumbbells", "flat_bench"], "note": "Chest compound, similar push pattern"},
            {"name": "Skull Crusher", "requires": ["ez_bar", "flat_bench"], "note": "Tricep isolation — less chest involvement"},
        ],
    },

    # ─── ADDITIONAL EXERCISES ─────────────────────────────
    "Dumbbell Shoulder Press": {
        "muscle_group": "shoulders",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Barbell OHP", "requires": ["barbell"], "note": "Heavier loading"},
            {"name": "Pike Push-Ups", "requires": [], "note": "Bodyweight overhead press"},
            {"name": "Arnold Press", "requires": ["dumbbells"], "note": "Rotation adds front delt work"},
        ],
    },
    "Romanian Deadlift": {
        "muscle_group": "hamstrings",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Dumbbell Romanian Deadlift", "requires": ["dumbbells"], "note": "Lighter, easier to control"},
            {"name": "Nordic Hamstring Curl", "requires": [], "note": "Bodyweight, brutal eccentric — pad knees"},
            {"name": "Single Leg Deadlift (DB)", "requires": ["dumbbells"], "note": "Unilateral balance work"},
            {"name": "Lying Leg Curl", "requires": ["leg_curl_ext"], "note": "Machine isolation"},
        ],
    },
    "Walking Lunge": {
        "muscle_group": "quads",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Bulgarian Split Squat", "requires": ["dumbbells"], "note": "Stationary, rear foot elevated"},
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Hold at chest, full depth"},
            {"name": "Step-Up", "requires": ["dumbbells"], "note": "Use a bench or box"},
        ],
    },
    "Standing Calf Raise": {
        "muscle_group": "calves",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Seated Calf Raise", "requires": ["dumbbells"], "note": "Seated, weight on knees"},
            {"name": "Calf Raises (step)", "requires": [], "note": "Bodyweight on a step, full ROM"},
        ],
    },
    "Leg Press": {
        "muscle_group": "quads",
        "requires": ["leg_press"],
        "alternatives": [
            {"name": "Barbell Back Squat", "requires": ["barbell"], "note": "Free weight compound"},
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Hold dumbbell at chest"},
            {"name": "Bulgarian Split Squat", "requires": ["dumbbells"], "note": "Unilateral, no machine needed"},
        ],
    },
    "Wide-Grip Lat Pulldown": {
        "muscle_group": "back",
        "requires": ["lat_pulldown"],
        "alternatives": [
            {"name": "Pull-Ups", "requires": ["pull_up_bar"], "note": "Wide grip, bodyweight"},
            {"name": "Dumbbell Pullover", "requires": ["dumbbells", "flat_bench"], "note": "Stretch + contraction"},
            {"name": "Barbell Bent-Over Row (underhand)", "requires": ["barbell"], "note": "Supinated grip for lats"},
        ],
    },
    "Single-Arm DB Row": {
        "muscle_group": "back",
        "requires": ["dumbbells", "flat_bench"],
        "alternatives": [
            {"name": "Cable Seated Row", "requires": ["cable_machine"], "note": "Bilateral, constant tension"},
            {"name": "Barbell Bent-Over Row", "requires": ["barbell"], "note": "Heavier bilateral pull"},
            {"name": "Inverted Row", "requires": ["pull_up_bar"], "note": "Bodyweight horizontal pull"},
        ],
    },
    "DB Shrug": {
        "muscle_group": "traps",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Barbell Shrug", "requires": ["barbell"], "note": "Heavier loading"},
            {"name": "Band Shrug", "requires": ["resistance_bands"], "note": "Stand on band, shrug up"},
        ],
    },
    "Hammer Curl": {
        "muscle_group": "biceps",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Dumbbell Curl", "requires": ["dumbbells"], "note": "Supinated grip, standard curl"},
            {"name": "EZ-Bar Curl", "requires": ["ez_bar"], "note": "Heavier loading, angled grip"},
            {"name": "Band Curl", "requires": ["resistance_bands"], "note": "Step on band, curl up"},
        ],
    },
    "Skull Crusher": {
        "muscle_group": "triceps",
        "requires": ["ez_bar", "flat_bench"],
        "alternatives": [
            {"name": "Cable Tricep Pushdown", "requires": ["cable_machine"], "note": "Standing, constant tension"},
            {"name": "Overhead Dumbbell Tricep Extension", "requires": ["dumbbells"], "note": "Long head focus"},
            {"name": "Diamond Push-Ups", "requires": [], "note": "Bodyweight tricep work"},
        ],
    },
    "Overhead Tricep Extension": {
        "muscle_group": "triceps",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Cable Tricep Pushdown", "requires": ["cable_machine"], "note": "Standing, constant tension"},
            {"name": "Skull Crusher", "requires": ["ez_bar", "flat_bench"], "note": "Lying extension"},
            {"name": "Diamond Push-Ups", "requires": [], "note": "Bodyweight, hands together"},
        ],
    },
    "Cable Lateral Raise": {
        "muscle_group": "shoulders",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Lateral Raise", "requires": ["dumbbells"], "note": "Free weight, standard"},
            {"name": "Band Lateral Raise", "requires": ["resistance_bands"], "note": "Step on band"},
        ],
    },
    "KB Swing": {
        "muscle_group": "posterior_chain",
        "requires": ["kettlebells"],
        "alternatives": [
            {"name": "Dumbbell Swing", "requires": ["dumbbells"], "note": "Same movement, hold one DB"},
            {"name": "Romanian Deadlift", "requires": ["barbell"], "note": "Slower hip hinge, same muscles"},
        ],
    },
    "Nordic Hamstring Curl": {
        "muscle_group": "hamstrings",
        "requires": [],
        "alternatives": [
            {"name": "Lying Leg Curl", "requires": ["leg_curl_ext"], "note": "Machine isolation"},
            {"name": "Dumbbell Romanian Deadlift", "requires": ["dumbbells"], "note": "Hip hinge hamstring work"},
        ],
    },
    "Bulgarian Split Squat": {
        "muscle_group": "quads",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Walking Lunge", "requires": ["dumbbells"], "note": "Moving lunge, similar pattern"},
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Bilateral, hold at chest"},
            {"name": "Step-Up", "requires": ["dumbbells"], "note": "Unilateral, use bench or box"},
        ],
    },

    # ─── MISC ──────────────────────────────────────────────
    "Incline Cable Fly": {
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
    "Lying Leg Curl": {
        "muscle_group": "hamstrings",
        "requires": ["leg_curl_ext"],
        "alternatives": [
            {"name": "Nordic Hamstring Curl", "requires": [], "note": "Bodyweight, brutal, use pad under knees"},
            {"name": "Dumbbell Leg Curl", "requires": ["dumbbells", "flat_bench"], "note": "Lie prone, DB between feet"},
            {"name": "Swiss Ball Hamstring Curl", "requires": [], "note": "Need a stability ball"},
            {"name": "Romanian Deadlift", "requires": ["barbell"], "note": "Compound hamstring + glute"},
        ],
    },

    # ─── NEW EXERCISES (11) ──────────────────────────────────
    "Inverted Row": {
        "muscle_group": "back",
        "requires": ["pull_up_bar"],
        "alternatives": [
            {"name": "Ring Row", "requires": ["trx"], "note": "Adjustable angle, same pull pattern"},
            {"name": "Cable Seated Row", "requires": ["cable_machine"], "note": "Seated horizontal pull, constant tension"},
            {"name": "Dumbbell Bent-Over Row", "requires": ["dumbbells"], "note": "Bilateral DB row, free weight"},
            {"name": "Band Pull-Apart", "requires": ["resistance_bands"], "note": "Upper back and rear delt activation"},
        ],
    },
    "Ab Wheel Rollout": {
        "muscle_group": "core",
        "requires": ["ab_wheel"],
        "alternatives": [
            {"name": "Plank", "requires": [], "note": "Isometric core, scale by duration"},
            {"name": "Dead Bug", "requires": [], "note": "Supine anti-extension, lower back safe"},
            {"name": "Cable Crunch", "requires": ["cable_machine"], "note": "Weighted flexion, kneel at cable"},
            {"name": "Hanging Knee Raise", "requires": ["pull_up_bar"], "note": "Hip flexion + core, hang from bar"},
        ],
    },
    "Goblet Squat": {
        "muscle_group": "quads",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "DB Front Squat", "requires": ["dumbbells"], "note": "DBs at shoulders, upright torso"},
            {"name": "KB Front Squat", "requires": ["kettlebells"], "note": "Rack position, same pattern as goblet"},
            {"name": "Bodyweight Squat", "requires": [], "note": "No load, add tempo or reps for difficulty"},
        ],
    },
    "Box Jump": {
        "muscle_group": "power",
        "requires": [],
        "alternatives": [
            {"name": "Squat Jump", "requires": [], "note": "Explosive vertical, no box needed"},
            {"name": "Lunge Jump", "requires": [], "note": "Alternating split jumps, plyometric"},
            {"name": "KB Swing", "requires": ["kettlebells"], "note": "Explosive hip extension, power development"},
        ],
    },
    "Plank": {
        "muscle_group": "core",
        "requires": [],
        "alternatives": [
            {"name": "Dead Bug", "requires": [], "note": "Supine anti-extension, lower back friendly"},
            {"name": "Ab Wheel Rollout", "requires": ["ab_wheel"], "note": "Dynamic anti-extension"},
            {"name": "Side Plank", "requires": [], "note": "Lateral core stability"},
            {"name": "Hollow Hold", "requires": [], "note": "Gymnastic core hold, brutal"},
        ],
    },
    "Power Clean": {
        "muscle_group": "full_body",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Hang Clean", "requires": ["barbell"], "note": "From hang position, less technical"},
            {"name": "KB Clean", "requires": ["kettlebells"], "note": "Single arm clean, good power developer"},
            {"name": "DB Power Clean", "requires": ["dumbbells"], "note": "DB from floor to shoulders, explosive"},
        ],
    },
    "Push Press": {
        "muscle_group": "shoulders",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "DB Push Press", "requires": ["dumbbells"], "note": "Same leg drive pattern, DBs at shoulders"},
            {"name": "Barbell OHP", "requires": ["barbell"], "note": "Strict press, no leg drive, heavier overhead work"},
            {"name": "KB Press", "requires": ["kettlebells"], "note": "Single or double KB overhead press"},
        ],
    },
    "Med Ball Slam": {
        "muscle_group": "power",
        "requires": ["medicine_ball"],
        "alternatives": [
            {"name": "KB Swing", "requires": ["kettlebells"], "note": "Explosive hip hinge, similar power output"},
            {"name": "Battle Rope Slam", "requires": [], "note": "If ropes available, same overhead-to-floor pattern"},
            {"name": "Burpee", "requires": [], "note": "Full body explosive, no equipment needed"},
        ],
    },
    "Push-Ups": {
        "muscle_group": "chest",
        "requires": [],
        "alternatives": [
            {"name": "DB Bench Press", "requires": ["dumbbells", "flat_bench"], "note": "Loaded pressing, more progressive overload"},
            {"name": "Incline Push-Up", "requires": [], "note": "Hands elevated, easier variation"},
            {"name": "Diamond Push-Up", "requires": [], "note": "Close hand position, more tricep focus"},
        ],
    },
    "Rear Delt Fly": {
        "muscle_group": "rear_delts",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Face Pull", "requires": ["cable_machine"], "note": "Cable, external rotation emphasis"},
            {"name": "Band Pull-Apart", "requires": ["resistance_bands"], "note": "Light, high-rep rear delt work"},
            {"name": "Reverse Cable Fly", "requires": ["cable_machine"], "note": "Low cables, same bent-arm fly pattern"},
        ],
    },
    "Tricep Dip": {
        "muscle_group": "triceps",
        "requires": ["dip_station"],
        "alternatives": [
            {"name": "Weighted Dips", "requires": ["dip_station"], "note": "Add load for progression"},
            {"name": "Close-Grip Push-Up", "requires": [], "note": "Bodyweight, hands inside shoulder width"},
            {"name": "Diamond Push-Up", "requires": [], "note": "Hands together, tricep dominant"},
        ],
    },

    # ─── VARIANT ALIASES (19) ────────────────────────────────
    # Short names used in workout_data.py that map to the same
    # muscle groups and alternatives as their full-name entries.
    "Bench Press": {
        "muscle_group": "chest",
        "requires": ["barbell", "flat_bench"],
        "alternatives": [
            {"name": "Dumbbell Bench Press", "requires": ["dumbbells", "flat_bench"], "note": "More ROM, stabilizer work"},
            {"name": "Push-Ups", "requires": [], "note": "Bodyweight, add weight plate on back for load"},
            {"name": "Floor Press (Dumbbells)", "requires": ["dumbbells"], "note": "No bench needed, limited ROM"},
        ],
    },
    "Bench": {
        "muscle_group": "chest",
        "requires": ["barbell", "flat_bench"],
        "alternatives": [
            {"name": "Dumbbell Bench Press", "requires": ["dumbbells", "flat_bench"], "note": "More ROM, stabilizer work"},
            {"name": "Push-Ups", "requires": [], "note": "Bodyweight, add weight plate on back for load"},
            {"name": "Floor Press (Dumbbells)", "requires": ["dumbbells"], "note": "No bench needed, limited ROM"},
        ],
    },
    "DB Bench Press": {
        "muscle_group": "chest",
        "requires": ["dumbbells", "flat_bench"],
        "alternatives": [
            {"name": "Barbell Bench Press", "requires": ["barbell", "flat_bench"], "note": "Heavier loading"},
            {"name": "Push-Ups", "requires": [], "note": "Bodyweight pressing"},
            {"name": "Floor Press (Dumbbells)", "requires": ["dumbbells"], "note": "No bench needed, limited ROM"},
        ],
    },
    "DB Bench": {
        "muscle_group": "chest",
        "requires": ["dumbbells", "flat_bench"],
        "alternatives": [
            {"name": "Barbell Bench Press", "requires": ["barbell", "flat_bench"], "note": "Heavier loading"},
            {"name": "Push-Ups", "requires": [], "note": "Bodyweight pressing"},
            {"name": "Floor Press (Dumbbells)", "requires": ["dumbbells"], "note": "No bench needed, limited ROM"},
        ],
    },
    "Back Squat": {
        "muscle_group": "quads",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Hold dumbbell at chest, great depth"},
            {"name": "Bulgarian Split Squat", "requires": ["dumbbells"], "note": "Unilateral, crushes quads"},
            {"name": "Bodyweight Squats", "requires": [], "note": "High reps, add jump for intensity"},
        ],
    },
    "Squat": {
        "muscle_group": "quads",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Hold dumbbell at chest, great depth"},
            {"name": "Bulgarian Split Squat", "requires": ["dumbbells"], "note": "Unilateral, crushes quads"},
            {"name": "Bodyweight Squats", "requires": [], "note": "High reps, add jump for intensity"},
        ],
    },
    "Deadlift": {
        "muscle_group": "posterior_chain",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Dumbbell Romanian Deadlift", "requires": ["dumbbells"], "note": "Hip hinge, hamstring focus"},
            {"name": "Kettlebell Deadlift", "requires": ["kettlebells"], "note": "Lighter, good form practice"},
            {"name": "Single Leg Deadlift (DB)", "requires": ["dumbbells"], "note": "Balance + posterior chain"},
        ],
    },
    "Bent-Over Row": {
        "muscle_group": "back",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Dumbbell Row (single arm)", "requires": ["dumbbells", "flat_bench"], "note": "Unilateral, easier on lower back"},
            {"name": "Cable Seated Row", "requires": ["cable_machine"], "note": "Seated, no lower back load"},
            {"name": "Inverted Row", "requires": ["pull_up_bar"], "note": "Bodyweight horizontal pull"},
        ],
    },
    "Heavy Lat Pulldown": {
        "muscle_group": "back",
        "requires": ["lat_pulldown"],
        "alternatives": [
            {"name": "Pull-Ups", "requires": ["pull_up_bar"], "note": "Harder, use band for assistance if needed"},
            {"name": "Dumbbell Pullover", "requires": ["dumbbells", "flat_bench"], "note": "Different angle, same lats"},
            {"name": "Barbell Bent-Over Row (underhand)", "requires": ["barbell"], "note": "Targets lats with supinated grip"},
        ],
    },
    "DB Walking Lunge": {
        "muscle_group": "quads",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Bulgarian Split Squat", "requires": ["dumbbells"], "note": "Stationary, rear foot elevated"},
            {"name": "Goblet Squat", "requires": ["dumbbells"], "note": "Hold at chest, full depth"},
            {"name": "Step-Up", "requires": ["dumbbells"], "note": "Use a bench or box"},
        ],
    },
    "DB Row": {
        "muscle_group": "back",
        "requires": ["dumbbells", "flat_bench"],
        "alternatives": [
            {"name": "Cable Seated Row", "requires": ["cable_machine"], "note": "Bilateral, constant tension"},
            {"name": "Barbell Bent-Over Row", "requires": ["barbell"], "note": "Heavier bilateral pull"},
            {"name": "Inverted Row", "requires": ["pull_up_bar"], "note": "Bodyweight horizontal pull"},
        ],
    },
    "Cable Row": {
        "muscle_group": "back",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Barbell Bent-Over Row", "requires": ["barbell"], "note": "Heavier, more lower back demand"},
            {"name": "Dumbbell Row (single arm)", "requires": ["dumbbells", "flat_bench"], "note": "Unilateral, great for imbalances"},
            {"name": "Inverted Row", "requires": ["pull_up_bar"], "note": "Bodyweight, adjust angle for difficulty"},
        ],
    },
    "DB OHP": {
        "muscle_group": "shoulders",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Barbell OHP", "requires": ["barbell"], "note": "Standing, heavier loading"},
            {"name": "Pike Push-Ups", "requires": [], "note": "Bodyweight, hips high"},
            {"name": "Arnold Press", "requires": ["dumbbells"], "note": "Rotation adds front delt work"},
        ],
    },
    "RDL": {
        "muscle_group": "hamstrings",
        "requires": ["barbell"],
        "alternatives": [
            {"name": "Dumbbell Romanian Deadlift", "requires": ["dumbbells"], "note": "Lighter, easier to control"},
            {"name": "Single Leg Deadlift (DB)", "requires": ["dumbbells"], "note": "Unilateral balance work"},
            {"name": "Kettlebell Deadlift", "requires": ["kettlebells"], "note": "Hip hinge pattern, lighter load"},
        ],
    },
    "DB Lateral Raise": {
        "muscle_group": "shoulders",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Cable Lateral Raise", "requires": ["cable_machine"], "note": "Constant tension"},
            {"name": "Band Lateral Raise", "requires": ["resistance_bands"], "note": "Step on band, raise out"},
            {"name": "Plate Raise", "requires": ["weight_plates"], "note": "Hold plate, raise to shoulder height"},
        ],
    },
    "Cable Chest Fly": {
        "muscle_group": "chest",
        "requires": ["cable_machine"],
        "alternatives": [
            {"name": "Dumbbell Fly", "requires": ["dumbbells", "flat_bench"], "note": "Free weight, stretch at bottom"},
            {"name": "Band Fly", "requires": ["resistance_bands"], "note": "Anchor behind, press and squeeze"},
            {"name": "Incline DB Press", "requires": ["dumbbells", "incline_bench"], "note": "Press alternative for upper chest"},
        ],
    },
    "Push-Up": {
        "muscle_group": "chest",
        "requires": [],
        "alternatives": [
            {"name": "DB Bench Press", "requires": ["dumbbells", "flat_bench"], "note": "Loaded pressing, more progressive overload"},
            {"name": "Incline Push-Up", "requires": [], "note": "Hands elevated, easier variation"},
            {"name": "Diamond Push-Up", "requires": [], "note": "Close hand position, more tricep focus"},
        ],
    },
    "Calf Raise": {
        "muscle_group": "calves",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "Seated Calf Raise", "requires": ["dumbbells"], "note": "Seated, weight on knees"},
            {"name": "Calf Raises (step)", "requires": [], "note": "Bodyweight on a step, full ROM"},
        ],
    },
    "DB Curl": {
        "muscle_group": "biceps",
        "requires": ["dumbbells"],
        "alternatives": [
            {"name": "EZ-Bar Curl", "requires": ["ez_bar"], "note": "Angled grip, heavier loading"},
            {"name": "Barbell Curl", "requires": ["barbell"], "note": "Straight bar, bilateral"},
            {"name": "Band Curl", "requires": ["resistance_bands"], "note": "Step on band, curl up"},
            {"name": "Hammer Curl", "requires": ["dumbbells"], "note": "Neutral grip, brachialis focus"},
        ],
    },
}


def get_alternatives(exercise_name, user_equipment=None):
    """Get swap options for an exercise based on available equipment.

    Args:
        exercise_name: Name of the exercise to swap
        user_equipment: list of equipment IDs the user has

    Returns:
        list of alternative dicts, or empty list if no swaps needed/available
    """
    import re
    from workout_data import resolve_name
    exercise_name = resolve_name(exercise_name)

    swap = EXERCISE_SWAPS.get(exercise_name)

    # Strip pump/test suffixes — e.g. "Goblet Squat (pump)" -> "Goblet Squat"
    if not swap:
        clean = re.sub(r'\s*\(pump\)\s*$', '', exercise_name).strip()
        swap = EXERCISE_SWAPS.get(clean)
    else:
        clean = exercise_name

    if not swap:
        # Fuzzy match — strip common prefixes/suffixes like "1RM test", "max weight"
        # Operates on the pump-stripped name so "(pump)" doesn't interfere
        clean = re.sub(r'\s*[-–]\s*(1RM test|max weight|pump)$', '', clean).strip()
        clean = re.sub(r'^(Barbell|DB|Dumbbell|Heavy|Cable)\s+', '', clean).strip()
        for key in EXERCISE_SWAPS:
            if clean.lower() in key.lower() or key.lower() in clean.lower():
                swap = EXERCISE_SWAPS[key]
                break

    if not swap:
        return []

    equipment_set = set(user_equipment or [])
    alternatives = []

    for alt in swap["alternatives"]:
        required = set(alt["requires"])
        available = not required or required.issubset(equipment_set)
        missing = list(required - equipment_set) if required and not available else []
        alternatives.append({
            "name": alt["name"],
            "note": alt["note"],
            "muscle_group": swap["muscle_group"],
            "available": available,
            "missing_equipment": missing,
        })

    return alternatives


def check_exercise_available(exercise_name, user_equipment):
    """Check if a user has the equipment for a given exercise.

    Returns True if equipment is available or exercise is not in the swap map.
    """
    import re
    from workout_data import resolve_name
    exercise_name = resolve_name(exercise_name)

    swap = EXERCISE_SWAPS.get(exercise_name)

    if not swap:
        clean = re.sub(r'\s*\(pump\)\s*$', '', exercise_name).strip()
        swap = EXERCISE_SWAPS.get(clean)
    else:
        clean = exercise_name

    if not swap:
        clean = re.sub(r'\s*[-–]\s*(1RM test|max weight|pump)$', '', clean).strip()
        clean = re.sub(r'^(Barbell|DB|Dumbbell|Heavy|Cable)\s+', '', clean).strip()
        for key in EXERCISE_SWAPS:
            if clean.lower() in key.lower() or key.lower() in clean.lower():
                swap = EXERCISE_SWAPS[key]
                break

    if not swap:
        return True  # Unknown exercise, assume available
    required = set(swap["requires"])
    if not required:
        return True  # Bodyweight, always available
    return required.issubset(set(user_equipment or []))


def auto_swap_workout(exercises, user_equipment):
    """Auto-swap exercises the user can't do with the best available alternative.
    Also prevents duplicate exercises in the same day.
    """
    result = []
    used_names = set()

    for ex in exercises:
        if check_exercise_available(ex["name"], user_equipment):
            if ex["name"] not in used_names:
                result.append(ex)
                used_names.add(ex["name"])
            # else: skip duplicate
        else:
            alts = get_alternatives(ex["name"], user_equipment)
            # Find first available alternative not already in today's workout
            picked = None
            for alt in alts:
                if alt["available"] and alt["name"] not in used_names:
                    picked = alt
                    break
            # Fallback: pick first available even if duplicate risk
            if not picked:
                for alt in alts:
                    if alt["available"]:
                        picked = alt
                        break
            if picked:
                swapped = dict(ex)
                swapped["name"] = picked["name"]
                swapped["note"] = picked["note"] + f" (replaces {ex['name']})"
                swapped["_swapped_from"] = ex["name"]
                result.append(swapped)
                used_names.add(picked["name"])
            else:
                # No alternatives available, keep original
                result.append(ex)
                used_names.add(ex["name"])
    return result


def validate_exercise_swaps():
    """Startup validation: warn about exercises with no alternatives.
    Returns list of exercise names with 0 alternatives."""
    import logging
    missing = []
    for name, data in EXERCISE_SWAPS.items():
        if not data.get("alternatives") or len(data["alternatives"]) < 2:
            missing.append(name)
            logging.warning(f"Exercise '{name}' has fewer than 2 alternatives")
    return missing
