"""Theme 5-three-state (2026-07-01 audit): a PARTIAL workout must NEVER read
complete, anywhere.

Canonical rule (workout_status.workout_state_from_rows): a slot is COMPLETE only
when EVERY prescribed exercise has its prescribed number of sets PERFORMED
(SetLog.done and not set_skipped), matched name-aware. Findings covered:

- app.py /api/sets auto-complete compared a name-agnostic COUNT of done rows
  against the day's set total, so extra sets on one exercise substituted for a
  skipped movement and DayCompletion was created for a partial day.
- app.py _build_coach_context / coach_assembler._build_completed_days marked a
  day "completed this week" off a single done set (morning-briefing coach saw a
  1-set aborted session as a banked day).
- coach_assembler._build_today_status and coach_rules._compute_workout_status
  had a "6+ sets today / 3+ done" heuristic that OR'd in complete while whole
  exercises were still open.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from workout_status import parse_sets_count, workout_state_from_rows


def _row(name, done=True, skipped=False):
    return SimpleNamespace(exercise_name=name, done=done, set_skipped=skipped)


# ---------------------------------------------------------------------------
# Pure canonical helper
# ---------------------------------------------------------------------------

class TestWorkoutStateFromRows:
    RX = [
        {"name": "Barbell Bench Press", "sets": 3},
        {"name": "Barbell Row", "sets": 3},
        {"name": "Barbell Back Squat", "sets": 3},
    ]

    def test_extra_sets_do_not_substitute_for_a_skipped_exercise(self):
        # The exact audit failure: 9 prescribed sets; 5 bench + 4 row done,
        # squats untouched. Old count-based check: 9 >= 9 -> complete. Wrong.
        rows = [_row("Barbell Bench Press")] * 5 + [_row("Barbell Row")] * 4
        assert workout_state_from_rows(self.RX, rows) == "in_progress"

    def test_every_exercise_at_prescribed_sets_is_complete(self):
        rows = ([_row("Barbell Bench Press")] * 3
                + [_row("Barbell Row")] * 3
                + [_row("Barbell Back Squat")] * 3)
        assert workout_state_from_rows(self.RX, rows) == "complete"

    def test_all_exercises_touched_but_sets_short_is_in_progress(self):
        rows = [_row("Barbell Bench Press"), _row("Barbell Row"),
                _row("Barbell Back Squat")]
        assert workout_state_from_rows(self.RX, rows) == "in_progress"

    def test_no_rows_is_not_started(self):
        assert workout_state_from_rows(self.RX, []) == "not_started"

    def test_undone_or_skipped_sets_do_not_count(self):
        rows = ([_row("Barbell Bench Press")] * 3
                + [_row("Barbell Row")] * 2 + [_row("Barbell Row", done=False)]
                + [_row("Barbell Back Squat")] * 2
                + [_row("Barbell Back Squat", skipped=True)])
        assert workout_state_from_rows(self.RX, rows) == "in_progress"

    def test_unplanned_day_never_reads_complete_from_set_counts(self):
        # Coach-or-nothing: no prescription -> rows alone can't complete a day.
        rows = [_row("Barbell Bench Press")] * 12
        assert workout_state_from_rows([], rows) == "in_progress"
        assert workout_state_from_rows(None, rows) == "in_progress"

    def test_sets_string_formats_parse(self):
        assert parse_sets_count(4) == 4
        assert parse_sets_count("4") == 4
        assert parse_sets_count("4x8") == 4
        assert parse_sets_count("3 x 12") == 3
        assert parse_sets_count(None) == 1  # unknown -> at least one set
        assert parse_sets_count("") == 1

    def test_name_matching_is_alias_and_case_aware(self):
        rx = [{"name": "Barbell Bench Press", "sets": "2x8"}]
        rows = [_row("barbell bench press"), _row("Barbell Bench Press")]
        assert workout_state_from_rows(rx, rows) == "complete"


# ---------------------------------------------------------------------------
# DB-backed paths
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _fresh_user(db, email):
    from models import User, SetLog, DayCompletion, WeeklyPrescription
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    DayCompletion.query.filter_by(user_id=u.id).delete()
    WeeklyPrescription.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return u


def _client_for(app_, u):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)
        s["_fresh"] = True
    return client


def _seed_rx(db, uid, week, day_idx, names, sets=2):
    from models import WeeklyPrescription
    for i, n in enumerate(names):
        db.session.add(WeeklyPrescription(
            user_id=uid, week=week, day_idx=day_idx, exercise_order=i,
            exercise_name=n, sets=sets, reps="8", rest="90s", source="coach"))
    db.session.commit()


def _resolved_names(app_, u, week, day_idx):
    """Post-equipment/manual-swap prescription names, as the UI shows them."""
    import coach_assembler as ca
    from flask_login import login_user
    with app_.test_request_context():
        login_user(u, force=True)
        resolved = ca._resolve_workout_for_day(week, day_idx) or {}
        return [e.get("name") for e in resolved.get("exercises", []) if e.get("name")]


def test_api_sets_autocomplete_requires_every_exercise(app_ctx):
    """Extra done sets on one exercise must NOT auto-complete the day while a
    prescribed movement is untouched (the old COUNT-based check did)."""
    app_, db = app_ctx
    from models import DayCompletion
    u = _fresh_user(db, "threestate-autocomplete@test.com")
    _seed_rx(db, u.id, 4, 2, ["Barbell Bench Press", "Barbell Row"], sets=2)
    names = _resolved_names(app_, u, 4, 2)
    assert len(names) == 2, names
    client = _client_for(app_, u)

    # 4 done sets of exercise ONE (total prescribed sets = 4) — second exercise
    # untouched. Old behavior: done_count 4 >= total 4 -> DayCompletion. Wrong.
    for sn in range(4):
        r = client.post("/api/sets", json={
            "exercise": names[0], "week": 4, "day_idx": 2,
            "set_number": sn, "weight": 100, "reps": 8, "done": True})
        assert r.status_code == 200, r.get_data(as_text=True)
    assert DayCompletion.query.filter_by(user_id=u.id, week=4, day_idx=2).first() is None, \
        "partial day (whole exercise skipped) must not auto-complete"

    # Now perform the second exercise's 2 prescribed sets -> day completes.
    for sn in range(2):
        r = client.post("/api/sets", json={
            "exercise": names[1], "week": 4, "day_idx": 2,
            "set_number": sn, "weight": 80, "reps": 8, "done": True})
        assert r.status_code == 200, r.get_data(as_text=True)
    dc = DayCompletion.query.filter_by(user_id=u.id, week=4, day_idx=2).first()
    assert dc is not None and dc.done, "fully-performed prescription must auto-complete"
    assert dc.completed_at, "auto-complete must stamp completed_at (date-gate)"


def test_coach_rules_partial_seven_done_sets_is_in_progress(app_ctx):
    """7 done sets across 2 of the prescribed exercises used to trip the
    6-sets/3-done heuristic and read complete. Must be in_progress."""
    app_, db = app_ctx
    from models import SetLog
    from flask_login import login_user
    import coach_rules as cr
    u = _fresh_user(db, "threestate-rules@test.com")
    today = date.today()
    _seed_rx(db, u.id, 5, 0,
             ["Barbell Bench Press", "Barbell Row", "Barbell Back Squat"], sets=4)
    names = _resolved_names(app_, u, 5, 0)
    for sn in range(4):
        db.session.add(SetLog(user_id=u.id, week=5, day_idx=0, exercise_name=names[0],
                              set_number=sn, weight=100, reps=8, done=True,
                              logged_date=today))
    for sn in range(3):
        db.session.add(SetLog(user_id=u.id, week=5, day_idx=0, exercise_name=names[1],
                              set_number=sn, weight=80, reps=8, done=True,
                              logged_date=today))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        s = cr._compute_workout_status(u.id, 5, 0, today, is_rest=False)
    assert s == "in_progress", f"7 done sets of a 12-set/3-exercise day read {s}"


def test_coach_rules_complete_when_every_prescribed_set_done(app_ctx):
    app_, db = app_ctx
    from models import SetLog
    from flask_login import login_user
    import coach_rules as cr
    u = _fresh_user(db, "threestate-rules-done@test.com")
    today = date.today()
    _seed_rx(db, u.id, 5, 0, ["Barbell Bench Press", "Barbell Row"], sets=2)
    names = _resolved_names(app_, u, 5, 0)
    for n in names:
        for sn in range(2):
            db.session.add(SetLog(user_id=u.id, week=5, day_idx=0, exercise_name=n,
                                  set_number=sn, weight=100, reps=8, done=True,
                                  logged_date=today))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        s = cr._compute_workout_status(u.id, 5, 0, today, is_rest=False)
    assert s == "complete", s


def test_completed_days_this_week_excludes_partial_days(app_ctx, monkeypatch):
    """A 1-set aborted session must not appear in completed_days_this_week
    (the morning-briefing coach used to see it as a banked [DONE] day)."""
    app_, db = app_ctx
    from models import SetLog
    from flask_login import login_user
    import coach_assembler as ca
    u = _fresh_user(db, "threestate-week@test.com")
    today = date.today()
    week = 5
    day_idx = today.weekday()
    _seed_rx(db, u.id, week, day_idx, ["Barbell Bench Press", "Barbell Row"], sets=3)
    names = _resolved_names(app_, u, week, day_idx)
    # ONE done set — an aborted session.
    db.session.add(SetLog(user_id=u.id, week=week, day_idx=day_idx,
                          exercise_name=names[0], set_number=0, weight=100,
                          reps=8, done=True, logged_date=today))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: week)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        out = ca._build_completed_days()["completed_days_this_week"]
    assert day_idx not in [e["day_idx"] for e in out], out

    # Finish every prescribed set -> the day IS completed.
    from models import SetLog as SL
    db.session.add(SL(user_id=u.id, week=week, day_idx=day_idx,
                      exercise_name=names[0], set_number=1, weight=100,
                      reps=8, done=True, logged_date=today))
    db.session.add(SL(user_id=u.id, week=week, day_idx=day_idx,
                      exercise_name=names[0], set_number=2, weight=100,
                      reps=8, done=True, logged_date=today))
    for sn in range(3):
        db.session.add(SL(user_id=u.id, week=week, day_idx=day_idx,
                          exercise_name=names[1], set_number=sn, weight=80,
                          reps=8, done=True, logged_date=today))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_current_week", lambda: week)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        out = ca._build_completed_days()["completed_days_this_week"]
    assert day_idx in [e["day_idx"] for e in out], out
