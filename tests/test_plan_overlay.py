"""Fail-loud serving contract: the static template must NEVER be served as the
user's plan. When a domain (run / lifts / meals) has no real coach/engine rows
for the week, the served day must strip the template content and mark that
domain 'unplanned' so the UI shows a loud empty state instead of hardcoded
placeholder numbers (e.g. the '60-90 min' run-duration range leak).
"""
from plan_overlay import finalize_day_plan


def _template_day():
    """A day as get_workouts() builds it from the static template."""
    return {
        "liftName": "Lower POWER (HOLD)",
        "isRest": False,
        "exercises": [
            {"name": "Front Squat", "sets": "3x3", "rest": "2-3 min", "note": "lead"},
            {"name": "Romanian Deadlift", "sets": "2x10", "rest": "90s", "note": ""},
        ],
        "run": {
            "type": "z2_long",
            "label": "Long fasted easy run",
            "time": "60-90 min",          # <-- the hardcoded range that leaked
            "detail": "Fasted state, fat-ox bias. HR under 140. Conversational.",
        },
        "mealPlan": {"label": "heavy_lift", "targetCal": 1800},
        "mealType": "heavy_lift",
    }


# ─── RUN ─────────────────────────────────────────────────────────────────

def test_run_stripped_when_no_runplan():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=True, has_runplan=False, has_mealplan=True,
    )
    assert day["run"] is None, "template run must NOT be served when no run-plan rows exist"
    assert day["runStatus"] == "unplanned"


def test_run_kept_when_runplan_exists():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=True, has_runplan=True, has_mealplan=True,
    )
    assert day["run"] is not None
    assert day["run"]["time"] == "60-90 min"  # overlay already replaced it upstream
    assert day["runStatus"] == "planned"


def test_no_template_range_ever_reaches_ui_without_runplan():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=True, has_runplan=False, has_mealplan=True,
    )
    # Hard guarantee: no '-min' range string survives anywhere in the run slot.
    assert "60-90" not in str(day.get("run"))


# ─── LIFTS ───────────────────────────────────────────────────────────────

def test_lifts_stripped_when_no_prescriptions_on_training_day():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=False, has_runplan=True, has_mealplan=True,
    )
    assert day["exercises"] == [], "template exercises must NOT be served without prescriptions"
    assert day["liftStatus"] == "unplanned"


def test_lifts_kept_when_prescriptions_exist():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=True, has_runplan=True, has_mealplan=True,
    )
    assert len(day["exercises"]) == 2
    assert day["liftStatus"] == "planned"


def test_rest_day_is_not_flagged_unplanned():
    rest = _template_day()
    rest["isRest"] = True
    rest["exercises"] = []
    day = finalize_day_plan(
        rest, has_prescriptions=False, has_runplan=True, has_mealplan=True,
    )
    assert day["liftStatus"] == "rest"


# ─── MEALS ───────────────────────────────────────────────────────────────

def test_meals_stripped_when_no_mealplan():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=True, has_runplan=True, has_mealplan=False,
    )
    assert day.get("mealPlan") is None
    assert day["mealStatus"] == "unplanned"


def test_meals_kept_when_mealplan_exists():
    day = finalize_day_plan(
        _template_day(),
        has_prescriptions=True, has_runplan=True, has_mealplan=True,
    )
    assert day["mealPlan"] is not None
    assert day["mealStatus"] == "planned"


# ─── PURE-TEMPLATE SURFACES (timing / notes) ─────────────────────────────

def test_static_timing_and_notes_never_served():
    src = _template_day()
    src["timing"] = ["6:00", "Lift (55 min)", "7:05", "Zone 2 easy 25-35 min"]
    src["notes"] = "Front Squat lead. Build reps 8->12, then bump weight."
    # Even on a fully planned day, the static schedule/notes must not be served.
    day = finalize_day_plan(
        src, has_prescriptions=True, has_runplan=True, has_mealplan=True,
    )
    assert "timing" not in day
    assert "notes" not in day
