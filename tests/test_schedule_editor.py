"""In-app schedule editor + CSV export (2026-09-03): the database is the
source of truth. Edits write the rows AND the change log with the reason;
taken rows keep their dose; past dates are untouched unless asked."""
from datetime import date, datetime, timedelta
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _seed(db, email):
    from models import User, PeptideDose, PeptideDoseHistory
    import protocol_history as ph
    u = User.query.filter_by(email=email).first() or User(email=email)
    db.session.add(u); db.session.commit()
    PeptideDose.query.filter_by(user_id=u.id).delete(); PeptideDoseHistory.query.filter_by(user_id=u.id).delete()
    ph.set_source("seed", None)
    for i in range(-2, 8):   # 2 past, 8 from today on
        db.session.add(PeptideDose(user_id=u.id, date=date(2026, 9, 3) + timedelta(days=i), time="07:00",
                                   event_type="Injection", compound="BPC-157", dose_mg=0.25, syringe_units="10u",
                                   taken_at=(datetime(2026, 9, 1, 14) if i < 0 else None)))
    db.session.commit()
    return u


def _client(app_, u):
    # the module-scoped app context keeps flask-login's cached user on g
    # between test clients — drop it so each client is its own athlete
    from flask import g
    g.pop("_login_user", None)
    c = app_.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(u.id); sess["_fresh"] = True
    return c


def test_update_range_writes_rows_and_history_with_reason(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from models import PeptideDose, PeptideDoseHistory
    u = _seed(db, "sched-update@test.com")
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 9, 3))
    c = _client(app_, u)
    r = c.post("/api/protocol/schedule/edit", json={"mode": "update", "compound": "BPC-157", "from_date": "2026-09-01",
                                                    "to_date": "2026-09-30", "dose_mg": 0.5, "syringe_units": "20u", "reason": "stay at 0.5"})
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["changed"] == 8 and j["created"] == 0 and j["deleted"] == 0
    assert any("past date" in s["reason"] for s in j["skipped"])   # the two past rows left alone
    rows = {x.date: x for x in PeptideDose.query.filter_by(user_id=u.id).all()}
    assert rows[date(2026, 9, 3)].dose_mg == 0.5 and rows[date(2026, 9, 1)].dose_mg == 0.25
    h = PeptideDoseHistory.query.filter_by(user_id=u.id, source="schedule_edit").all()
    assert len(h) == 16 and all(x.reason == "stay at 0.5" for x in h)
    assert {(x.field, x.old_value, x.new_value) for x in h} == {("dose_mg", "0.25", "0.5"), ("syringe_units", "10u", "20u")}


def test_reason_required_and_taken_rows_keep_dose(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from models import PeptideDose
    u = _seed(db, "sched-taken@test.com")
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 9, 3))
    c = _client(app_, u)
    assert c.post("/api/protocol/schedule/edit", json={"mode": "update", "compound": "BPC-157", "from_date": "2026-09-01",
                                                       "to_date": "2026-09-02", "dose_mg": 1}).status_code == 400
    r = c.post("/api/protocol/schedule/edit", json={"mode": "update", "compound": "BPC-157", "from_date": "2026-09-01",
                                                    "to_date": "2026-09-02", "dose_mg": 1, "notes": "hi", "reason": "x", "include_past": True})
    j = r.get_json()
    assert j["changed"] == 2 and any("immutable" in s["reason"] for s in j["skipped"])
    row = PeptideDose.query.filter_by(user_id=u.id, date=date(2026, 9, 1)).first()
    assert row.dose_mg == 0.25 and row.notes == "hi"


def test_add_remove_and_dry_run(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    from models import PeptideDose
    u = _seed(db, "sched-add@test.com")
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 9, 3))
    c = _client(app_, u)
    # add KPV Mon/Wed/Fri for two weeks — dry run first
    body = {"mode": "add", "compound": "KPV", "from_date": "2026-09-07", "to_date": "2026-09-20", "weekdays": [0, 2, 4],
            "time": "07:00", "dose_mg": 1, "syringe_units": "10u", "reason": "restart KPV"}
    j = c.post("/api/protocol/schedule/edit", json=dict(body, dry_run=True)).get_json()
    assert j["dry_run"] and j["created"] == 6
    assert PeptideDose.query.filter_by(user_id=u.id, compound="KPV").count() == 0
    j = c.post("/api/protocol/schedule/edit", json=body).get_json()
    assert j["created"] == 6 and PeptideDose.query.filter_by(user_id=u.id, compound="KPV").count() == 6
    # adding again skips existing rows
    assert c.post("/api/protocol/schedule/edit", json=body).get_json()["created"] == 0
    # remove BPC from Sep 8 on; the two taken past rows are never removed even with include_past
    j = c.post("/api/protocol/schedule/edit", json={"mode": "remove", "compound": "BPC-157", "from_date": "2026-09-01",
                                                    "to_date": "2026-09-30", "reason": "stop", "include_past": True}).get_json()
    assert j["deleted"] == 8 and sum(1 for s in j["skipped"] if "taken" in s["reason"]) == 2
    assert PeptideDose.query.filter_by(user_id=u.id, compound="BPC-157").count() == 2


def test_export_csv_comes_from_the_database(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    u = _seed(db, "sched-export@test.com")
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 9, 3))
    c = _client(app_, u)
    r = c.get("/api/protocol/export.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    lines = text.strip().split("\r\n")
    assert lines[0] == "Date,Time,Event_Type,Compound,Dose_mg,Syringe_Units,Site,Notes,Taken_At"
    assert len(lines) == 11 and lines[1].startswith("2026-09-01,07:00,Injection,BPC-157,0.25,10u,,,2026-09-01T14:00:00")


def test_import_route_is_restore_only(app_ctx, monkeypatch):
    app_, db = app_ctx
    u = _seed(db, "sched-restore@test.com")
    key = "restore-key-long-enough-for-the-guard-01"
    monkeypatch.setenv("ADMIN_API_KEY", key)
    c = app_.test_client()
    r = c.post(f"/api/admin/import-protocol?email={u.email}", json={}, headers={"X-Admin-Key": key})
    assert r.status_code == 400 and "source of truth" in r.get_json()["error"]
