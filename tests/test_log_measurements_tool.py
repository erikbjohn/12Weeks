"""Coach tool: log_measurements — tape measurements told to the coach in chat
must land in BodyMeasurement (the table Stats/Progress read), not vanish.

2026-08-29: Erik gave the coach his full tape before travel; the coach said
"Logging the set… Logged" and NO TOOL EXISTED — nothing was written, and the
Stats panel kept showing the Aug 23 row. Same failure class as the chat
bodyweight (10e4a51), now closed for measurements.
"""
import json
from datetime import date

import pytest


@pytest.fixture
def user_id():
    from app import app, db
    from models import User, BodyMeasurement
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="meastool@test.com").first()
        if not u:
            u = User(email="meastool@test.com", password_hash="x")
            db.session.add(u)
            db.session.commit()
        BodyMeasurement.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        yield u.id


def test_log_measurements_creates_row_and_mirrors_single_sides(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyMeasurement
    with app.app_context():
        out = json.loads(execute_tool("log_measurements", {
            "waist": 38.0, "chest": 41.0, "hips": 41.0, "neck": 15.0,
            "bicep": 14.0, "thigh": 25.5, "date": "2026-08-29",
        }, user_id=user_id))
        assert out.get("ok") is True
        row = BodyMeasurement.query.filter_by(user_id=user_id).one()
        assert row.log_date == date(2026, 8, 29)
        assert row.waist_inches == 38.0 and row.chest == 41.0
        assert row.hips == 41.0 and row.neck == 15.0
        assert row.bicep_left == 14.0 and row.bicep_right == 14.0, "single bicep → both sides"
        assert row.thigh_left == 25.5 and row.thigh_right == 25.5, "single thigh → both sides"


def test_log_measurements_upserts_and_keeps_unmentioned_fields(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyMeasurement
    with app.app_context():
        execute_tool("log_measurements", {"waist": 38.0, "neck": 15.0,
                                          "date": "2026-08-29"}, user_id=user_id)
        out = json.loads(execute_tool("log_measurements", {
            "waist": 37.5, "date": "2026-08-29"}, user_id=user_id))
        assert out.get("ok") is True
        row = BodyMeasurement.query.filter_by(user_id=user_id).one()
        assert row.waist_inches == 37.5, "same-day repeat updates"
        assert row.neck == 15.0, "a partial update must never blank other fields"


def test_log_measurements_per_side_values_win(user_id):
    from app import app
    from coach_tools import execute_tool
    from models import BodyMeasurement
    with app.app_context():
        out = json.loads(execute_tool("log_measurements", {
            "bicep_left": 14.5, "bicep_right": 14.0, "date": "2026-08-23",
        }, user_id=user_id))
        assert out.get("ok") is True
        row = BodyMeasurement.query.filter_by(user_id=user_id).one()
        assert row.bicep_left == 14.5 and row.bicep_right == 14.0


def test_log_measurements_rejects_garbage(user_id):
    from app import app
    from coach_tools import execute_tool
    with app.app_context():
        out = json.loads(execute_tool("log_measurements", {"waist": 3.0}, user_id=user_id))
        assert "error" in out, "a 3-inch waist is a bad tape read, refuse it"
        out2 = json.loads(execute_tool("log_measurements", {"date": "2026-08-29"}, user_id=user_id))
        assert "error" in out2, "no measurements at all → error, not an empty row"


def test_tool_is_declared_and_prompt_teaches_it():
    from coach_tools import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "log_measurements" in names
    import coach_with_tools
    src = open(coach_with_tools.__file__).read()
    assert "log_measurements" in src, "the tool-usage prompt must teach it like log_bodyweight"
