"""Adaptive training engine — computes exercise targets from performance data."""

import re
from datetime import date, datetime, timedelta, timezone
from models import db, SetLog, MuscleGroupProfile, SessionAnalysis, ExerciseCompletion, AppState


# Exercise → muscle group mapping (pulled from equipment_swaps at runtime)
def _get_muscle_group(exercise_name):
    """Get the muscle group for an exercise."""
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


def _get_progression_increment(exercise_name, muscle_group, is_weak):
    """Get the weight increment for progression."""
    if is_weak:
        return 2.5  # Conservative for weak muscle groups
    nl = exercise_name.lower()
    # Small isolation movements
    if any(k in nl for k in ['curl', 'raise', 'fly', 'extension', 'pushdown', 'face pull']):
        return 2.5
    return 5.0


def _get_configured_reps(exercise_name, week, day_idx):
    """Look up the configured rep count from workout data for this exercise."""
    try:
        from workout_data import get_workouts
        days = get_workouts(week)
        if day_idx < len(days):
            day = days[day_idx]
            for ex in day.get("exercises", []):
                if ex.get("name", "").lower() == exercise_name.lower():
                    m = re.match(r"(\d+)x(\d+)", ex.get("sets", ""))
                    if m:
                        return int(m.group(2))
    except Exception:
        pass
    return None


def _round_weight(weight, exercise_name):
    """Round to nearest 5 lbs (valid plate/dumbbell increments)."""
    if weight <= 0:
        return 0
    return round(weight / 5) * 5


def compute_next_targets(user_id, exercise_name, week, day_idx):
    """Compute targets for the next time this exercise appears.

    Returns: {
        target_weight: float,
        target_reps: int,
        target_sets: int,
        adjustment_reason: str,
        progression_indicator: str  ('up', 'hold', 'deload', 'weak', 'down')
    }
    """
    phase = _get_phase(week)
    muscle_group = _get_muscle_group(exercise_name)

    # Check muscle group strength
    profile = MuscleGroupProfile.query.filter_by(
        user_id=user_id, muscle_group=muscle_group
    ).first()
    is_weak = profile and (profile.user_flagged_weak or profile.relative_strength in ('weak', 'very_weak'))

    # Get last session data for this exercise
    last_sets = SetLog.query.filter_by(
        user_id=user_id, exercise_name=exercise_name, done=True
    ).order_by(SetLog.logged_date.desc(), SetLog.set_number.desc()).limit(20).all()

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

    # Get the most recent session's data
    last_date = last_sets[0].logged_date
    session_sets = [s for s in last_sets if s.logged_date == last_date]
    last_weight = session_sets[0].weight if session_sets else 0
    last_reps = session_sets[0].reps if session_sets else 0
    last_set_count = len(session_sets)

    # Check if user modified from target
    user_increased = any(getattr(s, 'modification_direction', None) == 'increased_weight' for s in session_sets)
    user_decreased = any(getattr(s, 'modification_direction', None) in ('decreased_weight', 'decreased_reps') for s in session_sets)
    sets_skipped = sum(1 for s in session_sets if getattr(s, 'set_skipped', False))

    # Avg reps across session
    avg_reps = sum(s.reps for s in session_sets if s.reps) / max(len(session_sets), 1)
    target_reps_last = getattr(session_sets[0], 'target_reps', None) or avg_reps
    exceeded_reps = avg_reps > target_reps_last + 1 if target_reps_last else False

    inc = _get_progression_increment(exercise_name, muscle_group, is_weak)

    # ─── SIGNAL 7: DELOAD WEEK ───
    if _is_deload(week):
        return {
            "target_weight": _round_weight(last_weight * 0.85, exercise_name),
            "target_reps": last_reps,
            "target_sets": max(last_set_count - 1, 2),
            "adjustment_reason": "Deload week — 85% weight, recovery focus",
            "progression_indicator": "deload",
        }

    # ─── SIGNAL 6: WEAK MUSCLE GROUP ───
    if is_weak and muscle_group == 'shoulders':
        # Shoulders: max +2.5/session, 12-15 rep range, need 3 good sessions
        good_sessions = _count_consecutive_good_sessions(user_id, exercise_name)
        if good_sessions >= 3:
            new_weight = _round_weight(last_weight + 2.5, exercise_name)
            return {
                "target_weight": new_weight,
                "target_reps": min(max(last_reps, 12), 15),
                "target_sets": last_set_count,
                "adjustment_reason": f"3 good sessions — +2.5 lb (shoulder: conservative)",
                "progression_indicator": "up",
            }
        return {
            "target_weight": _round_weight(last_weight, exercise_name),
            "target_reps": min(max(last_reps, 12), 15),
            "target_sets": last_set_count,
            "adjustment_reason": f"Shoulder work — holding ({good_sessions}/3 good sessions for increase)",
            "progression_indicator": "weak",
        }

    # ─── SIGNAL 2: USER INCREASED WEIGHT ───
    if user_increased:
        new_weight = _round_weight(last_weight + inc * 2, exercise_name)
        return {
            "target_weight": new_weight,
            "target_reps": last_reps,
            "target_sets": last_set_count,
            "adjustment_reason": "You went heavier last time — pushing further",
            "progression_indicator": "up",
        }

    # ─── SIGNAL 3: USER DECREASED ───
    if user_decreased:
        return {
            "target_weight": _round_weight(last_weight, exercise_name),
            "target_reps": last_reps,
            "target_sets": last_set_count,
            "adjustment_reason": "Reduced last session — holding weight",
            "progression_indicator": "hold",
        }

    # ─── SIGNAL 4: SETS SKIPPED ───
    if sets_skipped >= 2:
        return {
            "target_weight": _round_weight(last_weight, exercise_name),
            "target_reps": last_reps,
            "target_sets": max(last_set_count - 1, 2),
            "adjustment_reason": f"Skipped {sets_skipped} sets — volume reduced",
            "progression_indicator": "down",
        }

    # ─── SIGNAL 5: EXCEEDED REPS ───
    if exceeded_reps:
        new_weight = _round_weight(last_weight + inc, exercise_name)
        return {
            "target_weight": new_weight,
            "target_reps": {1: 10, 2: 6, 3: 4}.get(phase, 10),
            "target_sets": last_set_count,
            "adjustment_reason": f"Beat rep target — weight +{inc} lb",
            "progression_indicator": "up",
        }

    # ─── SIGNAL 1: STANDARD PROGRESSION BY PHASE ───
    if phase == 1:
        # Hypertrophy: increase reps, then bump weight
        # Cap at the workout's configured reps if available, otherwise 15
        configured_reps = _get_configured_reps(exercise_name, week, day_idx)
        phase_max_reps = configured_reps if configured_reps else 15
        if avg_reps >= phase_max_reps:
            new_weight = _round_weight(last_weight + inc, exercise_name)
            return {
                "target_weight": new_weight,
                "target_reps": configured_reps or 10,
                "target_sets": last_set_count,
                "adjustment_reason": f"Hit {int(avg_reps)} reps — weight +{inc} lb, reps reset to {configured_reps or 10}",
                "progression_indicator": "up",
            }
        target = min(int(avg_reps) + 1, phase_max_reps)
        return {
            "target_weight": _round_weight(last_weight, exercise_name),
            "target_reps": target,
            "target_sets": last_set_count,
            "adjustment_reason": f"Building reps: {int(avg_reps)} → {target}",
            "progression_indicator": "up" if avg_reps < phase_max_reps else "hold",
        }

    elif phase == 2:
        # Strength: increase weight every 1-2 sessions
        new_weight = _round_weight(last_weight + inc, exercise_name)
        return {
            "target_weight": new_weight,
            "target_reps": max(6, last_reps),
            "target_sets": last_set_count,
            "adjustment_reason": f"Strength phase — +{inc} lb",
            "progression_indicator": "up",
        }

    else:  # Phase 3
        # Power: aggressive increases
        new_weight = _round_weight(last_weight + inc, exercise_name)
        return {
            "target_weight": new_weight,
            "target_reps": max(4, last_reps),
            "target_sets": last_set_count,
            "adjustment_reason": f"Power phase — +{inc} lb, peak performance",
            "progression_indicator": "up",
        }


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

        # Don't override user_flagged_weak
        profile.strength_score = round(avg_score, 2)
        if not profile.user_flagged_weak:
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
