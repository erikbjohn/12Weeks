"""Codified lift-decline detector — the recomp-goal "Line 2" tripwire.

Block 3 pairs a peptide protocol with a recomp goal: cutting calories while
trying to hold/build strength. The coach must never be trusted to notice a
lift decline on its own (LLM judgment is exactly the failure mode this
module exists to remove) — this is a deterministic, DB-derived signal that
both the coach context and the weekly report read from the SAME function,
so the two surfaces can never disagree about whether a decline is real.

Definition (spec section 5b):
  - Deload weeks (DELOAD_WEEKS) are EXCLUDED ENTIRELY from every comparison
    — not compared against, not counted as "recent", not used as
    reference. A deliberately light deload week must never read as a
    decline.
  - The "reference" is the BEST (max) value among the trailing 3 non-deload
    weeks that come immediately before the two most recent non-deload
    weeks (in the non-deload sequence — a deload week sitting between the
    reference weeks and the recent weeks does not break adjacency; it is
    simply skipped).
  - Trips (lift_decline_suspected = True) when EITHER:
      (a) per-lift weekly max e1RM (from lift_history.lift_session_history,
          movement-matched) is down >= 5% vs reference on >= 2 of the 5
          KEY_LIFTS, for BOTH of the 2 most recent non-deload weeks; OR
      (b) weekly tonnage (sum of weight * reps over done, non-skipped
          working sets with weight > 0, across ALL logged lifts, not just
          the 5 key lifts) is down >= 10% vs the best-of-trailing-3
          reference, for BOTH of the 2 most recent non-deload weeks.
  - With fewer than 3 prior non-deload weeks of data, the detector NEVER
    trips — there isn't enough history to trust a "reference". e1rm_deltas
    still carries the most-recent-week values vs whatever reference exists
    (None per lift when there's no reference or no data for that lift that
    week). weeks_compared reports exactly what data existed, honestly.

Tonnage FALSY-ZERO LANDMINE: SetLog.weight == 0 is the bodyweight
sentinel, not a real "zero pounds" working set. It is excluded from
tonnage via `weight is not None and weight > 0` — never a truthiness
check (a real weight could theoretically be falsy-adjacent in other
fields; this module follows the codebase-wide convention explicitly).

Pure-ish: this module does DB reads (SetLog, via lift_history) but takes
plain `user_id`/`week` arguments like lift_history.py — no Flask request
context, no `current_user`. Safe to call from coach_assembler (request
context available) and weekly_report (may or may not have one).
"""

KEY_LIFTS = [
    "Barbell Bench Press", "Barbell Back Squat", "Conventional Deadlift",
    "Barbell OHP", "Barbell Bent-Over Row",
]
# DELOAD_WEEKS is gone (2026-08-30): deloads are coach-called per-user flags —
# _weeks_with_data excludes weeks flagged via deload.is_deload_week.

E1RM_DECLINE_PCT = 5.0
TONNAGE_DECLINE_PCT = 10.0


def _weeks_with_data(user_id, upto_week):
    """Ascending list of non-deload weeks (<= upto_week) where the athlete
    has at least one done, non-skipped SetLog row — the shared candidate
    pool used to pick "the 2 most recent" and "the trailing 3 reference"
    weeks. Deload weeks are excluded here so they can never be selected as
    either a recent week or a reference week, regardless of what data
    exists for them."""
    from models import SetLog
    rows = (SetLog.query
            .filter(SetLog.user_id == user_id,
                    SetLog.done.is_(True),
                    SetLog.set_skipped.isnot(True))
            .all())
    from deload import is_deload_week
    weeks = {r.week for r in rows if r.week is not None and r.week <= upto_week}
    weeks = {w for w in weeks if not is_deload_week(user_id, w)}
    return sorted(weeks)


def _tonnage_for_week(user_id, week):
    """Sum(weight * reps) over done, non-skipped working sets for ANY
    exercise (not just KEY_LIFTS) in the given week. Bodyweight-sentinel
    rows (weight == 0) are excluded via an explicit `> 0` check, never
    truthiness."""
    from models import SetLog
    rows = (SetLog.query
            .filter(SetLog.user_id == user_id,
                    SetLog.week == week,
                    SetLog.done.is_(True),
                    SetLog.set_skipped.isnot(True))
            .all())
    total = 0.0
    for s in rows:
        if s.weight is not None and s.weight > 0:
            total += s.weight * (s.reps or 0)
    return total


def _lift_history_by_week(user_id, lift_name):
    """{week: max_e1rm} for one lift, movement-matched, via
    lift_history.lift_session_history — the same SetLog-only source of
    truth every other reader (dashboard, weekly_report PRs) uses."""
    from lift_history import lift_session_history
    hist = lift_session_history(user_id, lift_name)
    by_week = {}
    for h in hist:
        wk, e1 = h.get("week"), h.get("e1rm")
        if wk is None or e1 is None:
            continue
        if wk not in by_week or e1 > by_week[wk]:
            by_week[wk] = e1
    return by_week


def lift_decline(user_id, week):
    """The one shared definition of the recomp lift-decline tripwire.

    Returns:
      {"lift_decline_suspected": bool,
       "e1rm_deltas": {lift_name: pct|None},   # most-recent-week vs reference
       "tonnage_delta_pct": float|None,        # most-recent-week vs reference
       "weeks_compared": [int, ...],           # reference weeks + the 2 recent
       "details": str}
    """
    weeks_data = _weeks_with_data(user_id, week)

    if len(weeks_data) < 2:
        recent2 = list(weeks_data)
        reference_weeks = []
    else:
        recent2 = weeks_data[-2:]
        reference_weeks = weeks_data[:-2][-3:]

    weeks_compared = reference_weeks + recent2
    sufficient = len(reference_weeks) >= 3 and len(recent2) == 2
    most_recent_week = weeks_data[-1] if weeks_data else None

    # ── per-lift e1RM history + most-recent-week deltas (always computed,
    #    independent of `sufficient` — this is the "honest partial data"
    #    field the spec calls for) ──────────────────────────────────────
    per_lift_by_week = {lift: _lift_history_by_week(user_id, lift) for lift in KEY_LIFTS}
    e1rm_deltas = {}
    ref_e1rm_by_lift = {}
    for lift in KEY_LIFTS:
        by_week = per_lift_by_week[lift]
        ref_vals = [by_week[w] for w in reference_weeks if w in by_week]
        ref_val = max(ref_vals) if ref_vals else None
        ref_e1rm_by_lift[lift] = ref_val
        cur_val = by_week.get(most_recent_week) if most_recent_week is not None else None
        if ref_val is None or not ref_val or cur_val is None:
            e1rm_deltas[lift] = None
        else:
            e1rm_deltas[lift] = round((cur_val - ref_val) / ref_val * 100, 1)

    # ── tonnage (all exercises) — same "most-recent-week vs reference" shape ──
    tonnage_by_week = {w: _tonnage_for_week(user_id, w) for w in weeks_compared}
    ref_tonnage_vals = [tonnage_by_week[w] for w in reference_weeks]
    ref_tonnage = max(ref_tonnage_vals) if ref_tonnage_vals else None
    tonnage_delta_pct = None
    if ref_tonnage and most_recent_week is not None:
        cur_tonnage = tonnage_by_week.get(most_recent_week)
        if cur_tonnage is not None:
            tonnage_delta_pct = round((cur_tonnage - ref_tonnage) / ref_tonnage * 100, 1)

    lift_decline_suspected = False
    details = None

    if sufficient:
        # Per-week down-lift lists, evaluated against the SAME reference
        # for both of the 2 most recent weeks.
        week_down_lifts = {}
        for wk in recent2:
            down = []
            for lift in KEY_LIFTS:
                ref_val = ref_e1rm_by_lift[lift]
                cur_val = per_lift_by_week[lift].get(wk)
                if ref_val and cur_val is not None:
                    pct = (cur_val - ref_val) / ref_val * 100
                    if pct <= -E1RM_DECLINE_PCT:
                        down.append((lift, round(pct, 1)))
            week_down_lifts[wk] = down
        e1rm_trip = all(len(week_down_lifts[wk]) >= 2 for wk in recent2)

        week_tonnage_pct = {}
        tonnage_trip = False
        if ref_tonnage:
            for wk in recent2:
                cur = tonnage_by_week.get(wk, 0.0)
                week_tonnage_pct[wk] = round((cur - ref_tonnage) / ref_tonnage * 100, 1)
            tonnage_trip = all(week_tonnage_pct.get(wk, 0.0) <= -TONNAGE_DECLINE_PCT for wk in recent2)

        lift_decline_suspected = e1rm_trip or tonnage_trip

        if lift_decline_suspected:
            reasons = []
            if e1rm_trip:
                seen = set()
                named = []
                for wk in reversed(recent2):  # most-recent week's numbers first
                    for lift, pct in week_down_lifts[wk]:
                        if lift not in seen:
                            seen.add(lift)
                            named.append(f"{lift} {pct}%")
                reasons.append(
                    f"e1RM down >= {E1RM_DECLINE_PCT:.0f}% on {len(seen)} lifts "
                    f"for weeks {recent2}: " + ", ".join(named)
                )
            if tonnage_trip:
                reasons.append(
                    f"tonnage down {week_tonnage_pct[recent2[0]]}%/{week_tonnage_pct[recent2[-1]]}% "
                    f"(weeks {recent2}) vs reference"
                )
            details = (
                "LIFT DECLINE SUSPECTED: " + "; ".join(reasons) +
                f" (reference = best of weeks {reference_weeks})"
            )
        else:
            details = (
                f"no decline detected (weeks {recent2} vs best of reference "
                f"weeks {reference_weeks})"
            )
    else:
        details = (
            f"no decline detected (insufficient history — only "
            f"{len(reference_weeks)} of 3 required reference weeks; "
            f"weeks_compared={weeks_compared})"
        )

    return {
        "lift_decline_suspected": lift_decline_suspected,
        "e1rm_deltas": e1rm_deltas,
        "tonnage_delta_pct": tonnage_delta_pct,
        "weeks_compared": weeks_compared,
        "details": details,
    }
