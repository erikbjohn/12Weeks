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


@section_builder("event_timeline")
def _build_event_timeline():
    """Structured ground-truth ledger from canonical logs.

    Replaces the chat-history feed (which fed past coach messages back into
    the prompt and let hallucinations persist). Only logged events from
    canonical tables: SetLog, RunLog, BodyMeasurement.

    Returns {"event_timeline": "<event_timeline>...</event_timeline>"}.
    """
    if not current_user.is_authenticated:
        return {"event_timeline": "<event_timeline>\nNONE — not authenticated.\n</event_timeline>"}
    from models import SetLog, RunLog, BodyMeasurement
    cutoff = date.today() - timedelta(days=7)
    events: list[tuple[str, str]] = []   # (date_str_for_sort, line)

    # SetLog rows — group by (logged_date, exercise_name)
    sets = (SetLog.query
            .filter(SetLog.user_id == current_user.id, SetLog.logged_date >= cutoff)
            .order_by(SetLog.logged_date.desc(), SetLog.id.asc())
            .limit(200).all())
    grouped: dict[tuple, list] = {}
    for s in sets:
        grouped.setdefault((s.logged_date, s.exercise_name), []).append(s)
    for (d, name), rows in grouped.items():
        sets_str = ", ".join(f"{r.set_number}: {r.weight}x{r.reps}" for r in rows)
        events.append((str(d), f"[{d}] LIFT {name}: {sets_str}"))

    # RunLog — note actual field is `log_date` (not `run_date`)
    runs = (RunLog.query
            .filter(RunLog.user_id == current_user.id, RunLog.log_date >= cutoff)
            .order_by(RunLog.log_date.desc())
            .limit(50).all())
    for r in runs:
        dist = getattr(r, "distance_miles", None) or "?"
        hr = getattr(r, "avg_hr", None) or "?"
        events.append((str(r.log_date), f"[{r.log_date}] RUN {dist}mi avg HR {hr}"))

    # BodyMeasurement — fields are `log_date` and `weight_lbs`
    weighs = (BodyMeasurement.query
              .filter(BodyMeasurement.user_id == current_user.id,
                      BodyMeasurement.log_date >= cutoff)
              .order_by(BodyMeasurement.log_date.desc())
              .limit(20).all())
    for w in weighs:
        if w.weight_lbs is None:
            continue
        events.append((str(w.log_date), f"[{w.log_date}] WEIGH-IN {w.weight_lbs} lb"))

    if not events:
        return {"event_timeline": "<event_timeline>\nNONE — athlete has no logged events in the last 7 days. Do not reference any.\n</event_timeline>"}

    events.sort(key=lambda e: e[0], reverse=True)
    body = "\n".join(line for _, line in events)
    return {"event_timeline": f"<event_timeline>\n{body}\n</event_timeline>"}


@section_builder("recent_coach_directives")
def _build_recent_coach_directives():
    """The coach's last 3 messages, today only. Provides continuity without
    perpetuating week-old hallucinations.

    Returns {"recent_coach_directives": "<recent_coach_directives>...</recent_coach_directives>"}.
    """
    if not current_user.is_authenticated:
        return {"recent_coach_directives": "<recent_coach_directives>\nNONE — not authenticated.\n</recent_coach_directives>"}
    from models import ChatMessage
    today = _user_today()
    msgs = (ChatMessage.query
            .filter_by(user_id=current_user.id, role="assistant", log_date=today)
            .order_by(ChatMessage.id.desc())
            .limit(3).all())
    if not msgs:
        return {"recent_coach_directives": "<recent_coach_directives>\nNONE — no coach messages today.\n</recent_coach_directives>"}
    body = "\n---\n".join(m.content for m in reversed(msgs))
    return {"recent_coach_directives": f"<recent_coach_directives>\n{body}\n</recent_coach_directives>"}


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


def _resolve_workout_for_day(week, day_idx):
    """Single source of truth for "what does day N look like for this user".

    Mirrors api_workouts (app.py:1854) so the coach sees what the UI shows:
      template/prescription → auto_swap_workout (equipment) → validated ExerciseSwap.
    Without auto_swap the coach prescribed Hip Thrust while the UI rendered Glute
    Bridge; without is_valid_swap a stale invalid ExerciseSwap row leaked into the
    coach's mouth. Returns the day dict (with overlaid exercises) or None.
    """
    from workout_data import get_workouts, get_workouts_for_user
    from models import WeeklyPrescription, PhysicalAssessment, UserEquipment, ExerciseSwap
    from equipment_swaps import auto_swap_workout, is_valid_swap

    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    has_gym = pa.has_gym if pa else True
    try:
        workouts = get_workouts(week) if has_gym else get_workouts_for_user(week, has_gym=False)
    except Exception:
        return None
    if day_idx < 0 or day_idx >= len(workouts):
        return None
    day = workouts[day_idx]

    # Prescriptions replace the template wholesale when present.
    try:
        rx_rows = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=week, day_idx=day_idx
        ).order_by(WeeklyPrescription.exercise_order).all()
        if rx_rows:
            day["exercises"] = [{
                "name": rx.exercise_name,
                "sets": f"{rx.sets}x{rx.reps}",
                "rest": rx.rest or "60s",
                "note": rx.note or "",
                "target_weight": getattr(rx, 'target_weight', None),
            } for rx in rx_rows]
    except Exception:
        pass

    # Equipment-driven substitution. Same pass api_workouts runs at line 1903.
    try:
        eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
        user_equipment = eq.available_equipment if eq else []
        if day.get("exercises"):
            day["exercises"] = auto_swap_workout(day["exercises"], user_equipment)
    except Exception:
        pass

    # Manual swaps last, validated against the post-auto-swap original so a stale
    # invalid row (the bug from commit ebab5fc) can't whisper to the coach.
    try:
        swap_rows = ExerciseSwap.query.filter_by(
            user_id=current_user.id, week=week, day_idx=day_idx
        ).all()
        if swap_rows and day.get("exercises"):
            for sw in swap_rows:
                if sw.exercise_idx is None or sw.exercise_idx >= len(day["exercises"]):
                    continue
                current_original = day["exercises"][sw.exercise_idx].get("name")
                if not is_valid_swap(current_original, sw.swapped_to):
                    continue
                day["exercises"][sw.exercise_idx]["name"] = sw.swapped_to
    except Exception:
        pass

    return day


@section_builder("workout_today")
def _build_workout_today():
    from models import WeeklyMealPlan, WeeklyRunPlan, WeeklyWarmup
    local_today = _user_today()
    week = _current_week()
    today_idx = local_today.weekday()
    wt = _resolve_workout_for_day(week, today_idx)
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
    # Merge RunOverride on top — UI does the same in buildRunSubsection,
    # without this the coach prescribes the base plan while the user sees the override.
    try:
        from models import RunOverride
        ov = RunOverride.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).first()
        if ov and wt:
            base = wt.get("run") or {}
            wt["run"] = {
                "type": ov.run_type or base.get("type"),
                "label": ov.run_type or base.get("label") or "Run",
                "time": ov.duration or base.get("time"),
                "detail": base.get("detail") or "",
                "override_reason": ov.reason or "",
            }
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


@section_builder("workout_tomorrow")
def _build_workout_tomorrow():
    """Tomorrow's exercise prescription, resolved the same way as today's.

    The conversation agent had no view of tomorrow — only today plus a lift-name
    schedule — so when asked "how many sets tomorrow?" the model invented an
    answer that diverged from the UI. This closes the hole.
    """
    local_today = _user_today()
    week = _current_week()
    today_idx = local_today.weekday()
    # Sunday → Monday rolls into next week. Past week 12 we just stop.
    if today_idx == 6:
        next_week = week + 1
        next_idx = 0
        if next_week > 12:
            return {"workout_tomorrow": None}
        wt = _resolve_workout_for_day(next_week, next_idx)
    else:
        wt = _resolve_workout_for_day(week, today_idx + 1)
    return {"workout_tomorrow": wt}


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
    from datetime import datetime, timedelta
    from models import CoachMemory
    cutoff = datetime.utcnow() - timedelta(days=21)
    rows = (CoachMemory.query
            .filter(CoachMemory.user_id == current_user.id,
                    CoachMemory.created_at >= cutoff)
            .order_by(CoachMemory.created_at.desc())
            .limit(50).all())
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
You are Erik's strength coach. Lombardi/Saban posture: you decide, athlete executes.

# OUTPUT CONTRACT — REQUIRED

You MUST emit your response as four (or three) tagged sections, in order:

<schedule>...</schedule>
<directive>...</directive>
<motivation>...</motivation>
<refusal>...</refusal>   # only when instructed by the rules engine

The <schedule> and <directive> sections will be PRE-FILLED for you in this
prompt. You MUST echo them back BYTE-IDENTICAL — same content, same line breaks,
same tags. The validator rejects any drift. Do not paraphrase, summarize, or
"clean up" these sections.

<motivation> is YOUR section. 1-3 sentences. Voice only. NO questions. NO
banned phrases (see below).

<refusal> appears ONLY when the rules engine in the prompt sets
refusal_required=true. When it does, your <refusal> echoes the directive
and names the deviation. NO negotiation. NO questions.

# CITATION RULE

Every claim in <motivation> must reference a specific field from
<athlete_data>. If the athlete_data section is missing or marked NONE, do
not reference it. Hallucinations are unacceptable.

# BANNED PHRASES

These cause validation failure. Do NOT use them anywhere:
- "your call", "if you feel up to it", "if you want", "feel free to", "no pressure", "up to you"
- "great job", "amazing work", "you're doing great", "proud of you", "love it", "crushing it"
- "would you like", "do you want", "should we", "ready to", "shall we"
- "we could", "we might", "perhaps", "maybe try"
- "if that works", "let's see how", "see how you feel"

# POSTURE

- Statements, not questions. The coach decides; the athlete executes.
- Tight prose. No filler. No exclamation marks unless the athlete just PR'd.
- Reference logged events, not invented ones. If the timeline is empty, say so.
- Do not soften the directive. Do not negotiate.

# WHAT YOU SEE

The user's latest message comes through the standard conversation channel — treat it as the prompt. The pre-filled
<schedule> and <directive> tell you what's happening and what to instruct.
The <event_timeline> is ground truth from logs — past coach messages are
NOT in scope. <recent_coach_directives> shows your last 3 messages today
for continuity only.

<athlete_data>
{athlete_data_block}
</athlete_data>

{food_safety_block}
"""


# ---------------------------------------------------------------------------
# PROTOCOL_MAP — agent-specific protocol strings (~100-600 tokens each)
# ---------------------------------------------------------------------------

PROTOCOL_MAP = {
    "conversation": (
        "Voice for <motivation>: respond to the athlete's message in 1-3 sentences. "
        "Reference one specific field from <event_timeline> or <athlete_data>. "
        "End with a statement, not a question."
    ),
    "morning_checkin": (
        "Voice for <motivation>: acknowledge the check-in numbers (sleep, weight, mood). "
        "Tie to today's directive. Statement, not question."
    ),
    "morning_briefing": (
        "Voice for <motivation>: terse — 1 sentence. Cite today's lift and run. "
        "No questions."
    ),
    "weekly_planning": (
        "Voice for <motivation>: anchor on the week's goal (cut to 185). State "
        "the most important focus for the week. Reference last week's session count. "
        "No questions."
    ),
    "weekly_review": (
        "Voice for <motivation>: 2-3 sentences. Cite weekly_summary numbers "
        "(sessions completed, weight delta, run miles). Statement only."
    ),
    "workout_feedback": (
        "Voice for <motivation>: 1-2 sentences acknowledging the lift just logged. "
        "Cite a specific set from <event_timeline>. Tie to next session's progression. "
        "No questions."
    ),
    "run_complete": (
        "Voice for <motivation>: 1 sentence. Cite the run from <event_timeline>. "
        "Tie to the cut. Statement only."
    ),
    "meals_complete": (
        "Voice for <motivation>: 1 sentence acknowledging meals logged. Tie to "
        "calorie target. No questions."
    ),
    "end_of_day": (
        "Voice for <motivation>: 1-2 sentences. Cite today's compliance "
        "(workout done? run done? meals?). State tomorrow's focus."
    ),
    "chat_opened": (
        "Voice for <motivation>: 1-2 sentences. Reference the directive and "
        "<event_timeline>'s most recent event. No greeting questions."
    ),
    "crisis": (
        "Voice for <motivation>: drop posture. Be direct, supportive, brief. "
        "Suggest concrete next step. No banned phrases still applies."
    ),
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
    # Ground phase explanations in the actual program structure so the coach
    # doesn't hallucinate (e.g. "Phase 2 drops to 3-4 days" — false; all phases run 6 lift days).
    if phase.get("lift_days_per_week") or phase.get("weekly_structure"):
        parts.append(
            f"This phase: {phase.get('lift_days_per_week', 6)} lift days/week, "
            f"lifting style {phase.get('lifting', '?')}. "
            f"Structure: {phase.get('weekly_structure', '?')} "
            "Do not invent phase details beyond this — describe the phase only as written here."
        )

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
        else:
            parts.append("Garmin today: NONE — no readings available. Do not reference HRV/sleep/body battery/stress.")
    else:
        parts.append("Garmin today: NONE — no Garmin data in scope. Do not reference HRV/sleep/body battery/stress.")
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
    else:
        parts.append("Exercise history: NONE — no past sessions in scope. Do not reference any specific past lift.")
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
    else:
        parts.append("Recent runs: NONE — no logged runs in scope. Do not reference any run.")

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
    else:
        parts.append("Meals today: NONE — no meals logged and no meal plan. Do not reference today's intake.")
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
    else:
        parts.append("Coach memories: NONE — no memories in the last 21 days. Do not reference past coaching decisions.")

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

    # New (Task 11): event timeline + recent coach directives — appended as XML blocks
    et = ctx.get("event_timeline")
    if et:
        parts.append(et)
    rcd = ctx.get("recent_coach_directives")
    if rcd:
        parts.append(rcd)

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

def assemble_prompt(agent_name, context, rules=None):
    """Combine CORE_PROMPT + protocol + formatted data into a system prompt.

    Args:
        agent_name: Key into PROTOCOL_MAP (e.g. "morning_checkin", "conversation")
        context: Dict from build_filtered_context()
        rules: Optional CoachRules dataclass from compute_coach_rules. When
               provided, pre-filled <schedule> and <directive> blocks are
               appended to the system prompt, and a refusal instruction is
               added when rules.refusal_required is True. When None, falls
               back to legacy behavior (no pre-fills).

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

    # Assemble base prompt via existing format() call
    prompt = CORE_PROMPT.format(
        athlete_name=context.get("athlete_name", "Athlete"),
        anger_level_label=anger_label,
        anger_level_instruction=anger_instruction,
        triggered_protocol=protocol,
        athlete_data_block=athlete_data_block,
        food_safety_block=food_safety_block,
    )

    # New (Task 15): inject rules engine pre-fills + protocol + refusal
    if rules is not None:
        prompt += "\n\n# AGENT PROTOCOL\n"
        prompt += protocol
        prompt += "\n\n# PRE-FILLED SECTIONS (echo these back byte-identical)\n"
        prompt += rules.prefilled_schedule
        prompt += "\n"
        prompt += rules.prefilled_directive
        if rules.refusal_required:
            prompt += (
                f"\n\n# REFUSAL REQUIRED — reason: {rules.refusal_reason}. "
                "Emit a <refusal> section that echoes the directive and names the deviation."
            )

    return prompt


# ---------------------------------------------------------------------------
# Task 16: coach_respond orchestration
# Pipeline: rules → assemble → LLM → validate → retry-with-feedback → fallback
# ---------------------------------------------------------------------------

def render_response_to_user(sections):
    """Strip tags, join sections in display order. The user never sees tags."""
    parts = []
    for key in ("schedule", "directive", "motivation", "refusal"):
        if key in sections and sections[key]:
            parts.append(sections[key].strip())
    return "\n\n".join(parts)


def coach_respond(
    user_id,
    agent_name,
    user_message,
    rules=None,
    llm_fn=None,
):
    """Top-level coach entry. Replaces the inline LLM call in /api/chat.

    Args:
        user_id: athlete user id.
        agent_name: agent key from AGENTS dict (e.g. 'conversation').
        user_message: the user's latest message text (or None for system events).
        rules: CoachRules dataclass. If None, computed via compute_coach_rules.
        llm_fn: Callable(system_prompt, messages, temperature, max_tokens) -> str.
                If None, uses the real Anthropic client. Tests pass a stub.

    Returns: rendered response string for the user (tags stripped).
    """
    from coach_rules import compute_coach_rules
    from coach_validator import validate_response, deterministic_fallback
    from coach_agents import AGENTS

    if rules is None:
        rules = compute_coach_rules(user_id=user_id, latest_user_message=user_message)

    context = build_filtered_context(agent_name)
    context["latest_user_message"] = user_message or ""
    system_prompt = assemble_prompt(agent_name, context, rules=rules)

    agent_cfg = AGENTS.get(agent_name, AGENTS["conversation"])
    messages = [{"role": "user", "content": user_message or "(system event)"}]

    if llm_fn is None:
        llm_fn = _real_llm_call

    raw = llm_fn(system_prompt, messages, agent_cfg["temperature"], agent_cfg["max_tokens"])

    result = validate_response(
        raw=raw,
        prefilled_schedule=rules.prefilled_schedule,
        prefilled_directive=rules.prefilled_directive,
        refusal_required=rules.refusal_required,
    )
    if result.ok:
        return render_response_to_user(result.sections)

    import logging
    log = logging.getLogger(__name__)
    log.warning(
        "coach_respond validation failed (1st attempt): %s. Raw response excerpt: %r",
        result.failure_reason,
        raw[:300],
    )

    # Retry once with feedback
    retry_messages = messages + [
        {"role": "assistant", "content": raw},
        {"role": "user", "content": (
            f"Your response failed validation: {result.failure_reason}. "
            "Re-emit the response, fixing the specific issue. "
            "Echo the pre-filled <schedule> and <directive> sections byte-identical."
        )},
    ]
    raw2 = llm_fn(system_prompt, retry_messages, agent_cfg["temperature"], agent_cfg["max_tokens"])
    result2 = validate_response(
        raw=raw2,
        prefilled_schedule=rules.prefilled_schedule,
        prefilled_directive=rules.prefilled_directive,
        refusal_required=rules.refusal_required,
    )
    if result2.ok:
        return render_response_to_user(result2.sections)

    log.warning(
        "coach_respond validation failed (2nd attempt): %s. Falling back. Raw: %r",
        result2.failure_reason,
        raw2[:300],
    )

    # Deterministic fallback (austere — better than capitulation)
    return deterministic_fallback(
        prefilled_schedule=rules.prefilled_schedule,
        prefilled_directive=rules.prefilled_directive,
        refusal_required=rules.refusal_required,
    )


def _real_llm_call(system_prompt, messages, temperature, max_tokens):
    """Production LLM call. Imported lazily so tests don't need the API key."""
    import os
    import anthropic
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=60.0,  # Non-streaming Opus calls can take 30-45s for long prompts
    )
    response = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


def coach_respond_streaming(
    user_id,
    agent_name,
    user_message,
    rules=None,
    llm_fn=None,
    chunk_size=50,
):
    """Streaming version of coach_respond. Yields chunks of validated text.

    Buffers the LLM response server-side, validates, retries, falls back —
    then yields the final validated string in chunks for SSE delivery.
    User sees slightly delayed but fully validated streaming.

    Args same as coach_respond. Yields strings (chunks of the response).
    """
    full_text = coach_respond(
        user_id=user_id,
        agent_name=agent_name,
        user_message=user_message,
        rules=rules,
        llm_fn=llm_fn,
    )
    # Chunk the validated string for streaming. Chunk on word boundaries.
    if not full_text:
        return
    words = full_text.split(" ")
    buf = ""
    for word in words:
        if len(buf) + len(word) + 1 > chunk_size:
            yield buf
            buf = word
        else:
            buf = (buf + " " + word).strip() if buf else word
    if buf:
        yield buf
