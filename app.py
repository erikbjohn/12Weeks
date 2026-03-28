"""Flask app for 12 Weeks Tracker with Garmin integration."""

import os
from datetime import date, timedelta, datetime
from flask import Flask, render_template, jsonify, request, session

from workout_data import (
    get_workouts, get_phase, PHASES, WARMUPS, SUPPLEMENTS,
    TRAVEL_WORKOUTS, TRAVEL_DAY_MAP,
)
from garmin_client import GarminClient
from overtraining import assess_readiness
from coach import get_coach_response
from psych_intake import get_intake_response, generate_intake_report
from models import (
    db, ExerciseLog, ExerciseCompletion, DayCompletion,
    MealLog, AppState, BodyWeight, BodyMeasurement,
    WeeklyCheckIn, SupplementLog, MorningCheckIn, ChatMessage,
    ProgressPhoto, PsychIntake, GarminTokens,
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
    # Drop and recreate psych_intake if it's missing the locked_until column
    from sqlalchemy import inspect as sa_inspect, text
    try:
        inspector = sa_inspect(db.engine)
        if "psych_intake" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("psych_intake")}
            if "locked_until" not in cols:
                db.session.execute(text("DROP TABLE psych_intake"))
                db.session.commit()
    except Exception:
        pass
    db.create_all()

garmin = GarminClient()

# Try to restore Garmin session from saved tokens
with app.app_context():
    garmin.try_restore_tokens()


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
        "traveling": s.traveling,
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
    if "traveling" in data:
        s.traveling = data["traveling"]
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


# ─── TRAVEL MODE ────────────────────────────────────────────────────────────

@app.route("/api/travel/workout")
def api_travel_workout():
    """Get bodyweight workout for a given day."""
    day = request.args.get("day", "Mon")
    workout_type = TRAVEL_DAY_MAP.get(day, "full")
    if workout_type is None or workout_type not in TRAVEL_WORKOUTS:
        return jsonify(None)
    return jsonify(TRAVEL_WORKOUTS[workout_type])


# ─── MORNING CHECK-IN ──────────────────────────────────────────────────────

@app.route("/api/morning-checkin")
def api_morning_checkin():
    d = request.args.get("date", date.today().isoformat())
    ci = MorningCheckIn.query.filter_by(log_date=date.fromisoformat(d)).first()
    if not ci:
        return jsonify({"exists": False})
    return jsonify({
        "exists": True,
        "date": ci.log_date.isoformat(),
        "sleep_quality": ci.sleep_quality,
        "stress_level": ci.stress_level,
        "soreness": ci.soreness,
        "mood": ci.mood,
        "motivation": ci.motivation,
        "anxiety": ci.anxiety,
        "notes": ci.notes,
    })


@app.route("/api/morning-checkin", methods=["POST"])
def api_morning_checkin_save():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    ci = MorningCheckIn.query.filter_by(log_date=d).first()
    if ci:
        ci.sleep_quality = data.get("sleep_quality", ci.sleep_quality)
        ci.stress_level = data.get("stress_level", ci.stress_level)
        ci.soreness = data.get("soreness", ci.soreness)
        ci.mood = data.get("mood", ci.mood)
        ci.motivation = data.get("motivation", ci.motivation)
        ci.anxiety = data.get("anxiety", ci.anxiety)
        ci.notes = data.get("notes", ci.notes)
    else:
        ci = MorningCheckIn(
            log_date=d,
            sleep_quality=data.get("sleep_quality"),
            stress_level=data.get("stress_level"),
            soreness=data.get("soreness"),
            mood=data.get("mood"),
            motivation=data.get("motivation"),
            anxiety=data.get("anxiety"),
            notes=data.get("notes"),
        )
        db.session.add(ci)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/morning-checkin/history")
def api_morning_checkin_history():
    days = request.args.get("days", 30, type=int)
    since = date.today() - timedelta(days=days)
    entries = MorningCheckIn.query.filter(
        MorningCheckIn.log_date >= since
    ).order_by(MorningCheckIn.log_date).all()
    return jsonify([{
        "date": e.log_date.isoformat(),
        "sleep_quality": e.sleep_quality,
        "stress_level": e.stress_level,
        "soreness": e.soreness,
        "mood": e.mood,
        "motivation": e.motivation,
        "anxiety": e.anxiety,
        "notes": e.notes,
    } for e in entries])


# ─── PSYCHOLOGICAL INTAKE ───────────────────────────────────────────────────

@app.route("/api/psych-intake/status")
def api_psych_intake_status():
    intake = PsychIntake.query.first()
    if not intake:
        return jsonify({"started": False, "completed": False, "has_report": False, "locked": False})
    locked = intake.locked_until and date.today() < intake.locked_until
    return jsonify({
        "started": True,
        "completed": intake.completed,
        "has_report": intake.report is not None,
        "message_count": len(intake.conversation or []),
        "locked": bool(locked),
        "locked_until": intake.locked_until.isoformat() if locked else None,
    })


@app.route("/api/psych-intake/conversation")
def api_psych_intake_conversation():
    intake = PsychIntake.query.first()
    if not intake:
        return jsonify({"conversation": [], "completed": False})
    return jsonify({
        "conversation": intake.conversation or [],
        "completed": intake.completed,
    })


@app.route("/api/psych-intake/message", methods=["POST"])
def api_psych_intake_message():
    data = request.get_json()
    user_msg = data.get("message", "").strip()

    intake = PsychIntake.query.first()
    if not intake:
        intake = PsychIntake(conversation=[], completed=False)
        db.session.add(intake)
        db.session.commit()

    # Check if locked out
    if intake.locked_until and date.today() < intake.locked_until:
        days_left = (intake.locked_until - date.today()).days
        return jsonify({
            "response": f"You're locked out for {days_left} more day{'s' if days_left != 1 else ''}. Come back when you've been alcohol-free for 7 days.",
            "completed": False,
            "locked": True,
            "locked_until": intake.locked_until.isoformat(),
        })

    # First message trigger - get Erik's opening without a fake user message
    is_first = not intake.conversation and not user_msg
    if is_first:
        user_msg = "[START]"

    if not user_msg:
        return jsonify({"error": "Message required"}), 400

    # Add user message to conversation (skip the [START] trigger)
    convo = list(intake.conversation or [])
    if not is_first:
        convo.append({"role": "user", "content": user_msg})

    # Get AI response
    response_text, is_complete = get_intake_response(user_msg, convo[:-1])

    # Check for lockout signal
    is_locked = "[INTAKE_LOCKED]" in response_text
    if is_locked:
        response_text = response_text.replace("[INTAKE_LOCKED]", "").strip()
        intake.locked_until = date.today() + timedelta(days=7)
        convo.append({"role": "assistant", "content": response_text})
        intake.conversation = convo
        db.session.commit()
        return jsonify({
            "response": response_text,
            "completed": False,
            "locked": True,
            "locked_until": intake.locked_until.isoformat(),
        })

    # Add assistant response
    convo.append({"role": "assistant", "content": response_text})
    intake.conversation = convo

    if is_complete:
        intake.completed = True
        # Generate the report with lifting data for combined plan
        lifting_data = _serialize_weights()
        report = generate_intake_report(convo, lifting_data=lifting_data)
        intake.report = report

    db.session.commit()

    return jsonify({
        "response": response_text,
        "completed": is_complete,
        "has_report": intake.report is not None,
    })


@app.route("/api/psych-intake/report")
def api_psych_intake_report():
    intake = PsychIntake.query.first()
    if not intake or not intake.report:
        return jsonify({"error": "No report available"}), 404
    return jsonify({"report": intake.report})


@app.route("/api/psych-intake/reset", methods=["POST"])
def api_psych_intake_reset():
    PsychIntake.query.delete()
    db.session.commit()
    return jsonify({"ok": True})


# ─── AI COACH CHAT ──────────────────────────────────────────────────────────

@app.route("/api/chat/history")
def api_chat_history():
    days = request.args.get("days", 7, type=int)
    since = date.today() - timedelta(days=days)
    messages = ChatMessage.query.filter(
        ChatMessage.log_date >= since
    ).order_by(ChatMessage.created_at).all()
    return jsonify([{
        "role": m.role,
        "content": m.content,
        "date": m.log_date.isoformat(),
        "time": m.created_at.strftime("%I:%M %p") if m.created_at else None,
    } for m in messages])


@app.route("/api/chat/clear", methods=["POST"])
def api_chat_clear():
    ChatMessage.query.delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Message required"}), 400

    # Save user message
    user_chat = ChatMessage(role="user", content=user_msg, log_date=date.today())
    db.session.add(user_chat)
    db.session.commit()

    # Build context for the AI coach
    context = _build_coach_context()

    # Get AI response
    response_text = get_coach_response(user_msg, context)

    # Save assistant message
    asst_chat = ChatMessage(role="assistant", content=response_text, log_date=date.today())
    db.session.add(asst_chat)
    db.session.commit()

    return jsonify({
        "response": response_text,
        "time": asst_chat.created_at.strftime("%I:%M %p") if asst_chat.created_at else None,
    })


def _build_coach_context():
    """Gather all relevant data for the AI coach."""
    # Recent morning check-ins
    since = date.today() - timedelta(days=14)
    checkins = [{
        "date": e.log_date.isoformat(),
        "sleep_quality": e.sleep_quality,
        "stress_level": e.stress_level,
        "soreness": e.soreness,
        "mood": e.mood,
        "motivation": e.motivation,
        "anxiety": e.anxiety,
        "notes": e.notes,
    } for e in MorningCheckIn.query.filter(
        MorningCheckIn.log_date >= since
    ).order_by(MorningCheckIn.log_date).all()]

    # Chat history
    chat_history = [{
        "role": m.role,
        "content": m.content,
    } for m in ChatMessage.query.filter(
        ChatMessage.log_date >= since
    ).order_by(ChatMessage.created_at).all()]

    # Body weight
    bw_entries = BodyWeight.query.order_by(BodyWeight.log_date).all()
    bodyweight = []
    for i, e in enumerate(bw_entries):
        window = bw_entries[max(0, i - 6):i + 1]
        avg = sum(w.weight_lbs for w in window) / len(window)
        bodyweight.append({
            "date": e.log_date.isoformat(),
            "weight": e.weight_lbs,
            "rolling_avg": round(avg, 1),
        })

    # Garmin data
    garmin_data = None
    readiness_data = None
    if garmin.connected:
        garmin_data = garmin.get_today_summary()
        readiness_data = assess_readiness(garmin_data)

    # Current state
    s = _get_state()
    week = s.current_week
    phase = get_phase(week)
    phase_info = PHASES[phase]

    # Today's workout
    workouts = get_workouts(week)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today_idx = date.today().weekday()  # 0=Mon
    workout_today = workouts[today_idx] if today_idx < len(workouts) else None

    # Supplements today
    supps = SupplementLog.query.filter_by(log_date=date.today()).all()
    supps_taken = {s.supplement_name: s.taken for s in supps}

    # Psych intake report (contains aspirational body type, goals, etc.)
    intake = PsychIntake.query.first()
    intake_report = intake.report if intake and intake.report else None

    return {
        "checkins": checkins,
        "chat_history": chat_history,
        "garmin": garmin_data,
        "readiness": readiness_data,
        "bodyweight": bodyweight[-14:],
        "workout_today": workout_today,
        "week": week,
        "phase": phase_info,
        "supplements_today": {"taken": supps_taken},
        "intake_report": intake_report,
    }


# ─── PROGRESS PHOTOS ────────────────────────────────────────────────────────

@app.route("/api/photos")
def api_photos():
    """Get all progress photos (metadata only, no image data)."""
    photos = ProgressPhoto.query.order_by(ProgressPhoto.log_date).all()
    return jsonify([{
        "id": p.id,
        "date": p.log_date.isoformat(),
        "pose": p.pose,
        "week": p.week,
        "analysis": p.analysis,
        "has_photo": True,
    } for p in photos])


@app.route("/api/photos/<int:photo_id>/image")
def api_photo_image(photo_id):
    """Get a specific photo's image data."""
    p = ProgressPhoto.query.get_or_404(photo_id)
    return jsonify({"photo_data": p.photo_data})


@app.route("/api/photos", methods=["POST"])
def api_photo_upload():
    """Upload a progress photo and get AI analysis."""
    data = request.get_json()
    photo_b64 = data.get("photo_data")
    pose = data.get("pose", "front")
    if not photo_b64:
        return jsonify({"error": "Photo data required"}), 400

    s = _get_state()
    week = s.current_week

    # Save photo
    photo = ProgressPhoto(
        log_date=date.today(),
        photo_data=photo_b64,
        pose=pose,
        week=week,
    )
    db.session.add(photo)
    db.session.commit()

    # Run AI analysis
    analysis = _analyze_progress_photo(photo_b64, pose, week)
    photo.analysis = analysis
    db.session.commit()

    return jsonify({
        "id": photo.id,
        "analysis": analysis,
        "week": week,
        "pose": pose,
    })


def _analyze_progress_photo(photo_b64, pose, current_week):
    """Use Claude vision to analyze a progress photo."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Photo saved. Add ANTHROPIC_API_KEY to enable AI analysis."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception:
        return "Photo saved. AI analysis unavailable."

    # Get previous photos for comparison
    prev_photos = ProgressPhoto.query.filter(
        ProgressPhoto.pose == pose,
        ProgressPhoto.log_date < date.today(),
    ).order_by(ProgressPhoto.log_date.desc()).limit(1).all()

    comparison_note = ""
    comparison_image = None
    if prev_photos:
        p = prev_photos[0]
        comparison_note = f"A previous {pose} photo from week {p.week} ({p.log_date.isoformat()}) is also provided for comparison."
        comparison_image = p.photo_data

    # Get body weight context
    bw = BodyWeight.query.order_by(BodyWeight.log_date.desc()).first()
    bw_note = f"Current body weight: {bw.weight_lbs} lb." if bw else ""

    # Get aspirational body type from psych intake
    aspiration_note = ""
    intake = PsychIntake.query.first()
    if intake and intake.conversation:
        convo_text = " ".join(m.get("content", "") for m in intake.conversation)
        # The aspirational reference is in the conversation - pass it to Claude to extract and use
        aspiration_note = f"\n\nIMPORTANT CONTEXT: During their intake, this person discussed their aspirational physique/celebrity reference. Here is the full intake conversation for context (search for celebrity/athlete mentions): {convo_text[:2000]}\n\nUse their aspirational reference to tailor your analysis. Compare their current physique to where they want to be. Suggest specific areas to focus on to move toward that goal physique. Be specific about what muscle groups need more work to achieve their ideal look."

    content = []
    content.append({
        "type": "text",
        "text": f"""Analyze this progress photo for a 12-week program (currently week {current_week}).
Pose: {pose} view. {bw_note} {comparison_note}{aspiration_note}

Please provide:
1. **Estimated body fat percentage** (give a range, e.g. 18-22%)
2. **Visible muscle groups** - which muscles are showing definition? Rate development.
3. **Areas of progress** - if a comparison photo is provided, what's changed?
4. **Goal physique gap** - based on their aspirational reference, what specific areas need the most work? What exercises should be emphasized?
5. **Aesthetic score** (1-10) - based on overall physique balance, symmetry, and conditioning
5. **Honest feedback** - what should they focus on? What's looking good?

Be direct and honest. This person wants real feedback, not flattery. They're using exercise for both physical and mental health."""
    })

    # Current photo
    media_type = "image/jpeg"
    if photo_b64.startswith("data:"):
        # Extract media type and clean base64
        parts = photo_b64.split(",", 1)
        if len(parts) == 2:
            media_type = parts[0].split(":")[1].split(";")[0]
            photo_b64_clean = parts[1]
        else:
            photo_b64_clean = photo_b64
    else:
        photo_b64_clean = photo_b64

    content.append({
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": photo_b64_clean},
    })

    # Comparison photo if available
    if comparison_image:
        comp_clean = comparison_image
        comp_media = "image/jpeg"
        if comparison_image.startswith("data:"):
            parts = comparison_image.split(",", 1)
            if len(parts) == 2:
                comp_media = parts[0].split(":")[1].split(";")[0]
                comp_clean = parts[1]

        content.append({
            "type": "text",
            "text": f"Previous photo (week {prev_photos[0].week}) for comparison:",
        })
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": comp_media, "data": comp_clean},
        })

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Photo saved. Analysis failed: {str(e)[:100]}"


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
