"""tests/test_aerobic_efficiency.py — GET /api/stats/aerobic-efficiency
(Task 6, engagement-features branch).

CRITICAL DATA QUIRK under test: RunLog.week (the "program week") is
SCRAMBLED across history — block-1 rows were re-homed to weeks 25-36,
block-2 to 13-18, current block is 1-12. The endpoint MUST bucket by
log_date calendar week (Monday-start), never by the week/day_idx columns.
Every seed helper below deliberately assigns a program `week` that has NO
relationship to the row's calendar position, to prove the endpoint ignores
it entirely.

Covers:
  (a) three calendar weeks, program weeks scrambled (25, 13, 1 — inserted
      out of chronological order too) -> response buckets follow log_date
      only, ascending by week_start.
  (b) easy-band filter: avg_hr 117 and 141 excluded, 118 and 140 included
      (band is inclusive [118, 140]).
  (c) pace/HR math hand-pinned to a specific pair of runs (see comments
      at the test for the arithmetic).
  (d) a calendar week with only out-of-band runs is omitted entirely
      (no zero-fill) while a qualifying week in the same response survives.
  (e) rows with null avg_hr, zero distance, or zero duration are ignored
      without the endpoint crashing.
  (f) cross-user isolation — one user's runs never leak into another's
      response.
  (g) a SUNDAY log_date (last day of a Monday-start week) buckets to that
      week's Monday, not the following Monday -- pins down the boundary
      the endpoint's `log_date - timedelta(days=log_date.weekday())` math
      is supposed to hit but which wasn't exercised by any of (a)-(f).

App-context handling: SHORT-LIVED contexts only, matching the documented
pattern in tests/test_projection_surfaces.py (module-scoped `app_ctx` just
creates tables; every DB write/read goes through `_do()`, which pushes and
pops its own app context so flask.g never survives past a single
operation) — not the module-scoped held-open `app_ctx` most other test
files use.
"""
from datetime import date, timedelta

import pytest

# Anchor Monday. 2026-08-10 is a confirmed Monday (system "today" is
# 2026-08-11, a Tuesday). Every other week below is derived by subtracting
# whole numbers of weeks from this anchor, which is guaranteed to land on a
# Monday too -- so no week boundary in this file is asserted by hand-waving,
# only by subtracting exact 7-day multiples from a known-good anchor.
ANCHOR_MONDAY = date(2026, 8, 10)


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


def _login(app_, db, email):
    def _do_it():
        from models import User
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        return u.id, u.email
    uid, uemail = _do(app_, _do_it)
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    return uid, uemail, client


def _seed_run(app_, db, uid, log_date, distance_miles, duration_min, avg_hr,
              week, day_idx):
    """Insert one RunLog row. `week`/`day_idx` are the (scrambled) program
    week fields -- deliberately decoupled from log_date/calendar semantics,
    only present to satisfy the model's UniqueConstraint(user_id, week, day_idx)."""
    def _do_it():
        from models import RunLog
        db.session.add(RunLog(
            user_id=uid, log_date=log_date, week=week, day_idx=day_idx,
            distance_miles=distance_miles, duration_min=duration_min,
            avg_hr=avg_hr, source="manual",
        ))
        db.session.commit()
    _do(app_, _do_it)


# ── (a) calendar bucketing ignores scrambled program weeks ─────────────────

def test_buckets_by_log_date_not_scrambled_program_week(app_ctx):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "aero-scramble@test.com")

    wk_early = ANCHOR_MONDAY - timedelta(weeks=20)   # earliest calendar week
    wk_mid = ANCHOR_MONDAY - timedelta(weeks=10)      # middle calendar week
    wk_late = ANCHOR_MONDAY                            # latest calendar week

    # Insert LATEST calendar week first, tagged with the SMALLEST program
    # week (1) -- and earliest calendar week last, tagged with the LARGEST
    # program week (25). If the endpoint bucketed by `week` instead of
    # `log_date`, this would come out in the wrong order or merge buckets.
    _seed_run(app_, db, uid, wk_late, 3.0, 27, 125, week=1, day_idx=0)
    _seed_run(app_, db, uid, wk_early, 3.0, 27, 125, week=25, day_idx=1)
    _seed_run(app_, db, uid, wk_mid, 3.0, 27, 125, week=13, day_idx=2)

    r = client.get("/api/stats/aerobic-efficiency")
    assert r.status_code == 200, r.get_data(as_text=True)
    weeks = r.get_json()["weeks"]

    assert [w["week_start"] for w in weeks] == [
        wk_early.isoformat(), wk_mid.isoformat(), wk_late.isoformat(),
    ]
    for w in weeks:
        assert w["n_runs"] == 1
        assert w["miles"] == 3.0


# ── (b) easy-band filter is inclusive [118, 140] ────────────────────────────

def test_band_filter_excludes_117_and_141_includes_118_and_140(app_ctx):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "aero-band@test.com")

    wk = ANCHOR_MONDAY - timedelta(weeks=5)
    # Four runs in the SAME calendar week, one per HR value. All same pace
    # inputs (3 mi / 30 min) so only the count of survivors, not the exact
    # pace number, is what this test cares about.
    _seed_run(app_, db, uid, wk, 3.0, 30, 117, week=99, day_idx=0)   # excluded (below band)
    _seed_run(app_, db, uid, wk, 3.0, 30, 118, week=99, day_idx=1)   # included (band floor)
    _seed_run(app_, db, uid, wk, 3.0, 30, 140, week=99, day_idx=2)   # included (band ceiling)
    _seed_run(app_, db, uid, wk, 3.0, 30, 141, week=99, day_idx=3)   # excluded (above band)

    r = client.get("/api/stats/aerobic-efficiency")
    assert r.status_code == 200, r.get_data(as_text=True)
    weeks = r.get_json()["weeks"]

    assert len(weeks) == 1
    assert weeks[0]["week_start"] == wk.isoformat()
    assert weeks[0]["n_runs"] == 2  # only the 118 and 140 rows count
    assert weeks[0]["miles"] == 6.0  # 3.0 + 3.0 from the two survivors
    # Both surviving rows have identical HR (118, 140 avg is 129 exactly --
    # duration-weighted mean of two equal-duration runs is a plain average).
    assert weeks[0]["avg_hr"] == 129.0


# ── (c) pace/HR math hand-pinned ────────────────────────────────────────────

def test_pace_and_hr_math_hand_pinned(app_ctx):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "aero-math@test.com")

    wk = ANCHOR_MONDAY - timedelta(weeks=3)
    # Run 1: 4.0 mi in 40 min (2400 sec) at avg_hr 130.
    # Run 2: 2.0 mi in 21 min (1260 sec) at avg_hr 140.
    #
    # pace_sec_per_mi = round(total_sec / total_miles)
    #                 = round((2400 + 1260) / (4.0 + 2.0))
    #                 = round(3660 / 6.0)
    #                 = round(610.0) = 610
    #
    # avg_hr = round(duration-weighted mean, 1)
    #        = round((130*2400 + 140*1260) / 3660, 1)
    #        = round((312000 + 176400) / 3660, 1)
    #        = round(488400 / 3660, 1)
    #        = round(133.442622..., 1) = 133.4
    _seed_run(app_, db, uid, wk, 4.0, 40, 130, week=25, day_idx=0)
    _seed_run(app_, db, uid, wk + timedelta(days=2), 2.0, 21, 140, week=25, day_idx=1)

    r = client.get("/api/stats/aerobic-efficiency")
    assert r.status_code == 200, r.get_data(as_text=True)
    weeks = r.get_json()["weeks"]

    assert len(weeks) == 1
    w = weeks[0]
    assert w["week_start"] == wk.isoformat()
    assert w["pace_sec_per_mi"] == 610
    assert w["avg_hr"] == 133.4
    assert w["n_runs"] == 2
    assert w["miles"] == 6.0


# ── (d) a week with only out-of-band runs is omitted, not zero-filled ──────

def test_out_of_band_only_week_is_omitted_entirely(app_ctx):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "aero-omit@test.com")

    wk_bad = ANCHOR_MONDAY - timedelta(weeks=8)   # only a hard-effort run, HR 200
    wk_good = ANCHOR_MONDAY - timedelta(weeks=4)   # one qualifying easy run

    _seed_run(app_, db, uid, wk_bad, 5.0, 35, 200, week=30, day_idx=0)
    _seed_run(app_, db, uid, wk_good, 3.0, 27, 125, week=2, day_idx=1)

    r = client.get("/api/stats/aerobic-efficiency")
    assert r.status_code == 200, r.get_data(as_text=True)
    weeks = r.get_json()["weeks"]

    week_starts = [w["week_start"] for w in weeks]
    assert wk_bad.isoformat() not in week_starts
    assert week_starts == [wk_good.isoformat()]


# ── (e) garbage rows (null HR, zero distance, zero duration) don't crash ──

def test_null_and_zero_rows_ignored_without_crash(app_ctx):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "aero-garbage@test.com")

    wk = ANCHOR_MONDAY - timedelta(weeks=6)
    _seed_run(app_, db, uid, wk, 5.0, 40, None, week=7, day_idx=0)   # null avg_hr
    _seed_run(app_, db, uid, wk, 0.0, 30, 125, week=7, day_idx=1)    # zero distance
    _seed_run(app_, db, uid, wk, 5.0, 0, 125, week=7, day_idx=2)     # zero duration
    _seed_run(app_, db, uid, wk, 3.0, 27, 125, week=7, day_idx=3)    # the one good row

    r = client.get("/api/stats/aerobic-efficiency")
    assert r.status_code == 200, r.get_data(as_text=True)
    weeks = r.get_json()["weeks"]

    assert len(weeks) == 1
    assert weeks[0]["week_start"] == wk.isoformat()
    assert weeks[0]["n_runs"] == 1
    assert weeks[0]["miles"] == 3.0


# ── (f) cross-user isolation ────────────────────────────────────────────────

def test_cross_user_isolation(app_ctx):
    app_, db = app_ctx
    uid_a, email_a, client_a = _login(app_, db, "aero-user-a@test.com")
    uid_b, email_b, client_b = _login(app_, db, "aero-user-b@test.com")

    wk = ANCHOR_MONDAY - timedelta(weeks=2)
    _seed_run(app_, db, uid_a, wk, 3.0, 27, 125, week=1, day_idx=0)
    _seed_run(app_, db, uid_b, wk, 10.0, 90, 130, week=1, day_idx=0)

    r_a = client_a.get("/api/stats/aerobic-efficiency")
    r_b = client_b.get("/api/stats/aerobic-efficiency")
    assert r_a.status_code == 200 and r_b.status_code == 200

    weeks_a = r_a.get_json()["weeks"]
    weeks_b = r_b.get_json()["weeks"]

    assert len(weeks_a) == 1 and weeks_a[0]["miles"] == 3.0 and weeks_a[0]["n_runs"] == 1
    assert len(weeks_b) == 1 and weeks_b[0]["miles"] == 10.0 and weeks_b[0]["n_runs"] == 1


# ── (g) Sunday log_date buckets to ITS week's Monday, not the next one ─────

def test_sunday_log_date_buckets_to_same_week_monday(app_ctx):
    app_, db = app_ctx
    uid, email, client = _login(app_, db, "aero-sunday@test.com")

    # ANCHOR_MONDAY (2026-08-10) is a confirmed Monday; +6 days is the
    # SUNDAY that closes out that same Monday-start week, not the next one.
    sunday = ANCHOR_MONDAY + timedelta(days=6)
    assert sunday.isoformat() == "2026-08-16"
    _seed_run(app_, db, uid, sunday, 3.0, 27, 125, week=1, day_idx=0)

    r = client.get("/api/stats/aerobic-efficiency")
    assert r.status_code == 200, r.get_data(as_text=True)
    weeks = r.get_json()["weeks"]

    assert len(weeks) == 1
    assert weeks[0]["week_start"] == ANCHOR_MONDAY.isoformat()  # NOT the following Monday


# ── per-run series (2026-09-03: one dot per run, not per week) ─────────────

def test_aerobic_efficiency_runs_is_one_point_per_run():
    from types import SimpleNamespace as R
    from workout_status import aerobic_efficiency_runs
    rows = [
        R(id=2, log_date=date(2026, 9, 2), distance_miles=3.0, duration_min=30.0, avg_hr=130),
        R(id=1, log_date=date(2026, 9, 1), distance_miles=4.0, duration_min=36.0, avg_hr=128),
        R(id=3, log_date=date(2026, 9, 2), distance_miles=2.0, duration_min=20.0, avg_hr=150),  # out of band
        R(id=4, log_date=date(2026, 9, 3), distance_miles=0, duration_min=20.0, avg_hr=125),    # no distance
        R(id=5, log_date=date(2026, 9, 3), distance_miles=5.0, duration_min=50.0, avg_hr=None), # no HR
    ]
    out = aerobic_efficiency_runs(rows)
    assert [o["date"] for o in out] == ["2026-09-01", "2026-09-02"]
    assert out[0]["pace_sec_per_mi"] == 540 and out[1]["pace_sec_per_mi"] == 600
    assert out[0]["miles"] == 4.0 and out[0]["duration_min"] == 36.0 and out[0]["avg_hr"] == 128
    assert "_id" not in out[0]
