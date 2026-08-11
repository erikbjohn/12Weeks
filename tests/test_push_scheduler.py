"""tests/test_push_scheduler.py — TDD for the push scheduler daemon (Task 3
of the engagement-features plan):

  app._push_scheduler_tick() -> list[(user_id, kind)]
  app._morning_brief_body(uid, local_date) -> str
  app._dose_night_body(uid, local_date) -> str | None
  app._sunday_recap_push(uid, local_date) -> str | None  (STUB, Task 7 fills in)

Windows are evaluated in the TARGET USER's own local time (zoneinfo, never a
fixed offset) against a mockable `appmod._utcnow()` now-provider — the same
seam tests/test_protocol_api.py freezes via
`monkeypatch.setattr(appmod, "_utcnow", ...)`.

NOTE on app-context handling: follows tests/test_push_foundation.py /
tests/test_protocol_api.py — every DB touch opens its own short-lived
`with app_.app_context():` block (via `_app_do`), never holding a context
open across calls, to avoid flask-login's current_user-on-`g` leak trap
documented in tests/test_security_auth.py. `app.push_to_user` is
monkeypatched in every test that reaches a real send, so no
network/pywebpush/VAPID work ever happens here.

NOTE on cross-test isolation: `app_ctx` is module-scoped (one shared DB
across every test below), so `_push_scheduler_tick()` calls made by a later
test also re-examine users subscribed by earlier tests in this file. That's
harmless — the tick is idempotent per (user, kind, date) and every
assertion below is scoped to the test's OWN user_id via `_calls_for()` /
`_pushsent_rows()` (both filtered by user_id) — but it does mean raw
`len(calls)` assertions across the WHOLE captured call list would be wrong;
always filter first.
"""
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def _make_user(app_, db, email, tz="America/Los_Angeles"):
    def _do():
        from models import (User, PushSubscription, PushSent, PeptideDose,
                             BodyWeight, AppState, WeeklyDaySchedule, WeeklyRunPlan)
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone=tz)
            db.session.add(u)
            db.session.commit()
        else:
            u.timezone = tz
            db.session.commit()
        PushSubscription.query.filter_by(user_id=u.id).delete()
        PushSent.query.filter_by(user_id=u.id).delete()
        PeptideDose.query.filter_by(user_id=u.id).delete()
        BodyWeight.query.filter_by(user_id=u.id).delete()
        AppState.query.filter_by(user_id=u.id).delete()
        WeeklyDaySchedule.query.filter_by(user_id=u.id).delete()
        WeeklyRunPlan.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _subscribe(app_, db, uid, endpoint=None):
    def _do():
        from models import PushSubscription
        db.session.add(PushSubscription(
            user_id=uid, endpoint=endpoint or f"https://push.example.com/sched-{uid}",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        ))
        db.session.commit()
    _app_do(app_, _do)


def _add_dose(app_, db, uid, d, compound, time_str, taken=False, dose_mg=1.0):
    def _do():
        from models import PeptideDose
        db.session.add(PeptideDose(
            user_id=uid, date=d, time=time_str, event_type="Injection",
            compound=compound, dose_mg=dose_mg,
            taken_at=(datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
                      if taken else None),
        ))
        db.session.commit()
    _app_do(app_, _do)


def _seed_appstate(app_, db, uid, start_date):
    def _do():
        from models import AppState
        db.session.add(AppState(user_id=uid, start_date=start_date, current_week=1))
        db.session.commit()
    _app_do(app_, _do)


def _seed_day_schedule(app_, db, uid, week, day_idx, lift_name=None, is_rest=False):
    def _do():
        from models import WeeklyDaySchedule
        db.session.add(WeeklyDaySchedule(
            user_id=uid, week=week, day_idx=day_idx, lift_name=lift_name, is_rest=is_rest))
        db.session.commit()
    _app_do(app_, _do)


def _seed_run_plan(app_, db, uid, week, day_idx, label, duration):
    def _do():
        from models import WeeklyRunPlan
        db.session.add(WeeklyRunPlan(
            user_id=uid, week=week, day_idx=day_idx, run_type="z2",
            label=label, duration=duration))
        db.session.commit()
    _app_do(app_, _do)


def _seed_bodyweight(app_, db, uid, d, lbs=200.0):
    def _do():
        from models import BodyWeight
        db.session.add(BodyWeight(user_id=uid, log_date=d, weight_lbs=lbs))
        db.session.commit()
    _app_do(app_, _do)


def _pushsent_rows(app_, uid):
    def _do():
        from models import PushSent
        return sorted((r.kind, r.local_date) for r in PushSent.query.filter_by(user_id=uid).all())
    return _app_do(app_, _do)


def _set_now(monkeypatch, dt):
    import app as appmod
    monkeypatch.setattr(appmod, "_utcnow", lambda: dt)


def _stub_push(monkeypatch, return_value=1, raise_exc=None):
    """Monkeypatch app.push_to_user to capture calls (across ALL users the
    tick touches, not just the test's own) instead of touching
    pywebpush/VAPID. Returns the `calls` list (each a dict) — filter with
    `_calls_for()` before asserting counts (see module docstring)."""
    import app as appmod
    calls = []

    def _fake(user_id, title, body, tag=None):
        calls.append({"user_id": user_id, "title": title, "body": body, "tag": tag})
        if raise_exc:
            raise raise_exc
        return return_value

    monkeypatch.setattr(appmod, "push_to_user", _fake)
    return calls


def _calls_for(calls, uid):
    return [c for c in calls if c["user_id"] == uid]


def _pt(y, m, d, hh, mm):
    """A wall-clock instant in America/Los_Angeles, expressed as UTC — lets
    tests state times the way a human reads them ("7am Monday PT") while
    the conversion to UTC is done by zoneinfo, never a hardcoded offset."""
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)


def _utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


_MON = date(2026, 8, 17)   # anchor Monday (verified: .weekday() == 0)
_SUN = date(2026, 8, 23)   # the Sunday of that same week (.weekday() == 6)


# ---- (a) fire-once semantics, incl. simulated restart ----------------------

def test_morning_fires_once_then_noop_same_date(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-morning-once@test.com")
    _subscribe(app_, db, uid)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 7, 0))

    fired1 = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "morning") in fired1
    assert len(_calls_for(calls, uid)) == 1

    # Second tick, same simulated "now" (still inside the window): no resend.
    fired2 = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "morning") not in fired2
    assert len(_calls_for(calls, uid)) == 1

    # "Restart": re-calling the tick again relies on nothing but the DB row
    # written by the first tick (there is no in-process cache) — still no
    # resend.
    _app_do(app_, appmod._push_scheduler_tick)
    assert len(_calls_for(calls, uid)) == 1
    assert _pushsent_rows(app_, uid) == [("morning", _MON)]


# ---- (b) window edges -------------------------------------------------------

def test_morning_window_edges(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid1 = _make_user(app_, db, "sched-edge-629@test.com")
    _subscribe(app_, db, uid1)
    calls1 = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 6, 29))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid1, "morning") not in fired
    assert _calls_for(calls1, uid1) == []

    uid2 = _make_user(app_, db, "sched-edge-630@test.com")
    _subscribe(app_, db, uid2)
    calls2 = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 6, 30))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid2, "morning") in fired
    assert len(_calls_for(calls2, uid2)) == 1

    uid3 = _make_user(app_, db, "sched-edge-1100@test.com")
    _subscribe(app_, db, uid3)
    calls3 = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 11, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid3, "morning") not in fired
    assert _calls_for(calls3, uid3) == []

    # A late server start landing INSIDE the window (not exactly at the
    # 06:30 edge) must still fire — this is a level check, not edge-triggered.
    uid4 = _make_user(app_, db, "sched-edge-late@test.com")
    _subscribe(app_, db, uid4)
    calls4 = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 9, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid4, "morning") in fired
    assert len(_calls_for(calls4, uid4)) == 1


# ---- (c) timezone honored, never a fixed offset -----------------------------

def test_timezone_honored_not_fixed_offset(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid = _make_user(app_, db, "sched-tz-fires@test.com")
    _subscribe(app_, db, uid)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _utc(2026, 8, 17, 13, 30))  # == 06:30 PT (PDT, UTC-7)
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "morning") in fired
    assert len(_calls_for(calls, uid)) == 1

    uid2 = _make_user(app_, db, "sched-tz-nofire@test.com")
    _subscribe(app_, db, uid2)
    calls2 = _stub_push(monkeypatch)
    _set_now(monkeypatch, _utc(2026, 8, 17, 6, 30))  # == 23:30 PT the PRIOR day
    fired2 = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid2, "morning") not in fired2
    assert _calls_for(calls2, uid2) == []


# ---- (d) dose-night gating ---------------------------------------------------

def test_dose_night_fires_for_untaken_late_dose(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-fires@test.com")
    _subscribe(app_, db, uid)
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", taken=False)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 22, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "dose_night") in fired
    my_calls = _calls_for(calls, uid)
    assert len(my_calls) == 1
    assert "Tesamorelin" in my_calls[0]["body"]
    assert _pushsent_rows(app_, uid) == [("dose_night", _MON)]


def test_dose_night_skips_when_all_taken(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-taken@test.com")
    _subscribe(app_, db, uid)
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", taken=True)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 22, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "dose_night") not in fired
    assert _calls_for(calls, uid) == []
    assert _pushsent_rows(app_, uid) == []


def test_dose_night_skips_when_no_late_dose(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-none@test.com")
    _subscribe(app_, db, uid)
    _add_dose(app_, db, uid, _MON, "BPC-157", "08:00", taken=False)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 22, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "dose_night") not in fired
    assert _calls_for(calls, uid) == []
    assert _pushsent_rows(app_, uid) == []


def test_dose_night_skips_when_late_dose_is_held(app_ctx, monkeypatch):
    """A held dose (dose_mg<=0, taken_at=None — the codebase's convention
    for an intentionally-skipped scheduled dose, per protocol.py's
    escalation/current_dose_mg docstrings) must never trigger the
    dose-night nudge, even though it's untaken and scheduled >=21:00."""
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-held@test.com")
    _subscribe(app_, db, uid)
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", taken=False, dose_mg=0)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 22, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "dose_night") not in fired
    assert _calls_for(calls, uid) == []
    assert _pushsent_rows(app_, uid) == []


def test_dose_night_held_dose_excluded_real_dose_still_fires(app_ctx, monkeypatch):
    """Mixed date: one held dose + one real untaken dose, both >=21:00.
    Must fire (the real dose is due) and the body must name only the real
    compound — never the held one, and never counted in "+N more"."""
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-mixed@test.com")
    _subscribe(app_, db, uid)
    _add_dose(app_, db, uid, _MON, "GHK-Cu", "22:00", taken=False, dose_mg=0)
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", taken=False, dose_mg=2.0)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 22, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "dose_night") in fired
    my_calls = _calls_for(calls, uid)
    assert len(my_calls) == 1
    body = my_calls[0]["body"]
    # Sorted-by-compound tiebreak (same "22:00" time) means a leaked held
    # row would sort BEFORE "Tesamorelin" ("GHK-Cu" < "Tesamorelin") and
    # get named as the "first" dose instead — so this also proves the held
    # row was excluded from `qualifying` entirely, not just hidden.
    assert "Tesamorelin" in body
    assert "GHK-Cu" not in body
    assert "+1 more" not in body  # only 1 qualifying dose — no "+N more" suffix
    assert _pushsent_rows(app_, uid) == [("dose_night", _MON)]


def test_dose_night_body_excludes_held_dose_directly(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-body-held@test.com")
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", taken=False, dose_mg=0)
    assert _app_do(app_, lambda: appmod._dose_night_body(uid, _MON)) is None


def test_has_dose_night_due_excludes_held(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-gate-held@test.com")
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", taken=False, dose_mg=0)
    assert _app_do(app_, lambda: appmod._has_dose_night_due(uid, _MON)) is False

    _add_dose(app_, db, uid, _MON, "GHK-Cu", "21:30", taken=False, dose_mg=1.0)
    assert _app_do(app_, lambda: appmod._has_dose_night_due(uid, _MON)) is True


def test_dose_night_body_names_first_plus_n_more(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-multi@test.com")
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00")
    _add_dose(app_, db, uid, _MON, "GHK-Cu", "21:30")

    body = _app_do(app_, lambda: appmod._dose_night_body(uid, _MON))
    assert body.startswith("GHK-Cu +1 more at 9:30 PM")
    assert "fasted 2h?" in body


def test_dose_night_body_none_when_nothing_qualifies(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-dose-body-none@test.com")
    assert _app_do(app_, lambda: appmod._dose_night_body(uid, _MON)) is None


# ---- (e) recap slot: stub must not burn the idempotency row ----------------

def test_recap_stub_none_no_push_no_ledger_row(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-recap-stub@test.com")
    _subscribe(app_, db, uid)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 23, 19, 30))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "recap") not in fired
    assert _calls_for(calls, uid) == []
    assert _pushsent_rows(app_, uid) == []


def test_recap_fires_once_when_builder_returns_text(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-recap-text@test.com")
    _subscribe(app_, db, uid)
    monkeypatch.setattr(appmod, "_sunday_recap_push",
                         lambda uid, d: "Week recap: solid week.")
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 23, 19, 30))

    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "recap") in fired
    my_calls = _calls_for(calls, uid)
    assert len(my_calls) == 1
    assert my_calls[0]["body"] == "Week recap: solid week."

    fired2 = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "recap") not in fired2
    assert len(_calls_for(calls, uid)) == 1
    assert _pushsent_rows(app_, uid) == [("recap", _SUN)]


def test_sunday_recap_push_stub_returns_none_directly(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-recap-stub-direct@test.com")
    assert _app_do(app_, lambda: appmod._sunday_recap_push(uid, _SUN)) is None


# ---- (f) no subscription -> never queried into a send -----------------------

def test_no_subscription_user_never_pushed(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-nosub@test.com")
    # Deliberately no _subscribe() call.
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 7, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert all(u != uid for u, _k in fired)
    assert _calls_for(calls, uid) == []


# ---- (g) ledger semantics around push_to_user's return / raise -------------

def test_pushsent_written_when_send_returns_zero(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-zero@test.com")
    _subscribe(app_, db, uid)
    calls = _stub_push(monkeypatch, return_value=0)
    _set_now(monkeypatch, _pt(2026, 8, 17, 7, 0))
    fired = _app_do(app_, appmod._push_scheduler_tick)
    assert (uid, "morning") in fired
    assert len(_calls_for(calls, uid)) == 1
    assert _pushsent_rows(app_, uid) == [("morning", _MON)]


def test_pushsent_integrity_error_rolls_back_and_does_not_duplicate(app_ctx, monkeypatch):
    """A genuine multi-worker race: two ticks both pass the PushSent
    pre-check before either commits its ledger row. Simulated here by
    having the body builder itself (called AFTER the pre-check, BEFORE
    _push_window_send's own insert) commit a real PushSent row on `uid`'s
    behalf — "the other worker" finishing first. This drives a REAL
    sqlite UNIQUE-constraint IntegrityError through the actual
    app.py:_push_window_send code path (not a mocked exception), proving
    the rollback-and-skip branch neither crashes the tick nor leaves a
    duplicate/corrupt ledger row."""
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-race@test.com")
    _subscribe(app_, db, uid)
    calls = _stub_push(monkeypatch)
    _set_now(monkeypatch, _pt(2026, 8, 17, 7, 0))

    def _racing_body(uid_, local_date_):
        from models import PushSent
        db.session.add(PushSent(user_id=uid_, kind="morning", local_date=local_date_))
        db.session.commit()
        return "Weigh in"

    monkeypatch.setattr(appmod, "_morning_brief_body", _racing_body)

    fired = _app_do(app_, appmod._push_scheduler_tick)  # must not raise

    # This process still sent (push_to_user was already called once the
    # PushSent pre-check passed, per the contract's "counts as attempted"
    # rule) even though its own ledger insert lost the race.
    assert (uid, "morning") in fired
    assert len(_calls_for(calls, uid)) == 1
    # Exactly ONE row survives — "the other worker's" — never zero (the
    # rollback didn't wipe it) and never two (no duplicate/crash on the
    # UNIQUE constraint).
    assert _pushsent_rows(app_, uid) == [("morning", _MON)]


def test_push_to_user_raises_no_crash_no_ledger_row(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-raise@test.com")
    _subscribe(app_, db, uid)
    calls = _stub_push(monkeypatch, raise_exc=RuntimeError("push service down"))
    _set_now(monkeypatch, _pt(2026, 8, 17, 7, 0))

    fired = _app_do(app_, appmod._push_scheduler_tick)  # must not raise

    assert (uid, "morning") not in fired
    assert len(_calls_for(calls, uid)) == 1  # attempted
    assert _pushsent_rows(app_, uid) == []


# ---- _morning_brief_body: real-data assembly --------------------------------

def test_morning_brief_body_assembles_real_parts(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-brief-parts@test.com")
    _seed_appstate(app_, db, uid, _MON)
    _seed_day_schedule(app_, db, uid, 1, 0, lift_name="Upper A - Chest & Back")
    _seed_run_plan(app_, db, uid, 1, 0, "Zone 2", "40 min")
    _add_dose(app_, db, uid, _MON, "BPC-157", "08:00")
    _add_dose(app_, db, uid, _MON, "KPV", "08:05")
    # A HELD dose (dose_mg<=0 -- intentionally skipped) must NOT inflate the
    # count: every sibling surface (dose-night gate, recap adherence,
    # calendar checkmark logic) already excludes held rows, so the brief
    # must still read "2 doses", not "3 doses" (final review I-1).
    _add_dose(app_, db, uid, _MON, "Tesamorelin", "22:00", dose_mg=0)

    body = _app_do(app_, lambda: appmod._morning_brief_body(uid, _MON))
    assert body == "Weigh in · 2 doses · Upper A - Chest & Back · Zone 2 40 min"


def test_morning_brief_body_omits_weighin_when_logged_and_marks_rest(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-brief-rest@test.com")
    _seed_appstate(app_, db, uid, _MON)
    _seed_day_schedule(app_, db, uid, 1, 0, is_rest=True)
    _seed_bodyweight(app_, db, uid, _MON)

    body = _app_do(app_, lambda: appmod._morning_brief_body(uid, _MON))
    assert body == "Rest"


def test_morning_brief_body_never_raises_without_any_data(app_ctx):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "sched-brief-empty@test.com")
    # No AppState, no WeeklyDaySchedule/WeeklyRunPlan, no BodyWeight, no doses.
    body = _app_do(app_, lambda: appmod._morning_brief_body(uid, _MON))
    assert body == "Weigh in"
