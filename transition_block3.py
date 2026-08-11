"""Block 2 -> Block 3 transactional transition and its ordered rollback.

WHY this exists (see docs/superpowers/specs/2026-08-10-peptide-protocol-
integration-design.md section 6 for the full narrative): the naive "same
playbook as last time" — an unscoped `week += 12` — is unsafe now. Block-1
history already occupies weeks 13-24 (re-stamped 2026-06-29), so shifting
block-2 by the same +12 collides with it: unique-constrained tables
(set_log, run_log, day_completion, weekly_checkin, ...) abort mid-UPDATE,
while unconstrained plan tables silently MERGE two blocks' rows with no way
to tell them apart afterward — and the unscoped rollback becomes
unexecutable (it would also drag block-1 into weeks 1-12). A reviewer
proved this. Every ordering rule below exists to prevent that corruption:

  - Block-1 shifts BEFORE block-2 (oldest first) so the two ranges are
    always disjoint from each other and from their targets — no in-flight
    collision is possible even within one bulk UPDATE statement.
  - Today (2026-08-10) is simultaneously block-2 week-7 day-0 AND block-3
    week-1 day-0: today's already-logged rows are RE-HOMED (moved) onto
    week 1, never archived to a phantom "week 19".
  - Rollback un-re-homes FIRST, then parks (never deletes) any real block-3
    training, then deletes only regenerable plan rows, then un-shifts
    newest-first. Reordering any of these steps corrupts data — see each
    function's docstring for the specific collision it prevents.

Both `run_transition` and `run_rollback` operate on the CALLER's db.session
and never call commit()/rollback() themselves — the Flask endpoint wraps
the whole call in one transaction: any raised exception propagates up,
the endpoint rolls back, and zero partial state survives (spec's "any
mismatch -> SQL ROLLBACK").
"""
import json
from datetime import date, datetime, timezone

from models import (
    db,
    # The 21-model shifted-table list (spec section 6).
    SessionAnalysis, ExerciseLog, SetLog, ExerciseSwap, ExerciseCompletion,
    WarmupCompletion, RunLog, DayCompletion, ProgressPhoto, WeeklyCheckIn,
    GarminActivity, GarminWorkoutLink, WeeklyReport, WeeklyScheduleOverride,
    MealPlanOverride, RunOverride, WeeklyPrescription, WeeklyMealPlan,
    WeeklyRunPlan, WeeklyWarmup, WeeklyDaySchedule,
    # Other tables this module reads/writes.
    TrainingGoal, AppState, BodyWeight, SystemFlag,
    PeptideDose, PeptideVial, LabReminder,
)
import goal_engine


# ── The 21-model table list (literal, per spec §6) ─────────────────────────
SHIFTED_TABLES = [
    SessionAnalysis, ExerciseLog, SetLog, ExerciseSwap, ExerciseCompletion,
    WarmupCompletion, RunLog, DayCompletion, ProgressPhoto, WeeklyCheckIn,
    GarminActivity, GarminWorkoutLink, WeeklyReport, WeeklyScheduleOverride,
    MealPlanOverride, RunOverride, WeeklyPrescription, WeeklyMealPlan,
    WeeklyRunPlan, WeeklyWarmup, WeeklyDaySchedule,
]

# LOG-TABLES: real user history. NEVER deleted at rollback — only shifted
# forward, or restored/parked backward.
LOG_TABLES = [
    SetLog, RunLog, DayCompletion, ExerciseCompletion, WarmupCompletion,
    GarminWorkoutLink, GarminActivity, ProgressPhoto, SessionAnalysis,
    ExerciseLog, WeeklyCheckIn, WeeklyReport, ExerciseSwap,
]

# PLAN-TABLES: coach-generated programming. Regenerable (via replan-week /
# meal-gen / run-gen), so rollback deletes week<=12 rows outright.
PLAN_TABLES = [
    WeeklyPrescription, WeeklyMealPlan, WeeklyRunPlan, WeeklyWarmup,
    WeeklyDaySchedule, WeeklyScheduleOverride, MealPlanOverride, RunOverride,
]

assert set(LOG_TABLES) | set(PLAN_TABLES) == set(SHIFTED_TABLES), \
    "LOG_TABLES + PLAN_TABLES must exactly partition SHIFTED_TABLES"
assert not (set(LOG_TABLES) & set(PLAN_TABLES)), \
    "LOG_TABLES and PLAN_TABLES must not overlap"

# Reliable Date-typed column per LOG_TABLES model, used by rollback to tell
# "today's re-homed block-2 rows" (date == TRANSITION_DATE) apart from
# genuine new block-3 training (date > TRANSITION_DATE). Tables absent from
# this map have no trustworthy date column:
#   - ExerciseSwap / ExerciseCompletion / WarmupCompletion have no date
#     column at all.
#   - DayCompletion.completed_at is a nullable free-text audit stamp ("when
#     this was marked done"), not a queryable Date, and is None for any row
#     that was never completed — unreliable as a discriminator. Matched on
#     week/day_idx alone instead (the "else all w1d0 rows" fallback the
#     spec allows for date-less tables).
_LOG_DATE_FIELD = {
    SessionAnalysis: "log_date",
    ExerciseLog: "logged_date",
    SetLog: "logged_date",
    RunLog: "log_date",
    ProgressPhoto: "log_date",
    WeeklyCheckIn: "check_in_date",
    GarminActivity: "activity_date",
    GarminWorkoutLink: "scheduled_date",
    WeeklyReport: "report_date",
}

# Week-bearing models deliberately excluded from SHIFTED_TABLES:
#   - CoachMemory: never shifted, carries across blocks.
#   - BodyweightRetest: keyed on week_number (not week), historical
#     display-only retest data.
#   - AppState: has current_week (not week), restored by its own step.
_EXCLUDED_WEEK_MODELS = {"CoachMemory", "BodyweightRetest", "AppState"}

TRANSITION_DATE = date(2026, 8, 10)
BLOCK3_TARGET_WEIGHT = 195.0
LAB_BASELINE_LABEL = "Baseline labs: T/E2, IGF-1, fasting glucose/A1c, lipids"
LAB_WEEK8_LABEL = "Week-8 labs: T/E2, IGF-1, fasting glucose/A1c, lipids"
LAB_WEEK8_DUE = date(2026, 9, 28)
PROTOCOL_ROLLBACK_END = date(2026, 11, 1)

_GOAL_SNAPSHOT_FIELDS = [
    "goal_type", "target_weight", "weight_projection", "phase_plan",
    "daily_calories", "protein_grams", "carb_grams", "fat_grams", "tdee",
]


def assert_table_census():
    """Schema-drift guard: models.py's week-bearing models (any model with a
    column literally named `week`), minus the 3 explicitly-excluded ones,
    must equal SHIFTED_TABLES exactly. Catches the case where a new
    week-bearing table gets added to models.py later and nobody remembers
    to add it to this spec-frozen list — silently excluding it from a
    future transition would corrupt/orphan its data."""
    found = set()
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        if cls.__name__ in _EXCLUDED_WEEK_MODELS:
            continue
        if "week" in mapper.columns:
            found.add(cls)
    expected = set(SHIFTED_TABLES)
    if found != expected:
        missing = sorted(m.__name__ for m in (expected - found))
        extra = sorted(m.__name__ for m in (found - expected))
        raise AssertionError(
            "SHIFTED_TABLES has drifted from models.py's week-bearing "
            f"models: missing={missing} extra={extra}"
        )


# ── Histogram helpers ────────────────────────────────────────────────────

def _histogram(model, user_id):
    """{'week_counts': [{'week', 'count'}, ...] sorted by week (None last),
    'min', 'max', 'total'} for one table/user — the rollback-data snapshot
    the spec calls for (raw counts alone can't detect a shift; per-week
    counts can)."""
    rows = (
        db.session.query(model.week, db.func.count())
        .filter(model.user_id == user_id)
        .group_by(model.week)
        .all()
    )
    weeks_present = [w for w, _c in rows if w is not None]
    week_counts = sorted(
        ({"week": w, "count": c} for w, c in rows),
        key=lambda wc: (wc["week"] is None, wc["week"]),
    )
    return {
        "week_counts": week_counts,
        "min": min(weeks_present) if weeks_present else None,
        "max": max(weeks_present) if weeks_present else None,
        "total": sum(c for _w, c in rows),
    }


def _all_histograms(user_id):
    return {model.__name__: _histogram(model, user_id) for model in SHIFTED_TABLES}


def _range_sum(histogram, lo, hi):
    return sum(
        wc["count"] for wc in histogram["week_counts"]
        if wc["week"] is not None and lo <= wc["week"] <= hi
    )


def _destination_conflicts(histograms):
    """Non-empty dict of {table_name: row_count} for every shifted table
    that already has rows in the block-1 destination range (25-36) —
    the precondition the earlier, unsafe playbook skipped."""
    conflicts = {}
    for name, hist in histograms.items():
        n = _range_sum(hist, 25, 36)
        if n:
            conflicts[name] = n
    return conflicts


def _week7_day_purity_conflicts(user_id):
    """Non-empty dict of {table_name: row_count} for every day_idx-bearing
    shifted table that has week==7 rows OUTSIDE day 0 (day_idx NOT NULL
    and != 0).

    The re-home step collapses EVERY week-7 row onto week=1, day_idx=0 —
    that's correct ONLY if week 7's sole occupant is today (day 0; the
    week just started). A stray week-7 non-zero-day row would otherwise
    get force-merged into day 0 by re-home: for unique-constrained tables
    that raises an IntegrityError mid-transaction (safe — the whole
    transaction rolls back — but an ugly, avoidable 500); for
    UNCONSTRAINED tables (SessionAnalysis, ExerciseLog, ExerciseSwap) it
    SILENTLY MERGES two different days' data into one row with a 200 —
    real data corruption that then survives rollback (rollback restores
    counts, not which row's data ended up where). Checking this before any
    write makes the collision structurally unreachable rather than merely
    caught eventually."""
    conflicts = {}
    for model in SHIFTED_TABLES:
        if not hasattr(model, "day_idx"):
            continue
        n = (
            model.query
            .filter(
                model.user_id == user_id,
                model.week == 7,
                model.day_idx.isnot(None),
                model.day_idx != 0,
            )
            .count()
        )
        if n:
            conflicts[model.__name__] = n
    return conflicts


def _snapshot_goal(goal):
    return {f: getattr(goal, f) for f in _GOAL_SNAPSHOT_FIELDS}


def _snapshot_appstate(state):
    if not state:
        return {"start_date": None, "current_week": None}
    return {
        "start_date": state.start_date.isoformat() if state.start_date else None,
        "current_week": state.current_week,
    }


def _upsert_flag(key, value):
    flag = SystemFlag.query.filter_by(key=key).first()
    if flag:
        flag.value = value
    else:
        db.session.add(SystemFlag(key=key, value=value))


def _verify_post_shift(pre_histograms, post_histograms):
    """Inside-the-transaction verification (spec §6 step 2e): block-1 fully
    landed at 25-36, block-2 fully landed at 13-18, weeks 2-12 are empty
    (week 1 may hold re-homed rows). Any mismatch raises -> caller's
    exception handler rolls back the whole transaction."""
    problems = []
    for model in SHIFTED_TABLES:
        name = model.__name__
        pre = pre_histograms[name]
        post = post_histograms[name]
        expected_block1 = _range_sum(pre, 13, 24)
        expected_block2 = _range_sum(pre, 1, 6)
        actual_block1 = _range_sum(post, 25, 36)
        actual_block2 = _range_sum(post, 13, 18)
        mid_empty = _range_sum(post, 2, 12)
        stray_7 = _range_sum(post, 7, 7)
        stray_19 = _range_sum(post, 19, 19)
        if (actual_block1 != expected_block1 or actual_block2 != expected_block2
                or mid_empty or stray_7 or stray_19):
            problems.append(
                f"{name}: block1 expected={expected_block1} actual={actual_block1}; "
                f"block2 expected={expected_block2} actual={actual_block2}; "
                f"weeks2-12={mid_empty} week7={stray_7} week19={stray_19}"
            )
    if problems:
        raise RuntimeError("post-shift verification failed: " + "; ".join(problems))


def _verify_rollback_restored(pre_histograms, post_histograms):
    """Every week that had count C before the transition must have count C
    again after rollback (extra weeks — e.g. parked block-3 rows at
    week>=100 — are expected and NOT part of this check).

    ONE deliberate carve-out: PLAN_TABLES at week==7. That row is the
    in-flight, not-yet-complete current week's programming — it went
    through the SAME re-home as log rows (week 7 -> week 1, day_idx 0) but,
    unlike log tables, plan tables are never un-re-homed at rollback (step
    1 only walks LOG_TABLES) and get deleted outright by step 3's blanket
    "delete plan-table rows week<=12". That's intentional (spec: plan rows
    are regenerable — the runbook's own next step re-plans week 1 via
    /api/admin/replan-week); it is NOT a data-loss bug like losing a log
    row would be, so it must not fail this guard. Every other week for
    plan tables (their completed-week history at 1-6/13-24) IS restored by
    the newest-first un-shift and is still checked here."""
    problems = []
    for model in SHIFTED_TABLES:
        name = model.__name__
        pre = pre_histograms[name]
        post = post_histograms[name]
        post_by_week = {wc["week"]: wc["count"] for wc in post["week_counts"]}
        is_plan = model in PLAN_TABLES
        for wc in pre["week_counts"]:
            week, expected = wc["week"], wc["count"]
            if is_plan and week == 7:
                continue
            actual = post_by_week.get(week, 0)
            if actual != expected:
                problems.append(f"{name} week={week}: expected={expected} actual={actual}")
    if problems:
        raise RuntimeError("rollback verification failed: " + "; ".join(problems))


# ── Forward transition ───────────────────────────────────────────────────

def run_transition(user, anchor_weight, dry_run=False):
    """Executes the full block-2 -> block-3 transition for `user`. Returns
    (status_code, body_dict). Never calls db.session.commit()/rollback() —
    the caller owns the transaction. dry_run=True performs every read-only
    validation but writes nothing (not even the block3_prestate flag)."""
    assert_table_census()

    if SystemFlag.query.filter_by(key="block3_prestate").first():
        return 409, {"error": "already transitioned — block3_prestate flag exists"}

    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not goal or goal.goal_type != "cut":
        return 409, {"error": "user has no active cut goal"}

    histograms = _all_histograms(user.id)
    conflicts = _destination_conflicts(histograms)
    if conflicts:
        return 409, {
            "error": "destination weeks 25-36 are not empty in every shifted table",
            "detail": conflicts,
        }

    week7_conflicts = _week7_day_purity_conflicts(user.id)
    if week7_conflicts:
        return 409, {
            "error": "week-7 rows exist beyond day 0 — resolve before transitioning",
            "detail": week7_conflicts,
        }

    if dry_run:
        would_shift = {
            name: {
                "block1_to_shift": _range_sum(h, 13, 24),
                "block2_to_shift": _range_sum(h, 1, 6),
                "to_rehome": _range_sum(h, 7, 7),
            }
            for name, h in histograms.items()
        }
        return 200, {"dry_run": True, "histograms": histograms, "would_shift": would_shift}

    state = AppState.query.filter_by(user_id=user.id).first()
    prestate = {
        "histograms": histograms,
        "goal": _snapshot_goal(goal),
        "app_state": _snapshot_appstate(state),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    db.session.add(SystemFlag(key="block3_prestate", value=json.dumps(prestate)))

    shifted = {}

    # (c) Block-1 shift FIRST — oldest first. Source (13-24) and target
    # (25-36) are disjoint and the target was just verified empty, so this
    # single bulk UPDATE cannot collide with itself or any other row.
    for model in SHIFTED_TABLES:
        expected = _range_sum(histograms[model.__name__], 13, 24)
        n = (
            model.query
            .filter(model.user_id == user.id, model.week.between(13, 24))
            .update({model.week: model.week + 12}, synchronize_session=False)
        )
        if n != expected:
            raise RuntimeError(
                f"block-1 shift rowcount mismatch on {model.__name__}: "
                f"expected {expected}, updated {n}"
            )
        shifted.setdefault(model.__name__, {})["block1"] = n

    # (d) Block-2 shift. 13-24 is now vacant (step above just emptied it),
    # so 1-6 -> 13-18 cannot collide with anything either.
    for model in SHIFTED_TABLES:
        expected = _range_sum(histograms[model.__name__], 1, 6)
        n = (
            model.query
            .filter(model.user_id == user.id, model.week.between(1, 6))
            .update({model.week: model.week + 12}, synchronize_session=False)
        )
        if n != expected:
            raise RuntimeError(
                f"block-2 shift rowcount mismatch on {model.__name__}: "
                f"expected {expected}, updated {n}"
            )
        shifted.setdefault(model.__name__, {})["block2"] = n

    # (e) Re-home today's already-logged week-7 rows onto block-3's day 0
    # (today is simultaneously block-2 week-7 day-0 and block-3 week-1
    # day-0 — this is a MOVE, never an archive to a phantom week 19).
    # Scoped to day_idx IN (0, NULL) — belt over the _week7_day_purity_
    # conflicts pre-flight assert above: even if that guard were ever
    # bypassed, this filter alone still can't merge a non-zero day into
    # day 0 (it just leaves the stray row at week 7, caught by the
    # post-shift verification's "week7 must be empty" check instead of
    # silently corrupting data).
    rehomed_total = 0
    for model in SHIFTED_TABLES:
        values = {model.week: 1}
        conds = [model.user_id == user.id, model.week == 7]
        if hasattr(model, "day_idx"):
            values[model.day_idx] = 0
            conds.append(db.or_(model.day_idx == 0, model.day_idx.is_(None)))
        n = (
            model.query
            .filter(*conds)
            .update(values, synchronize_session=False)
        )
        rehomed_total += n
        shifted.setdefault(model.__name__, {})["rehomed"] = n

    # (f) AppState reset.
    if not state:
        state = AppState(user_id=user.id)
        db.session.add(state)
    state.start_date = TRANSITION_DATE
    state.current_week = 1

    # (g) TrainingGoal: stays "cut", new target + canonical curve.
    goal.target_weight = BLOCK3_TARGET_WEIGHT
    goal.weight_projection = goal_engine.build_block3_projection(anchor_weight, TRANSITION_DATE)

    # (h) SystemFlags — same transaction as everything above (Task-13
    # handoff: both flags must land together or anchor-dependent consumers
    # break while projection_mode still reports piecewise_block3).
    _upsert_flag("projection_mode", "piecewise_block3")
    _upsert_flag("block3_anchor", str(anchor_weight))

    # (i) Day-0 BodyWeight, only if none exists yet for today.
    existing_bw = BodyWeight.query.filter_by(user_id=user.id, log_date=TRANSITION_DATE).first()
    if not existing_bw:
        db.session.add(BodyWeight(user_id=user.id, log_date=TRANSITION_DATE, weight_lbs=anchor_weight))

    # (j) LabReminders.
    db.session.add(LabReminder(user_id=user.id, label=LAB_BASELINE_LABEL, due_date=TRANSITION_DATE))
    db.session.add(LabReminder(user_id=user.id, label=LAB_WEEK8_LABEL, due_date=LAB_WEEK8_DUE))

    db.session.flush()

    # (k) Post-shift verification INSIDE the transaction — any mismatch
    # raises, the endpoint's except block rolls back everything above.
    post_histograms = _all_histograms(user.id)
    _verify_post_shift(histograms, post_histograms)

    return 200, {
        "ok": True,
        "shifted": shifted,
        "rehomed": rehomed_total,
        "flags_set": ["projection_mode", "block3_anchor"],
        "labs_created": 2,
    }


# ── Rollback (ORDER IS LOAD-BEARING) ─────────────────────────────────────

def run_rollback(user):
    """Ordered inverse of run_transition. Returns (status_code, body_dict).
    Never calls db.session.commit()/rollback() — the caller owns the
    transaction."""
    assert_table_census()

    prestate_flag = SystemFlag.query.filter_by(key="block3_prestate").first()
    if not prestate_flag:
        return 409, {"error": "no block3_prestate snapshot — nothing to roll back"}
    prestate = json.loads(prestate_flag.value)
    pre_histograms = prestate["histograms"]

    # (1) UN-RE-HOME FIRST. Must precede parking — if parking ran first,
    # these rows would already sit at week>=101 and this week==1/day_idx==0
    # selector would match nothing, stranding real training in the parked
    # range.
    restored = {}
    restored_total = 0
    for model in LOG_TABLES:
        conds = [model.user_id == user.id, model.week == 1]
        if hasattr(model, "day_idx"):
            conds.append(model.day_idx == 0)
        date_field = _LOG_DATE_FIELD.get(model)
        if date_field:
            conds.append(getattr(model, date_field) == TRANSITION_DATE)
        values = {model.week: 7}
        if hasattr(model, "day_idx"):
            values[model.day_idx] = 0
        n = model.query.filter(*conds).update(values, synchronize_session=False)
        restored[model.__name__] = n
        restored_total += n

    # (2) PARK (never delete) real block-3 training. The date predicate
    # (or, for date-less tables, the explicit week != 7 exclusion) is what
    # keeps this from re-catching the rows step (1) just restored to
    # week 7 (7 <= 12, so a bare "week<=12" filter would otherwise match
    # them again).
    parked = {}
    parked_total = 0
    for model in LOG_TABLES:
        date_field = _LOG_DATE_FIELD.get(model)
        if date_field:
            conds = [
                model.user_id == user.id,
                model.week <= 12,
                getattr(model, date_field) > TRANSITION_DATE,
            ]
        else:
            conds = [model.user_id == user.id, model.week <= 12, model.week != 7]
        n = model.query.filter(*conds).update({model.week: model.week + 100}, synchronize_session=False)
        parked[model.__name__] = n
        parked_total += n

    # (3) Delete regenerable block-3 rows in the plan tables only. Log
    # tables are NEVER in a delete statement — anything real in them was
    # either restored in (1) or parked in (2).
    for model in PLAN_TABLES:
        model.query.filter(model.user_id == user.id, model.week <= 12).delete(synchronize_session=False)

    # (4) Newest-first un-shift, same 21 tables.
    for model in SHIFTED_TABLES:
        model.query.filter(
            model.user_id == user.id, model.week.between(13, 18)
        ).update({model.week: model.week - 12}, synchronize_session=False)
    for model in SHIFTED_TABLES:
        model.query.filter(
            model.user_id == user.id, model.week.between(25, 36)
        ).update({model.week: model.week - 12}, synchronize_session=False)

    db.session.flush()
    post_histograms = _all_histograms(user.id)
    _verify_rollback_restored(pre_histograms, post_histograms)

    # (5) Restore AppState + TrainingGoal from the prestate snapshot; clear
    # flags. AppState alone is not enough — the 195 target + curve live in
    # TrainingGoal, and restoring only AppState leaves a false 220->195
    # line drawn over block-2 data.
    appstate_snap = prestate["app_state"]
    state = AppState.query.filter_by(user_id=user.id).first()
    if not state:
        state = AppState(user_id=user.id)
        db.session.add(state)
    state.start_date = date.fromisoformat(appstate_snap["start_date"]) if appstate_snap["start_date"] else None
    state.current_week = appstate_snap["current_week"]

    goal_snap = prestate["goal"]
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not goal:
        goal = TrainingGoal(user_id=user.id, goal_type=goal_snap["goal_type"])
        db.session.add(goal)
    for field, value in goal_snap.items():
        setattr(goal, field, value)

    for key in ("projection_mode", "block3_anchor", "block3_prestate"):
        SystemFlag.query.filter_by(key=key).delete(synchronize_session=False)

    # (6) Delete imported protocol rows, scoped to the transition window.
    PeptideDose.query.filter(
        PeptideDose.user_id == user.id,
        PeptideDose.date >= TRANSITION_DATE,
        PeptideDose.date <= PROTOCOL_ROLLBACK_END,
    ).delete(synchronize_session=False)
    # PeptideVial has no per-row date to scope against (a vial spans a
    # reconstitution window, not a single day) — but it's safe to delete
    # ALL of the user's vials unconditionally because PeptideVial exists
    # ONLY for this protocol: there is no other writer anywhere in the app
    # that could have created a PeptideVial row pre-dating this transition
    # for this user to accidentally destroy.
    PeptideVial.query.filter(PeptideVial.user_id == user.id).delete(synchronize_session=False)
    LabReminder.query.filter(
        LabReminder.user_id == user.id,
        LabReminder.due_date >= TRANSITION_DATE,
    ).delete(synchronize_session=False)

    return 200, {
        "ok": True,
        "restored": restored_total,
        "restored_detail": restored,
        "parked": parked_total,
        "parked_detail": parked,
    }
