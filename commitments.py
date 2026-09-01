"""Standing commitments (S080): {day, activity, duration_min, kind, cadence,
anchor_date, elevation_ft?} — "El Cajon trail run, Saturday, every other
week" is representable, and the planners get the concrete dates that fall in
the week being planned. Pure helpers; no Flask, no DB.
"""
from __future__ import annotations

from datetime import date, timedelta

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
KINDS = ("trail_long_run", "race", "group_run", "other")
CADENCES = ("weekly", "biweekly", "once")


def day_index(day) -> int | None:
    if isinstance(day, int):
        return day if 0 <= day <= 6 else None
    d = str(day or "").strip().lower()
    for i, n in enumerate(DAY_NAMES):
        if d.startswith(n.lower()[:3]):
            return i
    return None


def occurs_in_week(activity: dict, week_monday: date) -> date | None:
    """The date this commitment lands on inside [week_monday, +6], or None."""
    di = day_index(activity.get("day"))
    if di is None:
        return None
    on = week_monday + timedelta(days=di)
    cadence = (activity.get("cadence") or "weekly").lower()
    anchor = activity.get("anchor_date")
    try:
        anchor_d = date.fromisoformat(anchor) if anchor else None
    except ValueError:
        anchor_d = None
    if cadence == "weekly":
        return on
    if cadence == "biweekly":
        if anchor_d is None:
            return on
        return on if ((on - anchor_d).days // 7) % 2 == 0 and (on - anchor_d).days >= 0 else None
    if cadence == "once":
        return on if anchor_d == on else None
    return on


def fixed_days_for_week(activities, week_monday: date) -> dict:
    """{day_idx: activity} for the commitments that fall in this week."""
    out = {}
    for a in activities or []:
        if not isinstance(a, dict):
            continue
        d = occurs_in_week(a, week_monday)
        if d is not None:
            out[(d - week_monday).days] = dict(a, date=d.isoformat())
    return out


def describe(activities, week_monday: date | None = None) -> str:
    """Prompt text. With a week, lists only the commitments that land in it,
    with their dates; without, lists the standing rules."""
    lines = []
    if week_monday is not None:
        fixed = fixed_days_for_week(activities, week_monday)
        for di in sorted(fixed):
            a = fixed[di]
            lines.append(f"  - {DAY_NAMES[di]} {a['date']}: {a.get('activity', '?')} "
                         f"({a.get('duration_min', '?')} min, {a.get('kind') or 'other'}"
                         + (f", ~{a['elevation_ft']} ft gain" if a.get('elevation_ft') else "") + ") — FIXED; plan around it")
        return ("Committed activities THIS WEEK (fixed — the run on that day IS this; never prescribe a second run "
                "or a heavy lower session on top of it):\n" + "\n".join(lines)) if lines else ""
    for a in activities or []:
        if not isinstance(a, dict):
            continue
        cad = a.get("cadence") or "weekly"
        lines.append(f"  - {a.get('day', '?')}: {a.get('activity', '?')} ({a.get('duration_min', '?')} min, {cad}"
                     + (f" from {a['anchor_date']}" if a.get('anchor_date') else "") + ")")
    return ("Standing commitments:\n" + "\n".join(lines)) if lines else ""
