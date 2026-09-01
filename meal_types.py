"""THE meal day-type derivation (S111). It existed twice — app.py derived
from the real run+lift first (correct), coach_assembler read the cached
WeeklyMealPlan.day_type first — so a run replanned after Sunday's meals
made the card say one thing and the coach another. No app imports here.
"""
from __future__ import annotations


def get_day_meal_type(user_id, week, day_idx):
    """Meal day-type for a day. The athlete's ACTUAL prescribed run + lift are
    the source of truth — never a stale cached day_type, never the template's
    weekday assumption.

    This is the bug that kept putting "Long Run Day" on an interval Tuesday:
    the old code returned the cached WeeklyMealPlan.day_type FIRST, and the meal
    regenerator computes day-types FROM this function — so the stale "long_run"
    fed its own regeneration and could never be healed. And even the derive path
    read the TEMPLATE's run, not the athlete's replanned VO2 run. Now we overlay
    the real WeeklyRunPlan run before deriving, and the cache may never override
    a derivation that contradicts it.

    Fast days are goal-dependent: only 'cut' goals get true fast days.
    Bulk and recomp users get 'rest' on Sunday instead.
    """
    from workout_data import (DAY_MEAL_TYPES, derive_meal_type,
                              get_workouts, get_workouts_for_user)
    from models import (MealPlanOverride, PhysicalAssessment, WeeklyRunPlan,
                        WeeklyMealPlan, TrainingGoal)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday = day_names[day_idx] if day_idx < 7 else "Mon"

    # 1. Explicit override wins — a deliberate coach/user decision.
    try:
        override = MealPlanOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if override and override.meal_type:
            return override.meal_type
    except Exception:
        pass

    # 2. Derive from the day's ACTUAL run (WeeklyRunPlan) + lift, overlaid on the
    #    template. Authoritative: the meal label must match what the athlete is
    #    actually doing — a replanned VO2 Tuesday is intervals, not a long run.
    derived = None
    try:
        pa = PhysicalAssessment.query.filter_by(user_id=user_id).first()
        has_gym = pa.has_gym if pa else True
        tdays = (get_workouts(week) if has_gym
                 else get_workouts_for_user(week, has_gym=False))
        day_dict = dict(tdays[day_idx]) if day_idx < len(tdays) else {}
        try:
            rp = WeeklyRunPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if rp and rp.run_type:
                day_dict["run"] = {"type": rp.run_type, "label": rp.label,
                                   "time": rp.duration, "detail": rp.detail or ""}
        except Exception:
            pass
        derived = derive_meal_type(day_dict, weekday)
    except Exception:
        derived = None

    # 3. Fall back to the stored cache ONLY when derivation is impossible, then
    #    the weekday map. The cache may not override a contradicting derivation.
    if derived is None:
        try:
            wmp = WeeklyMealPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            derived = wmp.day_type if (wmp and wmp.day_type) else None
        except Exception:
            derived = None
    meal_type = derived or DAY_MEAL_TYPES.get(weekday, "moderate")

    # Fast days only make sense for cut goals.
    # Bulk/recomp users get a rest day instead.
    if meal_type == "fast_day":
        try:
            goal = TrainingGoal.query.filter_by(user_id=user_id).order_by(TrainingGoal.id.desc()).first()
            if goal and goal.goal_type in ("bulk", "recomp"):
                return "rest"
        except Exception:
            pass

    return meal_type
