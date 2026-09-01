"""tests/test_protocol_ui_payload.py — served-contract tests for the daily-
card Protocol section (static/app.js buildProtocolContent). JS has no test
runner in this repo, so every field/behavior buildProtocolContent reads off
GET /api/protocol/today is asserted here on the server side instead:

  (a) exactly 5 doses for a seeded 2026-08-10 user, each carrying every
      field the renderer reads (id/time/compound/dose_mg/syringe_units/
      site/notes/taken) plus `event_type`, asserted here as part of the
      served contract even though buildProtocolContent doesn't read it.
  (b) the payload never leaks PROTOCOL_COMPOUNDS reference content
      (watch_fors/mechanism) — card boundary rule.
  (c) fasting_bound is null on a plain 2026-08-10 day and "20:00" when a
      >=21:00 dose (Tesamorelin) is seeded on a monkeypatched "today".
  (d) missed entries carry an `id` (added at the app.py layer, NOT inside
      protocol.missed_line() whose return shape is pinned by
      tests/test_protocol_derivations.py) matching the real PeptideDose row,
      and that id actually works against /toggle — this is what makes the
      UI's "mark taken" button on a missed row functional at all.

NOTE on app-context handling: same short-lived-context fixture pattern as
tests/test_protocol_api.py (NOT the module-scoped held-open `app_ctx`
pattern most other test files use) — flask-login caches current_user on the
active app context's `g`, and a held-open context leaks one client's user
into the next request when multiple logged-in identities are exercised in
one module. See tests/test_protocol_api.py's docstring and
tests/test_security_auth.py for the original repro.
"""
import json
from datetime import date

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


def _client_for(app_, user_id):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return client


def _set_today(monkeypatch, d):
    import app as appmod
    monkeypatch.setattr(appmod, "_user_today", lambda: d)


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


# ── (a) exactly 5 doses, the full served contract per dose ──────────────────
# (event_type is part of the contract but NOT read by buildProtocolContent;
# everything else in this set is.)

DOSE_UI_FIELDS = {
    "id", "time", "event_type", "compound", "dose_mg",
    "syringe_units", "site", "notes", "taken", "change",
}


def test_today_payload_has_5_doses_with_all_ui_fields(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "ui-a@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)

    _add_dose(app_, db, uid, d, "07:00", "Oral", "Enclomiphene", 6.25,
              syringe=None, site=None, notes="Take with breakfast")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25,
              syringe="10u", site="Thigh", notes="Fresh 31G syringe")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "KPV", 1,
              syringe="10u", site="Love handle", notes="Separate syringe from BPC-157")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "Retatrutide", 2,
              syringe="20u", site="Abdomen", notes="Inject slowly 5-10sec")
    _add_dose(app_, db, uid, d, "07:00", "Injection", "TB-500", 2.5,
              syringe="25u", site="Thigh (opposite)", notes="Loading phase")

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()

    doses = body["doses"]
    assert len(doses) == 5
    for dd in doses:
        assert set(dd.keys()) == DOSE_UI_FIELDS
        # buildProtocolContent groups by `time` and interpolates dose_mg
        # directly — both must be present and non-null for every row.
        assert dd["time"] is not None
        assert dd["dose_mg"] is not None
        assert dd["compound"]
        assert isinstance(dd["taken"], bool)

    oral = next(dd for dd in doses if dd["compound"] == "Enclomiphene")
    assert oral["syringe_units"] is None
    assert oral["site"] is None
    assert oral["notes"] == "Take with breakfast"


# ── (b) no PROTOCOL_COMPOUNDS reference content leaks into the payload ──────

def test_today_payload_never_leaks_watch_fors_or_mechanism(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "ui-b@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25)

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    assert r.status_code == 200
    blob = json.dumps(r.get_json())
    assert "watch_fors" not in blob
    assert "mechanism" not in blob


# ── (c) fasting_bound: null on a plain day, "20:00" with a >=21:00 dose ─────

def test_fasting_bound_is_null_on_2026_08_10_with_only_morning_doses(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "ui-c-null@test.com")
    d = date(2026, 8, 10)
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "07:00", "Injection", "BPC-157", 0.25)

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    assert r.status_code == 200
    assert r.get_json()["fasting_bound"] is None


def test_fasting_bound_is_2000_when_tesamorelin_row_seeded_on_oct_5(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "ui-c-set@test.com")
    d = date(2026, 10, 5)
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "22:00", "Injection", "Tesamorelin", 2,
              notes="Fasted - 2+ hours after last meal")

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    assert r.status_code == 200
    body = r.get_json()
    assert body["fasting_bound"] == "20:00"
    # buildProtocolContent's fasting banner derives the triggering compound
    # from today's dose list (time >= "21:00") rather than hardcoding one —
    # confirm the data it needs for that is actually present.
    late = [dd for dd in body["doses"] if dd["time"] >= "21:00"]
    assert len(late) == 1
    assert late[0]["compound"] == "Tesamorelin"


# ── (d) missed entries carry a working `id` for the mark-taken button ───────

def test_missed_entry_carries_dose_id_that_works_against_toggle(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "ui-d@test.com")
    today = date(2026, 8, 10)
    yesterday = date(2026, 8, 9)
    _set_today(monkeypatch, today)
    dose_id = _add_dose(app_, db, uid, yesterday, "22:00", "Injection", "Tesamorelin", 2)

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/today")
    missed = r.get_json()["missed"]
    entry = next(m for m in missed if m["compound"] == "Tesamorelin")
    assert entry["action"] == "retro_mark"
    assert entry["id"] == dose_id

    r_toggle = client.post(f"/api/protocol/dose/{entry['id']}/toggle", json={"taken": True})
    assert r_toggle.status_code == 200
    assert r_toggle.get_json() == {"taken": True}

    r_after = client.get("/api/protocol/today")
    assert not any(m["compound"] == "Tesamorelin" for m in r_after.get_json()["missed"])


def test_date_param_serves_any_day_readonly_state(app_ctx, monkeypatch):
    """?date=YYYY-MM-DD returns that day's doses with is_today false and
    today-anchored blocks (missed/labs_due) suppressed — protocol is viewable
    on every card day, actionable only on today."""
    app_, db = app_ctx
    uid = _make_user(app_, db, "ui-dateparam@test.com")
    _set_today(monkeypatch, date(2026, 8, 10))
    _add_dose(app_, db, uid, date(2026, 8, 17), "07:00", "Injection",
              "Retatrutide", 2, syringe="20u", site="Abdomen", notes="wk2")
    client = _client_for(app_, uid)
    p = client.get("/api/protocol/today?date=2026-08-17").get_json()
    assert p["date"] == "2026-08-17"
    assert p["is_today"] is False
    assert len(p["doses"]) == 1 and p["doses"][0]["compound"] == "Retatrutide"
    assert p["missed"] == [] and p["labs_due"] == []
    today = client.get("/api/protocol/today").get_json()
    assert today["is_today"] is True
    assert client.get("/api/protocol/today?date=not-a-date").status_code == 400
