"""A finished weekly-program generation must not be hidden by a lost job.

The generation runs in a background thread and PERSISTS the program to the DB,
while the client polls /api/weekly-program/generate-status — which reads an
IN-PROCESS job store (_GEN_JOBS). That store is wiped on any worker restart
(a deploy mid-generation) or missed on a multi-worker poll. When that happens the
endpoint returned {"status":"none"}, the client polled fruitlessly for 3 min, and
the athlete saw nothing — even though the week was fully saved (Erik, 2026-06-07,
week 11). Fix: with no job, fall back to the source of truth — if the week has a
coach program, serialize and return it as done.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _user(db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    return u


def _client_for(app, uid):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return c


def test_status_falls_back_to_persisted_program_when_job_lost(app_ctx):
    """One ordered test (avoids module-fixture cross-test bleed): with no job and
    no program -> none; the moment a coach program is persisted (job still gone),
    the SAME poll recovers it as done."""
    app, db = app_ctx
    import app as appmod
    from models import WeeklyPrescription
    with app.app_context():
        uid = _user(db, "genfallback@test.com").id
        WeeklyPrescription.query.filter_by(user_id=uid, week=11).delete()
        db.session.commit()
        with appmod._GEN_JOBS_LOCK:
            appmod._GEN_JOBS.pop((uid, 11), None)
    client = _client_for(app, uid)

    # No job, no program -> genuinely nothing.
    assert client.get(
        "/api/weekly-program/generate-status?week=11").get_json()["status"] == "none"

    # Background generation finished + persisted, but the job store is still empty.
    with app.app_context():
        db.session.add(WeeklyPrescription(
            user_id=uid, week=11, day_idx=0, exercise_name="Barbell Back Squat",
            exercise_order=0, sets=3, reps="5", target_weight=165, source="coach"))
        db.session.commit()

    j = client.get("/api/weekly-program/generate-status?week=11").get_json()
    assert j["status"] == "done", j
    assert j.get("program"), j
