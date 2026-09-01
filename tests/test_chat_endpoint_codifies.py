"""S005: the non-streaming /api/chat must codify coach markers exactly like
the stream path does. It carries the Sunday 'Continue to Weekly Planning'
trigger and every popup trigger; before 2026-09-01 it saved the reply and
never called _parse_coach_markers, so announced changes never hit the card."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_api_chat_parses_markers(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import User, UserEquipment, PhysicalAssessment, AppState
    from datetime import date
    with app_.app_context():
        u = User(email="codify-test@example.com", password_hash="x", email_verified=True)
        db.session.add(u); db.session.commit()
        db.session.add(UserEquipment(user_id=u.id, available_equipment=["barbell"]))
        db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
        db.session.add(AppState(user_id=u.id, start_date=date.today()))
        db.session.commit()
        uid = u.id

    marker = "[SCHEDULE: day=2, time=3:00 PM, notes=moved lift to afternoon]"
    reply = f"Fine. Lift moves to 3 PM Wednesday. {marker}"
    import coach_with_tools
    monkeypatch.setattr(coach_with_tools, "coach_chat", lambda **kw: reply)

    seen = {}
    import app as app_module
    real = app_module._parse_coach_markers
    def spy(text, user_id, week):
        seen["text"], seen["user_id"] = text, user_id
        return real(text, user_id, week)
    monkeypatch.setattr(app_module, "_parse_coach_markers", spy)
    # memory extraction spawns a thread that would call the API — stub it
    monkeypatch.setattr(app_module, "extract_memories", lambda *a, **k: [])

    client = app_.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True; sess["_csrf_token"] = "tok"
    r = client.post("/api/chat", json={"message": "[WEEKLY_PLANNING] plan the week"},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert seen.get("text") == reply and seen.get("user_id") == uid
