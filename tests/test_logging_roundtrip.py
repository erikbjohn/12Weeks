"""End-to-end: the core user loop. Log a set through the REAL /api/sets endpoint,
then confirm it surfaces everywhere the user/coach looks — SetLog, the dashboard
lift chart (/api/progress), the day's sets endpoint, and the coach's tools — with
equipment-variant matching (log "DB Bench Press", see it under "Barbell Bench
Press"). This validates the workflow actually works, not just that code looks right.
"""
import json

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login(app_, db):
    from models import User, SetLog
    u = User.query.filter_by(email="roundtrip@test.com").first()
    if not u:
        u = User(email="roundtrip@test.com")
        db.session.add(u); db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)
        s["_fresh"] = True
    return u, client


def test_logged_set_surfaces_across_every_view(app_ctx):
    app_, db = app_ctx
    from models import SetLog
    u, client = _login(app_, db)

    # 1. LOG a set through the real endpoint the UI calls.
    r = client.post("/api/sets", json={
        "exercise": "DB Bench Press", "week": 1, "day_idx": 1,
        "set_number": 0, "weight": 155, "reps": 5, "done": True})
    assert r.status_code == 200, r.get_data(as_text=True)

    # 2. PERSISTED in SetLog (the live table).
    assert SetLog.query.filter_by(user_id=u.id, week=1, day_idx=1).count() == 1

    # 3. Reads back through the day's-sets endpoint.
    day = client.get("/api/sets/1/1")
    assert day.status_code == 200, day.get_data(as_text=True)
    assert "155" in day.get_data(as_text=True) or any(
        s.get("weight") == 155
        for v in (day.get_json() or {}).values() if isinstance(v, list)
        for s in v if isinstance(s, dict))

    # 4. Shows on the DASHBOARD lift chart — under the BARBELL key via movement match.
    prog = client.get("/api/progress")
    assert prog.status_code == 200, prog.get_data(as_text=True)
    lifts = prog.get_json().get("lifts", {})
    bench = lifts.get("Barbell Bench Press", [])
    assert any(e.get("weight") == 155 for e in bench), \
        f"logged 155 not on dashboard bench chart: {bench}"

    # 5. The COACH sees it: recent-sets tool finds the logged set by the
    #    archetype name (the bug that started this — coach said 'no bench logged').
    import coach_tools
    from flask_login import login_user
    with app_.test_request_context():
        login_user(u, force=True)
        rs = json.loads(coach_tools._tool_get_recent_sets(u.id, "Barbell Bench Press"))
        assert any(st["weight"] == 155 for st in rs["sets"]), rs
