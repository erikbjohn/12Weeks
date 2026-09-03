"""Day-title helpers shared by the card (app.api_workouts) and the coach
resolver (coach_assembler._resolve_workout_for_day). Lives here so both see
the SAME title — coach_assembler must not import app (S070)."""

_MUSCLE_LABELS = {
    "chest": "Chest", "chest_triceps": "Chest & Triceps", "back": "Back",
    "traps": "Traps", "shoulders": "Shoulders", "rear_delts": "Rear Delts",
    "quads": "Quads", "posterior_chain": "Posterior Chain",
    "hamstrings": "Hamstrings", "glutes": "Glutes", "calves": "Calves",
    "biceps": "Biceps", "triceps": "Triceps", "full_body": "Full Body",
    "power": "Power", "core": "Core",
}


def _scrub_deload_label(text):
    """Remove the word 'Deload' (and its '(light)' qualifiers) from a day
    title. The word is a VERDICT — it may only appear when the week's
    persisted flag says so (deload.py), never as template residue."""
    import re as _re
    if not text:
        return text
    out = _re.sub(r"(?i)\s*deload\s*[—–-]?\s*", " ", text)
    out = _re.sub(r"(?i)\s*\(light\)", "", out)
    out = _re.sub(r"(?i)\blight\b", "", out)
    out = _re.sub(r"\s{2,}", " ", out).strip(" —–-\t ")
    return out or None


def _schedule_day_title(template_name, coach_exercise_names, is_deload=False):
    """The day title written to WeeklyDaySchedule at generation. Prefers a name
    derived from the COACH'S exercises (the template label goes stale the moment
    the coach redesigns the day — audit S079, 'Deload — Lower' over a squat
    progression); scrubs 'Deload' unless the coach actually called one."""
    base = template_name
    if coach_exercise_names:
        base = _derive_lift_name(coach_exercise_names) or template_name
    if is_deload or not base:
        return base
    if "deload" in base.lower():
        base = _scrub_deload_label(base) or _derive_lift_name(coach_exercise_names) or "Training"
    return base


def _derive_lift_name(exercise_names):
    """Build an ACCURATE day title from the muscle groups the day actually
    trains. The template's day label ("HEAVY Lower", "Shoulder/Arms") goes stale
    when the coach redesigns the exercises — naming the day from its real
    contents kills the liftName-vs-exercises contradiction class."""
    from collections import Counter
    from workout_data import EXERCISES, resolve_name
    counts = Counter()
    for nm in exercise_names or []:
        info = EXERCISES.get(nm) or EXERCISES.get(resolve_name(nm)) or {}
        g = info.get("muscle_group")
        if not g:
            n = (nm or "").lower()
            if any(k in n for k in ("squat", "lunge", "leg press", "step-up")):
                g = "quads"
            elif "deadlift" in n or "rdl" in n or "good morning" in n:
                g = "posterior_chain"
            elif "calf" in n:
                g = "calves"
        if g:
            counts[g] += 1
    if not counts:
        return None
    # Core/abs don't name the day unless that's all there is.
    non_core = {g: c for g, c in counts.items() if g != "core"}
    use = non_core or counts
    top = [g for g, _ in sorted(use.items(), key=lambda kv: (-kv[1], kv[0]))][:2]
    name = " & ".join(_MUSCLE_LABELS.get(g, g.replace("_", " ").title()) for g in top)
    if non_core and "core" in counts:
        name += " + Core"
    return name


def _reconcile_lift_name(current, exercise_names, is_deload=False):
    """Keep a curated day title when it matches the movements; replace it with a
    muscle-derived title only when it names the WRONG region (a Lower title over
    an all-upper list) OR omits the day's DOMINANT muscle while naming specific
    others ("Shoulder/Arms" on a back-dominant day). Region/pattern labels
    ("HEAVY Lower", "Full Body", "Pull + Lat") that match are trusted as-is.
    'Deload' in a title is a VERDICT: unless the week's persisted flag says so
    (is_deload), it is scrubbed before any other logic (2026-08-30: four served
    week-4 titles still read 'Deload — …' on a vetoed progression week)."""
    from collections import Counter
    from workout_data import EXERCISES, resolve_name
    if not is_deload and current and "deload" in current.lower():
        current = _scrub_deload_label(current) or _derive_lift_name(exercise_names) or "Training"
    derived = _derive_lift_name(exercise_names)
    if not derived or not current:
        return current
    counts = Counter()
    for nm in exercise_names or []:
        g = (EXERCISES.get(nm) or EXERCISES.get(resolve_name(nm)) or {}).get("muscle_group")
        if not g:
            n = (nm or "").lower()
            if any(k in n for k in ("squat", "lunge", "leg press", "step-up")):
                g = "quads"
            elif "deadlift" in n or "rdl" in n:
                g = "posterior_chain"
            elif "calf" in n:
                g = "calves"
        if g and g != "core":
            counts[g] += 1
    if not counts:
        return current
    UPPER = {"chest", "chest_triceps", "back", "traps", "shoulders", "rear_delts", "biceps", "triceps"}
    LOWER = {"quads", "posterior_chain", "hamstrings", "glutes", "calves"}
    nu = sum(c for g, c in counts.items() if g in UPPER)
    nl = sum(c for g, c in counts.items() if g in LOWER)
    region = "upper" if nu > nl else ("lower" if nl > nu else "full")
    c = current.lower()
    c_lower = any(k in c for k in ("lower", "squat", "quad", "glute", "hamstring", "deadlift", "rdl", "leg", "calf", "hip thrust", "posterior"))
    c_upper = any(k in c for k in ("upper", "press", "bench", "push", "pull", "row", "shoulder", "chest", "back", "lat", "curl", "tricep", "bicep", "ohp", "delt", "arm"))
    c_region = "lower" if (c_lower and not c_upper) else ("upper" if (c_upper and not c_lower) else None)
    if c_region and region in ("upper", "lower") and c_region != region:
        return derived  # outright region swap
    if any(w in c for w in ("upper", "lower", "full", "push", "pull", "press")):
        return current  # a region/pattern label that matches the region — trust it
    dominant = counts.most_common(1)[0][0]
    DOM_KW = {
        "chest": ("chest",), "chest_triceps": ("chest", "tricep"),
        "back": ("back", "lat"), "shoulders": ("shoulder", "delt"),
        "rear_delts": ("shoulder", "delt", "rear"), "traps": ("trap", "shrug"),
        "quads": ("quad", "squat", "leg"), "glutes": ("glute", "hip"),
        "hamstrings": ("hamstring", "ham"), "calves": ("calf",),
        "biceps": ("bicep", "arm", "curl"), "triceps": ("tricep", "arm"),
    }
    kws = DOM_KW.get(dominant, ())
    if kws and not any(k in c for k in kws):
        return derived  # title names specific muscles but omits the dominant one
    return current
