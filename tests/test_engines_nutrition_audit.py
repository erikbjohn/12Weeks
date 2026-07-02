"""Regression tests for the 2026-07-01 whole-app audit, theme 7 (engines +
nutrition).

Covers:
- equipment_swaps.scale_for_swap: catalog-based equipment classification
  (Goblet Squat IS a dumbbell lift, Romanian Deadlift IS a barbell lift even
  though the names carry no equipment keyword), equivalent-machine swaps at
  1.0, and the dumbbell→barbell reverse rescue.
- training_engine._get_muscle_group: bicep curls are biceps, not hamstrings.
- training_engine.compute_muscle_strength: recency weighting divides by the
  weights actually applied — on-target lifts 8-14 days old are NOT 'very_weak'.
- training_engine SIGNAL 5: beating the rep target bumps weight but keeps the
  exercise's CONFIGURED rep scheme.
- goal_engine.compute_targets (cut): returned macros always fit the returned
  calorie budget.
- meal_generator.generate_meal_plan: targetCal never sits below the macro sum;
  targets_pre_adjusted skips the day-type carb multiplier so day adjustments
  don't compound; the protein-shortfall supplement only uses the user's own
  selected proteins (no dairy for the dairy-free).
- coach_planning_meals.generate_week_meals: one non-numeric macro value from
  the LLM must not discard the whole week's output.
"""
import json
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


def _mk_user(db):
    from models import User
    _USER_SEQ[0] += 1
    u = User(email=f"engines-audit-{_USER_SEQ[0]}@example.com", password_hash="x")
    db.session.add(u)
    db.session.commit()
    return u


# ─── scale_for_swap: catalog-based classification ──────────────────────────

class TestScaleForSwap:
    def test_barbell_to_goblet_squat_scales_down(self):
        # 'Goblet Squat' contains neither 'dumbbell' nor 'db ' — the old
        # substring classifier returned 1.0 and prescribed the full 225 lb
        # bar weight for a single-dumbbell movement.
        from equipment_swaps import scale_for_swap
        assert scale_for_swap("Barbell Back Squat", "Goblet Squat") == 0.7

    def test_barbell_to_bulgarian_split_squat_scales_down(self):
        from equipment_swaps import scale_for_swap
        assert scale_for_swap("Barbell Back Squat", "Bulgarian Split Squat") == 0.7

    def test_equivalent_stack_equipment_is_one(self):
        # Cable → machine of the same stack class must NOT take the old 20%
        # catch-all haircut ('hit target reps = weight goes up').
        from equipment_swaps import scale_for_swap
        assert scale_for_swap("Cable Seated Row", "Seated Row Machine") == 1.0
        assert scale_for_swap("Face Pull", "Reverse Cable Fly") == 1.0

    def test_dumbbell_rdl_to_barbell_rdl_scales_up(self):
        # The reverse rescue training_engine documents: DB history transfers
        # UP to the barbell version. 'Romanian Deadlift' contains no
        # 'barbell', so the old classifier never fired.
        from equipment_swaps import scale_for_swap
        assert scale_for_swap("Dumbbell Romanian Deadlift", "Romanian Deadlift") == pytest.approx(1.43)

    def test_engine_swap_factor_uses_the_scale(self):
        from training_engine import _equipment_swap_factor
        assert _equipment_swap_factor("Barbell Back Squat", "Goblet Squat") == 0.7
        assert _equipment_swap_factor(
            "Dumbbell Romanian Deadlift", "Romanian Deadlift") == pytest.approx(1.43)

    def test_bodyweight_swaps_do_not_scale(self):
        from equipment_swaps import scale_for_swap
        assert scale_for_swap("Push-Ups", "DB Bench Press") == 1.0


# ─── muscle-group classification ────────────────────────────────────────────

class TestMuscleGroupKeywords:
    def test_bicep_curls_are_biceps_not_hamstrings(self):
        from training_engine import _get_muscle_group
        for name in ("Barbell Curl", "Preacher Curl", "Concentration Curl"):
            assert _get_muscle_group(name) == "biceps", name

    def test_leg_and_hamstring_curls_stay_hamstrings(self):
        from training_engine import _get_muscle_group
        for name in ("Lying Leg Curl", "Nordic Hamstring Curl",
                     "Swiss Ball Hamstring Curl"):
            assert _get_muscle_group(name) == "hamstrings", name


# ─── compute_muscle_strength recency weighting ──────────────────────────────

class TestMuscleStrengthWeights:
    def test_on_target_old_sets_are_not_very_weak(self, app_ctx):
        # All sets 10 days old (recency weight 1.0), lifted EXACTLY at target:
        # the ratio is 1.0 per set. Old math divided the 1.0-weighted scores by
        # positional 2.0 weights → avg 0.667 → 'very_weak' and a weight hold.
        app, db = app_ctx
        from models import SetLog, MuscleGroupProfile
        from training_engine import compute_muscle_strength
        u = _mk_user(db)
        logged = date.today() - timedelta(days=10)
        for i in range(4):
            db.session.add(SetLog(
                user_id=u.id, exercise_name="Barbell Bench Press", week=3,
                day_idx=1, set_number=i + 1, weight=145, reps=8, done=True,
                logged_date=logged, target_weight=145,
            ))
        db.session.commit()
        compute_muscle_strength(u.id)
        prof = MuscleGroupProfile.query.filter_by(
            user_id=u.id, muscle_group="chest").first()
        assert prof is not None
        assert prof.strength_score == pytest.approx(1.0)
        assert prof.relative_strength == "average"


# ─── SIGNAL 5 keeps the configured rep scheme ───────────────────────────────

class TestExceededRepsKeepsConfiguredReps:
    def test_beating_reps_bumps_weight_not_rep_scheme(self, app_ctx):
        # Week 1 Monday Front Squat is configured 4x8. User beat the target
        # (10 reps vs target 8). Weight goes up; reps stay at the CONFIGURED
        # 8 — not the phase-1 hardcoded default of 10.
        app, db = app_ctx
        from models import SetLog
        from training_engine import compute_next_targets, _get_configured_reps
        u = _mk_user(db)
        configured = _get_configured_reps("Front Squat", 1, 0, 0)
        assert configured == 8  # template sanity
        logged = date.today() - timedelta(days=3)
        for i in range(4):
            db.session.add(SetLog(
                user_id=u.id, exercise_name="Front Squat", week=1, day_idx=0,
                set_number=i + 1, weight=135, reps=10, done=True,
                logged_date=logged, target_weight=135, target_reps=8,
            ))
        db.session.commit()
        result = compute_next_targets(u.id, "Front Squat", 1, 0,
                                      exercise_order=0, allow_llm=False)
        assert result["progression_indicator"] == "up"
        assert result["target_weight"] > 135
        assert result["target_reps"] == configured


# ─── compute_targets macros fit the calorie budget ─────────────────────────

class TestCutTargetsFitBudget:
    def test_aggressive_cut_macros_never_exceed_calories(self):
        from goal_engine import compute_targets
        # Erik's live cut shape: 212 lb → 185, TDEE 2500, 12 weeks → 1375 kcal.
        for weeks in (12, 7, 4):
            t = compute_targets(2500, "cut", 212, target_weight=185, weeks=weeks)
            macro_cal = t["protein"] * 4 + t["carbs"] * 4 + t["fat"] * 9
            assert macro_cal <= t["calories"], (weeks, t, macro_cal)
            assert t["carbs"] >= 0 and t["fat"] >= 0

    def test_moderate_cut_still_gets_standard_macros(self):
        from goal_engine import compute_targets
        t = compute_targets(3000, "cut", 200, target_weight=190, weeks=12)
        assert t["protein"] == 200
        assert t["fat"] == 60  # 0.3 g/lb fits comfortably
        macro_cal = t["protein"] * 4 + t["carbs"] * 4 + t["fat"] * 9
        assert macro_cal <= t["calories"]


# ─── meal generator consistency ─────────────────────────────────────────────

_FOODS = {
    "proteins": ["chicken_breast", "whey_protein"],
    "carbs": ["white_rice", "sweet_potato"],
    "fats": ["olive_oil", "avocado"],
    "vegetables": ["broccoli", "spinach"],
}


class TestMealPlanCalorieConsistency:
    def test_target_cal_never_below_macro_sum(self):
        from meal_generator import generate_meal_plan
        # Recomp long-run shape from the audit: goal_engine already added the
        # +100 carb day bump; the generator used to double carbs AGAIN and
        # floor fat without recomputing targetCal → macros 610 kcal over.
        plan = generate_meal_plan(
            _FOODS, "long_run",
            {"calories": 2650, "protein": 240, "carbs": 265, "fat": 70},
            targets_pre_adjusted=True,
        )
        macro_cal = (plan["targetProtein"] * 4 + plan["targetCarbs"] * 4
                     + plan["targetFat"] * 9)
        assert macro_cal <= plan["targetCal"]

    def test_pre_adjusted_targets_skip_day_multiplier(self):
        from meal_generator import generate_meal_plan
        plan = generate_meal_plan(
            _FOODS, "long_run",
            {"calories": 2650, "protein": 240, "carbs": 265, "fat": 70},
            targets_pre_adjusted=True,
        )
        # Day adjustment already happened upstream — no 2.0x compounding.
        assert plan["targetCarbs"] == 265
        assert plan["targetFat"] == 70
        assert plan["targetCal"] == 2650

    def test_unadjusted_carb_bump_is_funded_by_fat(self):
        from meal_generator import generate_meal_plan
        plan = generate_meal_plan(
            _FOODS, "long_run",
            {"calories": 2650, "protein": 240, "carbs": 265, "fat": 70},
        )
        macro_cal = (plan["targetProtein"] * 4 + plan["targetCarbs"] * 4
                     + plan["targetFat"] * 9)
        # Fat can only fund (70-20)*9 = 450 kcal of extra carbs; the carb bump
        # is clamped instead of overshooting the displayed calorie target.
        assert macro_cal <= plan["targetCal"]
        assert plan["targetFat"] >= 20

    def test_protein_supplement_respects_user_selections(self):
        from meal_generator import generate_meal_plan
        # Dairy-free user: selections contain NO whey / cottage cheese /
        # Greek yogurt. A protein shortfall must never prescribe dairy.
        dairy_free = {
            "proteins": ["tofu"],
            "carbs": ["white_rice"],
            "fats": ["olive_oil"],
            "vegetables": ["broccoli"],
        }
        plan = generate_meal_plan(
            dairy_free, "moderate",
            {"calories": 2400, "protein": 230, "carbs": 150, "fat": 80},
            targets_pre_adjusted=True,
        )
        items = [f["item"] for m in plan["meals"] for f in (m.get("foods") or [])]
        for banned in ("Whey Protein Powder", "Cottage Cheese", "Greek Yogurt"):
            assert not any(banned.lower() in i.lower() for i in items), items


# ─── nutritionist parsing resilience ────────────────────────────────────────

class TestNutritionistParsing:
    def test_non_numeric_macro_does_not_discard_week(self, app_ctx, monkeypatch):
        app, db = app_ctx
        import coach_planning_meals as cpm

        payload = {
            "0": {"day_type": "heavy", "calories": "1800-2000", "protein": 200,
                  "carbs": 180, "fat": 60, "rationale": "range slipped in"},
            "1": {"day_type": "rest", "calories": 1500, "protein": "200g",
                  "carbs": 100, "fat": 65, "rationale": "rest day"},
            "2": {"day_type": "moderate", "calories": 1800, "protein": 200,
                  "carbs": 150, "fat": 60, "rationale": "training"},
        }

        class _Block:
            type = "text"
            text = json.dumps(payload)

        class _Resp:
            content = [_Block()]

        class _Messages:
            def create(self, **kwargs):
                return _Resp()

        class _Client:
            messages = _Messages()

        monkeypatch.setattr(cpm, "_anthropic_client", lambda: _Client())
        u = _mk_user(db)
        out = cpm.generate_week_meals(u.id, 3, {0: "heavy"}, {"goal_type": "cut"})
        # The whole week survives; the garbage values coerce to 0 (treated as
        # 'no number prescribed'), the good days keep their numbers.
        assert set(out.keys()) == {0, 1, 2}
        assert out[0]["calories"] == 0 and out[0]["day_type"] == "heavy"
        assert out[1]["protein"] == 0 and out[1]["calories"] == 1500
        assert out[2]["calories"] == 1800 and out[2]["protein"] == 200


# ─── template names resolve into the coach catalog ─────────────────────────

class TestTemplateNamesInCatalog:
    def test_every_template_exercise_resolves_into_exercises(self):
        from workout_data import (EXERCISES, resolve_name, get_workouts,
                                  get_workouts_for_user)
        names = set()
        for wk in range(1, 13):
            for variant in (get_workouts(wk),
                            get_workouts_for_user(wk, has_gym=False)):
                for day in variant:
                    for ex in day.get("exercises", []) or []:
                        if ex.get("name"):
                            names.add(ex["name"])
        missing = sorted(n for n in names if resolve_name(n) not in EXERCISES)
        assert missing == [], (
            "Template exercises missing from the EXERCISES catalog (the coach "
            f"can never prescribe these and validate_program drops them): {missing}"
        )
