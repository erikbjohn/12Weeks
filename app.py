"""Flask app for 12 Weeks Tracker with Garmin integration."""

import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import date, timedelta, datetime, timezone
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, Response, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer

from workout_data import (
    get_workouts, get_phase, PHASES, WARMUPS, SUPPLEMENTS,
    TRAVEL_WORKOUTS, TRAVEL_DAY_MAP, EXERCISES,
)
from garmin_client import GarminClient
from overtraining import assess_readiness
from coach import get_coach_response, extract_memories
from psych_intake import get_intake_response, generate_intake_report, generate_full_profile
try:
    from training_engine import compute_next_targets, compute_muscle_strength, generate_session_analysis
except Exception:
    def compute_next_targets(uid, ex, w, d): return {"target_weight": None, "target_reps": 10, "target_sets": 4, "adjustment_reason": "", "progression_indicator": "hold"}
    def compute_muscle_strength(uid): pass
    def generate_session_analysis(uid, w, d): return None
from models import (
    db, User, Invite, ExerciseLog, ExerciseCompletion, ExerciseSwap, DayCompletion,
    MealLog, AppState, BodyWeight, BodyMeasurement,
    WeeklyCheckIn, SupplementLog, MorningCheckIn, ChatMessage,
    ProgressPhoto, PsychIntake, GarminTokens, PhysicalAssessment,
    UserConstraints, TrainingGoal, UserFoodSelections, WeeklyReport,
    UserEquipment, WarmupCompletion, RunLog, SetLog, CoachMemory, CoachRule,
    ComplianceState, MuscleGroupProfile, SessionAnalysis,
    DailyCoachState, WeeklyScheduleOverride, MealPlanOverride, RunOverride,
    Exercise, WeeklyPrescription, WeeklyMealPlan,
    WeeklyRunPlan, WeeklyWarmup, WeeklyDaySchedule,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# ─── MODEL CONSTANTS ──────────────────────────────────────────────────────
CLAUDE_OPUS = "claude-opus-4-20250514"
CLAUDE_SONNET = "claude-sonnet-4-20250514"


# CSRF token helper
def _generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = _generate_csrf_token

# Database
db_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({"error": "Login required"}), 401
    return redirect(url_for('login', next=request.url))

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # API key auth — allows CLI/curl access without browser session
        api_key = request.headers.get('X-Admin-Key') or request.args.get('admin_key')
        expected_key = os.environ.get('ADMIN_API_KEY')
        if api_key and expected_key and api_key == expected_key:
            return f(*args, **kwargs)
        # Fall back to session auth
        if not current_user or not current_user.is_authenticated:
            return jsonify({"error": "Login required"}), 401
        if not current_user.is_admin:
            return jsonify({"error": "Admin required"}), 403
        return f(*args, **kwargs)
    return decorated

def _determine_role(email):
    if email and email.lower().endswith("@placemetry.com"):
        return "admin"
    return "user"

def _safe_next_url(next_url):
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return next_url
    return '/'

from sqlalchemy import inspect as sa_inspect, text

with app.app_context():
    # Drop and recreate psych_intake if it's missing the locked_until column
    try:
        inspector = sa_inspect(db.engine)
        tables = inspector.get_table_names()
        # Drop and recreate tables missing critical columns
        for tbl, required_col in [("psych_intake", "locked_until"), ("physical_assessment", "chest_inches")]:
            if tbl in tables:
                cols = {c["name"] for c in inspector.get_columns(tbl)}
                if required_col not in cols:
                    db.session.execute(text(f"DROP TABLE {tbl}"))
                    db.session.commit()
    except Exception:
        pass
    try:
        db.create_all()
    except Exception as e:
        logging.error("[STARTUP] db.create_all() failed: %s", e)

    # Add missing columns to existing tables (db.create_all doesn't ALTER)
    _migrations = [
        ("physical_assessment", "stomach_inches", "FLOAT"),
        ("physical_assessment", "chest_inches", "FLOAT"),
        ("physical_assessment", "bicep_inches", "FLOAT"),
        ("physical_assessment", "thigh_inches", "FLOAT"),
        ("physical_assessment", "hips_inches", "FLOAT"),
        ("physical_assessment", "neck_inches", "FLOAT"),
        ("training_goal", "target_bf_pct", "FLOAT"),
        ("training_goal", "fasting_protocol", "VARCHAR(20)"),
        ("training_goal", "electrolyte_supplementation", "BOOLEAN"),
        ("training_goal", "weight_projection", "TEXT"),
        ("training_goal", "plan_accepted", "BOOLEAN"),
        ("exercise_log", "rpe_score", "INTEGER"),
        ("exercise_log", "reps_completed", "INTEGER"),
        ("exercise_log", "difficulty_notes", "TEXT"),
        ("training_goal", "baseline_assessment", "TEXT"),
        ("meal_log", "food_items", "TEXT"),
        ("meal_log", "scheduled_time", "TEXT"),
        ("meal_log", "actual_time", "TEXT"),
        ("set_log", "actual_time", "VARCHAR(30)"),
        ("day_completion", "completed_at", "VARCHAR(30)"),
        ("morning_checkin", "started_at", "VARCHAR(30)"),
        ("morning_checkin", "completed_at_time", "VARCHAR(30)"),
        ("morning_checkin", "missed", "BOOLEAN"),
        ("set_log", "target_weight", "FLOAT"),
        ("set_log", "target_reps", "INTEGER"),
        ("set_log", "target_rpe", "INTEGER"),
        ("set_log", "user_modified", "BOOLEAN"),
        ("set_log", "modification_direction", "VARCHAR(30)"),
        ("set_log", "set_skipped", "BOOLEAN"),
        ("set_log", "exercise_swapped", "BOOLEAN"),
        ("user", "timezone", "VARCHAR(64) DEFAULT 'UTC'"),
        ("chat_message", "message_type", "VARCHAR(30) DEFAULT 'chat'"),
        ("day_completion", "workout_started_at", "TEXT"),
        ("day_completion", "workout_ended_at", "TEXT"),
        ("day_completion", "workout_duration_min", "INTEGER"),
        ("weekly_prescription", "target_weight", "FLOAT"),
        ("weekly_prescription", "progression_indicator", "VARCHAR(20)"),
        ("weekly_prescription", "adjustment_reason", "TEXT"),
    ]
    try:
        inspector = sa_inspect(db.engine)
        for table, col, col_type in _migrations:
            if table in inspector.get_table_names():
                existing = {c["name"] for c in inspector.get_columns(table)}
                if col not in existing:
                    db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {col_type}'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Fix column types that are too small
    try:
        db.session.execute(text('ALTER TABLE "meal_log" ALTER COLUMN scheduled_time TYPE TEXT'))
        db.session.execute(text('ALTER TABLE "meal_log" ALTER COLUMN actual_time TYPE TEXT'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Add user_id to all existing tables
    _user_id_tables = [
        "exercise_log", "exercise_completion", "day_completion", "meal_log",
        "app_state", "body_weight", "body_measurement", "weekly_checkin",
        "supplement_log", "morning_checkin", "psych_intake", "garmin_tokens",
        "physical_assessment", "chat_message", "progress_photo",
        "user_constraints", "training_goal", "user_food_selections", "weekly_report",
        "user_equipment",
    ]
    try:
        for tbl in _user_id_tables:
            if tbl in inspector.get_table_names():
                existing = {c["name"] for c in inspector.get_columns(tbl)}
                if "user_id" not in existing:
                    db.session.execute(text(f'ALTER TABLE "{tbl}" ADD COLUMN user_id INTEGER REFERENCES "user"(id)'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Fix orphaned records with NULL user_id — assign to the first user
    try:
        _orphan_inspector = sa_inspect(db.engine)
        first_user = User.query.first()
        if first_user:
            _tables_with_user_id = []
            for tbl in _orphan_inspector.get_table_names():
                try:
                    cols = {c["name"] for c in _orphan_inspector.get_columns(tbl)}
                    if "user_id" in cols:
                        _tables_with_user_id.append(tbl)
                except Exception:
                    pass
            for tbl in _tables_with_user_id:
                try:
                    db.session.execute(text(
                        f'UPDATE "{tbl}" SET user_id = :uid WHERE user_id IS NULL'
                    ), {"uid": first_user.id})
                    db.session.commit()
                except Exception:
                    db.session.rollback()
    except Exception:
        db.session.rollback()

    # Ensure override tables exist (db.create_all handles creation above)
    for tbl in ["weekly_schedule_override", "meal_plan_override", "run_override"]:
        try:
            db.session.execute(text(f'SELECT 1 FROM "{tbl}" LIMIT 1'))
        except Exception:
            db.session.rollback()
            # Table will be created by db.create_all() above

    # actual_bmr column on physical_assessment
    try:
        db.session.execute(text('SELECT actual_bmr FROM physical_assessment LIMIT 1'))
    except Exception:
        db.session.rollback()
        try:
            db.session.execute(text('ALTER TABLE physical_assessment ADD COLUMN actual_bmr FLOAT'))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # New BodyMeasurement columns (chest, biceps, thighs, hips, neck)
    for col in ['weight_lbs', 'chest', 'bicep_left', 'bicep_right', 'thigh_left', 'thigh_right', 'hips', 'neck']:
        try:
            db.session.execute(text(f'SELECT {col} FROM body_measurement LIMIT 1'))
        except Exception:
            db.session.rollback()
            try:
                db.session.execute(text(f'ALTER TABLE body_measurement ADD COLUMN {col} FLOAT'))
                db.session.commit()
            except Exception:
                db.session.rollback()

    # SetLog columns (target_weight, target_reps, modification_direction if missing)
    for col, col_type in [('target_weight', 'FLOAT'), ('target_reps', 'INTEGER'), ('modification_direction', 'VARCHAR(30)'), ('user_modified', 'BOOLEAN'), ('exercise_swapped', 'BOOLEAN')]:
        try:
            db.session.execute(text(f'SELECT {col} FROM set_log LIMIT 1'))
        except Exception:
            db.session.rollback()
            try:
                db.session.execute(text(f'ALTER TABLE set_log ADD COLUMN {col} {col_type}'))
                db.session.commit()
            except Exception:
                db.session.rollback()

    # MealPlanOverride daily_calories column
    try:
        db.session.execute(text('SELECT daily_calories FROM meal_plan_override LIMIT 1'))
    except Exception:
        db.session.rollback()
        try:
            db.session.execute(text('ALTER TABLE meal_plan_override ADD COLUMN daily_calories INTEGER'))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # WeeklyMealPlan new columns (daily_calories, daily_protein, day_type, source)
    for col, col_type in [('daily_calories', 'INTEGER'), ('daily_protein', 'INTEGER'), ('day_type', 'VARCHAR(20)'), ('source', "VARCHAR(20) DEFAULT 'generator'")]:
        try:
            db.session.execute(text(f'SELECT {col} FROM weekly_meal_plan LIMIT 1'))
        except Exception:
            db.session.rollback()
            try:
                db.session.execute(text(f'ALTER TABLE weekly_meal_plan ADD COLUMN {col} {col_type}'))
                db.session.commit()
            except Exception:
                db.session.rollback()

    # Ensure new dynamic tables exist (db.create_all handles creation above)
    for tbl in ["weekly_run_plan", "weekly_warmup", "weekly_day_schedule"]:
        try:
            db.session.execute(text(f'SELECT 1 FROM "{tbl}" LIMIT 1'))
        except Exception:
            db.session.rollback()
            # Table will be created by db.create_all() above

    # Seed muscle group profiles
    try:
        _erik = User.query.filter_by(email="erikbjohn@gmail.com").first()
        if _erik:
            _shoulders = MuscleGroupProfile.query.filter_by(user_id=_erik.id, muscle_group='shoulders').first()
            if not _shoulders:
                db.session.add(MuscleGroupProfile(
                    user_id=_erik.id, muscle_group='shoulders',
                    strength_score=0.8, relative_strength='weak',
                    user_flagged_weak=True
                ))
                db.session.commit()
    except Exception:
        db.session.rollback()

    # Seed Exercise catalog from workout_data (idempotent)
    try:
        from workout_data import EXERCISES
        existing_count = Exercise.query.count()
        if existing_count < len(EXERCISES):
            for name, data in EXERCISES.items():
                if not Exercise.query.filter_by(name=name).first():
                    db.session.add(Exercise(
                        name=name,
                        muscle_group=data.get('muscle_group'),
                        category=data.get('category'),
                        equipment=data.get('equipment', []),
                        video_cue=data.get('video'),
                    ))
            db.session.commit()
    except Exception:
        db.session.rollback()

    # ONE-TIME: Canonicalize exercise names in set_log and exercise_log
    try:
        from workout_data import NAME_ALIASES
        for old_name, canonical in NAME_ALIASES.items():
            if old_name != canonical:
                db.session.execute(text(
                    'UPDATE set_log SET exercise_name = :new WHERE exercise_name = :old'
                ), {"new": canonical, "old": old_name})
                db.session.execute(text(
                    'UPDATE exercise_log SET exercise_name = :new WHERE exercise_name = :old'
                ), {"new": canonical, "old": old_name})
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Seed WeeklyPrescription for existing users who don't have any
    try:
        from workout_data import PHASE_TEMPLATES, get_phase
        users_with_state = db.session.query(AppState).filter(AppState.start_date.isnot(None)).all()
        for state in users_with_state:
            existing = WeeklyPrescription.query.filter_by(user_id=state.user_id, week=1).first()
            if not existing:
                phase = get_phase(1)
                template = PHASE_TEMPLATES.get(phase, PHASE_TEMPLATES.get(1, {}))
                for day_idx in range(7):
                    for order, ex in enumerate(template.get(day_idx, [])):
                        db.session.add(WeeklyPrescription(
                            user_id=state.user_id,
                            week=1,
                            day_idx=day_idx,
                            exercise_order=order,
                            exercise_name=ex['exercise'],
                            sets=ex['sets'],
                            reps=ex['reps'],
                            rest=ex.get('rest', '60s'),
                            note=ex.get('note', ''),
                            source='template',
                        ))
                db.session.commit()
    except Exception:
        db.session.rollback()

    # ONE-TIME: Backfill target_weight for existing prescriptions
    try:
        from training_engine import compute_next_targets
        rx_null = WeeklyPrescription.query.filter(
            WeeklyPrescription.target_weight == None
        ).all()
        if rx_null:
            filled = 0
            for rx in rx_null:
                try:
                    targets = compute_next_targets(rx.user_id, rx.exercise_name, rx.week, rx.day_idx)
                    if targets.get('target_weight'):
                        rx.target_weight = targets['target_weight']
                        filled += 1
                except Exception:
                    pass
            if filled:
                db.session.commit()
                logging.info("[migration] Backfilled %d prescription target_weights", filled)
    except Exception as e:
        logging.warning("[migration] target_weight backfill skipped: %s", e)

    # PRE-START COACH EMAIL: Send day before start date
    try:
        tomorrow = date.today() + timedelta(days=1)
        _prestart_users = db.session.query(User, AppState).join(
            AppState, AppState.user_id == User.id
        ).filter(AppState.start_date == tomorrow).all()
        for _user, _state in _prestart_users:
            # Check if already sent (look for marker in ChatMessage)
            _already_sent = ChatMessage.query.filter_by(
                user_id=_user.id, role="system", content="[PRESTART_EMAIL_SENT]"
            ).first()
            if not _already_sent:
                _send_prestart_email(_user)
    except Exception:
        pass


def _send_prestart_email(user):
    """Send a personalized pre-start email from Coach Erik the day before Day 1."""
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return

    # Get their intake report for personalization
    intake = PsychIntake.query.filter_by(user_id=user.id).first()
    report = intake.report if intake and intake.report else "No intake report available."

    # Generate personalized email body via Claude
    email_body = _generate_prestart_email_body(user.name or "Athlete", report)

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@12weeks.app")
        msg = Mail(
            from_email=from_email,
            to_emails=user.email,
            subject="Tomorrow. Day 1. — Coach Erik",
            html_content=email_body,
        )
        sg = SendGridAPIClient(api_key)
        sg.send(msg)

        # Mark as sent
        db.session.add(ChatMessage(
            role="system", content="[PRESTART_EMAIL_SENT]",
            log_date=date.today(), user_id=user.id,
        ))
        db.session.commit()
    except Exception:
        pass


def _generate_prestart_email_body(name, intake_report):
    """Generate the pre-start email using Claude in Coach Erik's voice."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        # Fallback static email
        return f"""<div style="background:#0d0f0e;color:#e8ede9;padding:2rem;font-family:sans-serif;max-width:500px;margin:0 auto">
        <div style="color:#4ade80;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:1rem">COACH ERIK</div>
        <h2 style="color:#e8ede9;margin-bottom:1rem">{name}. Tomorrow.</h2>
        <p style="line-height:1.6">Tomorrow is Day 1. You signed up for a reason. Don't forget it.</p>
        <p style="line-height:1.6">6am. Warm-up by 6:05. Lifting by 6:15. No negotiation.</p>
        <p style="line-height:1.6">I'll be there. You show up.</p>
        <p style="color:#4ade80;margin-top:2rem">— Erik</p>
        </div>"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key, timeout=15.0)
        response = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=300,
            system="""You are Coach Erik. Write a brief, powerful pre-start email for an athlete whose program begins TOMORROW.
Lombardi voice — direct, no fluff, no warmth. State facts. Set expectations.
Include: why they signed up (from their intake report), what Day 1 looks like, that you hold them accountable, no excuses.
Output HTML with inline styles. Dark background (#0d0f0e), light text (#e8ede9), green accent (#4ade80).
Keep it SHORT — 4-5 sentences max. Sign it "— Erik".""",
            messages=[{"role": "user", "content": f"Athlete name: {name}\n\nIntake report:\n{intake_report[:500]}"}],
        )
        return response.content[0].text
    except Exception:
        return f"""<div style="background:#0d0f0e;color:#e8ede9;padding:2rem;font-family:sans-serif;max-width:500px;margin:0 auto">
        <div style="color:#4ade80;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:1rem">COACH ERIK</div>
        <h2>{name}. Tomorrow.</h2>
        <p style="line-height:1.6">Tomorrow is Day 1. Show up. 6am.</p>
        <p style="color:#4ade80;margin-top:2rem">— Erik</p>
        </div>"""


# Validate exercise swap data on startup
try:
    from equipment_swaps import validate_exercise_swaps
    _missing_alts = validate_exercise_swaps()
    if _missing_alts:
        import logging
        logging.warning(f"Exercises with <2 alternatives: {_missing_alts}")
except Exception:
    pass

def _parse_coach_markers(text, user_id, week):
    """Parse structured markers from coach response and apply them."""
    import re
    # [SWAP: day_idx=N, exercise_idx=N, old=Name, new=Name, reason=text]
    # (CORE_PROMPT format — see coach_assembler.py CORE_PROMPT <markers>)
    for m in re.finditer(
        r'\[SWAP:\s*day_idx=(\d+),\s*exercise_idx=(\d+),\s*old=([^,]+),\s*new=([^,]+),\s*reason=([^\]]+)\]',
        text,
    ):
        try:
            day_idx = int(m.group(1))
            exercise_idx = int(m.group(2))
            new_name = m.group(4).strip()
            existing = ExerciseSwap.query.filter_by(
                user_id=user_id, week=week, day_idx=day_idx, exercise_idx=exercise_idx
            ).first()
            if existing:
                existing.swapped_to = new_name
            else:
                db.session.add(ExerciseSwap(
                    user_id=user_id, week=week, day_idx=day_idx,
                    exercise_idx=exercise_idx, swapped_to=new_name,
                ))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [SCHEDULE: day=X, time=3:00 PM, notes=...]
    for m in re.finditer(r'\[SCHEDULE:\s*day=(\d+),\s*time=([^,]+)(?:,\s*notes=([^\]]+))?\]', text):
        try:
            day_idx, workout_time = int(m.group(1)), m.group(2).strip()
            notes = m.group(3).strip() if m.group(3) else ''
            existing = WeeklyScheduleOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if existing:
                existing.workout_time = workout_time
                existing.notes = notes
            else:
                db.session.add(WeeklyScheduleOverride(user_id=user_id, week=week, day_idx=day_idx, workout_time=workout_time, notes=notes))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [NUTRITION: day=X, meal_type=fast_day, reason=...]
    for m in re.finditer(r'\[NUTRITION:\s*day=(\d+),\s*meal_type=([^,]+),\s*reason=([^\]]+)\]', text):
        try:
            day_idx, meal_type, reason = int(m.group(1)), m.group(2).strip(), m.group(3).strip()
            existing = MealPlanOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if existing:
                existing.meal_type = meal_type
                existing.reason = reason
            else:
                db.session.add(MealPlanOverride(user_id=user_id, week=week, day_idx=day_idx, meal_type=meal_type, reason=reason))
            # If it's a fast day, also skip the workout for that day
            if meal_type == 'fast_day':
                sched = WeeklyScheduleOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
                if sched:
                    sched.skip_day = True
                    sched.notes = 'Fast day \u2014 no workout'
                else:
                    db.session.add(WeeklyScheduleOverride(user_id=user_id, week=week, day_idx=day_idx, skip_day=True, notes='Fast day \u2014 no workout'))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [NUTRITION: daily_calories=XXXX, reason=...]
    for m in re.finditer(r'\[NUTRITION:\s*daily_calories=(\d+),\s*reason=([^\]]+)\]', text):
        try:
            new_cals = int(m.group(1))
            goal = TrainingGoal.query.filter_by(user_id=user_id).first()
            if goal:
                goal.daily_calories = new_cals
                db.session.commit()
        except Exception:
            db.session.rollback()

    # [WEIGHT: exercise=Name, adjustment=+5, reason=...]
    for m in re.finditer(r'\[WEIGHT:\s*exercise=([^,]+),\s*adjustment=([+-]?\d+),\s*reason=([^\]]+)\]', text):
        try:
            exercise, adj, reason = m.group(1).strip(), int(m.group(2)), m.group(3).strip()
            last_log = ExerciseLog.query.filter_by(user_id=user_id, exercise_name=exercise).order_by(ExerciseLog.logged_date.desc()).first()
            base_weight = last_log.weight if last_log else 0
            new_weight = base_weight + adj
            log = ExerciseLog(user_id=user_id, exercise_name=exercise, weight=new_weight, week=week, day_idx=0, rpe=None, logged_date=_user_today())
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [RUN: day=X, duration=50 min, type=zone2, reason=...]
    for m in re.finditer(r'\[RUN:\s*day=(\d+),\s*duration=([^,]+),\s*type=([^,]+),\s*reason=([^\]]+)\]', text):
        try:
            day_idx, duration, run_type, reason = int(m.group(1)), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()
            existing = RunOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if existing:
                existing.duration = duration
                existing.run_type = run_type
                existing.reason = reason
            else:
                db.session.add(RunOverride(user_id=user_id, week=week, day_idx=day_idx, duration=duration, run_type=run_type, reason=reason))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [BMR_UPDATE: new_bmr=XXXX, reason=...]
    for m in re.finditer(r'\[BMR_UPDATE:\s*new_bmr=(\d+),\s*reason=([^\]]+)\]', text):
        try:
            new_bmr = int(m.group(1))
            if 1000 <= new_bmr <= 3000:  # Sanity check
                pa = PhysicalAssessment.query.filter_by(user_id=user_id).first()
                if pa:
                    pa.actual_bmr = new_bmr
                    db.session.commit()
        except Exception:
            db.session.rollback()

    # [LOCKOUT_WARNING: count=X, reason=...]
    for m in re.finditer(r'\[LOCKOUT_WARNING:\s*count=([^,]+),\s*reason=([^\]]+)\]', text):
        try:
            count, reason = m.group(1).strip(), m.group(2).strip()
            cm = CoachMemory(user_id=user_id, memory_type='lockout_warning', content=f'Warning {count}: {reason}', week=week)
            db.session.add(cm)
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [PRESCRIPTION: week=X, day=Y, exercise=Name, sets=4, reps=10, rest=60-90s, weight=110]
    for m in re.finditer(r'\[PRESCRIPTION:\s*week=(\d+),\s*day=(\d+),\s*exercise=([^,]+),\s*sets=(\d+),\s*reps=([^,]+?)(?:,\s*rest=([^\],]+?))?(?:,\s*weight=([^\]]+))?\]', text):
        try:
            p_week, p_day, p_exercise = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            p_sets, p_reps = int(m.group(4)), m.group(5).strip()
            p_rest = m.group(6).strip() if m.group(6) else '60s'
            p_weight = float(m.group(7)) if m.group(7) else None
            from workout_data import resolve_name
            p_exercise = resolve_name(p_exercise)
            # Upsert
            existing = WeeklyPrescription.query.filter_by(
                user_id=user_id, week=p_week, day_idx=p_day, exercise_name=p_exercise
            ).first()
            if existing:
                existing.sets = p_sets
                existing.reps = p_reps
                existing.rest = p_rest
                existing.source = 'coach'
                if p_weight is not None:
                    existing.target_weight = p_weight
            else:
                # Find max exercise_order for this day
                max_order = db.session.query(db.func.max(WeeklyPrescription.exercise_order)).filter_by(
                    user_id=user_id, week=p_week, day_idx=p_day
                ).scalar() or -1
                db.session.add(WeeklyPrescription(
                    user_id=user_id, week=p_week, day_idx=p_day,
                    exercise_order=max_order + 1, exercise_name=p_exercise,
                    sets=p_sets, reps=p_reps, rest=p_rest, source='coach',
                    target_weight=p_weight,
                ))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [DAY_SCHEDULE: day=X, lift_name=Upper A - Chest & Back, muscle_groups=chest,back,triceps, is_rest=false]
    for m in re.finditer(r'\[DAY_SCHEDULE:\s*day=(\d+),\s*lift_name=([^,]+)(?:,\s*muscle_groups=([^,\]]+))?(?:,\s*is_rest=(true|false))?\]', text):
        try:
            day_idx = int(m.group(1))
            lift_name = m.group(2).strip()
            muscle_groups = [g.strip() for g in m.group(3).split(',')] if m.group(3) else []
            is_rest = m.group(4) == 'true' if m.group(4) else False
            existing = WeeklyDaySchedule.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if existing:
                existing.lift_name = lift_name
                existing.muscle_groups = muscle_groups
                existing.is_rest = is_rest
                existing.source = 'coach'
            else:
                db.session.add(WeeklyDaySchedule(user_id=user_id, week=week, day_idx=day_idx, lift_name=lift_name, muscle_groups=muscle_groups, is_rest=is_rest, source='coach'))
            db.session.commit()
        except Exception:
            db.session.rollback()


# Per-user Garmin clients (keyed by user_id)
_garmin_clients = {}


def _get_garmin(user_id=None):
    """Get or create a Garmin client for the current user."""
    uid = user_id or (current_user.id if current_user and current_user.is_authenticated else None)
    if not uid:
        return GarminClient()
    if uid not in _garmin_clients:
        client = GarminClient(user_id=uid)
        _garmin_clients[uid] = client
    return _garmin_clients[uid]


def _extract_age_from_intake(user_id):
    """Extract age from psych intake conversation. Returns 30 as default."""
    import re as _re
    age = 30
    try:
        intake = PsychIntake.query.filter_by(user_id=user_id).first()
        if intake and intake.conversation:
            for msg in intake.conversation:
                content = msg.get("content", "").lower().strip()
                if msg.get("role") == "user":
                    age_match = _re.search(r'\b(\d{1,2})\b', content)
                    if age_match:
                        num = int(age_match.group(1))
                        if 13 <= num <= 80:
                            age = num
    except Exception:
        pass
    return age


def _user_today():
    """Get today's date in the current user's local timezone (not server UTC)."""
    try:
        tz = current_user.timezone if hasattr(current_user, 'timezone') and current_user.timezone else 'UTC'
        from utils_time import user_local_now
        return user_local_now(tz).date()
    except Exception:
        return date.today()

def _current_week():
    """Compute current program week from start_date (not stale DB value)."""
    try:
        s = _get_state()
        if s.start_date:
            diff_days = (_user_today() - s.start_date).days
            return min(12, max(1, diff_days // 7 + 1))
        return s.current_week or 1
    except Exception:
        return 1

def _user_now():
    """Get current datetime in the current user's local timezone."""
    try:
        tz = current_user.timezone if hasattr(current_user, 'timezone') and current_user.timezone else 'UTC'
        from utils_time import user_local_now
        return user_local_now(tz)
    except Exception:
        return datetime.now()

def _get_day_meal_type(user_id, week, day_idx):
    """Get actual meal type for a day — DB first, template fallback."""
    try:
        override = MealPlanOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if override and override.meal_type:
            return override.meal_type
        wmp = WeeklyMealPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if wmp and wmp.day_type:
            return wmp.day_type
    except Exception:
        pass
    from workout_data import DAY_MEAL_TYPES
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return DAY_MEAL_TYPES.get(day_names[day_idx] if day_idx < 7 else "Mon", "moderate")


def _generate_run_plan(user_id, week, day_idx, template_run):
    """Progress run based on week number. Returns dict with type/label/time/detail."""
    base_type = template_run.get('type', 'z2')
    base_time = template_run.get('time', '30 min')
    match = re.search(r'\d+', base_time)
    base_minutes = int(match.group()) if match else 30

    if week <= 1:
        return template_run  # Week 1: use template as-is

    # Progression rules by run type
    weeks_completed = week - 1
    if base_type in ('z2', 'long'):
        extra = weeks_completed * 5
        cap = 90 if base_type == 'long' else 60
        new_minutes = min(base_minutes + extra, cap)
    elif base_type == 'tempo':
        extra = (weeks_completed // 2) * 5
        new_minutes = min(base_minutes + extra, 45)
    elif base_type == 'hiit':
        extra = (weeks_completed // 2) * 2
        new_minutes = min(base_minutes + extra, 35)
    else:
        new_minutes = base_minutes

    return {
        'type': base_type,
        'label': template_run.get('label', 'Run'),
        'time': f"{new_minutes} min" if base_type != 'min' else base_time,
        'detail': template_run.get('detail', ''),
    }


def _generate_warmup(day_exercises, muscle_groups, soreness_data=None):
    """Build a warmup that matches today's exercises and addresses soreness."""
    steps = []

    # 1. General mobility (always)
    steps.append({"name": "Arm circles", "reps": "15 each direction", "note": "Forward then backward"})

    # 2. Target muscle activation based on today's muscle groups
    MUSCLE_WARMUPS = {
        "chest": [
            {"name": "Band pull-aparts", "reps": "20", "note": "Light band"},
            {"name": "Push-up to downward dog", "reps": "8", "note": "Slow and controlled"},
        ],
        "back": [
            {"name": "Band pull-aparts", "reps": "20", "note": "Light band"},
            {"name": "Cat-cow stretch", "reps": "8", "note": "Breathe deep"},
        ],
        "quads": [
            {"name": "Bodyweight squats", "reps": "15", "note": "Full depth"},
            {"name": "Walking lunges", "reps": "8 each leg", "note": ""},
        ],
        "hamstrings": [
            {"name": "Leg swings (front-back)", "reps": "10 each leg", "note": ""},
            {"name": "Glute bridges", "reps": "15", "note": "Squeeze at top"},
        ],
        "shoulders": [
            {"name": "Band dislocates", "reps": "10", "note": "Slow"},
            {"name": "Lateral raises (light)", "reps": "10", "note": "Very light weight"},
        ],
        "glutes": [
            {"name": "Hip circles", "reps": "8 each direction", "note": ""},
            {"name": "Glute bridges", "reps": "15", "note": ""},
        ],
    }

    seen = set()
    for mg in muscle_groups:
        for step in MUSCLE_WARMUPS.get(mg, []):
            if step["name"] not in seen:
                steps.append(step)
                seen.add(step["name"])

    # 3. Soreness-specific stretches (static holds — keep hold time in note)
    if soreness_data:
        sore_area = soreness_data.get("area", "").lower()
        SORENESS_STRETCHES = {
            "shoulders": {"name": "Shoulder cross-body stretch", "reps": "Hold 15s each side", "note": "Gentle, don't force"},
            "lower back": {"name": "Child's pose", "reps": "Hold 45s", "note": "Breathe deep, relax into it"},
            "quads": {"name": "Standing quad stretch", "reps": "Hold 15s each leg", "note": "Hold wall for balance"},
            "hamstrings": {"name": "Standing hamstring stretch", "reps": "Hold 15s each leg", "note": "Slight bend"},
            "chest": {"name": "Doorway chest stretch", "reps": "Hold 15s each side", "note": ""},
        }
        if sore_area in SORENESS_STRETCHES:
            s = SORENESS_STRETCHES[sore_area]
            if s["name"] not in seen:
                steps.append(s)

    # 4. Movement prep with empty bar (if lifting day)
    bar_exercises = [e for e in day_exercises if "barbell" in e.get("exercise", "").lower() or "bench" in e.get("exercise", "").lower()]
    if bar_exercises:
        first_bar = bar_exercises[0]["exercise"]
        steps.append({"name": f"Empty bar {first_bar.split()[-1].lower()}", "reps": "15", "note": "Feel the groove"})

    return {
        "label": "Dynamic Warm-Up",
        "time": f"{max(5, len(steps) * 1)} min",
        "steps": steps[:8],  # Cap at 8 steps
    }


# ─── DIAGNOSTIC ───────────────────────────────────────────────────────────

@app.route("/api/debug/health")
def debug_health():
    """Quick health check — returns status of key tables."""
    results = {}
    try:
        from sqlalchemy import text as _t
        for tbl in ['user', 'psych_intake', 'physical_assessment', 'training_goal', 'app_state', 'weekly_prescription', 'exercise_log']:
            try:
                row = db.session.execute(_t(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
                results[tbl] = row
            except Exception as e:
                results[tbl] = f"ERROR: {str(e)[:80]}"
                db.session.rollback()

    except Exception as e:
        results["_fatal"] = str(e)[:200]
    return jsonify(results)


@app.route("/api/meals/regenerate", methods=["POST"])
@login_required
def api_regenerate_meals():
    """Regenerate meal plans for a week using current goal calories. Does NOT touch exercises."""
    try:
        from meal_generator import generate_meal_plan
        from goal_engine import compute_day_calories
        from workout_data import MEAL_PLANS

        data = request.get_json() or {}
        target_week = data.get("week", _current_week())

        goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
        bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
        fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()

        if not goal:
            return jsonify({"error": "No goal computed yet"}), 400
        if not fs or not fs.selected_foods:
            return jsonify({"error": "No food selections"}), 400

        current_weight = bw.weight_lbs if bw else 200
        base_calories = goal.daily_calories
        fasting_protocol = goal.fasting_protocol or "16_8"

        _cal_day_type_map = {
            "heavy_lift": "heavy", "long_run": "long_run",
            "moderate": "training", "fast_day": "rest",
        }
        day_types = [_get_day_meal_type(current_user.id, target_week, d) for d in range(7)]

        # Delete ALL meal plans for today+future (including coach-modified ones)
        WeeklyMealPlan.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(
            WeeklyMealPlan.day_idx >= _user_today().weekday()
        ).delete()

        # Only regenerate today and future days
        week_monday = _user_today() - timedelta(days=_user_today().weekday())
        meal_summary = []
        for day_idx in range(7):
            day_date = week_monday + timedelta(days=day_idx)
            if day_date < _user_today():
                continue  # Skip past days — don't overwrite eaten meals
            day_type = day_types[day_idx]
            if day_type == 'fast_day':
                meal_plan = MEAL_PLANS.get('fast_day', {})
            else:
                cal_day_type = _cal_day_type_map.get(day_type, "training")
                day_macros = compute_day_calories(base_calories, goal.goal_type or 'cut', cal_day_type, current_weight)
                meal_plan = generate_meal_plan(
                    selected_foods=fs.selected_foods, day_type=day_type,
                    targets=day_macros, fasting_protocol=fasting_protocol,
                )

            db.session.add(WeeklyMealPlan(
                user_id=current_user.id, week=target_week, day_idx=day_idx,
                meal_data=meal_plan,
                daily_calories=meal_plan.get('targetCal', 0),
                daily_protein=meal_plan.get('targetProtein', 0),
                day_type=day_type, source='generator',
            ))
            meal_summary.append({"day": day_idx, "type": day_type, "calories": meal_plan.get('targetCal', 0)})

        db.session.commit()
        return jsonify({"ok": True, "meals": meal_summary, "daily_calories": base_calories})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug/workouts-error")
@login_required
def debug_workouts_error():
    """Call api_workouts and return the error if it crashes."""
    try:
        return api_workouts()
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()[-1000:]}), 500


@app.route("/api/debug/goal-error", methods=["POST"])
@login_required
def debug_goal_error():
    """Call api_goal_compute and return the error if it crashes."""
    try:
        return api_goal_compute()
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()[-1000:]}), 500


# ─── AUTH ──────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/")

    if request.method == "POST":
        if request.form.get('csrf_token') != session.get('_csrf_token'):
            flash("Invalid request. Please try again.", "error")
            return redirect(url_for("login"))

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not user.password_hash:
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        if not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        if not user.email_verified:
            flash("Check your email for a verification link.", "error")
            return render_template("login.html")

        user.last_login_at = datetime.now(timezone.utc)
        # Save timezone from browser
        tz = request.form.get('timezone')
        if tz:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz)
                user.timezone = tz
            except Exception:
                pass
        db.session.commit()
        login_user(user, remember=True)
        return redirect(_safe_next_url(request.args.get("next")))

    return render_template("login.html")


@app.route("/signup", methods=["POST"])
def signup():
    if request.form.get('csrf_token') != session.get('_csrf_token'):
        flash("Invalid request. Please try again.", "error")
        return redirect(url_for("login", mode="signup"))

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()
    invite_code = request.form.get("invite_code", "").strip() or session.pop("invite_code", "")

    if not email or not password:
        flash("Email and password required.", "error")
        return redirect(url_for("login", mode="signup"))
    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(url_for("login", mode="signup"))
    if User.query.filter_by(email=email).first():
        flash("Email already registered.", "error")
        return redirect(url_for("login", mode="signup"))

    role = _determine_role(email)

    # Require invite for non-admins
    invite = None
    if role != "admin":
        if not invite_code:
            flash("Invite code required.", "error")
            return redirect(url_for("login", mode="signup"))
        invite = Invite.query.filter_by(code=invite_code, used_by=None).first()
        if not invite and not Invite.query.filter_by(code=invite_code, multi_use=True).first():
            flash("Invalid or used invite code.", "error")
            return redirect(url_for("login", mode="signup"))
        if not invite:
            invite = Invite.query.filter_by(code=invite_code, multi_use=True).first()

    user = User(
        email=email,
        name=name or email.split("@")[0],
        password_hash=generate_password_hash(password),
        role=role,
        email_verified=False,
        invites_remaining=3,
        invited_by=invite.created_by if invite else None,
    )
    db.session.add(user)
    db.session.commit()

    # Redeem invite
    if invite and not invite.multi_use:
        invite.used_by = user.id
        invite.used_at = datetime.now(timezone.utc)
        db.session.commit()

    # Send verification email
    _send_verification_email(user)

    flash("Account created! Check your email for a verification link.", "success")
    return redirect(url_for("login"))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/verify/<token>")
def verify_email(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        data = s.loads(token, salt="email-verify", max_age=86400)
        user = User.query.get(data.get("user_id"))
        if user:
            user.email_verified = True
            db.session.commit()
            flash("Email verified! You can now log in.", "success")
    except Exception:
        flash("Invalid or expired verification link.", "error")
    return redirect(url_for("login"))


_invite_attempts = {}  # IP -> (count, timestamp)


@app.route("/invite/<code>")
def accept_invite(code):
    ip = request.remote_addr
    now = time.time()
    attempts = _invite_attempts.get(ip, (0, 0))
    if attempts[0] >= 10 and now - attempts[1] < 300:
        flash("Too many attempts. Try again in 5 minutes.", "error")
        return redirect(url_for("login"))
    _invite_attempts[ip] = (attempts[0] + 1, now)

    invite = Invite.query.filter_by(code=code).first()
    if not invite:
        flash("Invalid invite link.", "error")
        return redirect(url_for("login"))
    if invite.used_by and not invite.multi_use:
        flash("This invite has already been used.", "error")
        return redirect(url_for("login"))
    session["invite_code"] = code
    flash("You've been invited! Create your account.", "success")
    return redirect(url_for("login", mode="signup"))


@app.route("/api/invite", methods=["POST"])
@login_required
def api_create_invite():
    data = request.get_json()
    email = data.get("email", "").strip().lower() if data else ""

    if not current_user.is_admin:
        if current_user.invites_remaining <= 0:
            return jsonify({"error": "No invites remaining"}), 400
        current_user.invites_remaining -= 1

    code = secrets.token_urlsafe(32)
    invite = Invite(code=code, created_by=current_user.id, email_sent_to=email or None)
    db.session.add(invite)
    db.session.commit()

    app_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    invite_url = f"{app_url}/invite/{code}"

    email_sent = False
    if email:
        email_sent = _send_invite_email(current_user.name or current_user.email, email, invite_url)

    return jsonify({
        "invite_url": invite_url,
        "remaining": current_user.invites_remaining if not current_user.is_admin else -1,
        "email_sent": email_sent,
        "is_admin": current_user.is_admin,
    })


@app.route("/api/request-invite", methods=["POST"])
def api_request_invite():
    data = request.get_json()
    name = data.get("name", "")
    email = data.get("email", "")
    if not email:
        return jsonify({"error": "Email required"}), 400
    # Email admin about the request
    _send_invite_request_email(name, email)
    return jsonify({"success": True})


@app.route("/api/invite-status")
@login_required
def api_invite_status():
    return jsonify({
        "remaining": current_user.invites_remaining,
        "is_admin": current_user.is_admin,
    })


# Google OAuth
try:
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth(app)
    _google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    _google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if _google_client_id and _google_client_secret:
        oauth.register(
            name="google",
            client_id=_google_client_id,
            client_secret=_google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        _google_enabled = True
    else:
        _google_enabled = False
except ImportError:
    _google_enabled = False


@app.route("/auth/google")
def google_login():
    if not _google_enabled:
        flash("Google login not configured.", "error")
        return redirect(url_for("login"))
    app_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    redirect_uri = f"{app_url}/auth/google/callback"
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    if not _google_enabled:
        return redirect(url_for("login"))
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") or oauth.google.parse_id_token(token, None)

        google_id = userinfo.get("sub")
        email = userinfo.get("email", "").lower()
        name = userinfo.get("name", "")
        picture = userinfo.get("picture", "")

        # Check if user exists by google_id or email
        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            user = User.query.filter_by(email=email).first()

        if user:
            # Link Google to existing account
            if not user.google_id:
                user.google_id = google_id
            if picture:
                user.avatar_url = picture
            user.email_verified = True
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user, remember=True)
            return redirect("/")

        # New user — check invite requirement
        role = _determine_role(email)
        invite_code = session.pop("invite_code", None)
        invite = None

        if role != "admin":
            if not invite_code:
                flash("You need an invite to sign up.", "error")
                return redirect(url_for("login"))
            invite = Invite.query.filter_by(code=invite_code).first()
            if not invite or (invite.used_by and not invite.multi_use):
                flash("Invalid or used invite.", "error")
                return redirect(url_for("login"))

        user = User(
            email=email, name=name, google_id=google_id,
            role=role, email_verified=True, avatar_url=picture,
            invites_remaining=3,
            invited_by=invite.created_by if invite else None,
        )
        db.session.add(user)
        db.session.commit()

        if invite and not invite.multi_use:
            invite.used_by = user.id
            invite.used_at = datetime.now(timezone.utc)
            db.session.commit()

        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=True)
        return redirect("/")
    except Exception as e:
        flash(f"Google login failed: {str(e)[:100]}", "error")
        return redirect(url_for("login"))


# ─── EMAIL HELPERS ─────────────────────────────────────────────────────────

def _send_verification_email(user):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return False
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        s = URLSafeTimedSerializer(app.secret_key)
        token = s.dumps({"user_id": user.id, "email": user.email}, salt="email-verify")
        app_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
        verify_url = f"{app_url}/verify/{token}"

        from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@12weeks.app")
        msg = Mail(
            from_email=from_email,
            to_emails=user.email,
            subject="Verify your 12 Weeks account",
            html_content=f"""<h2>Verify Your Email</h2>
            <p>Click the link below to verify your email and start your 12-week program.</p>
            <p><a href="{verify_url}" style="background:#4ade80;color:#0d0f0e;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Verify Email</a></p>
            <p>This link expires in 24 hours.</p>""",
        )
        sg = SendGridAPIClient(api_key)
        sg.send(msg)
        return True
    except Exception as e:
        import logging
        logging.warning("Failed to send verification email: %s", e)
        return False


def _send_invite_email(inviter_name, recipient_email, invite_url):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return False
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@12weeks.app")
        msg = Mail(
            from_email=from_email,
            to_emails=recipient_email,
            subject=f"{inviter_name} invited you to 12 Weeks",
            html_content=f"""<h2>You're Invited to 12 Weeks</h2>
            <p>{inviter_name} has invited you to join 12 Weeks — an AI-powered fitness coaching program.</p>
            <p><a href="{invite_url}" style="background:#4ade80;color:#0d0f0e;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Accept Invite</a></p>
            <p>This invite is single-use.</p>""",
        )
        sg = SendGridAPIClient(api_key)
        sg.send(msg)
        return True
    except Exception:
        return False


def _send_invite_request_email(name, email):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        admin_email = os.environ.get("ADMIN_EMAIL", "erik@placemetry.com")
        from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@12weeks.app")
        msg = Mail(
            from_email=from_email,
            to_emails=admin_email,
            subject="New 12 Weeks Invite Request",
            html_content=f"<p><strong>Name:</strong> {name}</p><p><strong>Email:</strong> {email}</p>",
        )
        sg = SendGridAPIClient(api_key)
        sg.send(msg)
    except Exception:
        pass


# ─── PAGES ──────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/static/sw.js")
def service_worker():
    """Serve service worker with no-cache headers so updates propagate immediately."""
    import flask
    response = flask.send_from_directory(app.static_folder, 'sw.js')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@app.route("/restart-plan")
@login_required
def restart_plan():
    """Reset plan_accepted and redirect to index with action param."""
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if goal:
        goal.plan_accepted = False
        db.session.commit()
    return redirect("/?action=restart-plan")


@app.route("/redo-measurements")
@login_required
def redo_measurements():
    """Reset physical assessment so user can re-enter measurements."""
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if pa:
        pa.completed = False
        db.session.commit()
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if goal:
        goal.plan_accepted = False
        db.session.commit()
    return redirect("/")


@app.route("/redo-equipment")
@login_required
def redo_equipment():
    """Reset equipment inventory so user can re-select."""
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    if eq:
        eq.completed = False
        db.session.commit()
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if goal:
        goal.plan_accepted = False
        db.session.commit()
    return redirect("/")


@app.route("/reset-onboarding")
@login_required
def reset_onboarding():
    """Reset all onboarding data for current user. Keeps the account."""
    uid = current_user.id
    for model in [ChatMessage, MorningCheckIn, PsychIntake, PhysicalAssessment,
                  ExerciseLog, ExerciseCompletion, DayCompletion, BodyWeight,
                  BodyMeasurement, WeeklyCheckIn, MealLog, SupplementLog,
                  ProgressPhoto, UserConstraints, TrainingGoal,
                  UserFoodSelections, WeeklyReport]:
        try:
            model.query.filter_by(user_id=uid).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
    # Reset app state
    state = AppState.query.filter_by(user_id=uid).first()
    if state:
        state.baseline_done = False
        state.current_week = 1
        state.start_date = None
        db.session.commit()
    # Also reset equipment
    try:
        UserEquipment.query.filter_by(user_id=uid).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect("/")


# ─── WORKOUT DATA ───────────────────────────────────────────────────────────

def _get_user_food_ids():
    """Get the set of food catalog IDs the user selected during onboarding."""
    fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()
    if not fs or not fs.selected_foods:
        return None  # No selections = show everything (onboarding not done)
    ids = set()
    for cat_foods in fs.selected_foods.values():
        ids.update(cat_foods)
    return ids


# Map meal plan food names → food catalog IDs
_FOOD_NAME_TO_ID = {
    "Whey protein shake": "whey_protein",
    "Whey protein shake (water)": "whey_protein",
    "Grilled chicken breast": "chicken_breast",
    "Baked chicken breast": "chicken_breast",
    "Eggs, scrambled": "eggs",
    "Eggs, omelette": "eggs",
    "Hard boiled egg": "eggs",
    "Hard boiled eggs": "eggs",
    "Greek yogurt": "greek_yogurt",
    "Cheddar cheese": "cheddar_cheese",
    "Cottage cheese": "cottage_cheese",
    "White rice": "white_rice",
    "Brown rice": "brown_rice",
    "Sweet potato": "sweet_potato",
    "Quinoa": "quinoa",
    "Oats": "oats",
    "Whole wheat toast": "whole_wheat_bread",
    "Banana": "banana",
    "Blueberries": "blueberries",
    "Mixed greens": "mixed_greens",
    "Spinach": "spinach",
    "Spinach (in omelette)": "spinach",
    "Spinach side salad": "spinach",
    "Side salad (mixed greens)": "mixed_greens",
    "Steamed broccoli": "broccoli",
    "Steamed asparagus": "asparagus",
    "Cherry tomatoes": "cherry_tomatoes",
    "Avocado": "avocado",
    "Almonds": "almonds",
    "Olive oil + lemon dressing": "olive_oil",
    "Olive oil dressing": "olive_oil",
    "Olive oil": "olive_oil",
}


def _filter_meals_by_food_selections(days, user_food_ids):
    """Remove foods from meal plans that the user didn't select.
    SAFETY CRITICAL: Also enforces allergen/dietary restriction filtering.
    Also enforces 16:8 fasting window — no caloric foods before 11am or after 7pm."""
    import copy, re
    if user_food_ids is None:
        return days  # No selections yet = show everything

    # Always-allowed items (zero-cal condiments, basics, beverages — don't break fast)
    always_allowed = {"Black coffee", "Water", "Salsa", "Electrolytes (salt, potassium)",
                      "Lemon juice"}

    # Get user's fasting protocol
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    fasting = goal.fasting_protocol if goal else None
    is_16_8 = fasting and ("16:8" in fasting or "16_8" in fasting)

    def _parse_meal_hour(time_str):
        """Parse '9:00am' → 9, '2:30pm' → 14, '11:00am' → 11."""
        if not time_str:
            return 12  # Default to in-window
        m = re.match(r'(\d+):?\d*\s*(am|pm)', time_str.lower())
        if not m:
            return 12
        hour = int(m.group(1))
        if m.group(2) == 'pm' and hour != 12:
            hour += 12
        if m.group(2) == 'am' and hour == 12:
            hour = 0
        return hour

    filtered_days = copy.deepcopy(days)
    for day in filtered_days:
        mp = day.get("mealPlan")
        if not mp or not mp.get("meals"):
            continue
        filtered_meals = []
        for meal in mp["meals"]:
            # 16:8 enforcement: remove caloric foods outside 11am-7pm window
            if is_16_8:
                meal_hour = _parse_meal_hour(meal.get("time", ""))
                if meal_hour < 11 or meal_hour >= 19:
                    # Outside eating window — only keep zero-cal items
                    fasting_foods = [f for f in meal.get("foods", []) if f["item"] in always_allowed]
                    if fasting_foods:
                        meal["foods"] = fasting_foods
                        meal["name"] = fasting_foods[0]["item"]  # e.g., "Black coffee"
                        filtered_meals.append(meal)
                    continue  # Skip food selection filtering — entire meal is outside window

            filtered_foods = []
            for food in meal.get("foods", []):
                name = food["item"]
                if name in always_allowed:
                    filtered_foods.append(food)
                    continue
                food_id = _FOOD_NAME_TO_ID.get(name)
                if food_id is None:
                    # Unknown mapping — keep it (don't remove unrecognized items)
                    filtered_foods.append(food)
                elif food_id in user_food_ids:
                    filtered_foods.append(food)
                # else: user didn't select this food — remove it

            # Fast day protein substitution: if whey was removed, add user's preferred protein
            has_caloric_food = any(f["item"] not in always_allowed and f.get("cal", 0) > 0 for f in filtered_foods)
            is_fast_meal = "Fast" in meal.get("name", "") or "fast" in meal.get("name", "")
            if is_fast_meal and not has_caloric_food and user_food_ids:
                # Find user's first selected protein and add a small portion
                _PROTEIN_OPTIONS = {
                    "chicken_breast": {"item": "Grilled chicken breast", "portion": "4 oz", "cal": 130, "protein": 26, "carbs": 0, "fat": 3},
                    "eggs": {"item": "Hard-boiled eggs", "portion": "3 eggs", "cal": 210, "protein": 18, "carbs": 0, "fat": 15},
                    "egg_whites": {"item": "Egg whites", "portion": "6 whites", "cal": 100, "protein": 24, "carbs": 0, "fat": 0},
                    "greek_yogurt": {"item": "Greek yogurt (plain)", "portion": "1 cup", "cal": 130, "protein": 22, "carbs": 8, "fat": 0},
                    "cottage_cheese": {"item": "Cottage cheese", "portion": "1 cup", "cal": 160, "protein": 28, "carbs": 6, "fat": 2},
                    "tuna_canned": {"item": "Canned tuna (water)", "portion": "1 can", "cal": 120, "protein": 28, "carbs": 0, "fat": 1},
                    "salmon": {"item": "Baked salmon", "portion": "4 oz", "cal": 180, "protein": 25, "carbs": 0, "fat": 8},
                    "whey_protein": {"item": "Whey protein shake", "portion": "1 scoop", "cal": 130, "protein": 30, "carbs": 2, "fat": 1},
                    "plant_protein": {"item": "Plant protein shake", "portion": "1 scoop", "cal": 120, "protein": 24, "carbs": 4, "fat": 2},
                }
                for pid in ["chicken_breast", "eggs", "egg_whites", "greek_yogurt", "cottage_cheese", "tuna_canned", "salmon", "whey_protein", "plant_protein"]:
                    if pid in user_food_ids:
                        sub = _PROTEIN_OPTIONS.get(pid)
                        if sub:
                            filtered_foods.insert(0, dict(sub))
                            break

            # If a meal has only zero-cal items, keep it (pre-workout coffee is fine)
            # If a meal has no foods left, drop it entirely
            if filtered_foods:
                meal["foods"] = filtered_foods
                # Update meal name to reflect actual contents (don't say "Chicken + Rice" if rice was removed)
                food_names = [f["item"] for f in filtered_foods if f["item"] not in always_allowed]
                if food_names and len(food_names) <= 3:
                    # Build a clean name from the actual foods
                    short_names = [n.replace("Baked ", "").replace("Grilled ", "").replace("Steamed ", "").replace(", scrambled", "").replace(", omelette", "") for n in food_names]
                    meal["name"] = " + ".join(short_names)
                elif food_names:
                    meal["name"] = food_names[0] + f" + {len(food_names) - 1} more"
                filtered_meals.append(meal)
        mp["meals"] = filtered_meals
    return filtered_days


@app.route("/api/workouts")
@login_required
def api_workouts():
    from equipment_swaps import auto_swap_workout
    from workout_data import EXERCISES, NAME_ALIASES
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    user_equipment = eq.available_equipment if eq else []
    user_food_ids = _get_user_food_ids()
    all_weeks = {}
    for week in range(1, 13):
        phase = get_phase(week)
        days = get_workouts(week)

        # Check for user-specific prescriptions
        prescriptions = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=week
        ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()

        if prescriptions:
            rx_by_day = {}
            for rx in prescriptions:
                if rx.day_idx not in rx_by_day:
                    rx_by_day[rx.day_idx] = []
                ex_dict = {
                    "name": rx.exercise_name,
                    "sets": f"{rx.sets}x{rx.reps}",
                    "rest": rx.rest or "60s",
                    "note": rx.note or "",
                }
                if getattr(rx, 'target_weight', None):
                    ex_dict["target_weight"] = rx.target_weight
                ex_info = EXERCISES.get(rx.exercise_name, {})
                if ex_info.get("video"):
                    ex_dict["video"] = ex_info["video"]
                rx_by_day[rx.day_idx].append(ex_dict)

            for day_idx, exercises in rx_by_day.items():
                if day_idx < len(days):
                    days[day_idx]["exercises"] = exercises

        for day in days:
            if "exercises" in day:
                day["exercises"] = auto_swap_workout(day["exercises"], user_equipment)

        # Check for user-specific meal plans
        try:
            meal_plans = WeeklyMealPlan.query.filter_by(
                user_id=current_user.id, week=week
            ).all()
            if meal_plans:
                mp_by_day = {mp.day_idx: mp.meal_data for mp in meal_plans}
                for day_idx, meal_data in mp_by_day.items():
                    if day_idx < len(days) and meal_data:
                        days[day_idx]["mealPlan"] = meal_data
                        days[day_idx]["mealType"] = meal_data.get("label", "custom")
        except Exception:
            pass  # Fall back to hardcoded meal plans

        # Run plan overlay
        try:
            run_plans = WeeklyRunPlan.query.filter_by(user_id=current_user.id, week=week).all()
            if run_plans:
                for rp in run_plans:
                    if rp.day_idx < len(days):
                        days[rp.day_idx]["run"] = {"type": rp.run_type, "label": rp.label, "time": rp.duration, "detail": rp.detail or ""}
        except Exception:
            pass

        # Warmup overlay
        try:
            warmups = WeeklyWarmup.query.filter_by(user_id=current_user.id, week=week).all()
            if warmups:
                for wu in warmups:
                    if wu.day_idx < len(days) and wu.warmup_data:
                        days[wu.day_idx]["warmup"] = wu.warmup_data
        except Exception:
            pass

        # Day schedule overlay
        try:
            day_schedules = WeeklyDaySchedule.query.filter_by(user_id=current_user.id, week=week).all()
            if day_schedules:
                for ds in day_schedules:
                    if ds.day_idx < len(days):
                        days[ds.day_idx]["liftName"] = ds.lift_name
                        if ds.is_rest:
                            days[ds.day_idx]["isRest"] = True
                            days[ds.day_idx]["exercises"] = []
        except Exception:
            pass

        days = _filter_meals_by_food_selections(days, user_food_ids)
        all_weeks[str(week)] = {
            "week": week,
            "phase": phase,
            "phaseInfo": PHASES[phase],
            "days": days,
        }
    try:
        all_weeks["_exerciseNames"] = sorted(set(list(EXERCISES.keys()) + list(NAME_ALIASES.keys())))
    except Exception:
        all_weeks["_exerciseNames"] = []
    return jsonify(all_weeks)


@app.route("/api/workouts/<int:week>")
@login_required
def api_week(week):
    if week < 1 or week > 12:
        return jsonify({"error": "Week must be 1-12"}), 400
    from equipment_swaps import auto_swap_workout
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    user_equipment = eq.available_equipment if eq else []
    user_food_ids = _get_user_food_ids()
    phase = get_phase(week)
    days = get_workouts(week)

    # Check for user-specific prescriptions
    prescriptions = WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=week
    ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()

    if prescriptions:
        rx_by_day = {}
        for rx in prescriptions:
            if rx.day_idx not in rx_by_day:
                rx_by_day[rx.day_idx] = []
            ex_dict = {
                "name": rx.exercise_name,
                "sets": f"{rx.sets}x{rx.reps}",
                "rest": rx.rest or "60s",
                "note": rx.note or "",
            }
            ex_info = EXERCISES.get(rx.exercise_name, {})
            if ex_info.get("video"):
                ex_dict["video"] = ex_info["video"]
            rx_by_day[rx.day_idx].append(ex_dict)

        for day_idx, exercises in rx_by_day.items():
            if day_idx < len(days):
                days[day_idx]["exercises"] = exercises

    for day in days:
        if "exercises" in day:
            day["exercises"] = auto_swap_workout(day["exercises"], user_equipment)

    # Check for user-specific meal plans
    try:
        meal_plans = WeeklyMealPlan.query.filter_by(
            user_id=current_user.id, week=week
        ).all()
        if meal_plans:
            mp_by_day = {mp.day_idx: mp.meal_data for mp in meal_plans}
            for day_idx, meal_data in mp_by_day.items():
                if day_idx < len(days) and meal_data:
                    days[day_idx]["mealPlan"] = meal_data
                    days[day_idx]["mealType"] = meal_data.get("label", "custom")
    except Exception:
        pass  # Fall back to hardcoded meal plans

    # Run plan overlay
    try:
        run_plans = WeeklyRunPlan.query.filter_by(user_id=current_user.id, week=week).all()
        if run_plans:
            for rp in run_plans:
                if rp.day_idx < len(days):
                    days[rp.day_idx]["run"] = {"type": rp.run_type, "label": rp.label, "time": rp.duration, "detail": rp.detail or ""}
    except Exception:
        pass

    # Warmup overlay
    try:
        warmups = WeeklyWarmup.query.filter_by(user_id=current_user.id, week=week).all()
        if warmups:
            for wu in warmups:
                if wu.day_idx < len(days) and wu.warmup_data:
                    days[wu.day_idx]["warmup"] = wu.warmup_data
    except Exception:
        pass

    # Day schedule overlay
    try:
        day_schedules = WeeklyDaySchedule.query.filter_by(user_id=current_user.id, week=week).all()
        if day_schedules:
            for ds in day_schedules:
                if ds.day_idx < len(days):
                    days[ds.day_idx]["liftName"] = ds.lift_name
                    if ds.is_rest:
                        days[ds.day_idx]["isRest"] = True
                        days[ds.day_idx]["exercises"] = []
    except Exception:
        pass

    days = _filter_meals_by_food_selections(days, user_food_ids)
    return jsonify({
        "week": week, "phase": phase,
        "phaseInfo": PHASES[phase],
        "days": days,
    })


@app.route("/api/warmups")
@login_required
def api_warmups():
    return jsonify(WARMUPS)


# ─── APP STATE ──────────────────────────────────────────────────────────────

def _get_state():
    s = AppState.query.filter_by(user_id=current_user.id).first()
    if not s:
        s = AppState(current_week=1, baseline_done=False, user_id=current_user.id)
        db.session.add(s)
        db.session.commit()
    return s


@app.route("/api/state")
@login_required
def api_state():
    s = _get_state()
    return jsonify({
        "current_week": s.current_week,
        "baseline_done": s.baseline_done,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "traveling": s.traveling,
        "timezone": current_user.timezone if hasattr(current_user, 'timezone') else 'UTC',
        "server_date": str(date.today()),
        "user_date": str(_user_today()),
    })


@app.route("/api/state", methods=["POST"])
@login_required
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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"ok": True})


# ─── EXERCISE WEIGHTS ───────────────────────────────────────────────────────

@app.route("/api/weights")
@login_required
def api_weights():
    # Merge legacy ExerciseLog with the modern SetLog table.
    # Per-exercise history collapses multi-set days into ONE entry per day
    # (max weight × max reps_completed for that day) so e1RM downstream is meaningful.
    result = {}

    # 1. Legacy ExerciseLog entries
    logs = ExerciseLog.query.filter_by(user_id=current_user.id).order_by(ExerciseLog.logged_date, ExerciseLog.id).all()
    for log in logs:
        name = log.exercise_name
        if name not in result:
            result[name] = {"current": 0, "history": []}
        entry = {
            "weight": log.weight,
            "reps": log.sets_label,
            "reps_completed": log.reps_completed,
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

    # 2. Modern SetLog entries — collapse per (exercise, week, day) to the max-weight set
    set_logs = SetLog.query.filter_by(user_id=current_user.id, done=True).order_by(SetLog.logged_date, SetLog.id).all()
    by_day = {}  # (name, week, day) -> {weight, reps}
    for s in set_logs:
        if not s.weight or s.weight <= 0:
            continue
        key = (s.exercise_name, s.week, s.day_idx)
        existing = by_day.get(key)
        if not existing or s.weight > existing["weight"]:
            by_day[key] = {
                "weight": s.weight,
                "reps_completed": s.reps or 0,
                "logged_date": s.logged_date,
            }
    # Sort the collapsed entries by date and merge into result
    for (name, wk, day_idx), info in sorted(by_day.items(), key=lambda kv: (kv[1]["logged_date"] or date.min, kv[0][1] or 0)):
        if name not in result:
            result[name] = {"current": 0, "history": []}
        result[name]["history"].append({
            "weight": info["weight"],
            "reps": str(info["reps_completed"]),
            "reps_completed": info["reps_completed"],
            "date": info["logged_date"].isoformat() if info["logged_date"] else None,
            "week": wk,
            "day": day_idx,
        })
        result[name]["current"] = info["weight"]

    return jsonify(result)


@app.route("/api/weights", methods=["POST"])
@login_required
def api_weights_record():
    from workout_data import resolve_name
    data = request.get_json()
    data["exercise"] = resolve_name(data["exercise"])
    weight = data.get("weight", 0)
    if weight < 0 or weight > 1500:
        return jsonify({"error": "Invalid weight"}), 400

    # Upsert: update existing entry for same exercise/week/day/user
    existing = None
    if data.get("week") is not None and data.get("day_idx") is not None:
        existing = ExerciseLog.query.filter_by(
            exercise_name=data["exercise"],
            week=data.get("week"),
            day_idx=data.get("day_idx"),
            user_id=current_user.id,
        ).first()

    if existing:
        existing.weight = weight
        existing.sets_label = data.get("sets_label")
        existing.rpe = data.get("rpe")
        existing.rpe_score = data.get("rpe_score")
        existing.reps_completed = data.get("reps_completed")
        existing.logged_date = _user_today()
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": "Save failed"}), 500
        return jsonify({"ok": True, "id": existing.id, "updated": True})

    log = ExerciseLog(
        exercise_name=data["exercise"],
        weight=weight,
        sets_label=data.get("sets_label"),
        rpe=data.get("rpe"),
        rpe_score=data.get("rpe_score"),
        reps_completed=data.get("reps_completed"),
        difficulty_notes=data.get("difficulty_notes"),
        week=data.get("week"),
        day_idx=data.get("day_idx"),
        logged_date=_user_today(),
        user_id=current_user.id,
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"ok": True, "id": log.id})


@app.route("/api/sets", methods=["POST"])
@login_required
def api_set_log():
    """Save individual set data — one row per set."""
    from workout_data import resolve_name
    data = request.get_json()
    exercise = resolve_name(data.get("exercise"))
    week = data.get("week")
    day_idx = data.get("day_idx")
    set_number = data.get("set_number")
    weight = data.get("weight", 0)
    reps = data.get("reps", 0)
    # done is OPTIONAL — if not provided, do NOT touch existing.done (race-condition fix).
    # This lets blur-triggered saveSetField save weight/reps without clobbering the done
    # state set by a concurrent toggleSet click.
    done_provided = "done" in data
    done = bool(data.get("done", False)) if done_provided else False

    if not exercise or week is None or day_idx is None or set_number is None:
        return jsonify({"error": "Missing required fields"}), 400

    # Upsert: update if exists, create if not
    existing = SetLog.query.filter_by(
        user_id=current_user.id, exercise_name=exercise,
        week=week, day_idx=day_idx, set_number=set_number
    ).first()

    if existing:
        existing.weight = weight
        existing.reps = reps
        if done_provided:
            existing.done = done
        existing.logged_date = _user_today()
    else:
        existing = SetLog(
            user_id=current_user.id, exercise_name=exercise,
            week=week, day_idx=day_idx, set_number=set_number,
            weight=weight, reps=reps,
            done=done if done_provided else False,
            logged_date=_user_today(),
        )
        db.session.add(existing)
    # Compute targets and detect modifications
    try:
        targets = compute_next_targets(current_user.id, exercise, week, day_idx)
        if targets.get("target_weight"):
            existing.target_weight = targets["target_weight"]
            existing.target_reps = targets.get("target_reps")
        # Detect user modification
        if targets.get("target_weight") and weight and targets["target_weight"] > 0:
            if weight > targets["target_weight"] * 1.02:
                existing.user_modified = True
                existing.modification_direction = 'increased_weight'
            elif weight < targets["target_weight"] * 0.98:
                existing.user_modified = True
                existing.modification_direction = 'decreased_weight'
            else:
                existing.modification_direction = 'as_prescribed'
    except Exception:
        pass
    if "exercise_swapped" in data:
        existing.exercise_swapped = data.get("exercise_swapped", False)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"ok": True, "id": existing.id})


@app.route("/api/sets")
@login_required
def api_get_sets():
    """Get all set logs for current user."""
    sets = SetLog.query.filter_by(user_id=current_user.id).order_by(
        SetLog.week, SetLog.day_idx, SetLog.set_number
    ).all()
    result = {}
    for s in sets:
        key = f"{s.week}_{s.day_idx}_{s.exercise_name}"
        if key not in result:
            result[key] = []
        result[key].append({
            "set": s.set_number, "weight": s.weight,
            "reps": s.reps, "done": s.done,
        })
    return jsonify(result)


@app.route("/api/prescription/seed", methods=["POST"])
@login_required
def api_prescription_seed():
    """Seed WeeklyPrescription rows for a week from the phase template."""
    data = request.get_json()
    week = data.get("week", _current_week())
    from workout_data import PHASE_TEMPLATES, get_phase

    # Don't overwrite existing prescriptions
    existing = WeeklyPrescription.query.filter_by(user_id=current_user.id, week=week).first()
    if existing:
        return jsonify({"message": "Prescriptions already exist for this week", "count": WeeklyPrescription.query.filter_by(user_id=current_user.id, week=week).count()})

    phase = get_phase(week)
    template = PHASE_TEMPLATES.get(phase, PHASE_TEMPLATES.get(1, {}))
    count = 0
    for day_idx in range(7):
        for order, ex in enumerate(template.get(day_idx, [])):
            db.session.add(WeeklyPrescription(
                user_id=current_user.id,
                week=week,
                day_idx=day_idx,
                exercise_order=order,
                exercise_name=ex['exercise'],
                sets=ex['sets'],
                reps=ex['reps'],
                rest=ex.get('rest', '60s'),
                note=ex.get('note', ''),
                source='template',
            ))
            count += 1
    db.session.commit()
    return jsonify({"seeded": count, "week": week})


@app.route("/api/weekly-program/generate", methods=["POST"])
@login_required
def api_generate_weekly_program():
    """Generate personalized weekly program using training engine + deficit plan."""
    data = request.get_json() or {}
    target_week = data.get("week", _current_week() + 1)

    # Don't overwrite coach-modified prescriptions
    existing = WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=target_week, source='coach'
    ).first()
    if existing:
        return jsonify({"message": "Coach-modified prescriptions exist", "week": target_week})

    # Get the phase template as baseline
    from workout_data import PHASE_TEMPLATES, get_phase, EXERCISES, resolve_name
    phase = get_phase(target_week)
    template = PHASE_TEMPLATES.get(phase, PHASE_TEMPLATES.get(1, {}))

    # Delete any existing template-sourced prescriptions for this week
    WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=target_week, source='template'
    ).delete()
    WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=target_week, source='engine'
    ).delete()

    program_summary = []

    for day_idx in range(7):
        exercises = template.get(day_idx, [])
        for order, ex_template in enumerate(exercises):
            exercise_name = resolve_name(ex_template['exercise'])
            base_sets = ex_template['sets']
            base_reps = ex_template['reps']
            base_rest = ex_template.get('rest', '60s')
            base_note = ex_template.get('note', '')

            # Run training engine for this exercise
            try:
                targets = compute_next_targets(
                    current_user.id, exercise_name, target_week, day_idx
                )
                if targets.get('target_weight'):
                    # Engine has a recommendation
                    adjusted_reps = str(targets.get('target_reps', base_reps))
                    adjusted_sets = targets.get('target_sets', base_sets)
                    reason = targets.get('adjustment_reason', '')
                    weight = targets.get('target_weight')
                    note = base_note
                    source = 'engine'
                else:
                    adjusted_reps = base_reps
                    adjusted_sets = base_sets
                    note = base_note
                    weight = None
                    reason = None
                    source = 'template'
            except Exception:
                adjusted_reps = base_reps
                adjusted_sets = base_sets
                note = base_note
                weight = None
                reason = None
                source = 'template'

            db.session.add(WeeklyPrescription(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                exercise_order=order,
                exercise_name=exercise_name,
                sets=adjusted_sets,
                reps=adjusted_reps,
                rest=base_rest,
                note=note,
                source=source,
                target_weight=weight,
                progression_indicator=targets.get('progression_indicator', 'hold') if source == 'engine' else None,
                adjustment_reason=reason,
            ))

            program_summary.append({
                "day": day_idx,
                "exercise": exercise_name,
                "sets": adjusted_sets,
                "reps": adjusted_reps,
                "target_weight": weight,
                "reason": reason if source == 'engine' else None,
            })

    db.session.commit()

    # Also run deficit plan
    deficit = None
    try:
        # Inline deficit calculation (same logic as api_deficit_plan)
        goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
        bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
        if goal and goal.target_weight and bw:
            current_weight = bw.weight_lbs
            target_weight = goal.target_weight
            weeks_remaining = max(1, 12 - target_week + 1)
            required_weekly = (current_weight - target_weight) / weeks_remaining
            if required_weekly > 0:
                deficit = {
                    "current_weight": current_weight,
                    "target_weight": target_weight,
                    "weeks_remaining": weeks_remaining,
                    "required_weekly_loss": round(required_weekly, 1),
                }
    except Exception:
        pass

    # --- MEAL PLAN GENERATION ---
    meal_summary = []
    try:
        from meal_generator import generate_meal_plan
        from goal_engine import compute_day_calories
        from workout_data import MEAL_PLANS

        # Get user's food selections
        fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()
        user_foods = fs.selected_foods if fs and fs.selected_foods else None

        # Get user's goal for calorie computation
        if not goal:
            goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
        if not bw:
            bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
        current_weight = bw.weight_lbs if bw else 200

        base_calories = goal.daily_calories if goal else 1800
        # Use deficit-adjusted calories if available
        if deficit and deficit.get('required_weekly_loss'):
            # Deficit already computed above; keep base_calories from goal
            pass

        # Map DAY_MEAL_TYPES day types to compute_day_calories day types
        _cal_day_type_map = {
            "heavy_lift": "heavy",
            "long_run": "long_run",
            "moderate": "training",
            "fast_day": "rest",
        }
        day_types = [_get_day_meal_type(current_user.id, target_week, d) for d in range(7)]
        fasting_protocol = goal.fasting_protocol if goal else "16_8"

        # Delete existing non-coach meal plans for this week
        WeeklyMealPlan.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyMealPlan.source != 'coach').delete()

        for day_idx in range(7):
            day_type = day_types[day_idx]

            if day_type == 'fast_day':
                # Use the hardcoded fast_day plan directly
                meal_plan = MEAL_PLANS.get('fast_day', {})
            elif user_foods:
                # Compute day-specific calorie/macro targets
                cal_day_type = _cal_day_type_map.get(day_type, "training")
                day_macros = compute_day_calories(
                    base_calories,
                    goal.goal_type if goal else 'cut',
                    cal_day_type,
                    current_weight,
                )

                # Generate personalized meal plan
                meal_plan = generate_meal_plan(
                    selected_foods=user_foods,
                    day_type=day_type,
                    targets=day_macros,
                    fasting_protocol=fasting_protocol,
                )
            else:
                # No food selections yet — skip meal generation
                continue

            db.session.add(WeeklyMealPlan(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                meal_data=meal_plan,
                daily_calories=meal_plan.get('targetCal', 0),
                daily_protein=meal_plan.get('targetProtein', 0),
                day_type=day_type,
                source='generator',
            ))

            meal_summary.append({
                "day": day_idx,
                "type": day_type,
                "calories": meal_plan.get('targetCal', 0),
                "protein": meal_plan.get('targetProtein', 0),
            })

        db.session.commit()
    except Exception:
        db.session.rollback()

    # --- RUN PLAN GENERATION ---
    run_summary = []
    try:
        from workout_data import get_workouts as _get_template_workouts
        template_days = _get_template_workouts(target_week)

        # Delete existing engine-sourced run plans for this week
        WeeklyRunPlan.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyRunPlan.source != 'coach').delete()

        for day_idx in range(7):
            template_run = template_days[day_idx].get("run") if day_idx < len(template_days) else None
            if not template_run:
                continue

            progressed = _generate_run_plan(current_user.id, target_week, day_idx, template_run)

            db.session.add(WeeklyRunPlan(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                run_type=progressed.get('type', 'z2'),
                label=progressed.get('label', 'Run'),
                duration=progressed.get('time', '30 min'),
                detail=progressed.get('detail', ''),
                source='engine',
            ))

            run_summary.append({
                "day": day_idx,
                "type": progressed.get('type'),
                "label": progressed.get('label'),
                "duration": progressed.get('time'),
            })

        db.session.commit()
    except Exception:
        db.session.rollback()

    # --- WARMUP GENERATION ---
    try:
        from workout_data import EXERCISES as _EXERCISES

        # Get latest soreness data from morning check-in
        soreness_data = None
        latest_checkin = MorningCheckIn.query.filter_by(
            user_id=current_user.id
        ).order_by(MorningCheckIn.created_at.desc()).first()
        if latest_checkin and latest_checkin.soreness and latest_checkin.soreness >= 6:
            # High soreness — try to infer area from notes
            area = "shoulders"  # Default for this user's known tightness
            if latest_checkin.notes:
                notes_lower = latest_checkin.notes.lower()
                for a in ["lower back", "hamstrings", "quads", "shoulders", "chest"]:
                    if a in notes_lower:
                        area = a
                        break
            soreness_data = {"area": area, "level": latest_checkin.soreness}

        # Delete existing engine-sourced warmups for this week
        WeeklyWarmup.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyWarmup.source != 'coach').delete()

        if not template_days:
            template_days = _get_template_workouts(target_week)

        for day_idx in range(7):
            day_data = template_days[day_idx] if day_idx < len(template_days) else {}
            day_exercises = day_data.get("exercises", [])

            # Extract muscle groups from exercises
            muscle_groups = set()
            for ex in day_exercises:
                ex_name = ex.get("name", ex.get("exercise", ""))
                ex_info = _EXERCISES.get(ex_name, {})
                mg = ex_info.get("muscle_group", "")
                if mg:
                    # Normalize compound groups like "chest_triceps" -> ["chest", "triceps"]
                    for part in mg.split("_"):
                        if part in ("chest", "back", "quads", "hamstrings", "shoulders", "glutes"):
                            muscle_groups.add(part)

            if not muscle_groups and not day_exercises:
                continue  # Rest day with no exercises, skip warmup

            warmup = _generate_warmup(day_exercises, list(muscle_groups), soreness_data)

            db.session.add(WeeklyWarmup(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                warmup_data=warmup,
                source='engine',
            ))

        db.session.commit()
    except Exception:
        db.session.rollback()

    # --- DAY SCHEDULE SEEDING ---
    schedule_summary = []
    try:
        # Delete existing engine-sourced schedules for this week
        WeeklyDaySchedule.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyDaySchedule.source != 'coach').delete()

        if not template_days:
            template_days = _get_template_workouts(target_week)

        for day_idx in range(7):
            day_data = template_days[day_idx] if day_idx < len(template_days) else {}
            lift_name = day_data.get("liftName", "Rest")
            is_rest = "rest" in lift_name.lower() and not day_data.get("exercises")

            # Extract muscle groups from the day's exercises
            muscle_groups = set()
            for ex in day_data.get("exercises", []):
                ex_name = ex.get("name", ex.get("exercise", ""))
                ex_info = _EXERCISES.get(ex_name, {})
                mg = ex_info.get("muscle_group", "")
                if mg:
                    for part in mg.split("_"):
                        if part in ("chest", "back", "quads", "hamstrings", "shoulders", "glutes", "biceps", "triceps", "core"):
                            muscle_groups.add(part)

            db.session.add(WeeklyDaySchedule(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                lift_name=lift_name,
                muscle_groups=list(muscle_groups),
                is_rest=is_rest,
                source='engine',
            ))

            schedule_summary.append({
                "day": day_idx,
                "lift_name": lift_name,
                "muscle_groups": list(muscle_groups),
                "is_rest": is_rest,
            })

        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify({
        "week": target_week,
        "phase": phase,
        "exercises_generated": len(program_summary),
        "program": program_summary,
        "deficit": deficit,
        "meal_summary": meal_summary,
        "run_summary": run_summary,
        "schedule_summary": schedule_summary,
    })


@app.route("/api/sets/<int:week>/<int:day_idx>")
@login_required
def api_get_day_sets(week, day_idx):
    """Get set logs for a specific day — used by frontend to populate set rows."""
    sets = SetLog.query.filter_by(
        user_id=current_user.id, week=week, day_idx=day_idx
    ).order_by(SetLog.exercise_name, SetLog.set_number).all()
    result = {}
    for s in sets:
        key = f"{week}_{day_idx}_{s.exercise_name}"
        if key not in result:
            result[key] = {}
        result[key][str(s.set_number)] = {
            "weight": s.weight, "reps": s.reps, "done": s.done,
        }
    return jsonify(result)


@app.route("/api/targets/<path:exercise_name>")
@login_required
def api_exercise_targets(exercise_name):
    from workout_data import resolve_name
    exercise_name = resolve_name(exercise_name)
    s = _get_state()
    week = _current_week()
    day_idx = _user_today().weekday()
    targets = compute_next_targets(current_user.id, exercise_name, week, day_idx)
    return jsonify(targets)


@app.route("/api/weights/baseline", methods=["POST"])
@login_required
def api_weights_baseline():
    from workout_data import resolve_name
    data = request.get_json()
    for entry in data.get("exercises", []):
        entry["name"] = resolve_name(entry["name"])
        log = ExerciseLog(
            exercise_name=entry["name"],
            weight=entry["working_weight"],
            sets_label=f"baseline: {entry['test_weight']}lb x {entry['test_reps']}",
            rpe="just_right",
            week=0,
            day_idx=0,
            logged_date=_user_today(),
            test_weight=entry.get("test_weight"),
            test_reps=entry.get("test_reps"),
            estimated_1rm=entry.get("estimated_1rm"),
            user_id=current_user.id,
        )
        db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/weight-detail/<path:exercise_name>")
@login_required
def api_weight_detail(exercise_name):
    """Detailed weight history + percentile for accordion expansion."""
    from body_stats import compute_1rm_percentile

    # Build weekly e1RM from per-set data (max e1RM per set per week)
    sets = SetLog.query.filter_by(
        user_id=current_user.id, exercise_name=exercise_name, done=True
    ).order_by(SetLog.week, SetLog.set_number).all()

    # Group by week, compute max e1RM per week
    weekly_e1rm = {}
    for s in sets:
        if s.weight and s.weight > 0:
            reps = min(s.reps or 10, 15)  # Cap at 15
            e1rm = round(s.weight * (1 + reps / 30))
            wk = s.week or 1
            if wk not in weekly_e1rm or e1rm > weekly_e1rm[wk]:
                weekly_e1rm[wk] = e1rm

    # Fallback: if SetLog is empty, compute from ExerciseLog
    if not weekly_e1rm:
        ex_logs = ExerciseLog.query.filter_by(
            user_id=current_user.id, exercise_name=exercise_name
        ).order_by(ExerciseLog.week).all()
        for log in ex_logs:
            if log.weight and log.weight > 0:
                reps = min(log.reps_completed or 10, 15)
                e1rm = round(log.weight * (1 + reps / 30))
                wk = log.week or 1
                if wk not in weekly_e1rm or e1rm > weekly_e1rm[wk]:
                    weekly_e1rm[wk] = e1rm

    # Merge in WeeklyPrescription target_weight as "scheduled" e1RM
    # so users see progression even before they've lifted at the new weight
    from models import WeeklyPrescription
    prescriptions = WeeklyPrescription.query.filter_by(
        user_id=current_user.id, exercise_name=exercise_name
    ).all()
    prescribed_e1rm = {}  # week -> e1rm
    for p in prescriptions:
        if not p.target_weight or p.target_weight <= 0:
            continue
        # Parse target reps — can be "10", "10s" (skip timed), "8-12" (use mid)
        reps_str = str(p.reps or '10').strip()
        if reps_str.endswith('s'):
            continue  # timed exercise, no e1RM
        if '-' in reps_str:
            parts = reps_str.split('-')
            try:
                reps_val = (int(parts[0]) + int(parts[1])) // 2
            except (ValueError, IndexError):
                reps_val = 10
        else:
            try:
                reps_val = int(reps_str)
            except ValueError:
                reps_val = 10
        reps_capped = min(reps_val, 15)
        e1rm = round(p.target_weight * (1 + reps_capped / 30))
        if p.week not in prescribed_e1rm or e1rm > prescribed_e1rm[p.week]:
            prescribed_e1rm[p.week] = e1rm

    # Build timeline — merge logged and prescribed, prescription wins if user hasn't caught up.
    # Only include weeks ≤ user's current week so future stub prescriptions don't appear.
    user_current_week = _current_week()
    all_weeks = sorted(set(weekly_e1rm.keys()) | set(prescribed_e1rm.keys()))
    timeline = []
    for wk in all_weeks:
        if wk > user_current_week:
            continue  # Don't show future weeks — they may have stub prescriptions
        logged = weekly_e1rm.get(wk, 0)
        scheduled = prescribed_e1rm.get(wk, 0)
        # Use the higher of the two — prescription wins if user hasn't caught up
        best = max(logged, scheduled)
        if best <= 0:
            continue
        timeline.append({
            "week": wk,
            "est_1rm": best,
            "logged_1rm": logged or None,
            "scheduled_1rm": scheduled or None,
            "source": "logged" if logged >= scheduled else "scheduled",
            "is_current": wk == user_current_week,
        })

    # Also check ExerciseLog for baseline data
    logs = ExerciseLog.query.filter_by(
        user_id=current_user.id, exercise_name=exercise_name
    ).order_by(ExerciseLog.logged_date.asc()).all()

    current_1rm = timeline[-1]["est_1rm"] if timeline else None
    percentile = None
    rating = None
    baseline_1rm = None

    # Baseline from ExerciseLog test entries
    baseline_entries = [l for l in logs if l.test_weight]
    if baseline_entries:
        bl = baseline_entries[0]
        bl_reps = min(bl.test_reps or 10, 15)
        baseline_1rm = round(bl.test_weight * (1 + bl_reps / 30))

        # Population percentile — get age/sex from psych intake
        try:
            pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
            latest_bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
            bw = latest_bw.weight_lbs if latest_bw else (pa.bodyweight_lbs if pa else 180)

            intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
            sex = "male"
            age = 30
            if intake and intake.conversation:
                for msg in intake.conversation:
                    content = msg.get("content", "").lower().strip()
                    if msg.get("role") == "user":
                        if content in ("male", "female", "m", "f"):
                            sex = "female" if content in ("female", "f") else "male"
                        try:
                            num = int(content)
                            if 15 <= num <= 80:
                                age = num
                        except ValueError:
                            pass

            pct_data = compute_1rm_percentile(current_1rm, bw, exercise_name, age, sex)
            if pct_data:
                percentile = pct_data.get("percentile")
                rating = pct_data.get("rating")
        except Exception:
            pass

    return jsonify({
        "exercise": exercise_name,
        "timeline": timeline,
        "current_1rm": current_1rm,
        "baseline_1rm": baseline_1rm,
        "percentile": percentile,
        "rating": rating,
        "total_sessions": len(logs),
    })


# ─── COMPLETIONS ────────────────────────────────────────────────────────────

@app.route("/api/completions")
@login_required
def api_completions():
    week = request.args.get("week", type=int)
    ex_q = ExerciseCompletion.query.filter_by(user_id=current_user.id)
    day_q = DayCompletion.query.filter_by(user_id=current_user.id)
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
@login_required
def api_toggle_exercise():
    data = request.get_json()
    w, d, e = data["week"], data["day_idx"], data["exercise_idx"]
    ec = ExerciseCompletion.query.filter_by(user_id=current_user.id, week=w, day_idx=d, exercise_idx=e).first()
    if ec:
        ec.done = not ec.done
    else:
        ec = ExerciseCompletion(week=w, day_idx=d, exercise_idx=e, done=True, user_id=current_user.id)
        db.session.add(ec)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"done": ec.done})


@app.route("/api/exercise-swaps")
@login_required
def api_exercise_swaps():
    """Get all exercise swaps for current user."""
    swaps = ExerciseSwap.query.filter_by(user_id=current_user.id).all()
    result = {}
    for s in swaps:
        key = f"{s.week}_{s.day_idx}_{s.exercise_idx}"
        result[key] = s.swapped_to
    return jsonify(result)


@app.route("/api/exercise-swap", methods=["POST"])
@login_required
def api_exercise_swap():
    """Save or delete an exercise swap. Empty swapped_to means "revert" (delete row)."""
    data = request.get_json()
    week = data.get("week")
    day_idx = data.get("day_idx")
    exercise_idx = data.get("exercise_idx")
    swapped_to = (data.get("swapped_to") or "").strip()

    if week is None or day_idx is None or exercise_idx is None:
        return jsonify({"error": "Missing fields"}), 400

    existing = ExerciseSwap.query.filter_by(
        user_id=current_user.id, week=week, day_idx=day_idx, exercise_idx=exercise_idx
    ).first()

    # Empty swapped_to → revert: delete the row
    if not swapped_to:
        if existing:
            db.session.delete(existing)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True, "reverted": True})

    if existing:
        existing.swapped_to = swapped_to
    else:
        existing = ExerciseSwap(
            user_id=current_user.id, week=week, day_idx=day_idx,
            exercise_idx=exercise_idx, swapped_to=swapped_to,
        )
        db.session.add(existing)

    try:
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/completions/day", methods=["POST"])
@login_required
def api_toggle_day():
    data = request.get_json()
    w, d = data["week"], data["day_idx"]
    dc = DayCompletion.query.filter_by(user_id=current_user.id, week=w, day_idx=d).first()
    if dc:
        dc.done = not dc.done
    else:
        dc = DayCompletion(week=w, day_idx=d, done=True, user_id=current_user.id)
        db.session.add(dc)
    # Save workout timing if provided
    if "workout_started_at" in data:
        dc.workout_started_at = data["workout_started_at"]
    if "workout_ended_at" in data:
        dc.workout_ended_at = data["workout_ended_at"]
    if "workout_duration_min" in data:
        dc.workout_duration_min = data["workout_duration_min"]
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    try:
        generate_session_analysis(current_user.id, w, d)
        compute_muscle_strength(current_user.id)
    except Exception:
        pass
    return jsonify({"done": dc.done})


# ─── MEALS ──────────────────────────────────────────────────────────────────

@app.route("/api/meals")
@login_required
def api_meals():
    d = request.args.get("date", _user_today().isoformat())
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).first()
    if not ml:
        return jsonify({"eaten": [], "adjustments": {}, "foodItems": [], "fasting": False})
    import json as _json
    def _ensure_list(val):
        if isinstance(val, list): return val
        if isinstance(val, str):
            try: parsed = _json.loads(val); return parsed if isinstance(parsed, list) else []
            except Exception: return []
        return []
    def _ensure_dict(val):
        if isinstance(val, dict): return val
        if isinstance(val, str):
            try: parsed = _json.loads(val); return parsed if isinstance(parsed, dict) else {}
            except Exception: return {}
        return {}
    # Parse mealTiming from scheduled_time field
    meal_timing = {}
    if ml.scheduled_time:
        try:
            _parsed = _json.loads(ml.scheduled_time)
            if isinstance(_parsed, dict):
                meal_timing = _parsed
        except Exception:
            pass
    return jsonify({
        "eaten": _ensure_list(ml.eaten),
        "adjustments": _ensure_dict(ml.adjustments),
        "foodItems": _ensure_list(ml.food_items),
        "mealTiming": meal_timing,
        "fasting": ml.fasting,
    })


@app.route("/api/meals", methods=["POST"])
@login_required
def api_meals_update():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", _user_today().isoformat()))
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=d).first()
    if not ml:
        ml = MealLog(log_date=d, user_id=current_user.id)
        db.session.add(ml)
    # Save core meal data first
    if "eaten" in data:
        ml.eaten = data["eaten"]
    if "adjustments" in data:
        ml.adjustments = data["adjustments"]
    if "foodItems" in data:
        ml.food_items = data["foodItems"]
    if "fasting" in data:
        ml.fasting = data["fasting"]
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500

    # Save timing data separately (non-critical)
    if "mealTiming" in data:
        try:
            import json as _json
            ml.scheduled_time = _json.dumps(data["mealTiming"])
            db.session.commit()
        except Exception:
            db.session.rollback()  # Don't fail the whole save for timing
    return jsonify({"ok": True})


# ─── BODY WEIGHT ────────────────────────────────────────────────────────────

@app.route("/api/bodyweight")
@login_required
def api_bodyweight():
    entries = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date).all()
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
@login_required
def api_bodyweight_record():
    data = request.get_json()
    weight = data.get("weight")
    if not weight or weight < 50 or weight > 600:
        return jsonify({"error": "Weight must be between 50 and 600 lbs"}), 400
    d = date.fromisoformat(data.get("date", _user_today().isoformat()))
    bw = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
    if bw:
        bw.weight_lbs = weight
    else:
        bw = BodyWeight(log_date=d, weight_lbs=weight, user_id=current_user.id)
        db.session.add(bw)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"ok": True})


@app.route("/api/bodyweight/<log_date>", methods=["DELETE"])
@login_required
def api_bodyweight_delete(log_date):
    bw = BodyWeight.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(log_date)).first()
    if bw:
        try:
            db.session.delete(bw)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({"error": "Delete failed"}), 500
    return jsonify({"ok": True})


# ─── BODY MEASUREMENTS ─────────────────────────────────────────────────────

@app.route("/api/measurements")
@login_required
def api_measurements():
    d = request.args.get("date")
    query = BodyMeasurement.query.filter_by(user_id=current_user.id)
    if d:
        query = query.filter_by(log_date=date.fromisoformat(d))
    entries = query.order_by(BodyMeasurement.log_date).all()
    return jsonify([{
        "date": e.log_date.isoformat(),
        "waist": e.waist_inches,
        "weight": getattr(e, 'weight_lbs', None),
        "chest": getattr(e, 'chest', None),
        "hips": getattr(e, 'hips', None),
        "neck": getattr(e, 'neck', None),
        "bicep_left": getattr(e, 'bicep_left', None),
        "bicep_right": getattr(e, 'bicep_right', None),
        "thigh_left": getattr(e, 'thigh_left', None),
        "thigh_right": getattr(e, 'thigh_right', None),
        "notes": e.notes,
    } for e in entries])


@app.route("/api/measurements", methods=["POST"])
@login_required
def api_measurements_record():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", _user_today().isoformat()))

    # Fix broken unique index: log_date was indexed as UNIQUE (should not be — multiple
    # users need to submit on the same date). Drop the unique constraint if it exists.
    try:
        db.session.execute(text('DROP INDEX IF EXISTS ix_body_measurement_log_date'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_body_measurement_log_date ON body_measurement (log_date)'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Also try finding by log_date alone (in case user_id was null on old row)
    bm = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=d).first()
    if not bm:
        bm = BodyMeasurement.query.filter_by(log_date=d).first()
        if bm and bm.user_id is None:
            bm.user_id = current_user.id  # claim orphan row
    if bm:
        if "weight" in data:
            bm.weight_lbs = data["weight"]
        if "waist" in data:
            bm.waist_inches = data["waist"]
        if "chest" in data:
            bm.chest = data["chest"]
        if "hips" in data:
            bm.hips = data["hips"]
        if "neck" in data:
            bm.neck = data["neck"]
        if "bicep_left" in data:
            bm.bicep_left = data["bicep_left"]
        if "bicep_right" in data:
            bm.bicep_right = data["bicep_right"]
        if "thigh_left" in data:
            bm.thigh_left = data["thigh_left"]
        if "thigh_right" in data:
            bm.thigh_right = data["thigh_right"]
        if "notes" in data:
            bm.notes = data["notes"]
    else:
        bm = BodyMeasurement(
            log_date=d,
            weight_lbs=data.get("weight"),
            waist_inches=data.get("waist"),
            chest=data.get("chest"),
            hips=data.get("hips"),
            neck=data.get("neck"),
            bicep_left=data.get("bicep_left"),
            bicep_right=data.get("bicep_right"),
            thigh_left=data.get("thigh_left"),
            thigh_right=data.get("thigh_right"),
            notes=data.get("notes"),
            user_id=current_user.id,
        )
        db.session.add(bm)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500
    return jsonify({"ok": True})


# ─── WEEKLY CHECK-IN ────────────────────────────────────────────────────────

@app.route("/api/checkins")
@login_required
def api_checkins():
    entries = WeeklyCheckIn.query.filter_by(user_id=current_user.id).order_by(WeeklyCheckIn.week).all()
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
@login_required
def api_checkins_record():
    data = request.get_json()
    week = data["week"]
    ci = WeeklyCheckIn.query.filter_by(user_id=current_user.id, week=week).first()
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
            check_in_date=_user_today(),
            user_id=current_user.id,
        )
        db.session.add(ci)
    db.session.commit()
    return jsonify({"ok": True})


# ─── SUPPLEMENTS ────────────────────────────────────────────────────────────

@app.route("/api/supplements")
@login_required
def api_supplements():
    d = request.args.get("date", _user_today().isoformat())
    logs = SupplementLog.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).all()
    taken = {s.supplement_name: s.taken for s in logs}
    return jsonify({"date": d, "taken": taken, "list": SUPPLEMENTS})


@app.route("/api/supplements", methods=["POST"])
@login_required
def api_supplements_toggle():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", _user_today().isoformat()))
    name = data["name"]
    sl = SupplementLog.query.filter_by(user_id=current_user.id, log_date=d, supplement_name=name).first()
    if sl:
        sl.taken = not sl.taken
    else:
        sl = SupplementLog(log_date=d, supplement_name=name, taken=True, user_id=current_user.id)
        db.session.add(sl)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"taken": sl.taken})


# ─── DATA EXPORT/IMPORT ────────────────────────────────────────────────────

@app.route("/api/export")
@login_required
def api_export():
    """Export all data as JSON for backup."""
    return jsonify({
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "weights": _serialize_weights(),
        "completions": _serialize_completions(),
        "bodyweight": [{
            "date": e.log_date.isoformat(), "weight": e.weight_lbs,
        } for e in BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date).all()],
        "measurements": [{
            "date": e.log_date.isoformat(), "waist": e.waist_inches, "notes": e.notes,
        } for e in BodyMeasurement.query.filter_by(user_id=current_user.id).order_by(BodyMeasurement.log_date).all()],
        "checkins": [{
            "week": e.week, "energy": e.energy_level, "sleep": e.sleep_quality,
            "soreness": e.soreness_level, "adherence": e.adherence_pct, "notes": e.notes,
        } for e in WeeklyCheckIn.query.filter_by(user_id=current_user.id).order_by(WeeklyCheckIn.week).all()],
        "meals": [{
            "date": e.log_date.isoformat(), "eaten": e.eaten,
            "adjustments": e.adjustments, "fasting": e.fasting,
        } for e in MealLog.query.filter_by(user_id=current_user.id).order_by(MealLog.log_date).all()],
        "state": {
            "current_week": _get_state().current_week,
            "baseline_done": _get_state().baseline_done,
            "start_date": _get_state().start_date.isoformat() if _get_state().start_date else None,
        },
    })


def _serialize_weights(user_id=None):
    uid = user_id or current_user.id
    logs = ExerciseLog.query.filter_by(user_id=uid).order_by(ExerciseLog.logged_date, ExerciseLog.id).all()
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


def _serialize_completions(user_id=None):
    uid = user_id or current_user.id
    exercises = {}
    for ec in ExerciseCompletion.query.filter_by(user_id=uid, done=True).all():
        exercises[f"{ec.week}_{ec.day_idx}_{ec.exercise_idx}"] = True
    days = {}
    for dc in DayCompletion.query.filter_by(user_id=uid, done=True).all():
        days[f"{dc.week}_{dc.day_idx}"] = True
    return {"exercises": exercises, "days": days}


@app.route("/api/import", methods=["POST"])
@login_required
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
                    logged_date=date.fromisoformat(h["date"]) if h.get("date") else _user_today(),
                    test_weight=h.get("testWeight"), test_reps=h.get("testReps"),
                    estimated_1rm=h.get("estimated1RM"),
                    user_id=current_user.id,
                )
                db.session.add(log)

    # Import body weight
    if "bodyweight" in data:
        for entry in data["bodyweight"]:
            d = date.fromisoformat(entry["date"])
            existing = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
            if not existing:
                db.session.add(BodyWeight(log_date=d, weight_lbs=entry["weight"], user_id=current_user.id))

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
@login_required
def api_progress():
    """Return all progress data for charts."""
    # Body weight trend
    bw_entries = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date).all()
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
        logs = ExerciseLog.query.filter_by(user_id=current_user.id, exercise_name=name).order_by(ExerciseLog.logged_date).all()
        lifts[name] = [{"date": l.logged_date.isoformat(), "weight": l.weight, "week": l.week} for l in logs]

    # Body measurements (all fields for Stats screen + charts)
    measurements = [{
        "date": e.log_date.isoformat(),
        "weight_lbs": e.weight_lbs,
        "waist": e.waist_inches,
        "chest": e.chest,
        "hips": e.hips,
        "neck": e.neck,
        "bicep_left": e.bicep_left,
        "bicep_right": e.bicep_right,
        "thigh_left": e.thigh_left,
        "thigh_right": e.thigh_right,
    } for e in BodyMeasurement.query.filter_by(user_id=current_user.id).order_by(BodyMeasurement.log_date).all()]

    # Check-ins
    checkins = [{
        "week": e.week, "energy": e.energy_level, "sleep": e.sleep_quality,
        "soreness": e.soreness_level, "adherence": e.adherence_pct,
    } for e in WeeklyCheckIn.query.filter_by(user_id=current_user.id).order_by(WeeklyCheckIn.week).all()]

    return jsonify({
        "bodyweight": bodyweight,
        "lifts": lifts,
        "measurements": measurements,
        "checkins": checkins,
    })


# ─── TRAVEL MODE ────────────────────────────────────────────────────────────

@app.route("/api/travel/workout")
@login_required
def api_travel_workout():
    """Get bodyweight workout for a given day."""
    day = request.args.get("day", "Mon")
    workout_type = TRAVEL_DAY_MAP.get(day, "full")
    if workout_type is None or workout_type not in TRAVEL_WORKOUTS:
        return jsonify(None)
    return jsonify(TRAVEL_WORKOUTS[workout_type])


# ─── MORNING CHECK-IN ──────────────────────────────────────────────────────

@app.route("/api/morning-checkin")
@login_required
def api_morning_checkin():
    d = request.args.get("date", _user_today().isoformat())
    ci = MorningCheckIn.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).first()
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
        "missed": bool(ci.notes and '[MISSED]' in (ci.notes or '')),
    })


@app.route("/api/morning-checkin", methods=["POST"])
@login_required
def api_morning_checkin_save():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", _user_today().isoformat()))
    ci = MorningCheckIn.query.filter_by(user_id=current_user.id, log_date=d).first()
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
            user_id=current_user.id,
        )
        db.session.add(ci)
    if "missed" in data:
        # Need to handle the 'missed' field — store as notes marker for now
        if data.get("missed"):
            ci.notes = (ci.notes or '') + ' [MISSED]'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"ok": True})


@app.route("/api/morning-checkin/history")
@login_required
def api_morning_checkin_history():
    days = request.args.get("days", 30, type=int)
    since = _user_today() - timedelta(days=days)
    entries = MorningCheckIn.query.filter(
        MorningCheckIn.user_id == current_user.id,
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


@app.route("/api/morning-checkin/extract", methods=["POST"])
@login_required
def api_extract_checkin_values():
    """Extract numeric check-in values from the morning conversation using AI."""
    data = request.get_json()
    conversation = data.get('conversation', '')
    if not conversation:
        return jsonify({"error": "No conversation"}), 400

    try:
        import anthropic
        import json
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": f"""Extract numeric check-in values from this coach conversation. Return ONLY a JSON object with these fields (each 1-10 scale):
- sleep_quality (how well they slept)
- stress_level (stress level)
- soreness (physical soreness)
- mood (emotional state)
- motivation (drive to train)
- anxiety (anxiety level)

If a value wasn't discussed, use 5 as default. Infer from context.

Conversation:
{conversation}"""}],
        )
        text = response.content[0].text.strip()
        # Find JSON in the response
        if '{' in text:
            json_str = text[text.index('{'):text.rindex('}') + 1]
            values = json.loads(json_str)
            # Update the morning check-in record
            d = _user_today()
            ci = MorningCheckIn.query.filter_by(user_id=current_user.id, log_date=d).first()
            if ci:
                ci.sleep_quality = values.get('sleep_quality', ci.sleep_quality)
                ci.stress_level = values.get('stress_level', ci.stress_level)
                ci.soreness = values.get('soreness', ci.soreness)
                ci.mood = values.get('mood', ci.mood)
                ci.motivation = values.get('motivation', ci.motivation)
                ci.anxiety = values.get('anxiety', ci.anxiety)
                ci.notes = (ci.notes or '') + ' [AI-extracted values]'
                db.session.commit()
            return jsonify(values)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── PSYCHOLOGICAL INTAKE ───────────────────────────────────────────────────

@app.route("/api/psych-intake/status")
@login_required
def api_psych_intake_status():
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if not intake:
        return jsonify({"started": False, "completed": False, "has_report": False, "locked": False})
    locked = intake.locked_until and _user_today() < intake.locked_until
    lockout_expired = intake.locked_until and _user_today() >= intake.locked_until
    return jsonify({
        "started": True,
        "completed": intake.completed,
        "has_report": intake.report is not None,
        "message_count": len(intake.conversation or []),
        "locked": bool(locked),
        "locked_until": intake.locked_until.isoformat() if locked else None,
        "lockout_expired": bool(lockout_expired),
    })


@app.route("/api/psych-intake/conversation")
@login_required
def api_psych_intake_conversation():
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if not intake:
        return jsonify({"conversation": [], "completed": False})
    return jsonify({
        "conversation": intake.conversation or [],
        "completed": intake.completed,
    })


# In-memory job store for async intake (works for single-worker deploys)
# NOTE: _intake_jobs is in-memory and per-worker. Multiple Gunicorn workers
# or multiple tabs can cause job_id mismatches. For production, use Redis.
# FLAG: Architecture change needed for distributed task queue.
_intake_jobs = {}


@app.route("/api/psych-intake/message", methods=["POST"])
@login_required
def api_psych_intake_message():
    try:
        data = request.get_json()
        user_msg = data.get("message", "").strip()

        intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
        if not intake:
            intake = PsychIntake(conversation=[], completed=False, user_id=current_user.id)
            db.session.add(intake)
            db.session.commit()

        # Check if locked out — return immediately (no background job needed)
        if intake.locked_until and _user_today() < intake.locked_until:
            days_left = (intake.locked_until - _user_today()).days
            return jsonify({
                "response": f"You're locked out for {days_left} more day{'s' if days_left != 1 else ''}. Come back when you've been alcohol-free for 7 days.",
                "completed": False,
                "locked": True,
                "locked_until": intake.locked_until.isoformat(),
            })

        # First message trigger
        is_first = not intake.conversation and not user_msg
        if is_first:
            user_msg = "[START]"

        if not user_msg:
            return jsonify({"error": "Message required"}), 400

        # Add user message to conversation
        convo = list(intake.conversation or [])
        if not is_first:
            convo.append({"role": "user", "content": user_msg})

        # Build history for API
        if is_first:
            history_for_api = []
        else:
            history_for_api = convo[:-1]

        # Extract and save the user's name (response to Q1: "What's your name?")
        # The first user message in the conversation is their name
        user_messages = [m for m in convo if m.get("role") == "user"]
        if len(user_messages) == 1 and not is_first:
            # This is the first user response — their name
            name = user_msg.strip().title()
            if name and len(name) < 50:
                current_user.name = name
                db.session.commit()

        # Save user message to DB immediately so it's not lost
        intake.conversation = convo
        db.session.commit()

        # Check for existing pending job — prevent duplicate threads
        for jid, job in _intake_jobs.items():
            if job.get("status") == "pending":
                return jsonify({"job_id": jid, "status": "pending"})

        # Create a job and run Claude in a background thread
        job_id = str(uuid.uuid4())[:8]
        _intake_jobs[job_id] = {"status": "pending", "result": None}

        # Capture values for the thread closure
        _user_msg = user_msg
        _is_first = is_first
        _history_for_api = list(history_for_api)

        def run_intake():
            try:
                # ONLY call Claude API here — no DB access in background thread
                response_text, is_complete = get_intake_response(
                    _user_msg, _history_for_api
                )
                _intake_jobs[job_id] = {
                    "status": "done",
                    "response_text": response_text,
                    "is_complete": is_complete,
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                _intake_jobs[job_id] = {
                    "status": "error",
                    "response_text": "Connection issue. Tap to retry.",
                    "is_complete": False,
                }

        thread = threading.Thread(target=run_intake)
        thread.start()

        return jsonify({"job_id": job_id, "status": "pending"})

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/psych-intake/result/<job_id>")
@login_required
def api_psych_intake_result(job_id):
    job = _intake_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] == "pending":
        return jsonify({"status": "pending"})

    # Job is done — save response to DB now (in the request thread, not background)
    response_text = job.get("response_text", "")
    is_complete = job.get("is_complete", False)
    del _intake_jobs[job_id]

    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if not intake:
        return jsonify({"status": "error", "response": "Intake not found"}), 500

    convo = list(intake.conversation or [])

    is_locked = "[INTAKE_LOCKED]" in response_text
    if is_locked:
        response_text = response_text.replace("[INTAKE_LOCKED]", "").strip()
        intake.locked_until = _user_today() + timedelta(days=7)

    convo.append({"role": "assistant", "content": response_text})
    intake.conversation = convo

    if is_complete and not is_locked:
        intake.completed = True
        lifting_data = _serialize_weights()
        report = generate_intake_report(convo, lifting_data=lifting_data)
        if report:
            intake.report = report

    db.session.commit()

    result = {
        "status": "done" if not job.get("status") == "error" else "error",
        "response": response_text,
        "completed": is_complete and not is_locked,
        "has_report": intake.report is not None,
        "report_error": is_complete and intake.report is None,
    }
    if is_locked:
        result["locked"] = True
        result["locked_until"] = intake.locked_until.isoformat()
    return jsonify(result)


@app.route("/api/psych-intake/report")
@login_required
def api_psych_intake_report():
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if not intake or not intake.report:
        return jsonify({"error": "No report available"}), 404
    return jsonify({"report": intake.report})


@app.route("/api/psych-intake/reset", methods=["POST"])
@login_required
def api_psych_intake_reset():
    PsychIntake.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/full-profile/generate", methods=["POST"])
@login_required
def api_generate_full_profile():
    """Generate the complete athlete profile after psych + physical are done."""
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if not intake or not intake.conversation:
        return jsonify({"error": "No intake conversation"}), 400

    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    latest_bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    physical_data = None
    if pa:
        physical_data = {
            "bodyweight": latest_bw.weight_lbs if latest_bw else pa.bodyweight_lbs,
            "height": pa.height_inches,
            "waist": pa.waist_inches,
            "has_gym": pa.has_gym,
            "pushup_count": pa.pushup_count,
            "pushup_from_knees": pa.pushup_from_knees,
            "plank_seconds": pa.plank_seconds,
            "squat_count": pa.squat_count,
            "pullup_count": pa.pullup_count,
        }

    lifting_data = _serialize_weights()

    # Run in background thread to avoid Gunicorn timeout
    job_id = str(uuid.uuid4())[:8]
    _intake_jobs[job_id] = {"status": "pending"}

    def run_profile():
        try:
            profile = generate_full_profile(
                intake.conversation,
                physical_data=physical_data,
                lifting_data=lifting_data,
            )
            _intake_jobs[job_id] = {
                "status": "done" if profile else "error",
                "profile": profile,
            }
        except Exception as e:
            _intake_jobs[job_id] = {"status": "error", "profile": None, "error": str(e)}

    thread = threading.Thread(target=run_profile)
    thread.start()
    return jsonify({"job_id": job_id, "status": "pending"})


@app.route("/api/full-profile/result/<job_id>")
@login_required
def api_full_profile_result(job_id):
    job = _intake_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] == "pending":
        return jsonify({"status": "pending"})
    profile = job.get("profile")
    del _intake_jobs[job_id]
    if profile:
        # Save to intake record
        intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
        if intake:
            intake.report = profile
            db.session.commit()
    return jsonify({"status": job["status"], "profile": profile})


# ─── AI COACH CHAT ──────────────────────────────────────────────────────────

_chat_rate_limit = {}  # user_id → last_send_timestamp

@app.route("/api/chat/history")
@login_required
def api_chat_history():
    days = request.args.get("days", 7, type=int)
    limit = request.args.get("limit", 100, type=int)
    since = _user_today() - timedelta(days=days)
    messages = ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= since
    ).order_by(ChatMessage.created_at).limit(limit).all()
    return jsonify([{
        "role": m.role,
        "content": m.content,
        "date": m.log_date.isoformat(),
        "time": m.created_at.strftime("%I:%M %p") if m.created_at else None,
    } for m in messages])


@app.route("/api/chat/clear", methods=["POST"])
@login_required
def api_chat_clear():
    ChatMessage.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Message required"}), 400

    # Handle /rule commands before normal chat processing
    if user_msg.startswith('/rule'):
        return _handle_rule_command(user_msg)

    # Double-send protection
    import time as _time
    _now = _time.time()
    _last = _chat_rate_limit.get(current_user.id, 0)
    if _now - _last < 2:
        return jsonify({"error": "Too fast — wait a moment"}), 429
    _chat_rate_limit[current_user.id] = _now

    mode = data.get('mode', 'chat')

    # Save user message
    user_chat = ChatMessage(role="user", content=user_msg, log_date=_user_today(), user_id=current_user.id, message_type=mode)
    db.session.add(user_chat)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500

    # Route trigger and build context
    from coach_router import route_trigger
    _route_info = route_trigger(user_msg)

    # Build context for the AI coach
    from coach_assembler import build_filtered_context
    context = build_filtered_context(_route_info["agent_name"])
    # "good enough" triggers Lombardi mode (demo keyword)
    if "good enough" in user_msg.lower():
        context["_force_angry"] = True

    # Get AI response
    from coach_assembler import assemble_prompt
    from coach import _build_messages
    from coach_agents import AGENTS
    import anthropic

    system_prompt = assemble_prompt(_route_info["agent_name"], context)
    messages = _build_messages(user_msg, context.get("chat_history", []), user_timezone=context.get("user_timezone"))
    agent_config = AGENTS.get(_route_info["agent_name"], AGENTS["conversation"])

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=CLAUDE_OPUS,
        max_tokens=agent_config["max_tokens"],
        temperature=agent_config["temperature"],
        system=system_prompt,
        messages=messages,
    )
    response_text = response.content[0].text

    # Save assistant message
    asst_chat = ChatMessage(role="assistant", content=response_text, log_date=_user_today(), user_id=current_user.id, message_type=mode)
    db.session.add(asst_chat)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500

    # Fire compliance events
    try:
        from coach_state import update_anger_level
        trigger = _route_info.get("trigger")
        if trigger == "WORKOUT_COMPLETE":
            update_anger_level(current_user.id, "completed_workout")
        elif trigger == "MEALS_COMPLETE":
            update_anger_level(current_user.id, "completed_workout")  # partial compliance
    except Exception:
        pass

    # Extract and save memories (runs in background, non-blocking)
    uid = current_user.id
    week = context.get("week", 1)
    _app = app

    def _save_memories():
        with _app.app_context():
            try:
                memories = extract_memories(user_msg, response_text, context)
                for mem in memories:
                    if mem.get('type') == 'rule':
                        existing = CoachRule.query.filter_by(user_id=uid, rule_text=mem['content'], active=True).first()
                        if not existing:
                            db.session.add(CoachRule(user_id=uid, rule_text=mem['content'], category='correction', source='auto'))
                    else:
                        cm = CoachMemory(
                            user_id=uid, content=mem["content"],
                            memory_type=mem["type"], week=week,
                        )
                        db.session.add(cm)
                if memories:
                    db.session.commit()
            except Exception:
                pass  # Memory extraction is best-effort

    import threading
    threading.Thread(target=_save_memories, daemon=True).start()

    return jsonify({
        "response": response_text,
        "time": asst_chat.created_at.strftime("%I:%M %p") if asst_chat.created_at else None,
    })


def _handle_rule_command(msg):
    """Handle /rule commands: list, delete, or add rules."""
    parts = msg.strip().split(None, 2)
    cmd = parts[1] if len(parts) > 1 else ""

    if cmd == "delete" and len(parts) > 2:
        try:
            rule_id = int(parts[2])
        except ValueError:
            return jsonify({"response": "Usage: /rule delete <id>"})
        rule = CoachRule.query.filter_by(id=rule_id, user_id=current_user.id).first()
        if rule:
            rule.active = False
            db.session.commit()
            return jsonify({"response": f"Rule #{rule_id} deactivated."})
        return jsonify({"response": "Rule not found."}), 404

    if not cmd or cmd == "list":
        rules = CoachRule.query.filter_by(user_id=current_user.id, active=True).all()
        if not rules:
            return jsonify({"response": "No active rules."})
        lines = [f"#{r.id}: {r.rule_text} [{r.category}]" for r in rules]
        return jsonify({"response": "Active rules:\n" + "\n".join(lines)})

    # Anything else is a new rule
    rule_text = msg[len('/rule '):].strip()
    if rule_text:
        db.session.add(CoachRule(user_id=current_user.id, rule_text=rule_text, category='preference', source='manual'))
        db.session.commit()
        return jsonify({"response": f'Rule saved: "{rule_text}"'})
    return jsonify({"response": "Usage: /rule <text> | /rule list | /rule delete <id>"})


@app.route("/api/rules")
@login_required
def api_rules():
    """List all active coaching rules for the current user."""
    rules = CoachRule.query.filter_by(user_id=current_user.id, active=True).order_by(CoachRule.created_at).all()
    return jsonify([{"id": r.id, "rule": r.rule_text, "category": r.category, "source": r.source} for r in rules])


@app.route("/api/chat/stream", methods=["POST"])
@login_required
def api_chat_stream():
    """Streaming coach response via SSE."""
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Message required"}), 400

    # Handle /rule commands before normal chat processing
    if user_msg.startswith('/rule'):
        return _handle_rule_command(user_msg)

    # Double-send protection
    import time as _time
    _now = _time.time()
    _last = _chat_rate_limit.get(current_user.id, 0)
    if _now - _last < 2:
        return jsonify({"error": "Too fast — wait a moment"}), 429
    _chat_rate_limit[current_user.id] = _now

    mode = data.get('mode', 'chat')

    # Save user message
    _log_date = _user_today()
    user_chat = ChatMessage(role="user", content=user_msg, log_date=_log_date, user_id=current_user.id, message_type=mode)
    db.session.add(user_chat)
    db.session.commit()

    _current_user_id = current_user.id
    _mode = mode

    # Route trigger and build context
    from coach_router import route_trigger
    _route_info = route_trigger(user_msg)

    try:
        from coach_assembler import build_filtered_context
        context = build_filtered_context(_route_info["agent_name"])
        # "good enough" triggers Lombardi mode (demo keyword)
        if "good enough" in user_msg.lower():
            context["_force_angry"] = True
    except Exception as ctx_err:
        import logging
        logging.error("Coach context build failed: %s", ctx_err)
        context = {"athlete_name": current_user.name or "Athlete", "user_timezone": getattr(current_user, 'timezone', 'UTC'), "chat_history": [], "week": 1}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "API key not configured"}), 500

    _app = app

    def generate():
        full_text = ""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=30.0)

            from coach_assembler import assemble_prompt
            from coach import _build_messages
            from coach_agents import AGENTS
            system_prompt = assemble_prompt(_route_info["agent_name"], context)
            messages = _build_messages(user_msg, context.get("chat_history", []), user_timezone=context.get("user_timezone"))
            _agent_config = AGENTS.get(_route_info["agent_name"], AGENTS["conversation"])

            with client.messages.stream(
                model=CLAUDE_OPUS,
                max_tokens=_agent_config["max_tokens"],
                temperature=_agent_config["temperature"],
                system=system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    # SSE data field cannot contain raw newlines — they break the parser
                    # Replace \n with a placeholder, client converts back
                    safe_text = text.replace('\n', '\\n')
                    yield f"data: {safe_text}\n\n"

            yield f"data: [DONE]\n\n"
        except GeneratorExit:
            import logging
            logging.warning("Client disconnected mid-stream")
        except Exception as e:
            import logging
            logging.error("Stream error: %s", e)
            yield f"data: [ERROR]\n\n"
        finally:
            # ALWAYS save the response if we got any text — even partial
            if full_text.strip():
                try:
                    with _app.app_context():
                        asst_chat = ChatMessage(role="assistant", content=full_text, log_date=_log_date, user_id=_current_user_id, message_type=_mode)
                        db.session.add(asst_chat)
                        db.session.commit()
                except Exception:
                    pass

                # Extract memories from conversation (same as non-streaming endpoint)
                try:
                    def _save_memories_stream():
                        with _app.app_context():
                            try:
                                memories = extract_memories(user_msg, full_text, context)
                                for mem in memories:
                                    if mem.get('type') == 'rule':
                                        existing = CoachRule.query.filter_by(user_id=_current_user_id, rule_text=mem['content'], active=True).first()
                                        if not existing:
                                            db.session.add(CoachRule(user_id=_current_user_id, rule_text=mem['content'], category='correction', source='auto'))
                                    else:
                                        cm = CoachMemory(
                                            user_id=_current_user_id, content=mem["content"],
                                            memory_type=mem["type"], week=context.get("week", 1),
                                        )
                                        db.session.add(cm)
                                if memories:
                                    db.session.commit()
                            except Exception:
                                pass  # Memory extraction is best-effort

                    threading.Thread(target=_save_memories_stream, daemon=True).start()
                except Exception:
                    pass

                # Parse structured markers from coach response
                try:
                    _parse_coach_markers(full_text, _current_user_id, context.get("week", 1))
                except Exception:
                    pass

                # Fire compliance events
                try:
                    from coach_state import update_anger_level
                    trigger = _route_info.get("trigger")
                    if trigger == "WORKOUT_COMPLETE":
                        update_anger_level(_current_user_id, "completed_workout")
                except Exception:
                    pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route('/api/coach/daily-opener')
@login_required
def api_daily_opener():
    """Returns today's morning opener. Generates if not yet created."""
    today = _user_today()

    # Check daily state
    state = DailyCoachState.query.filter_by(user_id=current_user.id, state_date=today).first()

    # Check if opener already exists
    existing = ChatMessage.query.filter_by(
        user_id=current_user.id, log_date=today
    ).filter(~ChatMessage.content.contains('[MORNING_CHECKIN]')).filter_by(
        role='assistant'
    ).order_by(ChatMessage.created_at.asc()).first()

    # Check if already dismissed
    already_seen = state and state.opener_dismissed_at is not None

    if existing and state and state.opener_shown_at:
        return jsonify({'message': existing.content, 'already_seen': already_seen})

    # Not yet generated — trigger it
    if not state:
        state = DailyCoachState(user_id=current_user.id, state_date=today)
        db.session.add(state)
    state.opener_shown_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({'message': None, 'needs_generation': True, 'already_seen': False})


@app.route('/api/coach/dismiss-opener', methods=['POST'])
@login_required
def api_dismiss_opener():
    today = _user_today()
    state = DailyCoachState.query.filter_by(user_id=current_user.id, state_date=today).first()
    if not state:
        state = DailyCoachState(user_id=current_user.id, state_date=today)
        db.session.add(state)
    state.opener_dismissed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/coach/today-history')
@login_required
def api_coach_today_history():
    """Today's chat messages only, excluding internal triggers."""
    today = _user_today()
    messages = ChatMessage.query.filter_by(
        user_id=current_user.id, log_date=today
    ).order_by(ChatMessage.created_at.asc()).all()

    result = []
    for m in messages:
        content = m.content or ''
        # Skip internal trigger messages
        if content.startswith('[MORNING_CHECKIN]') or content.startswith('[WORKOUT_COMPLETE]') or content.startswith('[MEALS_COMPLETE]') or content.startswith('[END_OF_DAY]'):
            continue
        result.append({
            'role': m.role,
            'content': content,
            'type': getattr(m, 'message_type', 'chat') or 'chat',
            'time': m.created_at.strftime('%I:%M %p') if m.created_at else None,
        })
    return jsonify(result)


def _build_coach_context():
    """Gather all relevant data for the AI coach."""
    local_today = _user_today()
    week = _current_week()

    # Recent morning check-ins
    since = local_today - timedelta(days=14)
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
        MorningCheckIn.user_id == current_user.id,
        MorningCheckIn.log_date >= since
    ).order_by(MorningCheckIn.log_date).all()]

    # Chat history — full current week (Mon-Sun) + older context
    week_start = local_today - timedelta(days=local_today.weekday())  # Monday of this week
    chat_history = [{
        "role": m.role,
        "content": m.content,
        "date": m.log_date.isoformat() if m.log_date else None,
    } for m in ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= week_start  # Full current week, not just 14 days
    ).order_by(ChatMessage.created_at).all()]
    # Also include older context (up to 14 days before this week) for continuity
    older_msgs = ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= since,
        ChatMessage.log_date < week_start
    ).order_by(ChatMessage.created_at).limit(50).all()
    older_history = [{"role": m.role, "content": m.content, "date": m.log_date.isoformat() if m.log_date else None} for m in older_msgs]
    chat_history = older_history + chat_history

    # Body weight — all entries (user weighs weekly, not daily)
    bw_entries = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date).all()
    bodyweight = [{
        "date": e.log_date.isoformat(),
        "weight": e.weight_lbs,
    } for e in bw_entries]

    # Garmin data
    garmin_data = None
    readiness_data = None
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if gc.connected:
        garmin_data = gc.get_today_summary()
        readiness_data = assess_readiness(garmin_data)

    # Current state
    s = _get_state()
    phase = get_phase(week)
    phase_info = PHASES[phase]

    # Today's workout — use user's local day of week
    workouts = get_workouts(week)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today_idx = local_today.weekday()  # 0=Mon
    workout_today = workouts[today_idx] if today_idx < len(workouts) else None

    # Overlay ALL DB data onto workout_today (templates are stale defaults)
    try:
        # Exercises from WeeklyPrescription
        _db_rx = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).order_by(WeeklyPrescription.exercise_order).all()
        if _db_rx and workout_today:
            workout_today["exercises"] = [
                {"name": rx.exercise_name, "sets": f"{rx.sets}x{rx.reps}",
                 "rest": rx.rest or "60s", "note": rx.note or "",
                 "target_weight": getattr(rx, 'target_weight', None)}
                for rx in _db_rx
            ]
    except Exception:
        pass
    try:
        # Meal plan from WeeklyMealPlan
        _db_meal = WeeklyMealPlan.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).order_by(WeeklyMealPlan.id.desc()).first()
        if _db_meal and _db_meal.meal_data and workout_today:
            workout_today["mealPlan"] = _db_meal.meal_data
    except Exception:
        pass
    try:
        # Run plan from WeeklyRunPlan
        _db_run = WeeklyRunPlan.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).first()
        if _db_run and workout_today:
            workout_today["run"] = {"type": _db_run.run_type, "label": _db_run.label,
                                     "time": _db_run.duration, "detail": _db_run.detail or ""}
    except Exception:
        pass
    try:
        # Warmup from WeeklyWarmup
        _db_warmup = WeeklyWarmup.query.filter_by(
            user_id=current_user.id, week=week, day_idx=today_idx
        ).first()
        if _db_warmup and _db_warmup.warmup_data and workout_today:
            workout_today["warmup"] = _db_warmup.warmup_data
    except Exception:
        pass

    # Full week schedule from DB (not templates)
    week_schedule = []
    try:
        _db_schedules = WeeklyDaySchedule.query.filter_by(
            user_id=current_user.id, week=week
        ).order_by(WeeklyDaySchedule.day_idx).all()
        if _db_schedules:
            for ds in _db_schedules:
                week_schedule.append({
                    "day_idx": ds.day_idx,
                    "day": day_names[ds.day_idx] if ds.day_idx < 7 else "?",
                    "liftName": ds.lift_name or "Rest",
                    "isRest": ds.is_rest or False,
                })
    except Exception:
        pass
    if not week_schedule:
        # Fallback to templates if no DB schedule exists
        for i, w in enumerate(workouts):
            week_schedule.append({
                "day_idx": i,
                "day": day_names[i],
                "liftName": w.get("liftName", "Rest"),
                "isRest": w.get("isRest", False),
            })

    # Supplements today
    supps = SupplementLog.query.filter_by(user_id=current_user.id, log_date=local_today).all()
    supps_taken = {s.supplement_name: s.taken for s in supps}

    # Psych intake report (contains aspirational body type, goals, etc.)
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    intake_report = intake.report if intake and intake.report else None

    # Food restrictions and allergies (SAFETY CRITICAL)
    constraints = UserConstraints.query.filter_by(user_id=current_user.id).first()
    food_restrictions = constraints.food_restrictions if constraints else []
    custom_allergies = constraints.custom_allergies if constraints else None

    # User's selected foods
    fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()
    selected_foods_summary = None
    if fs and fs.selected_foods:
        selected_foods_summary = fs.selected_foods

    # Training goal (full record)
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    fasting_protocol = goal.fasting_protocol if goal else None
    goal_data = None
    if goal:
        goal_data = {
            "goal_type": goal.goal_type,
            "target_weight": goal.target_weight,
            "target_bf_pct": goal.target_bf_pct,
            "daily_calories": goal.daily_calories,
            "protein_grams": goal.protein_grams,
            "carb_grams": goal.carb_grams,
            "fat_grams": goal.fat_grams,
            "fasting_protocol": goal.fasting_protocol,
            "calorie_by_day_type": goal.calorie_by_day_type,
        }

    # Exercise history — last 3 entries per exercise (shows progression)
    exercise_logs = ExerciseLog.query.filter_by(user_id=current_user.id).order_by(
        ExerciseLog.logged_date.desc(), ExerciseLog.id.desc()
    ).limit(200).all()
    from workout_data import resolve_name
    exercise_history = {}
    for log in exercise_logs:
        canonical = resolve_name(log.exercise_name)
        if canonical not in exercise_history:
            exercise_history[canonical] = []
        if len(exercise_history[canonical]) < 3:
            entry = {
                "weight": log.weight, "rpe": log.rpe,
                "reps_completed": log.reps_completed,
                "week": log.week,
                "date": log.logged_date.isoformat() if log.logged_date else None,
            }
            if log.estimated_1rm:
                entry["estimated_1rm"] = log.estimated_1rm
            exercise_history[canonical].append(entry)

    # Per-set data for today — use date-based query, not week number
    today_idx = local_today.weekday()
    today_sets = SetLog.query.filter(
        SetLog.user_id == current_user.id,
        SetLog.logged_date == local_today,
        SetLog.done == True
    ).order_by(SetLog.exercise_name, SetLog.set_number).all()
    set_data = {}
    for s in today_sets:
        canonical = resolve_name(s.exercise_name)
        if canonical not in set_data:
            set_data[canonical] = []
        set_data[canonical].append({
            "set": s.set_number + 1, "weight": s.weight,
            "reps": s.reps, "done": s.done,
            "target_weight": getattr(s, 'target_weight', None),
            "target_reps": getattr(s, 'target_reps', None),
            "modification_direction": getattr(s, 'modification_direction', None),
        })

    # Run logs (last 14 days)
    run_logs = RunLog.query.filter_by(user_id=current_user.id).order_by(
        RunLog.log_date.desc()
    ).limit(14).all()
    runs = [{
        "date": r.log_date.isoformat() if r.log_date else None,
        "distance_miles": r.distance_miles, "avg_hr": r.avg_hr,
        "elevation_ft": r.elevation_ft, "week": r.week,
    } for r in run_logs]

    # Physical assessment (baseline)
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    physical = None
    if pa:
        physical = {
            "height_inches": pa.height_inches,
            "bodyweight_lbs": pa.bodyweight_lbs,
            "waist": pa.waist_inches, "chest": pa.chest_inches,
            "bicep": pa.bicep_inches, "thigh": pa.thigh_inches,
            "neck": pa.neck_inches, "hips": pa.hips_inches,
            "pushups": pa.pushup_count, "plank_sec": pa.plank_seconds,
            "squats": pa.squat_count, "pullups": pa.pullup_count,
        }

    # Body measurements (last 4 for trend visibility)
    recent_measures = BodyMeasurement.query.filter_by(
        user_id=current_user.id
    ).order_by(BodyMeasurement.log_date.desc()).limit(4).all()
    measurements = [{"date": m.log_date.isoformat(), "waist": m.waist_inches} for m in recent_measures] if recent_measures else []

    # Equipment
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    equipment = eq.available_equipment if eq else []

    # Meal adherence today + today's meal plan (use local_today, not server UTC)
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=local_today).first()
    meals_today = None
    if ml:
        meals_today = {
            "eaten": ml.eaten or [],
            "fasting": ml.fasting,
            "scheduled_time": ml.scheduled_time if hasattr(ml, 'scheduled_time') else None,
            "actual_time": ml.actual_time if hasattr(ml, 'actual_time') else None,
        }

    # Weekly meal logs (so coach knows which days had meals tracked)
    week_monday = local_today - timedelta(days=local_today.weekday())
    week_meals = MealLog.query.filter(
        MealLog.user_id == current_user.id,
        MealLog.log_date >= week_monday,
        MealLog.log_date <= local_today
    ).all()
    weekly_meals_summary = []
    for ml_entry in week_meals:
        eaten_count = len(ml_entry.eaten) if isinstance(ml_entry.eaten, list) else 0
        weekly_meals_summary.append({
            "date": ml_entry.log_date.isoformat(),
            "day": day_names[ml_entry.log_date.weekday()] if ml_entry.log_date.weekday() < 7 else "?",
            "meals_logged": eaten_count,
        })

    # Today's meal plan (what they're supposed to eat)
    todays_meal_plan = None
    if workout_today and workout_today.get("mealPlan"):
        mp = workout_today["mealPlan"]
        todays_meal_plan = {
            "type": mp.get("label", ""),
            "target_cal": mp.get("targetCal"),
            "target_protein": mp.get("targetProtein"),
            "meals": [{"time": m.get("time", ""), "name": m.get("name", ""),
                       "foods": [f["item"] for f in m.get("foods", [])]}
                      for m in mp.get("meals", [])],
        }

    # Fasting state — compute hours since last meal for coach context
    fasting_state = None
    try:
        _fasting_protocol = goal.fasting_protocol if goal else "16_8"
        from meal_generator import _FASTING_PROTOCOLS
        _proto = _FASTING_PROTOCOLS.get(_fasting_protocol, _FASTING_PROTOCOLS["16_8"])
        _eating_end = _proto["end"]  # e.g., "6:30pm"
        # Parse end time
        _end_parts = _eating_end.replace("am", "").replace("pm", "")
        _end_h = int(_end_parts.split(":")[0])
        _end_m = int(_end_parts.split(":")[1]) if ":" in _end_parts else 0
        if "pm" in _eating_end and _end_h != 12:
            _end_h += 12
        # Look back: find the last day that had meals (not a fast day)
        _last_eating_day = None
        for _lookback in range(7):
            _check_date = local_today - timedelta(days=_lookback)
            _check_day_idx = _check_date.weekday()
            _day_meal_type = _get_day_meal_type(current_user.id, week, _check_day_idx)
            if _day_meal_type != 'fast_day':
                if _lookback == 0:
                    # Today is an eating day — not in an extended fast from a fast day
                    break
                _last_eating_day = _check_date
                break
        if _last_eating_day:
            from datetime import datetime as _dt
            _last_meal_time = _dt(_last_eating_day.year, _last_eating_day.month, _last_eating_day.day, _end_h, _end_m)
            _now = _dt.now()
            try:
                from utils_time import user_local_now
                _now = user_local_now(getattr(current_user, 'timezone', None) or 'UTC')
            except Exception:
                pass
            _hours_fasted = (_now - _last_meal_time).total_seconds() / 3600
            _eating_start = _proto["start"]  # e.g., "11:00am"
            fasting_state = {
                "hours_fasted": round(_hours_fasted, 1),
                "last_meal_day": _last_eating_day.strftime("%A"),
                "last_meal_time": _eating_end,
                "eating_window_opens": _eating_start,
                "is_expected": True,  # This IS the planned fast
            }
    except Exception:
        pass

    # Day completion status (this week) — use DATE-BASED query, not week number
    # The week number in SetLog may not match _current_week() due to frontend/backend mismatch
    week_monday = local_today - timedelta(days=local_today.weekday())
    completed_days = []

    # Check DayCompletion by both week number AND date range
    day_completions = DayCompletion.query.filter_by(
        user_id=current_user.id, week=week
    ).all()
    for dc in day_completions:
        if dc.done and dc.day_idx not in completed_days:
            completed_days.append(dc.day_idx)

    # Check SetLog by date range AND by any week number (catches ALL mismatches)
    week_sets = SetLog.query.filter(
        SetLog.user_id == current_user.id,
        SetLog.done == True,
        SetLog.logged_date >= week_monday
    ).all()
    for s in week_sets:
        if s.day_idx not in completed_days:
            completed_days.append(s.day_idx)
    # Also check by ALL week numbers user might have used (old stale week values)
    all_week_sets = SetLog.query.filter(
        SetLog.user_id == current_user.id,
        SetLog.done == True,
    ).all()
    for s in all_week_sets:
        # Map logged_date to day_idx if within this calendar week
        if s.logged_date and s.logged_date >= week_monday and s.logged_date <= local_today:
            if s.day_idx not in completed_days:
                completed_days.append(s.day_idx)

    # Enrich completed_days with day name and workout name
    completed_days_enriched = []
    for di in completed_days:
        entry = {"day_idx": di, "day": day_names[di] if di < 7 else "?"}
        if di < len(workouts):
            entry["liftName"] = workouts[di].get("liftName", "")
        completed_days_enriched.append(entry)

    # Schedule notes
    schedule_notes = constraints.schedule_notes if constraints else None

    # Coach memory — persistent observations across conversations
    memories = CoachMemory.query.filter_by(user_id=current_user.id).order_by(
        CoachMemory.created_at.desc()
    ).limit(20).all()
    coach_memories = [{"type": m.memory_type, "content": m.content, "week": m.week} for m in memories]

    # Compliance grade removed — tone is now fixed in coach.py

    # Check if missed morning checkin today
    missed_today = False
    mc_today = MorningCheckIn.query.filter_by(user_id=current_user.id, log_date=local_today).first()
    if mc_today and mc_today.notes and '[MISSED]' in (mc_today.notes or ''):
        missed_today = True

    # Latest session analysis
    latest_analysis = SessionAnalysis.query.filter_by(
        user_id=current_user.id
    ).order_by(SessionAnalysis.log_date.desc()).first()
    session_analysis = None
    if latest_analysis:
        session_analysis = {
            "date": latest_analysis.log_date.isoformat() if latest_analysis.log_date else None,
            "compliance": latest_analysis.overall_compliance,
            "muscles": latest_analysis.muscle_groups_trained,
            "deviations": latest_analysis.deviations,
            "summary": latest_analysis.summary_text,
        }

    # Weekly summary (for coach weekly check-in)
    weekly_summary = None
    try:
        from training_engine import generate_weekly_summary
        weekly_summary = generate_weekly_summary(current_user.id, week)
    except Exception:
        pass

    result = {
        "user_id": current_user.id,
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
        "athlete_name": current_user.name or "Athlete",
        "user_timezone": current_user.timezone if hasattr(current_user, 'timezone') else 'UTC',
        "scheduled_activities": _get_scheduled_activities(),
        "food_restrictions": food_restrictions,
        "custom_allergies": custom_allergies,
        "selected_foods": selected_foods_summary,
        "fasting_protocol": fasting_protocol,
        "fasting_state": fasting_state,
        # NEW — full athlete profile
        "goal": goal_data,
        "exercise_history": exercise_history,
        "today_sets": set_data,
        "run_history": runs,
        "physical_assessment": physical,
        "body_measurements": measurements,
        "equipment": equipment,
        "meals_today": meals_today,
        "weekly_meals_summary": weekly_meals_summary,
        "meal_plan_today": todays_meal_plan,
        "completed_days_this_week": completed_days_enriched,
        "week_schedule": week_schedule,
        "schedule_notes": schedule_notes,
        "coach_memories": coach_memories,
        "missed_checkin_today": missed_today,
        "session_analysis": session_analysis,
        "weekly_summary": weekly_summary,
        "today_meal_type": _get_day_meal_type(current_user.id, week, today_idx),
        # Skipped sets today
        "skipped_sets_today": [{"exercise": s.exercise_name, "set": s.set_number}
                               for s in today_sets if not s.done],
    }

    # Active overrides for this week (wrapped in try-except — tables may not exist yet)
    try:
        result["schedule_overrides"] = [{"day_idx": o.day_idx, "workout_time": o.workout_time, "skip_day": o.skip_day, "notes": o.notes}
                                        for o in WeeklyScheduleOverride.query.filter_by(user_id=current_user.id, week=week).all()]
    except Exception:
        result["schedule_overrides"] = []
    try:
        result["meal_overrides"] = [{"day_idx": o.day_idx, "meal_type": o.meal_type, "reason": o.reason}
                                    for o in MealPlanOverride.query.filter_by(user_id=current_user.id, week=week).all()]
    except Exception:
        result["meal_overrides"] = []
    try:
        result["run_overrides"] = [{"day_idx": o.day_idx, "duration": o.duration, "run_type": o.run_type, "reason": o.reason}
                                   for o in RunOverride.query.filter_by(user_id=current_user.id, week=week).all()]
    except Exception:
        result["run_overrides"] = []
    try:
        result["active_swaps"] = [{"day_idx": o.day_idx, "exercise_idx": o.exercise_idx, "swapped_to": o.swapped_to}
                                  for o in ExerciseSwap.query.filter_by(user_id=current_user.id, week=week).all()]
    except Exception:
        result["active_swaps"] = []

    # Next week's prescriptions (for Monday planning)
    try:
        next_week = week + 1
        if next_week <= 12:
            next_rx = WeeklyPrescription.query.filter_by(
                user_id=current_user.id, week=next_week
            ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()
            result["next_week_prescriptions"] = [
                {
                    "day_idx": rx.day_idx,
                    "exercise": rx.exercise_name,
                    "sets": rx.sets,
                    "reps": rx.reps,
                    "rest": rx.rest,
                    "target_weight": getattr(rx, 'target_weight', None),
                    "adjustment_reason": getattr(rx, 'adjustment_reason', None),
                    "progression_indicator": getattr(rx, 'progression_indicator', None),
                }
                for rx in next_rx
            ]
        else:
            result["next_week_prescriptions"] = []
    except Exception:
        result["next_week_prescriptions"] = []

    # Pre-computed engine analysis per exercise — authoritative progression decisions
    exercise_analysis = {}
    try:
        from training_engine import compute_next_targets
        for ex_name in list(exercise_history.keys()):
            try:
                analysis = compute_next_targets(current_user.id, ex_name, week, today_idx)
                exercise_analysis[ex_name] = {
                    "target_weight": analysis.get("target_weight"),
                    "target_reps": analysis.get("target_reps"),
                    "target_sets": analysis.get("target_sets"),
                    "adjustment_reason": analysis.get("adjustment_reason", ""),
                    "progression_indicator": analysis.get("progression_indicator", "hold"),
                    "coach_alert": analysis.get("coach_alert"),
                }
            except Exception:
                pass
    except Exception:
        pass
    result["exercise_analysis"] = exercise_analysis

    return result


def _get_scheduled_activities():
    """Get user's scheduled activities for coach context."""
    constraints = UserConstraints.query.filter_by(user_id=current_user.id).first()
    if not constraints or not constraints.scheduled_activities:
        return ""
    activities = constraints.scheduled_activities
    if not activities:
        return ""
    lines = ["Scheduled activities this athlete has committed to:"]
    for a in activities:
        lines.append(f"  - {a.get('day', '?')}: {a.get('activity', '?')} ({a.get('duration_min', '?')} min)")
    return "\n".join(lines)


# ─── PROGRESS PHOTOS ────────────────────────────────────────────────────────

@app.route("/api/photos")
@login_required
def api_photos():
    """Get all progress photos (metadata only, no image data)."""
    photos = ProgressPhoto.query.filter_by(user_id=current_user.id).order_by(ProgressPhoto.log_date).all()
    return jsonify([{
        "id": p.id,
        "date": p.log_date.isoformat(),
        "pose": p.pose,
        "week": p.week,
        "analysis": p.analysis,
        "has_photo": True,
    } for p in photos])


@app.route("/api/photos/<int:photo_id>/image")
@login_required
def api_photo_image(photo_id):
    """Get a specific photo's image data."""
    p = ProgressPhoto.query.filter_by(id=photo_id, user_id=current_user.id).first_or_404()
    return jsonify({"photo_data": p.photo_data})


@app.route("/api/photos", methods=["POST"])
@login_required
def api_photo_upload():
    """Upload a progress photo and get AI analysis."""
    data = request.get_json()
    photo_b64 = data.get("photo_data")
    pose = data.get("pose", "front")
    if not photo_b64:
        return jsonify({"error": "Photo data required"}), 400

    s = _get_state()
    week = _current_week()

    # Save photo
    photo = ProgressPhoto(
        log_date=_user_today(),
        photo_data=photo_b64,
        user_id=current_user.id,
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
        client = anthropic.Anthropic(api_key=api_key, timeout=45.0)
    except Exception:
        return "Photo saved. AI analysis unavailable."

    # Get previous photos for comparison
    prev_photos = ProgressPhoto.query.filter(
        ProgressPhoto.user_id == current_user.id,
        ProgressPhoto.pose == pose,
        ProgressPhoto.log_date < _user_today(),
    ).order_by(ProgressPhoto.log_date.desc()).limit(1).all()

    comparison_note = ""
    comparison_image = None
    if prev_photos:
        p = prev_photos[0]
        comparison_note = f"A previous {pose} photo from week {p.week} ({p.log_date.isoformat()}) is also provided for comparison."
        comparison_image = p.photo_data

    # Get body weight context
    bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    bw_note = f"Current body weight: {bw.weight_lbs} lb." if bw else ""

    # Get aspirational body type from psych intake
    aspiration_note = ""
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
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
            model=CLAUDE_OPUS,
            max_tokens=1000,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Photo saved. Analysis failed: {str(e)[:100]}"


# ─── GARMIN ─────────────────────────────────────────────────────────────────

@app.route("/api/garmin/login", methods=["POST"])
@login_required
def garmin_login():
    gc = _get_garmin()
    data = request.get_json()
    mfa_code = data.get("mfa_code") if data else None
    if mfa_code:
        success, error, needs_mfa = gc.login(None, None, user_id=current_user.id, mfa_code=mfa_code)
        if success:
            return jsonify({"connected": True})
        return jsonify({"connected": False, "error": error}), 401

    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email and password required"}), 400

    success, error, needs_mfa = gc.login(data["email"], data["password"], user_id=current_user.id)
    if success:
        return jsonify({"connected": True})
    if needs_mfa:
        return jsonify({"connected": False, "needs_mfa": True, "error": "Enter the verification code from your authenticator app"})
    return jsonify({"connected": False, "error": error}), 401


@app.route("/api/garmin/status")
@login_required
def garmin_status():
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    return jsonify({"connected": gc.connected})


@app.route("/api/garmin/today")
@login_required
def garmin_today():
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        return jsonify({"error": "Not connected to Garmin"}), 401
    summary = gc.get_today_summary()
    if summary is None:
        return jsonify({"error": "Failed to fetch Garmin data"}), 500
    return jsonify(summary)


@app.route("/api/garmin/readiness")
@login_required
def garmin_readiness():
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        return jsonify(assess_readiness(None))
    summary = gc.get_today_summary()
    return jsonify(assess_readiness(summary))


@app.route("/api/garmin/hrv-trend")
@login_required
def garmin_hrv_trend():
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        return jsonify({"error": "Not connected"}), 401
    return jsonify(gc.get_weekly_hrv() or [])


@app.route("/api/garmin/save-tokens", methods=["POST"])
@login_required
def garmin_save_tokens():
    """Save Garmin tokens from an external login (e.g. local CLI)."""
    data = request.get_json()
    tokens = data.get("tokens")
    if not tokens:
        return jsonify({"error": "tokens required"}), 400
    try:
        from garminconnect import Garmin as G
        gc = _get_garmin()
        gc.api = G()
        gc.api.login(tokenstore=tokens)
        gc._connected = True
        gc._cache = {}
        gc._user_id = current_user.id
        gc._save_tokens()
        return jsonify({"connected": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/garmin/logout", methods=["POST"])
@login_required
def garmin_logout():
    gc = _get_garmin()
    gc.api = None
    gc._connected = False
    gc._cache = {}
    uid = current_user.id
    if uid in _garmin_clients:
        del _garmin_clients[uid]
    session.pop("garmin_connected", None)
    return jsonify({"connected": False})


# ─── TIMEZONE ──────────────────────────────────────────────────────────────

@app.route('/api/user/timezone', methods=['POST'])
@login_required
def api_user_timezone():
    """Update user's timezone from browser detection."""
    data = request.get_json()
    tz = data.get('timezone', '').strip()
    if not tz:
        return jsonify({'error': 'timezone required'}), 400
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        try:
            import pytz
            pytz.timezone(tz)
        except Exception:
            return jsonify({'error': 'invalid timezone'}), 400
    current_user.timezone = tz
    db.session.commit()
    return jsonify({'timezone': tz})


# ─── PUSH NOTIFICATIONS ────────────────────────────────────────────────────

_push_subscriptions = []  # In-memory for now; could be stored in DB

@app.route("/api/push/vapid-key")
@login_required
def api_vapid_key():
    key = os.environ.get("VAPID_PUBLIC_KEY")
    if not key:
        return jsonify({"error": "Push not configured"}), 404
    return jsonify({"publicKey": key})


@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def api_push_subscribe():
    data = request.get_json()
    sub = data.get("subscription")
    if not sub:
        return jsonify({"error": "subscription required"}), 400
    # Deduplicate
    if sub not in _push_subscriptions:
        _push_subscriptions.append(sub)
    return jsonify({"ok": True})


@app.route("/api/push/test", methods=["POST"])
@login_required
def api_push_test():
    """Send a test push notification."""
    vapid_private = os.environ.get("VAPID_PRIVATE_KEY")
    vapid_email = os.environ.get("VAPID_EMAIL", "mailto:test@example.com")
    if not vapid_private or not _push_subscriptions:
        return jsonify({"error": "Push not configured or no subscribers"}), 400
    try:
        from pywebpush import webpush
        import json
        for sub in _push_subscriptions:
            webpush(
                subscription_info=sub,
                data=json.dumps({"title": "12 Weeks", "body": "Time for your morning check-in!", "tag": "morning-checkin"}),
                vapid_private_key=vapid_private,
                vapid_claims={"sub": vapid_email},
            )
        return jsonify({"ok": True, "sent": len(_push_subscriptions)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── CONSTRAINTS ───────────────────────────────────────────────────────────

@app.route("/api/constraints")
@login_required
def api_constraints():
    c = UserConstraints.query.filter_by(user_id=current_user.id).first()
    if not c:
        return jsonify({"completed": False})
    return jsonify({
        "completed": c.completed,
        "food_restrictions": c.food_restrictions or [],
        "custom_allergies": c.custom_allergies,
        "scheduled_activities": c.scheduled_activities or [],
        "schedule_notes": c.schedule_notes,
    })

@app.route("/api/constraints", methods=["POST"])
@login_required
def api_constraints_save():
    data = request.get_json()
    c = UserConstraints.query.filter_by(user_id=current_user.id).first()
    if not c:
        c = UserConstraints(user_id=current_user.id)
        db.session.add(c)
    if "food_restrictions" in data:
        c.food_restrictions = data["food_restrictions"]
    if "custom_allergies" in data:
        c.custom_allergies = data["custom_allergies"]
    if "scheduled_activities" in data:
        c.scheduled_activities = data["scheduled_activities"]
    if "schedule_notes" in data:
        c.schedule_notes = data["schedule_notes"]
    if "completed" in data:
        c.completed = data["completed"]
    db.session.commit()
    return jsonify({"ok": True})


# ─── GOAL COMPUTATION ─────────────────────────────────────────────────────

@app.route("/api/goal/compute", methods=["POST"])
@login_required
def api_goal_compute():
    """Compute training goal from intake + physical data."""
    from goal_engine import (
        detect_goal, compute_tdee, compute_targets,
        compute_phase_plan, compute_day_calories,
        determine_fasting_protocol, project_weight_curve,
    )

    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    existing_goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not intake and not existing_goal:
        return jsonify({"error": "Intake and physical assessment required"}), 400
    if not pa and not existing_goal:
        return jsonify({"error": "Physical assessment required"}), 400

    # Extract actor answer from conversation
    actor_answer = ""
    convo = (intake.conversation if intake else None) or []
    for i, msg in enumerate(convo):
        if msg.get("role") == "user" and i > 0:
            prev = convo[i-1].get("content", "")
            actor_keywords = ["actor", "movie", "body you want", "physique", "look like", "film", "body goal"]
            if any(kw in prev.lower() for kw in actor_keywords):
                actor_answer = msg["content"]
                break

    # Extract sex and age from conversation
    sex = "male"
    age = 30
    for msg in convo:
        content = msg.get("content", "").lower().strip()
        if msg.get("role") == "user":
            # Sex detection
            content_words = content.split()
            if any(w in content_words for w in ["male", "m", "man", "guy", "dude"]):
                sex = "male"
            elif any(w in content_words for w in ["female", "f", "woman", "girl", "lady"]):
                sex = "female"
            # Age detection — extract number from text like "I'm 32 years old"
            age_match = re.search(r'\b(\d{1,2})\b', content)
            if age_match:
                num = int(age_match.group(1))
                if 13 <= num <= 80:
                    age = num

    # BodyWeight is primary, PhysicalAssessment is fallback — NEVER default to 180
    latest_bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    if latest_bw:
        weight = latest_bw.weight_lbs
    elif pa and pa.bodyweight_lbs:
        weight = pa.bodyweight_lbs
        # Sync to BodyWeight table so it's there for next time
        db.session.add(BodyWeight(log_date=_user_today(), weight_lbs=weight, user_id=current_user.id))
        db.session.commit()
    elif existing_goal and existing_goal.target_weight:
        # Use a reasonable estimate from existing goal
        weight = existing_goal.target_weight + 30  # rough fallback
    else:
        return jsonify({"error": "No weight data found. Complete physical assessment first."}), 400
    height = (pa.height_inches if pa else None) or 70

    # Use existing goal type if recomputing, otherwise detect from intake
    if existing_goal and not actor_answer:
        goal_type = existing_goal.goal_type or "cut"
        target_bf = existing_goal.target_bf_pct or 0.12
    else:
        goal_info = detect_goal(actor_answer)
        goal_type = goal_info["goal_type"]
        target_bf = goal_info["target_bf"]

    # *** SAFETY: Minors (under 18) — NO calorie deficit, NO cut, NO fasting ***
    is_minor = age < 18
    if is_minor:
        goal_type = "recomp"
        target_bf = 0.12 if sex == "male" else 0.20

    # *** SAFETY: Weight-based goal override ***
    # A lightweight person should NEVER be on a cut — they need to build, not lose.
    # BMI-based thresholds (rough): underweight < 18.5, normal 18.5-25
    bmi = (weight / (height * height)) * 703 if height > 0 else 22
    if sex == "male":
        if weight < 150 and goal_type == "cut":
            goal_type = "bulk"  # Too light to cut — build muscle
            target_bf = 0.13
        elif weight < 170 and goal_type == "cut" and bmi < 22:
            goal_type = "recomp"  # Lean — recomp, not cut
            target_bf = 0.11
    else:
        if weight < 120 and goal_type == "cut":
            goal_type = "bulk"
            target_bf = 0.22
        elif weight < 140 and goal_type == "cut" and bmi < 22:
            goal_type = "recomp"
            target_bf = 0.19

    tdee_info = compute_tdee(weight, height, age, sex)

    # Compute target weight from body fat
    if sex == "male":
        est_bf = 0.12 if weight < 150 else 0.15 if weight < 180 else 0.20 if weight < 220 else 0.25
    else:
        est_bf = 0.20 if weight < 130 else 0.22 if weight < 150 else 0.28 if weight < 180 else 0.33
    lean_mass = weight * (1 - est_bf)
    target_weight = lean_mass / (1 - target_bf)

    # Never target weight loss below healthy minimum
    min_healthy_weight = lean_mass / 0.92 if sex == "male" else lean_mass / 0.85
    target_weight = max(target_weight, min_healthy_weight)

    # For minors: target weight should be ABOVE current weight (growth, not loss)
    if is_minor:
        target_weight = max(target_weight, weight + 5)

    # For bulk: target above current
    if goal_type == "bulk":
        target_weight = max(target_weight, weight + 10)

    _weeks_remaining = max(1, 12 - _current_week() + 1)
    targets = compute_targets(tdee_info["tdee"], goal_type, weight, age=age,
                              target_weight=target_weight, weeks=_weeks_remaining)

    if is_minor:
        # Override: NO deficit for minors — eat at TDEE or above
        targets["calories"] = max(targets["calories"], tdee_info["tdee"])
        # No fasting for minors
        fasting = {"protocol": "none", "eating_window_hours": 24, "electrolytes": False, "notes": "No fasting for athletes under 18. Eat regular meals throughout the day."}
    else:
        fasting = determine_fasting_protocol(goal_type, targets["calories"])

    phase_plan = compute_phase_plan(goal_type, weight, target_weight, est_bf)
    projection = project_weight_curve(weight, target_weight, tdee_info["tdee"], targets["calories"])

    # Compute per-day-type calories
    day_types = ["heavy_lift", "long_run", "moderate", "rest", "deload"]
    cal_by_day = {}
    for dt in day_types:
        cal_by_day[dt] = compute_day_calories(targets["calories"], goal_type, dt, weight_lbs=weight)

    # Save to DB
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not goal:
        goal = TrainingGoal(goal_type=goal_type, user_id=current_user.id)
        db.session.add(goal)
    goal.goal_type = goal_type
    goal.target_weight = round(target_weight, 1)
    goal.target_bf_pct = target_bf
    goal.daily_calories = targets["calories"]
    goal.protein_grams = targets["protein"]
    goal.carb_grams = targets["carbs"]
    goal.fat_grams = targets["fat"]
    goal.phase_plan = phase_plan
    goal.calorie_by_day_type = cal_by_day
    goal.fasting_protocol = fasting["protocol"]
    goal.electrolyte_supplementation = fasting["electrolytes"]
    goal.weight_projection = projection
    db.session.commit()

    daily_deficit = tdee_info["tdee"] - targets["calories"]
    weekly_loss = round(daily_deficit * 7 / 3500, 1) if daily_deficit > 0 else 0
    total_loss = round(weight - target_weight, 1)

    return jsonify({
        "goal_type": goal_type,
        "starting_weight": weight,
        "target_weight": round(target_weight, 1),
        "target_bf_pct": target_bf,
        "tdee": tdee_info["tdee"],
        "calories": targets["calories"],
        "daily_deficit": daily_deficit,
        "weekly_loss_lbs": weekly_loss,
        "total_loss_lbs": total_loss,
        "protein": targets["protein"],
        "carbs": targets["carbs"],
        "fat": targets["fat"],
        "fasting_protocol": fasting["protocol"],
        "electrolytes": fasting["electrolytes"],
        "phase_plan": phase_plan,
        "weight_projection": projection,
        "calorie_by_day_type": cal_by_day,
    })

@app.route("/api/goal")
@login_required
def api_goal():
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not goal:
        return jsonify({"computed": False})
    return jsonify({
        "computed": True,
        "goal_type": goal.goal_type,
        "target_weight": goal.target_weight,
        "target_bf_pct": goal.target_bf_pct,
        "calories": goal.daily_calories,
        "protein": goal.protein_grams,
        "carbs": goal.carb_grams,
        "fat": goal.fat_grams,
        "fasting_protocol": goal.fasting_protocol,
        "electrolytes": goal.electrolyte_supplementation,
        "phase_plan": goal.phase_plan,
        "weight_projection": goal.weight_projection,
        "calorie_by_day_type": goal.calorie_by_day_type,
        "plan_accepted": goal.plan_accepted or False,
    })


@app.route("/api/goal", methods=["POST"])
@login_required
def api_goal_update():
    data = request.get_json()
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not goal:
        return jsonify({"error": "No goal computed yet"}), 400
    if "plan_accepted" in data:
        goal.plan_accepted = data["plan_accepted"]
    db.session.commit()
    return jsonify({"ok": True})


# ─── FOOD CATALOG + SELECTIONS ────────────────────────────────────────────

@app.route("/api/food-catalog")
@login_required
def api_food_catalog():
    from food_catalog import get_filtered_catalog
    constraints = UserConstraints.query.filter_by(user_id=current_user.id).first()
    restrictions = constraints.food_restrictions if constraints else []
    catalog = get_filtered_catalog(restrictions)
    return jsonify(catalog)

@app.route("/api/food-selections")
@login_required
def api_food_selections():
    fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()
    if not fs:
        return jsonify({"completed": False, "selected_foods": {}})
    return jsonify({"completed": fs.completed, "selected_foods": fs.selected_foods or {}})

@app.route("/api/food-selections", methods=["POST"])
@login_required
def api_food_selections_save():
    data = request.get_json()
    fs = UserFoodSelections.query.filter_by(user_id=current_user.id).first()
    if not fs:
        fs = UserFoodSelections(user_id=current_user.id)
        db.session.add(fs)
    if "selected_foods" in data:
        fs.selected_foods = data["selected_foods"]
    if "completed" in data:
        fs.completed = data["completed"]
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/food-selections/validate", methods=["POST"])
@login_required
def api_food_selections_validate():
    from food_catalog import validate_selections
    data = request.get_json()
    selections = data.get("selected_foods", {})
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    daily_cal = goal.daily_calories if goal else 1800
    daily_protein = goal.protein_grams if goal else 150
    result = validate_selections(selections, daily_cal, daily_protein)
    return jsonify(result)


# ─── BASELINE ASSESSMENT ──────────────────────────────────────────────────

@app.route("/api/baseline-assessment")
@login_required
def api_baseline_assessment():
    from body_stats import build_baseline_assessment

    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    latest_bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    body_weight = latest_bw.weight_lbs if latest_bw else (pa.bodyweight_lbs if pa and pa.bodyweight_lbs else None)
    if not body_weight:
        return jsonify({"error": "No weight data found. Complete physical assessment first."}), 400

    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    sex = "male"
    age = 30
    if intake and intake.conversation:
        for msg in intake.conversation:
            content = msg.get("content", "").lower().strip()
            if msg.get("role") == "user":
                if content in ("male", "female", "m", "f"):
                    sex = "female" if content in ("female", "f") else "male"
                try:
                    num = int(content)
                    if 15 <= num <= 80:
                        age = num
                except ValueError:
                    pass

    physical_data = {}
    if pa:
        physical_data = {
            "waist": pa.waist_inches,
            "chest": pa.chest_inches,
            "bicep": pa.bicep_inches,
            "thigh": pa.thigh_inches,
            "neck": pa.neck_inches,
            "hips": pa.hips_inches,
            "height": pa.height_inches,
        }

    lifting_data = _serialize_weights(user_id=current_user.id)

    assessment = build_baseline_assessment(physical_data, lifting_data, age, sex, body_weight)
    return jsonify(assessment)


# ─── EQUIPMENT ─────────────────────────────────────────────────────────────

@app.route("/api/equipment/catalog")
@login_required
def api_equipment_catalog():
    from equipment_swaps import EQUIPMENT_CATALOG
    return jsonify(EQUIPMENT_CATALOG)


@app.route("/api/equipment")
@login_required
def api_equipment():
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    if not eq:
        return jsonify({"completed": False, "available_equipment": []})
    return jsonify({"completed": eq.completed, "available_equipment": eq.available_equipment or []})


@app.route("/api/equipment", methods=["POST"])
@login_required
def api_equipment_save():
    data = request.get_json()
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    if not eq:
        eq = UserEquipment(user_id=current_user.id)
        db.session.add(eq)
    if "available_equipment" in data:
        eq.available_equipment = data["available_equipment"]
    if "completed" in data:
        eq.completed = data["completed"]
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/exercise/alternatives/<path:exercise_name>")
@login_required
def api_exercise_alternatives(exercise_name):
    from workout_data import resolve_name
    exercise_name = resolve_name(exercise_name)
    from equipment_swaps import get_alternatives
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    user_equipment = eq.available_equipment if eq else []
    alts = get_alternatives(exercise_name, user_equipment)
    return jsonify({"exercise": exercise_name, "alternatives": alts})


# ─── SHOPPING LIST ──────────────────────────────────────────────────────────

@app.route("/api/shopping-list")
@login_required
def api_shopping_list():
    """Generate a weekly grocery list — raw ingredients you buy at the store."""
    import re
    s = _get_state()
    week = _current_week()
    workouts = get_workouts(week)

    # Filter by user's food selections
    user_food_ids = _get_user_food_ids()
    workouts = _filter_meals_by_food_selections(workouts, user_food_ids)

    # Map recipe names → raw grocery item + unit normalization
    INGREDIENT_MAP = {
        # Eggs — all forms are just eggs
        "Eggs, scrambled": ("Eggs", "large"),
        "Eggs, omelette": ("Eggs", "large"),
        "Hard boiled egg": ("Eggs", "large"),
        "Hard boiled eggs": ("Eggs", "large"),
        # Chicken — all forms are just chicken breast
        "Grilled chicken breast": ("Chicken breast", "oz"),
        "Baked chicken breast": ("Chicken breast", "oz"),
        # Greens — normalize
        "Mixed greens": ("Mixed greens", "cups"),
        "Side salad (mixed greens)": ("Mixed greens", "cups"),
        "Spinach side salad": ("Spinach", "cups"),
        "Spinach": ("Spinach", "cups"),
        "Spinach (in omelette)": ("Spinach", "cups"),
        # Broccoli
        "Steamed broccoli": ("Broccoli", "cups"),
        # Asparagus
        "Steamed asparagus": ("Asparagus", "cups"),
        # Oil dressings — all just olive oil
        "Olive oil + lemon dressing": ("Olive oil", "tbsp"),
        "Olive oil dressing": ("Olive oil", "tbsp"),
        # Rice
        "White rice": ("White rice", "cups cooked"),
        # Whey
        "Whey protein shake": ("Whey protein powder", "scoops"),
        # Coffee
        "Black coffee": ("Coffee", "brew"),
        # Water / electrolytes — skip, not a grocery item
        "Water": (None, None),
        "Electrolytes (salt, potassium)": ("Electrolytes", "serving"),
    }

    CATEGORY_MAP = {
        "Chicken breast": "Proteins",
        "Eggs": "Proteins",
        "Greek yogurt": "Proteins",
        "Whey protein powder": "Proteins",
        "Cheddar cheese": "Proteins",
        "Salmon fillet": "Proteins",
        "Mixed greens": "Produce",
        "Spinach": "Produce",
        "Broccoli": "Produce",
        "Asparagus": "Produce",
        "Cherry tomatoes": "Produce",
        "Avocado": "Produce",
        "Banana": "Produce",
        "Blueberries": "Produce",
        "Sweet potato": "Produce",
        "Salsa": "Produce",
        "Lemon": "Produce",
        "White rice": "Pantry",
        "Quinoa": "Pantry",
        "Olive oil": "Pantry",
        "Almonds": "Pantry",
        "Coffee": "Pantry",
        "Whey protein powder": "Pantry",
        "Electrolytes": "Pantry",
    }

    def parse_amount(portion):
        if not portion:
            return 1.0
        p = portion.strip().lower()
        p = p.replace("½", "0.5").replace("¼", "0.25").replace("¾", "0.75")
        # Handle "as needed", "unlimited"
        if "needed" in p or "unlimited" in p:
            return 0
        # Handle "1 oz (23 nuts)" → extract the number
        m = re.match(r'^(\d+(?:\.\d+)?(?:/\d+)?)', p)
        if m:
            num_str = m.group(1)
            if '/' in num_str:
                parts = num_str.split('/')
                try:
                    return float(parts[0]) / float(parts[1])
                except (ValueError, ZeroDivisionError):
                    return 1.0
            return float(num_str)
        return 1.0

    def normalize_unit(portion):
        """Extract just the unit from a portion string."""
        if not portion:
            return "serving"
        p = portion.strip().lower()
        p = p.replace("½", "0.5").replace("¼", "0.25").replace("¾", "0.75")
        m = re.match(r'^[\d./]+\s*(.*)', p)
        if m:
            unit = m.group(1).strip()
            # Clean up units
            unit = re.sub(r'\(.*\)', '', unit).strip()  # remove parentheticals
            unit = unit.rstrip('s') if unit.endswith('s') and unit not in ('cups',) else unit
            return unit or "serving"
        return "serving"

    # Aggregate
    grocery = {}  # normalized_name → {unit, total, category}

    for day_data in workouts:
        mp = day_data.get("mealPlan")
        if not mp or not mp.get("meals"):
            continue
        for meal in mp["meals"]:
            for food in meal.get("foods", []):
                raw_name = food["item"]
                portion = food.get("portion", "")

                # Normalize to raw ingredient
                if raw_name in INGREDIENT_MAP:
                    name, unit = INGREDIENT_MAP[raw_name]
                    if name is None:
                        continue  # skip water etc.
                else:
                    name = raw_name
                    unit = normalize_unit(portion)

                amount = parse_amount(portion)
                if amount == 0:
                    continue

                if name in grocery:
                    grocery[name]["total"] += amount
                else:
                    cat = CATEGORY_MAP.get(name, "Other")
                    grocery[name] = {"unit": unit, "total": amount, "category": cat}

    # Convert totals to shopping quantities
    def to_shopping_qty(name, total, unit):
        """Convert meal-plan units to store quantities."""
        if name == "Chicken breast" and unit == "oz":
            lbs = total / 16
            if lbs >= 1:
                return f"{lbs:.1f} lbs"
            return f"{total:.0f} oz"
        if name == "Eggs":
            count = int(total)
            dozens = count // 12
            remainder = count % 12
            if dozens >= 1 and remainder == 0:
                return f"{dozens} dozen"
            if dozens >= 1:
                return f"{dozens} dozen + {remainder}"
            return f"{count} eggs"
        if unit == "cups cooked" and name == "White rice":
            # ~1 cup dry = 3 cups cooked
            dry_cups = total / 3
            return f"{dry_cups:.1f} cups dry"
        if unit == "cups cooked" and name == "Quinoa":
            dry_cups = total / 2.5
            return f"{dry_cups:.1f} cups dry"
        # Default
        if total == int(total):
            return f"{int(total)} {unit}"
        return f"{total:.1f} {unit}"

    # Build categorized output
    categories = {}
    for name, info in sorted(grocery.items()):
        cat = info["category"]
        if cat not in categories:
            categories[cat] = []
        qty = to_shopping_qty(name, info["total"], info["unit"])
        categories[cat].append({"item": name, "total": qty})

    cat_order = ["Proteins", "Produce", "Pantry", "Other"]
    ordered = []
    for cat in cat_order:
        if cat in categories:
            ordered.append({"category": cat, "items": categories[cat]})

    return jsonify({"week": week, "categories": ordered})


# ─── WEEKLY REPORT ─────────────────────────────────────────────────────────

@app.route("/api/weekly-report/generate", methods=["POST"])
@login_required
def api_weekly_report_generate():
    from weekly_report import compute_weekly_metrics, generate_report_narrative

    s = _get_state()
    # Compute week from start_date (not stale current_week DB value)
    if s.start_date:
        local_today = _user_today()
        diff_days = (local_today - s.start_date).days
        week = min(12, max(1, diff_days // 7 + 1))
    else:
        week = s.current_week or 1

    _current_user_id = current_user.id
    metrics = compute_weekly_metrics(week, user_id=_current_user_id)

    # Save computed metrics immediately

    report = WeeklyReport.query.filter_by(user_id=current_user.id, week=week).first()
    if not report:
        report = WeeklyReport(week=week, report_date=_user_today(), user_id=current_user.id)
        db.session.add(report)
    report.workouts_completed = metrics["workouts_completed"]
    report.workouts_total = metrics["workouts_total"]
    report.weight_start = metrics["weight_start"]
    report.weight_end = metrics["weight_end"]
    report.weight_trend = metrics["weight_trend"]
    report.weight_vs_projected = metrics["weight_vs_projected"]
    report.key_lifts_summary = metrics["key_lifts"]
    report.checkin_avg = metrics["checkin_avg"]
    report.adherence_pct = metrics["adherence_pct"]
    db.session.commit()

    # Generate narrative in background
    job_id = str(uuid.uuid4())[:8]
    _intake_jobs[job_id] = {"status": "pending"}

    def run_narrative():
        try:
            narrative = generate_report_narrative(metrics)
            _intake_jobs[job_id] = {"status": "done", "narrative": narrative}
            # Save narrative to DB
            with app.app_context():
                r = WeeklyReport.query.filter_by(user_id=_current_user_id, week=week).first()
                if r and narrative:
                    r.narrative = narrative
                    db.session.commit()
        except Exception as e:
            _intake_jobs[job_id] = {"status": "error", "narrative": None}

    thread = threading.Thread(target=run_narrative)
    thread.start()

    return jsonify({
        "job_id": job_id,
        "metrics": metrics,
    })

@app.route("/api/weekly-report/<int:week>")
@login_required
def api_weekly_report(week):
    report = WeeklyReport.query.filter_by(user_id=current_user.id, week=week).first()
    if not report:
        return jsonify({"error": "No report for this week"}), 404
    return jsonify({
        "week": report.week,
        "workouts_completed": report.workouts_completed,
        "workouts_total": report.workouts_total,
        "weight_start": report.weight_start,
        "weight_end": report.weight_end,
        "weight_trend": report.weight_trend,
        "weight_vs_projected": report.weight_vs_projected,
        "key_lifts": report.key_lifts_summary,
        "checkin_avg": report.checkin_avg,
        "adherence_pct": report.adherence_pct,
        "narrative": report.narrative,
    })

@app.route("/api/weekly-report/result/<job_id>")
@login_required
def api_weekly_report_result(job_id):
    job = _intake_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] == "pending":
        return jsonify({"status": "pending"})
    narrative = job.get("narrative")
    del _intake_jobs[job_id]
    return jsonify({"status": job["status"], "narrative": narrative})


# ─── GOAL RECALIBRATION ───────────────────────────────────────────────────

@app.route("/api/goal/recalibrate", methods=["POST"])
@login_required
def api_goal_recalibrate():
    from goal_engine import recalibrate_projection, compute_tdee

    data = request.get_json()
    actual_weight = data.get("weight")
    week = data.get("week")

    if not actual_weight or not week:
        return jsonify({"error": "weight and week required"}), 400

    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if not goal or not pa:
        return jsonify({"error": "Goal not computed yet"}), 400

    # Extract age/sex for TDEE recalc
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    sex = "male"
    age = 30
    if intake and intake.conversation:
        for msg in intake.conversation:
            content = msg.get("content", "").lower().strip()
            if msg.get("role") == "user":
                if content in ("male", "female", "m", "f"):
                    sex = "female" if content in ("female", "f") else "male"
                try:
                    num = int(content)
                    if 15 <= num <= 80:
                        age = num
                except ValueError:
                    pass

    tdee_params = {
        "height_in": pa.height_inches or 70,
        "age": age,
        "sex": sex,
    }

    result = recalibrate_projection(
        actual_weight, week,
        goal.weight_projection or [],
        tdee_params
    )

    # Update goal
    goal.weight_projection = result["updated_projection"]
    goal.daily_calories = result["new_daily_calories"]
    db.session.commit()

    return jsonify(result)


# ─── MORNING BRIEFING ─────────────────────────────────────────────────────

@app.route("/api/morning-briefing", methods=["POST"])
@login_required
def api_morning_briefing():
    data = request.get_json() or {}

    # Build the morning briefing as a coach message with full context
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    garmin_data = gc.get_today_summary() if gc.connected else None
    readiness = assess_readiness(garmin_data)
    score = readiness.get("score") or 70

    if score >= 65:
        status = "GREEN"
    elif score >= 40:
        status = "YELLOW"
    else:
        status = "RED"

    # Get today's workout
    s = _get_state()
    workouts = get_workouts(_current_week())
    today_idx = _user_today().weekday()
    workout_today = workouts[today_idx] if today_idx < len(workouts) else None
    workout_name = workout_today.get("liftName", "Rest") if workout_today else "Rest"

    # Build checkin summary
    checkin_summary = f"Morning check-in: Sleep {data.get('sleep_quality', 5)}/10, Stress {data.get('stress_level', 5)}/10, Soreness {data.get('soreness', 5)}/10, Mood {data.get('mood', 5)}/10, Motivation {data.get('motivation', 5)}/10, Anxiety {data.get('anxiety', 3)}/10."
    if data.get('notes'):
        checkin_summary += f" Notes: {data['notes']}"

    # Use full coach context + special trigger
    briefing_msg = f"[MORNING_BRIEFING] Status: {status} ({score}/100). Today is {workout_name} — Week {_current_week()}. {checkin_summary} Give me a 1-2 sentence morning briefing. If GREEN, get me out the door. If YELLOW, name the adjustment. If RED, tell me to stand down."

    context = _build_coach_context()
    response_text = get_coach_response(briefing_msg, context)

    # Save as chat messages
    user_chat = ChatMessage(role="user", content=checkin_summary, log_date=_user_today(), user_id=current_user.id)
    asst_chat = ChatMessage(role="assistant", content=response_text, log_date=_user_today(), user_id=current_user.id)
    db.session.add(user_chat)
    db.session.add(asst_chat)
    db.session.commit()

    return jsonify({
        "status": status,
        "message": response_text,
        "workout": workout_name,
        "readiness_score": score,
        "needs_discussion": status == "RED",
    })


# ─── PLAN LOCKOUT ──────────────────────────────────────────────────────────

@app.route("/api/plan/lockout", methods=["POST"])
@login_required
def api_plan_lockout():
    """Lock user out for 1 week after rejecting the plan."""
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if intake:
        intake.locked_until = _user_today() + timedelta(days=7)
        db.session.commit()
    return jsonify({"ok": True, "locked_until": (_user_today() + timedelta(days=7)).isoformat()})


# ─── PHYSICAL ASSESSMENT ───────────────────────────────────────────────────

@app.route("/api/physical-assessment/status")
@login_required
def api_physical_assessment_status():
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if not pa:
        return jsonify({"started": False, "completed": False})
    latest_bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    return jsonify({
        "started": True,
        "completed": pa.completed,
        "has_gym": pa.has_gym,
        "has_measuring_tape": pa.has_measuring_tape,
        "bodyweight": latest_bw.weight_lbs if latest_bw else pa.bodyweight_lbs,
        "height": pa.height_inches,
        "waist": pa.waist_inches,
        "chest": pa.chest_inches,
        "bicep": pa.bicep_inches,
        "thigh": pa.thigh_inches,
        "hips": pa.hips_inches,
        "neck": pa.neck_inches,
    })


@app.route("/api/physical-assessment", methods=["POST"])
@login_required
def api_physical_assessment_save():
    data = request.get_json()
    # Validate physical measurements
    _pa_ranges = {
        "height": (48, 96), "bodyweight": (50, 600),
        "waist": (5, 80), "stomach": (5, 80), "chest": (5, 80),
        "bicep": (5, 80), "thigh": (5, 80), "hips": (5, 80), "neck": (5, 80),
    }
    for field, (lo, hi) in _pa_ranges.items():
        if field in data and data[field] is not None:
            try:
                val = float(data[field])
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid {field} value"}), 400
            if val < lo or val > hi:
                return jsonify({"error": f"{field.title()} must be between {lo} and {hi}"}), 400
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if not pa:
        pa = PhysicalAssessment(user_id=current_user.id)
        db.session.add(pa)

    if "has_gym" in data:
        pa.has_gym = data["has_gym"]
    if "has_measuring_tape" in data:
        pa.has_measuring_tape = data["has_measuring_tape"]
    if "height" in data:
        pa.height_inches = data["height"]
    if "bodyweight" in data and data["bodyweight"]:
        pa.bodyweight_lbs = float(data["bodyweight"])
        # Also log to BodyWeight table — this is the primary weight source
        d = _user_today()
        bw = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
        if bw:
            bw.weight_lbs = float(data["bodyweight"])
        else:
            # Check if concurrent /api/bodyweight POST already created one
            try:
                db.session.flush()  # flush PA changes first
                bw_check = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
                if not bw_check:
                    db.session.add(BodyWeight(log_date=d, weight_lbs=float(data["bodyweight"]), user_id=current_user.id))
            except Exception:
                db.session.rollback()
                # Re-query PA after rollback
                pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
                if pa:
                    pa.bodyweight_lbs = float(data["bodyweight"])
    if "waist" in data:
        pa.waist_inches = data["waist"]
        d = _user_today()
        bm = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=d).first()
        if bm:
            bm.waist_inches = data["waist"]
        else:
            db.session.add(BodyMeasurement(log_date=d, waist_inches=data["waist"], user_id=current_user.id))
    if "stomach" in data:
        pa.stomach_inches = data["stomach"]
    if "chest" in data:
        pa.chest_inches = data["chest"]
    if "bicep" in data:
        pa.bicep_inches = data["bicep"]
    if "thigh" in data:
        pa.thigh_inches = data["thigh"]
    if "hips" in data:
        pa.hips_inches = data["hips"]
    if "neck" in data:
        pa.neck_inches = data["neck"]
    if "pushup_count" in data:
        pa.pushup_count = data["pushup_count"]
    if "pushup_from_knees" in data:
        pa.pushup_from_knees = data["pushup_from_knees"]
    if "plank_seconds" in data:
        pa.plank_seconds = data["plank_seconds"]
    if "squat_count" in data:
        pa.squat_count = data["squat_count"]
    if "lunge_count_per_leg" in data:
        pa.lunge_count_per_leg = data["lunge_count_per_leg"]
    if "pullup_count" in data:
        pa.pullup_count = data["pullup_count"]
    if "gym_baseline_done" in data:
        pa.gym_baseline_done = data["gym_baseline_done"]
    if "completed" in data:
        pa.completed = data["completed"]

    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/physical-assessment/reset", methods=["POST"])
@login_required
def api_physical_assessment_reset():
    PhysicalAssessment.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


## User data reset endpoint removed — no data wipes allowed


## Full reset endpoint removed — no nuclear data wipes allowed


@app.route("/admin")
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    invites = Invite.query.order_by(Invite.created_at.desc()).all()
    pending = Invite.query.filter_by(used_by=None, multi_use=False).all()
    return render_template("admin.html", users=users, invites=invites, pending=pending)


@app.route("/api/admin/reset-password", methods=["POST"])
@admin_required
def api_admin_reset_password():
    """Reset a user's password. Admin-only. Returns a temporary password."""
    import secrets
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404
    temp_password = secrets.token_urlsafe(10)
    user.password_hash = generate_password_hash(temp_password)
    try:
        db.session.commit()
        return jsonify({"ok": True, "email": user.email, "temp_password": temp_password,
                        "message": f"Password reset for {user.email}. Give them the temp password and have them change it."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/set-weight", methods=["POST"])
@admin_required
def api_admin_set_weight():
    """Set a user's bodyweight and recompute their goal. Admin-only."""
    from goal_engine import compute_tdee, compute_targets, compute_day_calories
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    weight = data.get("weight")
    if not email or not weight:
        return jsonify({"error": "email and weight required"}), 400
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404

    # 1. Save to BodyWeight table
    d = _user_today()
    bw = BodyWeight.query.filter_by(user_id=user.id, log_date=d).first()
    if bw:
        bw.weight_lbs = float(weight)
    else:
        db.session.add(BodyWeight(log_date=d, weight_lbs=float(weight), user_id=user.id))

    # 2. Save to PhysicalAssessment
    pa = PhysicalAssessment.query.filter_by(user_id=user.id).first()
    if pa:
        pa.bodyweight_lbs = float(weight)

    db.session.commit()

    # 3. Recompute goal if one exists
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    recomputed = False
    if goal:
        try:
            intake = PsychIntake.query.filter_by(user_id=user.id).first()
            height = pa.height_inches if pa else 70
            age = intake.age if intake and hasattr(intake, 'age') and intake.age else 30
            sex = (intake.sex if intake and hasattr(intake, 'sex') else 'male') or 'male'
            tdee_info = compute_tdee(float(weight), height or 70, age, sex)
            targets = compute_targets(tdee_info["tdee"], goal.goal_type or "cut", float(weight),
                                      target_weight=goal.target_weight, weeks=12)
            goal.daily_calories = targets["calories"]
            goal.protein_grams = targets["protein"]
            goal.carb_grams = targets["carbs"]
            goal.fat_grams = targets["fat"]
            db.session.commit()
            recomputed = True
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": True, "weight_saved": True, "recomputed": False,
                            "recompute_error": str(e)})

    return jsonify({
        "ok": True,
        "email": user.email,
        "weight_saved": True,
        "weight_lbs": float(weight),
        "recomputed": recomputed,
        "calories": goal.daily_calories if goal else None,
        "protein": goal.protein_grams if goal else None,
    })


@app.route("/api/admin/debug/user/<path:email>")
@admin_required
def api_admin_debug_user(email):
    """Full diagnostic dump of a user's state. Admin-only."""
    email = email.strip().lower()
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404
    uid = user.id

    # Onboarding state
    state = AppState.query.filter_by(user_id=uid).first()
    intake = PsychIntake.query.filter_by(user_id=uid).first()
    pa = PhysicalAssessment.query.filter_by(user_id=uid).first()
    goal = TrainingGoal.query.filter_by(user_id=uid).first()
    from models import UserFoodSelections, UserConstraints, UserEquipment
    food = UserFoodSelections.query.filter_by(user_id=uid).first()
    constraints = UserConstraints.query.filter_by(user_id=uid).first()
    equipment = UserEquipment.query.filter_by(user_id=uid).first()

    # Measurements
    measurements = BodyMeasurement.query.filter_by(user_id=uid).order_by(BodyMeasurement.log_date.desc()).limit(5).all()
    # Also check orphan measurements (user_id=NULL) for today
    orphan_measurements = BodyMeasurement.query.filter_by(user_id=None).all()

    # Body weight
    weights = BodyWeight.query.filter_by(user_id=uid).order_by(BodyWeight.log_date.desc()).limit(5).all()

    # Check-ins
    checkins = MorningCheckIn.query.filter_by(user_id=uid).order_by(MorningCheckIn.log_date.desc()).limit(5).all()

    # DB index check
    index_info = []
    try:
        rows = db.session.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'body_measurement'"
        )).fetchall()
        index_info = [{"name": r[0], "definition": r[1]} for r in rows]
    except Exception as e:
        index_info = [{"error": str(e)}]

    return jsonify({
        "user": {"id": uid, "email": user.email, "name": user.name, "timezone": user.timezone,
                 "created_at": str(user.created_at)},
        "onboarding": {
            "state": {"baseline_done": state.baseline_done if state else None,
                      "start_date": str(state.start_date) if state and state.start_date else None,
                      "current_week": state.current_week if state else None} if state else None,
            "intake_completed": bool(intake and intake.completed) if intake else False,
            "pa_completed": bool(pa and pa.completed) if pa else False,
            "pa_weight": pa.bodyweight_lbs if pa else None,
            "pa_height": pa.height_inches if pa else None,
            "constraints_completed": bool(constraints and constraints.completed) if constraints else False,
            "equipment_completed": bool(equipment and equipment.completed) if equipment else False,
            "food_completed": bool(food and food.completed) if food else False,
            "food_count": len(food.selected_foods) if food and food.selected_foods else 0,
            "goal_computed": bool(goal) if goal else False,
            "goal_type": goal.goal_type if goal else None,
            "goal_calories": goal.daily_calories if goal else None,
            "goal_protein": goal.protein_grams if goal else None,
            "plan_accepted": goal.plan_accepted if goal else None,
        },
        "measurements": [{"date": str(m.log_date), "weight": m.weight_lbs, "waist": m.waist_inches,
                          "user_id": m.user_id} for m in measurements],
        "orphan_measurements": [{"id": m.id, "date": str(m.log_date), "weight": m.weight_lbs,
                                  "user_id": m.user_id} for m in orphan_measurements],
        "weights": [{"date": str(w.log_date), "weight": w.weight_lbs} for w in weights],
        "checkins": [{"date": str(c.log_date), "notes": c.notes} for c in checkins],
        "db_indexes": index_info,
    })


@app.route("/api/admin/debug/sql", methods=["POST"])
@admin_required
def api_admin_debug_sql():
    """Run a read-only SQL query. Admin-only. SELECT only."""
    data = request.get_json()
    sql = (data.get("sql") or "").strip()
    if not sql:
        return jsonify({"error": "No SQL provided"}), 400
    # Safety: only allow SELECT
    if not sql.upper().startswith("SELECT"):
        return jsonify({"error": "Only SELECT queries allowed"}), 403
    try:
        result = db.session.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return jsonify({"columns": columns, "rows": rows, "count": len(rows)})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/admin/debug/fix-indexes", methods=["POST"])
@admin_required
def api_admin_fix_indexes():
    """Drop broken unique indexes and recreate as non-unique. Admin-only."""
    fixed = []
    try:
        # body_measurement: log_date should NOT be unique
        db.session.execute(text('DROP INDEX IF EXISTS ix_body_measurement_log_date'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_body_measurement_log_date ON body_measurement (log_date)'))
        fixed.append("ix_body_measurement_log_date")
        # body_weight: same check
        db.session.execute(text('DROP INDEX IF EXISTS ix_body_weight_log_date'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_body_weight_log_date ON body_weight (log_date)'))
        fixed.append("ix_body_weight_log_date")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)[:300]}), 500
    return jsonify({"ok": True, "fixed": fixed})


@app.route("/api/admin/reset-assessment", methods=["POST"])
@admin_required
def api_admin_reset_assessment():
    """Reset a user's physical assessment so they redo it on next login."""
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": f"User {email} not found"}), 404

    # Reset physical assessment
    pa = PhysicalAssessment.query.filter_by(user_id=user.id).first()
    if pa:
        db.session.delete(pa)

    # Clear bad BodyWeight entries
    BodyWeight.query.filter_by(user_id=user.id).delete()

    # Reset goal so it recomputes with correct weight
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if goal:
        goal.plan_accepted = False

    # Reset baseline state
    state = AppState.query.filter_by(user_id=user.id).first()
    if state:
        state.baseline_done = False

    db.session.commit()
    return jsonify({"ok": True, "message": f"Reset assessment for {email}. They will redo physical assessment on next login."})


@app.route("/api/test/create-user", methods=["POST"])
def api_test_create_user():
    """Create test user for e2e testing. Only works for test@12weeks.com."""
    data = request.get_json(silent=True) or {}
    email = data.get("email", "test@12weeks.com")
    if email != "test@12weeks.com":
        return jsonify({"error": "Only test user allowed"}), 403

    existing = User.query.filter_by(email=email).first()
    if existing:
        uid = existing.id
        # Delete existing test user and all their data
        for model in [ChatMessage, MorningCheckIn, PsychIntake, PhysicalAssessment,
                      ExerciseLog, ExerciseCompletion, DayCompletion, BodyWeight,
                      BodyMeasurement, WeeklyCheckIn, MealLog, SupplementLog,
                      ProgressPhoto, AppState, UserConstraints, TrainingGoal,
                      UserFoodSelections, WeeklyReport, UserEquipment]:
            try:
                model.query.filter_by(user_id=uid).delete()
                db.session.commit()
            except Exception:
                db.session.rollback()
        # Invite uses created_by / used_by, not user_id
        try:
            Invite.query.filter_by(created_by=uid).delete()
            Invite.query.filter_by(used_by=uid).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
        User.query.filter_by(id=uid).delete()
        db.session.commit()

    user = User(
        email=email,
        name="Test User",
        password_hash=generate_password_hash("testtest1"),
        role="user",
        email_verified=True,
        invites_remaining=3,
    )
    db.session.add(user)
    db.session.commit()

    # Seed minimal psych intake so goal compute works
    intake = PsychIntake(
        user_id=user.id,
        completed=True,
        conversation=[
            {"role": "assistant", "content": "What sex were you assigned at birth?"},
            {"role": "user", "content": "male"},
            {"role": "assistant", "content": "How old are you?"},
            {"role": "user", "content": "35"},
            {"role": "assistant", "content": "What actor or movie character has the body you want?"},
            {"role": "user", "content": "Brad Pitt in Fight Club"},
        ],
        report="Test user psych intake. Goal: lean physique, cut body fat.",
    )
    db.session.add(intake)
    db.session.commit()

    return jsonify({"ok": True, "user_id": user.id})


@app.route("/api/warmup-completions")
@login_required
def api_warmup_completions():
    """Get all warm-up completions for current user."""
    comps = WarmupCompletion.query.filter_by(user_id=current_user.id).all()
    return jsonify({f"{c.week}_{c.day_idx}_{c.step_idx}": c.done for c in comps})


@app.route("/api/warmup-completions", methods=["POST"])
@login_required
def api_warmup_toggle():
    data = request.get_json()
    w, d, s = data["week"], data["day_idx"], data["step_idx"]
    wc = WarmupCompletion.query.filter_by(user_id=current_user.id, week=w, day_idx=d, step_idx=s).first()
    if wc:
        wc.done = not wc.done
    else:
        wc = WarmupCompletion(week=w, day_idx=d, step_idx=s, done=True, user_id=current_user.id)
        db.session.add(wc)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"done": wc.done})


@app.route("/api/run-log", methods=["POST"])
@login_required
def api_run_log():
    data = request.get_json()
    existing = RunLog.query.filter_by(
        user_id=current_user.id, week=data.get("week"), day_idx=data.get("day_idx")
    ).first()
    if existing:
        existing.distance_miles = data.get("distance_miles")
        existing.avg_hr = data.get("avg_hr")
        existing.elevation_ft = data.get("elevation_ft")
        existing.duration_min = data.get("duration_min")
        existing.notes = data.get("notes")
    else:
        existing = RunLog(
            user_id=current_user.id, week=data.get("week"), day_idx=data.get("day_idx"),
            distance_miles=data.get("distance_miles"), avg_hr=data.get("avg_hr"),
            elevation_ft=data.get("elevation_ft"), duration_min=data.get("duration_min"),
            notes=data.get("notes"), log_date=_user_today(),
        )
        db.session.add(existing)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"ok": True, "id": existing.id})


@app.route("/api/run-log")
@login_required
def api_run_logs():
    logs = RunLog.query.filter_by(user_id=current_user.id).all()
    return jsonify({f"{l.week}_{l.day_idx}": {
        "distance_miles": l.distance_miles, "avg_hr": l.avg_hr,
        "elevation_ft": l.elevation_ft, "duration_min": l.duration_min,
    } for l in logs})


@app.route("/api/session-summary/<int:week>/<int:day_idx>")
@login_required
def api_session_summary(week, day_idx):
    """Get session summary for a completed workout day."""
    analysis = SessionAnalysis.query.filter_by(
        user_id=current_user.id, week=week, day_idx=day_idx
    ).order_by(SessionAnalysis.log_date.desc()).first()

    sets = SetLog.query.filter_by(
        user_id=current_user.id, week=week, day_idx=day_idx, done=True
    ).order_by(SetLog.exercise_name, SetLog.set_number).all()

    exercises = {}
    for s in sets:
        if s.exercise_name not in exercises:
            exercises[s.exercise_name] = {"sets": [], "target_weight": None, "target_reps": None}
        exercises[s.exercise_name]["sets"].append({
            "set": s.set_number + 1, "weight": s.weight, "reps": s.reps,
            "target_weight": getattr(s, 'target_weight', None),
            "target_reps": getattr(s, 'target_reps', None),
            "modified": getattr(s, 'user_modified', False),
            "direction": getattr(s, 'modification_direction', None),
        })
        if getattr(s, 'target_weight', None):
            exercises[s.exercise_name]["target_weight"] = s.target_weight
        if getattr(s, 'target_reps', None):
            exercises[s.exercise_name]["target_reps"] = s.target_reps

    profiles = MuscleGroupProfile.query.filter_by(user_id=current_user.id).all()
    muscle_scores = {p.muscle_group: {
        "score": p.strength_score, "strength": p.relative_strength, "weak": p.user_flagged_weak
    } for p in profiles}

    return jsonify({
        "exercises": exercises,
        "compliance": analysis.overall_compliance if analysis else None,
        "deviations": analysis.deviations if analysis else [],
        "summary": analysis.summary_text if analysis else None,
        "muscle_scores": muscle_scores,
    })


# ─── DEFICIT CALCULATION & BMR RECALCULATION ─────────────────────────────

@app.route("/api/deficit-plan", methods=["POST"])
@login_required
def api_deficit_plan():
    """Calculate deficit gap and recommend interventions to hit target weight."""
    from math import ceil
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not goal or not goal.target_weight:
        return jsonify({"error": "No target weight set"}), 400

    # Current weight from latest bodyweight entry
    bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    if not bw:
        return jsonify({"error": "No weight data"}), 400

    current_weight = bw.weight
    target_weight = goal.target_weight

    week = _current_week()
    weeks_remaining = max(1, 12 - week + 1)
    required_weekly_loss = (current_weight - target_weight) / weeks_remaining

    if required_weekly_loss <= 0:
        return jsonify({"on_pace": True, "message": "Already at or below target"})

    # BMR -- use actual if available, otherwise Mifflin-St Jeor
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if pa and pa.actual_bmr:
        bmr = pa.actual_bmr
    elif pa and pa.bodyweight_lbs and pa.height_inches:
        # Mifflin-St Jeor (male): 10 x kg + 6.25 x cm - 5 x age - 5
        weight_kg = pa.bodyweight_lbs * 0.453592
        height_cm = pa.height_inches * 2.54
        age = _extract_age_from_intake(current_user.id)
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 5
    else:
        bmr = current_weight * 10  # rough fallback

    # Current daily calories
    daily_cals = goal.daily_calories or 2000

    # Exercise burn estimate (from this week's SetLog)
    local_today = _user_today()
    week_start = local_today - timedelta(days=local_today.weekday())
    sets = SetLog.query.filter(
        SetLog.user_id == current_user.id,
        SetLog.logged_date >= week_start,
        SetLog.done == True
    ).all()
    # Rough estimate: ~7 cal per completed set (conservative average for compound lifts)
    # 100 sets/week x 7 = 700 cal/week, consistent with research (150-250 kcal/hour)
    exercise_burn = len(sets) * 7
    exercise_burn = max(exercise_burn, 200)  # floor at 200 cal/week from lifting

    # Run burn estimate
    runs = RunLog.query.filter(
        RunLog.user_id == current_user.id,
        RunLog.log_date >= week_start
    ).all()
    run_burn = sum((r.distance_miles or 0) * current_weight * 0.63 for r in runs)

    # Weekly budget
    eating_days = 5  # Mon-Fri (Sat-Sun could be fast)
    weekly_intake = daily_cals * eating_days
    weekly_expenditure = (bmr * 7) + exercise_burn + run_burn
    current_deficit = weekly_expenditure - weekly_intake
    required_deficit = required_weekly_loss * 3500
    gap = required_deficit - current_deficit

    if gap <= 0:
        return jsonify({
            "on_pace": True,
            "current_weight": current_weight,
            "target_weight": target_weight,
            "weeks_remaining": weeks_remaining,
            "current_deficit": round(current_deficit),
            "required_deficit": round(required_deficit),
            "bmr": round(bmr),
        })

    recommendations = {"add_saturday_fast": True}
    remaining_gap = gap

    # 1. Saturday fast
    fast_savings = bmr
    remaining_gap -= fast_savings

    # 2. Reduce daily calories
    protein_floor = target_weight  # 1g/lb target weight in protein = ~4 cal/g
    cal_floor = max(bmr, protein_floor * 4 + 400)  # protein + minimum fat/carb
    max_reduction = max(0, daily_cals - cal_floor)
    cal_reduction = min(remaining_gap / eating_days, max_reduction) if remaining_gap > 0 else 0
    remaining_gap -= cal_reduction * eating_days
    recommendations["cal_reduction_per_day"] = round(cal_reduction)
    recommendations["new_daily_calories"] = round(daily_cals - cal_reduction)

    # 3. Increase run duration
    if remaining_gap > 0:
        extra_min = remaining_gap / 50  # ~10 cal/min x 5 days
        remaining_gap -= extra_min * 50
        recommendations["extra_run_minutes"] = round(extra_min)

    # 4. Tempo swaps
    if remaining_gap > 0:
        avg_run_burn = (run_burn / max(len(runs), 1))
        tempo_swaps = min(3, ceil(remaining_gap / max(avg_run_burn * 0.3, 50)))
        remaining_gap -= tempo_swaps * max(avg_run_burn * 0.3, 50)
        recommendations["tempo_swap_days"] = tempo_swaps

    if remaining_gap > 0:
        recommendations["shortfall"] = round(remaining_gap)

    recommendations["protein_floor_grams"] = round(target_weight)

    return jsonify({
        "on_pace": False,
        "current_weight": current_weight,
        "target_weight": target_weight,
        "weeks_remaining": weeks_remaining,
        "required_weekly_loss": round(required_weekly_loss, 1),
        "current_deficit": round(current_deficit),
        "required_deficit": round(required_deficit),
        "gap": round(gap),
        "bmr": round(bmr),
        "recommendations": recommendations,
    })


@app.route("/api/bmr-recalculate", methods=["POST"])
@login_required
def api_bmr_recalculate():
    """Recalculate BMR from actual weight loss data."""
    data = request.get_json()
    actual_loss = data.get("actual_weekly_loss", 0)
    weekly_intake = data.get("weekly_intake", 0)
    exercise_burn = data.get("exercise_burn", 0)
    run_burn = data.get("run_burn", 0)

    if actual_loss <= 0:
        return jsonify({"error": "No weight loss to calculate from"}), 400

    actual_deficit = actual_loss * 3500
    actual_expenditure = weekly_intake + actual_deficit
    actual_bmr = (actual_expenditure - exercise_burn - run_burn) / 7

    # Sanity bounds — BMR outside 1000-3000 for most adults is likely data error
    if actual_bmr < 1000 or actual_bmr > 3000:
        return jsonify({"error": "Computed BMR outside reasonable range", "computed": round(actual_bmr)}), 400

    # Save to DB
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if pa:
        pa.actual_bmr = round(actual_bmr)
        db.session.commit()

    return jsonify({"actual_bmr": round(actual_bmr)})


# ─── OVERRIDE ENDPOINTS ──────────────────────────────────────────────────

@app.route("/api/schedule-overrides")
@login_required
def api_schedule_overrides():
    """Get schedule overrides for a given week."""
    state = _get_state()
    week = request.args.get("week", _current_week(), type=int)
    overrides = WeeklyScheduleOverride.query.filter_by(user_id=current_user.id, week=week).all()
    return jsonify([{
        "day_idx": o.day_idx, "workout_time": o.workout_time,
        "skip_day": o.skip_day, "notes": o.notes,
    } for o in overrides])


@app.route("/api/meal-overrides")
@login_required
def api_meal_overrides():
    """Get meal plan overrides for a given week."""
    state = _get_state()
    week = request.args.get("week", _current_week(), type=int)
    overrides = MealPlanOverride.query.filter_by(user_id=current_user.id, week=week).all()
    return jsonify([{
        "day_idx": o.day_idx, "meal_type": o.meal_type, "reason": o.reason,
    } for o in overrides])


@app.route("/api/run-overrides")
@login_required
def api_run_overrides():
    """Get run overrides for a given week."""
    state = _get_state()
    week = request.args.get("week", _current_week(), type=int)
    overrides = RunOverride.query.filter_by(user_id=current_user.id, week=week).all()
    return jsonify([{
        "day_idx": o.day_idx, "duration": o.duration,
        "run_type": o.run_type, "reason": o.reason,
    } for o in overrides])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
