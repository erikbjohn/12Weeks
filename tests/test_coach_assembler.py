"""Tests for the rewritten coach_assembler section builders."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


_USER_SEQ = [0]


def _make_user(app_ctx):
    from models import User, UserEquipment, PhysicalAssessment
    app, db = app_ctx
    _USER_SEQ[0] += 1
    u = User(email=f"asm-{_USER_SEQ[0]}@example.com", password_hash="x")
    db.session.add(u); db.session.commit()
    eq = UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells"])
    pa = PhysicalAssessment(user_id=u.id, has_gym=True)
    db.session.add(eq); db.session.add(pa); db.session.commit()
    return u


class TestEventTimeline:
    def test_empty_timeline_returns_sentinel(self, app_ctx):
        from coach_assembler import _build_event_timeline
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_event_timeline()
        assert "event_timeline" in out
        assert "<event_timeline>" in out["event_timeline"]
        assert "NONE" in out["event_timeline"]

    def test_includes_set_log_events(self, app_ctx):
        from coach_assembler import _build_event_timeline
        from models import SetLog
        from datetime import date
        from app import db
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        db.session.add(SetLog(
            user_id=u.id, exercise_name="Front Squat", week=5, day_idx=0,
            set_number=1, weight=175, reps=5, done=True, logged_date=date.today(),
        ))
        db.session.commit()
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_event_timeline()
        assert "Front Squat" in out["event_timeline"]
        assert "175" in out["event_timeline"]


class TestRecentCoachDirectives:
    def test_returns_sentinel_when_no_messages(self, app_ctx):
        from coach_assembler import _build_recent_coach_directives
        from flask_login import login_user
        app, _ = app_ctx
        u = _make_user(app_ctx)
        with app.test_request_context():
            login_user(u, force=True)
            out = _build_recent_coach_directives()
        assert "recent_coach_directives" in out
        assert "<recent_coach_directives>" in out["recent_coach_directives"]
        assert "NONE" in out["recent_coach_directives"]
