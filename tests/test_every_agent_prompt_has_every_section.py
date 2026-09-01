"""S007/S008: served-prompt contract. Every athlete-facing agent's ASSEMBLED
prompt carries every core section's sentinel when the data exists, a failed
builder is announced as UNAVAILABLE (never silent absence), and both chat
endpoints codify markers."""
import pathlib
import re
from datetime import date, datetime, timezone
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


SENTINELS = {
    "cut_status": "<cut_status>",
    "protocol_status": "<protocol_status>",
    "today_status": "<today_status>",
    "garmin": "Garmin today",
    "bodyweight": "213",           # today's weigh-in must be quoted somewhere
    "week_schedule": "FULL WEEK",
}


def _seed(app_, db):
    import models as m
    u = m.User(email="contract@test.com", password_hash="x"); db.session.add(u); db.session.commit()
    today = date.today()
    monday = today.fromordinal(today.toordinal() - today.weekday())
    db.session.add(m.AppState(user_id=u.id, start_date=monday))
    db.session.add(m.TrainingGoal(user_id=u.id, goal_type="cut", target_weight=195.0, daily_calories=2000,
                                  protein_grams=200, plan_accepted=True))
    db.session.add(m.BodyWeight(user_id=u.id, weight_lbs=213.0, log_date=today))
    db.session.add(m.GarminWellness(user_id=u.id, date=today, sleep_score=70, hrv_last_night=55, body_battery=60))
    db.session.add(m.PeptideDose(user_id=u.id, date=today, time="07:00", event_type="Injection",
                                 compound="BPC-157", dose_mg=0.5, syringe_units="20u"))
    di = today.weekday()
    db.session.add(m.WeeklyPrescription(user_id=u.id, week=1, day_idx=di, exercise_order=0,
                                        exercise_name="Barbell Bench Press", sets=3, reps="8", rest="90s",
                                        target_weight=135, source="coach"))
    db.session.add(m.WeeklyRunPlan(user_id=u.id, week=1, day_idx=di, run_type="z2", label="Zone 2 Easy",
                                   duration="40 min", detail="40 min steady @ HR ≤132", source="coach"))
    db.session.commit()
    return u


def test_every_athlete_facing_agent_gets_every_section(app_ctx):
    app_, db = app_ctx
    from coach_agents import AGENTS, SPECIALIST_AGENTS
    import coach_assembler as ca
    from flask_login import login_user
    u = _seed(app_, db)
    for name in AGENTS:
        if name in SPECIALIST_AGENTS:
            continue
        with app_.test_request_context():
            login_user(u, force=True)
            ctx = ca.build_filtered_context(name)
            assert not ctx.get("_section_errors"), (name, ctx.get("_section_errors"))
            prompt = ca.assemble_prompt(name, ctx)
        for sec, sentinel in SENTINELS.items():
            assert sentinel in prompt, f"agent {name!r} is blind to {sec} ({sentinel!r} missing)"


def test_failed_builder_is_announced_not_silent(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    from models import User
    u = User.query.filter_by(email="contract@test.com").first()
    def boom(): raise RuntimeError("db hiccup")
    monkeypatch.setitem(ca._SECTION_BUILDERS, "cut_status", boom)
    with app_.test_request_context():
        login_user(u, force=True)
        ctx = ca.build_filtered_context("conversation")
        prompt = ca.assemble_prompt("conversation", ctx)
    assert "<section_errors>" in prompt and "cut_status" in prompt.split("<section_errors>")[1]


def test_both_chat_endpoints_codify_markers():
    """S007: the source must call _parse_coach_markers in api_chat AND the
    stream generator — one call site was how markers went advisory."""
    src = pathlib.Path("app.py").read_text()
    def body(fn):
        i = src.index(f"def {fn}(")
        j = src.find("\n@app.route", i)
        return src[i:j]
    assert "_parse_coach_markers(" in body("api_chat")
    assert "_parse_coach_markers(" in body("api_chat_stream")
