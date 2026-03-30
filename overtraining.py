"""Overtraining risk assessment from Garmin data."""


def assess_readiness(garmin_data):
    """
    Analyze Garmin metrics and return an overtraining risk assessment.

    Returns dict with:
        risk_level: "low" | "moderate" | "high"
        score: 0-100 (higher = more recovered)
        flags: list of warning strings
        suggestion: actionable text
        ok_to_train: bool
        metrics: dict of normalized metric scores
    """
    if not garmin_data:
        return {
            "risk_level": "unknown",
            "score": None,
            "flags": [],
            "suggestion": "No readiness data. Connect your Garmin watch to unlock this.",
            "ok_to_train": True,
            "metrics": {},
        }

    flags = []
    scores = {}
    weights = {}

    # --- Training Readiness (30%) ---
    tr = garmin_data.get("trainingReadiness")
    if tr and tr.get("score") is not None:
        tr_score = tr["score"]
        scores["trainingReadiness"] = min(tr_score, 100)
        weights["trainingReadiness"] = 0.30
        if tr_score < 30:
            flags.append(f"Training readiness very low ({tr_score})")
        elif tr_score < 50:
            flags.append(f"Training readiness below average ({tr_score})")

    # --- HRV (25%) ---
    hrv = garmin_data.get("hrv")
    if hrv and hrv.get("lastNight") is not None:
        last = hrv["lastNight"]
        weekly = hrv.get("weeklyAvg")
        baseline_high = hrv.get("baselineHigh")

        if weekly and weekly > 0:
            pct_change = ((last - weekly) / weekly) * 100
            # Normalize: +10% or better = 100, -25% or worse = 0
            hrv_score = max(0, min(100, 100 + (pct_change * 2.86)))
            scores["hrv"] = hrv_score
            weights["hrv"] = 0.25
            if pct_change < -25:
                flags.append(f"HRV {abs(pct_change):.0f}% below weekly average ({last} vs {weekly})")
            elif pct_change < -15:
                flags.append(f"HRV {abs(pct_change):.0f}% below weekly average")
        elif baseline_high:
            ratio = last / baseline_high
            hrv_score = min(100, ratio * 100)
            scores["hrv"] = hrv_score
            weights["hrv"] = 0.25

    # --- Sleep (20%) ---
    sleep = garmin_data.get("sleep")
    if sleep:
        sleep_score = sleep.get("score")
        duration_h = sleep.get("durationHours", 0)

        if sleep_score is not None:
            scores["sleep"] = min(sleep_score, 100)
            weights["sleep"] = 0.20
            if sleep_score < 50:
                flags.append(f"Sleep score poor ({sleep_score})")
            elif sleep_score < 70:
                flags.append(f"Sleep score below average ({sleep_score})")

        if duration_h < 5:
            flags.append(f"Very low sleep duration ({duration_h}h)")
        elif duration_h < 6:
            flags.append(f"Low sleep duration ({duration_h}h)")

    # --- Body Battery (15%) ---
    bb = garmin_data.get("bodyBattery")
    if bb and bb.get("current") is not None:
        bb_val = bb["current"]
        scores["bodyBattery"] = min(max(bb_val, 0), 100)
        weights["bodyBattery"] = 0.15
        if bb_val < 15:
            flags.append(f"Body battery critically low ({bb_val})")
        elif bb_val < 30:
            flags.append(f"Body battery low ({bb_val})")

    # --- Stress (10%) ---
    stress = garmin_data.get("stress")
    if stress and stress.get("overall") is not None:
        stress_val = stress["overall"]
        # Invert: low stress = high score
        stress_score = max(0, 100 - stress_val)
        scores["stress"] = stress_score
        weights["stress"] = 0.10
        if stress_val > 70:
            flags.append(f"Stress level very high ({stress_val})")
        elif stress_val > 50:
            flags.append(f"Stress level elevated ({stress_val})")

    # --- Composite Score ---
    if not scores:
        return {
            "risk_level": "unknown",
            "score": None,
            "flags": flags,
            "suggestion": "Garmin connected but no data yet. Wear your watch tonight.",
            "ok_to_train": True,
            "metrics": {},
        }

    # Normalize weights to sum to 1.0
    total_weight = sum(weights.values())
    composite = sum(scores[k] * (weights[k] / total_weight) for k in scores)
    composite = round(composite)

    # Determine risk level
    if composite >= 65:
        risk_level = "low"
        suggestion = "Green light. Hit it hard today."
        ok = True
    elif composite >= 40:
        risk_level = "moderate"
        suggestion = "Your body's talking — listen. Drop 1-2 sets or 10% weight. Form over ego today."
        ok = True
    else:
        risk_level = "high"
        suggestion = "Stand down. Walk, stretch, recover. Pushing through this is how you lose a week, not gain a day."
        ok = False

    return {
        "risk_level": risk_level,
        "score": composite,
        "flags": flags,
        "suggestion": suggestion,
        "ok_to_train": ok,
        "metrics": {k: round(v) for k, v in scores.items()},
    }
