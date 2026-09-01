"""S025: a glutening is CODIFIED (BodyWeight.event) via the tool or the
[SCALE_EVENT] marker, and every despike consumer treats it as authoritative."""
from datetime import date, timedelta
from dataclasses import dataclass
import pytest


@dataclass
class Row:
    log_date: date
    weight_lbs: float
    event: str = None


def test_codified_gluten_event_is_authoritative_without_a_visible_jump():
    """A +2 lb morning after a gluten event (masked by the cut's own slope)
    would never trip the inferred 3-8 lb band — the event makes it spiked."""
    from cut_guard import detect_water_spike
    d0 = date(2026, 9, 1)
    rows = [Row(d0, 202.0, event="gluten"), Row(d0 - timedelta(days=1), 200.0),
            Row(d0 - timedelta(days=2), 200.4), Row(d0 - timedelta(days=3), 200.8)]
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=2.5)
    assert spiked is True
    assert wt == pytest.approx(200.0 - 2.5 / 7)


def test_event_clears_when_weight_returns_to_trend():
    from cut_guard import detect_water_spike
    d0 = date(2026, 9, 8)
    rows = [Row(d0, 197.0), Row(d0 - timedelta(days=7), 205.0, event="gluten"),
            Row(d0 - timedelta(days=8), 199.5), Row(d0 - timedelta(days=9), 199.9)]
    _, spiked = detect_water_spike(rows, expected_weekly_loss=2.5)
    assert spiked is False


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_tool_and_marker_write_the_event(app_ctx):
    app_, db = app_ctx
    from models import User, BodyWeight
    import app as app_module
    from coach_tools import _tool_log_bodyweight
    u = User(email="scale-event@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    with app_.test_request_context():
        out = _tool_log_bodyweight(u.id, 204.2, event="gluten", note="pizza night")
    assert '"ok": true' in out
    row = BodyWeight.query.filter_by(user_id=u.id).first()
    assert row.event == "gluten" and row.note == "pizza night"

    tomorrow = (row.log_date + timedelta(days=1)).isoformat()
    with app_.test_request_context():
        app_module._parse_coach_markers(f"[SCALE_EVENT: date={tomorrow}, kind=sodium, reason=sushi]", u.id, 1)
    db.session.expire_all()
    r2 = BodyWeight.query.filter_by(user_id=u.id, log_date=date.fromisoformat(tomorrow)).first()
    assert r2 and r2.event == "sodium" and r2.weight_lbs == 204.2  # carried forward
