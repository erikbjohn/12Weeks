"""Adaptive training engine — computes exercise targets from performance data."""

import re
from datetime import date, datetime, timedelta, timezone
from models import db, SetLog, MuscleGroupProfile, SessionAnalysis


# Exercise → muscle group mapping (pulled from equipment_swaps at runtime)
def _get_muscle_group(exercise_name):
    """Get the muscle group for an exercise."""
    from workout_data import resolve_name
    exercise_name = resolve_name(exercise_name)
    try:
        from equipment_swaps import EXERCISE_SWAPS
        swap = EXERCISE_SWAPS.get(exercise_name)
        if swap:
            return swap.get("muscle_group", "unknown")
    except Exception:
        pass
    # Fallback keyword matching
    nl = exercise_name.lower()
    if any(k in nl for k in ['bench', 'push', 'fly', 'chest']):
        return 'chest'
    if any(k in nl for k in ['row', 'pull', 'lat']):
        return 'back'
    if any(k in nl for k in ['press', 'shoulder', 'ohp', 'lateral', 'raise']):
        return 'shoulders'
    if any(k in nl for k in ['squat', 'lunge', 'leg press', 'extension']):
        return 'quads'
    if any(k in nl for k in ['deadlift', 'rdl', 'curl', 'hamstring', 'nordic']):
        return 'hamstrings'
    if any(k in nl for k in ['bicep', 'curl']) and 'leg' not in nl:
        return 'biceps'
    if any(k in nl for k in ['tricep', 'pushdown', 'skull', 'dip']):
        return 'triceps'
    if 'calf' in nl:
        return 'calves'
    if any(k in nl for k in ['hip thrust', 'glute', 'bridge']):
        return 'glutes'
    return 'unknown'


def _get_phase(week):
    if week <= 4: return 1
    if week <= 8: return 2
    return 3


def _is_deload(week):
    return week in (4, 8)


def _is_peak_week(week):
    """Week 12 = peak finish (mini-taper, scale+look). HOLD everything."""
    return week == 12


def _get_progression_increment(exercise_name, is_weak):
    """Get the weight increment for progression."""
    if is_weak:
        return 2.5  # Conservative for weak muscle groups
    nl = exercise_name.lower()
    # Small isolation movements
    if any(k in nl for k in ['curl', 'raise', 'fly', 'extension', 'pushdown', 'face pull']):
        return 2.5
    # Heavy compound lower body — can absorb bigger jumps and the program demands
    # them (5x5 phase, "hit target reps = weight goes up, train near failure").
    if any(k in nl for k in ['squat', 'deadlift', 'hip thrust', 'leg press']):
        # Exclude split-stance and unilateral variants — those are dumbbell-loaded
        # accessory work and can't take 10 lb jumps cleanly.
        if not any(uni in nl for uni in ['split squat', 'bulgarian', 'split sq', 'lunge', 'pistol', 'single']):
            return 10.0
    return 5.0


def _get_configured_reps(exercise_name, week, day_idx, exercise_order=None):
    """Look up the configured rep count from workout data for this exercise."""
    sets_reps = _get_configured_sets_reps(exercise_name, week, day_idx, exercise_order)
    return sets_reps[1] if sets_reps else None


def _get_configured_sets(exercise_name, week, day_idx, exercise_order=None):
    """Look up the configured set count from workout data for this exercise."""
    sets_reps = _get_configured_sets_reps(exercise_name, week, day_idx, exercise_order)
    return sets_reps[0] if sets_reps else None


def _get_configured_sets_reps(exercise_name, week, day_idx, exercise_order=None):
    """Return (sets, reps) from the program template, or None if unknown.

    When exercise_order is provided, look up by position first and verify the
    name matches. This disambiguates exercises that appear twice in the same
    day (e.g. Phase 2 Tuesday has the heavy Lat Pulldown 5x5 at order 0 AND a
    pump Lat Pulldown 3x12 at order 2 — by name alone we'd return whichever
    comes first). Falls back to first-name-match when order is unspecified or
    doesn't line up.

    Both sides of the name comparison go through resolve_name so an alias-
    bearing template entry ("Heavy Lat Pulldown") matches a stored canonical
    row ("Lat Pulldown") and vice versa.
    """
    from workout_data import resolve_name
    canon = resolve_name(exercise_name).lower()
    try:
        from workout_data import get_workouts
        days = get_workouts(week)
        if day_idx < len(days):
            day = days[day_idx]
            exercises = day.get("exercises", []) or []
            if (exercise_order is not None and 0 <= exercise_order < len(exercises)):
                ex = exercises[exercise_order]
                if resolve_name(ex.get("name", "")).lower() == canon:
                    m = re.match(r"(\d+)x(\d+)", ex.get("sets", ""))
                    if m:
                        return int(m.group(1)), int(m.group(2))
            for ex in exercises:
                if resolve_name(ex.get("name", "")).lower() == canon:
                    m = re.match(r"(\d+)x(\d+)", ex.get("sets", ""))
                    if m:
                        return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


def _round_weight(weight):
    """Always round UP to the nearest 5 lbs. Never round down — we progress, not regress."""
    if weight <= 0:
        return 0
    import math
    return int(math.ceil(weight / 5) * 5)


def compute_next_targets(user_id, exercise_name, week, day_idx, exercise_order=None):
    """Compute targets for the next time this exercise appears.

    exercise_order disambiguates exercises that appear multiple times in the same
    day (Phase 2 Tuesday lists Lat Pulldown twice — heavy 5x5 at order 0 and pump
    3x12 at order 2). Without it, the configured-reps lookup returns the first
    match by name and the pump row gets prescribed the heavy row's rep scheme,
    which then triggers the rep-drop compensation against last session's reps and
    bumps weight ~10% on a row that should never see that bump.

    Returns: {
        target_weight: float,
        target_reps: int,
        target_sets: int,
        adjustment_reason: str,
        progression_indicator: str  ('up', 'hold', 'deload', 'weak', 'down')
    }
    """
    from workout_data import resolve_name
    raw_exercise_name = exercise_name
    exercise_name = resolve_name(exercise_name)
    phase = _get_phase(week)
    muscle_group = _get_muscle_group(exercise_name)

    # Check muscle group strength
    profile = MuscleGroupProfile.query.filter_by(
        user_id=user_id, muscle_group=muscle_group
    ).first()
    is_weak = profile and (profile.user_flagged_weak or profile.relative_strength in ('weak', 'very_weak'))

    # Get last session data for this exercise. Historical SetLog rows may have
    # been stored under either the un-resolved alias (e.g. "Back Squat") or the
    # canonical name (e.g. "Barbell Back Squat") — query both so we don't miss
    # a user's own history just because the alias map evolved.
    name_candidates = [exercise_name]
    if raw_exercise_name and raw_exercise_name != exercise_name:
        name_candidates.append(raw_exercise_name)
    last_sets = SetLog.query.filter(
        SetLog.user_id == user_id,
        SetLog.exercise_name.in_(name_candidates),
        SetLog.done == True,  # noqa: E712 — SQLAlchemy truth
    ).order_by(SetLog.logged_date.desc(), SetLog.set_number.asc()).limit(20).all()

    if not last_sets:
        # No history — return defaults based on phase
        rep_range = {1: 10, 2: 8, 3: 5}
        return {
            "target_weight": None,
            "target_reps": rep_range.get(phase, 10),
            "target_sets": 4 if phase <= 2 else 3,
            "adjustment_reason": "First session — establish baseline",
            "progression_indicator": "hold",
        }

    # ─── PEAK WEEK (week 12) — HOLD ───
    # Mini-taper. No bumps, no drops. Maintain Phase 3 lifts at the same
    # weight, reps, sets. Spec §7.
    if _is_peak_week(week):
        last_date = last_sets[0].logged_date
        session_sets = [s for s in last_sets if s.logged_date == last_date]
        last_weight = session_sets[0].weight if session_sets else 0
        last_reps = session_sets[0].reps if session_sets else 0
        last_set_count = len(session_sets)
        configured_reps = _get_configured_reps(
            exercise_name, week, day_idx, exercise_order,
        )
        configured_sets_peak = _get_configured_sets(
            exercise_name, week, day_idx, exercise_order,
        )
        return {
            "target_weight": _round_weight(last_weight),
            "target_reps": configured_reps or last_reps or 3,
            "target_sets": configured_sets_peak or last_set_count or 2,
            "adjustment_reason": "Week 12 peak — HOLD all knobs",
            "progression_indicator": "hold",
        }

    # Exclude deload-week sessions when establishing the progression baseline
    # for THIS (non-deload) week. Deload prescriptions are engine-mandated 85%
    # reductions; counting them as "the user's last session" makes the engine
    # misread its own deload as voluntary regression and peg the next week at
    # the deload weight.
    if not _is_deload(week):
        non_deload_sets = [s for s in last_sets if not _is_deload(s.week)]
        if non_deload_sets:
            last_sets = non_deload_sets

    # Get the most recent session's data
    last_date = last_sets[0].logged_date
    session_sets = [s for s in last_sets if s.logged_date == last_date]
    last_weight = session_sets[0].weight if session_sets else 0
    last_reps = session_sets[0].reps if session_sets else 0
    last_set_count = len(session_sets)

    # Volume floor: the program's configured set count is the source of truth.
    # Without this, every branch below took target_sets = last_set_count, so a
    # user who logged 2 sets once got prescribed 2 sets forever — the program's
    # 5x5 template silently collapsed to 2x5. The "Volume is sacred" comment in
    # SIGNAL 4 only enforced sacred-ness for THAT branch; this generalises it.
    # When the configured count is unknown (e.g. exercise auto-swapped to one
    # not in the template), preserve the user's logged effort as a fallback.
    configured_sets = _get_configured_sets(exercise_name, week, day_idx, exercise_order)
    target_sets = configured_sets or last_set_count or (4 if phase <= 2 else 3)

    # Check if user ACTUALLY decreased weight vs their PREVIOUS session (not vs computed target).
    # The old logic compared against the engine's computed target — if the engine suggested 115
    # but the user was prescribed 110 and lifted 110, it was wrongly flagged as "decreased".
    # Now we compare against what they actually lifted in the prior session.
    prev_session_sets = [s for s in last_sets if s.logged_date != last_date]
    prev_weight = prev_session_sets[0].weight if prev_session_sets else None
    user_increased = prev_weight is not None and last_weight > prev_weight * 1.02
    user_decreased = prev_weight is not None and last_weight < prev_weight * 0.95
    sets_skipped = sum(1 for s in session_sets if getattr(s, 'set_skipped', False))

    # Avg reps across session
    avg_reps = sum(s.reps for s in session_sets if s.reps) / max(len(session_sets), 1)
    target_reps_last = getattr(session_sets[0], 'target_reps', None) or avg_reps
    exceeded_reps = avg_reps > target_reps_last + 1 if target_reps_last else False

    inc = _get_progression_increment(exercise_name, is_weak)

    # ─── SIGNAL 7: DELOAD WEEK ───
    if _is_deload(week):
        return {
            "target_weight": _round_weight(last_weight * 0.85),
            "target_reps": last_reps,
            "target_sets": target_sets,
            "adjustment_reason": "Deload week — 85% weight, recovery focus",
            "progression_indicator": "deload",
        }

    # ─── SIGNAL 6: WEAK MUSCLE GROUP ───
    # Any muscle marked weak (user-flagged or relative_strength weak/very_weak) gets
    # conservative progression: +2.5 lb only after 3 clean sessions. Shoulders additionally
    # cap reps at 12-15 because high-rep shoulder work protects the joint.
    if is_weak:
        good_sessions = _count_consecutive_good_sessions(user_id, exercise_name)
        configured_reps = _get_configured_reps(exercise_name, week, day_idx, exercise_order)
        if muscle_group == 'shoulders':
            target_reps = min(max(last_reps, 12), 15)
        else:
            target_reps = configured_reps or last_reps or {1: 10, 2: 6, 3: 4}.get(phase, 10)
        if good_sessions >= 3:
            new_weight = _round_weight(last_weight + 2.5)
            return {
                "target_weight": new_weight,
                "target_reps": target_reps,
                "target_sets": target_sets,
                "adjustment_reason": f"3 good sessions — +2.5 lb ({muscle_group}: conservative)",
                "progression_indicator": "up",
            }
        return {
            "target_weight": _round_weight(last_weight),
            "target_reps": target_reps,
            "target_sets": target_sets,
            "adjustment_reason": f"{muscle_group.capitalize()} weak — holding ({good_sessions}/3 good sessions for increase)",
            "progression_indicator": "weak",
        }

    # ─── SIGNAL 2: USER INCREASED WEIGHT ───
    if user_increased:
        # Unilateral/split-stance lifts and small accessories can't take the
        # doubled jump cleanly — cap the bump at the base increment for those.
        nl_for_cap = exercise_name.lower()
        is_unilateral = any(k in nl_for_cap for k in [
            'split squat', 'bulgarian', 'split sq', 'lunge', 'pistol',
            'single', 'step-up', 'step up',
        ])
        bump = inc if is_unilateral else inc * 2
        new_weight = _round_weight(last_weight + bump)
        return {
            "target_weight": new_weight,
            "target_reps": last_reps,
            "target_sets": target_sets,
            "adjustment_reason": "You went heavier last time — pushing further",
            "progression_indicator": "up",
        }

    # ─── SIGNAL 3: USER DECREASED ───
    if user_decreased:
        return {
            "target_weight": _round_weight(last_weight),
            "target_reps": last_reps,
            "target_sets": target_sets,
            "adjustment_reason": "Reduced last session — holding weight",
            "progression_indicator": "hold",
        }

    # ─── SIGNAL 4: SETS SKIPPED ───
    # Volume is sacred — never reduce sets. Alert the coach instead.
    coach_alert = None
    if sets_skipped >= 2:
        coach_alert = f"skipped_{sets_skipped}_sets"
        # target_sets stays at configured count — volume is sacred

    # ─── SIGNAL 5: EXCEEDED REPS ───
    if exceeded_reps:
        new_weight = _round_weight(last_weight + inc)
        result = {
            "target_weight": new_weight,
            "target_reps": {1: 10, 2: 6, 3: 4}.get(phase, 10),
            "target_sets": target_sets,
            "adjustment_reason": f"Beat rep target — weight +{inc} lb",
            "progression_indicator": "up",
        }
        if coach_alert:
            result["coach_alert"] = coach_alert
        return result

    # ─── SIGNAL 1: STANDARD PROGRESSION BY PHASE ───
    if phase == 1:
        # Hypertrophy: increase reps, then bump weight
        # Cap at the workout's configured reps if available, otherwise 15
        configured_reps = _get_configured_reps(exercise_name, week, day_idx, exercise_order)
        phase_max_reps = configured_reps if configured_reps else 15
        if avg_reps >= phase_max_reps:
            new_weight = _round_weight(last_weight + inc)
            result = {
                "target_weight": new_weight,
                "target_reps": configured_reps or 10,
                "target_sets": target_sets,
                "adjustment_reason": f"Hit {int(avg_reps)} reps — weight +{inc} lb, reps reset to {configured_reps or 10}",
                "progression_indicator": "up",
            }
            if coach_alert:
                result["coach_alert"] = coach_alert
            return result
        target = min(int(avg_reps) + 2, phase_max_reps)
        result = {
            "target_weight": _round_weight(last_weight),
            "target_reps": target,
            "target_sets": target_sets,
            "adjustment_reason": f"Building reps: {int(avg_reps)} → {target}",
            "progression_indicator": "up" if avg_reps < phase_max_reps else "hold",
        }
        if coach_alert:
            result["coach_alert"] = coach_alert
        return result

    elif phase == 2:
        # Strength: increase weight every 1-2 sessions.
        # If the rep scheme just dropped (e.g. Phase 1 4x10-12 → Phase 2 5x5),
        # a flat +inc is far too conservative — fewer reps demand more weight.
        # Bump ~10% when this week's configured reps are <70% of last session's.
        configured_reps = _get_configured_reps(exercise_name, week, day_idx, exercise_order)
        rep_drop_factor = 1.0
        if configured_reps and last_reps and configured_reps < last_reps * 0.7:
            rep_drop_factor = 1.10
        base_weight = last_weight * rep_drop_factor if rep_drop_factor > 1.0 else last_weight
        new_weight = _round_weight(base_weight + inc)
        reason = f"Strength phase — +{inc} lb"
        if rep_drop_factor > 1.0:
            reason = f"Rep drop {last_reps}→{configured_reps} — +10% weight then +{inc} lb"
        result = {
            "target_weight": new_weight,
            "target_reps": configured_reps or max(5, last_reps),
            "target_sets": target_sets,
            "adjustment_reason": reason,
            "progression_indicator": "up",
        }
        if coach_alert:
            result["coach_alert"] = coach_alert
        return result

    else:  # Phase 3 — Cut climax. HOLD weights by default.
        configured_reps = _get_configured_reps(
            exercise_name, week, day_idx, exercise_order,
        )
        configured_sets_for_phase3 = _get_configured_sets(
            exercise_name, week, day_idx, exercise_order,
        )
        # Default behavior: HOLD weight, reps, sets (per spec §1, §6).
        # The strength block of Phase 2 is the deposit; Phase 3 protects it.
        # Phase 3 floor reps = 3 (3×3 / 4×3-5 templates); use as fallback when
        # the workout template has no entry for this exercise (e.g. swap).
        phase3_default_reps = 3
        phase3_default_sets = 3
        target_reps_threshold = configured_reps or phase3_default_reps
        target_sets_threshold = (
            configured_sets_for_phase3 or phase3_default_sets
        )
        held_reps = configured_reps or last_reps or phase3_default_reps
        held_sets = (
            configured_sets_for_phase3
            or last_set_count
            or phase3_default_sets
        )
        # Drop if user clearly missed top-set reps last session (proxy for
        # RPE>8). Two signals indicate "missed":
        #   (1) reps below the prescribed/floor count, OR
        #   (2) sets cut short below prescribed/floor.
        # Either is a strong RPE>8 indicator.
        missed_reps = bool(
            last_reps and last_reps < target_reps_threshold
        )
        missed_sets = bool(
            last_set_count and last_set_count < target_sets_threshold
        )
        if missed_reps or missed_sets:
            new_weight = _round_weight(last_weight * 0.95)
            if missed_reps:
                reason = (
                    f"Phase 3 — missed reps last session "
                    f"({last_reps}/{target_reps_threshold}), drop 5%"
                )
            else:
                reason = (
                    f"Phase 3 — cut session short "
                    f"({last_set_count}/{target_sets_threshold} sets), "
                    "drop 5%"
                )
            return {
                "target_weight": new_weight,
                "target_reps": held_reps,
                "target_sets": held_sets,
                "adjustment_reason": reason,
                "progression_indicator": "hold",
            }
        # Default HOLD path.
        result = {
            "target_weight": _round_weight(last_weight),
            "target_reps": held_reps,
            "target_sets": held_sets,
            "adjustment_reason": "Phase 3 cut climax — HOLD",
            "progression_indicator": "hold",
        }
        if coach_alert:
            result["coach_alert"] = coach_alert
        return result


def _count_consecutive_good_sessions(user_id, exercise_name):
    """Count consecutive sessions where user completed as prescribed (no modifications)."""
    sessions = SetLog.query.filter_by(
        user_id=user_id, exercise_name=exercise_name, done=True
    ).order_by(SetLog.logged_date.desc()).limit(30).all()

    if not sessions:
        return 0

    count = 0
    current_date = None
    for s in sessions:
        if s.logged_date != current_date:
            current_date = s.logged_date
            mod_dir = getattr(s, 'modification_direction', None)
            if mod_dir and mod_dir not in ('as_prescribed', None):
                break
            count += 1
    return count


def compute_muscle_strength(user_id):
    """Recompute muscle group strength scores from recent performance."""
    # Use user's local timezone, not server UTC
    try:
        from models import User
        from utils_time import user_local_now
        user = User.query.get(user_id)
        user_tz = user.timezone if user and user.timezone else 'UTC'
        _today = user_local_now(user_tz).date()
    except Exception:
        _today = date.today()
    since = _today - timedelta(days=14)
    recent_sets = SetLog.query.filter(
        SetLog.user_id == user_id,
        SetLog.done == True,
        SetLog.logged_date >= since
    ).all()

    # Group by muscle group
    groups = {}
    for s in recent_sets:
        mg = _get_muscle_group(s.exercise_name)
        if mg == 'unknown':
            continue
        if mg not in groups:
            groups[mg] = []

        target_wt = getattr(s, 'target_weight', None)
        if target_wt and target_wt > 0 and s.weight > 0:
            days_ago = (_today - s.logged_date).days if s.logged_date else 7
            recency_weight = 2.0 if days_ago <= 7 else 1.0
            groups[mg].append((s.weight / target_wt) * recency_weight)

    # Compute and upsert
    for mg, scores in groups.items():
        if not scores:
            continue
        total_weight = sum(2.0 if i < len(scores) // 2 else 1.0 for i in range(len(scores)))
        avg_score = sum(scores) / total_weight if total_weight > 0 else 1.0

        if avg_score > 1.1:
            rel = 'strong'
        elif avg_score >= 0.9:
            rel = 'average'
        elif avg_score >= 0.7:
            rel = 'weak'
        else:
            rel = 'very_weak'

        profile = MuscleGroupProfile.query.filter_by(user_id=user_id, muscle_group=mg).first()
        if not profile:
            profile = MuscleGroupProfile(user_id=user_id, muscle_group=mg)
            db.session.add(profile)

        profile.strength_score = round(avg_score, 2)
        if not profile.user_flagged_weak:
            profile.relative_strength = rel
        elif avg_score >= 1.0 and len(scores) >= 6:
            # Auto-clear the flag once the user is meeting/beating targets with enough data.
            # 6 scored sets in a 14-day window = at least two solid sessions of sustained performance.
            profile.user_flagged_weak = False
            profile.relative_strength = rel
        profile.last_updated = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def generate_session_analysis(user_id, week, day_idx):
    """Generate post-session analysis after workout completion."""
    # Use user's local timezone, not server UTC
    try:
        from models import User
        from utils_time import user_local_now
        user = User.query.get(user_id)
        user_tz = user.timezone if user and user.timezone else 'UTC'
        today = user_local_now(user_tz).date()
    except Exception:
        today = date.today()

    # Get today's sets
    sets = SetLog.query.filter_by(
        user_id=user_id, week=week, day_idx=day_idx, done=True
    ).all()

    if not sets:
        return None

    # Analyze
    exercises = {}
    for s in sets:
        if s.exercise_name not in exercises:
            exercises[s.exercise_name] = []
        exercises[s.exercise_name].append(s)

    muscle_groups = list(set(_get_muscle_group(n) for n in exercises.keys()))

    deviations = []
    progressions = []
    total_sets = len(sets)
    completed_as_prescribed = 0

    for ex_name, ex_sets in exercises.items():
        for s in ex_sets:
            tw = getattr(s, 'target_weight', None)
            md = getattr(s, 'modification_direction', None)
            if md == 'as_prescribed' or md is None:
                completed_as_prescribed += 1
            elif md:
                deviations.append({
                    "exercise": ex_name,
                    "direction": md,
                    "target": tw,
                    "actual": s.weight,
                })

    compliance = (completed_as_prescribed / total_sets * 100) if total_sets > 0 else 0

    analysis = SessionAnalysis(
        user_id=user_id, week=week, day_idx=day_idx, log_date=today,
        overall_compliance=round(compliance, 1),
        muscle_groups_trained=muscle_groups,
        deviations=deviations,
        progression_applied=progressions,
        flags=[mg for mg in muscle_groups if mg == 'shoulders'],
    )

    # Generate summary text
    parts = [f"Session compliance: {round(compliance)}%."]
    if deviations:
        parts.append(f"{len(deviations)} exercise(s) modified from target.")
    parts.append(f"Muscle groups: {', '.join(muscle_groups)}.")
    analysis.summary_text = ' '.join(parts)

    db.session.add(analysis)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return analysis


def generate_weekly_summary(user_id, week):
    """Generate weekly training summary for coach context.
    Called every 7 days or on Sunday planning."""

    # Get all sessions this week
    analyses = SessionAnalysis.query.filter_by(
        user_id=user_id, week=week
    ).all()

    if not analyses:
        return {"week": week, "sessions": 0, "summary": "No sessions completed this week."}

    # Average compliance
    compliances = [a.overall_compliance for a in analyses if a.overall_compliance is not None]
    avg_compliance = sum(compliances) / len(compliances) if compliances else 0

    # Collect all muscle groups trained
    all_muscles = set()
    all_deviations = []
    all_flags = []
    for a in analyses:
        if a.muscle_groups_trained:
            all_muscles.update(a.muscle_groups_trained)
        if a.deviations:
            all_deviations.extend(a.deviations)
        if a.flags:
            all_flags.extend(a.flags)

    # Get muscle group profiles for progress assessment
    profiles = MuscleGroupProfile.query.filter_by(user_id=user_id).all()
    progressing = [p.muscle_group for p in profiles if p.strength_score and p.strength_score > 1.05]
    stalling = [p.muscle_group for p in profiles if p.strength_score and p.strength_score < 0.85]
    weak_flagged = [p.muscle_group for p in profiles if p.user_flagged_weak or p.relative_strength in ('weak', 'very_weak')]

    # Phase assessment
    phase = _get_phase(week)
    phase_names = {1: "Hypertrophy", 2: "Strength", 3: "Power"}

    # Build summary
    parts = []
    parts.append(f"Week {week} ({phase_names.get(phase, '?')} phase): {len(analyses)} sessions completed.")
    parts.append(f"Average compliance: {round(avg_compliance)}%.")

    if progressing:
        parts.append(f"Progressing: {', '.join(progressing)}.")
    if stalling:
        parts.append(f"Stalling: {', '.join(stalling)} — may need adjustment.")
    if weak_flagged:
        parts.append(f"Weak areas: {', '.join(weak_flagged)} — conservative progression active.")

    deviation_count = len(all_deviations)
    if deviation_count > 0:
        parts.append(f"{deviation_count} exercise modification(s) this week.")

    # Periodization assessment
    if avg_compliance >= 85:
        parts.append("On track with periodization plan.")
    elif avg_compliance >= 70:
        parts.append("Slightly behind plan — consistency needed.")
    else:
        parts.append("Behind plan — review obstacles this week.")

    summary_text = ' '.join(parts)

    return {
        "week": week,
        "phase": phase_names.get(phase, '?'),
        "sessions": len(analyses),
        "avg_compliance": round(avg_compliance),
        "muscles_trained": list(all_muscles),
        "progressing": progressing,
        "stalling": stalling,
        "weak_flagged": weak_flagged,
        "deviations": deviation_count,
        "summary": summary_text,
    }
