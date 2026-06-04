"""A cut fast day says "0 cal — water, black coffee, electrolytes only; no food
until you break the fast." The serve-time food-selection filter must NOT inject
the athlete's selected protein (grilled chicken) onto that day — doing so was a
flat contradiction with the day's own header. The substitution is allowed ONLY
when the day's plan actually intends protein (a bulk/recomp fast that swaps a
removed shake)."""
import pytest


@pytest.fixture(scope="module")
def user_id():
    from app import app, db
    from models import User
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="fastday@test.com").first()
        if not u:
            u = User(email="fastday@test.com")
            db.session.add(u)
            db.session.commit()
        return u.id


def _run(user_id, target_protein, target_cal):
    from app import app, db, _filter_meals_by_food_selections
    from models import User
    from flask_login import login_user
    with app.app_context():
        with app.test_request_context():
            login_user(db.session.get(User, user_id), force=True)
            days = [{"mealPlan": {
                "label": "Fast Day", "targetCal": target_cal,
                "targetProtein": target_protein,
                "meals": [{"time": "Anytime", "name": "Fasting", "optional": False,
                           "foods": [
                               {"item": "Black coffee", "cal": 5, "protein": 0, "carbs": 0, "fat": 0},
                               {"item": "Water", "cal": 0, "protein": 0, "carbs": 0, "fat": 0}]}]}}]
            out = _filter_meals_by_food_selections(days, {"chicken_breast"})
            return [f["item"] for f in out[0]["mealPlan"]["meals"][0]["foods"]]


def test_cut_fast_day_keeps_only_water_and_coffee(user_id):
    foods = _run(user_id, target_protein=0, target_cal=0)
    assert not any("hicken" in f for f in foods), f"cut fast must not inject food: {foods}"
    assert foods == ["Black coffee", "Water"]


def test_bulk_fast_with_protein_target_still_substitutes(user_id):
    # A fast that legitimately budgets protein (bulk/recomp) keeps the swap.
    foods = _run(user_id, target_protein=30, target_cal=130)
    assert any("hicken" in f for f in foods), f"protein-intended fast should swap: {foods}"
