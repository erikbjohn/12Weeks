"""Tests for the null-aware run formatter (Step 1b)."""
from coach import _format_runs


def test_run_with_duration_emits_pace_and_avg_hr_full_session():
    """A run with duration_min should emit pace_min_per_mi and the
    semantic avg_hr_full_session tag."""
    runs = [{
        "date": "2026-05-06",
        "distance_miles": 6.2,
        "duration_min": 60,
        "avg_hr": 130,
    }]
    out = _format_runs(runs)
    assert "<runs_with_duration>" in out
    assert "6.2mi" in out
    assert "60min" in out
    assert "pace:" in out
    # 60 / 6.2 ≈ 9.68 min/mi
    assert "9.68" in out
    assert "avg_hr_full_session:130" in out
    # No "HR:" without semantic prefix
    assert "HR:130" not in out


def test_run_without_duration_lands_in_blocked_partition():
    """A run with duration_min=null should land in <runs_without_duration>
    with explicit annotation that pace is not computable."""
    runs = [{
        "date": "2026-05-06",
        "distance_miles": 6.2,
        "duration_min": None,
        "avg_hr": 130,
    }]
    out = _format_runs(runs)
    assert "<runs_without_duration>" in out
    assert "PACE NOT COMPUTABLE" in out
    assert "no duration logged" in out
    assert "distance_only:6.2mi" in out
    # No pace claim should appear in this block
    no_dur_block = out.split("<runs_without_duration>")[1]
    assert "pace:" not in no_dur_block


def test_mixed_runs_partition_correctly():
    runs = [
        {"date": "2026-05-06", "distance_miles": 6.2, "duration_min": 60, "avg_hr": 130},
        {"date": "2026-05-05", "distance_miles": 5.5, "duration_min": None, "avg_hr": 124},
    ]
    out = _format_runs(runs)
    # Both partitions present
    assert "<runs_with_duration>" in out
    assert "<runs_without_duration>" in out
    # The pace-block run does NOT leak into the no-duration block
    blocked_block = out.split("<runs_without_duration>")[1]
    assert "9.68" not in blocked_block  # the 60/6.2 pace
    # The no-duration rule appears
    assert "RULE:" in out


def test_empty_runs_returns_empty():
    assert _format_runs([]) == ""
    assert _format_runs(None) == ""


def test_no_avg_hr_field_named_explicitly():
    """The output should never use the bare 'HR:' prefix that historically
    let the model conflate avg with working-interval HR."""
    runs = [{"date": "2026-05-06", "distance_miles": 6.2, "duration_min": 60, "avg_hr": 130}]
    out = _format_runs(runs)
    assert " HR:" not in out  # bare HR: not used anywhere
    assert "avg_hr_full_session" in out
