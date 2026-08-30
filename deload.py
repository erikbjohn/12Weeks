"""deload.py — deloads are called by the coach from the data, never by week number.

Until 2026-08-30 `week in (4, 8, 12)` was hardcoded in eight places (planning
context, set-target curve, volume-floor anchor, auto-reconcile, run floors,
chat-marker guards, training_engine, lift_trend) and the coach could not
override it — Erik hit a forced deload in week 4 of block 3 while adding
weight. His call: "Let the coach call them from the data."

The ONLY source of truth is now a persisted per-week flag on
WeeklyDaySchedule (`deload`, `deload_reason`), written when the strength coach
returns its decision at weekly generation, and flippable by the athlete via the
codified [DELOAD: week=N, call=true|false, reason=…] chat marker.
"""
import logging
from datetime import timedelta

log = logging.getLogger(__name__)

DELOAD_VOLUME_FACTOR = 0.55  # a coach-called deload targets ~55% of the climb value


def _rows(user_id, week):
    from models import WeeklyDaySchedule
    return WeeklyDaySchedule.query.filter_by(user_id=user_id, week=week).all()


def is_deload_week(user_id, week) -> bool:
    """True only when the persisted flag says so. No week-number magic."""
    try:
        return any(bool(getattr(r, "deload", False)) for r in _rows(user_id, week))
    except Exception:
        log.warning("is_deload_week(%s, %s) failed", user_id, week, exc_info=True)
        return False


def deload_reason(user_id, week):
    try:
        for r in _rows(user_id, week):
            if getattr(r, "deload_reason", None):
                return r.deload_reason
    except Exception:
        pass
    return None


def persist_deload_decision(user_id, week, decision) -> int:
    """Write the coach's (or athlete's) decision onto every schedule row of the
    week. Returns the number of rows updated (0 when the week has no schedule
    yet — callers write the schedule first)."""
    from models import db
    flag = bool((decision or {}).get("deload"))
    reason = (decision or {}).get("reason") or None
    rows = _rows(user_id, week)
    for r in rows:
        r.deload = flag
        r.deload_reason = reason
    if rows:
        db.session.commit()
    return len(rows)


def athlete_override(user_id, week):
    """A decision the athlete codified via the [DELOAD] marker for this week
    (reason prefixed 'athlete:'), or None. Regeneration hands it to the coach
    as an instruction, not evidence."""
    try:
        for r in _rows(user_id, week):
            if (r.deload_reason or "").startswith("athlete:"):
                return {"deload": bool(r.deload), "reason": r.deload_reason}
    except Exception:
        pass
    return None


def weeks_since_deload(user_id, week):
    """(weeks_ago, that_week, reason) for the most recent flagged week before
    `week`, or None when none exists this block."""
    for w in range(int(week) - 1, 0, -1):
        if is_deload_week(user_id, w):
            return (int(week) - w, w, deload_reason(user_id, w))
    return None


_PLACEHOLDER = (5, 5, 5, 5, 5, 3)  # the client's invented neutral check-in (see audit S021)


def deload_evidence(user_id, week, today) -> dict:
    out = {"weeks_since_deload": weeks_since_deload(user_id, week),
           "wellness_line": None, "lift_decline": None, "checkins": None}
    try:
        from models import GarminWellness
        from coach_assembler import wellness_trends, format_wellness_line
        rows = (GarminWellness.query
                .filter(GarminWellness.user_id == user_id,
                        GarminWellness.date >= today - timedelta(days=28)).all())
        w = wellness_trends(rows, today) if rows else None
        out["wellness_line"] = format_wellness_line(w) if w else None
    except Exception:
        log.warning("deload evidence: wellness failed", exc_info=True)
    try:
        from lift_trend import lift_decline
        out["lift_decline"] = lift_decline(user_id, max(1, int(week) - 1))
    except Exception:
        log.warning("deload evidence: lift trend failed", exc_info=True)
    try:
        from models import MorningCheckIn
        rows = (MorningCheckIn.query
                .filter(MorningCheckIn.user_id == user_id,
                        MorningCheckIn.log_date >= today - timedelta(days=7)).all())
        real = [r for r in rows if (r.sleep_quality, r.stress_level, r.soreness, r.mood,
                                    r.motivation, r.anxiety) != _PLACEHOLDER]
        sore = [r.soreness for r in real if r.soreness is not None]
        sleep = [r.sleep_quality for r in real if r.sleep_quality is not None]
        if real:
            out["checkins"] = {"n": len(real),
                               "soreness_avg": round(sum(sore) / len(sore), 1) if sore else None,
                               "sleep_avg": round(sum(sleep) / len(sleep), 1) if sleep else None}
    except Exception:
        log.warning("deload evidence: check-ins failed", exc_info=True)
    return out


def deload_evidence_text(user_id, week, today) -> str:
    """The block the strength coach decides from. Numbers only — the decision
    and its one-sentence reason are the coach's."""
    ev = deload_evidence(user_id, week, today)
    ws = ev["weeks_since_deload"]
    last = (f"{ws[0]} week(s) ago (week {ws[1]}: {ws[2] or 'no reason recorded'})"
            if ws else f"none — no deload yet this block (this is week {week} of 12)")
    wl = ev["wellness_line"] or "wellness: no data (Garmin dark)"
    ld = ev["lift_decline"]
    if ld:
        lt = ("lift trend: DECLINE suspected — " + (ld.get("details") or "")
              if ld.get("lift_decline_suspected") else
              "lift trend: holding/progressing — " + (ld.get("details") or ""))
    else:
        lt = "lift trend: no data"
    ck = ev["checkins"]
    ckl = (f"check-ins (7d, real entries only, n={ck['n']}): soreness avg {ck['soreness_avg']}/10, "
           f"sleep avg {ck['sleep_avg']}/10") if ck else "check-ins (7d): no real entries"
    return (
        "DELOAD DECISION — yours, from this evidence. There are NO scheduled deload "
        "weeks in this program; being week 4/8/12 is NOT a reason.\n"
        f"- Last coach-called deload: {last}\n"
        f"- {wl}\n"
        f"- {lt}\n"
        f"- {ckl}\n"
        "Default = NORMAL week. Call a deload ONLY when at least two independent "
        "signals show accumulating fatigue (RHR/HRV 7d worse than 28d; lift "
        "regression on 2+ compounds; soreness/sleep trending bad; 5+ weeks since "
        "the last deload WITH any of the above). An athlete who just added load "
        "and is progressing does not get a deload. If you DO call one: ~"
        f"{int(DELOAD_VOLUME_FACTOR * 100)}% of the volume target via lighter loads "
        "and fewer movements — never fewer sets per movement — and cite the "
        "evidence in one sentence."
    )
