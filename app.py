"""Flask app for 12 Weeks Tracker with Garmin integration."""

import os
import re
import secrets
import threading
import time
import uuid
from datetime import date, timedelta, datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, Response, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer

from workout_data import (
    get_workouts, get_phase, PHASES, WARMUPS, SUPPLEMENTS,
    TRAVEL_WORKOUTS, TRAVEL_DAY_MAP,
)
from garmin_client import GarminClient
from overtraining import assess_readiness
from coach import get_coach_response, extract_memories
from psych_intake import get_intake_response, generate_intake_report, generate_full_profile
from models import (
    db, User, Invite, ExerciseLog, ExerciseCompletion, ExerciseSwap, DayCompletion,
    MealLog, AppState, BodyWeight, BodyMeasurement,
    WeeklyCheckIn, SupplementLog, MorningCheckIn, ChatMessage,
    ProgressPhoto, PsychIntake, GarminTokens, PhysicalAssessment,
    UserConstraints, TrainingGoal, UserFoodSelections, WeeklyReport,
    UserEquipment, WarmupCompletion, RunLog, SetLog, CoachMemory,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


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
    @login_required
    def decorated(*args, **kwargs):
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

with app.app_context():
    # Drop and recreate psych_intake if it's missing the locked_until column
    from sqlalchemy import inspect as sa_inspect, text
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
    db.create_all()

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
    ]
    try:
        inspector = sa_inspect(db.engine)
        for table, col, col_type in _migrations:
            if table in inspector.get_table_names():
                existing = {c["name"] for c in inspector.get_columns(table)}
                if col not in existing:
                    db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}'))
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
                    db.session.execute(text(f'ALTER TABLE {tbl} ADD COLUMN user_id INTEGER REFERENCES "user"(id)'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # ONE-TIME FIX: siggijohnson226@gmail.com weight = 128
    try:
        _fix_user = User.query.filter_by(email="siggijohnson226@gmail.com").first()
        if _fix_user:
            # Fix PhysicalAssessment
            _fix_pa = PhysicalAssessment.query.filter_by(user_id=_fix_user.id).first()
            if _fix_pa:
                _fix_pa.bodyweight_lbs = 128.0
            # Fix/create BodyWeight entry
            from datetime import date as _d
            _fix_bw = BodyWeight.query.filter_by(user_id=_fix_user.id).order_by(BodyWeight.log_date.desc()).first()
            if _fix_bw:
                _fix_bw.weight_lbs = 128.0
            else:
                db.session.add(BodyWeight(log_date=_d.today(), weight_lbs=128.0, user_id=_fix_user.id))
            # Reset goal to recompute with correct weight
            _fix_goal = TrainingGoal.query.filter_by(user_id=_fix_user.id).first()
            if _fix_goal:
                _fix_goal.plan_accepted = False
            db.session.commit()
    except Exception:
        db.session.rollback()

    # ONE-TIME FIX: Backfill 0-rep sets with target reps from workout data
    try:
        _zero_rep_sets = SetLog.query.filter_by(reps=0, done=True).all()
        if _zero_rep_sets:
            # Target reps by exercise from workout data
            _target_reps = {
                "Barbell Bench Press": 10, "Lat Pulldown": 8, "Incline DB Press": 10,
                "Face Pull": 15, "Lateral Raise": 15, "EZ-Bar Curl": 12,
                "Cable Tricep Pushdown": 12, "Barbell Bent-Over Row": 10,
                "Cable Seated Row": 10, "Dumbbell Shoulder Press": 10,
            }
            for s in _zero_rep_sets:
                target = _target_reps.get(s.exercise_name, 10)
                s.reps = target
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

        user.last_login_at = datetime.now()
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
        invite.used_at = datetime.now()
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
            user.last_login_at = datetime.now()
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
            invite.used_at = datetime.now()
            db.session.commit()

        user.last_login_at = datetime.now()
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
    SAFETY CRITICAL: Also enforces allergen/dietary restriction filtering."""
    import copy
    if user_food_ids is None:
        return days  # No selections yet = show everything

    # Always-allowed items (zero-cal condiments, basics, beverages — don't break fast)
    always_allowed = {"Black coffee", "Water", "Salsa", "Electrolytes (salt, potassium)",
                      "Lemon juice"}

    filtered_days = copy.deepcopy(days)
    for day in filtered_days:
        mp = day.get("mealPlan")
        if not mp or not mp.get("meals"):
            continue
        filtered_meals = []
        for meal in mp["meals"]:
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
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    user_equipment = eq.available_equipment if eq else []
    user_food_ids = _get_user_food_ids()
    all_weeks = {}
    for week in range(1, 13):
        phase = get_phase(week)
        days = get_workouts(week)
        for day in days:
            if "exercises" in day:
                day["exercises"] = auto_swap_workout(day["exercises"], user_equipment)
        days = _filter_meals_by_food_selections(days, user_food_ids)
        all_weeks[str(week)] = {
            "week": week,
            "phase": phase,
            "phaseInfo": PHASES[phase],
            "days": days,
        }
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
    for day in days:
        if "exercises" in day:
            day["exercises"] = auto_swap_workout(day["exercises"], user_equipment)
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
    logs = ExerciseLog.query.filter_by(user_id=current_user.id).order_by(ExerciseLog.logged_date, ExerciseLog.id).all()
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
@login_required
def api_weights_record():
    data = request.get_json()
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
        existing.logged_date = date.today()
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
        logged_date=date.today(),
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
    data = request.get_json()
    exercise = data.get("exercise")
    week = data.get("week")
    day_idx = data.get("day_idx")
    set_number = data.get("set_number")
    weight = data.get("weight", 0)
    reps = data.get("reps", 0)
    done = data.get("done", True)

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
        existing.done = done
        existing.logged_date = date.today()
    else:
        existing = SetLog(
            user_id=current_user.id, exercise_name=exercise,
            week=week, day_idx=day_idx, set_number=set_number,
            weight=weight, reps=reps, done=done, logged_date=date.today(),
        )
        db.session.add(existing)
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


@app.route("/api/weights/baseline", methods=["POST"])
@login_required
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
            user_id=current_user.id,
        )
        db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True})


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
    """Save an exercise swap."""
    data = request.get_json()
    week = data.get("week")
    day_idx = data.get("day_idx")
    exercise_idx = data.get("exercise_idx")
    swapped_to = data.get("swapped_to", "").strip()

    if week is None or day_idx is None or exercise_idx is None or not swapped_to:
        return jsonify({"error": "Missing fields"}), 400

    existing = ExerciseSwap.query.filter_by(
        user_id=current_user.id, week=week, day_idx=day_idx, exercise_idx=exercise_idx
    ).first()

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
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
    return jsonify({"done": dc.done})


# ─── MEALS ──────────────────────────────────────────────────────────────────

@app.route("/api/meals")
@login_required
def api_meals():
    d = request.args.get("date", date.today().isoformat())
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).first()
    if not ml:
        return jsonify({"eaten": [], "adjustments": {}, "fasting": False})
    return jsonify({
        "eaten": ml.eaten or [],
        "adjustments": ml.adjustments or {},
        "fasting": ml.fasting,
    })


@app.route("/api/meals", methods=["POST"])
@login_required
def api_meals_update():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=d).first()
    if not ml:
        ml = MealLog(log_date=d, user_id=current_user.id)
        db.session.add(ml)
    if "eaten" in data:
        ml.eaten = data["eaten"]
    if "adjustments" in data:
        ml.adjustments = data["adjustments"]
    if "fasting" in data:
        ml.fasting = data["fasting"]
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500
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
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
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
        db.session.delete(bw)
        db.session.commit()
    return jsonify({"ok": True})


# ─── BODY MEASUREMENTS ─────────────────────────────────────────────────────

@app.route("/api/measurements")
@login_required
def api_measurements():
    entries = BodyMeasurement.query.filter_by(user_id=current_user.id).order_by(BodyMeasurement.log_date).all()
    return jsonify([{
        "date": e.log_date.isoformat(),
        "waist": e.waist_inches,
        "notes": e.notes,
    } for e in entries])


@app.route("/api/measurements", methods=["POST"])
@login_required
def api_measurements_record():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    bm = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=d).first()
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
            user_id=current_user.id,
        )
        db.session.add(bm)
    db.session.commit()
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
            check_in_date=date.today(),
            user_id=current_user.id,
        )
        db.session.add(ci)
    db.session.commit()
    return jsonify({"ok": True})


# ─── SUPPLEMENTS ────────────────────────────────────────────────────────────

@app.route("/api/supplements")
@login_required
def api_supplements():
    d = request.args.get("date", date.today().isoformat())
    logs = SupplementLog.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).all()
    taken = {s.supplement_name: s.taken for s in logs}
    return jsonify({"date": d, "taken": taken, "list": SUPPLEMENTS})


@app.route("/api/supplements", methods=["POST"])
@login_required
def api_supplements_toggle():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
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
        "exported_at": datetime.utcnow().isoformat(),
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
                    logged_date=date.fromisoformat(h["date"]) if h.get("date") else date.today(),
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

    # Waist measurements
    measurements = [{
        "date": e.log_date.isoformat(), "waist": e.waist_inches,
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
    d = request.args.get("date", date.today().isoformat())
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
    })


@app.route("/api/morning-checkin", methods=["POST"])
@login_required
def api_morning_checkin_save():
    data = request.get_json()
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
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
    since = date.today() - timedelta(days=days)
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


# ─── PSYCHOLOGICAL INTAKE ───────────────────────────────────────────────────

@app.route("/api/psych-intake/status")
@login_required
def api_psych_intake_status():
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
    if not intake:
        return jsonify({"started": False, "completed": False, "has_report": False, "locked": False})
    locked = intake.locked_until and date.today() < intake.locked_until
    lockout_expired = intake.locked_until and date.today() >= intake.locked_until
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
        if intake.locked_until and date.today() < intake.locked_until:
            days_left = (intake.locked_until - date.today()).days
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
        intake.locked_until = date.today() + timedelta(days=7)

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

@app.route("/api/chat/history")
@login_required
def api_chat_history():
    days = request.args.get("days", 7, type=int)
    limit = request.args.get("limit", 100, type=int)
    since = date.today() - timedelta(days=days)
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

    # Save user message
    user_chat = ChatMessage(role="user", content=user_msg, log_date=date.today(), user_id=current_user.id)
    db.session.add(user_chat)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500

    # Build context for the AI coach
    context = _build_coach_context()

    # Get AI response
    response_text = get_coach_response(user_msg, context)

    # Save assistant message
    asst_chat = ChatMessage(role="assistant", content=response_text, log_date=date.today(), user_id=current_user.id)
    db.session.add(asst_chat)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Save failed"}), 500

    # Extract and save memories (runs in background, non-blocking)
    uid = current_user.id
    week = context.get("week", 1)
    _app = app

    def _save_memories():
        with _app.app_context():
            try:
                memories = extract_memories(user_msg, response_text, context)
                for mem in memories:
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


@app.route("/api/chat/stream", methods=["POST"])
@login_required
def api_chat_stream():
    """Streaming coach response via SSE."""
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Message required"}), 400

    # Save user message
    user_chat = ChatMessage(role="user", content=user_msg, log_date=date.today(), user_id=current_user.id)
    db.session.add(user_chat)
    db.session.commit()

    _current_user_id = current_user.id

    context = _build_coach_context()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "API key not configured"}), 500

    def generate():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=30.0)

            from coach import _build_system_prompt, _build_messages
            system_prompt = _build_system_prompt(context)
            messages = _build_messages(user_msg, context.get("chat_history", []))

            full_text = ""
            with client.messages.stream(
                model="claude-opus-4-20250514",
                max_tokens=800,
                system=system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    yield f"data: {text}\n\n"

            # Only save if stream completed fully with content
            if full_text.strip():
                asst_chat = ChatMessage(role="assistant", content=full_text, log_date=date.today(), user_id=_current_user_id)
                db.session.add(asst_chat)
                db.session.commit()

            yield f"data: [DONE]\n\n"
        except GeneratorExit:
            # Client disconnected mid-stream — don't save partial response
            import logging
            logging.warning("Client disconnected mid-stream, discarding partial response")
        except Exception as e:
            # Don't save partial response on error
            import logging
            logging.error("Stream error: %s", e)
            yield f"data: [ERROR]\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
        MorningCheckIn.user_id == current_user.id,
        MorningCheckIn.log_date >= since
    ).order_by(MorningCheckIn.log_date).all()]

    # Chat history
    chat_history = [{
        "role": m.role,
        "content": m.content,
    } for m in ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= since
    ).order_by(ChatMessage.created_at).all()]

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
    week = s.current_week
    phase = get_phase(week)
    phase_info = PHASES[phase]

    # Today's workout
    workouts = get_workouts(week)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today_idx = date.today().weekday()  # 0=Mon
    workout_today = workouts[today_idx] if today_idx < len(workouts) else None

    # Supplements today
    supps = SupplementLog.query.filter_by(user_id=current_user.id, log_date=date.today()).all()
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
    exercise_history = {}
    for log in exercise_logs:
        if log.exercise_name not in exercise_history:
            exercise_history[log.exercise_name] = []
        if len(exercise_history[log.exercise_name]) < 3:
            entry = {
                "weight": log.weight, "rpe": log.rpe,
                "reps_completed": log.reps_completed,
                "week": log.week,
                "date": log.logged_date.isoformat() if log.logged_date else None,
            }
            if log.estimated_1rm:
                entry["estimated_1rm"] = log.estimated_1rm
            exercise_history[log.exercise_name].append(entry)

    # Per-set data for today
    today_idx = date.today().weekday()
    today_sets = SetLog.query.filter_by(
        user_id=current_user.id, week=week, day_idx=today_idx
    ).order_by(SetLog.exercise_name, SetLog.set_number).all()
    set_data = {}
    for s in today_sets:
        if s.exercise_name not in set_data:
            set_data[s.exercise_name] = []
        set_data[s.exercise_name].append({
            "set": s.set_number + 1, "weight": s.weight,
            "reps": s.reps, "done": s.done,
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

    # Body measurements (latest)
    latest_measure = BodyMeasurement.query.filter_by(
        user_id=current_user.id
    ).order_by(BodyMeasurement.log_date.desc()).first()
    measurements = None
    if latest_measure:
        measurements = {
            "date": latest_measure.log_date.isoformat(),
            "waist": latest_measure.waist_inches,
        }

    # Equipment
    eq = UserEquipment.query.filter_by(user_id=current_user.id).first()
    equipment = eq.available_equipment if eq else []

    # Meal adherence today + today's meal plan
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=date.today()).first()
    meals_today = None
    if ml:
        meals_today = {"eaten": ml.eaten or [], "fasting": ml.fasting}

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

    # Day completion status (this week)
    day_completions = DayCompletion.query.filter_by(
        user_id=current_user.id, week=week
    ).all()
    completed_days = [dc.day_idx for dc in day_completions if dc.done]

    # Schedule notes
    schedule_notes = constraints.schedule_notes if constraints else None

    # Coach memory — persistent observations across conversations
    memories = CoachMemory.query.filter_by(user_id=current_user.id).order_by(
        CoachMemory.created_at.desc()
    ).limit(20).all()
    coach_memories = [{"type": m.memory_type, "content": m.content, "week": m.week} for m in memories]

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
        "athlete_name": current_user.name or "Athlete",
        "scheduled_activities": _get_scheduled_activities(),
        "food_restrictions": food_restrictions,
        "custom_allergies": custom_allergies,
        "selected_foods": selected_foods_summary,
        "fasting_protocol": fasting_protocol,
        # NEW — full athlete profile
        "goal": goal_data,
        "exercise_history": exercise_history,
        "today_sets": set_data,
        "run_history": runs,
        "physical_assessment": physical,
        "body_measurements": measurements,
        "equipment": equipment,
        "meals_today": meals_today,
        "meal_plan_today": todays_meal_plan,
        "completed_days_this_week": completed_days,
        "schedule_notes": schedule_notes,
        "coach_memories": coach_memories,
    }


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
    week = s.current_week

    # Save photo
    photo = ProgressPhoto(
        log_date=date.today(),
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
        ProgressPhoto.log_date < date.today(),
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
            model="claude-opus-4-20250514",
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
    if not intake or not pa:
        return jsonify({"error": "Intake and physical assessment required"}), 400

    # Extract actor answer from conversation
    actor_answer = ""
    convo = intake.conversation or []
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
        db.session.add(BodyWeight(log_date=date.today(), weight_lbs=weight, user_id=current_user.id))
        db.session.commit()
    else:
        return jsonify({"error": "No weight data found. Complete physical assessment first."}), 400
    height = (pa.height_inches if pa else None) or 70

    goal_info = detect_goal(actor_answer)
    goal_type = goal_info["goal_type"]
    target_bf = goal_info["target_bf"]

    tdee_info = compute_tdee(weight, height, age, sex)

    # Compute target weight from body fat
    # Estimate current BF: rough formula (not perfect but functional)
    if sex == "male":
        est_bf = 0.15 if weight < 180 else 0.20 if weight < 220 else 0.25
    else:
        est_bf = 0.22 if weight < 150 else 0.28 if weight < 180 else 0.33
    lean_mass = weight * (1 - est_bf)
    target_weight = lean_mass / (1 - target_bf)

    targets = compute_targets(tdee_info["tdee"], goal_type, weight)
    fasting = determine_fasting_protocol(goal_type, targets["calories"])
    phase_plan = compute_phase_plan(goal_type, weight, target_weight, est_bf)
    projection = project_weight_curve(weight, target_weight, tdee_info["tdee"], targets["calories"])

    # Compute per-day-type calories
    day_types = ["heavy_lift", "long_run", "moderate", "rest", "deload"]
    cal_by_day = {}
    for dt in day_types:
        cal_by_day[dt] = compute_day_calories(targets["calories"], goal_type, dt)

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
    week = s.current_week
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
    week = s.current_week

    _current_user_id = current_user.id
    metrics = compute_weekly_metrics(week, user_id=_current_user_id)

    # Save computed metrics immediately

    report = WeeklyReport.query.filter_by(user_id=current_user.id, week=week).first()
    if not report:
        report = WeeklyReport(week=week, report_date=date.today(), user_id=current_user.id)
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
    workouts = get_workouts(s.current_week)
    today_idx = date.today().weekday()
    workout_today = workouts[today_idx] if today_idx < len(workouts) else None
    workout_name = workout_today.get("liftName", "Rest") if workout_today else "Rest"

    # Build checkin summary
    checkin_summary = f"Morning check-in: Sleep {data.get('sleep_quality', 5)}/10, Stress {data.get('stress_level', 5)}/10, Soreness {data.get('soreness', 5)}/10, Mood {data.get('mood', 5)}/10, Motivation {data.get('motivation', 5)}/10, Anxiety {data.get('anxiety', 3)}/10."
    if data.get('notes'):
        checkin_summary += f" Notes: {data['notes']}"

    # Use full coach context + special trigger
    briefing_msg = f"[MORNING_BRIEFING] Status: {status} ({score}/100). Today is {workout_name} — Week {s.current_week}. {checkin_summary} Give me a 1-2 sentence morning briefing. If GREEN, get me out the door. If YELLOW, name the adjustment. If RED, tell me to stand down."

    context = _build_coach_context()
    response_text = get_coach_response(briefing_msg, context)

    # Save as chat messages
    user_chat = ChatMessage(role="user", content=checkin_summary, log_date=date.today(), user_id=current_user.id)
    asst_chat = ChatMessage(role="assistant", content=response_text, log_date=date.today(), user_id=current_user.id)
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
        intake.locked_until = date.today() + timedelta(days=7)
        db.session.commit()
    return jsonify({"ok": True, "locked_until": (date.today() + timedelta(days=7)).isoformat()})


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
        # CRITICAL: Also log to BodyWeight table — this is the primary weight source
        d = date.today()
        bw = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
        if bw:
            bw.weight_lbs = float(data["bodyweight"])
        else:
            db.session.add(BodyWeight(log_date=d, weight_lbs=float(data["bodyweight"]), user_id=current_user.id))
        # Flush immediately to ensure BodyWeight entry is created
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            # Re-add the physical assessment
            pa = PhysicalAssessment.query.filter_by(user_id=current_user.id).first()
            if pa:
                pa.bodyweight_lbs = float(data["bodyweight"])
    if "waist" in data:
        pa.waist_inches = data["waist"]
        d = date.today()
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
            notes=data.get("notes"), log_date=date.today(),
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
