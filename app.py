"""Flask app for 12-Week Cut Tracker with Garmin integration."""

import os
from flask import Flask, render_template, jsonify, request, session

from workout_data import get_workouts, get_phase, PHASES
from garmin_client import GarminClient
from overtraining import assess_readiness

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# One client per server process (fine for single-user app)
garmin = GarminClient()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/workouts")
def api_workouts():
    """Return all 12 weeks of workout data."""
    all_weeks = {}
    for week in range(1, 13):
        phase = get_phase(week)
        all_weeks[str(week)] = {
            "week": week,
            "phase": phase,
            "phaseInfo": PHASES[phase],
            "days": get_workouts(week),
        }
    return jsonify(all_weeks)


@app.route("/api/workouts/<int:week>")
def api_week(week):
    if week < 1 or week > 12:
        return jsonify({"error": "Week must be 1-12"}), 400
    phase = get_phase(week)
    return jsonify({
        "week": week,
        "phase": phase,
        "phaseInfo": PHASES[phase],
        "days": get_workouts(week),
    })


@app.route("/api/garmin/login", methods=["POST"])
def garmin_login():
    data = request.get_json()
    mfa_code = data.get("mfa_code") if data else None

    # MFA step - just need the code
    if mfa_code:
        success, error, needs_mfa = garmin.login(None, None, mfa_code=mfa_code)
        if success:
            session["garmin_connected"] = True
            return jsonify({"connected": True})
        return jsonify({"connected": False, "error": error}), 401

    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email and password required"}), 400

    success, error, needs_mfa = garmin.login(data["email"], data["password"])
    if success:
        session["garmin_connected"] = True
        return jsonify({"connected": True})
    if needs_mfa:
        return jsonify({"connected": False, "needs_mfa": True, "error": "Enter the verification code from your authenticator app"})
    return jsonify({"connected": False, "error": error}), 401


@app.route("/api/garmin/status")
def garmin_status():
    return jsonify({"connected": garmin.connected})


@app.route("/api/garmin/today")
def garmin_today():
    if not garmin.connected:
        return jsonify({"error": "Not connected to Garmin"}), 401
    summary = garmin.get_today_summary()
    if summary is None:
        return jsonify({"error": "Failed to fetch Garmin data"}), 500
    return jsonify(summary)


@app.route("/api/garmin/readiness")
def garmin_readiness():
    if not garmin.connected:
        return jsonify(assess_readiness(None))
    summary = garmin.get_today_summary()
    assessment = assess_readiness(summary)
    return jsonify(assessment)


@app.route("/api/garmin/hrv-trend")
def garmin_hrv_trend():
    if not garmin.connected:
        return jsonify({"error": "Not connected"}), 401
    trend = garmin.get_weekly_hrv()
    return jsonify(trend or [])


@app.route("/api/garmin/logout", methods=["POST"])
def garmin_logout():
    garmin.api = None
    garmin._connected = False
    garmin._cache = {}
    session.pop("garmin_connected", None)
    return jsonify({"connected": False})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
