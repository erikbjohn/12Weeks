"""tests/test_protocol_calendar.py — TDD for GET /api/protocol/calendar,
the full-calendar view of a user's whole peptide protocol (design-from-
artifact rule: the user must be able to SEE the whole 12-week artifact he
uploaded, not just today's slice).

Fixture pattern mirrors tests/test_protocol_api.py: each DB touch opens its
own short-lived `with app_.app_context():` block and returns plain values
(never attached ORM objects); client.get/post calls run with no app context
held open so Flask pushes a correct, fresh one per request (see that file's
module docstring for why — a held-open context leaks current_user across
test clients).

Seed protocol (3 weeks, one dose-step + one frequency-step, verified by
running protocol.escalation_dates()/escalation_events() directly against
the same rows below — not hand-derived):
  2026-08-10 (Mon, wk1): Enclomiphene 06:00 (oral), Retatrutide 07:00 2mg,
                         BPC-157 19:00 0.25mg (taken)
  2026-08-17 (Mon, wk2): Retatrutide 07:00 2mg
  2026-08-20 (Thu, wk2): Retatrutide 07:00 2mg  -> FREQUENCY-STEP (1x/wk -> 2x/wk)
  2026-08-24 (Mon, wk3): Retatrutide 07:00 3mg  -> DOSE-STEP (2mg -> 3mg)
                         BPC-157 19:00 0mg (HELD)
Total: 7 rows.
"""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as Row

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
        from models import User, PeptideDose
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Los_Angeles")
            db.session.add(u)
            db.session.commit()
        else:
            u.timezone = "America/Los_Angeles"
            db.session.commit()
        PeptideDose.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
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


def _add_dose(app_, db, user_id, d, time_s, compound, dose_mg,
              event_type="Injection", taken_at=None):
    def _do():
        from models import PeptideDose
        row = PeptideDose(
            user_id=user_id, date=d, time=time_s, event_type=event_type,
            compound=compound, dose_mg=dose_mg, syringe_units="10u",
            site="Thigh", notes=None, taken_at=taken_at,
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    return _app_do(app_, _do)


# ── The seed protocol, expressed both as DB rows and as SimpleNamespace
# rows for direct comparison against protocol.py's pure functions. ─────────

_SEED = [
    # (date, time, compound, dose_mg, taken)
    (date(2026, 8, 10), "06:00", "Enclomiphene", 6.25, False),
    (date(2026, 8, 10), "07:00", "Retatrutide", 2, False),
    (date(2026, 8, 10), "19:00", "BPC-157", 0.25, True),
    (date(2026, 8, 17), "07:00", "Retatrutide", 2, False),
    (date(2026, 8, 20), "07:00", "Retatrutide", 2, False),   # frequency-step date
    (date(2026, 8, 24), "07:00", "Retatrutide", 3, False),   # dose-step date
    (date(2026, 8, 24), "19:00", "BPC-157", 0, False),       # held dose
]


def _seed_rows_as_namespaces():
    """The same rows as _SEED, shaped for protocol.py's pure functions
    (taken_at is irrelevant to escalation derivation, so always None here)."""
    return [Row(date=d, time=t, compound=c, dose_mg=mg, taken_at=None)
            for (d, t, c, mg, taken) in _SEED]


def _seed_protocol(app_, db, uid):
    ids = {}
    for (d, t, c, mg, taken) in _SEED:
        taken_at = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc) if taken else None
        dose_id = _add_dose(app_, db, uid, d, t, c, mg, taken_at=taken_at)
        ids[(d.isoformat(), t, c)] = dose_id
    return ids


# ── (a) days grouped correctly; count matches seeded rows; times ordered ────

def test_days_grouped_correctly_count_and_time_order(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-a@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 11))

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/calendar")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()

    days = body["days"]
    total = sum(len(v) for v in days.values())
    assert total == len(_SEED)

    assert set(days.keys()) == {"2026-08-10", "2026-08-17", "2026-08-20", "2026-08-24"}

    day1 = days["2026-08-10"]
    assert [d["time"] for d in day1] == ["06:00", "07:00", "19:00"]
    assert [d["compound"] for d in day1] == ["Enclomiphene", "Retatrutide", "BPC-157"]
    for d in day1:
        assert set(d.keys()) == {"compound", "dose_mg", "time", "taken", "event_type", "syringe_units", "site", "notes"}

    day3 = days["2026-08-24"]
    assert len(day3) == 2
    held = next(dd for dd in day3 if dd["compound"] == "BPC-157")
    assert held["dose_mg"] == 0  # held dose INCLUDED, not dropped


def test_calendar_requires_login(app_ctx):
    app_, db = app_ctx
    r = _anon_client(app_).get("/api/protocol/calendar")
    assert r.status_code == 401


# ── (b) taken flag true only for taken_at rows ───────────────────────────

def test_taken_flag_true_only_for_taken_at_rows(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-b@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 11))

    client = _client_for(app_, uid)
    body = client.get("/api/protocol/calendar").get_json()

    day1 = body["days"]["2026-08-10"]
    taken_by_compound = {dd["compound"]: dd["taken"] for dd in day1}
    assert taken_by_compound == {"Enclomiphene": False, "Retatrutide": False, "BPC-157": True}

    # No other row in the whole seed is taken.
    for iso, doses in body["days"].items():
        for dd in doses:
            if iso == "2026-08-10" and dd["compound"] == "BPC-157":
                continue
            assert dd["taken"] is False


# ── (c) escalations agree with protocol.escalation_dates (not re-derived) ───

def test_escalations_agree_with_protocol_escalation_dates(app_ctx, monkeypatch):
    import protocol
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-c@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 11))

    client = _client_for(app_, uid)
    body = client.get("/api/protocol/calendar").get_json()

    expected_dates = protocol.escalation_dates(_seed_rows_as_namespaces())
    resp_dates = [date.fromisoformat(e["date"]) for e in body["escalations"]]
    assert resp_dates == expected_dates
    assert expected_dates == [date(2026, 8, 20), date(2026, 8, 24)]  # sanity on the fixture itself

    expected_events = protocol.escalation_events(_seed_rows_as_namespaces())
    assert body["escalations"] == [
        {"date": e["date"].isoformat(), "kind": e["kind"], "detail": e["detail"]}
        for e in expected_events
    ]


# ── (d) next_change: before / on / after an escalation date ─────────────────

def test_next_change_before_first_escalation_names_it(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-d-before@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 15))  # before the Aug 20 frequency-step

    client = _client_for(app_, uid)
    body = client.get("/api/protocol/calendar").get_json()

    assert body["next_change"] is not None
    assert "Aug 20" in body["next_change"]
    assert "retatrutide" in body["next_change"].lower()
    assert "1×/wk" in body["next_change"] or "1x/wk" in body["next_change"].lower()


def test_next_change_on_escalation_date_excludes_that_date(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-d-on@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 20))  # itself a frequency-step date

    client = _client_for(app_, uid)
    body = client.get("/api/protocol/calendar").get_json()

    # Aug 20 (today) must be excluded -> next_change should name Aug 24 instead.
    assert body["next_change"] is not None
    assert "Aug 20" not in body["next_change"]
    assert "Aug 24" in body["next_change"]
    assert "2 mg" in body["next_change"] and "3 mg" in body["next_change"]


def test_next_change_after_all_escalations_is_null(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-d-after@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 25))  # after the last (Aug 24) escalation

    client = _client_for(app_, uid)
    body = client.get("/api/protocol/calendar").get_json()
    assert body["next_change"] is None


def test_next_change_on_the_last_escalation_date_is_also_null(app_ctx, monkeypatch):
    """Strictly-after semantics apply even to the LAST escalation date —
    there is nothing after it in this fixture, so next_change is null."""
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-d-lastdate@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 24))

    client = _client_for(app_, uid)
    body = client.get("/api/protocol/calendar").get_json()
    assert body["next_change"] is None


# ── (e) card-boundary rule: no mechanism/watch_fors text in the payload ─────

def test_payload_never_leaks_mechanism_or_watch_fors(app_ctx, monkeypatch):
    from protocol import PROTOCOL_COMPOUNDS
    app_, db = app_ctx
    uid = _make_user(app_, db, "cal-e@test.com")
    _seed_protocol(app_, db, uid)
    _set_today(monkeypatch, date(2026, 8, 11))

    client = _client_for(app_, uid)
    r = client.get("/api/protocol/calendar")
    blob = json.dumps(r.get_json())

    assert "mechanism" not in blob
    assert "watch_fors" not in blob
    # A known watch_fors phrase for a compound actually present in the seed
    # (Retatrutide) must not have leaked in either.
    known_watch_for = PROTOCOL_COMPOUNDS["Retatrutide"]["watch_fors"][0]
    assert known_watch_for not in blob


# ── (f) another user's doses never appear ────────────────────────────────

def test_another_users_doses_never_appear(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid_a = _make_user(app_, db, "cal-f-a@test.com")
    uid_b = _make_user(app_, db, "cal-f-b@test.com")
    _seed_protocol(app_, db, uid_a)
    # Same dates as user A, different compound, so any cross-contamination
    # is easy to detect (extra rows or wrong compound on a shared date).
    _add_dose(app_, db, uid_b, date(2026, 8, 10), "08:00", "GHK-Cu", 0.2)
    _add_dose(app_, db, uid_b, date(2026, 8, 24), "08:00", "Tesamorelin", 2)
    _set_today(monkeypatch, date(2026, 8, 11))

    client_a = _client_for(app_, uid_a)
    body_a = client_a.get("/api/protocol/calendar").get_json()
    total_a = sum(len(v) for v in body_a["days"].values())
    assert total_a == len(_SEED)
    for doses in body_a["days"].values():
        for dd in doses:
            assert dd["compound"] not in {"GHK-Cu", "Tesamorelin"}

    client_b = _client_for(app_, uid_b)
    body_b = client_b.get("/api/protocol/calendar").get_json()
    total_b = sum(len(v) for v in body_b["days"].values())
    assert total_b == 2
    compounds_b = {dd["compound"] for doses in body_b["days"].values() for dd in doses}
    assert compounds_b == {"GHK-Cu", "Tesamorelin"}
