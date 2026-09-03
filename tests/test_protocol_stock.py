"""Sealed-vial stock + supply projection (2026-09-03): Erik wants to know
WHEN TO REORDER, counting the open vial AND the sealed vials on the shelf
against the scheduled doses, and a place to record new purchases."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS
import pytest


def _doses(compound, start, n, mg, every=1):
    return [NS(compound=compound, date=start + timedelta(days=i * every), time="07:00", dose_mg=mg, taken_at=None)
            for i in range(n)]


def test_stock_covers_after_open_vial_and_flags_order_by():
    from protocol import stock_status
    today = date(2026, 9, 3)
    vial = NS(compound="GHK-Cu", total_mg=10.0, reconstituted_on=date(2026, 8, 25), expiry_days=28)
    stock = [NS(compound="GHK-Cu", vial_mg=50.0, quantity=1)]
    doses = _doses("GHK-Cu", today, 40, 2.0)   # 80 mg needed over 40 days
    out = stock_status([vial], stock, doses, today, lead_time_days=14)
    st = out[0]
    assert st["compound"] == "GHK-Cu" and st["open_mg"] == 10.0 and st["sealed_vials"] == 1
    # 10 mg open = 5 doses, then 50 mg sealed = 25 doses -> 30 covered, runout on dose 31
    assert st["doses_covered"] == 30 and st["runout_date"] == today + timedelta(days=30)
    assert st["reorder_by"] == today + timedelta(days=16) and st["status"] == "ok" and st["reorder_flag"] is False


def test_open_vial_expiry_hands_over_to_the_shelf():
    from protocol import stock_status
    today = date(2026, 9, 3)
    vial = NS(compound="BPC-157", total_mg=100.0, reconstituted_on=date(2026, 8, 10), expiry_days=28)  # expires 09-07
    stock = [NS(compound="BPC-157", vial_mg=5.0, quantity=1)]
    doses = _doses("BPC-157", today, 20, 0.5)
    st = stock_status([vial], stock, doses, today)[0]
    # 4 doses before expiry (09-03..09-06), then 10 doses from the 5 mg vial -> 14 covered
    assert st["doses_covered"] == 14 and st["runout_date"] == today + timedelta(days=14)
    assert st["status"] == "order_now" and st["reorder_flag"] is True


def test_no_supply_with_doses_scheduled_soon_is_flagged():
    from protocol import stock_status
    today = date(2026, 9, 3)
    doses = _doses("KPV", today + timedelta(days=3), 5, 0.5)
    st = stock_status([], [], doses, today)[0]
    assert st["status"] == "no_supply" and st["reorder_flag"] is True and st["runout_date"] == today + timedelta(days=3)


def test_full_coverage_reports_no_runout():
    from protocol import stock_status
    today = date(2026, 9, 3)
    stock = [NS(compound="TB-500", vial_mg=10.0, quantity=2)]
    doses = _doses("TB-500", today, 4, 2.5, every=7)
    st = stock_status([], stock, doses, today)[0]
    assert st["runout_date"] is None and st["doses_covered"] == 4 and st["status"] == "ok"
    assert st["last_dose_date"] == today + timedelta(days=21)


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_stock_api_add_open_and_projection(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import User, PeptideDose, PeptideVial, PeptideStock
    import app as appmod
    u = User.query.filter_by(email="stock@test.com").first() or User(email="stock@test.com")
    db.session.add(u); db.session.commit()
    for M in (PeptideDose, PeptideVial, PeptideStock):
        M.query.filter_by(user_id=u.id).delete()
    import protocol_history as ph; ph.set_source("seed", None)
    for i in range(10):
        db.session.add(PeptideDose(user_id=u.id, date=date(2026, 9, 3) + timedelta(days=i), time="07:00",
                                   event_type="Injection", compound="GHK-Cu", dose_mg=2.0))
    db.session.commit()
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 9, 3))
    with app_.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = str(u.id); sess["_fresh"] = True
        r = c.post("/api/protocol/stock", json={"compound": "GHK-Cu", "vial_mg": 50, "quantity": 2, "vendor": "Vendor X"})
        assert r.status_code == 200, r.get_json()
        sid = r.get_json()["id"]
        bad = c.post("/api/protocol/stock", json={"compound": "Nonsense", "vial_mg": 5})
        assert bad.status_code == 400
        g = c.get("/api/protocol/stock").get_json()
        st = [x for x in g["stock"] if x["compound"] == "GHK-Cu"][0]
        assert st["sealed_vials"] == 2 and st["open_mg"] == 0 and st["runout_date"] is None
        o = c.post(f"/api/protocol/stock/{sid}/open", json={})
        assert o.status_code == 200 and o.get_json()["sealed_left"] == 1
        g = c.get("/api/protocol/stock").get_json()
        st = [x for x in g["stock"] if x["compound"] == "GHK-Cu"][0]
        assert st["sealed_vials"] == 1 and st["open_mg"] == 50.0
        assert g["purchases"][0]["quantity"] == 1
        today = c.get("/api/protocol/today").get_json()
        assert "stock" in today and "purchases" in today
