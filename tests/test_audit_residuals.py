"""Regression tests for residuals found by the post-fix adversarial review
(2026-07-02). Each locks a fix applied after the main themed pass:

  B) _serialize_weights (the /api/export weights block) must count only
     PERFORMED sets (done, not skipped) — else an export->import round-trip
     launders a typed-but-abandoned set into a "performed" PR.
  E) POST /api/sets must stamp logged_date to today on the first completion
     (done False->True) so a set blur-created earlier but performed today reads
     as trained-today — while still PRESERVING the date on a later edit of an
     already-done past set.
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_export_weights_excludes_undone_sets(app_ctx):
    import app as appmod
    from models import User, SetLog
    _, db = app_ctx
    u = User.query.filter_by(email="resid-export@test.com").first()
    if not u:
        u = User(email="resid-export@test.com")
        db.session.add(u); db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    # A real performed set at 100, plus a phantom 999 typed-but-not-done and a
    # skipped 500 — only 100 may surface in the export.
    db.session.add(SetLog(user_id=u.id, week=5, day_idx=1, set_number=0,
                          exercise_name="Barbell Bench Press", weight=100, reps=5,
                          done=True, logged_date=date(2026, 5, 4)))
    db.session.add(SetLog(user_id=u.id, week=5, day_idx=1, set_number=1,
                          exercise_name="Barbell Bench Press", weight=999, reps=1,
                          done=False, logged_date=date(2026, 5, 4)))
    db.session.add(SetLog(user_id=u.id, week=5, day_idx=1, set_number=2,
                          exercise_name="Barbell Bench Press", weight=500, reps=1,
                          done=True, set_skipped=True, logged_date=date(2026, 5, 4)))
    db.session.commit()
    out = appmod._serialize_weights(user_id=u.id)
    assert "Barbell Bench Press" in out
    weights = [h["weight"] for h in out["Barbell Bench Press"]["history"]]
    assert weights == [100], f"expected only the performed set, got {weights}"
    assert out["Barbell Bench Press"]["current"] == 100


def test_logged_date_stamps_on_first_completion_but_not_on_edit(app_ctx):
    from flask_login import login_user
    from workout_data import resolve_name
    import app as appmod
    from models import User, SetLog
    app_, db = app_ctx
    today = appmod._user_today()
    older = today - timedelta(days=3)
    # Seed with the SAME canonical name the POST handler resolves to, so the
    # upsert matches the seeded row instead of creating a new one.
    ex = resolve_name("Back Squat")

    u = User.query.filter_by(email="resid-logdate@test.com").first()
    if not u:
        u = User(email="resid-logdate@test.com")
        db.session.add(u); db.session.commit()
    SetLog.query.filter_by(user_id=u.id).delete()
    db.session.commit()

    # (E1) A set blur-created 3 days ago (done=False), completed TODAY -> re-stamp.
    db.session.add(SetLog(user_id=u.id, week=7, day_idx=2, set_number=0,
                          exercise_name=ex, weight=185, reps=5,
                          done=False, logged_date=older))
    # (E2) A set genuinely performed 3 days ago (done=True) -> edit must preserve.
    db.session.add(SetLog(user_id=u.id, week=7, day_idx=2, set_number=1,
                          exercise_name=ex, weight=185, reps=5,
                          done=True, logged_date=older))
    db.session.commit()

    with app_.test_request_context(json={
        "exercise": ex, "week": 7, "day_idx": 2,
        "set_number": 0, "weight": 185, "reps": 5, "done": True}):
        login_user(u, force=True)
        appmod.api_set_log()
    with app_.test_request_context(json={
        "exercise": ex, "week": 7, "day_idx": 2,
        "set_number": 1, "weight": 190, "reps": 5, "done": True}):
        login_user(u, force=True)
        appmod.api_set_log()

    completed = SetLog.query.filter_by(user_id=u.id, set_number=0).first()
    edited = SetLog.query.filter_by(user_id=u.id, set_number=1).first()
    assert completed.logged_date == today, "first completion should stamp today"
    assert edited.logged_date == older, "editing an already-done past set must preserve its date"
