"""S074: endpoint-preserving re-anchor — past kept, remaining rates rescaled
so the curve still lands on BLOCK3_TARGET_LB (185.0) at day 84; per-user rates flow to every
pace judgment; exactly once."""
from datetime import date, timedelta
import pytest
from goal_engine import reanchor_block3, curve_value, BLOCK3_WEEKLY_RATES, BLOCK3_TARGET_LB


def test_reanchor_lands_on_target_at_day_84():
    start = date(2026, 8, 10)
    on = start + timedelta(days=21)   # Monday of week 4
    # athlete is 4 lb behind the original curve on that morning
    behind = curve_value(220.0, start, on) + 4.0
    new_rates = reanchor_block3(behind, on, start)
    # weeks 1-3 untouched
    assert all(new_rates[w] == BLOCK3_WEEKLY_RATES[w] for w in (1, 2, 3))
    # from `on`, the rescaled remaining schedule removes exactly (behind - target)
    remaining = sum(new_rates[min(12, d // 7 + 1)] / 7.0 for d in range(21, 84))
    assert abs(behind - remaining - BLOCK3_TARGET_LB) < 0.01
    # steeper than before
    assert new_rates[6] > BLOCK3_WEEKLY_RATES[6]


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_admin_reanchor_is_one_shot_and_changes_verdicts(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import User, AppState, TrainingGoal, BodyWeight, SystemFlag
    from goal_engine import build_block3_projection, user_rates
    key = "reanchor-key-long-enough-for-the-guard-01"
    monkeypatch.setenv("ADMIN_API_KEY", key)
    u = User(email="reanchor@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    start = date.today() - timedelta(days=21)
    db.session.add(AppState(user_id=u.id, start_date=start))
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=BLOCK3_TARGET_LB,
                                weight_projection=build_block3_projection(220.0, start)))
    db.session.add(SystemFlag(key=f"projection_mode:{u.id}", value="piecewise_block3"))
    db.session.add(SystemFlag(key=f"block3_anchor:{u.id}", value="220.0"))
    # 4 lb behind today (and the two days before, so no spike inference)
    for k in range(3):
        d = date.today() - timedelta(days=k)
        db.session.add(BodyWeight(user_id=u.id, log_date=d, weight_lbs=round(curve_value(220.0, start, d) + 4.0, 1)))
    db.session.commit()
    c = app_.test_client()
    r = c.post("/api/admin/block3-reanchor", json={"email": "reanchor@test.com", "dry_run": True},
               headers={"X-Admin-Key": key})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert abs(r.get_json()["curve_end"] - BLOCK3_TARGET_LB) < 0.1
    r = c.post("/api/admin/block3-reanchor", json={"email": "reanchor@test.com"}, headers={"X-Admin-Key": key})
    assert r.status_code == 200
    assert user_rates(u.id) != BLOCK3_WEEKLY_RATES
    r = c.post("/api/admin/block3-reanchor", json={"email": "reanchor@test.com"}, headers={"X-Admin-Key": key})
    assert r.status_code == 409  # exactly once
