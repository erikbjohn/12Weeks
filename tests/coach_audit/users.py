"""Synthetic user fixtures + real-Erik fixture.

Every fixture returns a freshly-seeded `User` row. Test DB is sqlite under
`/tmp` (set by `tests/conftest.py`).
"""
from __future__ import annotations
import itertools
from datetime import date, timedelta


_SEQ = itertools.count(1)


def _next_email(prefix: str) -> str:
    return f"{prefix}-{next(_SEQ)}@audit.local"


def make_phase_2_mid_program():
    """Week 6, gym, full barbell access, 5 weeks of progressive SetLog history,
    currently cutting (-0.5 lb/wk trend over 4 BodyWeight rows)."""
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState,
        SetLog, BodyWeight, TrainingGoal,
    )

    u = User(email=_next_email("p2"), password_hash="x")
    db.session.add(u); db.session.commit()

    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=[
            "barbell", "dumbbells", "lat_pulldown", "cable_machine",
            "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
            "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
            "dip_station", "ab_machine", "smith_machine",
        ],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=35),
        current_week=6,
    ))
    db.session.add(TrainingGoal(
        user_id=u.id,
        goal_type="cut",
        target_weight=180.0,
        daily_calories=2200,
    ))
    db.session.commit()

    # 5 weeks x 3 lifts x 4 sets of progressive SetLog = 60 rows
    progression = {
        "Barbell Front Squat": [(135, 5), (145, 5), (155, 4), (165, 3), (170, 3)],
        "Barbell Bench Press": [(135, 6), (145, 5), (150, 5), (155, 4), (160, 4)],
        "Barbell Row":          [(115, 8), (125, 8), (135, 8), (140, 8), (145, 7)],
    }
    LIFT_DAY = {
        "Barbell Front Squat": 0,
        "Barbell Bench Press": 1,
        "Barbell Row":         3,
    }
    base_logged = date.today() - timedelta(days=34)
    for week in range(1, 6):
        days_offset = (week - 1) * 7
        for lift, sets in progression.items():
            weight, reps = sets[week - 1]
            day_idx = LIFT_DAY[lift]
            log_date = base_logged + timedelta(days=days_offset + day_idx)
            for set_no in range(1, 5):
                db.session.add(SetLog(
                    user_id=u.id,
                    week=week,
                    day_idx=day_idx,
                    exercise_name=lift,
                    set_number=set_no,
                    weight=weight,
                    reps=reps,
                    done=True,
                    logged_date=log_date,
                ))

    # 4 weeks of body weight, gentle cut
    for d_back, lbs in [(28, 188.0), (21, 187.4), (14, 186.5), (7, 186.0)]:
        db.session.add(BodyWeight(
            user_id=u.id,
            log_date=date.today() - timedelta(days=d_back),
            weight_lbs=lbs,
        ))

    db.session.commit()
    return u
