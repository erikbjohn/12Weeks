"""C3 + C4 — the coach actively runs the cut, and the gluten/water guard.

Block 1's central failure: the coach never coached the cut — the weigh-in was an
inert DB row, cut_status reached only the conversation/nutritionist agents, and a
glutening (water) read as fat and would have deepened the deficit.

C3: cut_status now reaches the daily moments (morning_checkin, meals_complete),
and carries a RECENT trailing slope + trend_reversal so a late reversal isn't
masked by the overall pace.
C4: a 3-8 lb one-week jump on a downtrend is flagged water_spike_suspected; the
recalibration anchors on the DE-SPIKED weight so a glutened week can't tighten
the deficit; the meals prompt holds.
"""
from datetime import date, timedelta

import pytest


# ---- C3 wiring (pure) ------------------------------------------------------------

def test_daily_agents_now_see_the_cut():
    from coach_agents import AGENTS
    assert "cut_status" in AGENTS["morning_checkin"]["requires"]
    assert "goal" in AGENTS["morning_checkin"]["requires"]
    assert "cut_status" in AGENTS["meals_complete"]["requires"]


# ---- C4 de-spike helper (DB) -----------------------------------------------------

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _seed_weights(db, email, series):
    """series: list of (days_ago, weight) — inserts BodyWeight rows."""
    from models import User, BodyWeight
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    BodyWeight.query.filter_by(user_id=u.id).delete()
    today = date(2026, 6, 29)
    for days_ago, w in series:
        db.session.add(BodyWeight(user_id=u.id, weight_lbs=w,
                                  log_date=today - timedelta(days=days_ago)))
    db.session.commit()
    return u


def test_despike_anchors_on_prior_weight_on_acute_spike(app_ctx):
    app_, db = app_ctx
    from app import _despiked_current_weight
    # descending ... then a +6 lb jump on the latest weigh-in = water spike.
    u = _seed_weights(db, "despike-spike@test.com",
                      [(21, 210.0), (14, 208.0), (7, 206.0), (0, 212.0)])
    wt, spiked = _despiked_current_weight(u.id)
    assert spiked is True
    assert wt == 206.0  # the prior (de-spiked) weight, NOT 212


def test_despike_passes_through_clean_loss(app_ctx):
    app_, db = app_ctx
    from app import _despiked_current_weight
    u = _seed_weights(db, "despike-clean@test.com",
                      [(21, 210.0), (14, 207.0), (7, 205.0), (0, 203.0)])
    wt, spiked = _despiked_current_weight(u.id)
    assert spiked is False
    assert wt == 203.0  # latest, losing cleanly


def test_despike_ignores_real_regain_above_window(app_ctx):
    app_, db = app_ctx
    from app import _despiked_current_weight
    # a +12 lb jump is outside the 3-8 water window -> treated as real, not water.
    u = _seed_weights(db, "despike-bigjump@test.com",
                      [(14, 208.0), (7, 206.0), (0, 218.0)])
    wt, spiked = _despiked_current_weight(u.id)
    assert spiked is False
    assert wt == 218.0


# ---- C3/C4 cut_status signal (DB + login) ----------------------------------------

def test_cut_status_scopes_to_current_block(app_ctx, monkeypatch):
    """B3 regression: cut pace/current must come from THIS block only. Block-1
    weigh-ins (the 226 start) must not leak into block 2's pace — that produced
    the day-1 dashboard/coach contradiction the adversarial pass caught."""
    app_, db = app_ctx
    import coach_assembler as ca
    from models import TrainingGoal, AppState
    from flask_login import login_user
    today = date(2026, 6, 29)
    # two block-1 weigh-ins (old, heavy) + two block-2 weigh-ins (recent, lighter)
    u = _seed_weights(db, "cutscope@test.com",
                      [(90, 226.0), (84, 220.0), (7, 208.0), (0, 206.0)])
    TrainingGoal.query.filter_by(user_id=u.id).delete()
    AppState.query.filter_by(user_id=u.id).delete()
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=185.0,
                                tdee=3000, daily_calories=1500))
    db.session.add(AppState(user_id=u.id, current_week=1,
                            start_date=today - timedelta(days=7)))  # block 2 starts day -7
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        monkeypatch.setattr(ca, "_current_week", lambda: 1)
        cs = ca._build_cut_status()["cut_status"]
        assert cs["current_weight"] == 206.0
        # pace reflects 208 -> 206 over the block (losing), NOT 226 -> 206
        assert cs["pace_per_week"] is not None and cs["pace_per_week"] < 0
        # 226/220 are out of block -> projection can't be inflated by them
        assert cs["projected_week_12_weight"] is None or cs["projected_week_12_weight"] < 210


def test_morning_checkin_prompt_surfaces_the_cut(app_ctx):
    """End-to-end (no LLM): the assembled morning_checkin system prompt must
    contain the cut signal AND the rule-21 directive to run the cut. In block 1
    this section never reached this agent, so the coach never coached the cut."""
    app_, db = app_ctx
    from coach_assembler import assemble_prompt
    from flask_login import login_user
    u = _seed_weights(db, "cut-prompt@test.com", [(7, 206.0), (0, 212.0)])
    ctx = {
        "athlete_name": "Erik",
        "cut_status": {
            "current_weight": 212.0, "target_weight": 185.0,
            "pace_per_week": -1.5, "recent_pace": 2.4,
            "trend_reversal": True, "water_spike_suspected": True,
            "latest_note": "glutened at dinner",
        },
    }
    with app_.test_request_context():
        login_user(u, force=True)
        prompt = assemble_prompt("morning_checkin", ctx)
    assert "<cut_status>" in prompt
    assert "WATER_SPIKE_SUSPECTED" in prompt
    assert "RUN THE CUT" in prompt           # CORE_PROMPT rule 21
    assert "GLUTEN" in prompt.upper()


def test_cut_status_flags_reversal_and_water_spike(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import TrainingGoal
    from flask_login import login_user
    u = _seed_weights(db, "cutstatus@test.com",
                      # losing overall, then an acute +6 spike on a down step
                      [(56, 226.0), (35, 214.0), (21, 210.0), (14, 208.0),
                       (7, 206.0), (0, 212.0)])
    TrainingGoal.query.filter_by(user_id=u.id).delete()
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", target_weight=185.0,
                                tdee=3000, daily_calories=1500))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_user_today", lambda: date(2026, 6, 29))
        monkeypatch.setattr(ca, "_current_week", lambda: 1)
        cs = ca._build_cut_status()["cut_status"]
        assert cs is not None
        assert cs["recent_pace"] is not None and cs["recent_pace"] > 0  # recently gaining
        assert cs["trend_reversal"] is True                            # overall down, recent up
        assert cs["water_spike_suspected"] is True                     # acute 3-8 lb on a down step
