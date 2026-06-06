"""Deterministic output gate: the coach LLM keeps prescribing a lift the athlete
already logged (it told Erik to do Back Squat 3×5 @155 he'd just finished). The
prompt + grounding don't stop it, so the gate strips the prescription before the
response ships — no LLM call, guaranteed."""
import pytest

SCREENSHOT = (
    "Heavy after yesterday's tempo is expected — 5.38 mi at HR 140 leaves a tax. "
    "Recovery jog did its job keeping it light at HR 119. "
    "HEAVY Lower still on deck — Back Squat 3×5 @ 155 leads. "
    "Heavy legs don't change the prescription, but they change the warmup: extra "
    "ramp set at 95, then 135, then work. If rep 1 at 155 moves slow, hold 155 "
    "across all three. No ego jumps. Report after the squats.")


def _gate_with_logged_lift(text):
    from app import app, db, _gate_coach_response, _current_week, _user_today
    from models import User, SetLog
    from flask_login import login_user
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="gate@test.com").first()
        if not u:
            u = User(email="gate@test.com")
            db.session.add(u)
            db.session.commit()
        uid = u.id
        with app.test_request_context():
            login_user(db.session.get(User, uid), force=True)
            wk, didx = _current_week(), _user_today().weekday()
            if not SetLog.query.filter_by(user_id=uid, week=wk, day_idx=didx).first():
                db.session.add(SetLog(
                    user_id=uid, week=wk, day_idx=didx,
                    exercise_name="Barbell Back Squat", set_number=0,
                    weight=155, reps=5, done=True))
                db.session.commit()
            return _gate_coach_response(text, uid)


def test_gate_strips_already_done_lift_keeps_the_run_analysis():
    out = _gate_with_logged_lift(SCREENSHOT)
    # the already-done lift prescription is gone
    assert "Back Squat" not in out
    assert "Report after" not in out
    assert "on deck" not in out.lower()
    assert "no ego" not in out.lower()
    # the run analysis survives
    assert "Recovery jog did its job" in out
    # honest closer added
    assert "already logged" in out


def test_gate_is_noop_when_nothing_logged_and_not_a_fast_day():
    from app import app, db, _gate_coach_response
    from models import User
    from flask_login import login_user
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="nogate@test.com").first()
        if not u:
            u = User(email="nogate@test.com")
            db.session.add(u)
            db.session.commit()
        uid = u.id
        with app.test_request_context():
            login_user(db.session.get(User, uid), force=True)
            # no SetLog today, not a fast day -> text returned untouched
            out = _gate_coach_response("Back Squat 3×5 @ 155 is on deck. Go.", uid)
    assert out == "Back Squat 3×5 @ 155 is on deck. Go."
