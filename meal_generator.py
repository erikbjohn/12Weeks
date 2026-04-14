"""
Personalized meal plan generator.

Generates meal plans from user food selections + calorie/macro targets.
Output matches the EXACT structure of MEAL_PLANS in workout_data.py.
"""

from food_catalog import FOOD_CATALOG, get_food


# ── Constants ─────────────────────────────────────────────────────────────────

# Pre-workout items (zero-calorie fasting window)
_BLACK_COFFEE = {"item": "Black coffee", "portion": "12 oz", "cal": 5, "protein": 0, "carbs": 0, "fat": 0}
_WATER = {"item": "Water", "portion": "16 oz", "cal": 0, "protein": 0, "carbs": 0, "fat": 0}

# Fasting protocol definitions
_FASTING_PROTOCOLS = {
    "16_8":  {"start": "11:00am", "end": "6:30pm", "meals": 3, "fasted_preworkout": True},
    "18_6":  {"start": "12:00pm", "end": "6:00pm", "meals": 2, "fasted_preworkout": True},
    "20_4":  {"start": "2:00pm",  "end": "6:00pm", "meals": 2, "fasted_preworkout": True},
    "omad":  {"start": "5:00pm",  "end": "6:00pm", "meals": 1, "fasted_preworkout": True},
    "none":  {"start": "6:00am",  "end": "9:00pm", "meals": 4, "fasted_preworkout": False},
}

# Meal calorie distribution by number of eating meals (excluding pre-workout).
# Each list sums to 1.0. Index 0 = first eating meal.
_MEAL_SPLITS = {
    1: [1.0],
    2: [0.55, 0.45],
    3: [0.38, 0.27, 0.35],
    4: [0.30, 0.25, 0.25, 0.20],
    5: [0.25, 0.20, 0.20, 0.20, 0.15],
}

# Day-type carb multipliers — fat adjusts inversely to keep total calories flat.
# This implements carb cycling: more carbs on performance days, less on rest days.
_DAY_MODIFIERS = {
    "heavy_lift": {"carbs": 1.5, "calories": 1.0},
    "long_run":   {"carbs": 2.0, "calories": 1.0},
    "moderate":   {"carbs": 1.0, "calories": 1.0},
    "rest":       {"carbs": 0.7, "calories": 1.0},
    "deload":     {"carbs": 1.2, "calories": 1.0},
}

# Day-type labels and notes
_DAY_LABELS = {
    "heavy_lift": ("Heavy Lift Day", "Extra carbs shifted from fat for training fuel. Same total calories."),
    "long_run":   ("Long Run Day", "Higher carbs for endurance fuel. Fat reduced to keep calories flat."),
    "moderate":   ("Training Day", "Standard macro split."),
    "rest":       ("Rest Day", "Lower carbs, higher fat. Recovery focus."),
    "deload":     ("Deload Day", "Slightly more carbs for recovery."),
}

# Meal name templates by position
_MEAL_NAMES = {
    0: "Break Fast",
    1: "Midday Meal",
    2: "Dinner",
    3: "Snack",
    4: "Late Snack",
}

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _round_portion(value, unit):
    """Round a portion size to a practical human-friendly amount."""
    if unit in ("egg", "medium", "scoop", "bar", "stick", "cake"):
        # Whole items: round to nearest whole number, minimum 1
        return max(1, round(value))
    if unit in ("slice",):
        return max(1, round(value))
    if unit in ("tbsp",):
        return max(0.5, round(value * 2) / 2)
    if unit in ("oz",):
        return max(1, round(value * 2) / 2)
    if unit in ("cup", "half"):
        return max(0.25, round(value * 4) / 4)
    # Default: round to 1 decimal
    return max(0.5, round(value, 1))


def _format_portion(amount, unit):
    """Format a portion amount into a human-readable string."""
    # Fraction display helper
    frac_map = {0.25: "1/4", 0.5: "1/2", 0.75: "3/4"}

    if unit == "scoop":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} scoop{'s' if amount > 1 else ''} + water"
    if unit == "half":
        if amount in frac_map:
            return frac_map[amount]
        if amount == 1.0:
            return "1 whole"
        return f"{amount}"
    if unit == "egg":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} large"
    if unit == "medium":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} medium"
    if unit == "slice":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} slice{'s' if n != 1 else ''}"
    if unit == "bar":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} bar{'s' if n != 1 else ''}"
    if unit == "stick":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} stick{'s' if n != 1 else ''}"
    if unit == "cake":
        n = int(amount) if amount == int(amount) else amount
        return f"{n} cake{'s' if n != 1 else ''}"

    # Numeric + unit with fraction support
    if amount == int(amount):
        return f"{int(amount)} {unit}"
    whole = int(amount)
    frac = round(amount - whole, 2)
    if whole == 0 and frac in frac_map:
        return f"{frac_map[frac]} {unit}"
    if whole > 0 and frac in frac_map:
        return f"{whole} {frac_map[frac]} {unit}"
    return f"{amount} {unit}"


def _scale_food(food_id, scale_factor):
    """Scale a food item by a factor relative to its default portion.

    food_catalog stores macros PER UNIT. default_portion is the number of units
    in a standard serving. scale_factor is applied to default_portion.

    Returns a dict in the exact output format:
        {"item", "portion", "cal", "protein", "carbs", "fat"}
    """
    food = get_food(food_id)
    if food is None:
        return None

    default_units = food["default_portion"]
    target_units = default_units * scale_factor
    rounded_units = _round_portion(target_units, food["unit"])

    return {
        "item": food["name"],
        "portion": _format_portion(rounded_units, food["unit"]),
        "cal": round(food["cal"] * rounded_units),
        "protein": round(food["protein"] * rounded_units),
        "carbs": round(food["carbs"] * rounded_units),
        "fat": round(food["fat"] * rounded_units),
    }


def _pick_from(selections, category, index):
    """Pick a food key from the user's selections for a given category, rotating by index."""
    keys = selections.get(category, [])
    if not keys:
        return None
    # Validate each key exists in catalog
    valid = [k for k in keys if get_food(k) is not None]
    if not valid:
        return None
    return valid[index % len(valid)]


def _compute_meal_times(protocol, num_meals):
    """Generate evenly spaced meal times within the eating window."""
    proto = _FASTING_PROTOCOLS[protocol]
    start_min = _parse_time_minutes(proto["start"])
    end_min = _parse_time_minutes(proto["end"])

    if num_meals == 1:
        return [proto["start"]]

    gap = (end_min - start_min) / (num_meals - 1) if num_meals > 1 else 0
    times = []
    for i in range(num_meals):
        t = start_min + round(gap * i)
        # Round to nearest 30 min
        t = round(t / 30) * 30
        times.append(_format_time(t))
    return times


def _parse_time_minutes(s):
    """Parse '11:00am' -> total minutes since midnight."""
    s = s.strip().lower()
    is_pm = s.endswith("pm")
    s = s.replace("am", "").replace("pm", "")
    parts = s.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    if is_pm and h != 12:
        h += 12
    if not is_pm and h == 12:
        h = 0
    return h * 60 + m


def _format_time(total_minutes):
    """Format total minutes since midnight -> '2:30pm'."""
    h = total_minutes // 60
    m = total_minutes % 60
    suffix = "am" if h < 12 else "pm"
    display_h = h if h <= 12 else h - 12
    if display_h == 0:
        display_h = 12
    return f"{display_h}:{m:02d}{suffix}"


def _sum_macros(foods_list):
    """Sum cal/protein/carbs/fat across a list of food dicts."""
    totals = {"cal": 0, "protein": 0, "carbs": 0, "fat": 0}
    for f in foods_list:
        if f is None:
            continue
        for k in totals:
            totals[k] += f.get(k, 0)
    return totals


# ── Core algorithm ────────────────────────────────────────────────────────────

def _build_meal_foods(protein_key, carb_key, veg_keys, fat_key, meal_targets):
    """Build a list of food items for a single meal, scaling to hit targets.

    Strategy:
        1. Start with protein, scale to hit protein target.
        2. Add carb, scale to hit carb target.
        3. Add vegetables at default portions (low calorie, don't need scaling).
        4. Add fat source, scale to fill remaining fat target.

    Parameters:
        protein_key: food catalog ID for protein source
        carb_key: food catalog ID for carb source (or None)
        veg_keys: list of food catalog IDs for vegetables
        fat_key: food catalog ID for fat source (or None)
        meal_targets: dict with keys cal, protein, carbs, fat

    Returns:
        list of food dicts in output format
    """
    foods = []
    remaining = dict(meal_targets)

    # 1. Protein: scale to hit protein target
    if protein_key:
        food_info = get_food(protein_key)
        if food_info and food_info["protein"] > 0:
            # Macros per default portion
            default_protein = food_info["protein"] * food_info["default_portion"]
            scale = remaining["protein"] / default_protein if default_protein > 0 else 1.0
            scale = max(0.5, min(scale, 3.0))  # Clamp to reasonable range
            if food_info.get("max_portion"):
                max_scale = food_info["max_portion"] / food_info["default_portion"]
                scale = min(scale, max_scale)
            food_item = _scale_food(protein_key, scale)
            if food_item:
                foods.append(food_item)
                for k in remaining:
                    remaining[k] = max(0, remaining[k] - food_item[k])

    # 2. Carb: scale to hit carb target
    if carb_key and remaining["carbs"] > 5:
        food_info = get_food(carb_key)
        if food_info and food_info["carbs"] > 0:
            default_carbs = food_info["carbs"] * food_info["default_portion"]
            scale = remaining["carbs"] / default_carbs if default_carbs > 0 else 1.0
            scale = max(0.25, min(scale, 2.0))
            if food_info.get("max_portion"):
                max_scale = food_info["max_portion"] / food_info["default_portion"]
                scale = min(scale, max_scale)
            food_item = _scale_food(carb_key, scale)
            if food_item:
                foods.append(food_item)
                for k in remaining:
                    remaining[k] = max(0, remaining[k] - food_item[k])

    # 3. Vegetables at default portions (minimal calorie impact)
    for vk in veg_keys:
        if vk:
            food_item = _scale_food(vk, 1.0)
            if food_item:
                foods.append(food_item)
                for k in remaining:
                    remaining[k] = max(0, remaining[k] - food_item[k])

    # 4. Fat source: scale to hit remaining fat target
    if fat_key and remaining["fat"] > 2:
        food_info = get_food(fat_key)
        if food_info and food_info["fat"] > 0:
            default_fat = food_info["fat"] * food_info["default_portion"]
            scale = remaining["fat"] / default_fat if default_fat > 0 else 1.0
            scale = max(0.25, min(scale, 3.0))
            if food_info.get("max_portion"):
                max_scale = food_info["max_portion"] / food_info["default_portion"]
                scale = min(scale, max_scale)
            food_item = _scale_food(fat_key, scale)
            if food_item:
                foods.append(food_item)

    return foods


def _generate_meal_name(position, protein_key, carb_key):
    """Create a descriptive meal name."""
    base = _MEAL_NAMES.get(position, f"Meal {position + 1}")

    parts = []
    if protein_key:
        food = get_food(protein_key)
        if food:
            # Use a short name without prep method
            short = food["name"].split("(")[0].strip()
            parts.append(short)
    if carb_key:
        food = get_food(carb_key)
        if food:
            short = food["name"].split("(")[0].strip()
            parts.append(short)

    if parts:
        return f"{base} - {' + '.join(parts)}"
    return base


# ── Public API ────────────────────────────────────────────────────────────────

def generate_meal_plan(selected_foods, day_type, targets, fasting_protocol="16_8"):
    """Generate a single-day meal plan matching the workout_data.py MEAL_PLANS format.

    Parameters:
        selected_foods: dict of user food selections by category, e.g.
            {"proteins": ["chicken_breast", "eggs", "salmon"],
             "carbs": ["white_rice", "sweet_potato"],
             "fats": ["avocado", "olive_oil", "almonds"],
             "vegetables": ["mixed_greens", "broccoli", "spinach"]}
        day_type: one of "heavy_lift", "long_run", "moderate", "rest", "deload", "fast_day"
        targets: dict {"calories": int, "protein": int, "carbs": int, "fat": int}
        fasting_protocol: one of "16_8", "18_6", "20_4", "omad", "none"

    Returns:
        dict matching MEAL_PLANS structure in workout_data.py:
        {
            "label": str,
            "targetCal": int,
            "targetProtein": int,
            "targetCarbs": int,
            "targetFat": int,
            "note": str,
            "meals": [{"time", "name", "optional", "foods": [...]}, ...]
        }
    """
    # Fast day: minimal plan — water, black coffee, protein shake if targets allow
    if day_type == "fast_day":
        meals = [{
            "time": "Anytime",
            "name": "Fasting",
            "optional": False,
            "foods": [
                dict(_BLACK_COFFEE),
                dict(_WATER),
            ],
        }]
        target_cal = targets.get("calories", 0)
        target_protein = targets.get("protein", 0)
        # If targets have protein (bulk/recomp fast), add a shake
        if target_protein > 0:
            shake_id = None
            for pid in selected_foods.get("proteins", []):
                if pid in ("whey_protein", "plant_protein"):
                    shake_id = pid
                    break
            if shake_id:
                shake = _scale_food(shake_id, 1.0)
                if shake:
                    meals.append({
                        "time": "Anytime",
                        "name": "Protein Shake",
                        "optional": False,
                        "foods": [shake],
                    })
                    target_cal = shake["cal"] + 5
                    target_protein = shake["protein"]
        return {
            "label": "Fast Day",
            "targetCal": target_cal,
            "targetProtein": target_protein,
            "targetCarbs": targets.get("carbs", 0),
            "targetFat": targets.get("fat", 0),
            "note": "Water, black coffee, electrolytes. Rest and recover.",
            "meals": meals,
        }

    proto = _FASTING_PROTOCOLS.get(fasting_protocol, _FASTING_PROTOCOLS["16_8"])
    modifiers = _DAY_MODIFIERS.get(day_type, _DAY_MODIFIERS["moderate"])
    label, note = _DAY_LABELS.get(day_type, ("Training Day", "Standard meal plan."))

    # Apply day-type modifiers to targets
    adj_cal = round(targets["calories"] * modifiers["calories"])
    adj_protein = targets["protein"]  # Protein stays constant
    adj_carbs = round(targets["carbs"] * modifiers["carbs"])
    adj_fat = targets["fat"]
    # Rebalance fat to keep total calories consistent after carb adjustment
    carb_cal_delta = (adj_carbs - targets["carbs"]) * 4
    fat_cal_adjust = carb_cal_delta / 9
    adj_fat = max(20, round(adj_fat - fat_cal_adjust))

    meals = []

    # ── Pre-workout meal ──────────────────────────────────────────────────────
    preworkout_foods = [dict(_BLACK_COFFEE)]
    preworkout_macros = {"cal": 5, "protein": 0, "carbs": 0, "fat": 0}

    if not proto["fasted_preworkout"]:
        # Non-fasting: add protein shake if user has whey or plant protein
        shake_id = None
        for pid in selected_foods.get("proteins", []):
            if pid in ("whey_protein", "plant_protein"):
                shake_id = pid
                break
        if shake_id:
            shake = _scale_food(shake_id, 1.0)
            if shake:
                preworkout_foods.append(shake)
                for k in preworkout_macros:
                    preworkout_macros[k] += shake[k]

    meals.append({
        "time": "5:30am",
        "name": "Pre-Workout",
        "optional": False,
        "foods": preworkout_foods,
    })

    # ── Post-workout shake (heavy_lift / long_run) ────────────────────────────
    post_workout_macros = {"cal": 0, "protein": 0, "carbs": 0, "fat": 0}
    if day_type in ("heavy_lift", "long_run"):
        pw_foods = []
        # Find a protein shake source
        shake_id = None
        for pid in selected_foods.get("proteins", []):
            if pid in ("whey_protein", "plant_protein"):
                shake_id = pid
                break
        if shake_id:
            shake = _scale_food(shake_id, 1.0)
            if shake:
                pw_foods.append(shake)

        # Long run: add banana for quick carbs (only if there's also a shake —
        # a banana alone doesn't warrant a separate meal, it'll go in meal 1)
        if day_type == "long_run" and shake_id:
            banana_id = None
            if "banana" in selected_foods.get("carbs", []):
                banana_id = "banana"
            if banana_id:
                b = _scale_food(banana_id, 1.0)
                if b:
                    pw_foods.append(b)

        if pw_foods:
            post_workout_macros = _sum_macros(pw_foods)
            shake_name = "Post-Workout Shake"
            if any(f["item"] == "Banana" for f in pw_foods):
                shake_name += " + Banana"
            # Place shake at eating window start — not hardcoded 9am which violates fasting
            shake_time = proto["start"] if proto["fasted_preworkout"] else "9:00am"
            meals.append({
                "time": shake_time,
                "name": shake_name,
                "optional": True,
                "foods": pw_foods,
            })

    # ── Remaining macros for eating-window meals ──────────────────────────────
    remaining_total = {
        "cal": adj_cal - preworkout_macros["cal"] - post_workout_macros["cal"],
        "protein": adj_protein - preworkout_macros["protein"] - post_workout_macros["protein"],
        "carbs": adj_carbs - preworkout_macros["carbs"] - post_workout_macros["carbs"],
        "fat": adj_fat - preworkout_macros["fat"] - post_workout_macros["fat"],
    }
    for k in remaining_total:
        remaining_total[k] = max(0, remaining_total[k])

    # Determine number of eating meals
    num_eating_meals = proto["meals"]
    splits = _MEAL_SPLITS.get(num_eating_meals, _MEAL_SPLITS[3])
    meal_times = _compute_meal_times(fasting_protocol, num_eating_meals)

    # ── Build each eating meal ────────────────────────────────────────────────
    # Filter out shake proteins from main meal rotation
    main_proteins = [p for p in selected_foods.get("proteins", [])
                     if p not in ("whey_protein", "plant_protein")]
    if not main_proteins:
        main_proteins = selected_foods.get("proteins", [])

    for i in range(num_eating_meals):
        fraction = splits[i]
        meal_targets = {
            "cal": round(remaining_total["cal"] * fraction),
            "protein": round(remaining_total["protein"] * fraction),
            "carbs": round(remaining_total["carbs"] * fraction),
            "fat": round(remaining_total["fat"] * fraction),
        }

        # Pick food items, rotating through selections
        protein_key = main_proteins[i % len(main_proteins)] if main_proteins else None

        carb_key = _pick_from(selected_foods, "carbs", i) if meal_targets["carbs"] > 10 else None
        fat_key = _pick_from(selected_foods, "fats", i)

        # Pick 1-2 vegetables, rotating
        veg_keys = []
        v1 = _pick_from(selected_foods, "vegetables", i)
        if v1:
            veg_keys.append(v1)
        v2 = _pick_from(selected_foods, "vegetables", i + 1)
        if v2 and v2 != v1:
            veg_keys.append(v2)

        foods = _build_meal_foods(protein_key, carb_key, veg_keys, fat_key, meal_targets)
        meal_name = _generate_meal_name(i, protein_key, carb_key)

        meals.append({
            "time": meal_times[i],
            "name": meal_name,
            "optional": False,
            "foods": foods,
        })

    return {
        "label": label,
        "targetCal": adj_cal,
        "targetProtein": adj_protein,
        "targetCarbs": adj_carbs,
        "targetFat": adj_fat,
        "note": note,
        "meals": meals,
    }


def generate_week_plan(selected_foods, day_types, targets, fasting_protocol="16_8"):
    """Generate a full 7-day meal plan.

    Parameters:
        selected_foods: dict of user food selections (same as generate_meal_plan)
        day_types: list of 7 day types (Mon-Sun), e.g.
            ["heavy_lift", "long_run", "heavy_lift", "moderate", "heavy_lift", "moderate", "rest"]
        targets: dict {"calories": int, "protein": int, "carbs": int, "fat": int}
        fasting_protocol: fasting protocol string

    Returns:
        dict mapping day names to meal plan dicts:
        {"Mon": {...}, "Tue": {...}, ..., "Sun": {...}}
    """
    if len(day_types) != 7:
        raise ValueError(f"day_types must have exactly 7 entries, got {len(day_types)}")

    week = {}

    for day_idx, (day_name, dtype) in enumerate(zip(_WEEKDAYS, day_types)):
        # Rotate food selections so meals differ across days
        rotated_foods = {}
        for category, ids in selected_foods.items():
            if ids:
                offset = day_idx % len(ids)
                rotated_foods[category] = ids[offset:] + ids[:offset]
            else:
                rotated_foods[category] = ids

        week[day_name] = generate_meal_plan(rotated_foods, dtype, targets, fasting_protocol)

    return week
