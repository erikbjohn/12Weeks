"""peptide_dose change log (2026-09-03): every write path leaves a row in
peptide_dose_history with old/new value, time, source and reason — the
athlete tap, a CSV import update/delete, raw admin SQL — and GET
/api/protocol/history groups them into readable lines."""
from datetime import date, datetime
import json
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _user(db, email):
    from models import User, PeptideDose, PeptideDoseHistory
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email); db.session.add(u); db.session.commit()
    PeptideDose.query.filter_by(user_id=u.id).delete()
    PeptideDoseHistory.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return u


def _hist(db, uid):
    from models import PeptideDoseHistory
    return PeptideDoseHistory.query.filter_by(user_id=uid).order_by(PeptideDoseHistory.id).all()


def test_insert_update_delete_are_logged_by_the_flush_listener(app_ctx):
    app_, db = app_ctx
    from models import PeptideDose
    import protocol_history as ph
    u = _user(db, "hist-orm@test.com")
    ph.set_source("csv_import", "unit test")
    r = PeptideDose(user_id=u.id, date=date(2026, 9, 10), time="22:00", event_type="Injection",
                    compound="Tesamorelin", dose_mg=1.0, syringe_units="10u", site="Abdomen", notes="n")
    db.session.add(r); db.session.commit()
    h = _hist(db, u.id)
    assert len(h) == 1 and h[0].field == "row" and h[0].old_value is None and '"time": "22:00"' in h[0].new_value
    assert h[0].source == "csv_import" and h[0].reason == "unit test"

    r.time = "07:00"; r.notes = "moved"; db.session.commit()
    h = _hist(db, u.id)
    fields = {x.field: (x.old_value, x.new_value) for x in h[1:]}
    assert fields == {"time": ("22:00", "07:00"), "notes": ("n", "moved")}

    db.session.delete(r); db.session.commit()
    h = _hist(db, u.id)
    assert h[-1].field == "row" and h[-1].new_value is None and '"time": "07:00"' in h[-1].old_value
    assert h[-1].date == date(2026, 9, 10) and h[-1].compound == "Tesamorelin"


def test_athlete_toggle_logs_taken_at_with_source(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import PeptideDose
    from flask_login import login_user
    u = _user(db, "hist-toggle@test.com")
    import protocol_history as ph
    ph.set_source("seed", None)
    r = PeptideDose(user_id=u.id, date=date(2026, 9, 3), time="07:00", event_type="Injection",
                    compound="Tesamorelin", dose_mg=1.0)
    db.session.add(r); db.session.commit()
    import app as appmod
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 9, 3))
    with app_.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = str(u.id); sess["_fresh"] = True
        resp = c.post(f"/api/protocol/dose/{r.id}/toggle", json={"taken": True})
        assert resp.status_code == 200, resp.get_json()
    h = _hist(db, u.id)
    last = h[-1]
    assert last.field == "taken_at" and last.old_value is None and last.new_value
    assert last.source == "athlete_toggle" and last.reason == "taken"


def test_history_endpoint_groups_a_bulk_change_into_one_line(app_ctx):
    app_, db = app_ctx
    from models import PeptideDose
    import protocol_history as ph
    u = _user(db, "hist-group@test.com")
    ph.set_source("seed", None)
    for i in range(5):
        db.session.add(PeptideDose(user_id=u.id, date=date(2026, 9, 7 + i), time="22:00", event_type="Injection",
                                   compound="Tesamorelin", dose_mg=1.0))
    db.session.commit()
    ph.set_source("csv_import", "move to mornings")
    for r in PeptideDose.query.filter_by(user_id=u.id).all():
        r.time = "07:00"
    db.session.commit()
    top = ph.grouped_history(u.id)[0]
    assert top["field"] == "time" and top["old"] == "22:00" and top["new"] == "07:00"
    assert top["rows"] == 5 and top["from_date"] == "2026-09-07" and top["to_date"] == "2026-09-11"
    assert top["source"] == "csv_import" and top["reason"] == "move to mornings"


def test_raw_sql_snapshot_diff_logs_the_change(app_ctx):
    app_, db = app_ctx
    from models import PeptideDose
    import protocol_history as ph
    from sqlalchemy import text
    u = _user(db, "hist-sql@test.com")
    ph.set_source("seed", None)
    db.session.add(PeptideDose(user_id=u.id, date=date(2026, 9, 20), time="07:00", event_type="Injection",
                               compound="GHK-Cu", dose_mg=1.0, syringe_units="5u"))
    db.session.commit()
    before = ph.snapshot(u.id)
    db.session.execute(text("UPDATE peptide_dose SET dose_mg=2.0, syringe_units='10u' WHERE user_id=:u"), {"u": u.id})
    db.session.expire_all()
    n = ph.diff_snapshots(before, ph.snapshot(u.id), "admin_exec", "back to 2 mg")
    db.session.commit()
    assert n == 2
    h = [x for x in _hist(db, u.id) if x.source == "admin_exec"]
    assert {(x.field, x.old_value, x.new_value) for x in h} == {("dose_mg", "1", "2"), ("syringe_units", "5u", "10u")}


def test_backfill_is_idempotent(app_ctx, monkeypatch):
    app_, db = app_ctx
    u = _user(db, "hist-backfill@test.com")
    key = "history-backfill-key-long-enough-for-guard"
    monkeypatch.setenv("ADMIN_API_KEY", key)
    rows = [{"date": "2026-08-27", "compound": "GHK-Cu", "field": "dose_mg", "old_value": "1", "new_value": "2",
             "changed_at": "2026-08-27T15:00:00", "source": "admin_exec", "reason": "note in row"}]
    with app_.test_client() as c:
        r1 = c.post("/api/admin/protocol-history/backfill", json={"email": u.email, "rows": rows}, headers={"X-Admin-Key": key})
        r2 = c.post("/api/admin/protocol-history/backfill", json={"email": u.email, "rows": rows}, headers={"X-Admin-Key": key})
    assert r1.status_code == 200, r1.get_json()
    assert r1.get_json()["inserted"] == 1 and r2.get_json()["inserted"] == 0 and r2.get_json()["skipped"] == 1
    h = _hist(db, u.id)
    assert h[-1].source == "backfill:admin_exec"
