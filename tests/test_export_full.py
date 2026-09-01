"""S001: /api/admin/export-full must be lossless — every per-user model, every
column — so the laptop backup job can restore anything the app writes."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_export_full_covers_every_per_user_model(app_ctx, monkeypatch):
    app_, db = app_ctx
    import models as m
    from sqlalchemy import inspect
    from datetime import date
    with app_.app_context():
        u = m.User(email="export-full@example.com", password_hash="x")
        db.session.add(u); db.session.commit()
        db.session.add(m.SetLog(user_id=u.id, week=1, day_idx=0, exercise_name="Bench",
                                set_number=0, weight=100, reps=5, logged_date=date.today()))
        db.session.add(m.BodyWeight(user_id=u.id, weight_lbs=200.0, log_date=date.today()))
        db.session.commit()
        expected = {mm.__tablename__ for n in dir(m)
                    for mm in [getattr(m, n)]
                    if isinstance(mm, type) and issubclass(mm, db.Model) and mm is not db.Model
                    and mm.__name__ != "GarminTokens"
                    and "user_id" in [c.key for c in inspect(mm).columns]}

    key = "export-test-key-long-enough-for-guard-01"
    monkeypatch.setenv("ADMIN_API_KEY", key)
    r = app_.test_client().get("/api/admin/export-full?email=export-full@example.com",
                               headers={"X-Admin-Key": key})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    d = r.get_json()
    assert set(d["tables"]) == expected
    assert "garmin_tokens" not in d["tables"]
    assert "password_hash" not in d["user"]
    assert d["tables"]["set_log"][0]["weight"] == 100
    assert d["tables"]["body_weight"][0]["weight_lbs"] == 200.0
