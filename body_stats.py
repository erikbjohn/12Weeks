"""Body composition, strength percentiles, and measurement analysis."""

import math


# ─── BODY FAT ESTIMATION (US Navy Method) ──────────────────────────────────

def estimate_body_fat_navy(waist, neck, height, sex, hips=None):
    """Estimate body fat percentage using the US Navy Method.

    Args:
        waist: Waist circumference in inches
        neck: Neck circumference in inches
        height: Height in inches
        sex: "male" or "female"
        hips: Hip circumference in inches (required for female)

    Returns:
        float: estimated body fat percentage, or None if inputs missing
    """
    if not waist or not neck or not height:
        return None
    if waist <= neck:
        return None

    try:
        if sex == "female":
            if not hips:
                return None
            bf = 163.205 * math.log10(waist + hips - neck) - 97.684 * math.log10(height) - 78.387
        else:
            bf = 86.010 * math.log10(waist - neck) - 70.041 * math.log10(height) + 36.76
        return round(max(3.0, min(50.0, bf)), 1)
    except (ValueError, ZeroDivisionError):
        return None


def body_fat_category(bf_pct, sex):
    """Return body fat category label."""
    if bf_pct is None:
        return "Unknown"
    if sex == "female":
        if bf_pct < 14:
            return "Essential Fat"
        elif bf_pct < 21:
            return "Athletic"
        elif bf_pct < 25:
            return "Fit"
        elif bf_pct < 32:
            return "Average"
        else:
            return "Above Average"
    else:
        if bf_pct < 6:
            return "Essential Fat"
        elif bf_pct < 14:
            return "Athletic"
        elif bf_pct < 18:
            return "Fit"
        elif bf_pct < 25:
            return "Average"
        else:
            return "Above Average"


# ─── 1RM ESTIMATION ───────────────────────────────────────────────────────

def estimate_1rm(weight, reps):
    """Epley formula: 1RM = weight × (1 + reps/30)."""
    if not weight or not reps or reps <= 0:
        return 0
    if reps == 1:
        return weight
    return round(weight * (1 + reps / 30))


# ─── STRENGTH PERCENTILES ─────────────────────────────────────────────────

# General population 1RM / bodyweight ratios by percentile
# Derived from PubMed study of 809,986 powerlifting entries,
# adjusted down ~1.5x for general population
_STRENGTH_PERCENTILES = {
    "male": {
        "Barbell Bench Press": {
            "percentiles": [(10, 0.40), (25, 0.57), (50, 0.80), (75, 1.03), (90, 1.30), (95, 1.50)],
        },
        "Barbell Back Squat": {
            "percentiles": [(10, 0.55), (25, 0.83), (50, 1.17), (75, 1.50), (90, 1.89), (95, 2.20)],
        },
        "Conventional Deadlift": {
            "percentiles": [(10, 0.70), (25, 1.00), (50, 1.33), (75, 1.67), (90, 2.17), (95, 2.50)],
        },
        "Barbell Bent-Over Row": {
            "percentiles": [(10, 0.35), (25, 0.50), (50, 0.70), (75, 0.90), (90, 1.10), (95, 1.25)],
        },
        "DB Overhead Press": {
            "percentiles": [(10, 0.20), (25, 0.30), (50, 0.45), (75, 0.60), (90, 0.75), (95, 0.85)],
        },
        "Barbell OHP": {
            "percentiles": [(10, 0.25), (25, 0.40), (50, 0.55), (75, 0.70), (90, 0.85), (95, 1.00)],
        },
        "Lat Pulldown": {
            "percentiles": [(10, 0.35), (25, 0.50), (50, 0.65), (75, 0.85), (90, 1.00), (95, 1.15)],
        },
        "Barbell Hip Thrust": {
            "percentiles": [(10, 0.50), (25, 0.75), (50, 1.00), (75, 1.35), (90, 1.70), (95, 2.00)],
        },
        "EZ-Bar Curl": {
            "percentiles": [(10, 0.15), (25, 0.25), (50, 0.35), (75, 0.45), (90, 0.55), (95, 0.65)],
        },
        "Cable Tricep Pushdown": {
            "percentiles": [(10, 0.15), (25, 0.22), (50, 0.30), (75, 0.40), (90, 0.50), (95, 0.55)],
        },
    },
    "female": {
        "Barbell Bench Press": {
            "percentiles": [(10, 0.25), (25, 0.38), (50, 0.55), (75, 0.72), (90, 0.90), (95, 1.05)],
        },
        "Barbell Back Squat": {
            "percentiles": [(10, 0.40), (25, 0.60), (50, 0.85), (75, 1.10), (90, 1.40), (95, 1.65)],
        },
        "Conventional Deadlift": {
            "percentiles": [(10, 0.50), (25, 0.75), (50, 1.00), (75, 1.30), (90, 1.65), (95, 1.95)],
        },
        "Barbell Bent-Over Row": {
            "percentiles": [(10, 0.25), (25, 0.35), (50, 0.50), (75, 0.65), (90, 0.80), (95, 0.95)],
        },
        "DB Overhead Press": {
            "percentiles": [(10, 0.12), (25, 0.20), (50, 0.30), (75, 0.42), (90, 0.55), (95, 0.65)],
        },
    },
}

# Age adjustment factors (relative to 18-35 peak)
_AGE_FACTORS = {
    (0, 18): 0.75,
    (18, 35): 1.00,
    (35, 45): 0.95,
    (45, 55): 0.88,
    (55, 65): 0.80,
    (65, 100): 0.70,
}


def _get_age_factor(age):
    for (lo, hi), factor in _AGE_FACTORS.items():
        if lo <= age < hi:
            return factor
    return 0.85


def compute_1rm_percentile(one_rm, body_weight, exercise, age, sex):
    """Compute population percentile for a given 1RM.

    Returns dict: {"percentile": int, "relative_strength": float, "rating": str}
    """
    if not one_rm or not body_weight or body_weight <= 0:
        return {"percentile": 0, "relative_strength": 0, "rating": "Unknown"}

    relative = one_rm / body_weight
    age_factor = _get_age_factor(age)
    # Adjust relative strength for age — older lifters get credit
    adjusted_relative = relative / age_factor

    sex_data = _STRENGTH_PERCENTILES.get(sex, _STRENGTH_PERCENTILES["male"])
    ex_data = sex_data.get(exercise)
    if not ex_data:
        # Try to find closest match
        for key in sex_data:
            if key.lower() in exercise.lower() or exercise.lower() in key.lower():
                ex_data = sex_data[key]
                break
    if not ex_data:
        return {"percentile": 50, "relative_strength": round(relative, 2), "rating": "N/A"}

    percentiles = ex_data["percentiles"]

    # Interpolate percentile
    pct = 5  # below minimum
    for i, (p, ratio) in enumerate(percentiles):
        if adjusted_relative <= ratio:
            if i == 0:
                pct = max(1, int(p * adjusted_relative / ratio))
            else:
                prev_p, prev_r = percentiles[i - 1]
                frac = (adjusted_relative - prev_r) / (ratio - prev_r) if ratio != prev_r else 0
                pct = int(prev_p + frac * (p - prev_p))
            break
    else:
        pct = min(99, int(percentiles[-1][0] + (adjusted_relative - percentiles[-1][1]) * 10))

    # Rating
    if pct >= 90:
        rating = "Elite"
    elif pct >= 75:
        rating = "Advanced"
    elif pct >= 50:
        rating = "Intermediate"
    elif pct >= 25:
        rating = "Novice"
    else:
        rating = "Beginner"

    return {
        "percentile": max(1, min(99, pct)),
        "relative_strength": round(relative, 2),
        "rating": rating,
    }


# ─── BODY MEASUREMENTS ────────────────────────────────────────────────────

_MEASUREMENT_AVERAGES = {
    "male": {
        "waist": {"avg": 40.5, "unit": "in", "label": "Waist"},
        "chest": {"avg": 42.0, "unit": "in", "label": "Chest"},
        "bicep": {"avg": 13.5, "unit": "in", "label": "Bicep"},
        "thigh": {"avg": 23.0, "unit": "in", "label": "Thigh"},
        "neck": {"avg": 16.0, "unit": "in", "label": "Neck"},
        "hips": {"avg": 41.0, "unit": "in", "label": "Hips"},
    },
    "female": {
        "waist": {"avg": 38.7, "unit": "in", "label": "Waist"},
        "chest": {"avg": 38.0, "unit": "in", "label": "Chest"},
        "bicep": {"avg": 12.0, "unit": "in", "label": "Bicep"},
        "thigh": {"avg": 22.0, "unit": "in", "label": "Thigh"},
        "neck": {"avg": 13.5, "unit": "in", "label": "Neck"},
        "hips": {"avg": 42.0, "unit": "in", "label": "Hips"},
    },
}


def get_measurement_comparison(value, measurement_key, sex):
    """Compare a measurement to population average."""
    avgs = _MEASUREMENT_AVERAGES.get(sex, _MEASUREMENT_AVERAGES["male"])
    ref = avgs.get(measurement_key)
    if not ref or not value:
        return None
    diff = round(value - ref["avg"], 1)
    if abs(diff) < 0.5:
        status = "at average"
    elif diff > 0:
        status = f"+{diff}\" above avg"
    else:
        status = f"{diff}\" below avg"
    return {
        "value": value,
        "avg": ref["avg"],
        "diff": diff,
        "status": status,
        "label": ref["label"],
    }


# ─── FULL BASELINE ASSESSMENT ─────────────────────────────────────────────

def build_baseline_assessment(physical_data, lifting_data, age, sex, body_weight):
    """Build the complete baseline assessment.

    Args:
        physical_data: dict with waist, neck, height, hips, chest, bicep, thigh
        lifting_data: dict of exercise name → {"current": weight, "history": [...]}
        age: int
        sex: "male" or "female"
        body_weight: float in lbs

    Returns:
        dict with body_comp, strength, measurements, summary
    """
    result = {
        "body_comp": {},
        "strength": [],
        "measurements": [],
        "summary": {},
    }

    # ─── Body Composition ─────────────────────────────────
    waist = physical_data.get("waist")
    neck = physical_data.get("neck")
    height = physical_data.get("height")
    hips = physical_data.get("hips")

    bf_pct = estimate_body_fat_navy(waist, neck, height, sex, hips)
    lean_mass = round(body_weight * (1 - bf_pct / 100), 1) if bf_pct else None
    fat_mass = round(body_weight * (bf_pct / 100), 1) if bf_pct else None

    result["body_comp"] = {
        "body_fat_pct": bf_pct,
        "category": body_fat_category(bf_pct, sex),
        "body_weight": body_weight,
        "lean_mass": lean_mass,
        "fat_mass": fat_mass,
        "height": height,
    }

    # ─── Strength Assessment ──────────────────────────────
    strongest = None
    weakest = None

    for ex_name, info in (lifting_data or {}).items():
        history = info.get("history", [])
        if not history:
            continue

        last = history[-1]
        sets_label = str(last.get("reps", ""))

        # Parse baseline format: "baseline: 95lb x 13"
        one_rm = 0
        test_weight = 0
        test_reps = 0
        baseline_match = None

        import re
        # Try multiple formats: "baseline: 95lb x 13", "95 lb x 13", "95lb x13", etc.
        baseline_match = re.search(r'(\d+)\s*(?:lb|lbs?)?\s*x\s*(\d+)', sets_label, re.IGNORECASE)
        if baseline_match:
            test_weight = int(baseline_match.group(1))
            test_reps = int(baseline_match.group(2))
            one_rm = estimate_1rm(test_weight, test_reps)
        elif info.get("current", 0) > 0:
            # Fallback: estimate from working weight (working = 75% of 1RM)
            one_rm = round(info.get("current", 0) / 0.75)
        else:
            one_rm = 0

        if one_rm <= 0:
            continue

        pct_data = compute_1rm_percentile(one_rm, body_weight, ex_name, age, sex)

        entry = {
            "exercise": ex_name,
            "test_weight": test_weight,
            "test_reps": test_reps,
            "estimated_1rm": one_rm,
            "relative_strength": pct_data["relative_strength"],
            "percentile": pct_data["percentile"],
            "rating": pct_data["rating"],
        }
        result["strength"].append(entry)

        if strongest is None or pct_data["percentile"] > strongest["percentile"]:
            strongest = entry
        if weakest is None or pct_data["percentile"] < weakest["percentile"]:
            weakest = entry

    # ─── Measurements ─────────────────────────────────────
    measurement_keys = [
        ("waist", "waist"), ("chest", "chest"), ("bicep", "bicep"),
        ("thigh", "thigh"), ("neck", "neck"), ("hips", "hips"),
    ]
    for data_key, ref_key in measurement_keys:
        val = physical_data.get(data_key)
        if val:
            comp = get_measurement_comparison(val, ref_key, sex)
            if comp:
                result["measurements"].append(comp)

    # ─── Summary ──────────────────────────────────────────
    result["summary"] = {
        "strongest": strongest["exercise"] if strongest else None,
        "strongest_percentile": strongest["percentile"] if strongest else None,
        "weakest": weakest["exercise"] if weakest else None,
        "weakest_percentile": weakest["percentile"] if weakest else None,
        "body_fat_pct": bf_pct,
        "body_fat_category": body_fat_category(bf_pct, sex) if bf_pct else None,
    }

    return result
