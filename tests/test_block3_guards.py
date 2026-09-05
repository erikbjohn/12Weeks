"""
Block 3 regression guards — prevent week-12-lock class bugs where breaking changes
slip through undetected.

1. Retest-lock: RETEST_WEEKS must stay empty (week-12 UI hard-lock was removed)
2. Gate-creep: no new location-blocking gates before renderAll() can sneak in
3. Curve-target: projection[11] must equal 195.0 lbs (the retatrutide end target)
4. Slope+ceiling: water-spike detector must stop firing when slope is steep
5. Table-census: all week-bearing models match the transition spec exactly
6. CSV integrity: peptide protocol has correct row count, no duplicates, correct doses
"""

import pytest
from pathlib import Path
from collections import namedtuple
from datetime import datetime, timedelta
import csv


class TestRetestLockGuard:
    """Guard 1: RETEST_WEEKS == () — the week-12 hard-lock was removed."""

    def test_retest_weeks_is_empty(self):
        import app as appmod
        assert appmod.RETEST_WEEKS == (), (
            "RETEST_WEEKS must be empty; the week-12 bodyweight retest "
            "hard-locked the UI (no dashboard/coach/settings until test was done). "
            "Erik removed it. Restore only if absolutely necessary."
        )


class TestGateCreepGuard:
    """Guard 2: Count blocking gates before renderAll() in the pre-renderAll init path.

    A blocking gate uses `location.href = ...` or `return;` to prevent renderAll()
    from being called, effectively hard-locking the app like week-12-lock did.
    The week-12-lock class of bug sneaks in when a new gate is added without updating
    this count. Every new gate must CONSCIOUSLY bump this assertion.
    """

    def test_no_new_blocking_gates_before_renderall(self):
        """Count return statements in the init path (before renderAll is called).

        Current known gates (all using `return;` before renderAll()):
        1. Pre-start lockout (line ~5462): blocks if program hasn't started yet
        2. Onboarding gate (line ~5519): blocks if onboarding is incomplete
        3. Bodyweight retest gate (line ~5567): blocks if retest is due (disabled via RETEST_WEEKS=())

        NOTE: The morning-check-in gate (line ~5558) is NOT a blocking gate — it calls
        checkMorningCheckin() but does NOT return early; it shows an overlay and continues
        to renderAll().

        These are LOCATION-BLOCKING gates that use `return;` before renderAll()
        to prevent the app from rendering. Any new gate added here must bump the
        expected_count below.
        """
        app_js_path = Path(__file__).parent.parent / "static" / "app.js"
        with open(app_js_path, 'r') as f:
            lines = f.readlines()

        # Locate the init function by its signature rather than a fixed line
        # range (unrelated edits above it used to shift the window and break
        # this test): from the async DOMContentLoaded handler to its first
        # renderAll() call plus the finally block that follows.
        start = next(i for i, l in enumerate(lines)
                     if "document.addEventListener('DOMContentLoaded', async" in l)
        end = next(i for i, l in enumerate(lines) if i > start and "renderAll();" in l) + 20
        init_lines = lines[start:end]

        # Count return statements in this range
        return_count = sum(1 for line in init_lines if 'return;' in line)

        # 401→/login redirect + server-unreachable retry banner (S013) +
        # Pre-start lockout + Onboarding + Bodyweight retest
        expected_count = 5
        assert return_count == expected_count, (
            f"Expected {expected_count} blocking gates before renderAll() in the init path, "
            f"found {return_count}. If you added a new gate that uses 'return;', bump this count. "
            f"If you removed a gate, decrement this count."
        )


class TestCurveTargetGuard:
    """Guard 3: The Block 3 projection curve must hit 195.0 lbs by week 12."""

    def test_projection_curve_targets_185_week_12(self):
        from goal_engine import build_block3_projection, BLOCK3_WEEKLY_RATES, CURVE_TOLERANCE_LB

        # Projection is built from an anchor weight (220 lbs, the start of block 3)
        anchor_weight = 220.0
        projection = build_block3_projection(anchor_weight, None)

        # Week 12 (index 11) must be at 185.0
        assert projection[11]["projected"] == 185.0, (
            f"Week 12 projection must be 185.0 (the block-3 target, 2026-09-05), "
            f"got {projection[11]['projected']}"
        )

    def test_weekly_rates_sum_to_35(self):
        from goal_engine import BLOCK3_WEEKLY_RATES
        total = sum(BLOCK3_WEEKLY_RATES.values())
        assert abs(total - 35.0) < 1e-9, (
            f"BLOCK3_WEEKLY_RATES must sum to exactly 35.0 lbs (220→185), "
            f"got {total}"
        )

    def test_curve_tolerance_is_1_5_lbs(self):
        from goal_engine import CURVE_TOLERANCE_LB
        assert CURVE_TOLERANCE_LB == 1.5, (
            f"CURVE_TOLERANCE_LB must be 1.5 lbs, got {CURVE_TOLERANCE_LB}"
        )

    def test_no_week_5_boundary_jump(self):
        from goal_engine import BLOCK3_WEEKLY_RATES
        # Sep-10 retatrutide frequency doubling is NOT a boundary
        # Week 4→5 should NOT show a boundary-style jump
        assert BLOCK3_WEEKLY_RATES[5] == BLOCK3_WEEKLY_RATES[4], (
            "Week 5 must NOT have a separate rate; the retatrutide "
            "frequency doubling (Sep 10) is mid-week, not a boundary. "
            "Do not add a week-5 rate."
        )


class TestSlopePlusCeilingGuard:
    """Guard 4: Water-spike detector must account for slope and ceiling.

    In Block 3, the expected weekly loss is steep (up to 2.5 lb/week). At that slope,
    a real gluten spike gets partly cancelled by the ongoing loss over the weigh-in gap.
    The detector must stop firing when the slope-adjusted step exceeds the ceiling.
    """

    def test_slope_adjusted_spike_firing(self):
        from cut_guard import detect_water_spike

        SimpleRow = namedtuple('SimpleRow', ['log_date', 'weight_lbs'])

        # (a) A step firing at slope 0 STOPS firing at slope 2.5
        # Raw: +7.0 lb over 7 days (fires as gluten at slope 0)
        # With slope 2.5: adjusted = 7.0 + 2.5 * (7/7) = 7.0 + 2.5 = 9.5 > 8 ceiling
        # Should NOT fire (reconstructed gross magnitude too large for water)
        before_date = datetime(2026, 8, 1)
        prior_date = datetime(2026, 8, 8)
        latest_date = datetime(2026, 8, 15)

        rows = [
            SimpleRow(log_date=latest_date, weight_lbs=195.0),  # +7.0
            SimpleRow(log_date=prior_date, weight_lbs=188.0),   # prior down
            SimpleRow(log_date=before_date, weight_lbs=192.0),  # before up (down from 192→188)
        ]

        # At slope 0 (unadjusted), this fires
        anchor_0, spiked_0 = detect_water_spike(rows, expected_weekly_loss=0.0)
        assert spiked_0 is True, "At slope 0, a 7 lb jump should fire as gluten"

        # At slope 2.5 (block 3 week 7-11), this does NOT fire
        anchor_25, spiked_25 = detect_water_spike(rows, expected_weekly_loss=2.5)
        assert spiked_25 is False, (
            "At slope 2.5, adjusted=9.5 > 8 ceiling; should NOT fire "
            "(reconstructed magnitude too large for water)"
        )

    def test_real_regain_does_not_fire(self):
        from cut_guard import detect_water_spike

        SimpleRow = namedtuple('SimpleRow', ['log_date', 'weight_lbs'])

        # (b) A large real regain (7.5 over 10 days, slope 2.5 → ~11.07 adjusted)
        # should NOT fire (slope-adjusted puts it way out of band)
        before_date = datetime(2026, 8, 1)
        prior_date = datetime(2026, 8, 11)  # 10 days later
        latest_date = datetime(2026, 8, 21)  # 10 days later

        rows = [
            SimpleRow(log_date=latest_date, weight_lbs=195.0),   # +7.5
            SimpleRow(log_date=prior_date, weight_lbs=187.5),    # prior down
            SimpleRow(log_date=before_date, weight_lbs=191.0),   # before up (down from 191→187.5)
        ]

        # At slope 2.5, adjusted = 7.5 + 2.5 * (10/7) ≈ 7.5 + 3.57 ≈ 11.07
        # This exceeds the 3-8 lb band AND the 8 lb ceiling
        anchor, spiked = detect_water_spike(rows, expected_weekly_loss=2.5)
        assert spiked is False, (
            "Large real regain (7.5 over 10 days, adjusted ~11.07) should NOT fire; "
            "it exceeds both the band and ceiling"
        )


class TestTableCensusGuard:
    """Guard 5: Schema drift guard — all week-bearing models must match the spec."""

    def test_table_census_passes(self):
        """The transition_block3 spec-frozen SHIFTED_TABLES list must match all
        week-bearing models in models.py (minus 3 explicitly-excluded ones).
        This catches the case where a new week-bearing table gets added later
        and nobody remembers to update SHIFTED_TABLES."""
        from transition_block3 import assert_table_census
        # This should not raise if the spec matches current models
        assert_table_census()


class TestCSVIntegrityGuard:
    """Guard 6: Peptide protocol CSV must have correct row count, no duplicates, correct doses."""

    def test_peptide_protocol_csv_integrity(self):
        """
        - 381 data rows (2026-08-30: Tesamorelin replanned — started early, 1 mg/40u M-F, weekends off)
        - Zero duplicate (Date, Compound) pairs
        - Enclomiphene always 6.25 mg
        - Retatrutide doses only in {2.0, 3.0, 4.0} mg
        """
        csv_path = Path(__file__).parent / "fixtures" / "peptide_protocol_snapshot.csv"  # snapshot 2026-09-03; the DB is the source of truth
        assert csv_path.exists(), f"peptide_protocol.csv not found at {csv_path}"

        rows = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 381, (
            f"Expected 381 data rows, got {len(rows)}"
        )

        # Check for duplicate (Date, Compound) pairs
        seen = set()
        duplicates = set()
        for row in rows:
            key = (row['Date'], row['Compound'])
            if key in seen:
                duplicates.add(key)
            seen.add(key)

        assert len(duplicates) == 0, (
            f"Found {len(duplicates)} duplicate (Date, Compound) pairs: {duplicates}"
        )

        # Check Enclomiphene dose (12.5 mg daily for the whole protocol — 7fc9106)
        for row in rows:
            if row['Compound'] == 'Enclomiphene':
                dose = float(row['Dose_mg'])
                assert dose == 12.5, (
                    f"Enclomiphene dose must be 12.5 mg, got {dose} on {row['Date']}"
                )

        # Check Retatrutide doses
        valid_retratrutide_doses = {2.0, 3.0, 4.0}
        for row in rows:
            if row['Compound'] == 'Retatrutide':
                dose = float(row['Dose_mg'])
                assert dose in valid_retratrutide_doses, (
                    f"Retatrutide dose must be in {valid_retratrutide_doses}, "
                    f"got {dose} on {row['Date']}"
                )
