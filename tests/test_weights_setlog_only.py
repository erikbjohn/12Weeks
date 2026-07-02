"""ExerciseLog is DEAD — /api/weights (GET+POST), /api/weights/baseline and
/api/import must live entirely on SetLog.

Audit 2026-07-01 (theme 4-exerciselog):
- app.py:3699  POST /api/weights wrote a duplicate summary row into ExerciseLog
  and GET merged ExerciseLog with SetLog, double-counting the same session.
- app.py:6051  /api/import restored backups into ExerciseLog while /api/export
  builds them from SetLog, so a round trip silently lost the history.
- static/app.js:12040  recordWeight() POSTed the ExerciseLog duplicate.
"""
from datetime import date

import pytest


@pytest.fixture(scope="module")
def client_ctx():
    from app import app, db
    from models import User
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="weights-setlog@test.com").first()
        if not u:
            u = User(email="weights-setlog@test.com", name="WeightsSetLog",
                     role="user", email_verified=True)
            db.session.add(u)
            db.session.commit()
        uid = u.id
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return client, app, uid


def _wipe(app, uid):
    from app import db
    from models import SetLog, ExerciseLog
    with app.app_context():
        SetLog.query.filter_by(user_id=uid).delete()
        ExerciseLog.query.filter_by(user_id=uid).delete()
        db.session.commit()


def test_post_weights_writes_setlog_never_exerciselog(client_ctx):
    client, app, uid = client_ctx
    _wipe(app, uid)
    r = client.post("/api/weights", json={
        "exercise": "Goblet Squat", "weight": 60, "reps_completed": 10,
        "week": 3, "day_idx": 2,
    })
    assert r.status_code == 200, r.data[:200]
    from models import SetLog, ExerciseLog
    with app.app_context():
        assert ExerciseLog.query.filter_by(user_id=uid).count() == 0, \
            "POST /api/weights wrote to the dead ExerciseLog table"
        rows = SetLog.query.filter_by(user_id=uid, exercise_name="Goblet Squat").all()
        assert len(rows) == 1
        assert rows[0].done is True
        assert rows[0].weight == 60
        assert rows[0].reps == 10
        assert rows[0].week == 3 and rows[0].day_idx == 2


def test_post_weights_noop_when_sets_already_logged(client_ctx):
    """Focus mode saves each set via /api/sets first; the summary POST must not
    add a second row for the same session."""
    client, app, uid = client_ctx
    _wipe(app, uid)
    from app import db
    from models import SetLog
    with app.app_context():
        db.session.add(SetLog(user_id=uid, exercise_name="DB Bench Press",
                              week=5, day_idx=1, set_number=0, weight=70,
                              reps=8, done=True, logged_date=date(2026, 6, 1)))
        db.session.commit()
    r = client.post("/api/weights", json={
        "exercise": "DB Bench Press", "weight": 70, "reps_completed": 8,
        "week": 5, "day_idx": 1,
    })
    assert r.status_code == 200
    assert r.get_json().get("already_logged") is True
    with app.app_context():
        assert SetLog.query.filter_by(user_id=uid, exercise_name="DB Bench Press",
                                      week=5, day_idx=1).count() == 1


def test_get_weights_reads_only_setlog(client_ctx):
    """Legacy ExerciseLog rows, undone sets and skipped sets must not appear."""
    client, app, uid = client_ctx
    _wipe(app, uid)
    from app import db
    from models import SetLog, ExerciseLog
    with app.app_context():
        # Legacy dead-table row — must be invisible.
        db.session.add(ExerciseLog(user_id=uid, exercise_name="Front Squat",
                                   weight=999, week=2, day_idx=0,
                                   logged_date=date(2026, 4, 1)))
        # Performed set — the only thing that counts.
        db.session.add(SetLog(user_id=uid, exercise_name="Front Squat",
                              week=6, day_idx=0, set_number=0, weight=115,
                              reps=5, done=True, logged_date=date(2026, 6, 8)))
        # Typed but never completed — NOT a performed set.
        db.session.add(SetLog(user_id=uid, exercise_name="Front Squat",
                              week=6, day_idx=3, set_number=0, weight=500,
                              reps=5, done=False, logged_date=date(2026, 6, 11)))
        # Skipped set — NOT a performed set.
        db.session.add(SetLog(user_id=uid, exercise_name="Front Squat",
                              week=6, day_idx=4, set_number=0, weight=400,
                              reps=5, done=True, set_skipped=True,
                              logged_date=date(2026, 6, 12)))
        db.session.commit()
    data = client.get("/api/weights").get_json()
    hist = data["Front Squat"]["history"]
    assert len(hist) == 1, f"expected only the performed set, got {hist}"
    assert hist[0]["weight"] == 115
    assert data["Front Squat"]["current"] == 115


def test_baseline_writes_performed_test_set_to_setlog(client_ctx):
    client, app, uid = client_ctx
    _wipe(app, uid)
    r = client.post("/api/weights/baseline", json={"exercises": [{
        "name": "Barbell Bench Press", "working_weight": 105,
        "test_weight": 95, "test_reps": 8, "estimated_1rm": 120,
    }]})
    assert r.status_code == 200, r.data[:200]
    from models import SetLog, ExerciseLog
    with app.app_context():
        assert ExerciseLog.query.filter_by(user_id=uid).count() == 0
        row = SetLog.query.filter_by(user_id=uid, week=0, day_idx=0).one()
        assert row.exercise_name == "Barbell Bench Press"
        assert row.weight == 95 and row.reps == 8 and row.done is True
    # Redoing the baseline upserts — no duplicate rows.
    client.post("/api/weights/baseline", json={"exercises": [{
        "name": "Barbell Bench Press", "working_weight": 110,
        "test_weight": 95, "test_reps": 10, "estimated_1rm": 127,
    }]})
    with app.app_context():
        rows = SetLog.query.filter_by(user_id=uid, week=0, day_idx=0).all()
        assert len(rows) == 1
        assert rows[0].reps == 10


def test_export_import_roundtrip_restores_setlog_history(client_ctx):
    client, app, uid = client_ctx
    _wipe(app, uid)
    from app import db
    from models import SetLog, ExerciseLog
    with app.app_context():
        for i, (w, reps) in enumerate([(60, 8), (65, 6), (70, 5)]):
            db.session.add(SetLog(user_id=uid, exercise_name="Romanian Deadlift",
                                  week=4, day_idx=2, set_number=i, weight=w,
                                  reps=reps, done=True,
                                  logged_date=date(2026, 5, 20)))
        db.session.commit()
    backup = client.get("/api/export").get_json()
    assert "Romanian Deadlift" in backup["weights"]

    _wipe(app, uid)  # simulate wipe/migration
    r = client.post("/api/import", json={"weights": backup["weights"]})
    assert r.status_code == 200, r.data[:200]
    with app.app_context():
        assert ExerciseLog.query.filter_by(user_id=uid).count() == 0, \
            "/api/import wrote to the dead ExerciseLog table"
        rows = SetLog.query.filter_by(user_id=uid,
                                      exercise_name="Romanian Deadlift").all()
        assert len(rows) == 1  # export collapses the session to its top set
        assert rows[0].weight == 70 and rows[0].done is True

    # Restored history is visible to the SetLog-based readers.
    data = client.get("/api/weights").get_json()
    assert data["Romanian Deadlift"]["current"] == 70
    from lift_history import lift_session_history
    with app.app_context():
        sess = lift_session_history(uid, "Romanian Deadlift")
        assert sess and sess[-1]["top_weight"] == 70

    # Re-import is idempotent — no duplicates.
    client.post("/api/import", json={"weights": backup["weights"]})
    with app.app_context():
        assert SetLog.query.filter_by(user_id=uid,
                                      exercise_name="Romanian Deadlift").count() == 1
