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


def _block3_mode():
    """True iff the block-3 piecewise curve is the live projection authority
    (SystemFlag key="projection_mode", value="piecewise_block3"). THE single
    flag lookup — app.py and coach_assembler.py both import this (never
    re-implement the query) so the two surfaces can't drift on what "block 3
    mode" means, the same discipline detect_water_spike enforces for the
    spike rule itself."""
    from models import SystemFlag
    flag = SystemFlag.query.filter_by(key="projection_mode").first()
    return bool(flag and flag.value == "piecewise_block3")


def _block3_anchor_and_start(user_id):
    """(anchor_weight, start_date) for rebuilding the block-3 curve, or
    (None, None)/partial-None when either half is missing.

    anchor_weight comes from SystemFlag(key="block3_anchor", value=<float
    as str>) — written once by the block-3 transition (Task 15) alongside
    the projection_mode flag, rather than re-derived from
    TrainingGoal.weight_projection[0] every call. start_date is
    AppState.start_date for user_id (per-user; SystemFlag is global)."""
    from models import SystemFlag, AppState
    flag = SystemFlag.query.filter_by(key="block3_anchor").first()
    anchor = None
    if flag and flag.value:
        try:
            anchor = float(flag.value)
        except (TypeError, ValueError):
            anchor = None
    state = AppState.query.filter_by(user_id=user_id).first()
    start = state.start_date if state and state.start_date else None
    return anchor, start


def expected_weekly_loss_for(user_id, week):
    """The slope-adjustment rate to feed into detect_water_spike, gated
    behind the `projection_mode` SystemFlag (set once block 3's piecewise
    curve goes live). Returns 0.0 — reproducing today's unadjusted behavior
    exactly — whenever the flag isn't set to "piecewise_block3", so this is
    a no-op everywhere until that flag flips on.

    user_id is accepted for a future per-user rollout but the flag is
    currently global; it is not yet used to scope the lookup.
    """
    if not _block3_mode():
        return 0.0
    import goal_engine
    return goal_engine.BLOCK3_WEEKLY_RATES.get(week, 0.0)
