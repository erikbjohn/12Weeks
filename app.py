"""Flask app for 12 Weeks Tracker with Garmin integration."""

import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import date, timedelta, datetime, timezone
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, Response, redirect, url_for, flash, make_response
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
    ProgressPhoto, PsychIntake, GarminTokens, GarminActivity, GarminWorkoutLink, GarminWellness, PhysicalAssessment,
    UserConstraints, TrainingGoal, UserFoodSelections, WeeklyReport,
    UserEquipment, BodyweightRetest, WarmupCompletion, RunLog, SetLog, CoachMemory, CoachRule,
    ComplianceState, MuscleGroupProfile, SessionAnalysis,
    DailyCoachState, WeeklyScheduleOverride, MealPlanOverride, RunOverride,
    Exercise, WeeklyPrescription, WeeklyMealPlan,
    WeeklyRunPlan, WeeklyWarmup, WeeklyDaySchedule,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# ─── MODEL CONSTANTS ──────────────────────────────────────────────────────
CLAUDE_OPUS = "claude-opus-4-7"
CLAUDE_SONNET = "claude-sonnet-4-6"


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
# Long-running LLM calls during the planning endpoint (4 Sonnet calls,
# 30-60s total) were causing the DB connection to die mid-request
# ("SSL SYSCALL error: EOF detected"). pool_pre_ping checks each
# connection before use and reconnects if dead; pool_recycle forces
# reconnect after the connection has been open for N seconds, beating
# Postgres' tcp_keepalives_idle.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
}
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

    # Fix indexes that db.create_all() may have created as UNIQUE.
    # These MUST be non-unique — multiple users need rows for the same date/week.
    # PostgreSQL: plain indexes use DROP INDEX, constraints need ALTER TABLE DROP CONSTRAINT.
    _broken_indexes = [
        ("body_measurement", "ix_body_measurement_log_date", "CREATE INDEX IF NOT EXISTS ix_body_measurement_log_date ON body_measurement (log_date)"),
        ("body_weight", "ix_body_weight_log_date", "CREATE INDEX IF NOT EXISTS ix_body_weight_log_date ON body_weight (log_date)"),
        ("day_completion", "day_completion_week_day_idx_key", "CREATE INDEX IF NOT EXISTS ix_day_completion_user ON day_completion (user_id, week, day_idx)"),
        ("exercise_completion", "exercise_completion_week_day_idx_exercise_idx_key", "CREATE INDEX IF NOT EXISTS ix_exercise_completion_user ON exercise_completion (user_id, week, day_idx, exercise_idx)"),
        ("meal_log", "ix_meal_log_log_date", "CREATE INDEX IF NOT EXISTS ix_meal_log_user_date ON meal_log (user_id, log_date)"),
        ("morning_checkin", "ix_morning_checkin_log_date", "CREATE INDEX IF NOT EXISTS ix_morning_checkin_user_date ON morning_checkin (user_id, log_date)"),
        ("supplement_log", "supplement_log_log_date_supplement_name_key", "CREATE INDEX IF NOT EXISTS ix_supplement_log_user ON supplement_log (user_id, log_date, supplement_name)"),
        ("weekly_checkin", "weekly_checkin_week_key", "CREATE INDEX IF NOT EXISTS ix_weekly_checkin_user_week ON weekly_checkin (user_id, week)"),
        ("weekly_report", "weekly_report_week_key", "CREATE INDEX IF NOT EXISTS ix_weekly_report_user_week ON weekly_report (user_id, week)"),
    ]
    for _tbl, _drop_name, _create_sql in _broken_indexes:
        for _drop_sql in [f'DROP INDEX IF EXISTS {_drop_name}', f'ALTER TABLE {_tbl} DROP CONSTRAINT IF EXISTS {_drop_name}']:
            try:
                db.session.execute(text(_drop_sql))
                db.session.commit()
                break
            except Exception:
                db.session.rollback()
        try:
            db.session.execute(text(_create_sql))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Add missing columns to existing tables (db.create_all doesn't ALTER)
    _migrations = [
        ("physical_assessment", "stomach_inches", "FLOAT"),
        ("physical_assessment", "chest_inches", "FLOAT"),
        ("physical_assessment", "bicep_inches", "FLOAT"),
        ("physical_assessment", "thigh_inches", "FLOAT"),
        ("physical_assessment", "hips_inches", "FLOAT"),
        ("physical_assessment", "neck_inches", "FLOAT"),
        ("physical_assessment", "burpee_count", "INTEGER"),
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
        ("training_goal", "tdee", "INTEGER"),
        ("exercise_swap", "original_name", "VARCHAR(120)"),
        ("run_log", "source", "VARCHAR(20)"),
        ("weekly_run_plan", "segments_json", "TEXT"),
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

    # Backfill TDEE for existing goals that don't have it
    try:
        from goal_engine import compute_tdee
        goals_without_tdee = TrainingGoal.query.filter(TrainingGoal.tdee.is_(None)).all()
        for g in goals_without_tdee:
            pa = PhysicalAssessment.query.filter_by(user_id=g.user_id).first()
            bw = BodyWeight.query.filter_by(user_id=g.user_id).order_by(BodyWeight.log_date.desc()).first()
            w = (bw.weight_lbs if bw else None) or (pa.bodyweight_lbs if pa else None) or 180
            h = (pa.height_inches if pa else None) or 70
            tdee_info = compute_tdee(w, h, 30, "male")
            g.tdee = tdee_info["tdee"]
        db.session.commit()
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


def _exercise_at_slot(user_id, week, day_idx, exercise_idx, _cache=None):
    """Resolve the original exercise name at (week, day_idx, exercise_idx) for a user.

    Mirrors api_workouts: WeeklyPrescription overrides take the whole day if any rows
    exist, otherwise the canonical program template (gym vs. bodyweight, phase/deload)
    runs through auto_swap_workout for equipment substitutions. The result is the same
    name the UI shows as the "original" on the swap card. Pass an empty dict as _cache
    to amortise the day lookup across repeated calls for the same (user, week, day).
    Returns None when the slot is out of range or the day is empty.
    """
    from equipment_swaps import auto_swap_workout
    from workout_data import get_workouts, get_workouts_for_user

    cache_key = (user_id, week, day_idx)
    if _cache is not None and cache_key in _cache:
        exercises = _cache[cache_key]
    else:
        rx = (WeeklyPrescription.query
              .filter_by(user_id=user_id, week=week, day_idx=day_idx)
              .order_by(WeeklyPrescription.exercise_order)
              .all())
        if rx:
            exercises = [{"name": r.exercise_name, "note": r.note or ""} for r in rx]
        else:
            pa = PhysicalAssessment.query.filter_by(user_id=user_id).first()
            has_gym = pa.has_gym if pa else True
            try:
                days = get_workouts(week) if has_gym else get_workouts_for_user(week, has_gym=False)
            except Exception:
                days = []
            if day_idx < 0 or day_idx >= len(days):
                exercises = []
            else:
                exercises = days[day_idx].get("exercises", []) or []

        if exercises:
            eq = UserEquipment.query.filter_by(user_id=user_id).first()
            user_equipment = eq.available_equipment if eq else []
            try:
                exercises = auto_swap_workout(exercises, user_equipment)
            except Exception:
                pass

        if _cache is not None:
            _cache[cache_key] = exercises

    if not exercises or exercise_idx < 0 or exercise_idx >= len(exercises):
        return None
    return exercises[exercise_idx].get("name")


def _parse_coach_markers(text, user_id, week):
    """Parse structured markers from coach response and apply them."""
    import re
    import logging
    from equipment_swaps import is_valid_swap
    from workout_data import resolve_name
    # [SWAP: day_idx=N, exercise_idx=N, old=Name, new=Name, reason=text]
    # (CORE_PROMPT format — see coach_assembler.py CORE_PROMPT <markers>)
    for m in re.finditer(
        r'\[SWAP:\s*day_idx=(\d+),\s*exercise_idx=(\d+),\s*old=([^,]+),\s*new=([^,]+),\s*reason=([^\]]+)\]',
        text,
    ):
        try:
            day_idx = int(m.group(1))
            exercise_idx = int(m.group(2))
            new_name = resolve_name(m.group(4).strip())
            # Resolve the original from the actual plan, not the marker's `old=` —
            # if the LLM hallucinates a stale `old`, we still validate against truth.
            original_name = _exercise_at_slot(user_id, week, day_idx, exercise_idx)
            if original_name is None:
                logging.warning(
                    f"Coach SWAP rejected: no exercise at slot week={week} "
                    f"day={day_idx} idx={exercise_idx} (user {user_id})"
                )
                continue
            if not is_valid_swap(original_name, new_name):
                logging.warning(
                    f"Coach SWAP rejected: '{new_name}' is not a valid alternative "
                    f"for '{original_name}' at week={week} day={day_idx} "
                    f"idx={exercise_idx} (user {user_id})"
                )
                continue
            existing = ExerciseSwap.query.filter_by(
                user_id=user_id, week=week, day_idx=day_idx, exercise_idx=exercise_idx
            ).first()
            if existing:
                existing.swapped_to = new_name
                existing.original_name = original_name
            else:
                db.session.add(ExerciseSwap(
                    user_id=user_id, week=week, day_idx=day_idx,
                    exercise_idx=exercise_idx, swapped_to=new_name,
                    original_name=original_name,
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

    # [SORENESS: area=shoulders, level=moderate]
    for m in re.finditer(r'\[SORENESS:\s*area=([^,\]]+)(?:,\s*level=([^\]]+))?\]', text):
        try:
            area = m.group(1).strip().lower()
            level = m.group(2).strip() if m.group(2) else 'moderate'
            # Save to the latest MorningCheckIn notes so warmup generator picks it up
            latest_ci = MorningCheckIn.query.filter_by(user_id=user_id).order_by(MorningCheckIn.log_date.desc()).first()
            if latest_ci:
                soreness_note = f'[SORENESS: {area}]'
                if latest_ci.notes and soreness_note not in latest_ci.notes:
                    latest_ci.notes = (latest_ci.notes or '') + ' ' + soreness_note
                elif not latest_ci.notes:
                    latest_ci.notes = soreness_note
                latest_ci.soreness = {'mild': 3, 'moderate': 5, 'severe': 7}.get(level, 5)
            # Also save as a coach memory for future reference
            db.session.add(CoachMemory(user_id=user_id, content=f'Athlete reports {level} soreness/tightness in {area}', memory_type='observation', week=week))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # [RUN: day=X, duration=50 min, type=zone2, reason=...]
    # Collect weeks to push; spawn ONE thread after the loop so two markers in
    # the same reply don't create two concurrent push_week calls on the same week
    # (duplicate scheduled workouts, orphaned workout ids).
    _garmin_weeks_to_push = set()
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
            # CODIFY, don't just advise: update the canonical WeeklyRunPlan row the
            # day card + regen actually read, so the coach's stated run change is
            # really applied (the bug where "holding at 40" left the plan at 38).
            wrp = WeeklyRunPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if wrp:
                wrp.duration = duration
                if run_type:
                    wrp.run_type = run_type
                wrp.source = 'coach'
                wrp.segments_json = None  # duration changed — old structure is void
            else:
                db.session.add(WeeklyRunPlan(
                    user_id=user_id, week=week, day_idx=day_idx,
                    run_type=run_type or 'z2', label=run_type or 'Run',
                    duration=duration, detail=reason, source='coach'))
            db.session.commit()
            _garmin_weeks_to_push.add(week)
        except Exception:
            db.session.rollback()
    # Re-push all affected weeks to Garmin in a single off-thread serial pass:
    # up to 3 Garmin HTTP calls must not block the SSE worker; the per-user lock
    # inside _garmin_push_week_best_effort prevents any overlap with the
    # generation hook's push that may fire concurrently.
    if _garmin_weeks_to_push:
        def _repush_async(uid=user_id, weeks=tuple(_garmin_weeks_to_push)):
            try:
                with app.app_context():
                    for wk in weeks:
                        _garmin_push_week_best_effort(uid, wk)
            except Exception:
                logging.exception("[GARMIN] async re-push failed")
        threading.Thread(target=_repush_async, daemon=True).start()

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

            # GUARD: never let the coach write a prescription weight that's
            # below 95% of the user's recent top set unless this is an
            # explicit deload week. The coach has historically hallucinated
            # low weights into the wave (e.g. bench at 100 when the user has
            # done 135), then blamed "the engine" for the regression in chat.
            # This guard refuses the write at the data layer so the wave can
            # never drop below proven capacity outside a deload.
            if p_weight is not None and p_weight > 0 and p_week not in (4, 8):
                top = db.session.query(db.func.max(SetLog.weight)).filter(
                    SetLog.user_id == user_id,
                    SetLog.exercise_name == p_exercise,
                    SetLog.weight > 0,
                ).scalar()
                if top is not None and p_weight < top * 0.95:
                    import logging
                    logging.warning(
                        "PRESCRIPTION guard: rejected coach write %s wk %s @ %s lb "
                        "(below 95%% of recent top set %s lb)",
                        p_exercise, p_week, p_weight, top,
                    )
                    continue
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
# Per-user push locks: serializes concurrent push_week calls (marker thread vs
# generation hook) so a single user never has two simultaneous pushes racing.
_garmin_push_locks: dict = {}
_garmin_push_locks_guard = threading.Lock()


def _get_garmin(user_id=None):
    """Get or create a Garmin client for the current user."""
    uid = user_id or (current_user.id if current_user and current_user.is_authenticated else None)
    if not uid:
        return GarminClient()
    if uid not in _garmin_clients:
        client = GarminClient(user_id=uid)
        _garmin_clients[uid] = client
    return _garmin_clients[uid]


def _garmin_linked(uid):
    """True if the user has a saved Garmin token. This is the durable
    'connected' state — it survives server restarts and outlives any single
    in-memory session. The live session (gc.connected) is just a cache; losing
    it (deploy, rate-limited restore) must NEVER present as 'logged out' while a
    token exists."""
    try:
        return GarminTokens.query.filter_by(user_id=uid).first() is not None
    except Exception:
        return False


def _garmin_push_week_best_effort(user_id, week):
    """Push a week's planned runs/HIIT to Garmin. Best-effort: never raises —
    a Garmin failure must never break planning or chat.

    Serialized per user via _garmin_push_locks so concurrent callers (marker
    thread + generation hook) queue instead of racing on the same week."""
    with _garmin_push_locks_guard:
        lock = _garmin_push_locks.setdefault(user_id, threading.Lock())
    with lock:
        try:
            import garmin_sync
            gc = _get_garmin(user_id)
            if not gc.connected:
                gc.try_restore_tokens(user_id)
            if not gc.connected:
                return
            # User-local 'today' WITHOUT request context (helper runs in worker threads).
            try:
                from utils_time import user_local_now
                _u = User.query.get(user_id)
                tz = _u.timezone if _u and getattr(_u, "timezone", None) else "UTC"
                local_today = user_local_now(tz).date()
            except Exception:
                local_today = date.today()
            res = garmin_sync.push_week(gc, user_id, week, today=local_today)
            logging.info("[GARMIN] push wk%s: pushed=%s skipped=%s failed=%s",
                         week, len(res["pushed"]), len(res["skipped"]), len(res["failed"]))
        except Exception:
            logging.exception("[GARMIN] best-effort push failed (wk%s)", week)


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
    """Compute current program week from start_date (not stale DB value).

    Persists the computed value back to AppState when it has drifted, so any
    code that reads state.current_week directly (admin queries, exports,
    audit fixtures, debug dashboards) sees the same value the rest of the
    app derives. AppState.current_week was being initialized at 1 and never
    auto-incrementing as time passed — Erik's row sat at 5 even after he
    started training Week 6, which broke the audit harness's ground-truth
    assumptions and made admin queries misleading."""
    try:
        s = _get_state()
        if s.start_date:
            diff_days = (_user_today() - s.start_date).days
            week = min(12, max(1, diff_days // 7 + 1))
            if s.current_week != week:
                s.current_week = week
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            return week
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
    """Meal day-type for a day. The athlete's ACTUAL prescribed run + lift are
    the source of truth — never a stale cached day_type, never the template's
    weekday assumption.

    This is the bug that kept putting "Long Run Day" on an interval Tuesday:
    the old code returned the cached WeeklyMealPlan.day_type FIRST, and the meal
    regenerator computes day-types FROM this function — so the stale "long_run"
    fed its own regeneration and could never be healed. And even the derive path
    read the TEMPLATE's run, not the athlete's replanned VO2 run. Now we overlay
    the real WeeklyRunPlan run before deriving, and the cache may never override
    a derivation that contradicts it.

    Fast days are goal-dependent: only 'cut' goals get true fast days.
    Bulk and recomp users get 'rest' on Sunday instead.
    """
    from workout_data import (DAY_MEAL_TYPES, derive_meal_type,
                              get_workouts, get_workouts_for_user)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday = day_names[day_idx] if day_idx < 7 else "Mon"

    # 1. Explicit override wins — a deliberate coach/user decision.
    try:
        override = MealPlanOverride.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if override and override.meal_type:
            return override.meal_type
    except Exception:
        pass

    # 2. Derive from the day's ACTUAL run (WeeklyRunPlan) + lift, overlaid on the
    #    template. Authoritative: the meal label must match what the athlete is
    #    actually doing — a replanned VO2 Tuesday is intervals, not a long run.
    derived = None
    try:
        pa = PhysicalAssessment.query.filter_by(user_id=user_id).first()
        has_gym = pa.has_gym if pa else True
        tdays = (get_workouts(week) if has_gym
                 else get_workouts_for_user(week, has_gym=False))
        day_dict = dict(tdays[day_idx]) if day_idx < len(tdays) else {}
        try:
            rp = WeeklyRunPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            if rp and rp.run_type:
                day_dict["run"] = {"type": rp.run_type, "label": rp.label,
                                   "time": rp.duration, "detail": rp.detail or ""}
        except Exception:
            pass
        derived = derive_meal_type(day_dict, weekday)
    except Exception:
        derived = None

    # 3. Fall back to the stored cache ONLY when derivation is impossible, then
    #    the weekday map. The cache may not override a contradicting derivation.
    if derived is None:
        try:
            wmp = WeeklyMealPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
            derived = wmp.day_type if (wmp and wmp.day_type) else None
        except Exception:
            derived = None
    meal_type = derived or DAY_MEAL_TYPES.get(weekday, "moderate")

    # Fast days only make sense for cut goals.
    # Bulk/recomp users get a rest day instead.
    if meal_type == "fast_day":
        try:
            goal = TrainingGoal.query.filter_by(user_id=user_id).order_by(TrainingGoal.id.desc()).first()
            if goal and goal.goal_type in ("bulk", "recomp"):
                return "rest"
        except Exception:
            pass

    return meal_type


# Barbell movements load a 45-lb Olympic bar. With no 2.5-lb micro-plates (the
# smallest plate is 5 lb → a 10-lb pair jump), every achievable barbell total is
# 45 + 10k, i.e. it ALWAYS ENDS IN 5 (45, 55, 65, … 145, 155). A barbell bench is
# never 150. Dumbbells and machine stacks move in 5-lb steps.
_BARBELL_RE = re.compile(
    r"barbell|bench press|back squat|front squat|deadlift|overhead press|\bohp\b|"
    r"bent[- ]?over row|hip thrust|romanian deadlift|\brdl\b", re.I)
_DB_RE = re.compile(r"\bdb\b|dumbbell", re.I)


def _is_barbell_movement(name: str) -> bool:
    nm = name or ""
    if _DB_RE.search(nm):  # "DB Overhead Press", "Incline DB Press" are NOT barbell
        return False
    return bool(_BARBELL_RE.search(nm))


def _round_to_loadable(exercise_name: str, w):
    """Round a prescribed load to one the athlete can actually build on the bar.
    Barbell → 45 + 10k (ends in 5), floored at the empty 45-lb bar. Everything
    else → nearest 5 lb. Ties round UP (progression-friendly)."""
    if not w or w <= 0:
        return w
    if _is_barbell_movement(exercise_name):
        k = int((float(w) - 45.0) / 10.0 + 0.5)  # round half up
        return float(max(45, 45 + 10 * k))
    return float(int(float(w) / 5.0 + 0.5) * 5)


def _honest_lift_reason(final, recent_top, really_new, is_barbell=False) -> str:
    """A number-correct reason built from facts — used to REPLACE a coach `why`
    that would contradict the prescribed number (the '+2.5 from 145 but shows
    150' / 'new movement but logged at 35' class)."""
    if not final or final <= 0:
        return "Bodyweight — no added load."
    if really_new or recent_top is None:
        if really_new:
            return f"New movement — starting light at {final:g} lb to groove the pattern."
        return f"Set at {final:g} lb."
    if final > recent_top:
        return f"Up to {final:g} lb from your last {recent_top:g} lb."
    if final < recent_top:
        return f"Held at {final:g} lb."
    # "isn't loadable on the bar" only makes sense for a BARBELL — never say it
    # about a dumbbell/cable/machine (a Rear Delt Fly has no bar).
    tail = " (a smaller bump isn't loadable on the bar)" if is_barbell else ""
    return f"Holding {final:g} lb to consolidate{tail}."


def _reconcile_lift_reason(reason, final, proposed, recent_top, really_new,
                           is_barbell=False) -> str:
    """If the coach's `why` would contradict the prescribed number — cites a
    weight that isn't the final load, implies a delta that doesn't add up, or
    claims a 'new/baseline' movement that actually has history — replace it with
    an honest, fact-built reason. Otherwise keep the coach's reasoning."""
    reason = (reason or "").strip()
    asserts_load = bool(re.search(r"(?:to|->|→|\+|holding at|hold at|\bat)\s*\$?\d", reason, re.I)) or "from" in reason.lower()
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*lb", reason)]
    num_contradiction = (final is not None and asserts_load
                         and any(abs(n - final) > 0.01 for n in nums))
    m = re.search(r"\+\s*(\d+(?:\.\d+)?)\s*lb\s*from\s*(?:last week'?s?\s*)?(\d+(?:\.\d+)?)", reason, re.I)
    if m and final is not None and abs((float(m.group(1)) + float(m.group(2))) - final) > 0.01:
        num_contradiction = True
    claims_new = bool(re.search(r"new movement|deliberately light|establish\w*\s+\w*\s*baseline|"
                                r"first (?:time|exposure)|introduc(?:e|ing|ed)", reason, re.I))
    false_new = claims_new and not really_new
    rounded_changed = (final is not None and proposed is not None
                       and abs(float(final) - float(proposed)) > 0.01)
    if num_contradiction or false_new or rounded_changed:
        return _honest_lift_reason(final, recent_top, really_new, is_barbell)
    return reason


def _reconcile_prescription_to_logged(user_id, exercise, logged_weight, from_week):
    """Auto-reconcile: when an athlete logs a BARBELL lift heavier than its
    prescription, raise the plan (this week + forward, skipping deload weeks
    4/8/12) up to the loadable logged weight — so the card never shows "plan 145"
    next to a logged 155. This is the same logic as /api/admin/heal-prescriptions,
    fired automatically at log time for ONE lift instead of by hand.

    Barbell only: isolations may be deliberately light (new-movement light-starts)
    and must NOT be force-raised. Never lowers a plan. Returns the changed rows.
    """
    if not exercise or not logged_weight or logged_weight <= 0:
        return []
    if not _is_barbell_movement(exercise):
        return []
    target = _round_to_loadable(exercise, logged_weight)
    changed = []
    rows = WeeklyPrescription.query.filter(
        WeeklyPrescription.user_id == user_id,
        WeeklyPrescription.exercise_name == exercise,
        WeeklyPrescription.week >= from_week,
    ).all()
    for rx in rows:
        if rx.week in (4, 8, 12):  # deload weeks stay light
            continue
        if rx.target_weight is None or rx.target_weight <= 0:
            continue
        if rx.target_weight >= target:  # never lower, never redundant
            continue
        old = rx.target_weight
        rx.adjustment_reason = _reconcile_lift_reason(
            rx.adjustment_reason or "", target, old, logged_weight, False, True)
        rx.target_weight = target
        changed.append({"week": rx.week, "day": rx.day_idx,
                        "from": old, "to": target})
    if changed:
        db.session.commit()
    return changed


_MUSCLE_LABELS = {
    "chest": "Chest", "chest_triceps": "Chest & Triceps", "back": "Back",
    "traps": "Traps", "shoulders": "Shoulders", "rear_delts": "Rear Delts",
    "quads": "Quads", "posterior_chain": "Posterior Chain",
    "hamstrings": "Hamstrings", "glutes": "Glutes", "calves": "Calves",
    "biceps": "Biceps", "triceps": "Triceps", "full_body": "Full Body",
    "power": "Power", "core": "Core",
}


def _derive_lift_name(exercise_names):
    """Build an ACCURATE day title from the muscle groups the day actually
    trains. The template's day label ("HEAVY Lower", "Shoulder/Arms") goes stale
    when the coach redesigns the exercises — naming the day from its real
    contents kills the liftName-vs-exercises contradiction class."""
    from collections import Counter
    from workout_data import EXERCISES, resolve_name
    counts = Counter()
    for nm in exercise_names or []:
        info = EXERCISES.get(nm) or EXERCISES.get(resolve_name(nm)) or {}
        g = info.get("muscle_group")
        if not g:
            n = (nm or "").lower()
            if any(k in n for k in ("squat", "lunge", "leg press", "step-up")):
                g = "quads"
            elif "deadlift" in n or "rdl" in n or "good morning" in n:
                g = "posterior_chain"
            elif "calf" in n:
                g = "calves"
        if g:
            counts[g] += 1
    if not counts:
        return None
    # Core/abs don't name the day unless that's all there is.
    non_core = {g: c for g, c in counts.items() if g != "core"}
    use = non_core or counts
    top = [g for g, _ in sorted(use.items(), key=lambda kv: (-kv[1], kv[0]))][:2]
    name = " & ".join(_MUSCLE_LABELS.get(g, g.replace("_", " ").title()) for g in top)
    if non_core and "core" in counts:
        name += " + Core"
    return name


def _reconcile_lift_name(current, exercise_names):
    """Keep a curated day title when it matches the movements; replace it with a
    muscle-derived title only when it names the WRONG region (a Lower title over
    an all-upper list) OR omits the day's DOMINANT muscle while naming specific
    others ("Shoulder/Arms" on a back-dominant day). Region/pattern labels
    ("HEAVY Lower", "Full Body", "Pull + Lat") that match are trusted as-is."""
    from collections import Counter
    from workout_data import EXERCISES, resolve_name
    derived = _derive_lift_name(exercise_names)
    if not derived or not current:
        return current
    counts = Counter()
    for nm in exercise_names or []:
        g = (EXERCISES.get(nm) or EXERCISES.get(resolve_name(nm)) or {}).get("muscle_group")
        if not g:
            n = (nm or "").lower()
            if any(k in n for k in ("squat", "lunge", "leg press", "step-up")):
                g = "quads"
            elif "deadlift" in n or "rdl" in n:
                g = "posterior_chain"
            elif "calf" in n:
                g = "calves"
        if g and g != "core":
            counts[g] += 1
    if not counts:
        return current
    UPPER = {"chest", "chest_triceps", "back", "traps", "shoulders", "rear_delts", "biceps", "triceps"}
    LOWER = {"quads", "posterior_chain", "hamstrings", "glutes", "calves"}
    nu = sum(c for g, c in counts.items() if g in UPPER)
    nl = sum(c for g, c in counts.items() if g in LOWER)
    region = "upper" if nu > nl else ("lower" if nl > nu else "full")
    c = current.lower()
    c_lower = any(k in c for k in ("lower", "squat", "quad", "glute", "hamstring", "deadlift", "rdl", "leg", "calf", "hip thrust", "posterior"))
    c_upper = any(k in c for k in ("upper", "press", "bench", "push", "pull", "row", "shoulder", "chest", "back", "lat", "curl", "tricep", "bicep", "ohp", "delt", "arm"))
    c_region = "lower" if (c_lower and not c_upper) else ("upper" if (c_upper and not c_lower) else None)
    if c_region and region in ("upper", "lower") and c_region != region:
        return derived  # outright region swap
    if any(w in c for w in ("upper", "lower", "full", "push", "pull", "press")):
        return current  # a region/pattern label that matches the region — trust it
    dominant = counts.most_common(1)[0][0]
    DOM_KW = {
        "chest": ("chest",), "chest_triceps": ("chest", "tricep"),
        "back": ("back", "lat"), "shoulders": ("shoulder", "delt"),
        "rear_delts": ("shoulder", "delt", "rear"), "traps": ("trap", "shrug"),
        "quads": ("quad", "squat", "leg"), "glutes": ("glute", "hip"),
        "hamstrings": ("hamstring", "ham"), "calves": ("calf",),
        "biceps": ("bicep", "arm", "curl"), "triceps": ("tricep", "arm"),
    }
    kws = DOM_KW.get(dominant, ())
    if kws and not any(k in c for k in kws):
        return derived  # title names specific muscles but omits the dominant one
    return current


def _day_has_training(user_id, week, day_idx):
    """True if the day has a prescribed run or lift. A fast day can still be a
    fasted-TRAINING day (the Sunday long fasted run, a fasted lift day) — so its
    meal note must not say "rest and recover" when there's training on the card."""
    try:
        if WeeklyRunPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first():
            return True
        if WeeklyPrescription.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first():
            return True
    except Exception:
        pass
    return False


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

    # Generate detail text that matches the actual progressed duration
    detail = template_run.get('detail', '')
    if new_minutes != base_minutes and base_type in ('z2', 'long', 'tempo'):
        if base_type == 'tempo':
            warmup = 5
            cooldown = 5
            tempo_portion = max(new_minutes - warmup - cooldown, 10)
            detail = f"HR 155-165. {warmup} min easy warmup, {tempo_portion} min at tempo, {cooldown} min cooldown."
        elif base_type in ('z2', 'long'):
            detail = f"HR 130-145. Easy conversational pace. {new_minutes} minutes total."

    return {
        'type': base_type,
        'label': template_run.get('label', 'Run'),
        'time': f"{new_minutes} min" if base_type != 'min' else base_time,
        'detail': detail,
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
    """Quick health check — returns status of key tables + deployed commit."""
    import os as _os
    results = {"commit": (_os.environ.get("RENDER_GIT_COMMIT") or "local")[:12]}
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
            "moderate": "training", "fast_day": "fast_day",
        }
        day_types = [_get_day_meal_type(current_user.id, target_week, d) for d in range(7)]

        # Identify days the athlete has already logged meals for — those are
        # historical and must not be overwritten. Even today, if any meal is
        # checked off, the prescription view becomes a record of what was
        # consumed; regenerating would wipe that.
        today = _user_today()
        week_monday = today - timedelta(days=today.weekday())
        protected_dates = set()
        for d_idx in range(7):
            d_date = week_monday + timedelta(days=d_idx)
            mlog = MealLog.query.filter_by(
                user_id=current_user.id, log_date=d_date,
            ).first()
            if mlog and (mlog.eaten or []):
                protected_dates.add(d_date)
            elif d_date < today:
                # Past dates with no log are still 'past' — don't regenerate.
                protected_dates.add(d_date)

        # Delete only meal plans for days we'll actually regenerate
        for d_idx in range(7):
            d_date = week_monday + timedelta(days=d_idx)
            if d_date in protected_dates:
                continue
            WeeklyMealPlan.query.filter_by(
                user_id=current_user.id, week=target_week, day_idx=d_idx,
            ).delete()

        meal_summary = []
        for day_idx in range(7):
            day_date = week_monday + timedelta(days=day_idx)
            if day_date in protected_dates:
                continue  # Logged meals or past day — preserve history
            day_type = day_types[day_idx]
            if day_type == 'fast_day':
                # Use user's selected foods with fast-day calorie target
                cal_day_type = _cal_day_type_map.get(day_type, "rest")
                day_macros = compute_day_calories(base_calories, goal.goal_type or 'cut', cal_day_type, current_weight)
                meal_plan = generate_meal_plan(
                    selected_foods=fs.selected_foods, day_type='fast_day',
                    targets=day_macros, fasting_protocol=fasting_protocol,
                    has_training=_day_has_training(current_user.id, target_week, day_idx),
                )
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


@app.route("/api/debug/override-day-with-actual")
def debug_override_day_with_actual():
    """Take the user's logged SetLog rows for (logged_date, day_idx) and write
    them to WeeklyPrescription for (week, day_idx) so the UI shows the actual
    session that was done instead of the template. One-shot recovery for when
    the user's session doesn't match the template for that day.

    Token-gated. Query: ?email=...&date=YYYY-MM-DD&week=6&day_idx=4&token=...
    """
    email = request.args.get("email", "")
    date_str = request.args.get("date", "")
    week = int(request.args.get("week", 0))
    day_idx = int(request.args.get("day_idx", -1))
    token = request.args.get("token", "")
    if token != "swap-cleanup-2026-04-30":
        return jsonify({"error": "bad token"}), 403
    if not email or not date_str or not week or day_idx < 0:
        return jsonify({"error": "email + date + week + day_idx required"}), 400
    try:
        from datetime import datetime as _dt
        from models import User, SetLog, WeeklyPrescription
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        target_date = _dt.strptime(date_str, "%Y-%m-%d").date()

        # Pull all sets for that user/date — collapse to one row per
        # (exercise_name) with sets count and rep range.
        rows = SetLog.query.filter_by(user_id=u.id, logged_date=target_date).all()
        if not rows:
            return jsonify({"error": "no SetLog rows on that date"}), 404
        by_ex: dict = {}
        for r in rows:
            by_ex.setdefault(r.exercise_name, []).append(r)

        # Wipe existing WeeklyPrescription for this (week, day_idx) — start clean.
        WeeklyPrescription.query.filter_by(
            user_id=u.id, week=week, day_idx=day_idx,
        ).delete()

        # Insert new prescription rows: one per exercise, sets=count, reps=mode.
        order = 0
        created = []
        for ex_name, sets in by_ex.items():
            n_sets = len(sets)
            reps_list = [s.reps for s in sets if s.reps]
            reps_str = str(max(set(reps_list), key=reps_list.count)) if reps_list else "5"
            top_weight = max((s.weight or 0) for s in sets) or None
            wp = WeeklyPrescription(
                user_id=u.id, week=week, day_idx=day_idx,
                exercise_order=order, exercise_name=ex_name,
                sets=n_sets, reps=reps_str, rest="60-90s",
                target_weight=top_weight, source='actual',
                note='Logged session — actual content replaces template.',
            )
            db.session.add(wp)
            created.append({"order": order, "exercise": ex_name,
                            "sets": n_sets, "reps": reps_str,
                            "target_weight": top_weight})
            order += 1

        # Move the sets to (week, day_idx) so they line up
        for r in rows:
            r.week = week
            r.day_idx = day_idx

        db.session.commit()
        return jsonify({
            "email": email, "date": date_str, "week": week, "day_idx": day_idx,
            "prescription_rows_created": created,
            "set_rows_aligned": len(rows),
        })
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-2000:],
        }), 500


@app.route("/api/debug/realign-session-week")
def debug_realign_session_week():
    """Move a logged session from one week to another. Moves SetLog,
    RunLog, WeeklyPrescription, DayCompletion. Optionally resets
    AppState.current_week.

    Token-gated. Query: ?email=...&from_week=6&to_week=5&day_idx=4&date=YYYY-MM-DD&token=...
    Optional: &reset_current_week=1
    """
    email = request.args.get("email", "")
    from_week = int(request.args.get("from_week", 0))
    to_week = int(request.args.get("to_week", 0))
    day_idx = int(request.args.get("day_idx", -1))
    date_str = request.args.get("date", "")
    reset_cw = request.args.get("reset_current_week") == "1"
    token = request.args.get("token", "")
    if token != "swap-cleanup-2026-04-30":
        return jsonify({"error": "bad token"}), 403
    if not email or not from_week or not to_week or day_idx < 0 or not date_str:
        return jsonify({"error": "email + from_week + to_week + day_idx + date required"}), 400
    try:
        from datetime import datetime as _dt
        from models import (User, SetLog, RunLog, WeeklyPrescription,
                            DayCompletion, AppState)
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        target_date = _dt.strptime(date_str, "%Y-%m-%d").date()

        # 1. Move SetLog rows
        sl = SetLog.query.filter_by(
            user_id=u.id, week=from_week, day_idx=day_idx, logged_date=target_date,
        ).all()
        for r in sl:
            r.week = to_week
        sl_count = len(sl)

        # 2. Move RunLog rows
        rl = RunLog.query.filter_by(
            user_id=u.id, week=from_week, day_idx=day_idx, log_date=target_date,
        ).all()
        for r in rl:
            r.week = to_week
        rl_count = len(rl)

        # 3. Copy WeeklyPrescription rows from from_week to to_week,
        # wiping to_week's existing rows for this day_idx first.
        WeeklyPrescription.query.filter_by(
            user_id=u.id, week=to_week, day_idx=day_idx,
        ).delete()
        src_rx = WeeklyPrescription.query.filter_by(
            user_id=u.id, week=from_week, day_idx=day_idx,
        ).all()
        for r in src_rx:
            new = WeeklyPrescription(
                user_id=u.id, week=to_week, day_idx=day_idx,
                exercise_order=r.exercise_order,
                exercise_name=r.exercise_name,
                sets=r.sets, reps=r.reps, rest=r.rest,
                target_weight=r.target_weight,
                progression_indicator=r.progression_indicator,
                adjustment_reason=r.adjustment_reason,
                note=r.note, source=r.source,
            )
            db.session.add(new)
        WeeklyPrescription.query.filter_by(
            user_id=u.id, week=from_week, day_idx=day_idx,
        ).delete()
        rx_count = len(src_rx)

        # 4. Move DayCompletion
        dc_from = DayCompletion.query.filter_by(
            user_id=u.id, week=from_week, day_idx=day_idx,
        ).first()
        DayCompletion.query.filter_by(
            user_id=u.id, week=to_week, day_idx=day_idx,
        ).delete()
        if dc_from:
            new_dc = DayCompletion(
                user_id=u.id, week=to_week, day_idx=day_idx,
                done=dc_from.done,
                workout_started_at=dc_from.workout_started_at,
                workout_ended_at=dc_from.workout_ended_at,
            )
            db.session.add(new_dc)
            db.session.delete(dc_from)
        dc_moved = bool(dc_from)

        # 5. Reset AppState.current_week if requested
        cw_changed = None
        if reset_cw:
            state = AppState.query.filter_by(user_id=u.id).first()
            if state:
                cw_changed = (state.current_week, to_week)
                state.current_week = to_week

        db.session.commit()
        return jsonify({
            "email": email, "from_week": from_week, "to_week": to_week,
            "day_idx": day_idx, "date": date_str,
            "setlogs_moved": sl_count, "runlogs_moved": rl_count,
            "prescriptions_moved": rx_count, "daycompletion_moved": dc_moved,
            "current_week_changed": cw_changed,
        })
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({"error_class": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()[-2000:]}), 500


@app.route("/api/debug/api-workouts-as-user")
def debug_api_workouts_as_user():
    """Run api_workouts as if the given user were logged in, return the JSON
    payload the UI would actually receive. UNAUTH diagnostic.
    Query: ?email=...&week=6&day_idx=4
    """
    email = request.args.get("email", "erik@placemetry.com")
    week = int(request.args.get("week", 6))
    day_idx = int(request.args.get("day_idx", 4))
    try:
        from models import User
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        # Login via test_client so @login_required passes; this gives us
        # the real Flask response payload the UI would receive.
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(u.id)
                sess["_fresh"] = True
            r = c.get("/api/workouts")
            payload = r.get_json() if r.is_json else None
            status_code = r.status_code

        target_week = (payload or {}).get(str(week)) or {}
        days = target_week.get("days", [])
        target_day = days[day_idx] if day_idx < len(days) else None
        return jsonify({
            "email": email, "week": week, "day_idx": day_idx,
            "status_code": status_code,
            "payload_keys": list((payload or {}).keys())[:20],
            "lift_name": (target_day or {}).get("liftName"),
            "exercises": [{
                "name": e.get("name"), "sets": e.get("sets"),
                "target_weight": e.get("target_weight"),
            } for e in (target_day or {}).get("exercises", [])],
            "run": (target_day or {}).get("run"),
            "is_rest": (target_day or {}).get("isRest"),
        })
    except Exception as e:
        import traceback
        return jsonify({"error_class": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()[-2000:]}), 500


@app.route("/api/debug/today-status")
def debug_today_status():
    """Dump the coach's today_status GROUNDING for a user — the exact 3-state
    workout signal (not_started/in_progress/complete) plus the rendered directive
    block the model actually reads. Read-only, NO LLM call. This is the cheap way
    to verify the coach won't be told a partially-logged lift is 'done'.
    Query: ?email=...
    """
    email = request.args.get("email", "erik@placemetry.com")
    try:
        from models import User
        from flask_login import login_user
        from coach_assembler import _build_today_status, _format_today_status_block
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        with app.test_request_context():
            login_user(u, force=True)
            ts = _build_today_status().get("today_status")
            block = "\n".join(_format_today_status_block(ts)) if ts else ""
        return jsonify({"email": email, "today_status": ts, "directive_block": block})
    except Exception as e:
        import traceback
        return jsonify({"error_class": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()[-2000:]}), 500


@app.route("/api/debug/copy-runplan")
def debug_copy_runplan():
    """Copy WeeklyRunPlan rows from one week to another. Used when the run
    engine hasn't generated the next week yet and the user is already there.

    Token-gated. Query: ?email=...&from_week=5&to_week=6&token=...
    """
    email = request.args.get("email", "")
    from_week = int(request.args.get("from_week", 0))
    to_week = int(request.args.get("to_week", 0))
    token = request.args.get("token", "")
    if token != "swap-cleanup-2026-04-30":
        return jsonify({"error": "bad token"}), 403
    if not email or not from_week or not to_week:
        return jsonify({"error": "email + from_week + to_week required"}), 400
    try:
        from models import User, WeeklyRunPlan
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        # Wipe destination
        WeeklyRunPlan.query.filter_by(user_id=u.id, week=to_week).delete()
        # Copy
        src = WeeklyRunPlan.query.filter_by(user_id=u.id, week=from_week).all()
        copied = []
        for r in src:
            new = WeeklyRunPlan(
                user_id=u.id, week=to_week, day_idx=r.day_idx,
                run_type=r.run_type, label=r.label,
                duration=r.duration, detail=r.detail,
                source=r.source,
                segments_json=r.segments_json,
            )
            db.session.add(new)
            copied.append({"day_idx": r.day_idx, "label": r.label,
                           "duration": r.duration})
        db.session.commit()
        return jsonify({
            "email": email, "from_week": from_week, "to_week": to_week,
            "copied": copied, "count": len(copied),
        })
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({"error_class": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()[-2000:]}), 500


@app.route("/api/debug/full-day-state")
def debug_full_day_state():
    """Dump everything stored for a user on a date: SetLog, RunLog,
    WeeklyPrescription, WeeklyRunPlan. Read-only diagnostic.
    Query: ?email=...&date=YYYY-MM-DD&week=6&day_idx=4
    """
    email = request.args.get("email", "erik@placemetry.com")
    date_str = request.args.get("date", "")
    week = request.args.get("week", type=int)
    day_idx = request.args.get("day_idx", type=int)
    try:
        from datetime import datetime as _dt
        from models import (User, SetLog, RunLog, WeeklyPrescription,
                            WeeklyRunPlan, DayCompletion, AppState)
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        target_date = _dt.strptime(date_str, "%Y-%m-%d").date() if date_str else None

        out = {"email": email, "user_id": u.id}

        state = AppState.query.filter_by(user_id=u.id).first()
        out["app_state"] = {
            "current_week": state.current_week if state else None,
            "start_date": str(state.start_date) if state and state.start_date else None,
        }

        if target_date:
            sl = SetLog.query.filter_by(user_id=u.id, logged_date=target_date).all()
            out["setlogs_on_date"] = [{
                "id": r.id, "exercise": r.exercise_name,
                "set": r.set_number, "weight": r.weight, "reps": r.reps,
                "done": r.done, "week": r.week, "day_idx": r.day_idx,
            } for r in sl]
            rl = RunLog.query.filter_by(user_id=u.id, log_date=target_date).all()
            out["runlogs_on_date"] = [{
                "id": r.id, "week": r.week, "day_idx": r.day_idx,
                "distance_miles": r.distance_miles, "avg_hr": r.avg_hr,
                "duration_min": r.duration_min,
            } for r in rl]

        if week is not None and day_idx is not None:
            wp = (WeeklyPrescription.query
                  .filter_by(user_id=u.id, week=week, day_idx=day_idx)
                  .order_by(WeeklyPrescription.exercise_order).all())
            out[f"prescription_w{week}_d{day_idx}"] = [{
                "order": r.exercise_order, "exercise": r.exercise_name,
                "sets": r.sets, "reps": r.reps,
                "target_weight": r.target_weight, "source": r.source,
            } for r in wp]
            wrp = WeeklyRunPlan.query.filter_by(user_id=u.id, week=week).all()
            out[f"runplan_w{week}"] = [{
                "day_idx": r.day_idx, "type": r.run_type,
                "label": r.label, "duration": r.duration,
                "source": r.source,
            } for r in wrp]
            dc = DayCompletion.query.filter_by(
                user_id=u.id, week=week, day_idx=day_idx,
            ).first()
            out[f"daycompletion_w{week}_d{day_idx}"] = (
                {"done": dc.done} if dc else None
            )

        return jsonify(out)
    except Exception as e:
        import traceback
        return jsonify({"error_class": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()[-2000:]}), 500


@app.route("/api/debug/show-sets")
def debug_show_sets():
    """Dump SetLog rows for a user across recent days. UNAUTH diagnostic.
    Query: ?email=...&days=7 (default 7)
    """
    email = request.args.get("email", "erik@placemetry.com")
    days_back = int(request.args.get("days", 7))
    try:
        from datetime import date as _date, timedelta as _td
        from models import User, SetLog
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        cutoff = _date.today() - _td(days=days_back)
        rows = (SetLog.query
                .filter(SetLog.user_id == u.id, SetLog.logged_date >= cutoff)
                .order_by(SetLog.logged_date.desc(),
                          SetLog.day_idx.asc(),
                          SetLog.exercise_name.asc(),
                          SetLog.set_number.asc())
                .all())
        # Group by (logged_date, day_idx, week)
        grouped = {}
        for r in rows:
            key = f"{r.logged_date}|wk{r.week}|day_idx={r.day_idx}"
            grouped.setdefault(key, []).append({
                "exercise": r.exercise_name,
                "set": r.set_number,
                "weight": r.weight,
                "reps": r.reps,
                "done": r.done,
            })
        return jsonify({
            "email": email,
            "days_back": days_back,
            "total_sets": len(rows),
            "by_day": grouped,
        })
    except Exception as e:
        import traceback
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-2000:],
        }), 500


@app.route("/api/debug/move-sets-day")
def debug_move_sets_day():
    """Move all SetLog rows for a user matching (logged_date, from_day_idx)
    to to_day_idx. Used to relocate sets logged under one day to another
    when the template layout changed underneath the user.

    Token-gated. Query: ?email=...&date=YYYY-MM-DD&from=4&to=3&token=...
    """
    email = request.args.get("email", "")
    date_str = request.args.get("date", "")
    from_day = int(request.args.get("from", -1))
    to_day = int(request.args.get("to", -1))
    token = request.args.get("token", "")
    if token != "swap-cleanup-2026-04-30":
        return jsonify({"error": "bad token"}), 403
    if not email or not date_str or from_day < 0 or to_day < 0:
        return jsonify({"error": "email + date + from + to required"}), 400
    try:
        from datetime import datetime as _dt
        from models import User, SetLog
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        target_date = _dt.strptime(date_str, "%Y-%m-%d").date()
        rows = SetLog.query.filter_by(
            user_id=u.id, day_idx=from_day, logged_date=target_date,
        ).all()
        moved_summary = [{
            "id": r.id, "exercise_name": r.exercise_name,
            "set_number": r.set_number, "weight": r.weight, "reps": r.reps,
        } for r in rows]
        for r in rows:
            r.day_idx = to_day
        db.session.commit()
        return jsonify({
            "email": email,
            "date": date_str,
            "from_day_idx": from_day,
            "to_day_idx": to_day,
            "moved_count": len(rows),
            "moved": moved_summary,
        })
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-2000:],
        }), 500


@app.route("/api/debug/run-plan")
def debug_run_plan():
    """Show user's stored WeeklyRunPlan rows + what coach_rules will resolve.
    UNAUTH. Diagnostic.
    """
    email = request.args.get("email", "erik@placemetry.com")
    week = int(request.args.get("week", 5))
    try:
        from models import User, WeeklyRunPlan
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        rows = WeeklyRunPlan.query.filter_by(user_id=u.id, week=week).all()
        from coach_rules import _resolve_run_for_day
        resolved = {}
        for d in range(7):
            r = _resolve_run_for_day(week, d, user_id=u.id)
            resolved[d] = {
                "type": r.run_type, "label": r.label, "detail": r.detail,
            } if r else None
        return jsonify({
            "email": email, "week": week,
            "stored_run_plan_rows": [
                {"day_idx": r.day_idx, "run_type": r.run_type,
                 "label": r.label, "duration": r.duration,
                 "source": r.source, "detail": (r.detail or "")[:100]}
                for r in rows
            ],
            "coach_resolves_per_day": resolved,
        })
    except Exception as e:
        import traceback
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-2000:],
        }), 500


@app.route("/api/debug/clear-stale-prescriptions")
def debug_clear_stale_prescriptions():
    """Delete all WeeklyPrescription rows for a user+week so api_workouts
    falls through to the fresh template. Used to recover from program rebuilds
    where stored prescriptions don't match the new template (e.g., Erik's
    week 5 had Push exercises stored on Friday from the old program).

    Token-gated to prevent abuse.
    Query: ?email=...&week=5&token=swap-cleanup-2026-04-30
    """
    email = request.args.get("email", "")
    week = int(request.args.get("week", 0))
    token = request.args.get("token", "")
    if token != "swap-cleanup-2026-04-30":
        return jsonify({"error": "bad token"}), 403
    if not email or not week:
        return jsonify({"error": "email + week required"}), 400
    try:
        from models import User, WeeklyPrescription
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        deleted = WeeklyPrescription.query.filter_by(
            user_id=u.id, week=week,
        ).delete()
        db.session.commit()
        return jsonify({
            "email": email,
            "week": week,
            "deleted_rows": deleted,
            "note": "Template will now drive api_workouts for this week.",
        })
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-2000:],
        }), 500


@app.route("/api/debug/program-friday")
def debug_program_friday():
    """Inspect what the program says for a user's Friday — template, prescription
    override, ExerciseSwap, run dict. UNAUTHENTICATED. Diagnostic only."""
    email = request.args.get("email", "erik@placemetry.com")
    week = int(request.args.get("week", 5))
    day_idx = int(request.args.get("day", 4))  # 4 = Friday
    try:
        from models import User, WeeklyPrescription, ExerciseSwap, AppState
        u = User.query.filter_by(email=email).first()
        if u is None:
            return jsonify({"error": f"user {email!r} not found"}), 404

        from workout_data import get_workouts
        template_days = get_workouts(week)
        template_day = template_days[day_idx] if day_idx < len(template_days) else None

        rxs = (WeeklyPrescription.query
               .filter_by(user_id=u.id, week=week, day_idx=day_idx)
               .all())
        rx_dump = [{
            "exercise_order": r.exercise_order,
            "exercise_name": r.exercise_name,
            "sets": r.sets,
            "reps": r.reps,
            "target_weight": r.target_weight,
        } for r in rxs]

        swaps = (ExerciseSwap.query
                 .filter_by(user_id=u.id, week=week, day_idx=day_idx)
                 .all())
        swap_dump = [{
            "exercise_idx": s.exercise_idx,
            "swapped_to": s.swapped_to,
            "original_name": s.original_name,
        } for s in swaps]

        state = AppState.query.filter_by(user_id=u.id).first()
        state_dump = {
            "start_date": str(state.start_date) if state and state.start_date else None,
            "current_week": state.current_week if state else None,
        }

        return jsonify({
            "email": email,
            "week": week,
            "day_idx": day_idx,
            "template_lift_name": (template_day or {}).get("liftName"),
            "template_run": (template_day or {}).get("run"),
            "template_exercises": [
                {"name": e.get("name"), "sets": e.get("sets")}
                for e in (template_day or {}).get("exercises", [])
            ],
            "weekly_prescription_rows": rx_dump,
            "exercise_swaps": swap_dump,
            "app_state": state_dump,
        })
    except Exception as e:
        import traceback
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-3000:],
        }), 500


@app.route("/api/coach/flag", methods=["POST"])
@login_required
def api_coach_flag():
    """User flags a bad coach response. Stored in CoachFeedback for tuning."""
    data = request.get_json() or {}
    text = (data.get("coach_text") or "").strip()
    category = (data.get("category") or "other").strip()[:40]
    note = (data.get("note") or "").strip()[:1000]
    chat_message_id = data.get("chat_message_id")
    user_message = (data.get("user_message") or "").strip()[:2000]
    if not text:
        return jsonify({"error": "coach_text required"}), 400
    try:
        from models import CoachFeedback
        cf = CoachFeedback(
            user_id=current_user.id,
            chat_message_id=chat_message_id,
            coach_text=text[:5000],
            category=category,
            note=note or None,
            user_message=user_message or None,
        )
        db.session.add(cf)
        db.session.commit()
        return jsonify({"ok": True, "id": cf.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/debug/coach-feedback")
def debug_coach_feedback():
    """Dump recent CoachFeedback rows. UNAUTH diagnostic.
    Query: ?email=...&days=14 (defaults to all users, last 14 days)
    """
    email = request.args.get("email", "")
    days_back = int(request.args.get("days", 14))
    try:
        from datetime import datetime as _dt, timedelta as _td
        from models import User, CoachFeedback
        cutoff = _dt.utcnow() - _td(days=days_back)
        q = CoachFeedback.query.filter(CoachFeedback.created_at >= cutoff)
        if email:
            u = User.query.filter_by(email=email).first()
            if u:
                q = q.filter(CoachFeedback.user_id == u.id)
        rows = q.order_by(CoachFeedback.created_at.desc()).limit(200).all()
        return jsonify({
            "count": len(rows),
            "feedback": [{
                "id": r.id, "user_id": r.user_id,
                "category": r.category, "note": r.note,
                "user_message": r.user_message,
                "coach_text": r.coach_text,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in rows],
        })
    except Exception as e:
        import traceback
        return jsonify({"error_class": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()[-2000:]}), 500


@app.route("/api/debug/coach-error")
def debug_coach_error():
    """Run the new coach pipeline against a user and return the response or
    full traceback on failure. UNAUTHENTICATED — same pattern as /api/debug/health.
    Useful for diagnosing production coach failures from outside the app.

    Query: ?email=erik@placemetry.com&msg=hello
    """
    import traceback
    email = request.args.get("email", "erik@placemetry.com")
    msg = request.args.get("msg", "what should I do right now")
    try:
        from models import User
        user = User.query.filter_by(email=email).first()
        if user is None:
            return jsonify({"error": f"user {email!r} not found"}), 404
        from flask_login import login_user
        login_user(user, force=True)
        from coach_assembler import coach_respond
        reply = coach_respond(
            user_id=user.id,
            agent_name="conversation",
            user_message=msg,
        )
        return jsonify({
            "email": email,
            "msg": msg,
            "reply_len": len(reply or ""),
            "reply_preview": (reply or "")[:1000],
            "reply_full": reply or "",
        })
    except Exception as e:
        return jsonify({
            "error_class": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()[-3000:],
            "email": email,
            "msg": msg,
        }), 500


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


@app.route("/invite/<code>", methods=["GET", "POST"])
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

    # Multi-use invites (no email attached) still go through the old signup form
    recipient_email = (invite.email_sent_to or "").strip().lower()
    if not recipient_email:
        session["invite_code"] = code
        flash("You've been invited! Create your account.", "success")
        return redirect(url_for("login", mode="signup"))

    existing = User.query.filter_by(email=recipient_email).first()

    # Already has a password → just send to login
    if request.method == "GET" and existing and existing.password_hash:
        flash("You already have an account — log in with your password.", "success")
        return redirect(url_for("login"))

    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("_csrf_token"):
            flash("Invalid request. Please try again.", "error")
            return redirect(url_for("accept_invite", code=code))

        password = request.form.get("password", "")
        confirm = request.form.get("password_confirm", "")
        name = (request.form.get("name", "") or "").strip()

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("accept_invite", code=code))
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("accept_invite", code=code))

        if existing:
            # Attach password to pre-existing row (e.g. Google-only account)
            existing.password_hash = generate_password_hash(password)
            if name and not existing.name:
                existing.name = name
            existing.email_verified = True
            user = existing
        else:
            role = _determine_role(recipient_email)
            user = User(
                email=recipient_email,
                name=name or recipient_email.split("@")[0],
                password_hash=generate_password_hash(password),
                role=role,
                email_verified=True,
                invites_remaining=3,
                invited_by=invite.created_by,
            )
            db.session.add(user)

        db.session.commit()

        if not invite.multi_use:
            invite.used_by = user.id
            invite.used_at = datetime.now(timezone.utc)
            db.session.commit()

        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=True)
        return redirect("/")

    is_existing_no_password = bool(existing and not existing.password_hash)
    suggested_name = (existing.name if existing else "") or ""
    return render_template(
        "invite.html",
        invite_code=code,
        email=recipient_email,
        suggested_name=suggested_name,
        is_existing=is_existing_no_password,
    )


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


# ─── Auto cache-busting for static assets ─────────────────────────────────
# Computes a content hash of static files at first access and caches it
# per-process. Templates use `{{ asset_url('app.js') }}` instead of a
# hand-bumped `?v=N` query param — every deploy that changes the file
# also changes the hash, so browsers automatically refetch.
import hashlib as _asset_hashlib
_asset_hash_cache: dict[str, str] = {}


def _static_asset_hash(filename: str) -> str:
    """First 12 chars of sha256 of static/<filename>'s bytes.

    Cached per-process — Render's gunicorn workers have a stable file
    contents for their lifetime, and a fresh deploy creates new
    workers, so we never need to invalidate within a process.
    """
    if filename in _asset_hash_cache:
        return _asset_hash_cache[filename]
    try:
        path = os.path.join(app.static_folder or "static", filename)
        with open(path, "rb") as f:
            h = _asset_hashlib.sha256(f.read()).hexdigest()[:12]
        _asset_hash_cache[filename] = h
        return h
    except Exception:
        # Fallback: empty hash means the URL has no ?v= — browsers
        # will use whatever cached copy they have. Better than 500.
        return ""


@app.context_processor
def _inject_asset_url():
    """Templates can call {{ asset_url('app.js') }} → /static/app.js?v=<hash>."""
    def asset_url(filename: str) -> str:
        h = _static_asset_hash(filename)
        suffix = f"?v={h}" if h else ""
        return f"/static/{filename}{suffix}"
    return {"asset_url": asset_url}


@app.route("/")
@login_required
def index():
    # No-store on the HTML so mobile browsers always pick up the latest
    # `<script src="/static/app.js?v=N">` reference. Without this,
    # Safari caches index.html and keeps fetching the old `?v=` URL
    # even after we bump the version.
    response = make_response(render_template("index.html"))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


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

            # Fast day protein substitution: ONLY when the day's plan actually
            # intends protein (a bulk/recomp fast that allows a shake) — never on
            # a true 0-cal CUT fast, whose note says "no food until you break the
            # fast". Injecting chicken there directly contradicts the header.
            has_caloric_food = any(f["item"] not in always_allowed and f.get("cal", 0) > 0 for f in filtered_foods)
            is_fast_meal = "Fast" in meal.get("name", "") or "fast" in meal.get("name", "")
            _plan_allows_protein = ((mp.get("targetProtein") or 0) > 0
                                    or (mp.get("targetCal") or 0) > 0)
            if is_fast_meal and not has_caloric_food and user_food_ids and _plan_allows_protein:
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

    # Detect bodyweight-only users
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    has_gym = pa.has_gym if pa else True

    all_weeks = {}
    for week in range(1, 13):
        phase = get_phase(week)
        if has_gym:
            days = get_workouts(week)
        else:
            from workout_data import get_workouts_for_user
            days = get_workouts_for_user(week, has_gym=False)

        # Check for user-specific prescriptions
        prescriptions = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=week
        ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()

        # Per-day "does a real plan exist?" sets — drive the fail-loud strip
        # below so the static template never reaches the UI as the user's plan.
        presc_day_set = {rx.day_idx for rx in prescriptions}
        runplan_day_set = set()

        if prescriptions:
            rx_by_day = {}
            for rx in prescriptions:
                if rx.day_idx not in rx_by_day:
                    rx_by_day[rx.day_idx] = []
                ex_dict = {
                    "name": rx.exercise_name,
                    "sets": f"{rx.sets}x{rx.reps}",
                    # Coach-only rest — no hardcoded default, no template-row leak.
                    "rest": rx.rest if rx.source == "coach" else None,
                    "note": rx.note or "",
                }
                # `is not None` (not truthy) so target_weight=0 — the
                # explicit "bodyweight" sentinel — is preserved on the wire.
                # Truthy check would strip 0 and the client's
                # isBodyweightPrescription detection would fail.
                if getattr(rx, 'target_weight', None) is not None:
                    ex_dict["target_weight"] = rx.target_weight
                ex_info = EXERCISES.get(rx.exercise_name, {})
                if ex_info.get("video"):
                    ex_dict["video"] = ex_info["video"]
                rx_by_day[rx.day_idx].append(ex_dict)

            for day_idx, exercises in rx_by_day.items():
                if day_idx < len(days):
                    days[day_idx]["exercises"] = exercises
                    if not days[day_idx].get("isRest"):
                        # Same reconciliation as /api/workouts/<week> so the two
                        # endpoints never disagree on a day's title (keep an
                        # accurate curated label, fix a wrong-region/omitted one).
                        days[day_idx]["liftName"] = _reconcile_lift_name(
                            days[day_idx].get("liftName"),
                            [e.get("name") for e in exercises])

        for day in days:
            if "exercises" in day:
                day["exercises"] = auto_swap_workout(day["exercises"], user_equipment)
                # Inject per-exercise metadata (tracked_metric, video) from the
                # EXERCISES catalog so the client can branch render — e.g. show
                # an "in" input for plyometric height-tracked lifts (Box Jump)
                # instead of the default "lb" weight input.
                for _ex in day["exercises"]:
                    _info = EXERCISES.get(_ex.get("name", ""), {})
                    if _info.get("tracked_metric") and not _ex.get("tracked_metric"):
                        _ex["tracked_metric"] = _info["tracked_metric"]

        # Apply user-explicit ExerciseSwap rows AFTER auto_swap_workout so a
        # manual swap overrides the equipment-driven substitution. Recompute
        # target_weight, note, and catalog metadata against the SWAP TARGET's
        # actual history rather than letting the slot's original prescription
        # leak through (which produced 175-lb DB RDL from a Conv DL slot).
        try:
            from equipment_swaps import EXERCISE_SWAPS
            _swap_rows = ExerciseSwap.query.filter_by(
                user_id=current_user.id, week=week
            ).all()
            _swap_map = {(s.day_idx, s.exercise_idx): (s.swapped_to, s.original_name)
                         for s in _swap_rows}
            for _day_idx, _day in enumerate(days):
                for _ex_idx, _ex in enumerate(_day.get("exercises", []) or []):
                    _key = (_day_idx, _ex_idx)
                    if _key not in _swap_map:
                        continue
                    _swap_target, _orig_recorded = _swap_map[_key]
                    _orig_displayed = _ex.get("name", "")
                    _ex["swapped_from"] = _orig_displayed
                    _ex["name"] = _swap_target
                    # Recompute target_weight via engine using the swap target's
                    # SetLog history, not the original slot's prescription value.
                    try:
                        _t = compute_next_targets(
                            current_user.id, _swap_target, week, _day_idx,
                            exercise_order=_ex_idx,
                        )
                        if _t and _t.get("target_weight"):
                            _ex["target_weight"] = _t["target_weight"]
                        else:
                            _ex.pop("target_weight", None)
                    except Exception:
                        _ex.pop("target_weight", None)
                    # Pull note from the original's catalog alternative entry.
                    # If the swap was recorded against a different "original"
                    # (e.g. earlier auto-swap renamed the slot), fall back to
                    # the displayed original or the catalog's own note.
                    _alt_note = None
                    for _candidate in (_orig_recorded, _orig_displayed):
                        if not _candidate:
                            continue
                        _entry = EXERCISE_SWAPS.get(_candidate) or {}
                        for _alt in _entry.get("alternatives", []) or []:
                            if _alt.get("name") == _swap_target:
                                _alt_note = _alt.get("note")
                                break
                        if _alt_note:
                            break
                    if _alt_note:
                        _ex["note"] = _alt_note
                    else:
                        _ex["note"] = ""
                    # Refresh tracked_metric for the swap target.
                    _info = EXERCISES.get(_swap_target, {})
                    if _info.get("tracked_metric"):
                        _ex["tracked_metric"] = _info["tracked_metric"]
                    elif _ex.get("tracked_metric"):
                        del _ex["tracked_metric"]
        except Exception:
            pass

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
                runplan_day_set = {rp.day_idx for rp in run_plans}
                for rp in run_plans:
                    if rp.day_idx < len(days):
                        days[rp.day_idx]["run"] = {"type": rp.run_type, "label": rp.label, "time": rp.duration, "detail": rp.detail or ""}
        except Exception:
            pass

        # LOGGED-RUN overlay: a day the athlete already RAN but has no plan row
        # should show their logged run — not a red "not planned" flag.
        try:
            from models import RunLog
            for rl in RunLog.query.filter_by(user_id=current_user.id, week=week).all():
                di = rl.day_idx
                if di is None or di >= len(days) or di in runplan_day_set:
                    continue
                if not (rl.duration_min or rl.distance_miles):
                    continue
                _t = (f"{rl.duration_min} min" if rl.duration_min
                      else f"{rl.distance_miles} mi")
                # Preserve the workout TYPE the athlete actually followed (from
                # the template that was displayed at the time); just relabel the
                # duration to what they logged. Their HIIT/intervals/etc. keep
                # their name in history.
                _tmpl = days[di].get("run") or {}
                _bits = []
                if rl.distance_miles: _bits.append(f"{rl.distance_miles} mi")
                if rl.duration_min: _bits.append(f"{rl.duration_min} min")
                if rl.avg_hr: _bits.append(f"avg HR {rl.avg_hr}")
                if rl.elevation_ft: _bits.append(f"{rl.elevation_ft} ft")
                days[di]["run"] = {
                    # Keep the label of the session, but type 'logged' (no
                    # interval/HIIT-timer button on a finished run) and show what
                    # was ACTUALLY run — never the template interval structure,
                    # which no longer matches the logged total.
                    "type": "logged",
                    "label": _tmpl.get("label", "Run"),
                    "time": _t,
                    "detail": ("Logged: " + " · ".join(_bits)) if _bits else "Logged.",
                    "logged": True,
                }
                runplan_day_set.add(di)
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

        # FINAL day-title reconciliation — AFTER the schedule overlay (which
        # carries a stale label) so the title shown on the dashboard/detail
        # matches the day's actual movements. Mirrors api_week; without it the
        # two endpoints disagree (api_workouts kept "Shoulder/Arms" on a back
        # day while /api/workouts/<week> already showed "Back & Biceps").
        for _d in days:
            if not _d.get("isRest") and _d.get("exercises"):
                _d["liftName"] = _reconcile_lift_name(
                    _d.get("liftName"), [e.get("name") for e in _d["exercises"]])

        # FAIL LOUD: strip any leftover template content for domains with no
        # real coach/engine plan so the static skeleton never reaches the UI as
        # the user's plan. Meals deferred (food-selection filtering owns them).
        from plan_overlay import finalize_day_plan
        for _di, _day in enumerate(days):
            finalize_day_plan(
                _day,
                has_prescriptions=(_di in presc_day_set),
                has_runplan=(_di in runplan_day_set),
                has_mealplan=True,
            )

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
    response = jsonify(all_weeks)
    # Force fresh — iOS PWA + Cloudflare have layered caches that have
    # been serving stale workout data after server-side template/prescription
    # changes. Hard refresh wasn't enough.
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


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

    # Detect bodyweight-only users
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    has_gym = pa.has_gym if pa else True
    if has_gym:
        days = get_workouts(week)
    else:
        from workout_data import get_workouts_for_user
        days = get_workouts_for_user(week, has_gym=False)

    # Check for user-specific prescriptions
    prescriptions = WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=week
    ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()

    presc_day_set = {rx.day_idx for rx in prescriptions}
    runplan_day_set = set()

    if prescriptions:
        rx_by_day = {}
        for rx in prescriptions:
            if rx.day_idx not in rx_by_day:
                rx_by_day[rx.day_idx] = []
            ex_dict = {
                "name": rx.exercise_name,
                "sets": f"{rx.sets}x{rx.reps}",
                # Coach-only rest — no hardcoded default, no template-row leak.
                "rest": rx.rest if rx.source == "coach" else None,
                "note": rx.note or "",
            }
            ex_info = EXERCISES.get(rx.exercise_name, {})
            if ex_info.get("video"):
                ex_dict["video"] = ex_info["video"]
            # Inject tracked_metric so height-tracked plyos (Box Jump) render
            # "in" not "lb" here too (the bulk endpoint already does this).
            if ex_info.get("tracked_metric"):
                ex_dict["tracked_metric"] = ex_info["tracked_metric"]
            rx_by_day[rx.day_idx].append(ex_dict)

        for day_idx, exercises in rx_by_day.items():
            if day_idx < len(days):
                days[day_idx]["exercises"] = exercises
                # (Day-title reconciliation runs AFTER the schedule overlay below,
                # which would otherwise overwrite a title set here.)

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
            runplan_day_set = {rp.day_idx for rp in run_plans}
            for rp in run_plans:
                if rp.day_idx < len(days):
                    days[rp.day_idx]["run"] = {"type": rp.run_type, "label": rp.label, "time": rp.duration, "detail": rp.detail or ""}
    except Exception:
        pass

    # LOGGED-RUN overlay (see /api/workouts): show an already-run day's logged
    # run instead of a red "not planned" flag.
    try:
        from models import RunLog
        for rl in RunLog.query.filter_by(user_id=current_user.id, week=week).all():
            di = rl.day_idx
            if di is None or di >= len(days) or di in runplan_day_set:
                continue
            if not (rl.duration_min or rl.distance_miles):
                continue
            _t = (f"{rl.duration_min} min" if rl.duration_min
                  else f"{rl.distance_miles} mi")
            _tmpl = days[di].get("run") or {}
            _bits = []
            if rl.distance_miles: _bits.append(f"{rl.distance_miles} mi")
            if rl.duration_min: _bits.append(f"{rl.duration_min} min")
            if rl.avg_hr: _bits.append(f"avg HR {rl.avg_hr}")
            if rl.elevation_ft: _bits.append(f"{rl.elevation_ft} ft")
            days[di]["run"] = {
                # type 'logged' (no HIIT-timer button on a finished run); show
                # what was actually run, not the template interval structure.
                "type": "logged",
                "label": _tmpl.get("label", "Run"),
                "time": _t,
                "detail": ("Logged: " + " · ".join(_bits)) if _bits else "Logged.",
                "logged": True,
            }
            runplan_day_set.add(di)
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

    # FINAL day-title reconciliation — last word after template + schedule
    # overlays (both carry labels that go stale when the coach redesigns the
    # day). Replaces a title only when it names the wrong region or omits the
    # day's dominant muscle; accurate curated labels are kept.
    for _d in days:
        if not _d.get("isRest") and _d.get("exercises"):
            _d["liftName"] = _reconcile_lift_name(
                _d.get("liftName"), [e.get("name") for e in _d["exercises"]])

    # FAIL LOUD: strip leftover template content for unplanned domains (run +
    # lifts). Mirrors /api/workouts. Meals deferred to food-selection filter.
    from plan_overlay import finalize_day_plan
    for _di, _day in enumerate(days):
        finalize_day_plan(
            _day,
            has_prescriptions=(_di in presc_day_set),
            has_runplan=(_di in runplan_day_set),
            has_mealplan=True,
        )

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
    # Detect user modifications by comparing against the PRESCRIPTION weight
    # (what the user was actually shown), NOT the computed target from the engine.
    # The engine may suggest a higher weight, but the user should only be judged
    # against what they were told to lift.
    try:
        rx = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=week, day_idx=day_idx,
            exercise_name=exercise
        ).first()
        # `is not None` to preserve target_weight=0 (bodyweight prescription)
        # rather than dropping it silently with a truthy check.
        prescribed_weight = rx.target_weight if rx and rx.target_weight is not None else None

        # Also compute progression targets for storage (used by next week's planning)
        targets = compute_next_targets(current_user.id, exercise, week, day_idx)
        if targets.get("target_weight"):
            existing.target_weight = targets["target_weight"]
            existing.target_reps = targets.get("target_reps")

        # Compare against PRESCRIPTION, not computed target
        compare_weight = prescribed_weight or (targets.get("target_weight") if targets else None)
        if compare_weight and weight and compare_weight > 0:
            if weight > compare_weight * 1.02:
                existing.user_modified = True
                existing.modification_direction = 'increased_weight'
            elif weight < compare_weight * 0.98:
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

    # Auto-complete day: if all prescribed exercises have all sets done, mark the day complete.
    if done_provided and done:
        try:
            from workout_data import get_workouts
            phase_workouts = get_workouts(week)
            if day_idx < len(phase_workouts):
                day_exercises = phase_workouts[day_idx].get("exercises", [])
                # Check user prescriptions (override template)
                user_rx = WeeklyPrescription.query.filter_by(
                    user_id=current_user.id, week=week, day_idx=day_idx
                ).all()
                if user_rx:
                    total_sets = sum(rx.sets for rx in user_rx)
                else:
                    total_sets = 0
                    for ex in day_exercises:
                        s = ex.get("sets", 1)
                        if isinstance(s, int):
                            total_sets += s
                        elif isinstance(s, str):
                            m = __import__('re').match(r'(\d+)', str(s))
                            total_sets += int(m.group(1)) if m else 1

                if total_sets > 0:
                    done_count = SetLog.query.filter_by(
                        user_id=current_user.id, week=week, day_idx=day_idx, done=True
                    ).count()
                    if done_count >= total_sets:
                        dc = DayCompletion.query.filter_by(
                            user_id=current_user.id, week=week, day_idx=day_idx
                        ).first()
                        if not dc:
                            db.session.add(DayCompletion(
                                user_id=current_user.id, week=week, day_idx=day_idx, done=True
                            ))
                            db.session.commit()
        except Exception:
            pass  # Don't fail the set save if auto-complete errors

    # Auto-reconcile the prescription UP when a barbell lift is COMPLETED heavier
    # than its plan, so the card never shows "plan 145" next to a logged 155.
    # Gated on done so a typo mid-entry can't ratchet the program. No-op unless
    # barbell + above plan (the helper enforces both).
    if done_provided and done and weight and weight > 0:
        try:
            _reconcile_prescription_to_logged(current_user.id, exercise, weight, week)
        except Exception:
            pass  # never fail the set save on a reconcile error

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
    from workout_data import PHASE_TEMPLATES, BW_PHASE_TEMPLATES, get_phase

    # Don't overwrite existing prescriptions
    existing = WeeklyPrescription.query.filter_by(user_id=current_user.id, week=week).first()
    if existing:
        return jsonify({"message": "Prescriptions already exist for this week", "count": WeeklyPrescription.query.filter_by(user_id=current_user.id, week=week).count()})

    # Use BW templates for no-gym users
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    has_gym = pa.has_gym if pa else True
    phase = get_phase(week)
    if has_gym:
        template = PHASE_TEMPLATES.get(phase, PHASE_TEMPLATES.get(1, {}))
    else:
        template = BW_PHASE_TEMPLATES.get(phase, BW_PHASE_TEMPLATES.get(1, {}))
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


def _enrich_program_with_whys(user_id, target_week, program, run_summary):
    """Generate per-exercise WHY blurbs via strength-coach agent, persist into
    WeeklyPrescription.adjustment_reason, and overwrite program[i]['reason']
    so the client renders them directly. Best-effort: on failure the existing
    reasons stay in place (and the client falls back to the deterministic
    exerciseWhy mapping).
    """
    from coach_planning_why import generate_week_whys

    # Skip the LLM call entirely when every row already has a long-form
    # coach reason. The engine writes short adjustment_reason strings like
    # "Strength phase — +5.0 lb"; the coach-agent ones are typically >40
    # chars and contain context words. If every program row already has a
    # reason >= 40 chars (likely agent-generated), just return what's stored.
    if program and all(
        ex.get("reason") and len(str(ex.get("reason"))) >= 40
        for ex in program
    ):
        # Sync the program list with the stored reasons (already happens via
        # SQL on the row read, but be explicit so the client sees it).
        for ex in program:
            ex["why"] = ex.get("reason")
        return
    # Build user_context
    try:
        goal = TrainingGoal.query.filter_by(user_id=user_id).first()
        bw = (BodyWeight.query.filter_by(user_id=user_id)
              .order_by(BodyWeight.log_date.desc()).first())
        from workout_data import get_phase
        phase = get_phase(target_week)
        user_context = {
            "phase": phase,
            "deload": target_week in (4, 8, 12),
            "goal_type": goal.goal_type if goal and goal.goal_type else "recomp",
            "current_weight": bw.weight_lbs if bw else None,
            "target_weight": goal.target_weight if goal else None,
            "weeks_remaining": max(0, 12 - target_week + 1),
        }
    except Exception:
        user_context = {"phase": "?", "deload": False, "goal_type": "recomp"}

    # Enrich each program entry with prev_weight and is_bw before sending
    def _last_session_weight(exercise_name):
        s = (SetLog.query.filter_by(
                user_id=user_id, exercise_name=exercise_name,
            ).filter(SetLog.weight > 0)
            .order_by(SetLog.logged_date.desc(), SetLog.set_number.desc())
            .first())
        return s.weight if s else None

    from workout_data import EXERCISES, resolve_name
    enriched = []
    for ex in program:
        info = EXERCISES.get(resolve_name(ex.get("exercise", ""))) or {}
        enriched.append({
            **ex,
            "tracked_metric": ex.get("tracked_metric") or info.get("tracked_metric"),
            "muscle_group": ex.get("muscle_group") or info.get("muscle_group"),
            "category": ex.get("category") or info.get("category"),
            "prev_weight": _last_session_weight(ex.get("exercise", "")),
            "is_bw": info.get("category") == "bodyweight" or info.get("tracked_metric") == "bodyweight",
        })

    whys = generate_week_whys(
        user_id=user_id, week=target_week,
        program=enriched, user_context=user_context,
        run_summary=run_summary,
    )
    if not whys:
        return  # LLM failed; leave existing reasons alone

    # Persist into WeeklyPrescription.adjustment_reason and write back to program
    for ex in program:
        key = (ex.get("day"), ex.get("exercise"))
        why = whys.get(key)
        if not why:
            continue
        ex["why"] = why
        # Also update the DB row so subsequent fetches return it
        try:
            WeeklyPrescription.query.filter_by(
                user_id=user_id, week=target_week,
                day_idx=ex.get("day"), exercise_name=ex.get("exercise"),
            ).update({"adjustment_reason": why})
        except Exception:
            pass
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _runs_context_for_week(user_id, target_week):
    """Build the running-coach context (goal, phase, ramped weekly mileage)."""
    goal = TrainingGoal.query.filter_by(user_id=user_id).first()
    bw = (BodyWeight.query.filter_by(user_id=user_id)
          .order_by(BodyWeight.log_date.desc()).first())
    ctx = {
        "phase": get_phase(target_week),
        "deload": target_week in (4, 8, 12),
        "goal_type": goal.goal_type if goal and goal.goal_type else "recomp",
        "current_weight": bw.weight_lbs if bw else None,
        "target_weight": goal.target_weight if goal else None,
        "weeks_remaining": max(0, 12 - target_week + 1),
    }
    peak = max(float(getattr(goal, 'target_weekly_miles', None) or 48), 40)
    if target_week in (4, 8):
        ctx["target_weekly_miles"] = round(peak * 0.62)
    elif target_week == 12:
        ctx["target_weekly_miles"] = round(peak * 0.73)
    elif target_week >= 11:
        ctx["target_weekly_miles"] = round(peak)
    elif target_week >= 9:
        ctx["target_weekly_miles"] = round(peak * 0.94)
    elif target_week >= 5:
        ctx["target_weekly_miles"] = round(38 + (target_week - 5) * 2)
    else:
        ctx["target_weekly_miles"] = round(25 + (target_week - 1) * 3)
    return ctx


def _prev_run_durations(user_id, target_week):
    """Last week's run duration per day AS DISPLAYED — a stored WeeklyRunPlan if
    one exists, ELSE the template run the card falls back to (an unplanned past
    week like week 9 still shows a 30-min VO2 from the template). This mirrors
    how the day card resolves the run, so the delta baseline matches what the
    athlete actually saw last week — not the stale same-week cache ('was 38')
    and not a DB-only lookup that misses the displayed template run."""
    if target_week <= 1:
        return {}
    out = {}
    # 1. Template/get_workouts baseline (what an unplanned week displays).
    try:
        from workout_data import get_workouts, get_workouts_for_user
        pa = PhysicalAssessment.query.filter_by(user_id=user_id).first()
        has_gym = pa.has_gym if pa else True
        tdays = (get_workouts(target_week - 1) if has_gym
                 else get_workouts_for_user(target_week - 1, has_gym=False))
        for di in range(min(7, len(tdays))):
            tr = tdays[di].get("run") if isinstance(tdays[di], dict) else None
            if tr:
                out[di] = tr.get("time") or tr.get("duration")
    except Exception:
        pass
    # 2. A stored prescription overrides the template for that day.
    try:
        for r in WeeklyRunPlan.query.filter_by(
                user_id=user_id, week=target_week - 1).all():
            out[r.day_idx] = r.duration
    except Exception:
        pass
    # 3. A LOGGED run is what the card actually DISPLAYS for a past week (the
    #    card overlays the logged duration onto the label), so it wins — this is
    #    why week 9 shows 30 min (logged) even with a 35-min template.
    try:
        from models import RunLog
        for rl in RunLog.query.filter_by(
                user_id=user_id, week=target_week - 1).all():
            if rl.duration_min:
                out[rl.day_idx] = f"{rl.duration_min} min"
    except Exception:
        pass
    return out


def _fill_missing_week_runs(user_id, target_week):
    """COACH-OR-NOTHING run generation for a week that has no run-plan rows.
    Touches only the run domain — never existing lift prescriptions. Returns
    (run_summary, failures). Days the running coach skips are reported, not
    backfilled with the engine or template.
    """
    from coach_planning_runs import generate_week_runs
    from workout_data import get_workouts, get_workouts_for_user
    pa = PhysicalAssessment.query.filter_by(user_id=user_id).first()
    has_gym = pa.has_gym if pa else True
    tdays = (get_workouts(target_week) if has_gym
             else get_workouts_for_user(target_week, has_gym=False))
    template_runs = []
    for di in range(7):
        tr = tdays[di].get("run") if di < len(tdays) else None
        if tr:
            template_runs.append({
                "day": di, "type": tr.get("type"), "label": tr.get("label"),
                "duration": tr.get("time") or tr.get("duration"),
            })
    if not template_runs:
        return [], []
    try:
        coach_runs = generate_week_runs(
            user_id=user_id, week=target_week,
            template_runs=template_runs,
            user_context=_runs_context_for_week(user_id, target_week),
        ) or {}
    except Exception:
        coach_runs = {}

    run_summary, failures = [], []
    _prev_runs = _prev_run_durations(user_id, target_week)
    for di in range(7):
        if not (tdays[di].get("run") if di < len(tdays) else None):
            continue
        cr = coach_runs.get(di)
        if not cr:
            failures.append({"domain": "run", "day": di})
            continue
        db.session.add(WeeklyRunPlan(
            user_id=user_id, week=target_week, day_idx=di,
            run_type=cr["type"], label=cr["label"], duration=cr["duration"],
            detail=cr.get("detail", ""), source='coach',
            segments_json=json.dumps(cr["segments"]) if cr.get("segments") else None,
        ))
        run_summary.append({
            "day": di, "type": cr["type"], "label": cr["label"],
            "duration": cr["duration"],
            "prev_duration": _prev_runs.get(di),
        })
    db.session.commit()
    return run_summary, failures


# In-process job store for async weekly-program generation. The force_regen
# path runs 30-90s of LLM work; doing it inside the request 502'd at the edge
# timeout before anything was written. We run it in a background thread, keyed
# by (user_id, week), and the client polls /generate-status.
_GEN_JOBS = {}
_GEN_JOBS_LOCK = threading.Lock()
# (user_id, week) -> latest human-readable progress line shown on the loading page
_GEN_PROGRESS = {}


def _gen_progress(user_id, week, msg):
    try:
        _GEN_PROGRESS[(user_id, week)] = msg
    except Exception:
        pass


@app.route("/api/weekly-program/generate-status")
@login_required
def api_weekly_program_generate_status():
    """Poll target for an async force_regen generation. Returns the same payload
    the synchronous endpoint used to return, plus a `status` field."""
    try:
        week = int(request.args.get("week"))
    except (TypeError, ValueError):
        return jsonify({"status": "none"}), 400
    with _GEN_JOBS_LOCK:
        job = _GEN_JOBS.get((current_user.id, week))
    if not job:
        # The in-process job store does NOT survive a worker restart (a deploy
        # mid-generation) or a multi-worker poll mismatch — but the generated
        # program is PERSISTED. Fall back to the source of truth: if the week
        # already has a coach program, serialize and return it as done so a lost
        # job can never hide a finished plan from the athlete (the bug that made
        # a completed week-11 plan "not show up").
        try:
            has_program = WeeklyPrescription.query.filter_by(
                user_id=current_user.id, week=week, source='coach').first()
            if has_program:
                out = dict(_weekly_generation_impl(week, False, None, {}) or {})
                out["status"] = "done"
                out["recovered"] = True
                return jsonify(out)
        except Exception:
            pass
        return jsonify({"status": "none"})
    if job["status"] == "done":
        out = dict(job.get("result") or {})
        out["status"] = "done"
        return jsonify(out)
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job.get("error", "generation failed")})
    return jsonify({"status": "running",
                    "progress": _GEN_PROGRESS.get((current_user.id, week))})


@app.route("/api/weekly-program/generate", methods=["POST"])
@login_required
def api_generate_weekly_program():
    """Generate personalized weekly program using training engine + deficit plan."""
    data = request.get_json() or {}
    target_week = data.get("week", _current_week() + 1)
    force_regen = bool(data.get("force_regen"))
    # Rest-of-week replan: `preserve_through_day` keeps TODAY and every earlier
    # day fully intact (prescriptions, runs, meals, logged work) and regenerates
    # only day_idx > preserve_through. Sending it implies a regen of those
    # future days. Validate to 0-6.
    preserve_through = data.get("preserve_through_day")
    try:
        preserve_through = int(preserve_through) if preserve_through is not None else None
    except (TypeError, ValueError):
        preserve_through = None
    # Convenience: `rest_of_week` lets the client say "replan the rest of this
    # week, leave today + earlier alone" without trusting the client's clock —
    # the server derives today's weekday, but only for the actual current week.
    if data.get("rest_of_week") and preserve_through is None:
        try:
            if target_week == _current_week():
                preserve_through = _user_today().weekday()
        except Exception:
            preserve_through = None
    if preserve_through is not None:
        preserve_through = max(-1, min(6, preserve_through))
        force_regen = True
        # Don't preserve trailing days that have nothing worth keeping (no logged
        # work, no coach plan). Otherwise "plan this week" on an un-started today
        # preserves an EMPTY today and the coach only plans the days after it —
        # leaving today blank (the Monday-runless / no-weights bug). Only ever
        # decrement, so logged work and coach-planned days stay protected.
        if preserve_through >= 0 and target_week == _current_week():
            def _day_has_content(_d):
                _uid = current_user.id
                return bool(
                    SetLog.query.filter_by(user_id=_uid, week=target_week, day_idx=_d, done=True).first()
                    or RunLog.query.filter_by(user_id=_uid, week=target_week, day_idx=_d).first()
                    or WeeklyPrescription.query.filter_by(user_id=_uid, week=target_week, day_idx=_d, source='coach').first()
                    or WeeklyRunPlan.query.filter_by(user_id=_uid, week=target_week, day_idx=_d, source='coach').first()
                )
            while preserve_through >= 0 and not _day_has_content(preserve_through):
                preserve_through -= 1

    # The non-regen path is fast (it only reads existing rows) — run it inline.
    # The force_regen path does 30-90s of LLM work; running THAT synchronously
    # made the request outlive the edge/proxy timeout (~25s) and return 502
    # before writing anything (the bug that left weeks empty). Run it in a
    # background thread and let the client poll /generate-status for the result.
    # Fast path: if this call will only READ existing rows (no force_regen and
    # the week already has a coach program or logged history), run inline — it's
    # a quick DB read. Otherwise the coaches WILL run (30-90s); do that in a
    # background thread so the request returns immediately and never 502s on the
    # edge timeout.
    _fast_read = (not force_regen) and bool(
        WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=target_week, source='coach').first()
        or SetLog.query.filter_by(
            user_id=current_user.id, week=target_week, done=True).first()
    )
    if _fast_read:
        return jsonify(_weekly_generation_impl(target_week, force_regen, preserve_through, data))

    _uid = current_user.id
    _key = (_uid, target_week)
    with _GEN_JOBS_LOCK:
        _job = _GEN_JOBS.get(_key)
        if _job and _job.get("status") == "running":
            return jsonify({"status": "started", "week": target_week})
        _GEN_JOBS[_key] = {"status": "running"}

    def _bg_generate():
        from flask_login import login_user
        from models import User as _User
        try:
            with app.app_context(), app.test_request_context():
                _u = db.session.get(_User, _uid)
                if _u:
                    login_user(_u)
                _res = _weekly_generation_impl(target_week, force_regen, preserve_through, data)
            with _GEN_JOBS_LOCK:
                _GEN_JOBS[_key] = {"status": "done", "result": _res}
        except Exception as _e:
            import logging, traceback
            logging.error("weekly generation failed: %s\n%s", _e, traceback.format_exc())
            with _GEN_JOBS_LOCK:
                _GEN_JOBS[_key] = {"status": "error", "error": str(_e)}

    threading.Thread(target=_bg_generate, daemon=True).start()
    return jsonify({"status": "started", "week": target_week})


@app.route("/api/admin/replan-week", methods=["POST"])
@admin_required
def admin_replan_week():
    """Admin trigger: force a full coach re-plan of a week for a user, no session
    needed. Runs in a background thread (login-impersonated) so it can't time out;
    poll the DB to confirm rows land. Default preserve_through_day=-1 replans the
    whole week (every day, including today)."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    week = data.get("week")
    if not email or week is None:
        return jsonify({"error": "email + week required"}), 400
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        return jsonify({"error": f"user {email!r} not found"}), 404
    week = int(week)
    preserve = int(data.get("preserve_through_day", -1))
    uid = user.id
    key = (uid, week)
    with _GEN_JOBS_LOCK:
        _GEN_JOBS[key] = {"status": "running"}

    def _bg():
        from flask_login import login_user
        from models import User as _User
        try:
            with app.app_context(), app.test_request_context():
                _u = db.session.get(_User, uid)
                if _u:
                    login_user(_u)
                _res = _weekly_generation_impl(week, True, preserve, {})
            with _GEN_JOBS_LOCK:
                _GEN_JOBS[key] = {"status": "done", "result": _res}
        except Exception as _e:
            import logging, traceback
            logging.error("admin replan failed: %s\n%s", _e, traceback.format_exc())
            with _GEN_JOBS_LOCK:
                _GEN_JOBS[key] = {"status": "error", "error": str(_e)}

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"ok": True, "started": True, "email": email,
                    "week": week, "preserve_through_day": preserve})


def _weekly_generation_impl(target_week, force_regen, preserve_through, data):
    """Heavy weekly-program generation: exercise + run + meal coaches, then DB
    writes. Runs in the request thread (non-regen) OR a background thread with a
    login context (force_regen). Uses current_user; never touches `request`.
    """
    def _future_only(q, model):
        """Restrict a query to regenerated days when preserving today+earlier."""
        if preserve_through is not None:
            return q.filter(model.day_idx > preserve_through)
        return q

    # Don't overwrite coach-modified prescriptions or past-week training
    # history — BUT still return the existing program so the planning UI can
    # render the day cards. Previously these guards returned only a
    # "message" stub with no `program` field, leaving _planDayBlocks empty
    # in the client and the HTML cards never appeared. Read the existing
    # rows and serialize them.
    #
    # force_regen=true skips the guard. Deletes the existing coach-source
    # rows for this week and runs the full coach pipeline (strength,
    # running, nutrition) fresh. Use when the user explicitly asks to
    # re-plan with the agents.
    if force_regen:
        _future_only(WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=target_week,
        ).filter(WeeklyPrescription.source.in_(('coach', 'engine'))),
            WeeklyPrescription).delete(synchronize_session=False)
        _future_only(WeeklyRunPlan.query.filter_by(
            user_id=current_user.id, week=target_week,
        ).filter(WeeklyRunPlan.source.in_(('coach', 'engine'))),
            WeeklyRunPlan).delete(synchronize_session=False)
        db.session.commit()
        existing_coach = None
        has_history = None
    else:
        existing_coach = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=target_week, source='coach'
        ).first()
        has_history = SetLog.query.filter_by(
            user_id=current_user.id, week=target_week, done=True,
        ).first()
    if existing_coach or has_history:
        rows = WeeklyPrescription.query.filter_by(
            user_id=current_user.id, week=target_week,
        ).order_by(WeeklyPrescription.day_idx, WeeklyPrescription.exercise_order).all()
        # Inject tracked_metric from the EXERCISES catalog so the planning
        # UI can render "in" for height-tracked plyometrics (Box Jump) and
        # the deterministic exerciseWhy() helper can give a plyo-appropriate
        # reason instead of a weight-based one.
        from workout_data import EXERCISES, resolve_name
        # Prior week's PRESCRIPTION, so the planning delta compares plan-to-plan
        # (not plan-vs-logged) — the fix for the phantom "was X" baseline.
        _prev_presc = {(p.day_idx, p.exercise_name): p
                       for p in WeeklyPrescription.query.filter_by(
                           user_id=current_user.id, week=target_week - 1).all()}
        program = []
        for r in rows:
            info = EXERCISES.get(resolve_name(r.exercise_name)) or {}
            _p = _prev_presc.get((r.day_idx, r.exercise_name))
            program.append({
                "day": r.day_idx,
                "exercise": r.exercise_name,
                "sets": r.sets,
                "reps": r.reps,
                "target_weight": r.target_weight,
                "reason": r.adjustment_reason,
                "rest": r.rest,
                "prev_target_weight": (_p.target_weight if _p else None),
                "prev_reps": (_p.reps if _p else None),
                "note": r.note,
                "tracked_metric": info.get("tracked_metric"),
                "muscle_group": info.get("muscle_group"),
                "category": info.get("category"),
            })
        # Pull run plan rows too so the day cards include the run line
        runs = WeeklyRunPlan.query.filter_by(
            user_id=current_user.id, week=target_week,
        ).order_by(WeeklyRunPlan.day_idx).all()
        # FAIL-LOUD GAP FILL: keeping logged lift history must NOT leave runs
        # unplanned. If this week has lift history/coach rows but no run plan
        # (the exact bug behind the leak), generate the runs now via the
        # running coach — coach-or-nothing, without touching the lift rows.
        run_failures = []
        if not runs:
            run_summary, run_failures = _fill_missing_week_runs(
                current_user.id, target_week,
            )
        else:
            _prev_runs = _prev_run_durations(current_user.id, target_week)
            run_summary = [{
                "day": r.day_idx,
                "type": r.run_type,
                "label": r.label,
                "duration": r.duration,
                "prev_duration": _prev_runs.get(r.day_idx),
            } for r in runs]
        _enrich_program_with_whys(
            current_user.id, target_week, program, run_summary,
        )
        # Off-thread: first push of a fresh week is ~14 Garmin HTTP calls and
        # this branch runs on the request thread (hash-skips make reloads cheap).
        def _push_async(uid=current_user.id, wk=target_week):
            try:
                with app.app_context():
                    _garmin_push_week_best_effort(uid, wk)
            except Exception:
                logging.exception("[GARMIN] async push failed")
        threading.Thread(target=_push_async, daemon=True).start()
        return {
            "message": "Existing prescriptions returned (not regenerated)",
            "week": target_week,
            "program": program,
            "run_summary": run_summary,
            "coach_failures": run_failures,
            "regenerated": False,
        }

    # Get the phase template as baseline — use BW templates for no-gym users
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    has_gym = pa.has_gym if pa else True
    if has_gym:
        from workout_data import PHASE_TEMPLATES, get_phase, EXERCISES, resolve_name
        phase = get_phase(target_week)
        template = PHASE_TEMPLATES.get(phase, PHASE_TEMPLATES.get(1, {}))
    else:
        from workout_data import BW_PHASE_TEMPLATES, PHASE_TEMPLATES, get_phase, EXERCISES, resolve_name
        phase = get_phase(target_week)
        template = BW_PHASE_TEMPLATES.get(phase, BW_PHASE_TEMPLATES.get(1, {}))

    # Delete any existing template-sourced prescriptions for this week
    # (future days only when preserving today+earlier).
    _future_only(WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=target_week, source='template'
    ), WeeklyPrescription).delete(synchronize_session=False)
    _future_only(WeeklyPrescription.query.filter_by(
        user_id=current_user.id, week=target_week, source='engine'
    ), WeeklyPrescription).delete(synchronize_session=False)

    program_summary = []
    # FAIL LOUD: domains the coach did not prescribe. No engine/template
    # fallback is written — these are surfaced so the UI can show "not planned".
    coach_failures = []
    # Prior week's PRESCRIPTION for honest plan-vs-plan deltas (not plan-vs-logged).
    _prev_presc = {(p.day_idx, p.exercise_name): p
                   for p in WeeklyPrescription.query.filter_by(
                       user_id=current_user.id, week=target_week - 1).all()}

    # Auto-swap exercises the user doesn't have equipment for
    from equipment_swaps import auto_swap_workout
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    user_equipment = eq.available_equipment if eq else []

    # ─── ALL THREE COACHES IN PARALLEL ───
    # Strength, running, nutritionist run concurrently via ThreadPoolExecutor.
    # Sequential they take ~45-60s combined and hit Render's request timeout.
    # Parallel ~ max(15s) per call. Engine fallbacks if any agent fails.
    _coach_pre_program = []
    for _di in range(7):
        for _ord, _ex in enumerate(auto_swap_workout(
            [{"name": resolve_name(e["exercise"]),
              "sets": e.get("sets"),
              "reps": e.get("reps"),
              "rest": e.get("rest", "60s"),
              "note": e.get("note", "")} for e in template.get(_di, [])],
            user_equipment,
        )):
            _coach_pre_program.append({
                "day": _di, "exercise_order": _ord,
                "exercise": _ex["name"],
                "sets": _ex.get("sets") or 3,
                "reps": _ex.get("reps") or "10",
            })

    _goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    _bw = (BodyWeight.query.filter_by(user_id=current_user.id)
           .order_by(BodyWeight.log_date.desc()).first())
    _common_ctx = {
        "phase": phase,
        "deload": target_week in (4, 8, 12),
        "goal_type": _goal.goal_type if _goal and _goal.goal_type else "recomp",
        "current_weight": _bw.weight_lbs if _bw else None,
        "target_weight": _goal.target_weight if _goal else None,
        "weeks_remaining": max(0, 12 - target_week + 1),
    }

    # Build template_runs for the running coach NOW so we can fire all three
    # in parallel before entering the per-day loop.
    _template_runs_for_coach = []
    try:
        from workout_data import get_workouts, get_workouts_for_user
        _tdays = (get_workouts(target_week) if has_gym
                  else get_workouts_for_user(target_week, has_gym=False))
        for _di in range(7):
            _tr = _tdays[_di].get("run") if _di < len(_tdays) else None
            if _tr:
                _template_runs_for_coach.append({
                    "day": _di,
                    "type": _tr.get("type"),
                    "label": _tr.get("label"),
                    "duration": _tr.get("time") or _tr.get("duration"),
                })
    except Exception:
        pass

    # Workout pattern for nutritionist (heavy_lift/long_run/rest/etc.)
    _workout_pattern_for_nutri = {}
    try:
        _workout_pattern_for_nutri = {d: _get_day_meal_type(current_user.id, target_week, d) for d in range(7)}
    except Exception:
        pass
    _nutri_ctx = dict(_common_ctx)
    _nutri_ctx["tdee"] = None  # filled in if available later
    _nutri_ctx["fasting_protocol"] = _goal.fasting_protocol if _goal else "16_8"

    _runs_ctx = dict(_common_ctx)
    # Target weekly mileage RAMPS through the build, not held flat. 40 is
    # the floor (Phase 2 base). For 12-week race-prep:
    #   P1 (wk 1-4):  ramp 25 → 35
    #   P2 (wk 5-8):  ramp 38 → 45, deload to 30 on wk 8
    #   P3 (wk 9-12): peak 45 → 48, taper to 35 on wk 12
    # Use TrainingGoal.target_weekly_miles when set as the wk-11 PEAK
    # target; ramp around it. Erik's 40-floor complaint: 40 was being
    # used as a flat target instead of a ramp anchor.
    _peak_miles = float(getattr(_goal, 'target_weekly_miles', None) or 48)
    _peak_miles = max(_peak_miles, 40)  # never under 40 for race prep
    if target_week == 8 or target_week == 4:
        _runs_ctx["target_weekly_miles"] = round(_peak_miles * 0.62)  # deload ~30
    elif target_week == 12:
        _runs_ctx["target_weekly_miles"] = round(_peak_miles * 0.73)  # taper ~35
    elif target_week >= 11:
        _runs_ctx["target_weekly_miles"] = round(_peak_miles)         # peak
    elif target_week >= 9:
        _runs_ctx["target_weekly_miles"] = round(_peak_miles * 0.94)  # ~45
    elif target_week >= 5:
        # P2: ramp 38 → 42 (Erik's window now)
        _runs_ctx["target_weekly_miles"] = round(38 + (target_week - 5) * 2)
    else:
        # P1: ramp 25 → 35
        _runs_ctx["target_weekly_miles"] = round(25 + (target_week - 1) * 3)

    # Fire in parallel
    import concurrent.futures as _cf
    from coach_planning_program import generate_week_program as _gen_program
    from coach_planning_runs import generate_week_runs as _gen_runs
    from coach_planning_meals import generate_week_meals as _gen_meals

    # Capture user_id + the Flask app so the worker threads can re-enter
    # the app context (SQLAlchemy queries inside the agent's history-block
    # builders fail with "Working outside of application context"
    # otherwise — same bug class as the SSE coach generator).
    _flask_app = app
    _captured_user_id = current_user.id

    # Option B: the strength coach DESIGNS the whole week (exercise selection,
    # sets, reps, AND loads) from history + equipment + injuries — NO template.
    # Volume target is the sawtooth (deload weeks ~55%); rails (ceiling, rest
    # day, injury, new-movement light-start) are enforced in code inside the
    # coach module.
    _program_ctx = dict(_common_ctx)
    _program_ctx["target_weekly_sets"] = (
        round(81 * 0.55) if target_week in (4, 8, 12) else 81)
    _program_ctx["train_days"] = 6

    def _call_program():
        try:
            with _flask_app.app_context():
                _prog, _notes = _gen_program(
                    user_id=_captured_user_id, week=target_week,
                    user_context=_program_ctx,
                )
                return _prog
        except Exception as _exc:
            import logging
            logging.warning("program-coach call exception: %s", _exc, exc_info=True)
            return {}

    def _call_runs():
        try:
            with _flask_app.app_context():
                return _gen_runs(
                    user_id=_captured_user_id, week=target_week,
                    template_runs=_template_runs_for_coach, user_context=_runs_ctx,
                )
        except Exception as _exc:
            import logging
            logging.warning("running-coach call exception: %s", _exc, exc_info=True)
            return {}

    def _call_meals():
        try:
            with _flask_app.app_context():
                return _gen_meals(
                    user_id=_captured_user_id, week=target_week,
                    workout_pattern=_workout_pattern_for_nutri,
                    user_context=_nutri_ctx,
                )
        except Exception as _exc:
            import logging
            logging.warning("nutritionist call exception: %s", _exc, exc_info=True)
            return {}

    _coach_program = {}
    _coach_runs_parallel = {}
    _nutri_day_overrides_parallel = {}
    _gen_progress(current_user.id, target_week,
                  "Consulting your strength, running & nutrition coaches — "
                  "designing the week from your history and last week's plan…")
    with _cf.ThreadPoolExecutor(max_workers=3) as _ex_pool:
        _f_str = _ex_pool.submit(_call_program)
        _f_run = _ex_pool.submit(_call_runs)
        _f_meal = _ex_pool.submit(_call_meals)
        try:
            _coach_program = _f_str.result(timeout=90) or {}
        except Exception as _e:
            import logging
            logging.warning("program-coach failed: %s", _e)
        try:
            _coach_runs_parallel = _f_run.result(timeout=60) or {}
        except Exception as _e:
            import logging
            logging.warning("running-coach failed: %s", _e)
        try:
            _nutri_day_overrides_parallel = _f_meal.result(timeout=60) or {}
        except Exception as _e:
            import logging
            logging.warning("nutritionist failed: %s", _e)

    _n_lifts = sum(len(v or []) for v in _coach_program.values())
    _n_days = len([d for d in _coach_program if _coach_program.get(d)])
    _gen_progress(current_user.id, target_week,
                  f"Strength coach designed {_n_lifts} lifts across {_n_days} days; "
                  f"runs and meals set — plate-rounding loads and saving your week…")

    for day_idx in range(7):
        if preserve_through is not None and day_idx <= preserve_through:
            continue  # leave today + earlier days untouched
        items = _coach_program.get(day_idx) or []
        if not items:
            # FAIL LOUD: the program coach designed nothing for this day (and
            # there is NO template fallback). Surface it; UI shows "not planned".
            coach_failures.append({"domain": "lift", "day": day_idx})
            continue
        for order, _it in enumerate(items):
            exercise_name = _it["exercise"]
            adjusted_sets = _it.get("sets") or 3
            adjusted_reps = str(_it.get("reps") or "8")
            weight = _it.get("weight")
            reason = _it.get("why") or "Coach-designed"
            # Rest is the coach's — NO hardcoded default. validate_program
            # already guarantees a single committed rest on every kept item;
            # this is the belt-and-suspenders coach-or-nothing guard.
            coach_rest = (_it.get("rest") or "").strip()
            if not coach_rest:
                coach_failures.append({"domain": "lift", "day": day_idx,
                                       "exercise": exercise_name,
                                       "reason": "coach omitted rest"})
                continue
            note = ""
            source = 'coach'

            # REGRESSION GUARD: never below the athlete's recent top set (except
            # deload). Skip brand-new movements — their light start is the point.
            if (weight is not None and weight > 0
                    and not _it.get("new")
                    and target_week not in (4, 8, 12)):
                _top = db.session.query(db.func.max(SetLog.weight)).filter(
                    SetLog.user_id == current_user.id,
                    SetLog.exercise_name == exercise_name,
                    SetLog.weight > 0,
                    SetLog.week >= max(1, target_week - 4),
                ).scalar()
                if _top is not None and weight < _top:
                    # REPLACE the coach's reason — it names the lighter number it
                    # proposed and would contradict the floored weight (the "why
                    # 70 if it says progressing to 65?" bug). Never append a note
                    # that disagrees with the prescription.
                    _proposed = weight
                    weight = float(_top)
                    reason = (f"Held at your top set of {_top:g} lb — no regression "
                              f"(coach proposed {_proposed:g}; raised to your "
                              f"proven max).")

            # Plate-round to an ACHIEVABLE load: barbell = 45 + 10k (ends in 5 —
            # a bench is never 150), everything else nearest 5. Done once here,
            # server-side, so every surface shows the same loadable number.
            _proposed_weight = weight
            if weight and weight > 0:
                weight = _round_to_loadable(exercise_name, weight)

            # HONESTY: the coach wrote `reason` against ITS proposed number and
            # its own "new movement" guess. If the load changed when we made it
            # loadable, or the movement actually has history, the why can now
            # contradict the displayed number (the "+2.5 from 145 but shows 150"
            # / "new movement but you've logged it" class). Reconcile from facts.
            try:
                _recent_top = db.session.query(db.func.max(SetLog.weight)).filter(
                    SetLog.user_id == current_user.id,
                    SetLog.exercise_name == exercise_name,
                    SetLog.weight > 0,
                    SetLog.week >= max(1, target_week - 6),
                ).scalar()
            except Exception:
                _recent_top = None
            _really_new = (_recent_top is None)
            reason = _reconcile_lift_reason(reason, weight, _proposed_weight,
                                            _recent_top, _really_new,
                                            _is_barbell_movement(exercise_name))

            db.session.add(WeeklyPrescription(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                exercise_order=order,
                exercise_name=exercise_name,
                sets=adjusted_sets,
                reps=adjusted_reps,
                rest=coach_rest,
                note=note,
                source=source,
                target_weight=weight,
                progression_indicator=None,
                adjustment_reason=reason,
            ))

            _ex_info = EXERCISES.get(exercise_name) or {}
            _p = _prev_presc.get((day_idx, exercise_name))
            program_summary.append({
                "day": day_idx,
                "exercise": exercise_name,
                "sets": adjusted_sets,
                "reps": adjusted_reps,
                "target_weight": weight,
                "rest": coach_rest,
                "reason": reason,
                "new": bool(_it.get("new")),
                "prev_target_weight": (_p.target_weight if _p else None),
                "prev_reps": (_p.reps if _p else None),
                "tracked_metric": _ex_info.get("tracked_metric"),
                "muscle_group": _ex_info.get("muscle_group"),
                "category": _ex_info.get("category"),
            })

    db.session.commit()

    # Carry forward exercise swaps from the previous week — but only when the slot
    # still holds the same original exercise. Phase boundaries (1→2→3, deload weeks)
    # reshuffle the day's exercise list, so a (day_idx, exercise_idx) that was Lying
    # Leg Curl in week 4 might be Hammer Curl in week 5; carrying the swap blindly
    # produces nonsense pairs.
    try:
        from equipment_swaps import is_valid_swap
        prev_week = target_week - 1
        if prev_week >= 1:
            prev_swaps = ExerciseSwap.query.filter_by(user_id=current_user.id, week=prev_week).all()
            slot_cache = {}
            for ps in prev_swaps:
                existing_swap = ExerciseSwap.query.filter_by(
                    user_id=current_user.id, week=target_week,
                    day_idx=ps.day_idx, exercise_idx=ps.exercise_idx
                ).first()
                if existing_swap:
                    continue
                # Original from prev row, falling back to recomputing from prev plan.
                prev_original = ps.original_name or _exercise_at_slot(
                    current_user.id, prev_week, ps.day_idx, ps.exercise_idx, _cache=slot_cache
                )
                new_original = _exercise_at_slot(
                    current_user.id, target_week, ps.day_idx, ps.exercise_idx, _cache=slot_cache
                )
                if not new_original:
                    continue
                # Only carry the swap when the slot's original hasn't changed AND the
                # swap target is still in that exercise's alternatives list.
                if prev_original and prev_original != new_original:
                    continue
                if not is_valid_swap(new_original, ps.swapped_to):
                    continue
                db.session.add(ExerciseSwap(
                    user_id=current_user.id, week=target_week,
                    day_idx=ps.day_idx, exercise_idx=ps.exercise_idx,
                    swapped_to=ps.swapped_to, original_name=new_original,
                ))
            db.session.commit()
    except Exception:
        db.session.rollback()

    # Also run deficit plan + AUTO-RECALIBRATE calories based on current weight.
    # As the user loses weight, TDEE drops. Recalibrating weekly keeps the deficit
    # on target for the remaining weeks. Without this, the same calorie intake
    # produces a shrinking deficit and the user falls behind pace.
    deficit = None
    try:
        goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
        bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
        if goal and goal.target_weight and bw:
            current_weight = bw.weight_lbs
            target_weight_val = goal.target_weight
            weeks_remaining = max(1, 12 - target_week + 1)
            required_weekly = (current_weight - target_weight_val) / weeks_remaining
            if required_weekly > 0:
                deficit = {
                    "current_weight": current_weight,
                    "target_weight": target_weight_val,
                    "weeks_remaining": weeks_remaining,
                    "required_weekly_loss": round(required_weekly, 1),
                }

            # Weekly calorie recalibration
            try:
                from goal_engine import compute_tdee, compute_targets, compute_day_calories
                pa_rec = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
                height_rec = (pa_rec.height_inches if pa_rec and pa_rec.height_inches else 70)
                intake_rec = PsychIntake.query.filter_by(user_id=current_user.id).first()
                convo_rec = intake_rec.conversation if intake_rec and intake_rec.conversation else []
                age_rec, sex_rec = 30, "male"
                for msg in (convo_rec if isinstance(convo_rec, list) else []):
                    if not isinstance(msg, dict) or msg.get("role") != "user":
                        continue
                    c = msg.get("content", "").lower().split()
                    if any(w in c for w in ["female", "f", "woman"]): sex_rec = "female"
                    import re as _re
                    am = _re.search(r'\b(\d{1,2})\b', msg.get("content", ""))
                    if am and 13 <= int(am.group(1)) <= 80: age_rec = int(am.group(1))

                tdee_rec = compute_tdee(current_weight, height_rec, age_rec, sex_rec)
                new_targets = compute_targets(tdee_rec["tdee"], goal.goal_type or "cut",
                                              current_weight, age=age_rec,
                                              target_weight=target_weight_val, weeks=weeks_remaining)
                old_cal = goal.daily_calories
                old_protein = goal.protein_grams
                goal.daily_calories = new_targets["calories"]
                goal.protein_grams = new_targets["protein"]
                goal.carb_grams = new_targets["carbs"]
                goal.fat_grams = new_targets["fat"]
                # Recompute per-day-type calories
                day_types_cal = ["heavy_lift", "long_run", "moderate", "rest", "deload"]
                cal_by_day = {}
                for dt in day_types_cal:
                    cal_by_day[dt] = compute_day_calories(new_targets["calories"], goal.goal_type or "cut", dt, weight_lbs=current_weight)
                goal.calorie_by_day_type = cal_by_day
                db.session.commit()
                if old_cal != goal.daily_calories:
                    import logging
                    logging.info(f"[RECALIBRATE] User {current_user.id} week {target_week}: {old_cal} -> {goal.daily_calories} cal (weight {current_weight}, {weeks_remaining}wk remain)")
            except Exception as e:
                import logging
                logging.warning(f"[RECALIBRATE] Failed for user {current_user.id}: {e}")
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
            "fast_day": "fast_day",
        }
        day_types = [_get_day_meal_type(current_user.id, target_week, d) for d in range(7)]
        fasting_protocol = goal.fasting_protocol if goal else "16_8"

        # ─── NUTRITIONIST: USE PARALLEL RESULT ───
        # Already fired upstream in the parallel ThreadPoolExecutor block.
        # Reuse those results — no second LLM call here.
        _nutri_day_overrides = _nutri_day_overrides_parallel or {}
        try:
            # Let the nutritionist override day_type when it has a strong reason
            for _di, _v in _nutri_day_overrides.items():
                if _v.get("day_type"):
                    # Map agent's free-form day_type back to system day types.
                    # carb_up/refeed are HIGH-carb (->long_run), recovery is
                    # moderate; unknown defaults to moderate, never silently to
                    # 'rest' (which cut carbs and inverted a carb-up directive).
                    _agent_type = _v["day_type"].lower()
                    _mapped = (
                        "heavy_lift" if "heavy" in _agent_type
                        else "long_run" if any(k in _agent_type for k in ("long", "run", "carb", "refeed"))
                        else "fast_day" if "fast" in _agent_type
                        else "moderate" if any(k in _agent_type for k in ("moderate", "training", "recovery"))
                        else "rest" if "rest" in _agent_type
                        else "moderate"
                    )
                    # fast day only for cut goals; bulk/recomp -> rest instead.
                    if _mapped == "fast_day":
                        _g = (TrainingGoal.query.filter_by(user_id=current_user.id)
                              .order_by(TrainingGoal.id.desc()).first())
                        if _g and _g.goal_type in ("bulk", "recomp"):
                            _mapped = "rest"
                    if 0 <= _di < 7:
                        day_types[_di] = _mapped
        except Exception as _e:
            import logging
            logging.warning("nutritionist failed, engine day_types kept: %s", _e)

        # Delete existing non-coach meal plans for this week (future days only
        # when preserving today+earlier).
        _future_only(WeeklyMealPlan.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyMealPlan.source != 'coach'),
            WeeklyMealPlan).delete(synchronize_session=False)

        for day_idx in range(7):
            if preserve_through is not None and day_idx <= preserve_through:
                continue  # leave today + earlier days untouched
            day_type = day_types[day_idx]

            if day_type == 'fast_day':
                # Use user's selected foods with fast-day calorie target
                if user_foods:
                    cal_day_type = _cal_day_type_map.get(day_type, "rest")
                    day_macros = compute_day_calories(
                        base_calories,
                        goal.goal_type if goal else 'cut',
                        cal_day_type,
                        current_weight,
                    )
                    # Runs are written to the DB AFTER this meal loop (below), so
                    # _day_has_training's DB query would miss a run-only day like
                    # Sunday. Use the in-memory coach output, which is already
                    # computed: a day has training if it has lifts OR a run.
                    _has_tr = bool((_coach_program or {}).get(day_idx)) or \
                        bool((_coach_runs_parallel or {}).get(day_idx))
                    meal_plan = generate_meal_plan(
                        selected_foods=user_foods,
                        day_type='fast_day',
                        targets=day_macros,
                        fasting_protocol=fasting_protocol,
                        has_training=_has_tr,
                    )
                else:
                    meal_plan = MEAL_PLANS.get('fast_day', {})  # fallback only if no selections
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
    _prev_run_dur = _prev_run_durations(current_user.id, target_week)
    try:
        from workout_data import get_workouts as _get_template_workouts
        template_days = _get_template_workouts(target_week)

        # Delete existing engine-sourced run plans for this week (future days
        # only when preserving today+earlier).
        _future_only(WeeklyRunPlan.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyRunPlan.source != 'coach'),
            WeeklyRunPlan).delete(synchronize_session=False)

        # ─── RUNNING COACH: USE PARALLEL RESULT ───
        # Already fired upstream in the ThreadPoolExecutor block. Reuse.
        _coach_runs = _coach_runs_parallel or {}

        for day_idx in range(7):
            if preserve_through is not None and day_idx <= preserve_through:
                continue  # leave today + earlier days untouched
            template_run = template_days[day_idx].get("run") if day_idx < len(template_days) else None
            if not template_run:
                continue

            # COACH-OR-NOTHING: the running coach is the only source. No engine
            # fallback (that fallback + the static template are what leaked the
            # "60-90 min" range). If the coach didn't prescribe this day's run,
            # write nothing and record the gap.
            coach_run = _coach_runs.get(day_idx)
            if not coach_run:
                coach_failures.append({"domain": "run", "day": day_idx})
                continue
            progressed = {
                "type": coach_run["type"],
                "label": coach_run["label"],
                "time": coach_run["duration"],
                "detail": coach_run["detail"],
                "segments": coach_run.get("segments"),
            }

            db.session.add(WeeklyRunPlan(
                user_id=current_user.id,
                week=target_week,
                day_idx=day_idx,
                run_type=progressed.get('type', 'z2'),
                label=progressed.get('label', 'Run'),
                duration=progressed.get('time', '30 min'),
                detail=progressed.get('detail', ''),
                source='coach',
                segments_json=json.dumps(progressed["segments"]) if progressed.get("segments") else None,
            ))

            run_summary.append({
                "day": day_idx,
                "type": progressed.get('type'),
                "label": progressed.get('label'),
                "duration": progressed.get('time'),
                "prev_duration": _prev_run_dur.get(day_idx),
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

        # Delete existing engine-sourced warmups for this week (future days
        # only when preserving today+earlier).
        _future_only(WeeklyWarmup.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyWarmup.source != 'coach'),
            WeeklyWarmup).delete(synchronize_session=False)

        if not template_days:
            template_days = _get_template_workouts(target_week)

        for day_idx in range(7):
            if preserve_through is not None and day_idx <= preserve_through:
                continue  # leave today + earlier days untouched
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
        # Delete existing engine-sourced schedules for this week (future days
        # only when preserving today+earlier).
        _future_only(WeeklyDaySchedule.query.filter_by(
            user_id=current_user.id, week=target_week
        ).filter(WeeklyDaySchedule.source != 'coach'),
            WeeklyDaySchedule).delete(synchronize_session=False)

        if not template_days:
            template_days = _get_template_workouts(target_week)

        for day_idx in range(7):
            if preserve_through is not None and day_idx <= preserve_through:
                continue  # leave today + earlier days untouched
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

    # Calorie recalibration info for the coach
    calorie_change = None
    try:
        if goal and hasattr(goal, 'daily_calories') and 'old_cal' in dir():
            pass  # old_cal set during recalibration above
    except Exception:
        pass
    try:
        calorie_change = {
            "previous_calories": old_cal,
            "new_calories": goal.daily_calories if goal else None,
            "previous_protein": old_protein,
            "new_protein": goal.protein_grams if goal else None,
            "reason": f"Recalibrated from {current_weight}lb with {weeks_remaining} weeks remaining" if deficit else None,
        }
    except Exception:
        calorie_change = None

    # Skip the separate WHY-enrichment Sonnet call in the regen path —
    # the strength coach now writes weight+why together in a single call.
    # Render's 30s edge timeout was being exceeded by the extra ~10s LLM
    # round-trip. WHYs that didn't come from the coach can be backfilled
    # later or render the deterministic fallback on the client.

    _garmin_push_week_best_effort(current_user.id, target_week)
    return {
        "week": target_week,
        "phase": phase,
        "exercises_generated": len(program_summary),
        "program": program_summary,
        "deficit": deficit,
        "calorie_change": calorie_change,
        "meal_summary": meal_summary,
        "run_summary": run_summary,
        "schedule_summary": schedule_summary,
        "coach_failures": coach_failures,
    }


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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500
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
    """Get all exercise swaps for current user, dropping any that no longer match
    the underlying program. Stale rows are deleted to self-heal existing bad data
    written before write-time validation existed."""
    from equipment_swaps import is_valid_swap
    swaps = ExerciseSwap.query.filter_by(user_id=current_user.id).all()
    result = {}
    slot_cache = {}
    stale_rows = []
    for s in swaps:
        current_original = _exercise_at_slot(
            current_user.id, s.week, s.day_idx, s.exercise_idx, _cache=slot_cache
        )
        # Keep when:
        #   - we can't compute the current original (don't lose a swap on transient errors)
        #   - the slot still holds the same original we recorded (or stored is unknown)
        #   - the swap target is still a valid alternative for the current original
        if current_original is None:
            result[f"{s.week}_{s.day_idx}_{s.exercise_idx}"] = s.swapped_to
            continue
        if s.original_name and s.original_name != current_original:
            stale_rows.append(s)
            continue
        if not is_valid_swap(current_original, s.swapped_to):
            stale_rows.append(s)
            continue
        result[f"{s.week}_{s.day_idx}_{s.exercise_idx}"] = s.swapped_to
    if stale_rows:
        try:
            for r in stale_rows:
                db.session.delete(r)
            db.session.commit()
        except Exception:
            db.session.rollback()
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
    # Resolve to canonical name so "Kettlebell Swing" → "KB Swing"
    if swapped_to:
        try:
            from workout_data import resolve_name
            swapped_to = resolve_name(swapped_to)
        except Exception:
            pass

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

    # Validate that the swap target is in the original exercise's alternatives.
    # Catches LLM markers, stale UI state, or anything that bypasses the swap menu.
    from equipment_swaps import is_valid_swap
    original_name = _exercise_at_slot(current_user.id, week, day_idx, exercise_idx)
    if original_name is None:
        return jsonify({"error": f"No exercise at week {week} day {day_idx} idx {exercise_idx}"}), 400
    if not is_valid_swap(original_name, swapped_to):
        return jsonify({
            "error": f"'{swapped_to}' is not a valid swap for '{original_name}'",
            "original": original_name,
        }), 400

    if existing:
        existing.swapped_to = swapped_to
        existing.original_name = original_name
    else:
        existing = ExerciseSwap(
            user_id=current_user.id, week=week, day_idx=day_idx,
            exercise_idx=exercise_idx, swapped_to=swapped_to,
            original_name=original_name,
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
    # Auto-backfill: if PhysicalAssessment has measurements but BodyMeasurement doesn't
    # have a baseline entry, create one from the intake data.
    try:
        pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
        if pa and pa.waist_inches:
            state = AppState.query.filter_by(user_id=current_user.id).first()
            baseline_date = state.start_date if state and state.start_date else (pa.created_at.date() if pa.created_at else _user_today())
            existing = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=baseline_date).first()
            if not existing:
                bm = BodyMeasurement(log_date=baseline_date, user_id=current_user.id)
                if pa.bodyweight_lbs: bm.weight_lbs = pa.bodyweight_lbs
                if pa.waist_inches: bm.waist_inches = pa.waist_inches
                if getattr(pa, 'chest_inches', None): bm.chest = pa.chest_inches
                if getattr(pa, 'hips_inches', None): bm.hips = pa.hips_inches
                if getattr(pa, 'neck_inches', None): bm.neck = pa.neck_inches
                if getattr(pa, 'bicep_inches', None):
                    bm.bicep_left = pa.bicep_inches
                    bm.bicep_right = pa.bicep_inches
                if getattr(pa, 'thigh_inches', None):
                    bm.thigh_left = pa.thigh_inches
                    bm.thigh_right = pa.thigh_inches
                db.session.add(bm)
                db.session.commit()
    except Exception:
        db.session.rollback()

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

    bm = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=d).first()
    if not bm:
        # Check for orphan row (user_id=NULL) — claim it if found
        orphan = BodyMeasurement.query.filter_by(user_id=None, log_date=d).first()
        if orphan:
            orphan.user_id = current_user.id
            bm = orphan
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


# ─── PROGRESS DASHBOARD (comprehensive single-call) ─────────────────────────

@app.route("/api/progress/dashboard")
@login_required
def api_progress_dashboard():
    """Return ALL progress dashboard data in a single call."""
    uid = current_user.id
    current_week = _current_week()
    today = _user_today()

    # ── 1. Body weight series ────────────────────────────────────────────
    bw_entries = BodyWeight.query.filter_by(user_id=uid).order_by(BodyWeight.log_date).all()
    bw_series = []
    for i, e in enumerate(bw_entries):
        window = bw_entries[max(0, i - 6):i + 1]
        avg = sum(w.weight_lbs for w in window) / len(window)
        bw_series.append({
            "date": e.log_date.isoformat(),
            "weight": e.weight_lbs,
            "rolling_avg_7d": round(avg, 1),
        })

    start_weight = bw_entries[0].weight_lbs if bw_entries else None
    current_weight = bw_entries[-1].weight_lbs if bw_entries else None

    goal = TrainingGoal.query.filter_by(user_id=uid).first()
    target_weight = goal.target_weight if goal else None

    # ── 2. Body measurements ─────────────────────────────────────────────
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
        "notes": e.notes,
    } for e in BodyMeasurement.query.filter_by(user_id=uid).order_by(BodyMeasurement.log_date).all()]

    # ── 3. Training stats ────────────────────────────────────────────────
    all_day_completions = DayCompletion.query.filter_by(user_id=uid).all()
    done_days = [d for d in all_day_completions if d.done]
    days_completed = len(done_days)
    days_scheduled = current_week * 6  # 6 workout days per week (Sunday rest)

    # Streak calculations — use (week, day_idx) tuples as sequential day keys
    done_set = {(d.week, d.day_idx) for d in done_days}

    # Build the full schedule of (week, day_idx) pairs up to today
    all_possible = []
    for w in range(1, current_week + 1):
        max_day = 6 if w < current_week else 5  # day_idx 0-5 = Mon-Sat
        for d in range(0, max_day + 1):
            all_possible.append((w, d))

    # Current streak: anchor at the latest DONE day (not the latest scheduled day,
    # which may be today/tomorrow and not yet logged — that would always zero the streak).
    # Then count backwards through consecutive done days.
    current_streak = 0
    latest_done_idx = -1
    for i in range(len(all_possible) - 1, -1, -1):
        if all_possible[i] in done_set:
            latest_done_idx = i
            break
    if latest_done_idx >= 0:
        for i in range(latest_done_idx, -1, -1):
            if all_possible[i] in done_set:
                current_streak += 1
            else:
                break

    # Best streak: scan forward through all possible days
    best_streak = 0
    running = 0
    for wd in all_possible:
        if wd in done_set:
            running += 1
            if running > best_streak:
                best_streak = running
        else:
            running = 0

    # Total completed sets
    sets_logged = SetLog.query.filter_by(user_id=uid, done=True).count()

    # Weekly adherence
    weekly_adherence = []
    for w in range(1, current_week + 1):
        w_done = sum(1 for d in done_days if d.week == w)
        weekly_adherence.append({
            "week": w,
            "days_done": w_done,
            "days_scheduled": 6,
        })

    # PRs for key lifts (max weight from SetLog where done=True)
    key_lift_names = [
        "Barbell Bench Press",
        "Barbell Back Squat",
        "Conventional Deadlift",
        "DB Overhead Press",
        "Barbell Bent-Over Row",
    ]
    prs = {}
    for lift_name in key_lift_names:
        best = (SetLog.query
                .filter_by(user_id=uid, exercise_name=lift_name, done=True)
                .filter(SetLog.weight > 0)
                .order_by(SetLog.weight.desc())
                .first())
        if best:
            prs[lift_name] = {
                "weight": best.weight,
                "reps": best.reps,
                "date": best.logged_date.isoformat() if best.logged_date else None,
                "week": best.week,
            }
        else:
            # Fall back to ExerciseLog if no SetLog entries exist
            best_el = (ExerciseLog.query
                       .filter_by(user_id=uid, exercise_name=lift_name)
                       .filter(ExerciseLog.weight > 0)
                       .order_by(ExerciseLog.weight.desc())
                       .first())
            if best_el:
                prs[lift_name] = {
                    "weight": best_el.weight,
                    "reps": best_el.reps_completed,
                    "date": best_el.logged_date.isoformat() if best_el.logged_date else None,
                    "week": best_el.week,
                }

    # ── 4. Nutrition ─────────────────────────────────────────────────────
    meals_logged = MealLog.query.filter_by(user_id=uid).count()
    target_calories = goal.daily_calories if goal else None
    fasting_protocol = goal.fasting_protocol if goal else None

    # ── 5. Projections ───────────────────────────────────────────────────
    state = _get_state()
    start_date = state.start_date if state and state.start_date else None
    weeks_remaining = max(0, 12 - current_week)

    # Linear plan: straight line from start_weight to target_weight across 12 weeks.
    # This is the "where you need to be" reference line the dashboard draws.
    linear_plan = []
    if start_weight is not None and target_weight is not None:
        for w in range(1, 13):
            frac = (w - 1) / 11.0 if 11 else 0
            linear_plan.append({
                "week": w,
                "planned_weight": round(start_weight + (target_weight - start_weight) * frac, 1),
            })

    # Projected final weight: extrapolate recent trajectory to week 12.
    # Use the most recent ~2 weeks of weigh-ins to estimate current rate —
    # averaging across the whole program is biased by the W1 water-weight drop
    # (glycogen depletion makes the first week always much larger than the
    # sustained rate). Start weight pulls the rate upward, the initial rolling
    # average pulls current weight upward too, so the old formula consistently
    # under-projected loss.
    projected_final_weight = None
    if current_weight is not None and bw_entries and weeks_remaining > 0:
        from datetime import timedelta
        latest_date = bw_entries[-1].log_date
        cutoff = latest_date - timedelta(days=14)
        recent = [e for e in bw_entries if e.log_date >= cutoff]
        if len(recent) >= 2:
            span_days = (recent[-1].log_date - recent[0].log_date).days or 1
            recent_rate_per_day = (recent[0].weight_lbs - recent[-1].weight_lbs) / span_days
            weekly_rate = recent_rate_per_day * 7
            projected_final_weight = round(current_weight - weekly_rate * weeks_remaining, 1)
        elif start_weight is not None and current_week > 0:
            # Fallback for users with too few recent entries: old formula
            weekly_rate = (start_weight - current_weight) / max(current_week, 1)
            projected_final_weight = round(current_weight - weekly_rate * weeks_remaining, 1)

    # On pace: does the projected end state hit the target? This matches the
    # copy shown to the user ("tracking to X by Week 12") — judging pace off the
    # current-week linear-plan milestone disagreed with the projection, so the
    # badge could say ON PACE while the projection landed well above goal.
    on_pace = None
    if projected_final_weight is not None and target_weight is not None:
        tol = 1.5  # lb tolerance so tiny rounding differences don't flip the badge
        if start_weight is not None and target_weight < start_weight:
            on_pace = projected_final_weight <= target_weight + tol  # cut
        else:
            on_pace = projected_final_weight >= target_weight - tol  # bulk

    # Preserve legacy stored projection for any existing consumers.
    weight_projection = goal.weight_projection if goal else None

    # Completed days: exact (week, day_idx) cells for accurate streak-grid placement.
    completed_days = [{"week": d.week, "day_idx": d.day_idx} for d in done_days]

    # ── 5b. Per-exercise weekly e1RM history for the Lift Progression card ──
    # Aggregate SetLog (preferred) else ExerciseLog into {exercise: [{week, weight, reps}, ...]}.
    lifts_data = {}
    all_sets = (SetLog.query
                .filter_by(user_id=uid, done=True)
                .filter(SetLog.weight > 0)
                .order_by(SetLog.week, SetLog.set_number)
                .all())
    for s in all_sets:
        name = s.exercise_name
        lifts_data.setdefault(name, []).append({
            "week": s.week or 1,
            "weight": s.weight,
            "reps_completed": s.reps or 0,
        })
    if not lifts_data:
        ex_logs = (ExerciseLog.query
                   .filter_by(user_id=uid)
                   .filter(ExerciseLog.weight > 0)
                   .order_by(ExerciseLog.week)
                   .all())
        for log in ex_logs:
            name = log.exercise_name
            lifts_data.setdefault(name, []).append({
                "week": log.week or 1,
                "weight": log.weight,
                "reps_completed": log.reps_completed or 0,
            })
    lifts_response = {name: {"history": history} for name, history in lifts_data.items()}

    # ── 6. Psych intake highlights ───────────────────────────────────────
    psych = PsychIntake.query.filter_by(user_id=uid).first()
    psych_highlights = None
    if psych and psych.conversation:
        athlete_idol = None
        body_goal = None
        commitment_text = None
        conv = psych.conversation if isinstance(psych.conversation, list) else []
        for msg in conv:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            lowered = content.lower()
            # Look for common psych intake patterns in assistant messages
            if msg.get("role") == "user":
                # Scan user responses for idol/body goal mentions
                if not athlete_idol and any(kw in lowered for kw in ["look like", "physique like", "body like", "idol", "aspire"]):
                    athlete_idol = content[:200]
                if not body_goal and any(kw in lowered for kw in ["goal", "target", "want to", "dream", "vision"]):
                    body_goal = content[:200]
                if not commitment_text and any(kw in lowered for kw in ["commit", "promise", "swear", "no excuses", "all in", "ready"]):
                    commitment_text = content[:300]
        quote = commitment_text or body_goal or athlete_idol
        # Intentionally do NOT fall back to psych.report. The report is an
        # AI-written profile summary (markdown with ##/# headers) — truncating
        # its first 240 chars produced ugly header-laden text in the "Why you
        # started" quote block. Better to hide the section than show that.
        psych_highlights = {
            "athlete_idol": athlete_idol,
            "body_goal": body_goal,
            "commitment_text": commitment_text,
            "report_summary": psych.report[:500] if psych.report else None,
            "quote": quote,
        }

    # ── Assemble response ────────────────────────────────────────────────
    return jsonify({
        "bodyweight": {
            "series": bw_series,
            "start_weight": start_weight,
            "current_weight": current_weight,
            "target_weight": target_weight,
        },
        "measurements": measurements,
        "training": {
            "days_completed": days_completed,
            "days_scheduled": days_scheduled,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "sets_logged": sets_logged,
            "weekly_adherence": weekly_adherence,
            "completed_days": completed_days,
            "prs": prs,
        },
        "lifts": lifts_response,
        "nutrition": {
            "meals_logged": meals_logged,
            "target_calories": target_calories,
            "fasting_protocol": fasting_protocol,
        },
        "projections": {
            "start_date": start_date.isoformat() if start_date else None,
            "weight_projection": weight_projection,
            "linear_plan": linear_plan,
            "projected_final_weight": projected_final_weight,
            "weeks_remaining": weeks_remaining,
            "current_week": current_week,
            "on_pace": on_pace,
        },
        "psych_highlights": psych_highlights,
    })


# ─── STATS PANEL ENDPOINTS ──────────────────────────────────────────────────

@app.route("/api/stats/projection-inputs")
@login_required
def api_stats_projection_inputs():
    """Return all inputs needed for the interactive projection calculator."""
    try:
        uid = current_user.id
        current_week = _current_week()

        # Body weight series
        bw_entries = BodyWeight.query.filter_by(user_id=uid).order_by(BodyWeight.log_date).all()
        weight_series = []
        for i, e in enumerate(bw_entries):
            window = bw_entries[max(0, i - 6):i + 1]
            avg = sum(w.weight_lbs for w in window) / len(window)
            weight_series.append({
                "date": e.log_date.isoformat(),
                "weight": e.weight_lbs,
                "rolling_avg": round(avg, 1),
            })

        current_weight = bw_entries[-1].weight_lbs if bw_entries else None
        start_weight = bw_entries[0].weight_lbs if bw_entries else None

        # Training goal
        goal = TrainingGoal.query.filter_by(user_id=uid).order_by(TrainingGoal.created_at.desc()).first()

        # Physical assessment
        pa = PhysicalAssessment.query.filter_by(user_id=uid).first()
        height_in = pa.height_inches if pa else None

        # Age/sex from PsychIntake conversation
        sex = "male"
        age = 30
        intake = PsychIntake.query.filter_by(user_id=uid).first()
        if intake and intake.conversation:
            convo = intake.conversation if isinstance(intake.conversation, list) else []
            for msg in convo:
                content = msg.get("content", "").lower().strip()
                if msg.get("role") == "user":
                    # Sex detection
                    content_words = content.split()
                    if any(w in content_words for w in ["male", "m", "man", "guy", "dude"]):
                        sex = "male"
                    elif any(w in content_words for w in ["female", "f", "woman", "girl", "lady"]):
                        sex = "female"
                    # Age detection
                    age_match = re.search(r'\b(\d{1,2})\b', content)
                    if age_match:
                        num = int(age_match.group(1))
                        if 13 <= num <= 80:
                            age = num

        return jsonify({
            "current_weight": current_weight,
            "start_weight": start_weight,
            "target_weight": goal.target_weight if goal else None,
            "height_in": height_in,
            "age": age,
            "sex": sex,
            "tdee": goal.tdee if goal else None,
            "daily_calories": goal.daily_calories if goal else None,
            "goal_type": goal.goal_type if goal else None,
            "fasting_protocol": goal.fasting_protocol if goal else None,
            "activity_multiplier": 1.55,
            "current_week": current_week,
            "weeks_total": 12,
            "weight_series": weight_series,
            "stored_projection": goal.weight_projection if goal else None,
            "phase_plan": goal.phase_plan if goal else None,
        })
    except Exception as e:
        logging.exception("stats/projection-inputs failed")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/stats/body-comp")
@login_required
def api_stats_body_comp():
    """Return body composition data — measurements, height, weight, demographics."""
    try:
        uid = current_user.id

        # Physical assessment for height
        pa = PhysicalAssessment.query.filter_by(user_id=uid).first()
        height_in = pa.height_inches if pa else None

        # Latest body weight
        latest_bw = BodyWeight.query.filter_by(user_id=uid).order_by(BodyWeight.log_date.desc()).first()
        current_weight = latest_bw.weight_lbs if latest_bw else (pa.bodyweight_lbs if pa else None)

        # Age/sex from PsychIntake
        sex = "male"
        age = 30
        intake = PsychIntake.query.filter_by(user_id=uid).first()
        if intake and intake.conversation:
            convo = intake.conversation if isinstance(intake.conversation, list) else []
            for msg in convo:
                content = msg.get("content", "").lower().strip()
                if msg.get("role") == "user":
                    content_words = content.split()
                    if any(w in content_words for w in ["male", "m", "man", "guy", "dude"]):
                        sex = "male"
                    elif any(w in content_words for w in ["female", "f", "woman", "girl", "lady"]):
                        sex = "female"
                    age_match = re.search(r'\b(\d{1,2})\b', content)
                    if age_match:
                        num = int(age_match.group(1))
                        if 13 <= num <= 80:
                            age = num

        # All body measurements
        measurements = [{
            "date": e.log_date.isoformat(),
            "waist": e.waist_inches,
            "neck": e.neck,
            "chest": e.chest,
            "hips": e.hips,
            "bicep_left": e.bicep_left,
            "bicep_right": e.bicep_right,
            "thigh_left": e.thigh_left,
            "thigh_right": e.thigh_right,
        } for e in BodyMeasurement.query.filter_by(user_id=uid).order_by(BodyMeasurement.log_date).all()]

        return jsonify({
            "height_in": height_in,
            "sex": sex,
            "age": age,
            "current_weight": current_weight,
            "measurements": measurements,
        })
    except Exception as e:
        logging.exception("stats/body-comp failed")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/stats/strength")
@login_required
def api_stats_strength():
    """Return strength data — per-exercise weekly e1RM, percentiles, muscle profiles."""
    try:
        from body_stats import compute_1rm_percentile
        uid = current_user.id

        # Demographics
        pa = PhysicalAssessment.query.filter_by(user_id=uid).first()
        latest_bw = BodyWeight.query.filter_by(user_id=uid).order_by(BodyWeight.log_date.desc()).first()
        current_weight = latest_bw.weight_lbs if latest_bw else (pa.bodyweight_lbs if pa else None)

        sex = "male"
        age = 30
        intake = PsychIntake.query.filter_by(user_id=uid).first()
        if intake and intake.conversation:
            convo = intake.conversation if isinstance(intake.conversation, list) else []
            for msg in convo:
                content = msg.get("content", "").lower().strip()
                if msg.get("role") == "user":
                    content_words = content.split()
                    if any(w in content_words for w in ["male", "m", "man", "guy", "dude"]):
                        sex = "male"
                    elif any(w in content_words for w in ["female", "f", "woman", "girl", "lady"]):
                        sex = "female"
                    age_match = re.search(r'\b(\d{1,2})\b', content)
                    if age_match:
                        num = int(age_match.group(1))
                        if 13 <= num <= 80:
                            age = num

        # All completed sets
        all_sets = SetLog.query.filter_by(user_id=uid, done=True).filter(
            SetLog.weight > 0
        ).order_by(SetLog.week, SetLog.set_number).all()

        # Group by exercise, then by week — compute max e1RM per week
        exercise_data = {}
        for s in all_sets:
            name = s.exercise_name
            if name not in exercise_data:
                exercise_data[name] = {}
            reps = min(s.reps or 10, 15)
            e1rm = round(s.weight * (1 + reps / 30))
            wk = s.week or 1
            if wk not in exercise_data[name] or e1rm > exercise_data[name][wk]:
                exercise_data[name][wk] = e1rm

        # Fallback: if an exercise has no SetLog, check ExerciseLog
        if not exercise_data:
            ex_logs = ExerciseLog.query.filter_by(user_id=uid).filter(
                ExerciseLog.weight > 0
            ).order_by(ExerciseLog.week).all()
            for log in ex_logs:
                name = log.exercise_name
                if name not in exercise_data:
                    exercise_data[name] = {}
                reps = min(log.reps_completed or 10, 15)
                e1rm = round(log.weight * (1 + reps / 30))
                wk = log.week or 1
                if wk not in exercise_data[name] or e1rm > exercise_data[name][wk]:
                    exercise_data[name][wk] = e1rm

        # Build per-exercise response with percentiles
        bw = current_weight or 180
        exercises = {}
        for ex_name, weekly_map in exercise_data.items():
            sorted_weeks = sorted(weekly_map.keys())
            weekly_e1rm = [{"week": wk, "e1rm": weekly_map[wk]} for wk in sorted_weeks]
            current_1rm = weekly_map[sorted_weeks[-1]] if sorted_weeks else None

            percentile = None
            rating = None
            relative_strength = None
            if current_1rm:
                try:
                    pct_data = compute_1rm_percentile(current_1rm, bw, ex_name, age, sex)
                    if pct_data:
                        percentile = pct_data.get("percentile")
                        rating = pct_data.get("rating")
                except Exception:
                    pass
                relative_strength = round(current_1rm / bw, 2) if bw else None

            exercises[ex_name] = {
                "weekly_e1rm": weekly_e1rm,
                "current_1rm": current_1rm,
                "percentile": percentile,
                "relative_strength": relative_strength,
                "rating": rating,
            }

        # Muscle group profiles
        profiles = MuscleGroupProfile.query.filter_by(user_id=uid).all()
        muscle_profiles = [{
            "muscle_group": p.muscle_group,
            "strength_score": p.strength_score,
            "relative_strength": p.relative_strength,
        } for p in profiles]

        return jsonify({
            "current_weight": current_weight,
            "age": age,
            "sex": sex,
            "exercises": exercises,
            "muscle_profiles": muscle_profiles,
        })
    except Exception as e:
        logging.exception("stats/strength failed")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/stats/wellness")
@login_required
def api_stats_wellness():
    """Return wellness data — morning check-ins, weekly reports, session compliance."""
    try:
        uid = current_user.id

        # Morning check-ins
        checkins = [{
            "date": ci.log_date.isoformat(),
            "sleep_quality": ci.sleep_quality,
            "stress_level": ci.stress_level,
            "soreness": ci.soreness,
            "mood": ci.mood,
            "motivation": ci.motivation,
            "anxiety": ci.anxiety,
        } for ci in MorningCheckIn.query.filter_by(user_id=uid).order_by(MorningCheckIn.log_date).all()]

        # Weekly reports
        weekly_reports = [{
            "week": wr.week,
            "adherence_pct": wr.adherence_pct,
            "narrative": wr.narrative,
        } for wr in WeeklyReport.query.filter_by(user_id=uid).order_by(WeeklyReport.week).all()]

        # Session compliance from SessionAnalysis
        compliance = [{
            "week": sa.week,
            "day_idx": sa.day_idx,
            "overall_compliance": sa.overall_compliance,
            "muscle_groups_trained": sa.muscle_groups_trained or [],
        } for sa in SessionAnalysis.query.filter_by(user_id=uid).order_by(
            SessionAnalysis.week, SessionAnalysis.day_idx
        ).all()]

        return jsonify({
            "checkins": checkins,
            "weekly_reports": weekly_reports,
            "compliance": compliance,
        })
    except Exception as e:
        logging.exception("stats/wellness failed")
        return jsonify({"error": str(e)[:200]}), 500


# ─── TRAVEL MODE ────────────────────────────────────────────────────────────

@app.route("/api/travel/workout")
@login_required
def api_travel_workout():
    """Get bodyweight workout for a given day."""
    day = request.args.get("day", "Mon")
    # Derive the body part from the REAL lift that day (not the weekday map,
    # which returned the wrong body part Tue/Wed/Thu).
    _days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    workout_type = None
    try:
        from workout_data import get_workouts, get_workouts_for_user, _warmup_type_for_day
        di = _days.index(day) if day in _days else 0
        pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
        has_gym = pa.has_gym if pa else True
        tdays = (get_workouts(_current_week()) if has_gym
                 else get_workouts_for_user(_current_week(), has_gym=False))
        dd = tdays[di] if di < len(tdays) else None
        if dd is not None:
            workout_type = "rest" if (dd.get("isRest") or not dd.get("exercises")) \
                else _warmup_type_for_day(dd)
    except Exception:
        workout_type = None
    if not workout_type:
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
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500

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

    system_prompt = assemble_prompt(_route_info["agent_name"], context)
    messages = _build_messages(user_msg, context.get("chat_history", []), user_timezone=context.get("user_timezone"))
    agent_config = AGENTS.get(_route_info["agent_name"], AGENTS["conversation"])

    # Tool-using coach: model can call get_workout / get_recent_sets / etc.
    # mid-response to look up data instead of guessing. Eliminates the
    # "Monday is Back Squat 160×4×5" hallucination class.
    from coach_with_tools import coach_chat
    response_text = coach_chat(
        user_id=current_user.id,
        system_prompt=system_prompt,
        messages=messages,
        max_tokens=agent_config["max_tokens"],
        agent_name=_route_info["agent_name"],
    )
    # No output gate: Opus 4.8 obeys the done-lift / fast-day rules on its own
    # (verified via /api/admin/debug/coach-dryrun). An earlier keyword gate
    # false-positived on correct answers, so it was removed.

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
    _current_user_obj = current_user._get_current_object()
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
        # SSE generators run AFTER the original request context closes —
        # tools that touch current_user / db.session would otherwise raise
        # `RuntimeError: Working outside of application context`. Re-enter
        # both the app context and a request context with the user logged
        # in so coach_chat_stream's tool loop has live Flask state.
        from flask_login import login_user
        try:
            with _app.app_context(), _app.test_request_context():
                login_user(_current_user_obj, force=True)
                from coach_assembler import assemble_prompt
                from coach import _build_messages
                from coach_agents import AGENTS
                from coach_with_tools import coach_chat_stream
                system_prompt = assemble_prompt(_route_info["agent_name"], context)
                messages = _build_messages(user_msg, context.get("chat_history", []), user_timezone=context.get("user_timezone"))
                _agent_config = AGENTS.get(_route_info["agent_name"], AGENTS["conversation"])

                # Tool-using coach: server-side tool loop, then chunked stream of
                # the final reply. (No output gate — Opus 4.8 obeys the done-lift /
                # fast-day rules on its own; the gate false-positived on correct
                # answers. Streaming live again for responsiveness.)
                for chunk in coach_chat_stream(
                    user_id=_current_user_id,
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=_agent_config["max_tokens"],
                ):
                    full_text += chunk + " "
                    safe_text = (chunk + " ").replace('\n', '\\n')
                    yield f"data: {safe_text}\n\n"

            yield f"data: [DONE]\n\n"
            full_text = full_text.rstrip()
        except GeneratorExit:
            import logging
            logging.warning("Client disconnected mid-stream")
        except Exception as e:
            import logging
            logging.error("Stream error: %s", e)
            # Send error details to client so we can diagnose
            err_msg = str(e)[:200].replace('\n', ' ')
            yield f"data: [ERROR: {err_msg}]\n\n"
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
                 "rest": (rx.rest if rx.source == "coach" else None), "note": rx.note or "",
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
    linked = gc.connected or _garmin_linked(current_user.id)
    return jsonify({"connected": linked, "live": gc.connected, "linked": linked})


@app.route("/api/garmin/today")
@login_required
def garmin_today():
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        if _garmin_linked(current_user.id):
            return jsonify({"error": "Garmin is reconnecting (rate-limited). Your account is still linked — try again shortly.",
                            "linked": True, "reconnecting": True}), 503
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


@app.route("/api/admin/garmin/save-tokens", methods=["POST"])
@admin_required
def admin_garmin_save_tokens():
    """Save Garmin tokens for a user from the local token helper (CLI + admin key).
    Bypasses Garmin's rate-limited web login: tokens are minted locally by
    garmin_token_helper.py and uploaded here. Validates by restoring a session."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    tokens = data.get("tokens")
    if not email or not tokens:
        return jsonify({"error": "email + tokens required"}), 400
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        return jsonify({"error": f"user {email!r} not found"}), 404
    try:
        from garminconnect import Garmin as G
        gc = _get_garmin(user.id)
        gc.api = G()
        gc.api.login(tokenstore=tokens)
        gc._connected = True
        gc._cache = {}
        gc._user_id = user.id
        gc._save_tokens()
        return jsonify({"connected": True, "user_id": user.id})
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
    # Delete the saved token so the account is genuinely unlinked. Connection
    # state is now driven by token presence, so a logout that left the token
    # behind would keep showing "Connected" — this is the real disconnect.
    try:
        GarminTokens.query.filter_by(user_id=uid).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"connected": False})


_garmin_sync_last = {}  # user_id -> epoch seconds of last successful pull


@app.route("/api/garmin/sync-activities", methods=["POST"])
@login_required
def garmin_sync_activities():
    """Pull recent Garmin activities into RunLog. Throttled to 15 min unless
    {"force": true} (the manual Sync Now button)."""
    import garmin_sync
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    now = time.time()
    last = _garmin_sync_last.get(current_user.id, 0)
    if not force and now - last < 900:
        return jsonify({"throttled": True,
                        "seconds_until_next": int(900 - (now - last)),
                        "days_filled": []})
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        if _garmin_linked(current_user.id):
            return jsonify({"error": "Garmin is reconnecting (rate-limited). Your account is still linked — try again shortly.",
                            "linked": True, "reconnecting": True}), 503
        return jsonify({"error": "Not connected to Garmin"}), 401
    try:
        days_back = max(1, min(30, int(data.get("days_back") or 3)))
    except (TypeError, ValueError):
        days_back = 3
    result = garmin_sync.sync_activities(
        gc, current_user.id,
        days_back=days_back,
        today=_user_today())
    if not result.get("error"):
        _garmin_sync_last[current_user.id] = now
    # Wellness snapshot rides the same throttled sync; failures are independent
    # of the activity sync and reported separately.
    try:
        result["wellness"] = garmin_sync.sync_wellness(gc, current_user.id, today=_user_today())
    except Exception:
        logging.exception("[GARMIN] wellness sync failed")
        result["wellness"] = {"wellness_error": "wellness sync crashed (see logs)"}
    return jsonify(result)


@app.route("/api/garmin/push-week", methods=["POST"])
@login_required
def garmin_push_week():
    """Push the given week's planned runs/HIIT to the watch as scheduled workouts."""
    import garmin_sync
    data = request.get_json(silent=True) or {}
    week = int(data.get("week") or _current_week())
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    if not gc.connected:
        if _garmin_linked(current_user.id):
            return jsonify({"error": "Garmin is reconnecting (rate-limited). Your account is still linked — try again shortly.",
                            "linked": True, "reconnecting": True}), 503
        return jsonify({"error": "Not connected to Garmin"}), 401
    result = garmin_sync.push_week(gc, current_user.id, week, today=_user_today())
    return jsonify(result)


@app.route("/api/garmin/sync-status")
@login_required
def garmin_sync_status():
    """Connection + last pull + per-day push status for the settings panel."""
    week = request.args.get("week", type=int) or _current_week()
    gc = _get_garmin()
    if not gc.connected:
        gc.try_restore_tokens(current_user.id)
    linked = gc.connected or _garmin_linked(current_user.id)
    last = _garmin_sync_last.get(current_user.id)
    links = GarminWorkoutLink.query.filter_by(user_id=current_user.id, week=week).all()
    return jsonify({
        "connected": linked,
        "live": gc.connected,
        "linked": linked,
        "last_activity_sync": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
        "week": week,
        "workouts": [{
            "day_idx": l.day_idx,
            "status": l.status,
            "error": l.error,
            "scheduled_date": l.scheduled_date.isoformat() if l.scheduled_date else None,
            "garmin_workout_id": l.garmin_workout_id,
        } for l in sorted(links, key=lambda x: x.day_idx)],
    })



@app.route("/api/garmin/wellness")
@login_required
def garmin_wellness():
    """Stored wellness history (DB only — never triggers a Garmin call)."""
    days = max(1, min(90, request.args.get("days", default=1, type=int) or 1))
    since = _user_today() - timedelta(days=days - 1)
    rows = GarminWellness.query.filter(
        GarminWellness.user_id == current_user.id,
        GarminWellness.date >= since,
    ).order_by(GarminWellness.date.desc()).all()
    return jsonify([{
        "date": r.date.isoformat(),
        "sleep_hours": round(r.sleep_seconds / 3600, 1) if r.sleep_seconds else None,
        "sleep_score": r.sleep_score,
        "hrv": r.hrv_last_night,
        "hrv_weekly_avg": r.hrv_weekly_avg,
        "body_battery": r.body_battery,
        "readiness": r.training_readiness,
        "resting_hr": r.resting_hr,
        "stress": r.stress_overall,
        "vo2max": r.vo2max,
    } for r in rows])


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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500
    return jsonify({"ok": True})


# ─── GOAL COMPUTATION ─────────────────────────────────────────────────────

def _compute_goal_for_user(user, overrides=None):
    """Compute and persist TrainingGoal for a user. Returns result dict or (error, status).

    overrides (all optional): target_weight (float, user manual cap), target_bf (float
    fraction, e.g. 0.15), goal_type ("cut"/"bulk"/"recomp"), aggressive_request (str
    free text — reserved, currently not auto-applied beyond target overrides).

    Safety guardrails always apply on top of overrides: BMI >= 25 forces cut and caps
    target_weight at current; min_healthy_weight floor always enforced.
    """
    from goal_engine import (
        detect_goal, compute_tdee, compute_targets,
        compute_phase_plan, compute_day_calories,
        determine_fasting_protocol, project_weight_curve,
    )
    overrides = overrides or {}

    intake = PsychIntake.query.filter_by(user_id=user.id).first()
    pa = PhysicalAssessment.query.filter_by(user_id=user.id).first()
    existing_goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not intake and not existing_goal:
        return {"error": "Intake and physical assessment required"}, 400
    if not pa and not existing_goal:
        return {"error": "Physical assessment required"}, 400

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
    latest_bw = BodyWeight.query.filter_by(user_id=user.id).order_by(BodyWeight.log_date.desc()).first()
    if latest_bw:
        weight = latest_bw.weight_lbs
    elif pa and pa.bodyweight_lbs:
        weight = pa.bodyweight_lbs
        # Sync to BodyWeight table so it's there for next time
        db.session.add(BodyWeight(log_date=_user_today(), weight_lbs=weight, user_id=user.id))
        db.session.commit()
    elif existing_goal and existing_goal.target_weight:
        # Use a reasonable estimate from existing goal
        weight = existing_goal.target_weight + 30  # rough fallback
    else:
        return {"error": "No weight data found. Complete physical assessment first."}, 400
    height = (pa.height_inches if pa else None) or 70

    # Goal type: override > existing > detect from actor
    override_goal_type = overrides.get("goal_type")
    override_target_bf = overrides.get("target_bf")
    if override_goal_type in ("cut", "bulk", "recomp"):
        goal_type = override_goal_type
        target_bf = override_target_bf if override_target_bf else (existing_goal.target_bf_pct if existing_goal else 0.12)
    elif existing_goal and not actor_answer:
        goal_type = existing_goal.goal_type or "cut"
        target_bf = existing_goal.target_bf_pct or 0.12
    else:
        goal_info = detect_goal(actor_answer)
        goal_type = goal_info["goal_type"]
        # If the user already has this goal type stored with a custom target_bf,
        # preserve it. Otherwise detect_goal's table defaults (e.g. 0.08 male cut)
        # would silently overwrite a user-picked target on every recompute.
        if (existing_goal and existing_goal.goal_type == goal_type
                and existing_goal.target_bf_pct):
            target_bf = existing_goal.target_bf_pct
        else:
            target_bf = goal_info["target_bf"]
    if override_target_bf and 0.05 <= float(override_target_bf) <= 0.40:
        target_bf = float(override_target_bf)

    # *** SAFETY: Minors (under 18) — NO fasting. Healthy-weight minors: no deficit,
    # no cut (recomp at TDEE). Overweight minors: mild deficit only, target 5-lb loss. ***
    is_minor = age < 18
    bmi = (weight / (height * height)) * 703 if height > 0 else 22
    if is_minor:
        if bmi >= 25:
            goal_type = "cut"
            target_bf = 0.22 if sex == "female" else 0.15
        else:
            goal_type = "recomp"
            target_bf = 0.12 if sex == "male" else 0.20

    # *** SAFETY: Weight-based goal override ***
    # A lightweight person should NEVER be on a cut — they need to build, not lose.
    # BMI-based thresholds (rough): underweight < 18.5, normal 18.5-25, overweight >= 25
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

    # *** SAFETY: Overweight lock — BMI >= 25 forces cut, regardless of actor/intake ***
    # An overweight person must never be prescribed a bulk, a recomp, or a weight gain.
    # Minors are exempt (growth > composition; handled by is_minor branch below).
    is_overweight = (bmi >= 25) and not is_minor
    if is_overweight and goal_type in ("bulk", "recomp"):
        goal_type = "cut"
        # Moderate cut target — not extreme. 22% female / 15% male is realistic for
        # a 12-week cut from overweight; the full lean target (16/8) would force an
        # unrealistic deficit.
        lock_bf = 0.22 if sex == "female" else 0.15
        # Don't weaken an already-lean target the user chose. If they were aiming
        # at 10% BF, flipping from recomp→cut shouldn't push them back to 15%.
        if existing_goal and existing_goal.target_bf_pct and 0.05 <= existing_goal.target_bf_pct < lock_bf:
            target_bf = existing_goal.target_bf_pct
        else:
            target_bf = lock_bf

    tdee_info = compute_tdee(weight, height, age, sex)

    # Prefer real navy body fat from tape measurements; fall back to weight-bucket estimate.
    # estimate_body_fat_navy returns PERCENT (e.g., 31.0), not decimal — convert before use.
    est_bf = None
    if pa and pa.waist_inches and pa.neck_inches:
        try:
            from body_stats import estimate_body_fat_navy
            navy_bf_pct = estimate_body_fat_navy(
                pa.waist_inches, pa.neck_inches, height, sex,
                hips=pa.hips_inches,
            )
            if navy_bf_pct and 5.0 <= navy_bf_pct <= 60.0:
                est_bf = navy_bf_pct / 100.0
        except Exception:
            est_bf = None
    if est_bf is None:
        if sex == "male":
            est_bf = 0.12 if weight < 150 else 0.15 if weight < 180 else 0.20 if weight < 220 else 0.25
        else:
            est_bf = 0.20 if weight < 130 else 0.22 if weight < 150 else 0.28 if weight < 180 else 0.33
    lean_mass = weight * (1 - est_bf)
    target_weight = lean_mass / (1 - target_bf)

    # User-supplied target weight override (e.g., "I want to hit 160") —
    # honored within safety bounds below.
    user_target_override = overrides.get("target_weight")
    if user_target_override:
        try:
            target_weight = float(user_target_override)
        except (TypeError, ValueError):
            pass

    # Never target weight loss below healthy minimum. Use BMI 18.5 as the
    # absolute physiological floor — the old lean-mass/0.85 formula could
    # produce a floor ABOVE current weight when BF was underestimated,
    # silently blocking user-specified cuts.
    bmi_18_5_weight = (18.5 * height * height) / 703 if height > 0 else 110
    min_healthy_weight = bmi_18_5_weight
    target_weight = max(target_weight, min_healthy_weight)

    # For healthy-weight minors: target weight should be ABOVE current weight
    # (growth, not loss). Overweight minors are handled by the BMI>=25 floor below.
    if is_minor and bmi < 25:
        target_weight = max(target_weight, weight + 5)

    # For bulk: target above current — BUT only if not overweight AND user didn't
    # specify their own target (respect their choice over the arbitrary +10 floor).
    if goal_type == "bulk" and not is_overweight and not user_target_override:
        target_weight = max(target_weight, weight + 10)

    # *** Overweight floor: minimum 5-lb loss target, any age. ***
    # Applies to adults and overweight minors. Prevents the lean-mass formula (or
    # the minor growth floor) from producing a target at or above current weight
    # for someone with BMI >= 25.
    if bmi >= 25:
        target_weight = min(target_weight, weight - 5)

    _weeks_remaining = max(1, 12 - _current_week() + 1)
    targets = compute_targets(tdee_info["tdee"], goal_type, weight, age=age,
                              target_weight=target_weight, weeks=_weeks_remaining)

    if is_minor:
        if bmi >= 25:
            # Overweight minor: cap deficit at ~250 cal/day (enough for ~5-lb loss
            # over 12 weeks). Prevents aggressive restriction during growth.
            min_cals = tdee_info["tdee"] - 250
            targets["calories"] = max(targets["calories"], min_cals)
        else:
            # Healthy-weight minor: NO deficit — eat at TDEE or above.
            targets["calories"] = max(targets["calories"], tdee_info["tdee"])
        # No fasting for minors
        fasting = {"protocol": "none", "eating_window_hours": 24, "electrolytes": False, "notes": "No fasting for athletes under 18. Eat regular meals throughout the day."}
    else:
        fasting = determine_fasting_protocol(goal_type, targets["calories"])

    phase_plan = compute_phase_plan(goal_type, weight, target_weight, est_bf)
    projection = project_weight_curve(weight, target_weight, tdee_info["tdee"], targets["calories"],
                                     weeks=_weeks_remaining, height_in=height, age=age, sex=sex,
                                     start_week=_current_week())

    # Compute per-day-type calories
    day_types = ["heavy_lift", "long_run", "moderate", "rest", "deload"]
    cal_by_day = {}
    for dt in day_types:
        cal_by_day[dt] = compute_day_calories(targets["calories"], goal_type, dt, weight_lbs=weight)

    # Save to DB
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not goal:
        goal = TrainingGoal(goal_type=goal_type, user_id=user.id)
        db.session.add(goal)
    goal.goal_type = goal_type
    goal.target_weight = round(target_weight, 1)
    goal.target_bf_pct = target_bf
    goal.daily_calories = targets["calories"]
    goal.protein_grams = targets["protein"]
    goal.carb_grams = targets["carbs"]
    goal.fat_grams = targets["fat"]
    goal.tdee = tdee_info["tdee"]
    goal.phase_plan = phase_plan
    goal.calorie_by_day_type = cal_by_day
    goal.fasting_protocol = fasting["protocol"]
    goal.electrolyte_supplementation = fasting["electrolytes"]
    goal.weight_projection = projection
    db.session.commit()

    daily_deficit = tdee_info["tdee"] - targets["calories"]
    weekly_loss = round(daily_deficit * 7 / 3500, 1) if daily_deficit > 0 else 0
    total_loss = round(weight - target_weight, 1)

    return {
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
    }, 200


@app.route("/api/goal/compute", methods=["POST"])
@login_required
def api_goal_compute():
    """Compute training goal from intake + physical data.

    Accepts optional overrides: target_weight, target_bf, goal_type,
    aggressive_request. Safety guardrails (BMI >= 25 → cut, overweight
    ceiling at current weight, min healthy weight floor) always apply.
    """
    data = request.get_json() or {}
    result, status = _compute_goal_for_user(current_user, overrides=data)
    return jsonify(result), status


@app.route("/api/admin/set-goal-target", methods=["POST"])
@admin_required
def api_admin_set_goal_target():
    """Directly set a user's target_weight / goal_type / target_bf. Admin-only.

    Bypasses the compute pipeline. Recomputes macros using the stored TDEE and
    the new target_weight; leaves tdee/phase_plan/projection untouched.
    """
    from goal_engine import compute_targets
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not goal:
        return jsonify({"error": "User has no training goal to update"}), 400

    bw = BodyWeight.query.filter_by(user_id=user.id).order_by(BodyWeight.log_date.desc()).first()
    current_weight = bw.weight_lbs if bw else (goal.target_weight + 10)

    if "target_weight" in data:
        goal.target_weight = float(data["target_weight"])
    if "goal_type" in data and data["goal_type"] in ("cut", "bulk", "recomp"):
        goal.goal_type = data["goal_type"]
    if "target_bf" in data:
        goal.target_bf_pct = float(data["target_bf"])

    # Weeks remaining must come from the TARGET user's program, not the admin's
    # session. _current_week() reads current_user's app_state, which in admin
    # context has no start_date and falls back to 1 — making the deficit plan
    # assume a full 12 weeks even when the user is already mid-program.
    user_state = AppState.query.filter_by(user_id=user.id).first()
    if user_state and user_state.start_date:
        from datetime import date as _date
        user_cw = min(12, max(1, (_date.today() - user_state.start_date).days // 7 + 1))
    else:
        user_cw = user_state.current_week if user_state and user_state.current_week else 1
    weeks_remaining = max(1, 12 - user_cw + 1)

    if goal.tdee and goal.goal_type and current_weight:
        targets = compute_targets(goal.tdee, goal.goal_type, current_weight,
                                  target_weight=goal.target_weight,
                                  weeks=weeks_remaining)
        goal.daily_calories = targets["calories"]
        goal.protein_grams = targets["protein"]
        goal.carb_grams = targets["carbs"]
        goal.fat_grams = targets["fat"]

    db.session.commit()
    return jsonify({
        "ok": True,
        "email": user.email,
        "current_weight": current_weight,
        "target_weight": goal.target_weight,
        "goal_type": goal.goal_type,
        "target_bf_pct": goal.target_bf_pct,
        "calories": goal.daily_calories,
        "protein": goal.protein_grams,
        "carbs": goal.carb_grams,
        "fat": goal.fat_grams,
    })


@app.route("/api/admin/recompute-goal", methods=["POST"])
@admin_required
def api_admin_recompute_goal():
    """Force a full goal recompute for a specific user. Admin-only.

    Useful after a goal-engine bugfix. Accepts email + optional overrides
    (target_weight, target_bf, goal_type).
    """
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404
    result, status = _compute_goal_for_user(user, overrides=data)
    if isinstance(result, dict):
        result = {"email": user.email, **result}
    return jsonify(result), status


@app.route("/api/goal")
@login_required
def api_goal():
    goal = TrainingGoal.query.filter_by(user_id=current_user.id).first()
    if not goal:
        return jsonify({"computed": False})

    tdee = goal.tdee or 0
    daily_deficit = tdee - goal.daily_calories if tdee and goal.daily_calories else 0

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
        "tdee": tdee,
        "daily_deficit": daily_deficit,
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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500
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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500
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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)[:100]}"}), 500
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

    # Use ACTUAL meal plans from DB (generated by meal_generator), not templates
    db_meals = WeeklyMealPlan.query.filter_by(
        user_id=current_user.id, week=week
    ).all()
    if db_meals:
        workouts = []
        for mp in db_meals:
            if mp.meal_data:
                workouts.append({"mealPlan": mp.meal_data})
    else:
        # Fallback to template if no generated meals exist
        workouts = get_workouts(week)
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

    # Update goal — recalc TDEE at new weight
    goal.weight_projection = result["updated_projection"]
    goal.daily_calories = result["new_daily_calories"]
    try:
        new_tdee = compute_tdee(actual_weight, pa.height_inches or 70, age, sex)
        goal.tdee = new_tdee["tdee"]
    except Exception:
        pass
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

    # Bridge ALL intake measurements to BodyMeasurement as baseline.
    # Previously only waist was bridged — chest, bicep, thigh, hips, neck were lost.
    _has_any_measurement = any(data.get(k) for k in ["waist", "chest", "bicep", "thigh", "hips", "neck"])
    if _has_any_measurement:
        d = _user_today()
        bm = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=d).first()
        if not bm:
            bm = BodyMeasurement(log_date=d, user_id=current_user.id)
            db.session.add(bm)
        if data.get("waist"): bm.waist_inches = float(data["waist"])
        if data.get("chest"): bm.chest = float(data["chest"])
        if data.get("bicep"):
            bm.bicep_left = float(data["bicep"])
            bm.bicep_right = float(data["bicep"])
        if data.get("thigh"):
            bm.thigh_left = float(data["thigh"])
            bm.thigh_right = float(data["thigh"])
        if data.get("hips"): bm.hips = float(data["hips"])
        if data.get("neck"): bm.neck = float(data["neck"])
        if data.get("bodyweight"): bm.weight_lbs = float(data["bodyweight"])
    if "pushup_count" in data:
        pa.pushup_count = data["pushup_count"]
    if "pushup_from_knees" in data:
        pa.pushup_from_knees = data["pushup_from_knees"]
    if "plank_seconds" in data:
        pa.plank_seconds = data["plank_seconds"]
    if "squat_count" in data:
        pa.squat_count = data["squat_count"]
    if "burpee_count" in data:
        pa.burpee_count = data["burpee_count"]
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


# ─── BODYWEIGHT RETEST (week 12 only) ──────────────────────────────────────
# Week 6 retest disabled per Erik's request — it was an intrusive blocking
# gate that interrupted the program at the phase 1→2 boundary. The week 12
# retest still fires for the program-wrap delta against PhysicalAssessment
# baseline.
RETEST_WEEKS = (12,)


@app.route("/api/bodyweight-retest/status")
@login_required
def api_bodyweight_retest_status():
    """Tell the client if a retest is due this week and whether it's done."""
    week = _current_week()
    due_week = week if week in RETEST_WEEKS else None
    retests = {r.week_number: r for r in BodyweightRetest.query.filter_by(user_id=current_user.id).all()}
    completed = {w: retests[w].completed for w in retests}
    due_and_pending = bool(due_week and not (retests.get(due_week) and retests[due_week].completed))
    return jsonify({
        "current_week": week,
        "due_week": due_week,
        "due_and_pending": due_and_pending,
        "completed": completed,
    })


@app.route("/api/bodyweight-retest", methods=["POST"])
@login_required
def api_bodyweight_retest_save():
    data = request.get_json() or {}
    week = data.get("week_number") or _current_week()
    if week not in RETEST_WEEKS:
        return jsonify({"error": f"Retest only accepted for weeks {RETEST_WEEKS}, not week {week}"}), 400

    rt = BodyweightRetest.query.filter_by(user_id=current_user.id, week_number=week).first()
    if not rt:
        rt = BodyweightRetest(user_id=current_user.id, week_number=week)
        db.session.add(rt)

    for field in ("squat_count", "pushup_count", "burpee_count", "plank_seconds"):
        if field in data and data[field] is not None:
            setattr(rt, field, int(data[field]))
    if "pushup_from_knees" in data:
        rt.pushup_from_knees = bool(data["pushup_from_knees"])
    if data.get("completed"):
        rt.completed = True
        rt.completed_at = datetime.now(timezone.utc)

    db.session.commit()
    return jsonify({"ok": True, "week_number": week, "completed": rt.completed})


@app.route("/api/bodyweight-retest/deltas")
@login_required
def api_bodyweight_retest_deltas():
    """Return baseline-vs-retest deltas for the athlete dashboard / weekly report."""
    pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
    if not pa:
        return jsonify({"baseline": None, "retests": []})

    baseline = {
        "squat_count": pa.squat_count,
        "pushup_count": pa.pushup_count,
        "pushup_from_knees": pa.pushup_from_knees,
        "burpee_count": pa.burpee_count,
        "plank_seconds": pa.plank_seconds,
    }
    results = []
    for rt in BodyweightRetest.query.filter_by(user_id=current_user.id).order_by(BodyweightRetest.week_number.asc()).all():
        deltas = {}
        for field in ("squat_count", "pushup_count", "burpee_count", "plank_seconds"):
            b = baseline.get(field)
            v = getattr(rt, field)
            if b is not None and v is not None:
                deltas[field] = {"baseline": b, "current": v, "delta": v - b}
        results.append({
            "week_number": rt.week_number,
            "completed": rt.completed,
            "completed_at": rt.completed_at.isoformat() if rt.completed_at else None,
            "pushup_from_knees": rt.pushup_from_knees,
            "deltas": deltas,
        })
    return jsonify({"baseline": baseline, "retests": results})


## User data reset endpoint removed — no data wipes allowed


## Full reset endpoint removed — no nuclear data wipes allowed


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html")


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
    # Optional explicit password (admin sets a known value at the user's
    # request); otherwise generate a random temp one.
    _explicit = (data.get("password") or "").strip()
    if _explicit and len(_explicit) < 6:
        return jsonify({"error": "password too short (min 6)"}), 400
    temp_password = _explicit or secrets.token_urlsafe(10)
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

    # 2. Save to PhysicalAssessment (weight + optional height)
    pa = PhysicalAssessment.query.filter_by(user_id=user.id).first()
    if pa:
        pa.bodyweight_lbs = float(weight)
        if data.get("height"):
            pa.height_inches = float(data["height"])
    height = (pa.height_inches if pa and pa.height_inches else data.get("height")) or 70

    db.session.commit()

    # 3. Recompute goal (create if needed)
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    recomputed = False
    goal_type = data.get("goal_type") or (goal.goal_type if goal else "cut")
    try:
        intake = PsychIntake.query.filter_by(user_id=user.id).first()
        age = intake.age if intake and hasattr(intake, 'age') and intake.age else 30
        sex = (intake.sex if intake and hasattr(intake, 'sex') else 'male') or 'male'
        tdee_info = compute_tdee(float(weight), height, age, sex)
        target_weight = (goal.target_weight if goal else None) or float(weight) - 20
        targets = compute_targets(tdee_info["tdee"], goal_type, float(weight),
                                  target_weight=target_weight, weeks=12)
        if not goal:
            goal = TrainingGoal(user_id=user.id, goal_type=goal_type, target_weight=target_weight)
            db.session.add(goal)
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


@app.route("/api/admin/debug/patch-set", methods=["POST"])
@admin_required
def api_admin_debug_patch_set():
    """Patch a single set_log row by id. Admin-only. For typo fixes."""
    from models import SetLog
    data = request.get_json() or {}
    set_id = data.get("id")
    if not set_id:
        return jsonify({"error": "id required"}), 400
    s = SetLog.query.get(set_id)
    if not s:
        return jsonify({"error": f"set_log id={set_id} not found"}), 404
    before = {"reps": s.reps, "weight": s.weight}
    if "reps" in data:
        s.reps = int(data["reps"])
    if "weight" in data:
        s.weight = float(data["weight"])
    db.session.commit()
    return jsonify({"ok": True, "id": s.id, "before": before,
                    "after": {"reps": s.reps, "weight": s.weight}})


@app.route("/api/admin/debug/regenerate-projection", methods=["POST"])
@admin_required
def api_admin_debug_regenerate_projection():
    """Re-anchor training_goal.weight_projection using a specified starting weight.

    Admin-only. Used when the original projection was anchored on an intermediate
    weigh-in (e.g., post-water-weight) instead of the true Mar 30 baseline.
    """
    from goal_engine import project_weight_curve
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    starting_weight = data.get("starting_weight")
    if not email or starting_weight is None:
        return jsonify({"error": "email and starting_weight required"}), 400
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"user '{email}' not found"}), 404
    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not goal:
        return jsonify({"error": "no training_goal for user"}), 404
    pa = PhysicalAssessment.query.filter_by(user_id=user.id).first()
    height = pa.height_inches if pa and pa.height_inches else 70
    age = pa.age if pa and getattr(pa, "age", None) else 40
    sex = pa.sex if pa and getattr(pa, "sex", None) else "male"
    before = goal.weight_projection
    projection = project_weight_curve(
        starting_weight=float(starting_weight),
        target_weight=goal.target_weight,
        tdee=goal.tdee or 2500,
        daily_calories=goal.daily_calories or 2000,
        weeks=12,
        height_in=height, age=age, sex=sex,
    )
    goal.weight_projection = projection
    db.session.commit()
    return jsonify({
        "ok": True,
        "user_id": user.id,
        "starting_weight": starting_weight,
        "target_weight": goal.target_weight,
        "before": before,
        "after": projection,
    })


@app.route("/api/admin/generate-meals", methods=["POST"])
@admin_required
def api_admin_generate_meals():
    """Generate meal plans for a user. Admin-only."""
    from meal_generator import generate_meal_plan
    from goal_engine import compute_day_calories
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    week = data.get("week", 1)
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404

    goal = TrainingGoal.query.filter_by(user_id=user.id).first()
    if not goal or not goal.daily_calories:
        return jsonify({"error": "No goal computed"}), 400
    fs = UserFoodSelections.query.filter_by(user_id=user.id).first()
    if not fs or not fs.selected_foods:
        return jsonify({"error": "No food selections"}), 400

    from workout_data import get_workouts, get_workouts_for_user
    pa = PhysicalAssessment.query.filter_by(user_id=user.id).first()
    has_gym = pa.has_gym if pa else True
    days = get_workouts(week) if has_gym else get_workouts_for_user(week, has_gym=False)
    fasting_protocol = goal.fasting_protocol or '16_8'
    latest_bw = BodyWeight.query.filter_by(user_id=user.id).order_by(BodyWeight.log_date.desc()).first()
    weight = latest_bw.weight_lbs if latest_bw else 200

    generated = 0
    for day_idx, day_data in enumerate(days):
        # Determine day type — use template mealType first, then infer from run/lift
        template_meal_type = day_data.get('mealType', '')
        from workout_data import DAY_MEAL_TYPES
        day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][day_idx] if day_idx < 7 else 'Mon'
        cal_day_type = template_meal_type or DAY_MEAL_TYPES.get(day_name, 'moderate')
        # Map to calorie computation types
        _cal_map = {"heavy_lift": "heavy", "long_run": "long_run", "moderate": "training", "fast_day": "fast_day", "rest": "rest", "deload": "rest"}
        cal_compute_type = _cal_map.get(cal_day_type, "training")

        try:
            day_macros = compute_day_calories(goal.daily_calories, goal.goal_type or 'cut', cal_compute_type, weight_lbs=weight)
        except Exception:
            day_macros = {"calories": goal.daily_calories, "protein": goal.protein_grams or 200, "carbs": goal.carb_grams or 150, "fat": goal.fat_grams or 60}

        # Check for fast day — override first, then template mealType
        day_meal_type = 'standard'
        try:
            override = MealPlanOverride.query.filter_by(user_id=user.id, week=week, day_idx=day_idx).first()
            if override and override.meal_type:
                day_meal_type = override.meal_type
        except Exception:
            pass
        if day_meal_type == 'standard':
            # Check template (Sunday = fast_day)
            template_meal_type = day_data.get('mealType', '')
            if template_meal_type == 'fast_day':
                # Fast day only for cut goals; bulk/recomp get rest instead.
                if (goal.goal_type or 'cut') in ('bulk', 'recomp'):
                    day_meal_type = 'rest'
                    cal_day_type = 'rest'
                else:
                    day_meal_type = 'fast_day'
                    cal_day_type = 'rest'

        # Force-zero macros when fast_day is active (override OR template). The
        # earlier flow computed day_macros from the lift/run-derived day type
        # BEFORE checking overrides — so a Wed override to fast_day kept the
        # heavy_lift 1512 cal target and the saved row showed daily_calories=1512
        # even though the meal plan itself was 'Fasting (water + coffee).'
        if day_meal_type == 'fast_day':
            day_macros = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}

        try:
            meal_plan = generate_meal_plan(
                selected_foods=fs.selected_foods,
                day_type=day_meal_type if day_meal_type != 'standard' else cal_day_type,
                targets=day_macros,
                fasting_protocol=fasting_protocol,
                has_training=_day_has_training(user.id, week, day_idx),
            )
        except Exception as e:
            continue

        # Don't overwrite days the athlete has already logged meals for.
        # Mirror the protection in /api/meals/regenerate so admin tools can't
        # silently rewrite history either.
        from datetime import timedelta as _timedelta, date as _date
        from models import AppState as _AppState
        _state = _AppState.query.filter_by(user_id=user.id).first()
        if _state and _state.start_date:
            _day_date = _state.start_date + _timedelta(days=(week - 1) * 7 + day_idx)
            _mlog = MealLog.query.filter_by(user_id=user.id, log_date=_day_date).first()
            if _mlog and (_mlog.eaten or []):
                continue

        # Save
        save_day_type = day_meal_type if day_meal_type != 'standard' else cal_day_type
        existing = WeeklyMealPlan.query.filter_by(user_id=user.id, week=week, day_idx=day_idx).first()
        if existing:
            existing.meal_data = meal_plan
            existing.day_type = save_day_type
            existing.daily_calories = meal_plan.get('targetCal', 0)
            existing.daily_protein = meal_plan.get('targetProtein', 0)
        else:
            db.session.add(WeeklyMealPlan(user_id=user.id, week=week, day_idx=day_idx, meal_data=meal_plan))
        generated += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)[:200]}), 500

    return jsonify({"ok": True, "email": email, "week": week, "days_generated": generated})


@app.route("/api/admin/save-measurements", methods=["POST"])
@admin_required
def api_admin_save_measurements():
    """Save measurements for a user by email. Admin-only."""
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({"error": f"User '{email}' not found"}), 404
    d = date.fromisoformat(data.get("date", _user_today().isoformat()))
    bm = BodyMeasurement.query.filter_by(user_id=user.id, log_date=d).first()
    if not bm:
        # Check for orphan row (user_id=NULL) for this date — claim it
        orphan = BodyMeasurement.query.filter_by(user_id=None, log_date=d).first()
        if orphan:
            orphan.user_id = user.id
            bm = orphan
        else:
            bm = BodyMeasurement(log_date=d, user_id=user.id)
            db.session.add(bm)
    if data.get("weight"): bm.weight_lbs = float(data["weight"])
    if data.get("waist"): bm.waist_inches = float(data["waist"])
    if data.get("chest"): bm.chest = float(data["chest"])
    if data.get("hips"): bm.hips = float(data["hips"])
    if data.get("neck"): bm.neck = float(data["neck"])
    if data.get("bicep_left"): bm.bicep_left = float(data["bicep_left"])
    if data.get("bicep_right"): bm.bicep_right = float(data["bicep_right"])
    if data.get("thigh_left"): bm.thigh_left = float(data["thigh_left"])
    if data.get("thigh_right"): bm.thigh_right = float(data["thigh_right"])
    try:
        db.session.commit()
        return jsonify({"ok": True, "date": d.isoformat(), "user": email})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/admin/dashboard")
@admin_required
def api_admin_dashboard_data():
    """All-users overview for admin monitoring. Returns onboarding status,
    activity, and key metrics for every user."""
    users = User.query.order_by(User.created_at).all()
    result = []
    for u in users:
        if u.role == 'admin' and u.email != 'erik@placemetry.com':
            continue  # skip test admins

        # Onboarding state
        state = AppState.query.filter_by(user_id=u.id).first()
        intake = PsychIntake.query.filter_by(user_id=u.id).first()
        pa = PhysicalAssessment.query.filter_by(user_id=u.id).first()
        goal = TrainingGoal.query.filter_by(user_id=u.id).first()
        from models import UserFoodSelections, UserEquipment, UserConstraints
        food = UserFoodSelections.query.filter_by(user_id=u.id).first()
        eq = UserEquipment.query.filter_by(user_id=u.id).first()
        con = UserConstraints.query.filter_by(user_id=u.id).first()

        # Activity
        last_chat = ChatMessage.query.filter_by(user_id=u.id, role='user').order_by(ChatMessage.created_at.desc()).first()
        last_checkin = MorningCheckIn.query.filter_by(user_id=u.id).order_by(MorningCheckIn.log_date.desc()).first()
        last_weight = BodyWeight.query.filter_by(user_id=u.id).order_by(BodyWeight.log_date.desc()).first()

        # Workout completion
        days_done = DayCompletion.query.filter_by(user_id=u.id, done=True).count()
        sets_logged = SetLog.query.filter_by(user_id=u.id, done=True).count()

        # Onboarding progress (0-7 steps)
        steps_done = sum([
            bool(intake and intake.completed),
            bool(con and con.completed),
            bool(pa and pa.completed),
            bool(eq and eq.completed),
            bool(goal),
            bool(food and food.completed),
            bool(goal and goal.plan_accepted),
        ])

        result.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "created": str(u.created_at)[:10] if u.created_at else None,
            "timezone": u.timezone,
            "onboarding": {
                "steps_done": steps_done,
                "steps_total": 7,
                "complete": steps_done == 7,
                "intake": bool(intake and intake.completed),
                "constraints": bool(con and con.completed),
                "physical": bool(pa and pa.completed),
                "equipment": bool(eq and eq.completed),
                "goal": bool(goal),
                "food": bool(food and food.completed),
                "plan_accepted": bool(goal and goal.plan_accepted),
            },
            "program": {
                "week": state.current_week if state else None,
                "start_date": str(state.start_date) if state and state.start_date else None,
                "goal_type": goal.goal_type if goal else None,
                "calories": goal.daily_calories if goal else None,
                "protein": goal.protein_grams if goal else None,
            },
            "body": {
                "weight": last_weight.weight_lbs if last_weight else None,
                "weight_date": str(last_weight.log_date) if last_weight else None,
                "pa_weight": pa.bodyweight_lbs if pa else None,
                "pa_height": pa.height_inches if pa else None,
            },
            "activity": {
                "last_chat": str(last_chat.created_at)[:16] if last_chat else None,
                "last_checkin": str(last_checkin.log_date) if last_checkin else None,
                "days_completed": days_done,
                "sets_logged": sets_logged,
            },
        })

    return jsonify({"users": result, "count": len(result)})


@app.route("/api/admin/debug/fire-coach", methods=["POST"])
@admin_required
def api_admin_debug_fire_coach():
    """Run a coach trigger as the specified user. Saves request + response
    to chat_message. Admin-only. Used to test review flows without going
    through the localStorage-gated UI path."""
    from flask_login import login_user
    from coach_router import route_trigger
    from coach_assembler import build_filtered_context, assemble_prompt
    from coach import _build_messages
    from coach_with_tools import coach_chat
    from coach_agents import AGENTS
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    trigger = (data.get("trigger") or "").strip()
    if not email or not trigger:
        return jsonify({"error": "email and trigger required"}), 400
    user_obj = User.query.filter_by(email=email).first()
    if not user_obj:
        return jsonify({"error": f"user {email} not found"}), 404
    with app.test_request_context():
        login_user(user_obj, force=True)
        log_date = _user_today()
        # Save user message
        user_msg = ChatMessage(
            role="user", content=trigger, log_date=log_date,
            user_id=user_obj.id, message_type="chat",
        )
        db.session.add(user_msg)
        db.session.commit()
        # Route + build context + run coach
        route_info = route_trigger(trigger)
        context = build_filtered_context(route_info["agent_name"])
        system_prompt = assemble_prompt(route_info["agent_name"], context)
        messages = _build_messages(
            trigger, context.get("chat_history", []),
            user_timezone=context.get("user_timezone"),
        )
        agent_config = AGENTS.get(route_info["agent_name"], AGENTS["conversation"])
        response = coach_chat(
            user_id=user_obj.id, system_prompt=system_prompt,
            messages=messages, max_tokens=agent_config["max_tokens"],
            agent_name=route_info["agent_name"],
        )
        # Save assistant response
        asst = ChatMessage(
            role="assistant", content=response, log_date=log_date,
            user_id=user_obj.id, message_type="chat",
        )
        db.session.add(asst)
        db.session.commit()
        return jsonify({
            "ok": True, "agent": route_info["agent_name"],
            "response": response,
        })


@app.route("/api/admin/debug/exec", methods=["POST"])
@admin_required
def api_admin_debug_exec():
    """Run a write SQL statement. Admin-only. UPDATE/INSERT/DELETE only."""
    data = request.get_json()
    sql = (data.get("sql") or "").strip()
    if not sql:
        return jsonify({"error": "No SQL provided"}), 400
    upper = sql.upper().lstrip()
    if not (upper.startswith("UPDATE") or upper.startswith("INSERT") or upper.startswith("DELETE")):
        return jsonify({"error": "Only UPDATE/INSERT/DELETE allowed"}), 403
    try:
        result = db.session.execute(text(sql))
        db.session.commit()
        return jsonify({"ok": True, "rowcount": result.rowcount})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/admin/heal-prescriptions", methods=["POST"])
@admin_required
def api_admin_heal_prescriptions():
    """Heal stored lift prescriptions in place so no row renders a non-loadable
    barbell weight or a why that contradicts its number — covers PRESERVED/past/
    pre-fix rows the generation-time loadability+reconcile never touched (e.g. a
    re-derive that preserves Monday leaves its stale 'climbing to 140' on a load
    that's actually 155). Idempotent. Body: {email, week?(int, all weeks if omitted)}."""
    data = request.get_json() or {}
    u = User.query.filter_by(email=data.get("email")).first()
    if not u:
        return jsonify({"error": "user not found"}), 404
    q = WeeklyPrescription.query.filter_by(user_id=u.id, source='coach')
    if data.get("week") is not None:
        q = q.filter_by(week=int(data["week"]))
    healed = []
    for rx in q.all():
        w0 = rx.target_weight
        reason0 = rx.adjustment_reason or ""
        recent_top = None
        if w0 and w0 > 0:
            recent_top = db.session.query(db.func.max(SetLog.weight)).filter(
                SetLog.user_id == u.id, SetLog.exercise_name == rx.exercise_name,
                SetLog.weight > 0, SetLog.week >= max(1, rx.week - 6)).scalar()
        proposed = w0
        neww = w0
        is_bb = _is_barbell_movement(rx.exercise_name)
        if w0 and w0 > 0:
            neww = _round_to_loadable(rx.exercise_name, w0)
            # Floor below the logged top ONLY for barbell lifts. Non-barbell
            # isolations (e.g. a Rear Delt Fly the coach deliberately starts
            # light as a new movement) must NOT be force-raised by the heal —
            # the write loop's new-movement light-start rule owns those.
            if (is_bb and rx.week not in (4, 8, 12)
                    and recent_top is not None and neww < recent_top):
                neww = float(recent_top)
        really_new = (recent_top is None)
        newreason = _reconcile_lift_reason(reason0, neww, proposed, recent_top,
                                           really_new, is_bb)
        if (neww != w0) or (newreason != reason0):
            healed.append({"week": rx.week, "day": rx.day_idx, "ex": rx.exercise_name,
                           "weight": f"{w0}->{neww}", "reason_was": reason0[:60],
                           "reason_now": newreason[:60]})
            rx.target_weight = neww
            rx.adjustment_reason = newreason
    db.session.commit()
    return jsonify({"ok": True, "healed_count": len(healed), "healed": healed[:60]})


@app.route("/api/admin/debug/coach-dryrun", methods=["POST"])
@admin_required
def api_admin_coach_dryrun():
    """Run the live coach for a user with the CURRENT model, NO output gate — to
    test whether the raw model (e.g. Opus 4.8) prescribes an already-logged lift
    or fast-day food on its own. Body: {email, message}. Returns the raw response
    plus the grounding signals it had, and what the gate WOULD have done."""
    from flask_login import login_user
    from models import User as _User
    data = request.get_json() or {}
    u = _User.query.filter_by(email=data.get("email")).first()
    if not u:
        return jsonify({"error": "user not found"}), 404
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "message required"}), 400
    force_done = bool(data.get("force_workout_logged"))
    force_fast = bool(data.get("force_fast_day"))
    try:
        with app.test_request_context():
            login_user(u, force=True)
            from coach_router import route_trigger
            from coach_assembler import build_filtered_context, assemble_prompt
            from coach import _build_messages, CLAUDE_OPUS
            ri = route_trigger(msg)
            ctx = build_filtered_context(ri["agent_name"])
            # Inject the failure conditions into context WITHOUT touching the DB,
            # so we can test the model on the exact signals that broke it.
            if force_done:
                ctx.setdefault("today_status", {})
                ctx["today_status"]["workout_prescribed"] = True
                ctx["today_status"]["workout_logged"] = True
            if force_fast:
                ctx["fasting_state"] = {"hours_fasted": 15.0, "last_meal_day": "yesterday",
                                        "last_meal_time": "7:00pm", "is_fast_day": True,
                                        "eating_window_opens": "NONE — full fast day"}
            sp = assemble_prompt(ri["agent_name"], ctx)
            messages = _build_messages(msg, ctx.get("chat_history", []),
                                       user_timezone=ctx.get("user_timezone"))
            # Direct, NO-TOOL call so the model answers from the prompt+context
            # alone (tools would re-fetch real DB state and muddy the forced test).
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), max_retries=2)
            resp = client.messages.create(model=CLAUDE_OPUS, max_tokens=600,
                                           system=sp, messages=messages)
            raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
            ts = ctx.get("today_status") or {}
            return jsonify({
                "model": CLAUDE_OPUS,
                "agent": ri["agent_name"],
                "forced": {"workout_logged": force_done, "fast_day": force_fast},
                "signals_in_context": {"workout_logged": ts.get("workout_logged"),
                                       "is_fast_day": (ctx.get("fasting_state") or {}).get("is_fast_day")},
                "raw_response": raw,
            })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e)[:300], "tb": traceback.format_exc()[:700]}), 500


@app.route("/api/admin/debug/fix-indexes", methods=["POST"])
@admin_required
def api_admin_fix_indexes():
    """Drop ALL broken unique indexes that lack user_id and recreate correctly."""
    fixed = []
    errors = []
    # Every UNIQUE index/constraint without user_id is a cross-user data leak.
    # PostgreSQL: plain indexes use DROP INDEX, but constraints need ALTER TABLE DROP CONSTRAINT.
    fixes = [
        ("body_measurement", "ix_body_measurement_log_date", "CREATE INDEX IF NOT EXISTS ix_body_measurement_log_date ON body_measurement (log_date)"),
        ("body_weight", "ix_body_weight_log_date", "CREATE INDEX IF NOT EXISTS ix_body_weight_log_date ON body_weight (log_date)"),
        ("day_completion", "day_completion_week_day_idx_key", "CREATE INDEX IF NOT EXISTS ix_day_completion_user ON day_completion (user_id, week, day_idx)"),
        ("exercise_completion", "exercise_completion_week_day_idx_exercise_idx_key", "CREATE INDEX IF NOT EXISTS ix_exercise_completion_user ON exercise_completion (user_id, week, day_idx, exercise_idx)"),
        ("meal_log", "ix_meal_log_log_date", "CREATE INDEX IF NOT EXISTS ix_meal_log_user_date ON meal_log (user_id, log_date)"),
        ("morning_checkin", "ix_morning_checkin_log_date", "CREATE INDEX IF NOT EXISTS ix_morning_checkin_user_date ON morning_checkin (user_id, log_date)"),
        ("supplement_log", "supplement_log_log_date_supplement_name_key", "CREATE INDEX IF NOT EXISTS ix_supplement_log_user ON supplement_log (user_id, log_date, supplement_name)"),
        ("weekly_checkin", "weekly_checkin_week_key", "CREATE INDEX IF NOT EXISTS ix_weekly_checkin_user_week ON weekly_checkin (user_id, week)"),
        ("weekly_report", "weekly_report_week_key", "CREATE INDEX IF NOT EXISTS ix_weekly_report_user_week ON weekly_report (user_id, week)"),
    ]
    for tbl, drop_name, create_sql in fixes:
        # Try DROP INDEX first, then ALTER TABLE DROP CONSTRAINT as fallback
        for drop_sql in [
            f'DROP INDEX IF EXISTS {drop_name}',
            f'ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {drop_name}',
        ]:
            try:
                db.session.execute(text(drop_sql))
                db.session.commit()
                break
            except Exception:
                db.session.rollback()
        try:
            db.session.execute(text(create_sql))
            db.session.commit()
            fixed.append(drop_name)
        except Exception as e:
            db.session.rollback()
            errors.append({"index": drop_name, "error": str(e)[:100]})
    return jsonify({"ok": True, "fixed": fixed, "errors": errors})


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
        existing.source = "manual"
    else:
        existing = RunLog(
            user_id=current_user.id, week=data.get("week"), day_idx=data.get("day_idx"),
            distance_miles=data.get("distance_miles"), avg_hr=data.get("avg_hr"),
            elevation_ft=data.get("elevation_ft"), duration_min=data.get("duration_min"),
            notes=data.get("notes"), log_date=_user_today(), source="manual",
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
        "source": l.source or "manual",
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
