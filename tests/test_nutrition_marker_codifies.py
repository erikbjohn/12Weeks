"""S026: [NUTRITION: daily_calories=N] must reach the served meal cards for
the rest of the week, and persist as an override the recalibration honours."""
import pytest
from datetime import date


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_calories_marker_regenerates_remaining_days(app_ctx):
    app_, db = app_ctx
    from models import User, TrainingGoal, AppState, UserFoodSelections, WeeklyMealPlan, CoachMarkerLog
    import app as app_module
    from food_catalog import FOOD_CATALOG
    u = User(email="nutri-marker@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    monday = date.today() - __import__("datetime").timedelta(days=date.today().weekday())
    db.session.add(AppState(user_id=u.id, start_date=monday))
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", daily_calories=2400, protein_grams=200,
                                fasting_protocol="16_8"))
    sel = {cat: [f["id"] for f in foods] for cat, foods in FOOD_CATALOG.items()}
    db.session.add(UserFoodSelections(user_id=u.id, selected_foods=sel))
    db.session.commit()
    with app_.test_request_context():
        app_module._parse_coach_markers("[NUTRITION: daily_calories=1900, reason=tighten]", u.id, 1)
    db.session.expire_all()
    goal = TrainingGoal.query.filter_by(user_id=u.id).first()
    assert goal.daily_calories == 1900
    assert goal.calorie_override["calories"] == 1900 and goal.calorie_override["week"] == 1
    plans = WeeklyMealPlan.query.filter_by(user_id=u.id, week=1).all()
    assert plans, "remaining days must have regenerated meal cards"
    assert all(p.daily_calories <= 1900 * 1.15 for p in plans)  # per-day types scale off the new base
    log = CoachMarkerLog.query.filter_by(user_id=u.id, marker_type="NUTRITION").first()
    assert log and log.status == "applied"
