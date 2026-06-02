"""The weekly-planning walkthrough goes ONE day at a time and must never lock
the whole week on the first 'yes'.

Two mechanisms enforce this:
  1. The actual day-by-day ADVANCE is driven deterministically on the CLIENT
     (sendInlineCoachMsg auto-advances on the athlete's confirmation, regardless
     of whether the model emits [SHOW_NEXT_DAY]).
  2. The server injects a STATIC anti-lock guard, _weekly_planning_progress(),
     into the weekly_planning prompt.

An earlier version of the guard counted days and hardcoded 'Monday' as the next
day — which made the coach announce the WRONG day when the walkthrough started
on a later weekday. The guard must therefore name NO specific weekday; the app
owns day order.
"""
from coach_assembler import _weekly_planning_progress


def test_injects_planning_progress_block():
    d = _weekly_planning_progress()
    assert "<planning_progress>" in d and "</planning_progress>" in d


def test_forbids_locking_the_whole_week():
    low = _weekly_planning_progress().lower()
    assert "never" in low
    assert "lock" in low
    assert "whole week" in low


def test_requires_show_next_day_to_advance():
    assert "[SHOW_NEXT_DAY]" in _weekly_planning_progress()


def test_names_no_specific_weekday():
    # the bug was hardcoding 'Monday'; the app owns day order, so the guard must
    # not name any weekday.
    d = _weekly_planning_progress()
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"):
        assert day not in d, f"guard must not hardcode a weekday; found {day!r}"
