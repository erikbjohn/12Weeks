"""Flask app for 12 Weeks Tracker with Garmin integration."""

import os
import secrets
import threading
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
from coach import get_coach_response
from psych_intake import get_intake_response, generate_intake_report, generate_full_profile
from models import (
    db, User, Invite, ExerciseLog, ExerciseCompletion, DayCompletion,
    MealLog, AppState, BodyWeight, BodyMeasurement,
    WeeklyCheckIn, SupplementLog, MorningCheckIn, ChatMessage,
    ProgressPhoto, PsychIntake, GarminTokens, PhysicalAssessment,
    UserConstraints, TrainingGoal, UserFoodSelections, WeeklyReport,
    UserEquipment,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

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

garmin = GarminClient()

# Try to restore Garmin session from saved tokens
with app.app_context():
    garmin.try_restore_tokens()


# ─── AUTH ──────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/")

    if request.method == "POST":
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


@app.route("/invite/<code>")
def accept_invite(code):
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


# ─── WORKOUT DATA ───────────────────────────────────────────────────────────

@app.route("/api/workouts")
@login_required
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
@login_required
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
    db.session.commit()
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
    log = ExerciseLog(
        exercise_name=data["exercise"],
        weight=data["weight"],
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
    db.session.commit()
    return jsonify({"ok": True, "id": log.id})


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
    db.session.commit()
    return jsonify({"done": ec.done})


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
    db.session.commit()
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
    db.session.commit()
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
    d = date.fromisoformat(data.get("date", date.today().isoformat()))
    bw = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
    if bw:
        bw.weight_lbs = data["weight"]
    else:
        # log_date has a global unique constraint; check if another user owns it
        existing = BodyWeight.query.filter_by(log_date=d).first()
        if existing:
            # Update in place (shouldn't happen in single-user, but handles constraint)
            existing.weight_lbs = data["weight"]
            existing.user_id = current_user.id
        else:
            bw = BodyWeight(log_date=d, weight_lbs=data["weight"], user_id=current_user.id)
            db.session.add(bw)
    db.session.commit()
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
    db.session.commit()
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
    db.session.commit()
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
    return jsonify({
        "started": True,
        "completed": intake.completed,
        "has_report": intake.report is not None,
        "message_count": len(intake.conversation or []),
        "locked": bool(locked),
        "locked_until": intake.locked_until.isoformat() if locked else None,
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

        # Save user message to DB immediately so it's not lost
        intake.conversation = convo
        db.session.commit()

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
        else:
            intake.completed = False

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
    since = date.today() - timedelta(days=days)
    messages = ChatMessage.query.filter(
        ChatMessage.user_id == current_user.id,
        ChatMessage.log_date >= since
    ).order_by(ChatMessage.created_at).all()
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
    db.session.commit()

    # Build context for the AI coach
    context = _build_coach_context()

    # Get AI response
    response_text = get_coach_response(user_msg, context)

    # Save assistant message
    asst_chat = ChatMessage(role="assistant", content=response_text, log_date=date.today(), user_id=current_user.id)
    db.session.add(asst_chat)
    db.session.commit()

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

            # Save complete response
            asst_chat = ChatMessage(role="assistant", content=full_text, log_date=date.today(), user_id=_current_user_id)
            db.session.add(asst_chat)
            db.session.commit()

            yield f"data: [DONE]\n\n"
        except Exception as e:
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

    # Body weight
    bw_entries = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date).all()
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
    supps = SupplementLog.query.filter_by(user_id=current_user.id, log_date=date.today()).all()
    supps_taken = {s.supplement_name: s.taken for s in supps}

    # Psych intake report (contains aspirational body type, goals, etc.)
    intake = PsychIntake.query.filter_by(user_id=current_user.id).first()
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
@login_required
def garmin_status():
    return jsonify({"connected": garmin.connected})


@app.route("/api/garmin/today")
@login_required
def garmin_today():
    if not garmin.connected:
        return jsonify({"error": "Not connected to Garmin"}), 401
    summary = garmin.get_today_summary()
    if summary is None:
        return jsonify({"error": "Failed to fetch Garmin data"}), 500
    return jsonify(summary)


@app.route("/api/garmin/readiness")
@login_required
def garmin_readiness():
    if not garmin.connected:
        return jsonify(assess_readiness(None))
    summary = garmin.get_today_summary()
    return jsonify(assess_readiness(summary))


@app.route("/api/garmin/hrv-trend")
@login_required
def garmin_hrv_trend():
    if not garmin.connected:
        return jsonify({"error": "Not connected"}), 401
    return jsonify(garmin.get_weekly_hrv() or [])


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
        garmin.api = G()
        garmin.api.login(tokenstore=tokens)
        garmin._connected = True
        garmin._cache = {}
        garmin._save_tokens()
        return jsonify({"connected": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/garmin/logout", methods=["POST"])
@login_required
def garmin_logout():
    garmin.api = None
    garmin._connected = False
    garmin._cache = {}
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
            if "actor" in prev.lower() or "movie" in prev.lower() or "body you want" in prev.lower():
                actor_answer = msg["content"]
                break

    # Extract sex and age from conversation
    sex = "male"
    age = 30
    for msg in convo:
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

    # BodyWeight is primary, PhysicalAssessment is fallback
    latest_bw = BodyWeight.query.filter_by(user_id=current_user.id).order_by(BodyWeight.log_date.desc()).first()
    if latest_bw:
        weight = latest_bw.weight_lbs
    elif pa and pa.bodyweight_lbs:
        weight = pa.bodyweight_lbs
        # Sync to BodyWeight table so it's there for next time
        db.session.add(BodyWeight(log_date=date.today(), weight_lbs=weight, user_id=current_user.id))
        db.session.commit()
    else:
        weight = 180
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

    return jsonify({
        "goal_type": goal_type,
        "target_weight": round(target_weight, 1),
        "target_bf_pct": target_bf,
        "calories": targets["calories"],
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
    body_weight = latest_bw.weight_lbs if latest_bw else (pa.bodyweight_lbs if pa else 180)

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

MORNING_BRIEFING_PROMPT = """You are Erik — high-performance coach. Lombardi voice. Direct. Invested. No fluff.

STATUS: {status}
DATA: {data}
WORKOUT: {workout}

Write ONE sentence. If GREEN: acknowledge the data, name today's workout, get them out the door. If YELLOW: name the adjustment needed. If RED: say "We need to talk" and ask what's going on.

No motivational speeches. Facts + orders. End with the workout name or a question (never a dead statement)."""

@app.route("/api/morning-briefing", methods=["POST"])
@login_required
def api_morning_briefing():
    data = request.get_json()

    # Get readiness status
    garmin_data = garmin.get_today_summary() if garmin.connected else None
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

    # Build data summary
    data_summary = f"Readiness: {score}/100."
    if garmin_data:
        hrv = garmin_data.get("hrv", {})
        sleep = garmin_data.get("sleep", {})
        if hrv.get("lastNight"):
            data_summary += f" HRV: {hrv['lastNight']}."
        if sleep.get("score"):
            data_summary += f" Sleep: {sleep['score']}."

    # Checkin data
    checkin = data or {}
    if checkin.get("mood"):
        data_summary += f" Mood: {checkin['mood']}/10."
    if checkin.get("soreness") and checkin["soreness"] >= 7:
        data_summary += f" Soreness: {checkin['soreness']}/10."

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"status": status, "message": f"{status}. {workout_name} today.", "workout": workout_name})

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)

        prompt = MORNING_BRIEFING_PROMPT.format(
            status=status, data=data_summary, workout=workout_name
        )

        full_text = ""
        with client.messages.stream(
            model="claude-opus-4-20250514",
            max_tokens=200,
            system=prompt,
            messages=[{"role": "user", "content": "Give me the morning briefing."}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text

        return jsonify({
            "status": status,
            "message": full_text.strip(),
            "workout": workout_name,
            "readiness_score": score,
            "needs_discussion": status == "RED",
        })
    except Exception:
        return jsonify({"status": status, "message": f"{workout_name} today. Score: {score}.", "workout": workout_name})


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
    if "bodyweight" in data:
        pa.bodyweight_lbs = data["bodyweight"]
        # Also log to BodyWeight table
        d = date.today()
        bw = BodyWeight.query.filter_by(user_id=current_user.id, log_date=d).first()
        if bw:
            bw.weight_lbs = data["bodyweight"]
        else:
            # log_date has a global unique constraint, so another user may own this date
            existing_bw = BodyWeight.query.filter_by(log_date=d).first()
            if not existing_bw:
                db.session.add(BodyWeight(log_date=d, weight_lbs=data["bodyweight"], user_id=current_user.id))
    if "waist" in data:
        pa.waist_inches = data["waist"]
        d = date.today()
        bm = BodyMeasurement.query.filter_by(user_id=current_user.id, log_date=d).first()
        if bm:
            bm.waist_inches = data["waist"]
        else:
            existing_bm = BodyMeasurement.query.filter_by(log_date=d).first()
            if not existing_bm:
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
