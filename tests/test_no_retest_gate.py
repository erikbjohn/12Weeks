"""The week-12 bodyweight retest must NOT gate the app. It hard-locked the entire
UI at week 12 (no dashboard/coach/settings until a 4x60s test was done, no escape).
Erik removed it (RETEST_WEEKS = ()). The status endpoint must never report a retest
due_and_pending, so the frontend gate (which returns before renderAll) never fires.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_retest_weeks_is_empty():
    import app as appmod
    assert appmod.RETEST_WEEKS == ()


def test_status_never_due_even_at_week_12(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from models import User
    u = User.query.filter_by(email="no-retest@test.com").first()
    if not u:
        u = User(email="no-retest@test.com")
        db.session.add(u); db.session.commit()
    monkeypatch.setattr(appmod, "_current_week", lambda: 12)
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)
        s["_fresh"] = True
    data = client.get("/api/bodyweight-retest/status").get_json()
    assert data["due_week"] is None
    assert data["due_and_pending"] is False
