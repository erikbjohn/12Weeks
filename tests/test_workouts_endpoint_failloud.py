"""Integration: /api/workouts must never serve the static template run as the
user's plan. A user with a lift prescription but no run plan for a week must get
run=None / runStatus='unplanned' for that day — not the hardcoded '25-30 min'
template range.
"""
import pytest


@pytest.fixture(scope="module")
def client_ctx():
    from app import app, db
    from models import User
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="failloud@test.com").first()
        if not u:
            u = User(email="failloud@test.com", name="FailLoud",
                     role="user", email_verified=True)
            db.session.add(u)
            db.session.commit()
        uid = u.id
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return client, app, uid


def _seed_week9_lift_only(app, uid):
    from app import db
    from models import WeeklyPrescription, WeeklyRunPlan
    with app.app_context():
        WeeklyPrescription.query.filter_by(user_id=uid, week=9).delete()
        WeeklyRunPlan.query.filter_by(user_id=uid, week=9).delete()
        db.session.add(WeeklyPrescription(
            user_id=uid, week=9, day_idx=0, exercise_order=0,
            exercise_name="Front Squat", sets=3, reps="3", rest="2-3 min",
            note="", source="coach", target_weight=135.0,
        ))
        db.session.commit()


def test_run_not_served_from_template_when_no_runplan(client_ctx):
    client, app, uid = client_ctx
    _seed_week9_lift_only(app, uid)

    resp = client.get("/api/workouts")
    assert resp.status_code == 200, resp.data[:200]
    day0 = resp.get_json()["9"]["days"][0]

    # Lifts are coach-planned -> shown.
    assert day0["liftStatus"] == "planned"
    assert any(e["name"] == "Front Squat" for e in day0["exercises"])

    # Run has no plan -> must be stripped and flagged, NOT the template range.
    assert day0["run"] is None
    assert day0["runStatus"] == "unplanned"
    assert "min" not in str(day0.get("run"))  # no '25-30 min' style leak


def test_day_without_prescription_strips_template_lifts(client_ctx):
    client, app, uid = client_ctx
    _seed_week9_lift_only(app, uid)  # only day 0 has a prescription

    resp = client.get("/api/workouts")
    days = resp.get_json()["9"]["days"]

    # A training day with no prescription must not show template exercises.
    day2 = days[2]  # Wednesday — template has exercises, but we seeded none
    if not day2.get("isRest"):
        assert day2["exercises"] == []
        assert day2["liftStatus"] == "unplanned"
