"""Coach tool: log_bodyweight — weight told to the coach in chat must land
in the BodyWeight table (the same table Stats/Progress read), not vanish."""
import json
from datetime import date

import pytest


@pytest.fixture
def user_id():
    from app import app, db
    from models import User, BodyWeight
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="bwtool@test.com").first()
        if not u:
            u = User(email="bwtool@test.com", password_hash="x")
            db.session.add(u)
            db.session.commit()
        BodyWeight.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        yield u.id


def test_log_bodyweight_creates_row(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyWeight
    with app.app_context():
        out = json.loads(execute_tool("log_bodyweight", {"weight_lbs": 211.4}, user_id=user_id))
        assert out.get("ok") is True
        row = BodyWeight.query.filter_by(user_id=user_id).one()
        assert row.weight_lbs == 211.4


def test_log_bodyweight_updates_same_day(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyWeight
    with app.app_context():
        execute_tool("log_bodyweight", {"weight_lbs": 211.4}, user_id=user_id)
        execute_tool("log_bodyweight", {"weight_lbs": 210.8}, user_id=user_id)
        rows = BodyWeight.query.filter_by(user_id=user_id).all()
        assert len(rows) == 1
        assert rows[0].weight_lbs == 210.8


def test_log_bodyweight_explicit_date(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyWeight
    with app.app_context():
        out = json.loads(execute_tool(
            "log_bodyweight", {"weight_lbs": 212.0, "date": "2026-08-18"}, user_id=user_id))
        assert out.get("ok") is True
        row = BodyWeight.query.filter_by(user_id=user_id).one()
        assert row.log_date == date(2026, 8, 18)


def test_log_bodyweight_rejects_garbage(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyWeight
    with app.app_context():
        out = json.loads(execute_tool("log_bodyweight", {"weight_lbs": 21.4}, user_id=user_id))
        assert "error" in out
        assert BodyWeight.query.filter_by(user_id=user_id).count() == 0


def test_log_bodyweight_tool_is_declared():
    from coach_tools import TOOLS
    assert any(t["name"] == "log_bodyweight" for t in TOOLS)
