"""Aerobic-base gate: with a low trailing run volume, NO hard sessions survive
generation — every threshold/interval/tempo day is deterministically converted
to an easy Z2 run of bounded duration. The prompt advises; the rail enforces.

Trigger: trailing-14-day RunLog volume < 120 min/week average. (Erik 2026-08:
~70 min/wk of ~10-min daily runs; the planner prescribed 4x4 @ HR165 off that
base — this rail exists so it can't happen again.)
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_low_base_converts_hard_days_to_z2():
    from coach_planning_runs import enforce_run_base
    out = {
        0: {"type": "z2", "label": "Zone 2 Easy", "duration": "40 min",
            "detail": "5 min warmup; 30 min steady; 5 min cooldown"},
        1: {"type": "threshold", "label": "Threshold 4x4", "duration": "34 min",
            "detail": "10 min warmup; 4x4 min hard @ HR <=165 / 3 min easy; 7 min cooldown"},
        2: {"type": "interval", "label": "VO2 Intervals", "duration": "45 min",
            "detail": "hard stuff"},
    }
    gated = enforce_run_base(out, weekly_minutes=70.0)
    assert gated[0]["type"] == "z2"                      # easy day untouched
    assert gated[0]["detail"].startswith("5 min warmup")
    for d in (1, 2):
        assert gated[d]["type"] == "z2"
        assert "hard" not in gated[d]["detail"].lower()
        assert "base" in gated[d]["detail"].lower()      # honest why
    # bounded duration: converted days never exceed 40 min
    assert int(gated[1]["duration"].split()[0]) <= 40
    assert int(gated[2]["duration"].split()[0]) <= 40


def test_adequate_base_leaves_plan_alone():
    from coach_planning_runs import enforce_run_base
    out = {1: {"type": "threshold", "label": "Threshold", "duration": "34 min",
               "detail": "10 min warmup; 4x4 min hard; 7 min cooldown"}}
    gated = enforce_run_base(out, weekly_minutes=200.0)
    assert gated[1]["type"] == "threshold"
    assert gated[1]["detail"] == out[1]["detail"]


def test_weekly_run_minutes_reads_trailing_14d(app_ctx):
    app_, db = app_ctx
    from models import User, RunLog
    from coach_planning_runs import weekly_run_minutes
    u = User.query.filter_by(email="runbase@test.com").first()
    if not u:
        u = User(email="runbase@test.com")
        db.session.add(u)
        db.session.commit()
    RunLog.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    assert weekly_run_minutes(u.id) == 0.0
    today = date.today()
    for i in range(14):  # 10 min every day for 14 days = 70 min/week
        db.session.add(RunLog(user_id=u.id, log_date=today - timedelta(days=i),
                              week=90 + i // 7, day_idx=i % 7, duration_min=10,
                              distance_miles=1.0))
    db.session.commit()
    assert weekly_run_minutes(u.id) == pytest.approx(70.0)
