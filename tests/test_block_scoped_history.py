"""S010: parked prior-block rows (transition_block3 moved block-1 history to
weeks 25-36 and block-2 to 13-18 in the SAME tables) must never read as
'recent' for the current block."""
from datetime import date, timedelta
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_planner_history_ignores_parked_block_rows(app_ctx):
    app_, db = app_ctx
    from models import User, SetLog, AppState
    import coach_planning_program as cpp
    u = User(email="blockscope@test.com", password_hash="x")
    db.session.add(u); db.session.commit()
    start = date.today() - timedelta(days=21)
    db.session.add(AppState(user_id=u.id, start_date=start))
    # June (parked at week 30) — a 225 top the current block has never seen
    db.session.add(SetLog(user_id=u.id, exercise_name="Barbell Back Squat", week=30,
                          day_idx=0, set_number=0, weight=225, reps=5, done=True,
                          logged_date=start - timedelta(days=80)))
    # this block, week 2
    db.session.add(SetLog(user_id=u.id, exercise_name="Barbell Bench Press", week=2,
                          day_idx=1, set_number=0, weight=135, reps=5, done=True,
                          logged_date=start + timedelta(days=8)))
    db.session.commit()

    rows = cpp._block_set_rows(u.id, 4, 4).all()
    assert {r.exercise_name for r in rows} == {"Barbell Bench Press"}
    assert max(r.weight for r in rows) == 135
    text = cpp._history_block(u.id, 4)
    assert "Squat" not in text and "225" not in text


def test_recent_macros_bounded_to_block(app_ctx):
    app_, db = app_ctx
    from models import User, WeeklyMealPlan
    import coach_planning_meals as cpm
    u = User(email="blockscope-meals@test.com", password_hash="x")
    db.session.add(u); db.session.commit()
    db.session.add(WeeklyMealPlan(user_id=u.id, week=36, day_idx=0, day_type="heavy",
                                  meal_data={}, daily_calories=3100, daily_protein=200))
    db.session.add(WeeklyMealPlan(user_id=u.id, week=3, day_idx=0, day_type="rest",
                                  meal_data={}, daily_calories=1900, daily_protein=200))
    db.session.commit()
    block = cpm._build_recent_macros_block(u.id, 4)
    assert "wk 3 " in block and "wk 36" not in block
