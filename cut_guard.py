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


def expected_weekly_loss_for(user_id, week):
    """The slope-adjustment rate to feed into detect_water_spike, gated
    behind the `projection_mode` SystemFlag (set once block 3's piecewise
    curve goes live). Returns 0.0 — reproducing today's unadjusted behavior
    exactly — whenever the flag isn't set to "piecewise_block3", so this is
    a no-op everywhere until that flag flips on.

    user_id is accepted for a future per-user rollout but the flag is
    currently global; it is not yet used to scope the lookup.
    """
    from models import SystemFlag
    flag = SystemFlag.query.filter_by(key="projection_mode").first()
    if not flag or flag.value != "piecewise_block3":
        return 0.0
    import goal_engine
    return goal_engine.BLOCK3_WEEKLY_RATES.get(week, 0.0)
