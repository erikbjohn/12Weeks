"""Training streak counts EVIDENCE, not just the day-done toggle (Erik,
2026-08-24): Thu w2 had every prescribed set done but no DayCompletion row
(auto-complete silently failed) and Sunday's 90-min run could never count
because Sunday was hard-coded as rest. A day is done when any of:
  - the toggle row says done
  - every prescribed set is performed (workout_state_from_rows == complete)
  - the day prescribes no lifting and a run is logged
"""
from types import SimpleNamespace as NS

from workout_status import completed_day_keys, streak_stats


def _row(name, done=True, skipped=False):
    return NS(exercise_name=name, done=done, set_skipped=skipped)


RX = [{"name": "Barbell Bent-Over Row", "sets": 4}, {"name": "Goblet Squat", "sets": 3}]


def test_toggle_counts():
    done = completed_day_keys(schedule=[(2, 3)], toggled={(2, 3)},
                              prescribed={}, set_rows={}, run_days=set())
    assert done == {(2, 3)}


def test_all_prescribed_sets_done_counts_without_toggle():
    rows = [_row("Barbell Bent-Over Row")] * 4 + [_row("Goblet Squat")] * 3
    done = completed_day_keys(schedule=[(2, 3)], toggled=set(),
                              prescribed={(2, 3): RX}, set_rows={(2, 3): rows}, run_days=set())
    assert done == {(2, 3)}


def test_partial_sets_do_not_count():
    rows = [_row("Barbell Bent-Over Row")] * 4 + [_row("Goblet Squat")] * 2
    done = completed_day_keys(schedule=[(2, 3)], toggled=set(),
                              prescribed={(2, 3): RX}, set_rows={(2, 3): rows}, run_days=set())
    assert done == set()


def test_run_only_day_counts_when_run_logged():
    done = completed_day_keys(schedule=[(2, 6)], toggled=set(),
                              prescribed={(2, 6): []}, set_rows={}, run_days={(2, 6)})
    assert done == {(2, 6)}


def test_lift_day_with_only_a_run_does_not_count():
    done = completed_day_keys(schedule=[(2, 3)], toggled=set(),
                              prescribed={(2, 3): RX}, set_rows={}, run_days={(2, 3)})
    assert done == set()


def test_unplanned_day_without_run_does_not_count():
    done = completed_day_keys(schedule=[(2, 6)], toggled=set(),
                              prescribed={(2, 6): []}, set_rows={}, run_days=set())
    assert done == set()


def test_streak_spans_seven_day_weeks():
    # w1 Fri, Sat, Sun + w2 Mon done -> current streak 4 (Sunday is a real day)
    sched = [(1, d) for d in range(7)] + [(2, 0), (2, 1)]
    st = streak_stats(sched, {(1, 4), (1, 5), (1, 6), (2, 0)})
    assert st["current_streak"] == 4
    assert st["best_streak"] == 4


def test_streak_anchors_on_latest_done_day():
    # today (2,1) not yet logged must not zero the streak
    sched = [(1, d) for d in range(7)] + [(2, 0), (2, 1)]
    st = streak_stats(sched, {(1, 6), (2, 0)})
    assert st["current_streak"] == 2


def test_best_streak_survives_a_gap():
    sched = [(1, d) for d in range(7)]
    st = streak_stats(sched, {(1, 0), (1, 1), (1, 2), (1, 4)})
    assert st["best_streak"] == 3
    assert st["current_streak"] == 1
