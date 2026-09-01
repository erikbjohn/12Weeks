"""tests/test_protocol_api.py — TDD for the user-facing protocol API:

  GET  /api/protocol/today
  POST /api/protocol/dose/<id>/toggle
  POST /api/protocol/dose/<id>/late
  POST /api/admin/add-vial
  POST /api/admin/complete-lab-reminder

"Today" is controlled by monkeypatching `appmod._user_today` (the
current_user-timezone helper — this endpoint family always runs under a
logged-in session, unlike the admin import endpoint's `_user_today_for`).
The real-clock gate in /late is controlled by monkeypatching a
module-level `appmod._utcnow` now-provider, never `datetime.now` itself.

User.timezone is set to "America/Los_Angeles" throughout, so a 07:00
local dose is 14:00 UTC (PDT, no DST edge in the dates used here).

NOTE on app-context handling: unlike most other test files in this repo,
this module's fixture deliberately does NOT hold an app context open
across test-client requests. flask-login caches the resolved current_user
on the active app context's `g`; when a context is already on the stack,
Flask's request dispatch reuses it instead of pushing a fresh one, so a
held-open module context leaks one client's (or one anonymous request's)
user into the next request — confirmed by direct repro: a second test
client logged in as a DIFFERENT user still received the first user's
data. tests/test_security_auth.py documents and avoids the same trap.
Every DB touch here therefore opens its own short-lived
`with app_.app_context():` block and returns plain values (ids, dicts),
never attached ORM objects, while client.get/post calls always run
with no app context held open so Flask pushes a correct, fresh one.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _app_do(app_, fn):
    with app_.app_context():
        return fn()


def _make_user(app_, db, email):
    def _do():
        from models import User, PeptideDose, PeptideVial, LabReminder
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Los_Angeles")
            db.session.add(u)
            db.session.commit()
        else:
            u.timezone = "America/Los_Angeles"
            db.session.commit()
        PeptideDose.query.filter_by(user_id=u.id).delete()
        PeptideVial.query.filter_by(user_id=u.id).delete()
        LabReminder.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _user_email(app_, user_id):
    def _do():
        from models import User
        return User.query.get(user_id).email
    return _app_do(app_, _do)


def _client_for(app_, user_id):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return client


def _anon_client(app_):
    return app_.test_client()


def _set_today(monkeypatch, d):
    import app as appmod
    monkeypatch.setattr(appmod, "_user_today", lambda: d)


def _set_now(monkeypatch, dt):
    import app as appmod
    monkeypatch.setattr(appmod, "_utcnow", lambda: dt)


def _admin_client(app_, monkeypatch, admin_key="test-admin-key-long-enough-for-guard-01"):
    monkeypatch.setenv("ADMIN_API_KEY", admin_key)
    return app_.test_client(), admin_key


def _add_dose(app_, db, user_id, d, time_s, event_type, compound, dose_mg,
              syringe="10u", site="Thigh", notes=None, taken_at=None):
    def _do():
        from models import PeptideDose
        row = PeptideDose(
            user_id=user_id, date=d, time=time_s, event_type=event_type,
            compound=compound, dose_mg=dose_mg, syringe_units=syringe,
            site=site, notes=notes, taken_at=taken_at,
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    return _app_do(app_, _do)


def _dose_taken_at(app_, dose_id):
    def _do():
        from models import PeptideDose
        return PeptideDose.query.get(dose_id).taken_at
    return _app_do(app_, _do)


def _add_vial(app_, db, user_id, compound, total_mg, reconstituted_on, expiry_days):
    def _do():
        from models import PeptideVial
        v = PeptideVial(user_id=user_id, compound=compound, total_mg=total_mg,
                         reconstituted_on=reconstituted_on, expiry_days=expiry_days)
        db.session.add(v)
        db.session.commit()
        return v.id
    return _app_do(app_, _do)


def _vial_fields(app_, vial_id):
    def _do():
        from models import PeptideVial
        v = PeptideVial.query.get(vial_id)
        return dict(user_id=v.user_id, compound=v.compound, total_mg=v.total_mg,
                    reconstituted_on=v.reconstituted_on, expiry_days=v.expiry_days,
                    notes=v.notes)
    return _app_do(app_, _do)


def _add_lab(app_, db, user_id, label, due_date):
    def _do():
        from models import LabReminder
        l = LabReminder(user_id=user_id, label=label, due_date=due_date)
        db.session.add(l)
        db.session.commit()
        return l.id
    return _app_do(app_, _do)


def _lab_completed_at(app_, lab_id):
    def _do():
        from models import LabReminder
        return LabReminder.query.get(lab_id).completed_at
    return _app_do(app_, _do)


# ── (a) today payload: all 5 real 2026-08-10 doses, incl. the oral ──────────

def test_today_payload_lists_all_seeded_doses_sorted_by_time(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "today-a@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)

    _add_dose(app_, db, uid, d, "07:00", "Oral", "Enclomiphene", 6.25, syringe=None, notes="Take with breakfast")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25, syringe="10u", site="Thigh")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "KPV", 1, syringe="10u", site="Love handle")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "Retatrutide", 2, syringe="20u", site="Abdomen")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "TB-500", 2.5, syringe="25u", site="Thigh (opposite)")

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()

    assert body["date"] == "2026-08-10"
    assert len(body["doses"]) == 5
    compounds = {dd["compound"] for dd in body["doses"]}
    assert compounds == {"Enclomiphene", "BPC-157", "KPV", "Retatrutide", "TB-500"}
    assert all(dd["taken"] is False for dd in body["doses"])
    oral = next(dd for dd in body["doses"] if dd["compound"] == "Enclomiphene")
    assert oral["event_type"] == "Oral"
    assert oral["dose_mg"] == 6.25
    for dd in body["doses"]:
        assert set(dd.keys()) == {"id", "time", "event_type", "compound", "dose_mg",
                                   "syringe_units", "site", "notes", "taken", "change"}
    times = [dd["time"] for dd in body["doses"]]
    assert times == sorted(times)


def test_today_payload_requires_login(app_ctx):
    app_, db = app_ctx
    client = _anon_client(app_)
    r = client.get("/api/protocol/today")
    assert r.status_code == 401


# ── (i) payload never leaks PROTOCOL_COMPOUNDS reference content ────────────

def test_today_payload_never_leaks_watch_fors_or_mechanism(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "today-leak@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25)

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    assert r.status_code == 200
    blob = json.dumps(r.get_json())
    assert "watch_fors" not in blob
    assert "mechanism" not in blob


# ── (b) toggle on/off sets/clears taken_at, persists across a re-GET ────────

def test_toggle_on_then_off_persists_across_reget(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "toggle-b@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)
    dose_id = _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25)
    client = _client_for(app_, uid)

    r_on = client.post(f"/api/protocol/dose/{dose_id}/toggle", json={"taken": True})
    assert r_on.status_code == 200, r_on.get_data(as_text=True)
    assert r_on.get_json() == {"taken": True}

    r_get = client.get("/api/protocol/today")
    dose = next(dd for dd in r_get.get_json()["doses"] if dd["id"] == dose_id)
    assert dose["taken"] is True

    r_off = client.post(f"/api/protocol/dose/{dose_id}/toggle", json={"taken": False})
    assert r_off.status_code == 200
    assert r_off.get_json() == {"taken": False}

    r_get2 = client.get("/api/protocol/today")
    dose2 = next(dd for dd in r_get2.get_json()["doses"] if dd["id"] == dose_id)
    assert dose2["taken"] is False

    assert _dose_taken_at(app_, dose_id) is None


# ── (c) toggle write-gate: 400 on 3-days-ago and future; 404 cross-user ─────

def test_toggle_rejects_dose_three_days_ago_and_future(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "toggle-c@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)

    old_id = _add_dose(app_, db, uid, today - timedelta(days=3), "07:00", "Injection", "BPC-157", 0.25)
    future_id = _add_dose(app_, db, uid, today + timedelta(days=1), "07:00", "Injection", "BPC-157", 0.25)
    client = _client_for(app_, uid)

    r_old = client.post(f"/api/protocol/dose/{old_id}/toggle", json={"taken": True})
    assert r_old.status_code == 400

    r_future = client.post(f"/api/protocol/dose/{future_id}/toggle", json={"taken": True})
    assert r_future.status_code == 400


def test_toggle_404s_on_another_users_dose(app_ctx, monkeypatch):
    app_, db = app_ctx
    owner_id = _make_user(app_, db, "toggle-owner@test.com")
    other_id = _make_user(app_, db, "toggle-other@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    dose_id = _add_dose(app_, db, owner_id, today, "07:00", "Injection", "BPC-157", 0.25)

    other_client = _client_for(app_, other_id)
    r = other_client.post(f"/api/protocol/dose/{dose_id}/toggle", json={"taken": True})
    assert r.status_code == 404


def test_toggle_404s_on_unknown_dose_id(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "toggle-unknown@test.com")
    _set_today(monkeypatch, date(2026, 8, 10))
    client = _client_for(app_, uid)
    r = client.post("/api/protocol/dose/999999/toggle", json={"taken": True})
    assert r.status_code == 404


# ── (d) NEXT-MORNING RETRO: yesterday's dose toggles on and drops from missed ─

def test_next_morning_retro_toggle_clears_missed(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "retro-d@test.com")
    today = date(2026, 8, 10)
    yesterday = today - timedelta(days=1)
    _set_today(monkeypatch, today)

    dose_id = _add_dose(app_, db, uid, yesterday, "22:00", "Injection", "Tesamorelin", 2)
    client = _client_for(app_, uid)

    r_before = client.get("/api/protocol/today")
    missed_before = r_before.get_json()["missed"]
    assert any(m["compound"] == "Tesamorelin" and m["date"] == yesterday.isoformat()
               for m in missed_before)
    assert next(m for m in missed_before if m["compound"] == "Tesamorelin")["action"] == "retro_mark"

    r_toggle = client.post(f"/api/protocol/dose/{dose_id}/toggle", json={"taken": True})
    assert r_toggle.status_code == 200
    assert r_toggle.get_json() == {"taken": True}

    r_after = client.get("/api/protocol/today")
    missed_after = r_after.get_json()["missed"]
    assert not any(m["compound"] == "Tesamorelin" for m in missed_after)


# ── (e) /late with null window → exactly "confirm with your doctor" ─────────

def test_late_null_window_is_403_confirm_with_doctor(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "late-e@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    old_id = _add_dose(app_, db, uid, today - timedelta(days=3), "07:00", "Injection", "BPC-157", 0.25)
    client = _client_for(app_, uid)

    r = client.post(f"/api/protocol/dose/{old_id}/late")
    assert r.status_code == 403
    assert r.get_json() == {"error": "confirm with your doctor"}
    assert _dose_taken_at(app_, old_id) is None


def test_late_rejects_dose_not_older_than_yesterday(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "late-notold@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    yesterday_id = _add_dose(app_, db, uid, today - timedelta(days=1), "07:00", "Injection", "BPC-157", 0.25)
    today_id = _add_dose(app_, db, uid, today, "07:00", "Injection", "BPC-157", 1)
    client = _client_for(app_, uid)

    r1 = client.post(f"/api/protocol/dose/{yesterday_id}/late")
    assert r1.status_code == 400

    r2 = client.post(f"/api/protocol/dose/{today_id}/late")
    assert r2.status_code == 400


# ── (f) /late with a doctor-confirmed window: within succeeds, beyond 400 ───

def test_late_within_monkeypatched_window_succeeds(app_ctx, monkeypatch):
    import protocol
    app_, db = app_ctx
    uid = _make_user(app_, db, "late-f-within@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    monkeypatch.setitem(protocol.PROTOCOL_COMPOUNDS["KPV"], "late_window_hours", 96)

    # 2026-08-06 07:00 America/Los_Angeles (PDT, UTC-7) == 2026-08-06 14:00 UTC.
    # allowed until 2026-08-06 14:00 UTC + 96h == 2026-08-10 14:00 UTC.
    dose_id = _add_dose(app_, db, uid, date(2026, 8, 6), "07:00", "Injection", "KPV", 1)
    _set_now(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc))  # within window
    client = _client_for(app_, uid)

    r = client.post(f"/api/protocol/dose/{dose_id}/late")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {"taken": True, "late": True}

    taken_at = _dose_taken_at(app_, dose_id)
    assert taken_at is not None
    assert taken_at.replace(tzinfo=timezone.utc) == datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)


def test_late_beyond_monkeypatched_window_is_400(app_ctx, monkeypatch):
    import protocol
    app_, db = app_ctx
    uid = _make_user(app_, db, "late-f-beyond@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    monkeypatch.setitem(protocol.PROTOCOL_COMPOUNDS["KPV"], "late_window_hours", 96)

    dose_id = _add_dose(app_, db, uid, date(2026, 8, 6), "07:00", "Injection", "KPV", 1)
    _set_now(monkeypatch, datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc))  # beyond window
    client = _client_for(app_, uid)

    r = client.post(f"/api/protocol/dose/{dose_id}/late")
    assert r.status_code == 400

    assert _dose_taken_at(app_, dose_id) is None


def test_late_404s_on_another_users_dose(app_ctx, monkeypatch):
    import protocol
    app_, db = app_ctx
    owner_id = _make_user(app_, db, "late-owner@test.com")
    other_id = _make_user(app_, db, "late-other@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    monkeypatch.setitem(protocol.PROTOCOL_COMPOUNDS["KPV"], "late_window_hours", 96)
    dose_id = _add_dose(app_, db, owner_id, date(2026, 8, 6), "07:00", "Injection", "KPV", 1)

    other_client = _client_for(app_, other_id)
    r = other_client.post(f"/api/protocol/dose/{dose_id}/late")
    assert r.status_code == 404


def test_late_day_boundary_crossing_dose_uses_correct_utc_conversion(app_ctx, monkeypatch):
    """Pins the highest-risk case for the naive-local->UTC conversion: a
    22:00 America/Los_Angeles (PDT, UTC-7) dose whose scheduled UTC instant
    lands on the NEXT calendar day (2026-08-05 22:00 PDT == 2026-08-06 05:00
    UTC). All other /late tests use 07:00 doses, which don't cross midnight
    UTC and so can't distinguish a correct zoneinfo conversion from a naive
    one that treats the local wall-clock string as if it were already UTC.

    With late_window_hours=96, the CORRECT window is
    [2026-08-06 05:00 UTC, 2026-08-10 05:00 UTC]. A NAIVE (no-tz-conversion)
    implementation would instead compute
    [2026-08-05 22:00 UTC, 2026-08-09 22:00 UTC] -- a window that closes 7
    hours earlier.

    Assertion 1: frozen now = 2026-08-10 04:00 UTC sits inside the correct
    window but OUTSIDE the naive one, so success here only happens if the
    conversion is done correctly.
    Assertion 2 (same dose, clock advanced): frozen now = 2026-08-10 06:00
    UTC is just past the CORRECT window's end -> 400, confirming the gate
    actually closes and isn't just always-open."""
    import protocol
    app_, db = app_ctx
    uid = _make_user(app_, db, "late-boundary@test.com")
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)
    monkeypatch.setitem(protocol.PROTOCOL_COMPOUNDS["Tesamorelin"], "late_window_hours", 96)

    dose_id = _add_dose(app_, db, uid, date(2026, 8, 5), "22:00", "Injection", "Tesamorelin", 2)
    client = _client_for(app_, uid)

    # Inside the CORRECT window (2026-08-06 05:00 UTC + 96h = 2026-08-10
    # 05:00 UTC), but past the NAIVE window's end (2026-08-05 22:00 UTC +
    # 96h = 2026-08-09 22:00 UTC) -- discriminates correct vs. naive.
    _set_now(monkeypatch, datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc))
    r1 = client.post(f"/api/protocol/dose/{dose_id}/late")
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert r1.get_json() == {"taken": True, "late": True}
    taken_at = _dose_taken_at(app_, dose_id)
    assert taken_at.replace(tzinfo=timezone.utc) == datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc)

    # Clock advances past the CORRECT window's end (05:00 UTC) -> 400. The
    # window check runs independent of taken_at, so re-posting the same
    # dose still exercises the boundary itself.
    _set_now(monkeypatch, datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc))
    r2 = client.post(f"/api/protocol/dose/{dose_id}/late")
    assert r2.status_code == 400


# ── (g) fasting_bound: "20:00" iff a >=21:00 dose exists today, else None ───

def test_fasting_bound_present_when_late_dose_scheduled(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "fasting-g-yes@test.com")
    d = date(2026, 10, 5)
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "22:00", "Injection", "Tesamorelin", 2, notes="Fasted - 2+ hours after last meal")
    client = _client_for(app_, uid)

    r = client.get("/api/protocol/today")
    assert r.status_code == 200
    assert r.get_json()["fasting_bound"] == "20:00"


def test_fasting_bound_absent_without_late_dose(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "fasting-g-no@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25)
    client = _client_for(app_, uid)

    r = client.get("/api/protocol/today")
    assert r.status_code == 200
    assert r.get_json()["fasting_bound"] is None


# ── (h) vials + labs_due surface correctly ───────────────────────────────────

def test_vials_surface_in_today_payload(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "vials-h@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)
    _add_vial(app_, db, uid, "BPC-157", 10.0, date(2026, 8, 1), 28)
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25)
    client = _client_for(app_, uid)

    r = client.get("/api/protocol/today")
    body = r.get_json()
    assert len(body["vials"]) == 1
    v = body["vials"][0]
    assert v["compound"] == "BPC-157"
    assert isinstance(v["runout_date"], str)
    assert isinstance(v["reorder_by"], str)
    assert "mg_remaining" in v and "doses_left" in v and "reorder_flag" in v


def test_labs_due_within_window_and_disappears_after_admin_complete(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "labs-h@test.com")
    email = _user_email(app_, uid)
    today = date(2026, 8, 10)
    _set_today(monkeypatch, today)

    due_soon_id = _add_lab(app_, db, uid, "Lipid panel", today + timedelta(days=3))
    _add_lab(app_, db, uid, "Far-out panel", today + timedelta(days=30))

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    labs_due = r.get_json()["labs_due"]
    labels = {l["label"] for l in labs_due}
    assert "Lipid panel" in labels
    assert "Far-out panel" not in labels
    for l in labs_due:
        assert set(l.keys()) == {"id", "label", "due_date"}

    admin_client, admin_key = _admin_client(app_, monkeypatch)
    r_complete = admin_client.post(
        "/api/admin/complete-lab-reminder",
        json={"email": email, "reminder_id": due_soon_id},
        headers={"X-Admin-Key": admin_key},
    )
    assert r_complete.status_code == 200, r_complete.get_data(as_text=True)

    r2 = client.get("/api/protocol/today")
    labels2 = {l["label"] for l in r2.get_json()["labs_due"]}
    assert "Lipid panel" not in labels2

    assert _lab_completed_at(app_, due_soon_id) is not None


def test_complete_lab_reminder_404s_unknown_email_and_unknown_reminder(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "labs-404@test.com")
    email = _user_email(app_, uid)
    admin_client, admin_key = _admin_client(app_, monkeypatch)

    r1 = admin_client.post(
        "/api/admin/complete-lab-reminder",
        json={"email": "nonexistent@test.com", "reminder_id": 1},
        headers={"X-Admin-Key": admin_key},
    )
    assert r1.status_code == 404

    r2 = admin_client.post(
        "/api/admin/complete-lab-reminder",
        json={"email": email, "reminder_id": 999999},
        headers={"X-Admin-Key": admin_key},
    )
    assert r2.status_code == 404


# ── /api/admin/add-vial ──────────────────────────────────────────────────────

def test_admin_add_vial_creates_and_returns_id(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "addvial@test.com")
    email = _user_email(app_, uid)
    admin_client, admin_key = _admin_client(app_, monkeypatch)

    r = admin_client.post(
        "/api/admin/add-vial",
        json={"email": email, "compound": "BPC-157", "total_mg": 10.0,
              "reconstituted_on": "2026-08-01", "expiry_days": 28, "notes": "fresh"},
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert "id" in body

    fields = _vial_fields(app_, body["id"])
    assert fields["user_id"] == uid
    assert fields["compound"] == "BPC-157"
    assert fields["total_mg"] == 10.0
    assert fields["reconstituted_on"] == date(2026, 8, 1)
    assert fields["expiry_days"] == 28
    assert fields["notes"] == "fresh"


def test_admin_add_vial_404s_unknown_email(app_ctx, monkeypatch):
    app_, db = app_ctx
    admin_client, admin_key = _admin_client(app_, monkeypatch)
    r = admin_client.post(
        "/api/admin/add-vial",
        json={"email": "nonexistent@test.com", "compound": "BPC-157", "total_mg": 10.0,
              "reconstituted_on": "2026-08-01", "expiry_days": 28},
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 404


def test_admin_add_vial_400s_on_missing_fields(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "addvial-missing@test.com")
    email = _user_email(app_, uid)
    admin_client, admin_key = _admin_client(app_, monkeypatch)
    r = admin_client.post(
        "/api/admin/add-vial",
        json={"email": email, "compound": "BPC-157"},
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 400
