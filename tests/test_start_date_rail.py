"""S039: start_date is locked once the block has logged work; otherwise it
must be a Monday. /api/import obeys the same rail."""
from datetime import date, timedelta
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _client(app_, uid):
    # The module-scoped app context caches flask-login's user on g across
    # test-client requests; drop it so this client is really `uid`.
    from flask import g
    g.pop("_login_user", None)
    c = app_.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    return c


def test_start_date_rail(app_ctx):
    app_, db = app_ctx
    from models import User, AppState, SetLog
    u = User(email="startrail@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    monday = date(2026, 8, 31)
    db.session.add(AppState(user_id=u.id, start_date=monday)); db.session.commit()
    c = _client(app_, u.id)

    # not a Monday → 400
    r = c.post("/api/state", json={"start_date": "2026-09-02"})
    assert r.status_code == 400
    # a Monday, no logged work → allowed
    r = c.post("/api/state", json={"start_date": "2026-09-07"})
    assert r.status_code == 200
    db.session.expire_all()
    assert AppState.query.filter_by(user_id=u.id).first().start_date == date(2026, 9, 7)

    # log work in the block → locked
    db.session.add(SetLog(user_id=u.id, exercise_name="Bench", week=1, day_idx=0, set_number=0,
                          weight=100, reps=5, done=True, logged_date=date(2026, 9, 8)))
    db.session.commit()
    r = c.post("/api/state", json={"start_date": "2026-09-14"})
    assert r.status_code == 409
    db.session.expire_all()
    assert AppState.query.filter_by(user_id=u.id).first().start_date == date(2026, 9, 7)

    # import must not override either
    r = c.post("/api/import", json={"state": {"start_date": "2026-03-30"}})
    assert r.status_code == 200 and "start_date not imported" in " ".join(r.get_json().get("warnings", []))
    db.session.expire_all()
    assert AppState.query.filter_by(user_id=u.id).first().start_date == date(2026, 9, 7)


def test_completion_toggles_are_idempotent_with_explicit_done(app_ctx):
    """S033: two replayed POSTs with done:true leave the row done; a legacy
    body without `done` still toggles."""
    app_, db = app_ctx
    from models import User, ExerciseCompletion, DayCompletion
    u = User(email="idem@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    c = _client(app_, u.id)
    for _ in range(2):
        r = c.post("/api/completions/exercise", json={"week": 1, "day_idx": 0, "exercise_idx": 2, "done": True})
        assert r.status_code == 200 and r.get_json()["done"] is True
    for _ in range(2):
        r = c.post("/api/completions/day", json={"week": 1, "day_idx": 0, "done": True})
        assert r.status_code == 200
    db.session.remove()  # the day toggle's swallowed analysis error can leave the scoped session dirty
    assert ExerciseCompletion.query.filter_by(user_id=u.id, week=1, day_idx=0, exercise_idx=2).first().done is True
    assert DayCompletion.query.filter_by(user_id=u.id, week=1, day_idx=0).first().done is True
    r = c.post("/api/completions/exercise", json={"week": 1, "day_idx": 0, "exercise_idx": 2})
    assert r.get_json()["done"] is False
