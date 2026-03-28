"""Flask app for 12-Week Cut Tracker with Garmin integration."""

import os
from datetime import date, timedelta, datetime
from flask import Flask, render_template, jsonify, request, session

from workout_data import get_workouts, get_phase, PHASES, WARMUPS, SUPPLEMENTS
from garmin_client import GarminClient
from overtraining import assess_readiness
from models import (
    db, ExerciseLog, ExerciseCompletion, DayCompletion,
    MealLog, AppState, BodyWeight, BodyMeasurement,
    WeeklyCheckIn, SupplementLog,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Database
db_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()

garmin = GarminClient()


# ─── PAGES ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── WORKOUT DATA ───────────────────────────────────────────────────────────

@app.route("/api/workouts")
def api_workouts():
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
        "week": week, "phase": phase,
        "phaseInfo": PHASES[phase],
        "days": get_workouts(week),
    })


@app.route("/api/warmups")
def api_warmups():
    return jsonify(WARMUPS)


# ─── APP STATE ──────────────────────────────────────────────────────────────

def _get_state():
    s = AppState.query.first()
    if not s:
        s = AppState(current_week=1, baseline_done=False)
        db.session.add(s)
        db.session.commit()
    return s


@app.route("/api/state")
def api_state():
    s = _get_state()
    return jsonify({
        "current_week": s.current_week,
        "baseline_done": s.baseline_done,
        "start_date": s.start_date.isoformat() if s.start_date else None,
    })


@app.route("/api/state", methods=["POST"])
def api_state_update():
    data = request.get_json()
    s = _get_state()
    if "current_week" in data:
        s.current_week = data["current_week"]
    if "baseline_done" in data:
        s.baseline_done = data["baseline_done"]
    if "start_date" in data:
        s.start_date = date.fromisoformat(data["start_date"]) if data["start_date"] else None
    db.session.commit()
    return jsonify({"ok": True})


# ─── EXERCISE WEIGHTS ───────────────────────────────────────────────────────

@app.route("/api/weights")
def api_weights():
    logs = ExerciseLog.query.order_by(ExerciseLog.logged_date, ExerciseLog.id).all()
    result = {}
    for log in logs:
        name = log.exercise_name
        if name not in result:
            result[name] = {"current": 0, "history": []}
        entry = {
            "weight": log.weight,
            "reps": log.sets_label,
            "rpe": log.rpe,
            "date": log.logged_date.isoformat() if log.logged_date else None,
            "week": log.week,
            "day": log.day_idx,
        }
        if log.test_weight is not None:
            entry["testWeight"] = log.test_weight
            entry["testReps"] = log.test_reps
            entry["estimated1RM"] = log.estimated_1rm
        result[name]["history"].append(entry)
        result[name]["current"] = log.weight
    return jsonify(result)


@app.route("/api/weights", methods=["POST"])
def api_weights_record():
    data = request.get_json()
    log = ExerciseLog(
        exercise_name=data["exercise"],
        weight=data["weight"],
        sets_label=data.get("sets_label"),
        rpe=data.get("rpe"),
        week=data.get("week"),
        day_idx=data.get("day_idx"),
        logged_date=date.today(),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True, "id": log.id})


@app.route("/api/weights/baseline", methods=["POST"])
def api_weights_baseline():
    data = request.get_json()
    for entry in data.get("exercises", []):
        log = ExerciseLog(
            exercise_name=entry["name"],
            weight=entry["working_weight"],
            sets_label=f"baseline: {entry['test_weight']}lb x {entry['test_reps']}",
            rpe="just_right",
            week=0,
            day_idx=0,
            logged_date=date.today(),
            test_weight=entry.get("test_weight"),
            test_reps=entry.get("test_reps"),
            estimated_1rm=entry.get("estimated_1rm"),
        )
        db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True})


# ─── COMPLETIONS ────────────────────────────────────────────────────────────

@app.route("/api/completions")
def api_completions():
    week = request.args.get("week", type=int)
    ex_q = ExerciseCompletion.query
    day_q = DayCompletion.query
    if week is not None:
        ex_q = ex_q.filter_by(week=week)
        day_q = day_q.filter_by(week=week)

    exercises = {}
    for ec in ex_q.filter_by(done=True).all():
        key = f"{ec.week}_{ec.day_idx}_{ec.exercise_idx}"
        exercises[key] = True

    days = {}
    for dc in day_q.filter_by(done=True).all():
        key = f"{dc.week}_{dc.day_idx}"
        days[key] = True

    return jsonify({"exercises": exercises, "days": days})


@app.route("/api/completions/exercise", methods=["POST"])
def api_toggle_exercise():
    data = request.get_json()
    w, d, e = data["week"], data["day_idx"], data["exercise_idx"]
    ec = ExerciseCompletion.query.filter_by(week=w, day_idx=d, exercise_idx=e).first()
    if ec:
        ec.done = not ec.done
    else:
        ec = ExerciseCompletion(week=w, day_idx=d, exercise_idx=e, done=True)
        db.session.add(ec)
    db.session.commit()
    return jsonify({"done": ec.done})


@app.route("/api/completions/day", methods=["POST"])
def api_toggle_day():
    data = request.get_json()
    w, d = data["week"], data["day_idx"]
    dc = DayCompletion.query.filter_by(week=w, day_idx=d).first()
    if dc:
        dc.done = not dc.done
    else:
        dc = DayCompletion(week=w, day_idx=d, done=True)
        db.session.add(dc)
    db.session.commit()
    return jsonify({"done": dc.done})


# ─── MEALS ──────────────────────────────────────────────────────────────────

@app.route("/api/meals")
def api_meals():
    d = request.args.get("date", date.today().isoformat())
    ml = MealLog.query.filter_by(log_date=date.fromisoformat(d)).first()
    if not ml:
        return jsonify({"eaten": [], "adjustments": {}, "fasting": False})
    return jsonify({
        "eaten": ml.eaten or [],
        "adjustments": ml.adjustments or {},
        "fasting": ml.fasting,
    })


@app.route("/api/meals", methods=["POST"])
def api_meals_update():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    ml = MealLog.query.filter_by(log_date=d).first()
    if not ml:
        ml = MealLog(log_date=d)
        db.session.add(ml)
    if "eaten" in data:
        ml.eaten = data["eaten"]
    if "adjustments" in data:
        ml.adjustments = data["adjustments"]
    if "fasting" in data:
        ml.fasting = data["fasting"]
    db.session.commit()
    return jsonify({"ok": True})


# ─── BODY WEIGHT ────────────────────────────────────────────────────────────

@app.route("/api/bodyweight")
def api_bodyweight():
    entries = BodyWeight.query.order_by(BodyWeight.log_date).all()
    result = []
    for i, e in enumerate(entries):
        window = entries[max(0, i - 6):i + 1]
        avg = sum(w.weight_lbs for w in window) / len(window)
        result.append({
            "date": e.log_date.isoformat(),
            "weight": e.weight_lbs,
            "rolling_avg": round(avg, 1),
        })
    return jsonify(result)


@app.route("/api/bodyweight", methods=["POST"])
def api_bodyweight_record():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    bw = BodyWeight.query.filter_by(log_date=d).first()
    if bw:
        bw.weight_lbs = data["weight"]
    else:
        bw = BodyWeight(log_date=d, weight_lbs=data["weight"])
        db.session.add(bw)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/bodyweight/<log_date>", methods=["DELETE"])
def api_bodyweight_delete(log_date):
    bw = BodyWeight.query.filter_by(log_date=date.fromisoformat(log_date)).first()
    if bw:
        db.session.delete(bw)
        db.session.commit()
    return jsonify({"ok": True})


# ─── BODY MEASUREMENTS ─────────────────────────────────────────────────────

@app.route("/api/measurements")
def api_measurements():
    entries = BodyMeasurement.query.order_by(BodyMeasurement.log_date).all()
    return jsonify([{
        "date": e.log_date.isoformat(),
        "waist": e.waist_inches,
        "notes": e.notes,
    } for e in entries])


@app.route("/api/measurements", methods=["POST"])
def api_measurements_record():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    bm = BodyMeasurement.query.filter_by(log_date=d).first()
    if bm:
        if "waist" in data:
            bm.waist_inches = data["waist"]
        if "notes" in data:
            bm.notes = data["notes"]
    else:
        bm = BodyMeasurement(
            log_date=d,
            waist_inches=data.get("waist"),
            notes=data.get("notes"),
        )
        db.session.add(bm)
    db.session.commit()
    return jsonify({"ok": True})


# ─── WEEKLY CHECK-IN ────────────────────────────────────────────────────────

@app.route("/api/checkins")
def api_checkins():
    entries = WeeklyCheckIn.query.order_by(WeeklyCheckIn.week).all()
    return jsonify([{
        "week": e.week,
        "energy": e.energy_level,
        "sleep": e.sleep_quality,
        "soreness": e.soreness_level,
        "adherence": e.adherence_pct,
        "notes": e.notes,
        "date": e.check_in_date.isoformat() if e.check_in_date else None,
    } for e in entries])


@app.route("/api/checkins", methods=["POST"])
def api_checkins_record():
    data = request.get_json()
    week = data["week"]
    ci = WeeklyCheckIn.query.filter_by(week=week).first()
    if ci:
        ci.energy_level = data.get("energy", ci.energy_level)
        ci.sleep_quality = data.get("sleep", ci.sleep_quality)
        ci.soreness_level = data.get("soreness", ci.soreness_level)
        ci.adherence_pct = data.get("adherence", ci.adherence_pct)
        ci.notes = data.get("notes", ci.notes)
    else:
        ci = WeeklyCheckIn(
            week=week,
            energy_level=data.get("energy"),
            sleep_quality=data.get("sleep"),
            soreness_level=data.get("soreness"),
            adherence_pct=data.get("adherence"),
            notes=data.get("notes"),
            check_in_date=date.today(),
        )
        db.session.add(ci)
    db.session.commit()
    return jsonify({"ok": True})


# ─── SUPPLEMENTS ────────────────────────────────────────────────────────────

@app.route("/api/supplements")
def api_supplements():
    d = request.args.get("date", date.today().isoformat())
    logs = SupplementLog.query.filter_by(log_date=date.fromisoformat(d)).all()
    taken = {s.supplement_name: s.taken for s in logs}
    return jsonify({"date": d, "taken": taken, "list": SUPPLEMENTS})


@app.route("/api/supplements", methods=["POST"])
def api_supplements_toggle():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    name = data["name"]
    sl = SupplementLog.query.filter_by(log_date=d, supplement_name=name).first()
    if sl:
        sl.taken = not sl.taken
    else:
        sl = SupplementLog(log_date=d, supplement_name=name, taken=True)
        db.session.add(sl)
    db.session.commit()
    return jsonify({"taken": sl.taken})


# ─── DATA EXPORT/IMPORT ────────────────────────────────────────────────────

@app.route("/api/export")
def api_export():
    """Export all data as JSON for backup."""
    return jsonify({
        "exported_at": datetime.utcnow().isoformat(),
        "weights": _serialize_weights(),
        "completions": _serialize_completions(),
        "bodyweight": [{
            "date": e.log_date.isoformat(), "weight": e.weight_lbs,
        } for e in BodyWeight.query.order_by(BodyWeight.log_date).all()],
        "measurements": [{
            "date": e.log_date.isoformat(), "waist": e.waist_inches, "notes": e.notes,
        } for e in BodyMeasurement.query.order_by(BodyMeasurement.log_date).all()],
        "checkins": [{
            "week": e.week, "energy": e.energy_level, "sleep": e.sleep_quality,
            "soreness": e.soreness_level, "adherence": e.adherence_pct, "notes": e.notes,
        } for e in WeeklyCheckIn.query.order_by(WeeklyCheckIn.week).all()],
        "meals": [{
            "date": e.log_date.isoformat(), "eaten": e.eaten,
            "adjustments": e.adjustments, "fasting": e.fasting,
        } for e in MealLog.query.order_by(MealLog.log_date).all()],
        "state": {
            "current_week": _get_state().current_week,
            "baseline_done": _get_state().baseline_done,
            "start_date": _get_state().start_date.isoformat() if _get_state().start_date else None,
        },
    })


def _serialize_weights():
    logs = ExerciseLog.query.order_by(ExerciseLog.logged_date, ExerciseLog.id).all()
    result = {}
    for log in logs:
        name = log.exercise_name
        if name not in result:
            result[name] = {"current": 0, "history": []}
        result[name]["history"].append({
            "weight": log.weight, "reps": log.sets_label,
            "rpe": log.rpe, "date": log.logged_date.isoformat() if log.logged_date else None,
            "week": log.week, "day": log.day_idx,
        })
        result[name]["current"] = log.weight
    return result


def _serialize_completions():
    exercises = {}
    for ec in ExerciseCompletion.query.filter_by(done=True).all():
        exercises[f"{ec.week}_{ec.day_idx}_{ec.exercise_idx}"] = True
    days = {}
    for dc in DayCompletion.query.filter_by(done=True).all():
        days[f"{dc.week}_{dc.day_idx}"] = True
    return {"exercises": exercises, "days": days}


@app.route("/api/import", methods=["POST"])
def api_import():
    """Import data from a backup JSON (from localStorage migration or backup restore)."""
    data = request.get_json()

    # Import weights
    if "weights" in data:
        for name, info in data["weights"].items():
            for h in info.get("history", []):
                log = ExerciseLog(
                    exercise_name=name, weight=h["weight"],
                    sets_label=h.get("reps"), rpe=h.get("rpe"),
                    week=h.get("week", 0), day_idx=h.get("day", 0),
                    logged_date=date.fromisoformat(h["date"]) if h.get("date") else date.today(),
                    test_weight=h.get("testWeight"), test_reps=h.get("testReps"),
                    estimated_1rm=h.get("estimated1RM"),
                )
                db.session.add(log)

    # Import body weight
    if "bodyweight" in data:
        for entry in data["bodyweight"]:
            d = date.fromisoformat(entry["date"])
            existing = BodyWeight.query.filter_by(log_date=d).first()
            if not existing:
                db.session.add(BodyWeight(log_date=d, weight_lbs=entry["weight"]))

    # Import state
    if "state" in data:
        s = _get_state()
        s.current_week = data["state"].get("current_week", s.current_week)
        s.baseline_done = data["state"].get("baseline_done", s.baseline_done)
        if data["state"].get("start_date"):
            s.start_date = date.fromisoformat(data["state"]["start_date"])

    db.session.commit()
    return jsonify({"ok": True})


# ─── PROGRESS CHARTS DATA ──────────────────────────────────────────────────

@app.route("/api/progress")
def api_progress():
    """Return all progress data for charts."""
    # Body weight trend
    bw_entries = BodyWeight.query.order_by(BodyWeight.log_date).all()
    bodyweight = []
    for i, e in enumerate(bw_entries):
        window = bw_entries[max(0, i - 6):i + 1]
        avg = sum(w.weight_lbs for w in window) / len(window)
        bodyweight.append({
            "date": e.log_date.isoformat(),
            "weight": e.weight_lbs,
            "avg": round(avg, 1),
        })

    # Key lift progression
    key_lifts = [
        "Barbell Bench Press", "Barbell Back Squat", "Conventional Deadlift",
        "Barbell OHP", "Barbell Bent-Over Row", "Lat Pulldown",
    ]
    lifts = {}
    for name in key_lifts:
        logs = ExerciseLog.query.filter_by(exercise_name=name).order_by(ExerciseLog.logged_date).all()
        lifts[name] = [{"date": l.logged_date.isoformat(), "weight": l.weight, "week": l.week} for l in logs]

    # Waist measurements
    measurements = [{
        "date": e.log_date.isoformat(), "waist": e.waist_inches,
    } for e in BodyMeasurement.query.order_by(BodyMeasurement.log_date).all()]

    # Check-ins
    checkins = [{
        "week": e.week, "energy": e.energy_level, "sleep": e.sleep_quality,
        "soreness": e.soreness_level, "adherence": e.adherence_pct,
    } for e in WeeklyCheckIn.query.order_by(WeeklyCheckIn.week).all()]

    return jsonify({
        "bodyweight": bodyweight,
        "lifts": lifts,
        "measurements": measurements,
        "checkins": checkins,
    })


# ─── GARMIN ─────────────────────────────────────────────────────────────────

@app.route("/api/garmin/login", methods=["POST"])
def garmin_login():
    data = request.get_json()
    mfa_code = data.get("mfa_code") if data else None
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
    return jsonify(assess_readiness(summary))


@app.route("/api/garmin/hrv-trend")
def garmin_hrv_trend():
    if not garmin.connected:
        return jsonify({"error": "Not connected"}), 401
    return jsonify(garmin.get_weekly_hrv() or [])


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
