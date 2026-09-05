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


def test_admin_reanchor_upserts_preseeded_rates_flag(app_ctx, monkeypatch):
    """A per-user rates flag seeded BEFORE the re-anchor (to pin the accrued
    weeks to an older table) must be replaced, not collide on the unique key
    (this 500'd in prod on 2026-09-05)."""
    app_, db = app_ctx
    from models import User, AppState, TrainingGoal, BodyWeight, SystemFlag
    from goal_engine import build_block3_projection, user_rates
    import json as _json
    key = "reanchor-key-long-enough-for-the-guard-02"
    monkeypatch.setenv("ADMIN_API_KEY", key)
    u = User(email="reanchor2@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    start = date.today() - timedelta(days=26)
    old = {1: 1.25, 2: 1.25, 3: 2.0, 4: 2.0, 5: 2.0, 6: 2.0, 7: 2.5, 8: 2.5, 9: 2.5, 10: 2.5, 11: 2.5, 12: 2.0}
    db.session.add(AppState(user_id=u.id, start_date=start))
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=BLOCK3_TARGET_LB,
                                weight_projection=build_block3_projection(220.0, start, old)))
    db.session.add(SystemFlag(key=f"projection_mode:{u.id}", value="piecewise_block3"))
    db.session.add(SystemFlag(key=f"block3_anchor:{u.id}", value="220.0"))
    db.session.add(SystemFlag(key=f"block3_rates:{u.id}", value=_json.dumps({str(k): v for k, v in old.items()})))
    for k in range(3):
        db.session.add(BodyWeight(user_id=u.id, log_date=date.today() - timedelta(days=k), weight_lbs=198.2))
    db.session.commit()
    c = app_.test_client()
    before = list(TrainingGoal.query.filter_by(user_id=u.id).first().weight_projection)
    r = c.post("/api/admin/block3-reanchor", json={"email": "reanchor2@test.com"}, headers={"X-Admin-Key": key})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert abs(body["curve_end"] - BLOCK3_TARGET_LB) < 0.1
    assert body["curve_today"] == pytest.approx(198.2)        # the curve passes through today's weight
    rates = user_rates(u.id)
    assert all(rates[w] == old[w] for w in (1, 2, 3))      # accrued weeks pinned
    assert rates[8] < old[8]                                # remaining weeks rescaled (athlete is ahead)
    assert SystemFlag.query.filter_by(key=f"block3_rates:{u.id}").count() == 1
    # HISTORY IS NEVER REWRITTEN (2026-09-05 regression): the anchor stays
    # 220 and the stored plan for the weeks already lived is byte-identical.
    assert SystemFlag.query.filter_by(key=f"block3_anchor:{u.id}").first().value == "220.0"
    after = TrainingGoal.query.filter_by(user_id=u.id).first().weight_projection
    assert after[:3] == before[:3] == [{"week": 1, "projected": 218.75}, {"week": 2, "projected": 217.5},
                                       {"week": 3, "projected": 215.5}]
    assert after[-1]["projected"] == BLOCK3_TARGET_LB
    # every reader sees the same curve: today == 198.2, day 84 == target, pre-re-anchor day == old plan
    assert curve_value(220.0, start, date.today(), rates) == pytest.approx(198.2)
    assert curve_value(220.0, start, start + timedelta(days=84), rates) == pytest.approx(BLOCK3_TARGET_LB, abs=1e-3)
    assert curve_value(220.0, start, start + timedelta(days=14), rates) == pytest.approx(217.5)
