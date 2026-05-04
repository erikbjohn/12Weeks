"""Synthetic user fixtures + real-Erik fixture.

Every fixture returns a freshly-seeded `User` row. Test DB is sqlite under
`/tmp` (set by `tests/conftest.py`). Each archetype factory composes a few
small `_seed_*` helpers so fixture authors can mix and match (e.g. a future
plateau archetype shares the same SetLog-seeding logic with a different
progression dict).
"""
from __future__ import annotations
import itertools
from datetime import date, timedelta


_SEQ = itertools.count(1)

SETS_PER_LIFT = 4


def _next_email(prefix: str) -> str:
    return f"{prefix}-{next(_SEQ)}@audit.local"


def _seed_progressive_setlog(
    user_id: int,
    progression: dict[str, list[tuple[float, int]]],
    lift_day: dict[str, int],
    sets_per_lift: int = SETS_PER_LIFT,
) -> None:
    """Seed SetLog rows from a per-lift progression.

    progression: {lift_name: [(weight, reps), ...]} — one tuple per week.
    lift_day:    {lift_name: day_idx}                — weekday index for each lift.
    """
    from app import db
    from models import SetLog
    weeks = max(len(s) for s in progression.values())
    base_logged = date.today() - timedelta(days=(weeks * 7) - 1)
    for week in range(1, weeks + 1):
        days_offset = (week - 1) * 7
        for lift, sets in progression.items():
            weight, reps = sets[week - 1]
            day_idx = lift_day[lift]
            log_date = base_logged + timedelta(days=days_offset + day_idx)
            for set_no in range(1, sets_per_lift + 1):
                db.session.add(SetLog(
                    user_id=user_id,
                    week=week,
                    day_idx=day_idx,
                    exercise_name=lift,
                    set_number=set_no,
                    weight=weight,
                    reps=reps,
                    done=True,
                    logged_date=log_date,
                ))


def _seed_bodyweight_trend(user_id: int, weights: list[tuple[int, float]]) -> None:
    """Seed BodyWeight rows. `weights` is a list of (days_back, lbs) tuples."""
    from app import db
    from models import BodyWeight
    for d_back, lbs in weights:
        db.session.add(BodyWeight(
            user_id=user_id,
            log_date=date.today() - timedelta(days=d_back),
            weight_lbs=lbs,
        ))


def make_phase_2_mid_program():
    """Week 6, gym, full barbell access, 5 weeks of progressive SetLog history,
    currently cutting (-0.5 lb/wk trend over 4 BodyWeight rows)."""
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState, TrainingGoal,
    )

    # First commit materializes user.id so subsequent FKs resolve.
    u = User(email=_next_email("p2"), password_hash="x")
    db.session.add(u)
    db.session.commit()

    # AppState is keyed by user_id — never read via .first(); always filter.
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

    # 5 weeks × 3 lifts × SETS_PER_LIFT = 60 progressive SetLog rows.
    _seed_progressive_setlog(
        user_id=u.id,
        progression={
            "Barbell Front Squat": [(135, 5), (145, 5), (155, 4), (165, 3), (170, 3)],
            "Barbell Bench Press": [(135, 6), (145, 5), (150, 5), (155, 4), (160, 4)],
            "Barbell Row":          [(115, 8), (125, 8), (135, 8), (140, 8), (145, 7)],
        },
        lift_day={
            "Barbell Front Squat": 0,
            "Barbell Bench Press": 1,
            "Barbell Row":         3,
        },
    )

    _seed_bodyweight_trend(
        u.id,
        [(28, 188.0), (21, 187.4), (14, 186.5), (7, 186.0)],
    )

    db.session.commit()
    return u


ARCHETYPE_DESCRIPTIONS: dict[str, str] = {
    "phase_2_mid_program": (
        "Week 6 of a 12-week program. Phase 2 (weeks 5-8). "
        "Monday: Lower POWER — Front Squat 4x3 (heavy, low rep). "
        "Tuesday: Upper PRESS — DB Bench Press, with secondary work. "
        "Wednesday: Shoulder Volume + tempo run. "
        "Thursday: Upper PULL — Weighted Pull-Up + Barbell Row. "
        "Friday: HEAVY Lower — Back Squat 4x5. "
        "Saturday: Full Body, lighter. Sunday: Long fasted run, rest from lifting. "
        "Currently cutting at ~-0.5 lb/week. Has full gym access."
    ),
    "phase_1_newbie": (
        "Week 2. Just onboarded — minimal SetLog history. Phase 1 (weeks 1-4) "
        "establishes movement competency at moderate weights. Coach must use the "
        "lifting_agent to set starting weights, NOT extrapolate from non-existent history."
    ),
    "phase_3_cut": (
        "Week 9. Phase 3 (weeks 9-12). Hit a progression plateau on bench press "
        "(stuck at 165 for 3+ weeks). Ahead on weight-loss target. Coach should "
        "address plateau with deload or accessory shift, not push for PR."
    ),
    "no_gym_bw": (
        "Week 3. No gym, bodyweight + kettlebells only. Coach MUST NOT prescribe "
        "barbell lifts. Programming is push-up / pull-up progressions, "
        "kettlebell goblet squats, KB swings, single-leg work."
    ),
    "real_erik": (
        "Live athlete. Pull current state from production. Whatever the program "
        "says is ground truth — coach should cite from `get_workout` tool results "
        "and the full-week block in athlete_data."
    ),
}
