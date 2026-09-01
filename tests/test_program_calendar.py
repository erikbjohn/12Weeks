"""S023: one week formula, everywhere."""
import pathlib
import re
from datetime import date
from program_calendar import program_week, day_date, week_day_for_date


def test_week_boundaries_and_clamps():
    start = date(2026, 8, 10)  # Monday
    assert program_week(start, start) == 1
    assert program_week(start, date(2026, 8, 16)) == 1
    assert program_week(start, date(2026, 8, 17)) == 2
    assert program_week(start, date(2026, 8, 1)) == 1      # pre-start clamps to 1
    assert program_week(start, date(2027, 1, 1)) == 12     # post-block clamps to 12
    assert program_week(None, date(2026, 9, 1)) == 1


def test_day_date_and_inverse_round_trip():
    start = date(2026, 8, 10)
    for week in (1, 4, 12):
        for di in range(7):
            d = day_date(start, week, di)
            assert week_day_for_date(start, d) == (week, di)
    assert week_day_for_date(start, date(2026, 8, 9)) == (None, None)   # before block
    assert week_day_for_date(start, day_date(start, 13, 0)) == (None, None)  # after block


def test_no_inline_copies_of_the_formula_remain():
    for f in ("app.py", "coach_assembler.py", "coach_rules.py", "weekly_report.py", "garmin_sync.py"):
        src = pathlib.Path(f).read_text()
        assert "// 7 + 1" not in src, f"{f} still has an inline week formula"
    js = pathlib.Path("static/app.js").read_text()
    assert len(re.findall(r"Math\.floor\(\w+ / 7\) \+ 1", js)) == 1, "JS must have exactly one formula (programWeekFor)"
