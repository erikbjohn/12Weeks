"""Main-page Stats accordion is PHASE-scoped (Erik, 2026-08-24): measurements
sparklines/deltas and lift detail only include rows logged on/after this
block's AppState.start_date. Progress overlay stays all-time (his call)."""
from datetime import date

import pytest

START = date(2026, 8, 10)


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _do(app_, fn):
    with app_.app_context():
        return fn()


def _login(app_, db, email):
    def _do_it():
        from models import User, AppState
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Los_Angeles")
            db.session.add(u)
            db.session.commit()
        AppState.query.filter_by(user_id=u.id).delete()
        db.session.add(AppState(user_id=u.id, current_week=2, start_date=START))
        db.session.commit()
        return u.id
    uid = _do(app_, _do_it)
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    return uid, client


def test_measurements_exclude_pre_block_rows(app_ctx):
    app_, db = app_ctx
    uid, client = _login(app_, db, "scope-meas@test.com")

    def _seed():
        from models import BodyMeasurement
        db.session.add(BodyMeasurement(user_id=uid, log_date=date(2026, 3, 30), waist_inches=46.0))
        db.session.add(BodyMeasurement(user_id=uid, log_date=START, waist_inches=42.0))
        db.session.add(BodyMeasurement(user_id=uid, log_date=date(2026, 8, 17), waist_inches=41.0))
        db.session.commit()
    _do(app_, _seed)
    rows = client.get("/api/measurements").get_json()
    dates = [r["date"] for r in rows]
    assert "2026-03-30" not in dates
    assert dates == ["2026-08-10", "2026-08-17"]


def test_weight_detail_excludes_pre_block_sets(app_ctx):
    app_, db = app_ctx
    uid, client = _login(app_, db, "scope-detail@test.com")

    def _seed():
        from models import SetLog
        # Old block: week 5 @ 165x5 (a bigger e1RM than anything this block)
        db.session.add(SetLog(user_id=uid, exercise_name="Barbell Back Squat", week=5, day_idx=0,
                              set_number=1, weight=165, reps=5, done=True, logged_date=date(2026, 6, 8)))
        db.session.add(SetLog(user_id=uid, exercise_name="Barbell Back Squat", week=1, day_idx=0,
                              set_number=1, weight=105, reps=8, done=True, logged_date=date(2026, 8, 11)))
        db.session.add(SetLog(user_id=uid, exercise_name="Barbell Back Squat", week=2, day_idx=0,
                              set_number=1, weight=115, reps=8, done=True, logged_date=date(2026, 8, 18)))
        db.session.commit()
    _do(app_, _seed)
    d = client.get("/api/weight-detail/Barbell%20Back%20Squat").get_json()
    weeks = [t["week"] for t in d["timeline"]]
    assert 5 not in weeks, d["timeline"]
    assert weeks == [1, 2]
    # Baseline is this block's first week, not a March test row
    assert d["baseline_1rm"] == round(105 * (1 + 8 / 30))
    assert d["current_1rm"] == round(115 * (1 + 8 / 30))
