"""THE program-week arithmetic. Pure functions, no Flask, no DB (S023).

start_date is the block's Monday. Week N covers start_date + 7*(N-1) ..
+6; day_idx 0..6 is Mon..Sun. Every surface — _current_week, the
generation lock, Garmin week mapping, the weekly report, coach_rules,
the client's getActualProgramWeek — must agree, and they can only agree
if they all call these. Before this module the formula existed as seven
Python copies and four JS copies, one of which used server-UTC time.
"""
from __future__ import annotations

from datetime import date, timedelta

PROGRAM_WEEKS = 12


def program_week(start_date: date | None, today: date) -> int:
    """1..12, clamped. Week 1 before the start (pre-start lockout is the
    caller's job) and week 12 after the block ends."""
    if not start_date:
        return 1
    diff_days = (today - start_date).days
    return min(PROGRAM_WEEKS, max(1, diff_days // 7 + 1))


def day_date(start_date: date, week: int, day_idx: int) -> date:
    """Calendar date of (week, day_idx)."""
    return start_date + timedelta(days=(week - 1) * 7 + day_idx)


def week_day_for_date(start_date: date | None, d: date | None):
    """Inverse of day_date. (None, None) outside the 12-week window —
    NOT clamped, because a Garmin activity from before the block must not
    be filed under week 1."""
    if not start_date or not d:
        return (None, None)
    diff = (d - start_date).days
    if diff < 0:
        return (None, None)
    week = diff // 7 + 1
    if week > PROGRAM_WEEKS:
        return (None, None)
    return (week, diff % 7)
