"""Fail-loud serving contract for the day plan.

The static template (workout_data.py) is the COACH'S INPUT scaffold — it defines
which exercises, set/rep schemes, and run types a week should contain. It must
NEVER be served to the athlete as their actual plan. Only real coach/engine rows
(WeeklyPrescription / WeeklyRunPlan / WeeklyMealPlan) are a plan.

`finalize_day_plan` runs after the DB overlays in /api/workouts. For any domain
(lifts / run / meals) that has no real row for the day, it strips the leftover
template content and tags the domain 'unplanned' so the client renders a loud
empty state instead of a hardcoded placeholder (e.g. the '60-90 min' range).

Status values per domain:
  lifts -> liftStatus: 'planned' | 'unplanned' | 'rest'
  run   -> runStatus:  'planned' | 'unplanned' | 'none'   ('none' = no run scheduled)
  meals -> mealStatus: 'planned' | 'unplanned'
"""
from __future__ import annotations


def finalize_day_plan(day, *, has_prescriptions, has_runplan, has_mealplan):
    """Strip template content for any unplanned domain. Mutates and returns day.

    Booleans are PER-DAY: does this day_idx have at least one real row of that
    kind for the week?

    SISTER LOGIC: coach_assembler._resolve_workout_for_day applies the SAME
    "no prescription -> strip the template lifts as unplanned" rule for the coach
    prompt (it sets lift_unplanned + nulls liftName, where this sets liftStatus).
    test_coach_unplanned_day.test_coach_and_dashboard_agree_on_lift_planned_state
    pins the two together — keep the planned/unplanned definition identical.
    """
    # ─── LIFTS ───
    if day.get("isRest"):
        day["liftStatus"] = "rest"
    elif has_prescriptions:
        day["liftStatus"] = "planned"
    else:
        day["exercises"] = []
        day["liftStatus"] = "unplanned"

    # ─── RUN ───
    run = day.get("run")
    if has_runplan:
        day["runStatus"] = "planned"
    elif run is not None:
        # Template scheduled a run but the coach never prescribed it: this is
        # the leak. Drop the placeholder rather than serve a static range.
        day["run"] = None
        day["runStatus"] = "unplanned"
    else:
        day["runStatus"] = "none"

    # ─── MEALS ───
    if has_mealplan:
        day["mealStatus"] = "planned"
    else:
        day.pop("mealPlan", None)
        day.pop("mealType", None)
        day["mealStatus"] = "unplanned"

    # ─── PURE-TEMPLATE SURFACES ───
    # `timing` (daily schedule, contains range strings like "run 60-90 min")
    # and `notes` (shown to the user as "Coach note" but actually hardcoded
    # template text) have NO coach overlay anywhere — they are always static.
    # Never serve them as the user's plan.
    day.pop("timing", None)
    day.pop("notes", None)

    return day
