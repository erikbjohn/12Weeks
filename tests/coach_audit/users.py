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
    # Names match production canonical (workout_data.py): no "Barbell" prefix
    # on Front Squat; Phase 2 bench is DB; rows are "Barbell Bent-Over Row".
    _seed_progressive_setlog(
        user_id=u.id,
        progression={
            "Front Squat":           [(135, 5), (145, 5), (155, 4), (165, 3), (170, 3)],
            "DB Bench Press":        [(60, 6),  (65, 5),  (70, 5),  (72, 4),  (75, 4)],
            "Barbell Bent-Over Row": [(115, 8), (125, 8), (135, 8), (140, 8), (145, 7)],
        },
        lift_day={
            "Front Squat":           0,
            "DB Bench Press":        1,
            "Barbell Bent-Over Row": 3,
        },
    )

    _seed_bodyweight_trend(
        u.id,
        [(28, 188.0), (21, 187.4), (14, 186.5), (7, 186.0)],
    )

    db.session.commit()
    return u


def make_phase_1_newbie():
    """Week 2, gym, just-onboarded — no SetLog history yet so the coach
    must lean on `lifting_agent` for starting weights instead of
    extrapolating from non-existent data."""
    from app import db
    from models import User, UserEquipment, PhysicalAssessment, AppState

    u = User(email=_next_email("p1"), password_hash="x")
    db.session.add(u)
    db.session.commit()

    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=["barbell", "dumbbells", "flat_bench", "pull_up_bar"],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=7),
        current_week=2,
    ))
    db.session.commit()
    return u


def make_phase_3_cut():
    """Week 9, gym, bench plateau (3 weeks all at 165 lb), ahead on
    weight-loss target. Coach should propose deload or accessory shift,
    not push for a PR."""
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState, TrainingGoal,
    )

    u = User(email=_next_email("p3"), password_hash="x")
    db.session.add(u)
    db.session.commit()

    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=[
            "barbell", "dumbbells", "flat_bench", "pull_up_bar",
            "lat_pulldown", "cable_machine",
        ],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=56),
        current_week=9,
    ))
    db.session.add(TrainingGoal(
        user_id=u.id, goal_type="cut", target_weight=175.0, daily_calories=2000,
    ))

    # Plateau pattern — 3 weeks of bench at 165, all the same.
    # Phase 3 still uses DB Bench Press as the canonical Tuesday lift name.
    _seed_progressive_setlog(
        user_id=u.id,
        progression={"DB Bench Press": [(165, 4), (165, 4), (165, 4)]},
        lift_day={"DB Bench Press": 1},
    )

    # Weight ahead of target (181 lb with target 175 — 6 lb to go in 4 weeks).
    _seed_bodyweight_trend(
        u.id,
        [(28, 188.0), (21, 185.0), (14, 183.0), (7, 181.0)],
    )

    db.session.commit()
    return u


def make_no_gym_bw():
    """Week 3, no gym — bodyweight + kettlebells + pull-up bar only.
    Coach must NOT prescribe barbell lifts."""
    from app import db
    from models import User, UserEquipment, PhysicalAssessment, AppState

    u = User(email=_next_email("bw"), password_hash="x")
    db.session.add(u)
    db.session.commit()

    db.session.add(UserEquipment(
        user_id=u.id,
        available_equipment=["kettlebells", "pull_up_bar"],
    ))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=False))
    db.session.add(AppState(
        user_id=u.id,
        start_date=date.today() - timedelta(days=14),
        current_week=3,
    ))
    db.session.commit()
    return u


def make_real_erik():
    """Pull Erik's current state from production via /api/admin/debug/sql,
    mirror into the local test DB. Read-only against prod — writes only to
    the test sqlite DB."""
    import os
    import requests
    from app import db
    from models import (
        User, UserEquipment, PhysicalAssessment, AppState,
        WeeklyRunPlan, SetLog,
    )

    api_key = os.environ.get("ADMIN_API_KEY")
    if not api_key:
        raise RuntimeError("ADMIN_API_KEY not set — cannot mirror real Erik state.")
    base = os.environ.get("PLACEMETRY_PROD_URL", "https://12weeks-app.onrender.com")

    def q(sql: str) -> list[dict]:
        r = requests.post(
            f"{base}/api/admin/debug/sql",
            headers={"X-Admin-Key": api_key, "Content-Type": "application/json"},
            json={"sql": sql},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("rows") or []

    # 1) Resolve Erik's user_id via email
    user_rows = q("SELECT id, email FROM \"user\" WHERE email = 'erik@placemetry.com' LIMIT 1")
    if not user_rows:
        raise RuntimeError("real Erik not found in prod by email")
    src_id = user_rows[0]["id"]

    # 2) Mirror — local copies get fresh PKs
    u = User(email=_next_email("erik"), password_hash="x")
    db.session.add(u)
    db.session.commit()
    new_id = u.id

    # AppState
    rows = q(f"SELECT current_week, start_date FROM app_state WHERE user_id = {src_id}")
    if rows:
        r = rows[0]
        sd = r["start_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd[:10])
        db.session.add(AppState(user_id=new_id, current_week=r["current_week"], start_date=sd))

    # UserEquipment
    rows = q(f"SELECT available_equipment FROM user_equipment WHERE user_id = {src_id}")
    if rows:
        eq = rows[0]["available_equipment"] or []
        db.session.add(UserEquipment(user_id=new_id, available_equipment=eq))

    # PhysicalAssessment
    rows = q(f"SELECT has_gym FROM physical_assessment WHERE user_id = {src_id}")
    if rows:
        db.session.add(PhysicalAssessment(user_id=new_id, has_gym=bool(rows[0]["has_gym"])))

    # SetLog (last 60 days)
    rows = q(f"""
        SELECT week, day_idx, exercise_name, set_number, weight, reps, done, logged_date
        FROM set_log
        WHERE user_id = {src_id} AND logged_date > current_date - 60
        ORDER BY logged_date DESC LIMIT 500
    """)
    for r in rows:
        ld = r["logged_date"]
        if isinstance(ld, str):
            ld = date.fromisoformat(ld[:10])
        db.session.add(SetLog(
            user_id=new_id,
            week=r["week"], day_idx=r["day_idx"],
            exercise_name=r["exercise_name"],
            set_number=r["set_number"],
            weight=r["weight"], reps=r["reps"],
            done=bool(r["done"]),
            logged_date=ld,
        ))

    # WeeklyRunPlan (current week's plan)
    rows = q(f"""
        SELECT week, day_idx, run_type, label, duration, detail, source
        FROM weekly_run_plan WHERE user_id = {src_id}
    """)
    for r in rows:
        db.session.add(WeeklyRunPlan(
            user_id=new_id,
            week=r["week"], day_idx=r["day_idx"],
            run_type=r["run_type"], label=r["label"],
            duration=r["duration"], detail=r["detail"], source=r["source"],
        ))

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
