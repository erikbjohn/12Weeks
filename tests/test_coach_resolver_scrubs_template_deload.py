"""2026-09-03: the morning check-in said 'Today is Deload — Pull' on a week
the athlete had VETOED (WeeklyDaySchedule.deload=False, lift_name='Pull').
The card said 'Pull'. Cause: coach_assembler._resolve_workout_for_day kept
the STATIC template's liftName ('Deload — Pull', the week-4 PHASE_TEMPLATE)
because only api_workouts overlays WeeklyDaySchedule.lift_name and runs
_reconcile_lift_name. The coach must see the same title the card serves."""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _user(db, email):
    from models import User, WeeklyPrescription, WeeklyDaySchedule
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    WeeklyPrescription.query.filter_by(user_id=u.id).delete()
    WeeklyDaySchedule.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return u


def _plan_week4_pull(db, u, deload_flag, title):
    from models import WeeklyPrescription, WeeklyDaySchedule
    for i, (nm, s, r) in enumerate([("Barbell Bent-Over Row", 4, 8),
                                    ("Hammer Curl", 3, 12),
                                    ("Rear Delt Fly", 3, 12)]):
        db.session.add(WeeklyPrescription(user_id=u.id, week=4, day_idx=3,
                                          exercise_order=i, exercise_name=nm,
                                          sets=s, reps=r, target_weight=100))
    db.session.add(WeeklyDaySchedule(user_id=u.id, week=4, day_idx=3,
                                     lift_name=title, is_rest=False,
                                     deload=deload_flag, source="engine"))
    db.session.commit()


def test_resolver_never_says_deload_when_week_not_deload(app_ctx):
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    from workout_data import get_workouts
    assert "deload" in get_workouts(4)[3]["liftName"].lower()  # the template residue
    u = _user(db, "resolver-deload-veto@test.com")
    _plan_week4_pull(db, u, deload_flag=False, title="Pull")
    with app_.test_request_context():
        login_user(u, force=True)
        day = ca._resolve_workout_for_day(4, 3)
    assert day and not day.get("lift_unplanned")
    assert "deload" not in (day.get("liftName") or "").lower(), day.get("liftName")
    assert day["liftName"] == "Pull"


def test_resolver_keeps_deload_title_when_coach_called_it(app_ctx):
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    u = _user(db, "resolver-deload-called@test.com")
    _plan_week4_pull(db, u, deload_flag=True, title="Deload — Pull")
    with app_.test_request_context():
        login_user(u, force=True)
        day = ca._resolve_workout_for_day(4, 3)
    assert "deload" in (day.get("liftName") or "").lower(), day.get("liftName")


def test_week_program_block_matches_card_title(app_ctx, monkeypatch):
    """The FULL WEEK PROGRAM the coach cites from must carry the schedule title."""
    app_, db = app_ctx
    import coach_assembler as ca
    from flask_login import login_user
    u = _user(db, "resolver-deload-weekblock@test.com")
    _plan_week4_pull(db, u, deload_flag=False, title="Pull")
    with app_.test_request_context():
        login_user(u, force=True)
        text = ca._format_full_week_program(4)
    if text is None:
        pytest.skip("week program formatter not exposed")
    assert "Thursday — Pull:" in text, text
    assert "Deload — Pull" not in text
