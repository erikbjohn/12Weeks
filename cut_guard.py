"""Shared slope-aware gluten/water-spike detector.

This used to be two independent implementations — app._despiked_current_weight
and coach_assembler._build_cut_status — each carrying a comment promising the
other would be kept "exactly" in sync. Nothing enforced that promise; it was
pure vigilance. Now there's ONE algorithm and both call sites import it, so
the two can no longer drift.

Core rule (unchanged from the original): a one-week jump of 3-8 lb against a
prior DOWN step, within <=10 days, is water/inflammation (a gluten spike),
not fat — recalibrating cut math off it would wrongly tighten the deficit on
a glutened week (the block-1 failure this guard exists to prevent).

Block 3 runs a steeper expected weekly loss (up to 2.5 lb/wk). At that slope,
a real gluten spike gets partly cancelled by the ongoing loss over the
weigh-in gap: a genuine ~5 lb spike over a 10-day gap can observe as only
+1.6 lb, which falls below the RAW 3 lb floor and the old rule would miss it.
`expected_weekly_loss` slope-adjusts the observed step by adding back the
loss we'd expect to have accrued over the gap before testing the band.
Passing 0.0 (the default) reproduces the original, unadjusted rule exactly.
"""


def detect_water_spike(rows, expected_weekly_loss=0.0):
    """rows: newest-first, objects with `.log_date` (date) and `.weight_lbs`
    (float). Only the first three rows matter (latest / prior / before) — the
    minimum needed to confirm "a jump on top of a downtrend".

    expected_weekly_loss: the slope (lb/week) the cut is expected to be
    losing at, e.g. `goal_engine.BLOCK3_WEEKLY_RATES[week]`. Used to adjust
    the observed step so an active cut's own loss doesn't mask a real spike.
    0.0 reproduces today's unadjusted behavior exactly.

    Returns (weight_to_anchor_on, spiked: bool):
      - spiked False: weight_to_anchor_on is the latest logged weight (or
        None if there are no rows at all — nothing to anchor on).
      - spiked True: weight_to_anchor_on is the PRIOR (pre-spike) weight —
        the de-spiked anchor for cut math.
    """
    if len(rows) < 3:
        return (rows[0].weight_lbs if rows else None), False

    latest, prior, before = rows[0], rows[1], rows[2]
    if prior.weight_lbs is None or before.weight_lbs is None:
        return latest.weight_lbs, False

    step = latest.weight_lbs - prior.weight_lbs
    step_days = (latest.log_date - prior.log_date).days
    prior_down = prior.weight_lbs < before.weight_lbs
    adjusted_step = step + expected_weekly_loss * (step_days / 7)

    if 3 <= adjusted_step <= 8 and prior_down and 0 < step_days <= 10:
        return prior.weight_lbs, True
    return latest.weight_lbs, False


def _flag_value(base_key, user_id):
    """SystemFlag value for `base_key`, preferring the per-user KEYED row
    (`<base_key>:<user_id>`) and falling back to the legacy GLOBAL unkeyed
    row (`base_key`) only when no keyed row exists for this user.

    I-4 (per-user block-3 flags): the legacy unkeyed rows — Erik's original
    block-3 transition flags — don't record an owner, so this fallback is
    read by EVERY user pre-migration (status quo, a brief window at first
    boot). Once app.py's one-shot startup migration renames Erik's rows to
    the keyed form, the unkeyed rows are gone: Erik's own lookup hits his
    keyed row on the first query; every OTHER user's first query (their own
    keyed row, which never existed) finds nothing, the second (legacy)
    query finds nothing either (it's gone), and they correctly see no
    block-3 state — the actual I-4 fix. See app.py's
    `_migrate_block3_flags_to_keyed` for the rename."""
    from models import SystemFlag
    if user_id is not None:
        flag = SystemFlag.query.filter_by(key=f"{base_key}:{user_id}").first()
        if flag is not None:
            return flag.value
    flag = SystemFlag.query.filter_by(key=base_key).first()
    return flag.value if flag else None


def _block3_mode(user_id):
    """True iff the block-3 piecewise curve is the live projection authority
    for `user_id` (SystemFlag key=f"projection_mode:{user_id}", value=
    "piecewise_block3", falling back to the legacy unkeyed "projection_mode"
    row pre-migration — see _flag_value). THE single flag lookup — app.py
    and coach_assembler.py both import this (never re-implement the query)
    so the two surfaces can't drift on what "block 3 mode" means, the same
    discipline detect_water_spike enforces for the spike rule itself."""
    return _flag_value("projection_mode", user_id) == "piecewise_block3"


def _block3_anchor_and_start(user_id):
    """(anchor_weight, start_date) for rebuilding the block-3 curve, or
    (None, None)/partial-None when either half is missing.

    anchor_weight comes from the keyed-with-fallback SystemFlag value for
    "block3_anchor" (see _flag_value) — written once by the block-3
    transition alongside the projection_mode flag, rather than re-derived
    from TrainingGoal.weight_projection[0] every call. start_date is
    AppState.start_date for user_id (always per-user; SystemFlag rows are
    what used to be global before the I-4 keying fix)."""
    from models import AppState
    anchor = None
    value = _flag_value("block3_anchor", user_id)
    if value:
        try:
            anchor = float(value)
        except (TypeError, ValueError):
            anchor = None
    state = AppState.query.filter_by(user_id=user_id).first()
    start = state.start_date if state and state.start_date else None
    return anchor, start


def expected_weekly_loss_for(user_id, week):
    """The slope-adjustment rate to feed into detect_water_spike, gated
    behind `_block3_mode(user_id)` (per-user, keyed-with-fallback — see
    _flag_value). Returns 0.0 — reproducing today's unadjusted behavior
    exactly — whenever block-3 mode isn't on for this user, so this is a
    no-op everywhere until that flag flips on for them.
    """
    if not _block3_mode(user_id):
        return 0.0
    import goal_engine
    return goal_engine.BLOCK3_WEEKLY_RATES.get(week, 0.0)


def despiked_weight_for_week(user_id, week):
    """(weight_to_anchor_on, spiked: bool) for `user_id` — the SAME
    block-scoped (>= AppState.start_date), newest-first-limit-3 query
    app._despiked_current_weight and coach_assembler._build_cut_status
    already run, reused here so weekly_report's block-3 judgment (I-3)
    can't drift from either badge's despike verdict. `week` feeds
    expected_weekly_loss_for's slope adjustment — callers pass the specific
    program week being judged (e.g. a weekly report's own week_num), not
    necessarily "today's" week."""
    from models import BodyWeight, AppState
    state = AppState.query.filter_by(user_id=user_id).first()
    block_start = state.start_date if state and state.start_date else None
    q = (BodyWeight.query.filter_by(user_id=user_id)
         .filter(BodyWeight.weight_lbs.isnot(None)))
    if block_start is not None:
        q = q.filter(BodyWeight.log_date >= block_start)
    rows = q.order_by(BodyWeight.log_date.desc(), BodyWeight.id.desc()).limit(3).all()
    expected_loss = expected_weekly_loss_for(user_id, week)
    return detect_water_spike(rows, expected_loss)
