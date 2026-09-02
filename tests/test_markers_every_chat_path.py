"""S007: a taught marker persists through BOTH chat endpoints. Red before the
non-stream path called _parse_coach_markers; green now — and it stays green
only if both paths keep codifying."""
import pytest
from datetime import date


@pytest.fixture
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _seed(app_, db, email):
    from models import User, UserEquipment, PhysicalAssessment, AppState, WeeklyRunPlan, WeeklyPrescription
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email, password_hash="x", email_verified=True)
        db.session.add(u); db.session.commit()
        db.session.add(UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells"]))
        db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    AppState.query.filter_by(user_id=u.id).delete()
    db.session.add(AppState(user_id=u.id, start_date=date(2026, 8, 10), current_week=4))
    WeeklyRunPlan.query.filter_by(user_id=u.id, week=4).delete()
    WeeklyPrescription.query.filter_by(user_id=u.id, week=4).delete()
    for d in range(7):
        db.session.add(WeeklyRunPlan(user_id=u.id, week=4, day_idx=d, run_type="z2", label="Zone 2 Easy",
                                     duration="50 min", detail="50 min easy", source="coach"))
    db.session.add(WeeklyPrescription(user_id=u.id, week=4, day_idx=0, exercise_order=0, exercise_name="Barbell Bench Press",
                                      sets=4, reps="8", target_weight=125, source="coach"))
    db.session.commit()
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id); s["_fresh"] = True; s["_csrf_token"] = "tok"
    return u, client


REPLY = ("Run change noted. [RUN: day=2, duration=30 min, type=z2, label=Easy, detail=30 min easy Z2, reason=t] "
         "And the swap: [SWAP: day_idx=0, exercise_idx=0, old=Barbell Bench Press, new={alt}, reason=t]")


def _alt():
    from equipment_swaps import get_alternatives
    alts = get_alternatives("Barbell Bench Press") or []
    names = [a.get("name") if isinstance(a, dict) else a for a in alts]
    return names[0]


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_run_and_swap_markers_persist_on_both_paths(app_ctx, monkeypatch, path):
    app_, db = app_ctx
    u, client = _seed(app_, db, f"markers-{path.replace('/', '_')}@test.com")
    import app as appmod, coach_with_tools, coach_assembler
    reply = REPLY.format(alt=_alt())
    monkeypatch.setattr(coach_with_tools, "coach_chat", lambda **kw: reply)
    monkeypatch.setattr(coach_with_tools, "coach_chat_stream", lambda **kw: iter([reply]))
    monkeypatch.setattr(appmod, "extract_memories", lambda *a, **k: [])
    monkeypatch.setattr(coach_assembler, "_current_week", lambda: 4)
    appmod._chat_rate_limit[u.id] = 0
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    r = client.post(path, json={"message": "change tuesday to 30 easy and swap bench"}, headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    r.get_data()   # drain the stream so its finally-block codifies
    from models import WeeklyRunPlan, ExerciseSwap, RunOverride
    rp = WeeklyRunPlan.query.filter_by(user_id=u.id, week=4, day_idx=2).first()
    assert rp.label == "Easy" and rp.duration == "30 min", (path, rp.label, rp.duration)
    assert RunOverride.query.filter_by(user_id=u.id, week=4, day_idx=2).first() is not None
    assert ExerciseSwap.query.filter_by(user_id=u.id, week=4, day_idx=0, exercise_idx=0).first() is not None, path
