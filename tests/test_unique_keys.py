"""S043: per-user unique keys on plan tables and weigh-ins; a second insert
for the same key is refused by the DB, not by vigilance."""
import pytest
from datetime import date
from sqlalchemy.exc import IntegrityError


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_duplicate_run_plan_row_is_refused(app_ctx):
    app_, db = app_ctx
    from models import User, WeeklyRunPlan
    u = User(email="uq@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    db.session.add(WeeklyRunPlan(user_id=u.id, week=1, day_idx=0, run_type="z2", label="Easy", duration="30 min"))
    db.session.commit()
    db.session.add(WeeklyRunPlan(user_id=u.id, week=1, day_idx=0, run_type="z2", label="Dup", duration="40 min"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_duplicate_bodyweight_is_refused_but_api_updates_in_place(app_ctx):
    app_, db = app_ctx
    from models import User, BodyWeight
    u = User(email="uq-bw@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    uid = u.id
    from flask import g; g.pop("_login_user", None)
    c = app_.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    for w in (200.0, 199.5):
        r = c.post("/api/bodyweight", json={"weight": w, "date": date.today().isoformat()})
        assert r.status_code == 200, r.get_data(as_text=True)
    rows = BodyWeight.query.filter_by(user_id=uid, log_date=date.today()).all()
    assert len(rows) == 1 and rows[0].weight_lbs == 199.5
