"""tests/test_i3_i4_fixes.py — TDD for Task 8 (block-3 final review I-3/I-4):

  I-3: weekly_report.compute_weekly_metrics's `weight_vs_projected` used a
  raw ±1.0 lb comparison against the RAW logged weight, while the dashboard
  on_pace badge (and coach_assembler cut_status.on_curve) judge the SAME
  question via goal_engine.pace_status on the DE-SPIKED weight with
  CURVE_TOLERANCE_LB (1.5) — a spiked (water/gluten) weigh-in could make
  the weekly report say "behind" in the same beat every other surface says
  "on pace", a no-UI-contradiction violation. Fixed: block-3 mode now
  routes weight_vs_projected through the identical pace_status/despike
  code path; non-block-3 users keep the legacy ±1.0 logic unchanged.

  I-4: SystemFlag rows `projection_mode`/`block3_anchor` were GLOBAL and
  UNKEYED — a second app user would silently inherit Erik's block-3 mode.
  Fixed: cut_guard now reads/writes PER-USER KEYED names
  (`projection_mode:<uid>` / `block3_anchor:<uid>`), falling back to the
  legacy unkeyed row only when no keyed row exists (pre-migration compat).
  A one-shot startup migration (app._migrate_block3_flags_to_keyed) renames
  Erik's unkeyed rows to keyed form on first boot, never guessing the
  target user.

Covers:
  (a) I-3: a spiked weigh-in (+5 lb water event) -> weekly_report agrees
      with the dashboard on_pace badge (does NOT say "behind" when the
      badge says on-pace); a legacy (non-block-3) user keeps the old ±1.0
      wording/logic byte-for-byte.
  (b) I-4 keyed read: a user with KEYED flags -> block-3 mode on; a SECOND
      user with NO flags of their own, while the first user's KEYED flags
      exist -> legacy (off) behavior — the actual I-4 bug, pinned.
  (c) Fallback: only legacy UNKEYED rows exist -> block-3 mode still comes
      on for ANY user (pre-migration compat — the brief, intentional
      window before the startup migration converts the rows).
  (d) Migration: unkeyed rows + a resolvable erik@placemetry.com user
      (block3_prestate present, AppState consistent) -> renamed to keyed,
      marker set, values preserved, idempotent on a second run; an
      unresolvable case (erik exists but no corroborating signal) -> rows
      left untouched, marker still set, loud warning logged.
  (e) Transition/rollback write PATH: run_transition writes KEYED rows
      only (never the legacy unkeyed names); run_rollback clears them.

App-context handling: SHORT-LIVED contexts only (matches
tests/test_scoreboard.py / tests/test_projection_surfaces.py's documented
pattern) — every DB touch opens its own `with app_.app_context():` block,
client.get/post calls never run inside a held-open context.
"""
import logging
from datetime import date, timedelta

import pytest

ANCHOR = 220.0
START = date(2026, 8, 10)  # Monday — matches transition_block3.TRANSITION_DATE
WEEK1_END = START + timedelta(days=6)  # 2026-08-16


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


@pytest.fixture()
def clean_flags(app_ctx):
    """SystemFlag is a GLOBAL table (not per-user) — reset the legacy
    UNKEYED names before AND after each test so the flag-present and
    flag-absent scenarios never leak into each other. Per-user KEYED rows
    are left alone: every test below uses a fresh, never-reused email, so
    a keyed row can't collide with a later test's lookup."""
    app_, db = app_ctx

    def _clear():
        from models import SystemFlag
        SystemFlag.query.filter(
            SystemFlag.key.in_(["projection_mode", "block3_anchor"])
        ).delete(synchronize_session=False)
        db.session.commit()

    _do(app_, _clear)
    yield
    _do(app_, _clear)


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


def _seed_goal_and_state(app_, db, uid, weight_projection, target_weight=195.0,
                          start_date=START, goal_type="cut"):
    def _do_it():
        from models import TrainingGoal, AppState
        TrainingGoal.query.filter_by(user_id=uid).delete()
        AppState.query.filter_by(user_id=uid).delete()
        db.session.commit()
        db.session.add(TrainingGoal(
            user_id=uid, goal_type=goal_type, target_weight=target_weight,
            daily_calories=1800, tdee=2800, weight_projection=weight_projection,
        ))
        db.session.add(AppState(user_id=uid, current_week=1, start_date=start_date))
        db.session.commit()
    _do(app_, _do_it)


def _set_weights(app_, db, uid, pairs):
    """pairs: [(date, weight), ...] oldest-first."""
    def _do_it():
        from models import BodyWeight
        BodyWeight.query.filter_by(user_id=uid).delete()
        db.session.commit()
        for d, w in pairs:
            db.session.add(BodyWeight(user_id=uid, weight_lbs=w, log_date=d))
        db.session.commit()
    _do(app_, _do_it)


def _set_keyed_block3_flags(app_, db, uid, anchor=ANCHOR):
    def _do_it():
        from models import SystemFlag
        SystemFlag.query.filter(SystemFlag.key.in_(
            [f"projection_mode:{uid}", f"block3_anchor:{uid}"])).delete(synchronize_session=False)
        db.session.add(SystemFlag(key=f"projection_mode:{uid}", value="piecewise_block3"))
        db.session.add(SystemFlag(key=f"block3_anchor:{uid}", value=str(anchor)))
        db.session.commit()
    _do(app_, _do_it)


def _set_unkeyed_block3_flags(app_, db, anchor=ANCHOR):
    def _do_it():
        from models import SystemFlag
        db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
        db.session.add(SystemFlag(key="block3_anchor", value=str(anchor)))
        db.session.commit()
    _do(app_, _do_it)


def _freeze_weekly_report_today(monkeypatch, frozen_date):
    """weekly_report.compute_weekly_metrics calls `date.today()` internally
    for its BodyWeight/MorningCheckIn/MealLog window (a pre-existing quirk,
    out of scope for this task — see tests/test_sunday_recap.py's identical
    seam-monkeypatch). Freeze that name so the window lines up with a
    hand-seeded week."""
    import weekly_report

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return frozen_date

    monkeypatch.setattr(weekly_report, "date", _FixedDate)


def _get_metrics(app_, week_num, uid):
    def _do_it():
        import weekly_report
        return weekly_report.compute_weekly_metrics(week_num, user_id=uid)
    return _do(app_, _do_it)


# ── (a) I-3: weekly report agrees with the dashboard badge ─────────────────

def test_block3_spike_report_agrees_with_badge_not_behind(app_ctx, clean_flags, monkeypatch):
    """Prior downtrend (220 -> 218.5) then a +5 lb spike over 3 days
    (218.5 -> 223.5) — cut_guard.detect_water_spike strips it (adjusted
    step 5.0 + 1.25*(3/7) = 5.54, within the 3-8 lb band on a downtrend) and
    both surfaces anchor on the PRIOR 218.5. Curve target at week-1's end
    (Aug17, elapsed=7 days) is 218.75 -> despiked 218.5 is within
    CURVE_TOLERANCE_LB (1.5) -> "on_pace"/"on_track". The RAW 223.5 the old
    ±1.0 code used is 4.75 lb over the same target -- it would have said
    "behind" while the dashboard says on-pace. That's the exact
    contradiction I-3 fixes."""
    app_, db = app_ctx
    import app as appmod
    from goal_engine import build_block3_projection

    uid, email, client = _login(app_, db, "i3-spike@test.com")
    proj = build_block3_projection(ANCHOR, START)
    _seed_goal_and_state(app_, db, uid, proj, target_weight=195.0, start_date=START)
    _set_weights(app_, db, uid, [
        (START, 220.0),
        (START + timedelta(days=3), 218.5),
        (START + timedelta(days=6), 223.5),  # the spike
    ])
    _set_keyed_block3_flags(app_, db, uid)
    monkeypatch.setattr(appmod, "_user_today", lambda: WEEK1_END)
    _freeze_weekly_report_today(monkeypatch, WEEK1_END)

    r = client.get("/api/progress/dashboard")
    assert r.status_code == 200, r.get_data(as_text=True)
    dash_on_pace = r.get_json()["projections"]["on_pace"]
    assert dash_on_pace is True  # despiked 218.5 vs curve ~218.93 -> on-pace

    metrics = _get_metrics(app_, 1, uid)
    assert metrics["weight_vs_projected"] == "on_track"
    assert metrics["weight_vs_projected"] != "behind"
    # Task 7's field is untouched by this fix (no removals).
    assert metrics["weight_projection_target"] == pytest.approx(218.75, abs=0.01)


def test_legacy_user_no_flags_old_ratio_logic_intact(app_ctx, clean_flags):
    """No block-3 flags at all -> weight_vs_projected uses the untouched
    raw ±1.0 comparison against the raw logged weight (week-1 target 219.0,
    logged 221.0 -> diff +2.0 -> "behind", exactly the pre-fix formula)."""
    app_, db = app_ctx
    import weekly_report

    uid, email, client = _login(app_, db, "i3-legacy@test.com")
    proj = [{"week": w, "projected": 220.0 - w} for w in range(1, 13)]
    _seed_goal_and_state(app_, db, uid, proj, target_weight=185.0, start_date=START)
    # S064: compute_weekly_metrics windows on the PROGRAM week (START..+6),
    # so a weigh-in on START is week 1's — no clock dependence.
    _set_weights(app_, db, uid, [(START, 221.0)])

    def _do_it():
        return weekly_report.compute_weekly_metrics(1, user_id=uid)
    metrics = _do(app_, _do_it)

    assert metrics["weight_vs_projected"] == "behind"
    assert metrics["weight_projection_target"] == pytest.approx(219.0)


# ── (b) I-4 keyed read + the second-user bug pin ────────────────────────────

def _make_user(app_, db, email):
    def _do_it():
        from models import User
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        return u.id
    return _do(app_, _do_it)


def _set_appstate(app_, db, uid, start_date):
    def _do_it():
        from models import AppState
        AppState.query.filter_by(user_id=uid).delete()
        db.session.add(AppState(user_id=uid, current_week=1, start_date=start_date))
        db.session.commit()
    _do(app_, _do_it)


def test_keyed_flags_enable_block3_mode_for_that_user(app_ctx, clean_flags):
    app_, db = app_ctx
    uid = _make_user(app_, db, "i4-keyed@test.com")
    _set_appstate(app_, db, uid, START)
    _set_keyed_block3_flags(app_, db, uid, anchor=ANCHOR)

    def _check():
        import cut_guard
        return cut_guard._block3_mode(uid), cut_guard._block3_anchor_and_start(uid)
    mode, anchor_start = _do(app_, _check)
    assert mode is True
    assert anchor_start == (ANCHOR, START)


def test_second_user_without_flags_gets_legacy_behavior_pin(app_ctx, clean_flags):
    """THE I-4 bug pin: user1 has KEYED block-3 flags (mode ON for them).
    user2 has no flags of their own, and no legacy unkeyed rows exist
    either — user2 must NOT inherit user1's block-3 mode."""
    app_, db = app_ctx
    uid1 = _make_user(app_, db, "i4-pin-user1@test.com")
    uid2 = _make_user(app_, db, "i4-pin-user2@test.com")
    _set_appstate(app_, db, uid1, START)
    _set_appstate(app_, db, uid2, START + timedelta(days=30))
    _set_keyed_block3_flags(app_, db, uid1, anchor=ANCHOR)

    def _check():
        import cut_guard
        return cut_guard._block3_mode(uid1), cut_guard._block3_mode(uid2)
    mode1, mode2 = _do(app_, _check)
    assert mode1 is True
    assert mode2 is False  # the actual bug: must NOT be True


# ── (c) fallback: unkeyed-only rows still enable block-3 mode (pre-migration) ──

def test_unkeyed_only_fallback_enables_block3_mode_for_any_user(app_ctx, clean_flags):
    """Pre-migration compat: only the legacy UNKEYED rows exist -> EVERY
    user's lookup falls back to them (status quo, the brief window before
    app._migrate_block3_flags_to_keyed runs at boot) — existing block-3
    tests across the suite rely on exactly this fallback."""
    app_, db = app_ctx
    uid_a = _make_user(app_, db, "i4-fallback-a@test.com")
    uid_b = _make_user(app_, db, "i4-fallback-b@test.com")
    start_b = START + timedelta(days=14)
    _set_appstate(app_, db, uid_a, START)
    _set_appstate(app_, db, uid_b, start_b)
    _set_unkeyed_block3_flags(app_, db, anchor=ANCHOR)

    def _check():
        import cut_guard
        return (
            cut_guard._block3_mode(uid_a), cut_guard._block3_anchor_and_start(uid_a),
            cut_guard._block3_mode(uid_b), cut_guard._block3_anchor_and_start(uid_b),
        )
    mode_a, as_a, mode_b, as_b = _do(app_, _check)
    assert mode_a is True and as_a == (ANCHOR, START)
    # Anchor is shared (only one legacy value exists); start_date is always
    # per-user (AppState, never SystemFlag) regardless of flag keying.
    assert mode_b is True and as_b == (ANCHOR, start_b)


# ── (d) one-shot migration ───────────────────────────────────────────────────

def _erik_uid(app_, db):
    return _make_user(app_, db, "erik@placemetry.com")


def _reset_migration_state(app_, db, erik_uid):
    def _do_it():
        from models import SystemFlag, AppState
        keys = [
            "block3_flags_keyed_v1", "projection_mode", "block3_anchor",
            "block3_prestate", f"projection_mode:{erik_uid}", f"block3_anchor:{erik_uid}",
        ]
        SystemFlag.query.filter(SystemFlag.key.in_(keys)).delete(synchronize_session=False)
        AppState.query.filter_by(user_id=erik_uid).delete()
        db.session.commit()
    _do(app_, _do_it)


def _run_migration(app_):
    def _do_it():
        import app as appmod
        appmod._migrate_block3_flags_to_keyed()
    _do(app_, _do_it)


def _flag_snapshot(app_, erik_uid):
    def _do_it():
        from models import SystemFlag
        def val(key):
            f = SystemFlag.query.filter_by(key=key).first()
            return f.value if f else None
        return {
            "keyed_pm": val(f"projection_mode:{erik_uid}"),
            "keyed_ba": val(f"block3_anchor:{erik_uid}"),
            "unkeyed_pm": val("projection_mode"),
            "unkeyed_ba": val("block3_anchor"),
            "marker": val("block3_flags_keyed_v1"),
        }
    return _do(app_, _do_it)


def test_migration_renames_unkeyed_rows_to_keyed_for_resolved_user(app_ctx):
    app_, db = app_ctx
    erik_uid = _erik_uid(app_, db)
    _reset_migration_state(app_, db, erik_uid)

    def _seed():
        from models import SystemFlag, AppState
        import transition_block3
        db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
        db.session.add(SystemFlag(key="block3_anchor", value="220.0"))
        db.session.add(SystemFlag(key="block3_prestate", value="{}"))
        db.session.add(AppState(user_id=erik_uid, current_week=1,
                                 start_date=transition_block3.TRANSITION_DATE))
        db.session.commit()
    _do(app_, _seed)

    _run_migration(app_)
    snap = _flag_snapshot(app_, erik_uid)
    assert snap["keyed_pm"] == "piecewise_block3"
    assert snap["keyed_ba"] == "220.0"
    assert snap["unkeyed_pm"] is None  # renamed, not copied — old row is gone
    assert snap["unkeyed_ba"] is None
    assert snap["marker"] == f"migrated_uid_{erik_uid}"

    # Idempotent: a second run is a pure no-op (marker guards re-entry).
    _run_migration(app_)
    snap2 = _flag_snapshot(app_, erik_uid)
    assert snap2 == snap


def test_migration_ambiguous_when_erik_user_does_not_exist(app_ctx, caplog):
    """Code-review fix-round-2 (finding I1): resolution is a plain email
    lookup for erik@placemetry.com -- run_transition is the only writer of
    these unkeyed rows and always writes block3_prestate in the SAME
    transaction, so a "has block3_prestate" corroboration check is always
    true whenever the unkeyed rows this function is already gated on
    exist; it was dead weight dressed up as a second signal. The only
    genuine ambiguity left is "no User row for that email at all" -- the
    migration must NOT guess a different user. Rows stay unkeyed, the
    marker is still set (so this never re-runs), and a loud warning is
    logged."""
    app_, db = app_ctx

    def _reset_no_erik():
        from models import SystemFlag, User
        SystemFlag.query.filter(SystemFlag.key.in_(
            ["block3_flags_keyed_v1", "projection_mode", "block3_anchor", "block3_prestate"]
        )).delete(synchronize_session=False)
        User.query.filter_by(email="erik@placemetry.com").delete(synchronize_session=False)
        db.session.commit()
    _do(app_, _reset_no_erik)

    def _seed():
        from models import SystemFlag
        db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
        db.session.add(SystemFlag(key="block3_anchor", value="220.0"))
        db.session.commit()
    _do(app_, _seed)
    # Deliberately NO User row for erik@placemetry.com at all.

    with caplog.at_level(logging.WARNING):
        _run_migration(app_)
    assert any("could not resolve" in r.message for r in caplog.records)

    def _check():
        from models import SystemFlag
        def val(key):
            f = SystemFlag.query.filter_by(key=key).first()
            return f.value if f else None
        return val("projection_mode"), val("block3_anchor"), val("block3_flags_keyed_v1")
    unkeyed_pm, unkeyed_ba, marker = _do(app_, _check)
    assert unkeyed_pm == "piecewise_block3"  # untouched
    assert unkeyed_ba == "220.0"
    assert marker == "ambiguous_no_migration"


def test_migration_collision_deletes_stale_unkeyed_row_not_left_forever(app_ctx, caplog):
    """Code-review fix-round-1 finding: if a KEYED row for the resolved
    user already exists (defensive/edge case -- shouldn't happen via any
    normal write path), the migration must not just skip-and-leave the
    unkeyed row in place. Since the marker is set unconditionally and this
    never re-runs, an orphaned unkeyed row left here would sit forever as
    a fallback hazard any OTHER user's cut_guard lookup could still hit --
    reproducing I-4. The pre-existing keyed row (already correct for the
    resolved user) must be left untouched; only the now-redundant unkeyed
    row is deleted."""
    app_, db = app_ctx
    erik_uid = _erik_uid(app_, db)
    _reset_migration_state(app_, db, erik_uid)

    def _seed():
        from models import SystemFlag, AppState
        import transition_block3
        db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
        db.session.add(SystemFlag(key="block3_anchor", value="220.0"))
        db.session.add(SystemFlag(key="block3_prestate", value="{}"))
        db.session.add(AppState(user_id=erik_uid, current_week=1,
                                 start_date=transition_block3.TRANSITION_DATE))
        # A keyed row ALREADY exists for erik_uid, pre-empting the rename.
        db.session.add(SystemFlag(key=f"projection_mode:{erik_uid}", value="already_here"))
        db.session.commit()
    _do(app_, _seed)

    with caplog.at_level(logging.WARNING):
        _run_migration(app_)
    assert any("already exists" in r.message for r in caplog.records)

    snap = _flag_snapshot(app_, erik_uid)
    assert snap["keyed_pm"] == "already_here"  # pre-existing keyed value untouched
    assert snap["unkeyed_pm"] is None  # the redundant unkeyed row is GONE, not orphaned
    # The non-colliding flag (block3_anchor) still migrates normally.
    assert snap["keyed_ba"] == "220.0"
    assert snap["unkeyed_ba"] is None
    assert snap["marker"] == f"migrated_uid_{erik_uid}"


# ── (e) transition/rollback write PATH: keyed only, never unkeyed ──────────

def test_transition_and_rollback_write_and_clear_keyed_flags_only(app_ctx):
    app_, db = app_ctx

    def _seed_minimal_user():
        from models import User, TrainingGoal, SystemFlag
        u = User.query.filter_by(email="i4-transition-write@test.com").first()
        if not u:
            u = User(email="i4-transition-write@test.com")
            db.session.add(u)
            db.session.commit()
        TrainingGoal.query.filter_by(user_id=u.id).delete()
        db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=185.0,
                                     tdee=2500, daily_calories=1800))
        SystemFlag.query.filter(SystemFlag.key.in_(
            [f"projection_mode:{u.id}", f"block3_anchor:{u.id}",
             "projection_mode", "block3_anchor", "block3_prestate"]
        )).delete(synchronize_session=False)
        db.session.commit()
        return u.id
    uid = _do(app_, _seed_minimal_user)

    def _run_transition():
        from transition_block3 import run_transition
        from models import User
        u = User.query.get(uid)
        status, body = run_transition(u, 220.0, dry_run=False)
        db.session.commit()
        return status, body
    status, body = _do(app_, _run_transition)
    assert status == 200, body

    def _flags():
        from models import SystemFlag
        def val(key):
            f = SystemFlag.query.filter_by(key=key).first()
            return f.value if f else None
        return {
            "keyed_pm": val(f"projection_mode:{uid}"),
            "keyed_ba": val(f"block3_anchor:{uid}"),
            "unkeyed_pm": val("projection_mode"),
            "unkeyed_ba": val("block3_anchor"),
        }
    after_transition = _do(app_, _flags)
    assert after_transition["keyed_pm"] == "piecewise_block3"
    assert after_transition["keyed_ba"] == "220.0"
    assert after_transition["unkeyed_pm"] is None
    assert after_transition["unkeyed_ba"] is None

    def _run_rollback():
        from transition_block3 import run_rollback
        from models import User
        u = User.query.get(uid)
        status, body = run_rollback(u)
        db.session.commit()
        return status, body
    status2, body2 = _do(app_, _run_rollback)
    assert status2 == 200, body2

    after_rollback = _do(app_, _flags)
    assert after_rollback == {
        "keyed_pm": None, "keyed_ba": None, "unkeyed_pm": None, "unkeyed_ba": None,
    }
