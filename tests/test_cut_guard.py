"""cut_guard — the ONE shared, slope-aware gluten/water-spike detector.

Block 1's water-spike rule (3-8 lb one-week jump on a downtrend = water/
inflammation, not fat) was implemented TWICE — app._despiked_current_weight
and coach_assembler._build_cut_status — with a comment promising they'd stay
in sync. Nothing enforced that promise.

Block 3 also breaks the RAW version of the rule: at a 2.5 lb/wk expected
loss, a real 5-6 lb gluten spike over a 7-10 day gap nets out to an observed
step as low as +1.4..+3.5 (the expected loss partially cancels the spike),
which can fall below the 3 lb floor and the guard misses exactly when it's
needed most. detect_water_spike() slope-adjusts the observed step by adding
back the expected loss accrued over the gap before testing the band.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import pytest


@dataclass
class Row:
    log_date: date
    weight_lbs: float


D0 = date(2026, 6, 29)


def _rows(*day_weight_pairs):
    """day_weight_pairs: (days_ago, weight) newest-first as given."""
    return [Row(D0 - timedelta(days=d), w) for d, w in day_weight_pairs]


# ---- (a) legacy behavior at slope 0 (today's unadjusted rule) --------------------

def test_slope0_5lb_spike_on_downtrend_fires():
    from cut_guard import detect_water_spike
    rows = _rows((0, 212.0), (7, 206.0), (14, 208.0))  # down then +6 jump
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=0.0)
    assert spiked is True
    assert wt == 206.0  # anchors on the prior (de-spiked) weight


def test_slope0_2lb_step_does_not_fire():
    from cut_guard import detect_water_spike
    rows = _rows((0, 208.0), (7, 206.0), (14, 208.0))  # +2 lb, below the floor
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=0.0)
    assert spiked is False
    assert wt == 208.0


def test_slope0_9lb_step_does_not_fire_band_ceiling():
    from cut_guard import detect_water_spike
    rows = _rows((0, 215.0), (7, 206.0), (14, 208.0))  # +9 lb, above the ceiling
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=0.0)
    assert spiked is False
    assert wt == 215.0


def test_slope0_step_days_over_10_does_not_fire():
    from cut_guard import detect_water_spike
    rows = _rows((0, 212.0), (11, 206.0), (18, 208.0))  # +6 lb but 11-day gap
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=0.0)
    assert spiked is False
    assert wt == 212.0


def test_slope0_no_prior_downtrend_does_not_fire():
    from cut_guard import detect_water_spike
    rows = _rows((0, 212.0), (7, 206.0), (14, 204.0))  # prior step was UP (204->206)
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=0.0)
    assert spiked is False
    assert wt == 212.0


# ---- (b) THE attenuation case: block-3 slope unmasks a spike the old rule misses --

def test_attenuation_case_fires_with_block3_slope_but_not_at_slope0():
    from cut_guard import detect_water_spike
    # Real spike is ~5.2 lb, but a 2.5 lb/wk expected loss over a 10-day gap
    # eats most of it: observed step is only +1.6 -> below the RAW 3 lb floor.
    rows = _rows((0, 207.6), (10, 206.0), (17, 208.0))
    # Old (unpatched) rule: slope 0 -> adjusted == raw == 1.6 -> must NOT fire.
    wt0, spiked0 = detect_water_spike(rows, expected_weekly_loss=0.0)
    assert spiked0 is False
    assert wt0 == 207.6
    # Slope-adjusted: adjusted = 1.6 + 2.5*(10/7) = 5.1714... -> FIRES.
    wt, spiked = detect_water_spike(rows, expected_weekly_loss=2.5)
    assert spiked is True
    assert wt == 206.0


# ---- (c) 0/1/2-row degradation ---------------------------------------------------

def test_zero_rows_returns_none_not_spiked():
    from cut_guard import detect_water_spike
    assert detect_water_spike([]) == (None, False)


def test_one_row_returns_latest_not_spiked():
    from cut_guard import detect_water_spike
    rows = _rows((0, 200.0))
    assert detect_water_spike(rows) == (200.0, False)


def test_two_rows_returns_latest_not_spiked():
    from cut_guard import detect_water_spike
    rows = _rows((0, 200.0), (7, 195.0))  # a +5 lb jump but no 3rd row to confirm trend
    assert detect_water_spike(rows) == (200.0, False)


# ---- (d) expected_weekly_loss_for gating on the SystemFlag -----------------------

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


@pytest.fixture()
def clean_projection_flag(app_ctx):
    """Ensure the projection_mode flag doesn't leak into other test modules."""
    _, db = app_ctx
    from models import SystemFlag
    SystemFlag.query.filter_by(key="projection_mode").delete()
    db.session.commit()
    yield
    SystemFlag.query.filter_by(key="projection_mode").delete()
    db.session.commit()


def test_expected_weekly_loss_is_zero_without_flag(app_ctx, clean_projection_flag):
    from cut_guard import expected_weekly_loss_for
    assert expected_weekly_loss_for(user_id=1, week=7) == 0.0


def test_expected_weekly_loss_uses_block3_rate_when_flag_set(app_ctx, clean_projection_flag):
    _, db = app_ctx
    from models import SystemFlag
    from cut_guard import expected_weekly_loss_for
    import goal_engine
    db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
    db.session.commit()
    assert expected_weekly_loss_for(user_id=1, week=7) == goal_engine.BLOCK3_WEEKLY_RATES[7]
    assert expected_weekly_loss_for(user_id=1, week=3) == goal_engine.BLOCK3_WEEKLY_RATES[3]


def test_expected_weekly_loss_ignores_flag_with_wrong_value(app_ctx, clean_projection_flag):
    _, db = app_ctx
    from models import SystemFlag
    from cut_guard import expected_weekly_loss_for
    db.session.add(SystemFlag(key="projection_mode", value="something_else"))
    db.session.commit()
    assert expected_weekly_loss_for(user_id=1, week=7) == 0.0


# ---- (e) both call sites agree -- the MUST-match discipline enforced by code -----

def _seed_weights(db, email, series):
    from models import User, BodyWeight
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    BodyWeight.query.filter_by(user_id=u.id).delete()
    for days_ago, w in series:
        db.session.add(BodyWeight(user_id=u.id, weight_lbs=w,
                                  log_date=D0 - timedelta(days=days_ago)))
    db.session.commit()
    return u


def test_both_call_sites_agree_on_spike_verdict(app_ctx, clean_projection_flag, monkeypatch):
    app_, db = app_ctx
    from models import TrainingGoal, AppState
    from flask_login import login_user
    import app as appmod
    import coach_assembler as ca

    u = _seed_weights(db, "cutguard-agree@test.com",
                      [(21, 210.0), (14, 208.0), (7, 206.0), (0, 212.0)])
    TrainingGoal.query.filter_by(user_id=u.id).delete()
    AppState.query.filter_by(user_id=u.id).delete()
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=185.0,
                                tdee=3000, daily_calories=1500))
    db.session.add(AppState(user_id=u.id, current_week=1,
                            start_date=D0 - timedelta(days=90)))
    db.session.commit()

    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(appmod, "_user_today", lambda: D0)
        monkeypatch.setattr(ca, "_user_today", lambda: D0)
        app_wt, app_spiked = appmod._despiked_current_weight(u.id)
        cs = ca._build_cut_status()["cut_status"]

    assert app_spiked is True
    assert cs["water_spike_suspected"] == app_spiked


def test_both_call_sites_agree_on_clean_loss(app_ctx, clean_projection_flag, monkeypatch):
    app_, db = app_ctx
    from models import TrainingGoal, AppState
    from flask_login import login_user
    import app as appmod
    import coach_assembler as ca

    u = _seed_weights(db, "cutguard-agree-clean@test.com",
                      [(21, 210.0), (14, 207.0), (7, 205.0), (0, 203.0)])
    TrainingGoal.query.filter_by(user_id=u.id).delete()
    AppState.query.filter_by(user_id=u.id).delete()
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=185.0,
                                tdee=3000, daily_calories=1500))
    db.session.add(AppState(user_id=u.id, current_week=1,
                            start_date=D0 - timedelta(days=90)))
    db.session.commit()

    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(appmod, "_user_today", lambda: D0)
        monkeypatch.setattr(ca, "_user_today", lambda: D0)
        app_wt, app_spiked = appmod._despiked_current_weight(u.id)
        cs = ca._build_cut_status()["cut_status"]

    assert app_spiked is False
    assert cs["water_spike_suspected"] == app_spiked
