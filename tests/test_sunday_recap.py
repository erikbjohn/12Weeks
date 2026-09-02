"""tests/test_sunday_recap.py — TDD for Task 7 of the engagement-features
plan (Sunday recap builder + card + push wiring):

  weekly_report.build_sunday_recap(uid, local_date) -> {"text": str, "data": {...}} | None
  app._sunday_recap_push(uid, local_date) -> str | None   (Task 3's stub, now real)
  GET /api/sunday-recap                                    (login_required)

ONE builder feeds all three surfaces — the push body, the card endpoint, and
the recap `data` dict — so none of them can ever disagree (one-source-of-truth).

App-context handling: SHORT-LIVED contexts only (matches
tests/test_scoreboard.py / tests/test_push_scheduler.py's documented
pattern) — every DB touch opens its own `with app_.app_context():` block,
never held open across calls, to avoid flask-login's current_user-on-`g`
leak trap (tests/test_security_auth.py).

`weekly_report.compute_weekly_metrics` hardcodes `today = date.today()`
internally for its BodyWeight/MorningCheckIn/MealLog window (a pre-existing
quirk, out of scope for this task — see its docstring: "Approximate week
boundaries ... use the last 7 days ending today"). To get a deterministic,
reproducible weight window that lines up with a hand-seeded week, tests that
need exact weight numbers freeze `weekly_report.date` to a fixed "today" via
`_freeze_weekly_report_today` (a local `datetime.date` subclass swap — the
same kind of seam-monkeypatch `test_push_scheduler.py` uses for
`app._utcnow`, just scoped to this module's own `date` name instead of the
stdlib one).
"""
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

ANCHOR = 220.0
START = date(2026, 8, 10)  # Monday
WEEK6_MON = START + timedelta(days=35)  # 2026-09-14
WEEK6_SUN = WEEK6_MON + timedelta(days=6)  # 2026-09-20


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _do(app_, fn):
    """Run fn() inside a fresh, short-lived app context (pushed and popped
    immediately) so flask.g never survives past this call."""
    with app_.app_context():
        return fn()


def _fresh_user(app_, db, email, tz="America/Los_Angeles"):
    def _do_it():
        from models import (User, AppState, TrainingGoal, BodyWeight, SetLog,
                             PeptideDose, RunLog, GarminWellness,
                             PushSubscription, PushSent)
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone=tz)
            db.session.add(u)
            db.session.commit()
        else:
            u.timezone = tz
            db.session.commit()
        AppState.query.filter_by(user_id=u.id).delete()
        TrainingGoal.query.filter_by(user_id=u.id).delete()
        BodyWeight.query.filter_by(user_id=u.id).delete()
        SetLog.query.filter_by(user_id=u.id).delete()
        PeptideDose.query.filter_by(user_id=u.id).delete()
        RunLog.query.filter_by(user_id=u.id).delete()
        GarminWellness.query.filter_by(user_id=u.id).delete()
        PushSubscription.query.filter_by(user_id=u.id).delete()
        PushSent.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _do(app_, _do_it)


def _seed_appstate(app_, db, uid, start_date):
    def _do_it():
        from models import AppState
        db.session.add(AppState(user_id=uid, start_date=start_date, current_week=1))
        db.session.commit()
    _do(app_, _do_it)


def _seed_projection(app_, db, uid, anchor=ANCHOR, start_date=START):
    def _do_it():
        from models import TrainingGoal
        from goal_engine import build_block3_projection
        proj = build_block3_projection(anchor, start_date)
        db.session.add(TrainingGoal(user_id=uid, goal_type="recomp",
                                     target_weight=195.0, weight_projection=proj))
        db.session.commit()
    _do(app_, _do_it)


def _seed_weights(app_, db, uid, pairs):
    def _do_it():
        from models import BodyWeight
        for d, w in pairs:
            db.session.add(BodyWeight(user_id=uid, log_date=d, weight_lbs=w))
        db.session.commit()
    _do(app_, _do_it)


def _add_sets(app_, db, uid, week, exercise, weight, reps, n_sets, day_idx=0):
    def _do_it():
        from models import SetLog
        for i in range(n_sets):
            db.session.add(SetLog(
                user_id=uid, exercise_name=exercise, week=week, day_idx=day_idx,
                set_number=i, weight=weight, reps=reps, done=True,
                logged_date=START,
            ))
        db.session.commit()
    _do(app_, _do_it)


def _add_dose(app_, db, uid, d, compound, dose_mg=1.0, taken_at=None):
    def _do_it():
        from models import PeptideDose
        db.session.add(PeptideDose(
            user_id=uid, date=d, time="08:00", event_type="Injection",
            compound=compound, dose_mg=dose_mg, taken_at=taken_at,
        ))
        db.session.commit()
    _do(app_, _do_it)


def _add_run(app_, db, uid, d, week, day_idx, miles):
    def _do_it():
        from models import RunLog
        db.session.add(RunLog(user_id=uid, log_date=d, week=week, day_idx=day_idx,
                               distance_miles=miles))
        db.session.commit()
    _do(app_, _do_it)


def _add_wellness(app_, db, uid, d, sleep_seconds=None):
    def _do_it():
        from models import GarminWellness
        db.session.add(GarminWellness(user_id=uid, date=d, sleep_seconds=sleep_seconds))
        db.session.commit()
    _do(app_, _do_it)


def _freeze_weekly_report_today(monkeypatch, frozen_date):
    """weekly_report.compute_weekly_metrics calls `date.today()` internally
    for its BodyWeight/MorningCheckIn/MealLog window — freeze that name
    (module-local, never the stdlib `datetime.date` itself) to `frozen_date`
    so the window lines up with a hand-seeded week."""
    import weekly_report

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return frozen_date

    monkeypatch.setattr(weekly_report, "date", _FixedDate)


def _login(app_, db, email, tz="America/Los_Angeles"):
    def _do_it():
        from models import User
        u = User.query.filter_by(email=email).first()
        return u.id
    uid = _do(app_, _do_it)
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    return uid, client


def _subscribe(app_, db, uid):
    def _do_it():
        from models import PushSubscription
        db.session.add(PushSubscription(
            user_id=uid, endpoint=f"https://push.example.com/recap-{uid}",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        ))
        db.session.commit()
    _do(app_, _do_it)


def _pushsent_rows(app_, uid):
    def _do_it():
        from models import PushSent
        return sorted((r.kind, r.local_date) for r in PushSent.query.filter_by(user_id=uid).all())
    return _do(app_, _do_it)


def _stub_push(monkeypatch):
    import app as appmod
    calls = []

    def _fake(user_id, title, body, tag=None):
        calls.append({"user_id": user_id, "title": title, "body": body, "tag": tag})
        return 1

    monkeypatch.setattr(appmod, "push_to_user", _fake)
    return calls


def _calls_for(calls, uid):
    return [c for c in calls if c["user_id"] == uid]


def _pt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)


def _utc_taken(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


# ── (a) fully-seeded week -> EXACT pinned text + data dict ──────────────────

def test_build_sunday_recap_exact_text_seeded_week(app_ctx, monkeypatch):
    app_, db = app_ctx
    import weekly_report

    uid = _fresh_user(app_, db, "recap-a@test.com")
    _seed_appstate(app_, db, uid, START)
    _seed_projection(app_, db, uid)
    _seed_weights(app_, db, uid, [(WEEK6_MON, 212.0), (WEEK6_SUN, 209.9)])

    # Lift tonnage: reference weeks 1-3 @ 1000/wk (1 set x 100 x 10 reps),
    # recent weeks 5-6 @ 900/wk (1 set x 90 x 10 reps) -> -10.0% exactly.
    # Week 4 (deload) deliberately left unseeded — excluded either way.
    for wk in (1, 2, 3):
        _add_sets(app_, db, uid, wk, "Leg Press", 100.0, 10, 1)
    for wk in (5, 6):
        _add_sets(app_, db, uid, wk, "Leg Press", 90.0, 10, 1)

    # Doses: 6 scheduled (dose_mg>0) across the week -- 5 taken (one LATE),
    # 1 untaken -- plus 1 HELD dose (dose_mg<=0) that must be excluded from
    # BOTH numerator and denominator (would read 5/7 or 6/7 if it leaked in).
    _add_dose(app_, db, uid, WEEK6_MON, "CompoundA", taken_at=_utc_taken(2026, 9, 14))
    _add_dose(app_, db, uid, WEEK6_MON, "CompoundB", taken_at=_utc_taken(2026, 9, 14))
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=1), "CompoundC", taken_at=_utc_taken(2026, 9, 15))
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=2), "CompoundD",
              taken_at=_utc_taken(2026, 9, 19))  # LATE (3 days after its own date) -- still TAKEN
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=3), "CompoundE", taken_at=_utc_taken(2026, 9, 17))
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=4), "CompoundF", taken_at=None)  # untaken
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=5), "HeldCompound", dose_mg=0, taken_at=None)

    # Runs: 5 + 6 + 4 = 15 miles this week.
    _add_run(app_, db, uid, WEEK6_MON, 6, 0, 5.0)
    _add_run(app_, db, uid, WEEK6_MON + timedelta(days=2), 6, 2, 6.0)
    _add_run(app_, db, uid, WEEK6_MON + timedelta(days=4), 6, 4, 4.0)

    # Sleep: 7 days x 28440s (7.9h) -> avg 7.9h exactly.
    for i in range(7):
        _add_wellness(app_, db, uid, WEEK6_MON + timedelta(days=i), sleep_seconds=28440)

    _freeze_weekly_report_today(monkeypatch, WEEK6_SUN)

    recap = _do(app_, lambda: weekly_report.build_sunday_recap(uid, WEEK6_SUN))

    assert recap is not None
    assert recap["text"] == (
        "Wk 6: 212→209.9 (curve 209.5) · lifts -10% · weigh-ins 2/7 · 15 mi · doses 5/6 · sleep 7.9h avg"
    ), recap["text"]
    assert recap["data"] == {
        "week": 6,
        "weight_start": 212.0,
        "weight_end": 209.9,
        "curve_target": 209.5,
        "lift_trend": -10.0,
        "miles": 15.0,
        "doses_taken": 5,
        "doses_scheduled": 6,
        "sleep_avg_h": 7.9,
        # S076: sessions done/planned + weigh-in days (planned is None here:
        # the seeded week has no prescription rows)
        "lifts_done": 3, "lifts_planned": None, "weigh_in_days": 2,
    }


# ── (b) missing sleep data -> sleep segment absent, key None ────────────────

def test_missing_sleep_data_segment_omitted(app_ctx, monkeypatch):
    app_, db = app_ctx
    import weekly_report

    uid = _fresh_user(app_, db, "recap-b@test.com")
    _seed_appstate(app_, db, uid, START)
    _seed_weights(app_, db, uid, [(WEEK6_MON, 200.0), (WEEK6_SUN, 199.0)])
    # Deliberately NO GarminWellness rows at all this week.

    _freeze_weekly_report_today(monkeypatch, WEEK6_SUN)

    recap = _do(app_, lambda: weekly_report.build_sunday_recap(uid, WEEK6_SUN))

    assert recap is not None
    assert "sleep" not in recap["text"]
    assert recap["data"]["sleep_avg_h"] is None
    # The rest of the line still renders — this isn't an all-or-nothing gate.
    assert "200" in recap["text"] and "199" in recap["text"]


# ── (b2) genuine 0.0 miles logged -> shown, never silently omitted ─────────

def test_genuine_zero_miles_logged_shows_zero_not_omitted(app_ctx, monkeypatch):
    """A RunLog row that exists for this week but logged 0.0 miles (e.g. a
    run cut short to nothing, or a placeholder entry) is REAL data, not
    missing data — it must render "0 mi", never be dropped the way a week
    with zero RunLog rows at all is dropped. This is exactly the falsy-zero
    bug class this codebase has been bitten by before
    (feedback_falsy_zero_bugs.md: `if data["miles"]:` would wrongly treat
    0.0 as "nothing to show" and silently omit the segment; the code under
    test uses `if data["miles"] is not None:` instead — this test pins
    that so a future truthy-check regression fails loudly)."""
    app_, db = app_ctx
    import weekly_report

    uid = _fresh_user(app_, db, "recap-b2@test.com")
    _seed_appstate(app_, db, uid, START)
    _add_run(app_, db, uid, WEEK6_MON, 6, 0, 0.0)  # only run this week: 0.0 miles

    _freeze_weekly_report_today(monkeypatch, WEEK6_SUN)

    recap = _do(app_, lambda: weekly_report.build_sunday_recap(uid, WEEK6_SUN))

    assert recap is not None
    assert recap["data"]["miles"] == 0.0
    assert recap["data"]["miles"] is not None  # explicit: 0.0 is not missing
    assert "0 mi" in recap["text"], recap["text"]


# ── (c) dose math: late counts taken, held excluded both sides ─────────────

def test_dose_adherence_late_counts_taken_held_excluded(app_ctx, monkeypatch):
    app_, db = app_ctx
    import weekly_report

    uid = _fresh_user(app_, db, "recap-c@test.com")
    _seed_appstate(app_, db, uid, START)
    _add_dose(app_, db, uid, WEEK6_MON, "LateOne",
              taken_at=_utc_taken(2026, 9, 20))  # taken several days late -- still TAKEN
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=1), "Untaken", taken_at=None)
    _add_dose(app_, db, uid, WEEK6_MON + timedelta(days=2), "Held", dose_mg=0, taken_at=None)

    _freeze_weekly_report_today(monkeypatch, WEEK6_SUN)

    recap = _do(app_, lambda: weekly_report.build_sunday_recap(uid, WEEK6_SUN))

    assert recap is not None
    # scheduled = 2 (LateOne + Untaken); Held is NOT scheduled -- if it leaked
    # in, this would read 1/3 instead of 1/2.
    assert recap["data"]["doses_scheduled"] == 2
    assert recap["data"]["doses_taken"] == 1
    assert "doses 1/2" in recap["text"]


def test_no_scheduled_doses_segment_omitted(app_ctx, monkeypatch):
    """Nothing scheduled (0/0, or only held doses) -> no dose segment at
    all, never a fabricated "0/0"."""
    app_, db = app_ctx
    import weekly_report

    uid = _fresh_user(app_, db, "recap-c2@test.com")
    _seed_appstate(app_, db, uid, START)
    _add_dose(app_, db, uid, WEEK6_MON, "OnlyHeld", dose_mg=0, taken_at=None)

    _freeze_weekly_report_today(monkeypatch, WEEK6_SUN)

    recap = _do(app_, lambda: weekly_report.build_sunday_recap(uid, WEEK6_SUN))

    assert recap is not None
    assert "doses" not in recap["text"]
    assert recap["data"]["doses_scheduled"] is None
    assert recap["data"]["doses_taken"] is None


# ── (d) one source of truth: endpoint == push body ──────────────────────────

def test_endpoint_and_push_agree_exactly(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    uid = _fresh_user(app_, db, "recap-d@test.com")
    _seed_appstate(app_, db, uid, START)
    _seed_weights(app_, db, uid, [(WEEK6_MON, 205.0), (WEEK6_SUN, 203.0)])

    _freeze_weekly_report_today(monkeypatch, WEEK6_SUN)
    monkeypatch.setattr(appmod, "_user_today", lambda: WEEK6_SUN)

    uid2, client = _login(app_, db, "recap-d@test.com")
    assert uid2 == uid

    r = client.get("/api/sunday-recap")
    assert r.status_code == 200, r.get_data(as_text=True)
    endpoint_recap = r.get_json()["recap"]
    assert endpoint_recap is not None

    push_text = _do(app_, lambda: appmod._sunday_recap_push(uid, WEEK6_SUN))

    assert push_text == endpoint_recap["text"]
    assert push_text.startswith("Wk 6:")


# ── (e) scheduler integration: Sunday slot fires with the real recap text ──

def test_scheduler_sunday_slot_fires_with_real_recap_text(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    _MON = date(2026, 8, 17)
    _SUN = date(2026, 8, 23)

    uid = _fresh_user(app_, db, "recap-e@test.com")
    _seed_appstate(app_, db, uid, _MON)
    _subscribe(app_, db, uid)

    calls = _stub_push(monkeypatch)
    _freeze_weekly_report_today(monkeypatch, _SUN)
    monkeypatch.setattr(appmod, "_utcnow", lambda: _pt(2026, 8, 23, 19, 30))

    fired = _do(app_, appmod._push_scheduler_tick)

    assert (uid, "recap") in fired
    my_calls = _calls_for(calls, uid)
    assert len(my_calls) == 1
    assert my_calls[0]["body"] == "Wk 1"  # AppState-only user: no data segments, still a real body
    assert my_calls[0]["title"] == "12 Weeks"
    assert _pushsent_rows(app_, uid) == [("recap", _SUN)]

    # Second tick same date: no resend (idempotent per (user, kind, date)).
    fired2 = _do(app_, appmod._push_scheduler_tick)
    assert (uid, "recap") not in fired2
    assert len(_calls_for(calls, uid)) == 1


# ── (f) builder returns None for a data-less user: stub-protection holds ───

def test_no_appstate_user_none_recap_no_push_no_ledger(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod

    _SUN = date(2026, 8, 23)

    uid = _fresh_user(app_, db, "recap-f@test.com")
    # Deliberately NO AppState row -- "no current-block week resolvable".
    _subscribe(app_, db, uid)

    calls = _stub_push(monkeypatch)
    monkeypatch.setattr(appmod, "_utcnow", lambda: _pt(2026, 8, 23, 19, 30))

    fired = _do(app_, appmod._push_scheduler_tick)

    assert (uid, "recap") not in fired
    assert _calls_for(calls, uid) == []
    assert _pushsent_rows(app_, uid) == []

    # Direct builder call: None.
    import weekly_report
    assert _do(app_, lambda: weekly_report.build_sunday_recap(uid, _SUN)) is None
    assert _do(app_, lambda: appmod._sunday_recap_push(uid, _SUN)) is None

    # Endpoint: {"recap": null}, never a 404/error.
    monkeypatch.setattr(appmod, "_user_today", lambda: _SUN)
    uid2, client = _login(app_, db, "recap-f@test.com")
    r = client.get("/api/sunday-recap")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {"recap": None}
