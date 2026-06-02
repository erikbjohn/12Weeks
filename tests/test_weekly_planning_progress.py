"""The weekly-planning walkthrough must go ONE day at a time and never lock the
week on the first 'yes'. assemble_prompt injects a computed progress directive
(_weekly_planning_progress) that tells the model exactly which day to show and
forbids early lock. These tests pin the deterministic counting.
"""
import pytest


@pytest.fixture(scope="module")
def ctx():
    from app import app, db
    from models import User
    with app.app_context():
        db.create_all()
        u = User.query.filter_by(email="wpp@test.com").first()
        if not u:
            u = User(email="wpp@test.com", name="WPP", role="user", email_verified=True)
            db.session.add(u); db.session.commit()
        uid = u.id
    return app, uid


def _run(app, uid, messages):
    from app import db
    from models import ChatMessage
    from flask_login import login_user
    from coach_assembler import _weekly_planning_progress
    with app.app_context():
        ChatMessage.query.filter_by(user_id=uid).delete()
        for c in messages:
            db.session.add(ChatMessage(user_id=uid, role="assistant", content=c))
        db.session.commit()
        u = db.session.get(__import__("models").User, uid)
        with app.test_request_context():
            login_user(u)
            return _weekly_planning_progress()


def test_first_yes_shows_monday_never_locks(ctx):
    app, uid = ctx
    d = _run(app, uid, ["Week 10 overview. Ready to see Monday?"])
    assert "Monday" in d
    # the whole point: on the first 'yes' it must forbid locking the whole week
    assert "NEVER lock or summarize the whole week" in d
    assert "week locked" in d  # appears inside a "Do NOT say 'week locked'" instruction
    # must NOT instruct to summarize/lock yet
    assert "give a 2-3 sentence week summary and" not in d


def test_after_monday_shown_advances_to_tuesday(ctx):
    app, uid = ctx
    d = _run(app, uid, [
        "Week 10 overview. Ready to see Monday?",
        "[SHOW_NEXT_DAY]\nMonday — Front Squat. Anything to swap?",
    ])
    assert "Tuesday" in d


def test_after_all_six_shown_allows_lock(ctx):
    app, uid = ctx
    msgs = ["Week 10 overview. Ready to see Monday?"]
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
        msgs.append(f"[SHOW_NEXT_DAY]\n{day} — stuff. Anything else?")
    d = _run(app, uid, msgs)
    assert "summary and" in d.lower() and "lock it" in d.lower()
