"""Block-2 lifting volume must CLIMB across the block, never taper.

Block 1's #1 programming failure (Erik's debrief, 2026-06-29): the weekly target
was a FLAT 81 and the coach obeyed "more is not better" at the low end, so volume
collapsed 163 -> 48 sets across weeks 1-12. Block 2 replaces the flat target with
a climbing curve (C1) plus a code-enforced floor (C2, see test_volume_floor.py).

C1 here: the per-week target itself must strictly increase on non-deload weeks,
notch down on the deload/test weeks (4/8/12), and peak aggressively (Erik chose
the ~106 peak governor).
"""


def test_target_weekly_sets_climbs_across_block():
    from app import _target_weekly_sets
    deloads = {4, 8, 12}
    nondeload = [w for w in range(1, 13) if w not in deloads]
    vals = [_target_weekly_sets(w) for w in nondeload]
    # strictly increasing across every non-deload week — the anti-taper guarantee
    assert vals == sorted(vals), vals
    assert len(set(vals)) == len(vals), vals  # no flat stretches


def test_deload_weeks_dip_below_neighbors():
    from app import _target_weekly_sets
    for d in (4, 8, 12):
        for n in (d - 1, d + 1):
            if 1 <= n <= 12:
                assert _target_weekly_sets(d) < _target_weekly_sets(n), (d, n)


def test_aggressive_peak_at_week_eleven():
    from app import _target_weekly_sets
    # Erik's governor call: aggressive, peak ~106 at wk11 — and above block-1's 89.
    assert _target_weekly_sets(11) >= 100
    assert _target_weekly_sets(11) == max(_target_weekly_sets(w) for w in range(1, 13))
