"""S029: a marker whose write fails is recorded, surfaced once in chat, and
listed in the coach's <marker_outcomes> block."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_failed_marker_is_recorded_and_surfaced(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import User, CoachMarkerLog, WeeklyRunPlan
    import app as app_module
    u = User(email="markerlog@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    uid = u.id

    # make the RUN handler's write blow up
    def boom(*a, **k): raise RuntimeError("disk on fire")
    monkeypatch.setattr(WeeklyRunPlan, "query", property(lambda self: boom()), raising=False)
    raw = "[RUN: day=2, duration=40 min, type=z2, label=Zone 2 Easy, detail=40 easy, reason=x]"
    with app_.test_request_context():
        app_module._parse_coach_markers(raw, uid, 1)
    monkeypatch.undo()

    rows = CoachMarkerLog.query.filter_by(user_id=uid, status="failed").all()
    assert rows and rows[0].marker_type == "RUN" and "RUN" in rows[0].raw_marker

    from flask import g; g.pop("_login_user", None)
    c = app_.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    hist = c.get("/api/coach/today-history").get_json()
    flags = [m for m in hist if m.get("type") == "flag"]
    assert flags and "NOT applied" in flags[0]["content"]
    # surfaced once only
    assert not [m for m in c.get("/api/coach/today-history").get_json() if m.get("type") == "flag"]

    with app_.test_request_context():
        from flask_login import login_user
        login_user(u, force=True)
        import coach_assembler as ca
        sec = ca._build_marker_outcomes()
        assert sec["marker_outcomes"] and "RUN" in sec["marker_outcomes"][0]["marker"]
