"""assess_readiness: HRV normalization floor + no-data honesty (2026-07 audit)."""


def _garmin(hrv_last, hrv_weekly, tr=62, sleep_score=70, bb=60, stress=40):
    return {
        "trainingReadiness": {"score": tr},
        "hrv": {"lastNight": hrv_last, "weeklyAvg": hrv_weekly},
        "sleep": {"score": sleep_score, "durationHours": 7.0},
        "bodyBattery": {"current": bb},
        "stress": {"overall": stress},
    }


def test_hrv_crash_of_25pct_scores_zero():
    # Documented mapping: "-25% or worse = 0". The old 2.86 factor scored a
    # -25% HRV crash at 28.5/100 — inflating the composite during the exact
    # condition the metric exists to catch.
    from overtraining import assess_readiness
    r = assess_readiness(_garmin(hrv_last=41.25, hrv_weekly=55))  # exactly -25%
    assert r["metrics"]["hrv"] == 0
    assert any("below weekly average" in f for f in r["flags"])


def test_hrv_crash_drops_composite_out_of_green():
    # Audit failure case: TR 62, sleep 70, BB 60, stress 40, HRV -25%.
    # With the broken factor the composite hit 66.7 → "low" risk / "hit it
    # hard"; the corrected floor lands ~59.6 → moderate, back-off suggestion.
    from overtraining import assess_readiness
    r = assess_readiness(_garmin(hrv_last=41.25, hrv_weekly=55))
    assert r["risk_level"] == "moderate"
    assert r["score"] < 65


def test_hrv_above_weekly_avg_still_scores_100():
    from overtraining import assess_readiness
    r = assess_readiness(_garmin(hrv_last=60, hrv_weekly=55))  # ~+9%
    assert r["metrics"]["hrv"] == 100


def test_no_garmin_data_reports_unknown_with_null_score():
    from overtraining import assess_readiness
    r = assess_readiness(None)
    assert r["risk_level"] == "unknown" and r["score"] is None
