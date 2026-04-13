"""Prompt assembler for the 12Weeks coaching system.

Replaces the 22KB Jinja2 template with:
  1. Section builder registry — decorator pattern, one builder per data section
  2. CORE_PROMPT — ~400 token identity/rules string
  3. PROTOCOL_MAP — agent-specific protocol strings
  4. assemble_prompt() — combines CORE + protocol + formatted data sections

Section builders query models directly and call existing formatters from coach.py.
They do NOT duplicate the queries — they ARE the queries (moved from _build_coach_context).
"""

import logging
from datetime import date, timedelta, datetime

from flask_login import current_user

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section builder registry
# ---------------------------------------------------------------------------

_SECTION_BUILDERS = {}


def section_builder(name):
    """Register a section builder function by name."""
    def decorator(fn):
        _SECTION_BUILDERS[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Shared helpers (thin wrappers over app.py functions, imported lazily)
# ---------------------------------------------------------------------------

def _user_today():
    try:
        tz = current_user.timezone if hasattr(current_user, 'timezone') and current_user.timezone else 'UTC'
        from utils_time import user_local_now
        return user_local_now(tz).date()
    except Exception:
        return date.today()


def _current_week():
    try:
        from models import AppState
        s = AppState.query.filter_by(user_id=current_user.id).first()
        if s and s.start_date:
            diff_days = (_user_today() - s.start_date).days
            return min(12, max(1, diff_days // 7 + 1))
        return s.current_week if s else 1
    except Exception:
        return 1


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Section builders — one per agent.requires key
# ---------------------------------------------------------------------------

@section_builder("base")
def _build_base():
    from workout_data import get_phase, PHASES
    local_today = _user_today()
    week = _current_week()
    phase = get_phase(week)
    phase_info = PHASES[phase]
    return {
        "user_id": current_user.id,
        "week": week,
        "phase": phase_info,
        "athlete_name": current_user.name or "Athlete",
        "user_timezone": getattr(current_user, 'timezone', 'UTC') or 'UTC',
        "local_today": local_today,
        "today_idx": local_today.weekday(),
    }


@section_builder("checkins")
def _build_checkins():
    from models import MorningCheckIn
    since = _user_today() - timedelta(days=14)
    rows = MorningCheckIn.query.filter(
        MorningCheckIn.user_id == current_user.id,
        MorningCheckIn.log_date >= since
    ).order_by(MorningCheckIn.log_date).all()
    return {"checkins": [{
        "date": e.log_date.isoformat(), "sleep_quality": e.sleep_quality,
        "stress_level": e.stress_level, "soreness": e.soreness,
        "mood": e.mood, "motivation": e.motivation,
        "anxiety": e.anxiety, "notes": e.notes,
    } for e in rows]}


@section_builder("chat_history")
def _build_chat_history():
    from models import ChatMessage
    local_today = _user_today()
    week_start = local_today - timedelta(days=local_today.weekday())
    # Today's messages (most relevant, limit 20 to prevent bloat from planning retries)
    today_msgs = [{
        "role": m.role, "content": m.content,
        "date": m.log_date.isoformat() if m.log_date else None,
        "time": m.created_at.isoformat() if m.created_at else None,
    } for m in ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= local_today
    ).order_by(ChatMessage.created_at.desc()).limit(20).all()][::-1]  # reverse to chronological
    # Earlier this week (limit 15)
    earlier_week = [{
        "role": m.role, "content": m.content,
        "date": m.log_date.isoformat() if m.log_date else None,
        "time": m.created_at.isoformat() if m.created_at else None,
    } for m in ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= week_start,
        ChatMessage.log_date < local_today
    ).order_by(ChatMessage.created_at.desc()).limit(15).all()][::-1]
    # Older context (last week, limit 10 — memories carry the rest)
    older = [{
        "role": m.role, "content": m.content,
        "date": m.log_date.isoformat() if m.log_date else None,
    } for m in ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date < week_start
    ).order_by(ChatMessage.created_at.desc()).limit(10).all()][::-1]
    return {"chat_history": older + earlier_week + today_msgs}


@section_builder("bodyweight")
def _build_bodyweight():
    from models import BodyWeight
    rows = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date).all()
    entries = [{"date": e.log_date.isoformat(), "weight": e.weight_lbs} for e in rows]
    return {"bodyweight": entries[-14:]}


@section_builder("garmin")
def _build_garmin():
    from garmin_client import GarminClient
    from overtraining import assess_readiness
    gc = GarminClient(user_id=current_user.id)
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    garmin_data = gc.get_today_summary() if gc.connected else None
    readiness = assess_readiness(garmin_data) if garmin_data else None
    return {"garmin": garmin_data, "readiness": readiness}


@section_builder("workout_today")
def _build_workout_today():
    from workout_data import get_workouts
    from models import WeeklyPrescription, WeeklyMealPlan, WeeklyRunPlan, WeeklyWarmup
    local_today = _user_today()
    week = _current_week()
    today_idx = local_today.weekday()
    workouts = get_workouts(week)
    wt = workouts[today_idx] if today_idx < len(workouts) else None
    # Overlay DB prescriptions + apply exercise swaps
    try:
        rx_rows = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).order_by(WeeklyPrescription.exercise_order).all()
        if rx_rows and wt:
            # Load exercise swaps for this day
            from models import ExerciseSwap
            swaps = {}
            try:
                swap_rows = ExerciseSwap.query.filter_by(
                    user_id=current_user.id, week=week, day_idx=today_idx
                ).all()
                for sw in swap_rows:
                    swaps[sw.exercise_idx] = sw.swapped_to
            except Exception:
                pass
            exercises = []
            for i, rx in enumerate(rx_rows):
                name = swaps.get(i, rx.exercise_name)
                exercises.append({
                    "name": name, "sets": f"{rx.sets}x{rx.reps}",
                    "rest": rx.rest or "60s", "note": rx.note or "",
                    "target_weight": getattr(rx, 'target_weight', None),
                })
            wt["exercises"] = exercises
    except Exception:
        pass
    try:
        mp = WeeklyMealPlan.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).order_by(WeeklyMealPlan.id.desc()).first()
        if mp and mp.meal_data and wt:
            wt["mealPlan"] = mp.meal_data
    except Exception:
        pass
    try:
        rp = WeeklyRunPlan.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).first()
        if rp and wt:
            wt["run"] = {"type": rp.run_type, "label": rp.label,
                         "time": rp.duration, "detail": rp.detail or ""}
    except Exception:
        pass
    try:
        wu = WeeklyWarmup.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).first()
        if wu and wu.warmup_data and wt:
            wt["warmup"] = wu.warmup_data
    except Exception:
        pass
    return {"workout_today": wt}


@section_builder("week_schedule")
def _build_week_schedule():
    from models import WeeklyDaySchedule
    from workout_data import get_workouts
    week = _current_week()
    rows = WeeklyDaySchedule.query.filter_by(
        user_id=current_user.id, week=week
    ).order_by(WeeklyDaySchedule.day_idx).all()
    if rows:
        schedule = [{"day_idx": ds.day_idx,
                     "day": DAY_NAMES[ds.day_idx] if ds.day_idx < 7 else "?",
                     "liftName": ds.lift_name or "Rest",
                     "isRest": ds.is_rest or False} for ds in rows]
    else:
        workouts = get_workouts(week)
        schedule = [{"day_idx": i, "day": DAY_NAMES[i],
                     "liftName": w.get("liftName", "Rest"),
                     "isRest": w.get("isRest", False)} for i, w in enumerate(workouts)]
    return {"week_schedule": schedule}


@section_builder("exercise_history")
def _build_exercise_history():
    from models import ExerciseLog
    from workout_data import resolve_name
    rows = ExerciseLog.query.filter_by(user_id=current_user.id).order_by(
        ExerciseLog.logged_date.desc(), ExerciseLog.id.desc()
    ).limit(200).all()
    history = {}
    for log in rows:
        canonical = resolve_name(log.exercise_name)
        if canonical not in history:
            history[canonical] = []
        if len(history[canonical]) < 3:
            entry = {"weight": log.weight, "rpe": log.rpe,
                     "reps_completed": log.reps_completed,
                     "week": log.week,
                     "date": log.logged_date.isoformat() if log.logged_date else None}
            if log.estimated_1rm:
                entry["estimated_1rm"] = log.estimated_1rm
            history[canonical].append(entry)
    return {"exercise_history": history}


@section_builder("exercise_analysis")
def _build_exercise_analysis():
    """Read pre-computed analysis from WeeklyPrescription (set by training engine during
    program generation). Falls back to live compute_next_targets only if no prescriptions exist."""
    from models import WeeklyPrescription
    from workout_data import resolve_name
    week = _current_week()
    today_idx = _user_today().weekday()
    analysis = {}
    # Read from pre-generated prescriptions (authoritative)
    rx_list = WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=week
    ).all()
    if rx_list:
        for rx in rx_list:
            name = resolve_name(rx.exercise_name)
            if name not in analysis and getattr(rx, 'target_weight', None):
                analysis[name] = {
                    "target_weight": rx.target_weight,
                    "target_reps": int(rx.reps) if rx.reps and rx.reps.isdigit() else 10,
                    "target_sets": rx.sets,
                    "adjustment_reason": getattr(rx, 'adjustment_reason', '') or '',
                    "progression_indicator": getattr(rx, 'progression_indicator', 'hold') or 'hold',
                    "coach_alert": None,
                }
    # Fallback: if no prescriptions, compute live
    if not analysis:
        try:
            from models import ExerciseLog
            from training_engine import compute_next_targets
            rows = ExerciseLog.query.filter_by(user_id=current_user.id).order_by(
                ExerciseLog.logged_date.desc()
            ).limit(200).all()
            names = set(resolve_name(log.exercise_name) for log in rows)
            for ex_name in names:
                try:
                    result = compute_next_targets(current_user.id, ex_name, week, today_idx)
                    analysis[ex_name] = {
                        "target_weight": result.get("target_weight"),
                        "target_reps": result.get("target_reps"),
                        "target_sets": result.get("target_sets"),
                        "adjustment_reason": result.get("adjustment_reason", ""),
                        "progression_indicator": result.get("progression_indicator", "hold"),
                        "coach_alert": result.get("coach_alert"),
                    }
                except Exception:
                    pass
        except Exception:
            pass
    return {"exercise_analysis": analysis}


@section_builder("today_sets")
def _build_today_sets():
    from models import SetLog
    from workout_data import resolve_name
    local_today = _user_today()
    today_idx = local_today.weekday()  # Mon=0, Sun=6
    week = _current_week()
    # Filter by SCHEDULED day (week + day_idx), not logged_date.
    # User might log Thursday's workout on Sunday — logged_date is Sunday
    # but day_idx is 3 (Thursday). We only want TODAY's scheduled sets.
    rows = SetLog.query.filter(
        SetLog.user_id == current_user.id,
        SetLog.week == week,
        SetLog.day_idx == today_idx,
        SetLog.done == True  # noqa: E712
    ).order_by(SetLog.exercise_name, SetLog.set_number).all()
    set_data = {}
    for s in rows:
        canonical = resolve_name(s.exercise_name)
        if canonical not in set_data:
            set_data[canonical] = []
        set_data[canonical].append({
            "set": s.set_number + 1, "weight": s.weight,
            "reps": s.reps, "done": s.done,
            "target_weight": getattr(s, 'target_weight', None),
            "target_reps": getattr(s, 'target_reps', None),
            "modification_direction": getattr(s, 'modification_direction', None),
        })
    return {"today_sets": set_data}


@section_builder("runs")
def _build_runs():
    from models import RunLog
    rows = RunLog.query.filter_by(user_id=current_user.id).order_by(
        RunLog.log_date.desc()
    ).limit(14).all()
    return {"run_history": [{
        "date": r.log_date.isoformat() if r.log_date else None,
        "distance_miles": r.distance_miles, "avg_hr": r.avg_hr,
        "elevation_ft": r.elevation_ft, "week": r.week,
    } for r in rows]}


@section_builder("physical")
def _build_physical():
    from models import PhysicalAssessment, BodyMeasurement
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    physical = None
    if pa:
        physical = {
            "height_inches": pa.height_inches, "bodyweight_lbs": pa.bodyweight_lbs,
            "waist": pa.waist_inches, "chest": pa.chest_inches,
            "bicep": pa.bicep_inches, "thigh": pa.thigh_inches,
            "neck": pa.neck_inches, "hips": pa.hips_inches,
            "pushups": pa.pushup_count, "plank_sec": pa.plank_seconds,
            "squats": pa.squat_count, "pullups": pa.pullup_count,
        }
    recent = BodyMeasurement.query.filter_by(
        user_id=current_user.id
    ).order_by(BodyMeasurement.log_date.desc()).limit(4).all()
    measurements = [{"date": m.log_date.isoformat(), "waist": m.waist_inches} for m in recent] if recent else []
    return {"physical_assessment": physical, "body_measurements": measurements}


@section_builder("equipment")
def _build_equipment():
    from models import UserEquipment
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    return {"equipment": eq.available_equipment if eq else []}


@section_builder("meals_today")
def _build_meals_today():
    from models import MealLog
    local_today = _user_today()
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=local_today).first()
    meals_today = None
    if ml:
        meals_today = {
            "eaten": ml.eaten or [], "fasting": ml.fasting,
            "scheduled_time": getattr(ml, 'scheduled_time', None),
            "actual_time": getattr(ml, 'actual_time', None),
        }
    # Weekly meals summary
    week_monday = local_today - timedelta(days=local_today.weekday())
    week_meals = MealLog.query.filter(
        MealLog.user_id == current_user.id,
        MealLog.log_date >= week_monday,
        MealLog.log_date <= local_today
    ).all()
    weekly = []
    for entry in week_meals:
        eaten_count = len(entry.eaten) if isinstance(entry.eaten, list) else 0
        weekly.append({
            "date": entry.log_date.isoformat(),
            "day": DAY_NAMES[entry.log_date.weekday()] if entry.log_date.weekday() < 7 else "?",
            "meals_logged": eaten_count,
        })
    # Today's meal plan (from workout_today context if available)
    return {"meals_today": meals_today, "weekly_meals_summary": weekly}


@section_builder("fasting")
def _build_fasting():
    from models import TrainingGoal, MealPlanOverride, WeeklyMealPlan
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    fasting_protocol = goal.fasting_protocol if goal else "16_8"
    local_today = _user_today()
    week = _current_week()
    today_idx = local_today.weekday()
    fasting_state = None
    try:
        from meal_generator import _FASTING_PROTOCOLS
        proto = _FASTING_PROTOCOLS.get(fasting_protocol, _FASTING_PROTOCOLS["16_8"])
        eating_end = proto["end"]
        end_parts = eating_end.replace("am", "").replace("pm", "")
        end_h = int(end_parts.split(":")[0])
        end_m = int(end_parts.split(":")[1]) if ":" in end_parts else 0
        if "pm" in eating_end and end_h != 12:
            end_h += 12
        # Look back for last eating day
        last_eating_day = None
        for lookback in range(7):
            check_date = local_today - timedelta(days=lookback)
            check_idx = check_date.weekday()
            day_meal_type = _get_day_meal_type_local(current_user.id, week, check_idx)
            if day_meal_type != 'fast_day':
                if lookback == 0:
                    break
                last_eating_day = check_date
                break
        if last_eating_day:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from pytz import timezone as _ptz
                class ZoneInfo:
                    def __new__(cls, key):
                        return _ptz(key)
            _tz_str = current_user.timezone if hasattr(current_user, 'timezone') and current_user.timezone else 'UTC'
            last_meal_time = datetime(last_eating_day.year, last_eating_day.month,
                                     last_eating_day.day, end_h, end_m, tzinfo=ZoneInfo(_tz_str))
            now = datetime.now()
            try:
                from utils_time import user_local_now
                _tz = current_user.timezone if hasattr(current_user, 'timezone') and current_user.timezone else 'UTC'
                now = user_local_now(_tz)
            except Exception:
                pass
            hours_fasted = (now - last_meal_time).total_seconds() / 3600
            fasting_state = {
                "hours_fasted": round(hours_fasted, 1),
                "last_meal_day": last_eating_day.strftime("%A"),
                "last_meal_time": eating_end,
                "eating_window_opens": proto["start"],
                "is_expected": True,
            }
    except Exception:
        pass
    # Today's meal type
    today_meal_type = _get_day_meal_type_local(current_user.id, week, today_idx)
    # On fast days, override the eating window — there is none
    if today_meal_type == 'fast_day' and fasting_state:
        fasting_state["eating_window_opens"] = "NONE — full fast day, no eating window"
        fasting_state["is_fast_day"] = True
    return {
        "fasting_protocol": fasting_protocol,
        "fasting_state": fasting_state,
        "today_meal_type": today_meal_type,
    }


def _get_day_meal_type_local(user_id, week, day_idx):
    """Get actual meal type for a day — DB first, template fallback."""
    try:
        from models import MealPlanOverride, WeeklyMealPlan
        override = MealPlanOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if override and override.meal_type:
            return override.meal_type
        wmp = WeeklyMealPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if wmp and wmp.day_type:
            return wmp.day_type
    except Exception:
        pass
    from workout_data import DAY_MEAL_TYPES
    return DAY_MEAL_TYPES.get(DAY_NAMES[day_idx] if day_idx < 7 else "Mon", "moderate")


@section_builder("food_safety")
def _build_food_safety():
    from models import UserConstraints, UserFoodSelections
    constraints = UserConstraints.query.filter_by(user_id=current_user.id).first()
    food_restrictions = constraints.food_restrictions if constraints else []
    custom_allergies = constraints.custom_allergies if constraints else None
    schedule_notes = constraints.schedule_notes if constraints else None
    # Scheduled activities
    scheduled_activities = ""
    if constraints and constraints.scheduled_activities:
        lines = ["Scheduled activities this athlete has committed to:"]
        for a in constraints.scheduled_activities:
            lines.append(f"  - {a.get('day', '?')}: {a.get('activity', '?')} ({a.get('duration_min', '?')} min)")
        scheduled_activities = "\n".join(lines)
    # Selected foods
    fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()
    selected_foods = fs.selected_foods if fs else None
    return {
        "food_restrictions": food_restrictions,
        "custom_allergies": custom_allergies,
        "selected_foods": selected_foods,
        "schedule_notes": schedule_notes,
        "scheduled_activities": scheduled_activities,
    }


@section_builder("goal")
def _build_goal():
    from models import TrainingGoal
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not goal:
        return {"goal": None}
    return {"goal": {
        "goal_type": goal.goal_type, "target_weight": goal.target_weight,
        "target_bf_pct": goal.target_bf_pct, "daily_calories": goal.daily_calories,
        "protein_grams": goal.protein_grams, "carb_grams": goal.carb_grams,
        "fat_grams": goal.fat_grams, "fasting_protocol": goal.fasting_protocol,
        "calorie_by_day_type": goal.calorie_by_day_type,
    }}


@section_builder("coach_memories")
def _build_coach_memories():
    from models import CoachMemory
    rows = CoachMemory.query.filter_by(user_id=current_user.id).order_by(
        CoachMemory.created_at.desc()
    ).limit(50).all()
    return {"coach_memories": [{"type": m.memory_type, "content": m.content, "week": m.week} for m in rows]}


@section_builder("user_rules")
def _build_user_rules():
    from models import CoachRule
    rows = CoachRule.query.filter_by(user_id=current_user.id, active=True).order_by(
        CoachRule.created_at
    ).limit(25).all()
    return {"user_rules": [{"rule_text": r.rule_text, "category": r.category} for r in rows]}


@section_builder("completed_days")
def _build_completed_days():
    from models import DayCompletion, SetLog
    from workout_data import get_workouts
    local_today = _user_today()
    week = _current_week()
    week_monday = local_today - timedelta(days=local_today.weekday())
    completed = []
    # DayCompletion records
    for dc in DayCompletion.query.filter_by(user_id=current_user.id, week=week).all():
        if dc.done and dc.day_idx not in completed:
            completed.append(dc.day_idx)
    # SetLog by date range
    week_sets = SetLog.query.filter(
        SetLog.user_id == current_user.id,
        SetLog.done == True,  # noqa: E712
        SetLog.logged_date >= week_monday
    ).all()
    for s in week_sets:
        if s.day_idx not in completed:
            completed.append(s.day_idx)
        if s.logged_date and s.logged_date >= week_monday and s.logged_date <= local_today:
            if s.day_idx not in completed:
                completed.append(s.day_idx)
    # Enrich with names
    workouts = get_workouts(week)
    enriched = []
    for di in completed:
        entry = {"day_idx": di, "day": DAY_NAMES[di] if di < 7 else "?"}
        if di < len(workouts):
            entry["liftName"] = workouts[di].get("liftName", "")
        enriched.append(entry)
    return {"completed_days_this_week": enriched}


@section_builder("overrides")
def _build_overrides():
    from models import WeeklyScheduleOverride, MealPlanOverride, RunOverride, ExerciseSwap
    week = _current_week()
    uid = current_user.id
    result = {}
    try:
        result["schedule_overrides"] = [
            {"day_idx": o.day_idx, "workout_time": o.workout_time, "skip_day": o.skip_day, "notes": o.notes}
            for o in WeeklyScheduleOverride.query.filter_by(user_id=uid, week=week).all()]
    except Exception:
        result["schedule_overrides"] = []
    try:
        result["meal_overrides"] = [
            {"day_idx": o.day_idx, "meal_type": o.meal_type, "reason": o.reason}
            for o in MealPlanOverride.query.filter_by(user_id=uid, week=week).all()]
    except Exception:
        result["meal_overrides"] = []
    try:
        result["run_overrides"] = [
            {"day_idx": o.day_idx, "duration": o.duration, "run_type": o.run_type, "reason": o.reason}
            for o in RunOverride.query.filter_by(user_id=uid, week=week).all()]
    except Exception:
        result["run_overrides"] = []
    try:
        result["active_swaps"] = [
            {"day_idx": o.day_idx, "exercise_idx": o.exercise_idx, "swapped_to": o.swapped_to}
            for o in ExerciseSwap.query.filter_by(user_id=uid, week=week).all()]
    except Exception:
        result["active_swaps"] = []
    return result


@section_builder("next_week")
def _build_next_week():
    from models import WeeklyPrescription
    week = _current_week()
    next_week = week + 1
    if next_week > 12:
        return {"next_week_prescriptions": []}
    rows = WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=next_week
    ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()
    return {"next_week_prescriptions": [
        {"day_idx": rx.day_idx, "exercise": rx.exercise_name,
         "sets": rx.sets, "reps": rx.reps, "rest": rx.rest,
         "target_weight": getattr(rx, 'target_weight', None),
         "adjustment_reason": getattr(rx, 'adjustment_reason', None),
         "progression_indicator": getattr(rx, 'progression_indicator', None)}
        for rx in rows
    ]}


@section_builder("session_analysis")
def _build_session_analysis():
    from models import SessionAnalysis
    latest = SessionAnalysis.query.filter_by(
        user_id=current_user.id
    ).order_by(SessionAnalysis.log_date.desc()).first()
    sa = None
    if latest:
        sa = {
            "date": latest.log_date.isoformat() if latest.log_date else None,
            "compliance": latest.overall_compliance,
            "muscles": latest.muscle_groups_trained,
            "deviations": latest.deviations,
            "summary": latest.summary_text,
        }
    weekly_summary = None
    try:
        from training_engine import generate_weekly_summary
        weekly_summary = generate_weekly_summary(current_user.id, _current_week())
    except Exception:
        pass
    return {"session_analysis": sa, "weekly_summary": weekly_summary}


@section_builder("missed_checkin")
def _build_missed_checkin():
    from models import MorningCheckIn
    mc = MorningCheckIn.query.filter_by(user_id=current_user.id, log_date=_user_today()).first()
    missed = bool(mc and mc.notes and '[MISSED]' in (mc.notes or ''))
    return {"missed_checkin_today": missed}


@section_builder("intake")
def _build_intake():
    from models import PsychIntake
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    return {"intake_report": intake.report if intake and intake.report else None}


@section_builder("supplements")
def _build_supplements():
    from models import SupplementLog
    rows = SupplementLog.query.filter_by(user_id=current_user.id, log_date=_user_today()).all()
    return {"supplements_today": {"taken": {s.supplement_name: s.taken for s in rows}}}


# ---------------------------------------------------------------------------
# build_filtered_context — calls only the builders an agent needs
# ---------------------------------------------------------------------------

def build_filtered_context(agent_name):
    """Look up agent.requires, call only those builders, merge results."""
    from coach_agents import AGENTS
    agent = AGENTS.get(agent_name)
    if not agent:
        log.warning("Unknown agent: %s — falling back to conversation", agent_name)
        agent = AGENTS["conversation"]
    requires = agent.get("requires", ["base"])
    ctx = {}
    for section_name in requires:
        builder = _SECTION_BUILDERS.get(section_name)
        if builder:
            try:
                fragment = builder()
                ctx.update(fragment)
            except Exception as e:
                log.warning("Section builder '%s' failed: %s", section_name, e)
        else:
            log.warning("No section builder registered for '%s'", section_name)
    return ctx


# ---------------------------------------------------------------------------
# CORE_PROMPT — the ~400 token identity/rules core (replaces 22KB template)
# ---------------------------------------------------------------------------

CORE_PROMPT = """\
<identity>
You are Coach Erik. The athlete is {athlete_name}.
Vince Lombardi's standards. Nick Saban's process obsession. Zero tolerance for excuses.
Intensity level: {anger_level_label}
{anger_level_instruction}
</identity>

<non_negotiable_rules>
1. DATA FIRST — Every claim must cite a number from <athlete_data>. Never invent stats.
2. NO SYCOPHANCY — Banned phrases (NEVER use these or close variants):
   "great job", "good job", "amazing", "awesome", "love that", "love it",
   "proud of you", "I'm proud", "you're crushing it", "killing it", "nailed it",
   "way to go", "you got this", "keep it up", "fantastic", "incredible",
   "that's huge", "respect", "well done", "good for you", "happy to hear",
   "glad to hear", "nice work", "solid work", "beautiful", "perfect".
   Do NOT validate feelings. Do NOT cheerlead. Do NOT mirror enthusiasm.
   Acknowledgment is allowed only when tied to a measurable number — and even then
   it's flat: "Hit target. Next." not "Crushed it!"
3. NO EMOTIONAL VALIDATION — Do not say "that makes sense", "I hear you",
   "that's understandable", "totally fair". The athlete didn't hire a therapist,
   they hired a coach. Reflect data, not feelings.
4. DIRECTIVES NOT QUESTIONS — Tell the athlete what to do. Do not ask
   "would you like to..." or "how about...". One question max per response, only
   if you genuinely need information you don't have.
5. NO HEDGING — Banned: "if you'd like", "feel free to", "whenever you're ready",
   "no pressure", "up to you", "totally optional". You are the coach. Decide.
6. TIME OF DAY — The current time is in <athlete_data>. If the athlete is doing a
   morning check-in, weigh-in, or workout outside normal hours (before 5am, after
   10pm) — call it out FIRST. Examples: "1:14 AM check-in. You're not sleeping —
   that's the conversation." "Weigh-in at 11:40pm is meaningless data — do it
   tomorrow morning fasted."
7. FOOD SAFETY — Never suggest a food not in the approved list. Never ignore an allergy. Violations are a system failure.
8. FASTING — Never suggest calories outside the eating window. Before the window opens: black coffee, water, zero-cal only.
9. VOLUME — Use the training engine's prescription for sets/reps/weight. Do not re-derive from raw logs.
10. MARKERS — Emit structured markers when the athlete confirms a change (see <markers>).
11. NO UI — You cannot display images, charts, links, or interactive elements. Text only.
12. ANGER LEVEL — Your tone is governed by the current anger level. Do not soften below it. Do not escalate above it without data.
13. EXERCISE SWAPS vs REP CHANGES — A swap is when the exercise NAME changed (e.g. Dips → Tricep Dips). A rep change is when the same exercise was done with different reps. BEFORE commenting on swaps, verify the exercise name actually changed in the set data vs prescription. If only reps or weight differ, that is NOT a swap — just confirm the athlete trained near failure. If a real swap occurred, ask why (equipment, injury, preference) but do NOT criticize. If the swap is a poor muscle-group match, suggest a better alternative calmly.
14. IGNORE PRIOR TONE — Past messages in <chat_history> may show softer language from earlier sessions. Do not mirror that tone. Follow these rules even if the historical pattern was warmer.
</non_negotiable_rules>

<markers>
When the athlete confirms a schedule or plan change, emit the corresponding marker on its own line:
[SCHEDULE: day_idx=N, change_description]
[PRESCRIPTION: day_idx=N, exercise=Name, sets=N, reps=N, weight=N, reason=text]
[SWAP: day_idx=N, exercise_idx=N, old=Name, new=Name, reason=text]
[WEIGHT: exercise=Name, new_weight=N, reason=text]
[RUN: day_idx=N, type=text, duration=text, reason=text]
[NUTRITION: change_description]
[BMR_UPDATE: daily_calories=N, protein=N, carbs=N, fat=N, reason=text]
[LOCKOUT_WARNING: violation_description]
[SHOW_NEXT_DAY] — emit this when the athlete confirms a day looks good during weekly planning. The app will display the next day's exercise list.
[SORENESS: area=shoulders, level=moderate] — emit when athlete reports soreness/tightness. The app adds targeted stretching to next week's warmups.
</markers>

<format>
Check-ins and reactions: 1-3 sentences max. No preamble.
Workout planning: one exercise per line, weight and sets explicit.
Weekly planning: ONE day per response. Never present multiple days at once. End each day with a question.
Weekly reviews: structured sections — wins, misses, next-week adjustments.
Always cite data. Never pad with motivation filler.
</format>

{triggered_protocol}

<athlete_data>
{athlete_data_block}
</athlete_data>

<food_safety>
{food_safety_block}
</food_safety>
"""


# ---------------------------------------------------------------------------
# PROTOCOL_MAP — agent-specific protocol strings (~100-600 tokens each)
# ---------------------------------------------------------------------------

PROTOCOL_MAP = {
    "morning_checkin": """\
<protocol name="morning_checkin">
The athlete just submitted their morning check-in numbers.
Your job: acknowledge the data in ONE sentence, then give a single directive for the day.

Rules:
- TIME CHECK FIRST: Look at the current time in <athlete_data>. If it's before
  5:00 AM or after 10:00 AM, that's NOT a normal morning check-in time.
  - Before 5 AM: "1:14 AM check-in means you're not sleeping. The check-in numbers
    don't matter — sleep does. Get back to bed. We'll talk in the morning."
  - 5-10 AM: normal, proceed.
  - After 10 AM: "10:30 AM check-in is late. Half the day's plan is already
    compromised. Tomorrow, before 8 AM."
- Lead with the most notable data point (sleep drop, anxiety spike, soreness change).
- If garmin data is available, cross-reference HRV/sleep with self-report.
- If data is unremarkable, say so: "Numbers are steady. Here's today."
- State today's workout and first meal time.
- If they missed yesterday's check-in, name it. No lecture.
- 2-3 sentences maximum. No questions. No "thanks for checking in."
</protocol>""",

    "morning_briefing": """\
<protocol name="morning_briefing">
Auto-generated morning briefing. The athlete did NOT speak — this is a push notification.
Your job: one tight paragraph covering today's plan.

Rules:
- Open with the day and workout name.
- State the run type and duration.
- State first meal time from the meal plan.
- If garmin shows a readiness flag, name it and state the adaptation (e.g., "HRV dipped — we hold weight today").
- If it's a rest day, say so and name tomorrow's workout.
- No greeting. No "good morning." Just the briefing.
- 2-4 sentences max.
</protocol>""",

    "workout_feedback": """\
<protocol name="workout_feedback">
The athlete just finished logging their workout sets.
Your job: compare actual performance to prescribed targets, then give one forward-looking directive.

Rules:
- Compare each exercise: prescribed weight/reps vs actual weight/reps.
- Use the exercise analysis (progression_indicator) to contextualize: was this a PROGRESS, HOLD, or DELOAD day?
- If they hit all targets: "Prescription met." + what's next.
- If they exceeded targets: name the lift and the delta. One sentence.
- If they fell short: name the lift, the gap, and whether it's a concern or expected variance.
- State tomorrow's workout at the end.
- No "proud of you." No "great session." Just the data.
- 3-5 sentences.
</protocol>""",

    "weekly_review": """\
<protocol name="weekly_review">
End-of-week review. Summarize the full training week.

Rules:
- WINS: List completed workouts, PRs, compliance streaks. Cite specific numbers.
- MISSES: List missed workouts, skipped meals, incomplete days. Name the day and what was missed.
- BODY: Weight trend this week. Waist measurement if available. Compare to goal trajectory.
- MOOD: Summarize check-in trends (mood, sleep, anxiety). Flag any concerning patterns.
- GRADE: Give a single word assessment — COMPLIANT, PARTIAL, or OFF-TRACK.
- NEXT WEEK: Preview the upcoming week's focus. Name any adjustments made by the training engine.
- Do NOT re-derive progression — use the engine's next_week_prescriptions.
- Structured format with headers. 8-15 sentences total.
</protocol>""",

    "weekly_planning": """\
<protocol name="weekly_planning">
Weekly planning is a CONVERSATION. The app displays exercise lists — you do NOT list exercises.

Rules:
- First response: 2-3 sentence overview of changes (calories, weight, progression highlights).
  End with "Ready to see Monday?"
- The app shows the exercise list when the athlete is ready. You do NOT list exercises ever.
- After each day is shown, ask ONE question: any swaps or weight adjustments?
  Do NOT mention the next day until the athlete says they're good.
- When the athlete confirms a day looks good WITH NO CHANGES (e.g. "looks good", "no changes"),
  respond briefly and emit [SHOW_NEXT_DAY] on its own line. The app will display the next day.
  Example: "Monday locked in. [SHOW_NEXT_DAY]"
- If the athlete requests ANY change (swap, weight adjustment, etc.):
  1. Acknowledge the change
  2. Ask "Anything else for [this day]?" — do NOT emit [SHOW_NEXT_DAY]
  3. Only emit [SHOW_NEXT_DAY] when the athlete explicitly says no more changes
- NEVER emit [SHOW_NEXT_DAY] in the same response as acknowledging a change.
- After all 6 days, summarize the week.
- NEVER list exercises. The app handles all exercise display.
- One question per response. Never ask about two things at once.
</protocol>""",

    "meals_complete": """\
<protocol name="meals_complete">
The athlete just logged all their meals for the day.
Your job: compare actual intake to the meal plan, then give one directive.

Rules:
- State meals eaten vs meals planned.
- If it's a fasting day, confirm the fast was held.
- If they hit protein target: acknowledge in one clause.
- If they missed protein target: name the gap in grams.
- If off-plan foods were eaten: name them. No lecture. State the calorie impact.
- One sentence on tomorrow's meal plan type (heavy lift, rest, fast, etc.).
- 2-3 sentences max.
</protocol>""",

    "end_of_day": """\
<protocol name="end_of_day">
End-of-day summary. The athlete is done for the day.
Your job: state what was completed, what's tomorrow.

Rules:
- Name what was completed today (workout, meals, run).
- Name anything incomplete (skipped workout, missing meals).
- State tomorrow's workout name and type.
- If tomorrow is a rest day, say so.
- No reflection. No "you should feel good." Just status and what's next.
- 2-3 sentences max.
</protocol>""",

    "freeform": """\
<protocol name="freeform">
The athlete is having a free conversation. No specific trigger.
Your job: answer their question or respond to their statement using the full athlete context.

Rules:
- If they ask about their plan, cite the prescription data.
- If they ask about progress, cite body weight trend and exercise history.
- If they're venting or struggling, acknowledge briefly then redirect to action.
- If they're making excuses, name the excuse and redirect to the commitment.
- If they ask to change something, confirm the change and emit the appropriate marker.
- Check coach_memories before making any compliance judgment — they may have a granted exception.
- Check user_rules — the athlete may have corrected a previous coaching behavior.
- Match the anger level in your tone. Do not soften.
- Length varies by topic. Default to concise.
</protocol>""",

    "conversation": """\
<protocol name="conversation">
General conversation mode. The athlete sent a message outside a specific trigger flow.
Behave as in freeform: respond to what they said, using full context.

Rules:
- Check coach_memories before compliance judgments.
- Check user_rules for corrections to your behavior.
- If they report completing something, acknowledge and emit the marker.
- If they ask a question, answer directly with data.
- Match the anger level. Stay concise.
</protocol>""",

    "chat_opened": """\
<protocol name="chat_opened">
The athlete just opened the chat. No message yet — this is your opener.
Your job: give a status-aware greeting in 1-2 sentences.

Rules:
- If morning check-in is missing, prompt for it.
- If workout is incomplete, name it.
- If meals aren't logged, mention it.
- If everything is on track, say so and ask what they need.
- If they're in an active fast, acknowledge the fasting state.
- No generic greetings. Context-specific only.
- 1-2 sentences max.
</protocol>""",

    "crisis": """\
<protocol name="crisis">
The athlete expressed something that suggests emotional crisis or severe mental health distress.
Your job: be human first, coach second.

Rules:
- Acknowledge what they said. Do not minimize.
- Do not pivot to training.
- If they mention self-harm or suicidal ideation, provide the 988 Suicide & Crisis Lifeline number.
- Keep your response warm but grounded. No toxic positivity.
- Ask one open-ended question to keep them talking.
- 2-4 sentences max.
</protocol>""",
}


# ---------------------------------------------------------------------------
# _format_athlete_data — builds <athlete_data> XML from context sections
# ---------------------------------------------------------------------------

def _format_athlete_data(ctx, requires):
    """Build the athlete_data block from available context sections.

    Calls existing formatters from coach.py — does NOT re-implement formatting.
    """
    from coach import (
        _format_goal, _format_exercise_history, _format_exercise_analysis,
        _format_today_sets, _format_runs, _format_physical, _format_measurements,
        _format_next_week_prescriptions, _format_weekly_meals, _format_meals_today,
        _format_memories, _format_today, _format_week_schedule, _format_meals_today_xml,
        _summarize_checkins,
    )

    parts = []

    # Always: date/time/week/phase
    parts.append(_format_today(ctx))
    phase = ctx.get("phase", {})
    week = ctx.get("week", 1)
    parts.append(f"Week {week}/12 — Phase: {phase.get('label', '?')} — Focus: {phase.get('focus', '?')}")

    # Workout summary
    w = ctx.get("workout_today")
    if w:
        if w.get("isRest"):
            parts.append("Today is a rest day (streak mile only).")
        else:
            run_info = w.get('run', {})
            parts.append(f"Today's workout: {w.get('liftName', 'Rest')}. Run: {run_info.get('label', '?')} {run_info.get('time', '')}.")
            if w.get("exercises"):
                parts.append("Prescribed exercises:")
                for ex in w["exercises"]:
                    tw = f" @ {ex['target_weight']}lb" if ex.get('target_weight') else ""
                    note = f" — {ex['note']}" if ex.get('note') else ""
                    parts.append(f"  {ex['name']}: {ex['sets']} rest {ex['rest']}{tw}{note}")

    # Body weight trend
    bw = ctx.get("bodyweight", [])
    if bw:
        latest = bw[-1]
        first = bw[0]
        bw_line = f"Latest weight: {latest['weight']} lb ({latest['date']})."
        total_delta = latest['weight'] - first['weight']
        if len(bw) >= 2:
            direction = "down" if total_delta < 0 else "up" if total_delta > 0 else "flat"
            bw_line += f" Program total: {direction} {abs(total_delta):.1f} lb."
            prev = bw[-2]
            weekly_delta = latest['weight'] - prev['weight']
            wk_dir = "down" if weekly_delta < 0 else "up" if weekly_delta > 0 else "flat"
            bw_line += f" Last weigh-in: {wk_dir} {abs(weekly_delta):.1f} lb vs {prev['date']}."
        if len(bw) >= 3:
            weights_str = " -> ".join(str(e['weight']) for e in bw[-6:])
            bw_line += f"\n  Weight history: {weights_str}"
        parts.append(bw_line)

    # Garmin
    g = ctx.get("garmin")
    if g:
        garmin_parts = []
        if g.get("hrv") and g["hrv"].get("lastNight") is not None:
            garmin_parts.append(f"HRV {g['hrv']['lastNight']} (avg {g['hrv'].get('weeklyAvg', '?')})")
        if g.get("sleep") and g["sleep"].get("score") is not None:
            garmin_parts.append(f"Sleep score {g['sleep']['score']} ({g['sleep'].get('durationHours', '?')}h)")
        if g.get("bodyBattery") and g["bodyBattery"].get("current") is not None:
            garmin_parts.append(f"Body battery {g['bodyBattery']['current']}")
        if g.get("stress") and g["stress"].get("overall") is not None:
            garmin_parts.append(f"Stress {g['stress']['overall']}")
        if garmin_parts:
            parts.append("Garmin today: " + ", ".join(garmin_parts) + ".")
    r = ctx.get("readiness")
    if r and r.get("score") is not None:
        readiness_line = f"Readiness score: {r['score']}/100 ({r['risk_level']} risk)."
        if r.get("flags"):
            readiness_line += f" Flags: {', '.join(r['flags'])}."
        parts.append(readiness_line)

    # Check-ins
    if "checkins" in requires:
        parts.append(_summarize_checkins(ctx.get("checkins", [])))
    if ctx.get("missed_checkin_today"):
        parts.append("WARNING: Morning check-in today was MISSED.")

    # Goal
    if ctx.get("goal"):
        parts.append(_format_goal(ctx["goal"]))

    # Week schedule + completed
    if ctx.get("week_schedule"):
        parts.append(_format_week_schedule(ctx["week_schedule"], ctx.get("completed_days_this_week", [])))

    # Exercise data
    if ctx.get("exercise_history"):
        parts.append(_format_exercise_history(ctx["exercise_history"]))
    if ctx.get("exercise_analysis"):
        parts.append(_format_exercise_analysis(ctx["exercise_analysis"]))
    if ctx.get("today_sets"):
        parts.append(_format_today_sets(ctx["today_sets"]))

    # Session analysis
    sa = ctx.get("session_analysis")
    if sa:
        parts.append(f"LAST SESSION ({sa.get('date', '?')}): Compliance {sa.get('compliance', '?')}%. {sa.get('summary', '')}")
        parts.append(f"Muscle groups: {', '.join(sa.get('muscles', []))}")
    ws = ctx.get("weekly_summary")
    if ws and ws.get("sessions", 0) > 0:
        parts.append(f"WEEKLY SUMMARY (Week {ws.get('week', '?')}): {ws.get('summary', '')}")

    # Runs
    if ctx.get("run_history"):
        parts.append(_format_runs(ctx["run_history"]))

    # Physical
    if ctx.get("physical_assessment"):
        parts.append(_format_physical(ctx["physical_assessment"]))
    if ctx.get("body_measurements"):
        parts.append(_format_measurements(ctx["body_measurements"]))

    # Meals
    meal_plan = None
    wt = ctx.get("workout_today")
    if wt and wt.get("mealPlan"):
        mp = wt["mealPlan"]
        meal_plan = {
            "type": mp.get("label", ""),
            "target_cal": mp.get("targetCal"),
            "target_protein": mp.get("targetProtein"),
            "meals": [{"time": m.get("time", ""), "name": m.get("name", ""),
                       "foods": [f["item"] for f in m.get("foods", [])]}
                      for m in mp.get("meals", [])],
        }
    meal_plan_type = ctx.get("today_meal_type", "standard")
    if meal_plan:
        raw_type = meal_plan.get('type', '').lower()
        if 'fast' in raw_type or 'protein-sparing' in raw_type:
            meal_plan_type = "fast_day"
    if ctx.get("meals_today") is not None or meal_plan:
        parts.append(_format_meals_today_xml(ctx.get("meals_today"), meal_plan, meal_plan_type, user_timezone=ctx.get("user_timezone")))
    if ctx.get("weekly_meals_summary"):
        parts.append(_format_weekly_meals(ctx["weekly_meals_summary"]))

    # Fasting
    fasting_state = ctx.get("fasting_state")
    if fasting_state:
        if fasting_state.get("is_fast_day"):
            parts.append(
                f"CURRENT FASTING STATE: {fasting_state['hours_fasted']} hours fasted "
                f"(since {fasting_state['last_meal_day']} {fasting_state['last_meal_time']}). "
                f"TODAY IS A FULL FAST DAY — NO eating window. Zero calories until tomorrow. "
                f"Water, black coffee, electrolytes only. Do NOT suggest breaking the fast."
            )
        else:
            parts.append(
                f"CURRENT FASTING STATE: {fasting_state['hours_fasted']} hours fasted "
                f"(since {fasting_state['last_meal_day']} {fasting_state['last_meal_time']}). "
                f"Eating window opens at {fasting_state['eating_window_opens']}."
            )
    fp = ctx.get("fasting_protocol")
    if fp:
        parts.append(f"FASTING PROTOCOL: {fp}")

    # Equipment
    eq = ctx.get("equipment", [])
    if eq:
        parts.append(f"Equipment: {', '.join(eq)}")

    # Supplements
    supps = ctx.get("supplements_today", {})
    taken = [k for k, v in supps.get("taken", {}).items() if v]
    if taken:
        parts.append(f"Supplements taken: {', '.join(taken)}")

    # Intake report
    if ctx.get("intake_report"):
        parts.append(f"PSYCH INTAKE REPORT:\n{ctx['intake_report']}")

    # Next week
    if ctx.get("next_week_prescriptions"):
        parts.append(_format_next_week_prescriptions(ctx["next_week_prescriptions"]))

    # Coach memories
    if ctx.get("coach_memories"):
        parts.append(_format_memories(ctx["coach_memories"]))

    # User rules (corrections from the athlete)
    rules = ctx.get("user_rules", [])
    if rules:
        lines = ["ATHLETE CORRECTIONS (you MUST follow these — the athlete told you to change behavior):"]
        for r in rules:
            cat = f"[{r['category']}] " if r.get('category') else ""
            lines.append(f"  {cat}{r['rule_text']}")
        parts.append("\n".join(lines))

    # Schedule notes / activities
    if ctx.get("schedule_notes"):
        parts.append(f"Schedule notes: {ctx['schedule_notes']}")
    if ctx.get("scheduled_activities"):
        parts.append(ctx["scheduled_activities"])

    # Overrides
    for key in ("schedule_overrides", "meal_overrides", "run_overrides", "active_swaps"):
        items = ctx.get(key, [])
        if items:
            parts.append(f"{key.upper()}: {items}")

    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# _format_food_safety_block — builds <food_safety> XML
# ---------------------------------------------------------------------------

def _format_food_safety_block(ctx):
    """Build the food_safety block from context."""
    parts = []

    # Restrictions / allergies
    restrictions = ctx.get("food_restrictions", [])
    custom = ctx.get("custom_allergies", "")
    if restrictions or custom:
        allergen_list = ", ".join(restrictions) if restrictions else "None"
        parts.append(f"DIETARY RESTRICTIONS: {allergen_list}")
        if custom:
            parts.append(f"Custom allergies/intolerances: {custom}")

    # Approved food list
    selected_foods = ctx.get("selected_foods")
    if selected_foods:
        _FOOD_ID_TO_NAME = {
            "chicken_breast": "Chicken Breast", "ground_turkey_93": "Ground Turkey",
            "ground_beef_90": "Ground Beef", "salmon": "Salmon", "tilapia": "Tilapia",
            "shrimp": "Shrimp", "tuna_canned": "Canned Tuna", "eggs": "Eggs",
            "egg_whites": "Egg Whites", "greek_yogurt": "Greek Yogurt",
            "cottage_cheese": "Cottage Cheese", "tofu_firm": "Tofu", "tempeh": "Tempeh",
            "whey_protein": "Whey Protein", "plant_protein": "Plant Protein",
            "white_rice": "White Rice", "brown_rice": "Brown Rice", "oats": "Oats",
            "sweet_potato": "Sweet Potato", "white_potato": "White Potato", "quinoa": "Quinoa",
            "whole_wheat_bread": "Whole Wheat Bread", "whole_wheat_pasta": "Whole Wheat Pasta",
            "black_beans": "Black Beans", "lentils": "Lentils", "banana": "Banana",
            "blueberries": "Blueberries", "broccoli": "Broccoli", "spinach": "Spinach",
            "kale": "Kale", "asparagus": "Asparagus", "green_beans": "Green Beans",
            "bell_pepper": "Bell Pepper", "zucchini": "Zucchini", "cauliflower": "Cauliflower",
            "mixed_greens": "Mixed Greens", "cherry_tomatoes": "Cherry Tomatoes",
            "olive_oil": "Olive Oil", "coconut_oil": "Coconut Oil", "avocado": "Avocado",
            "almonds": "Almonds", "walnuts": "Walnuts", "peanut_butter": "Peanut Butter",
            "almond_butter": "Almond Butter", "chia_seeds": "Chia Seeds",
            "flax_seeds": "Flax Seeds", "cheddar_cheese": "Cheddar Cheese",
        }
        names = []
        for cat, food_ids in selected_foods.items():
            for fid in food_ids:
                names.append(_FOOD_ID_TO_NAME.get(fid, fid))
        parts.append(
            "COMPLETE LIST OF APPROVED FOODS. There are NO other approved foods:\n"
            f"{', '.join(sorted(names))}\n"
            "If a food is NOT on this list, it DOES NOT EXIST for this athlete. "
            "Do not mention it. Do not suggest it. Do not reference it."
        )

    if not parts:
        parts.append("No dietary restrictions on file.")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# assemble_prompt — the main entry point
# ---------------------------------------------------------------------------

def assemble_prompt(agent_name, context):
    """Combine CORE_PROMPT + protocol + formatted data into a system prompt.

    Args:
        agent_name: Key into PROTOCOL_MAP (e.g. "morning_checkin", "conversation")
        context: Dict from build_filtered_context()

    Returns:
        Complete system prompt string ready for Claude API.
    """
    from coach_agents import AGENTS
    agent = AGENTS.get(agent_name, AGENTS.get("conversation"))
    requires = agent.get("requires", ["base"])

    # Anger level — "good enough" in message forces Lombardi mode (demo)
    try:
        from coach_state import get_anger_label, get_anger_instruction, ANGER_LEVELS
        if context.get("_force_angry"):
            anger_label = ANGER_LEVELS[3]["label"]
            anger_instruction = ANGER_LEVELS[3]["instruction"]
        else:
            anger_label = get_anger_label(current_user.id)
            anger_instruction = get_anger_instruction(current_user.id)
    except Exception:
        anger_label = "Baseline — Saban process mode"
        anger_instruction = "Standard coaching intensity. Process-focused. Direct."

    # Protocol
    protocol = PROTOCOL_MAP.get(agent_name, PROTOCOL_MAP.get("freeform", ""))

    # Athlete data block
    athlete_data_block = _format_athlete_data(context, requires)

    # Food safety block
    food_safety_block = _format_food_safety_block(context)

    # Assemble
    prompt = CORE_PROMPT.format(
        athlete_name=context.get("athlete_name", "Athlete"),
        anger_level_label=anger_label,
        anger_level_instruction=anger_instruction,
        triggered_protocol=protocol,
        athlete_data_block=athlete_data_block,
        food_safety_block=food_safety_block,
    )

    return prompt
