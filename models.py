"""SQLAlchemy models for all tracking data."""

from datetime import date, datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    password_hash = db.Column(db.Text)
    google_id = db.Column(db.String(255), unique=True, nullable=True)
    role = db.Column(db.String(20), default="user", nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    avatar_url = db.Column(db.Text, nullable=True)
    invites_remaining = db.Column(db.Integer, default=0, nullable=False)
    invited_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    timezone = db.Column(db.String(64), default='UTC')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_admin(self):
        return self.role == "admin"


class Invite(db.Model):
    __tablename__ = "invite"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    used_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    email_sent_to = db.Column(db.String(255), nullable=True)
    multi_use = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    used_at = db.Column(db.DateTime, nullable=True)


class CoachMemory(db.Model):
    """Rolling memory for the AI coach — persists across conversations.
    Stores key observations, commitments, injury notes, and athlete patterns
    that must survive beyond the 20-message chat window."""
    __tablename__ = "coach_memory"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)  # The summary text
    memory_type = db.Column(db.String(30), default="summary")  # summary, commitment, injury, observation
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    week = db.Column(db.Integer)  # Which week this was recorded


class CoachRule(db.Model):
    """Per-user coaching rules — persistent directives that override default coach behavior.
    Created when user corrects the coach or manually adds a rule via /rule command."""
    __tablename__ = "coach_rule"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    rule_text = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(30), default="correction")
    source = db.Column(db.String(20), default="auto")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ComplianceState(db.Model):
    """Running compliance state for anger level and coaching tone adaptation.
    One row per user, upserted by the state machine after each interaction."""
    __tablename__ = "compliance_state"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True, index=True)
    anger_level = db.Column(db.Integer, default=0)  # 0=baseline, 1=warning, 2=stern, 3=lombardi
    consecutive_misses = db.Column(db.Integer, default=0)
    last_miss_date = db.Column(db.Date, nullable=True)
    last_escalation_date = db.Column(db.Date, nullable=True)
    last_deescalation_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class MuscleGroupProfile(db.Model):
    """Per-muscle-group strength tracking."""
    __tablename__ = "muscle_group_profile"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    muscle_group = db.Column(db.String(30), nullable=False)
    strength_score = db.Column(db.Float, default=1.0)
    relative_strength = db.Column(db.String(15), default='average')
    user_flagged_weak = db.Column(db.Boolean, default=False)
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class SessionAnalysis(db.Model):
    """Post-session analysis for coach and progression."""
    __tablename__ = "session_analysis"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer)
    day_idx = db.Column(db.Integer)
    log_date = db.Column(db.Date, default=date.today)
    overall_compliance = db.Column(db.Float)
    muscle_groups_trained = db.Column(db.JSON, default=list)
    deviations = db.Column(db.JSON, default=list)
    progression_applied = db.Column(db.JSON, default=list)
    flags = db.Column(db.JSON, default=list)
    summary_text = db.Column(db.Text)


class ExerciseLog(db.Model):
    """Per-exercise weight/reps/RPE history."""
    __tablename__ = "exercise_log"
    id = db.Column(db.Integer, primary_key=True)
    exercise_name = db.Column(db.String(100), nullable=False, index=True)
    weight = db.Column(db.Float, nullable=False)
    sets_label = db.Column(db.String(50))
    rpe = db.Column(db.String(20))  # legacy: "too_easy", "just_right", "too_hard"
    rpe_score = db.Column(db.Integer, nullable=True)  # 1-10 RPE scale
    reps_completed = db.Column(db.Integer, nullable=True)  # actual reps done (vs prescribed)
    difficulty_notes = db.Column(db.Text, nullable=True)  # optional free text
    week = db.Column(db.Integer)
    day_idx = db.Column(db.Integer)
    logged_date = db.Column(db.Date, default=date.today)
    test_weight = db.Column(db.Float, nullable=True)
    test_reps = db.Column(db.Integer, nullable=True)
    estimated_1rm = db.Column(db.Float, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)


class SetLog(db.Model):
    """Per-set weight/reps tracking — one row per set per exercise per day."""
    __tablename__ = "set_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    exercise_name = db.Column(db.String(100), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    set_number = db.Column(db.Integer, nullable=False)  # 0-indexed
    weight = db.Column(db.Float, default=0)
    reps = db.Column(db.Integer, default=0)
    done = db.Column(db.Boolean, default=False)
    logged_date = db.Column(db.Date, default=date.today)
    target_weight = db.Column(db.Float)
    target_reps = db.Column(db.Integer)
    user_modified = db.Column(db.Boolean, default=False)
    modification_direction = db.Column(db.String(30))
    exercise_swapped = db.Column(db.Boolean, default=False)
    actual_time = db.Column(db.String(30), nullable=True)
    target_rpe = db.Column(db.Integer, nullable=True)
    set_skipped = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("user_id", "exercise_name", "week", "day_idx", "set_number"),)


class ExerciseSwap(db.Model):
    """Persisted exercise swaps — survives across sessions."""
    __tablename__ = "exercise_swap"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    exercise_idx = db.Column(db.Integer, nullable=False)
    swapped_to = db.Column(db.String(100), nullable=False)
    # Snapshot of the original exercise the user was looking at when they made the swap.
    # Without this, swaps survive phase boundaries by index alone — e.g. a Lying Leg Curl
    # swap from week 4 carries to week 5 where index 6 now points at Hammer Curl.
    # Nullable so legacy rows persist; validation falls back to recomputing from the plan.
    original_name = db.Column(db.String(120), nullable=True)


class ExerciseCompletion(db.Model):
    """Exercise-level completion checkbox."""
    __tablename__ = "exercise_completion"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    exercise_idx = db.Column(db.Integer, nullable=False)
    done = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    __table_args__ = (db.UniqueConstraint("user_id", "week", "day_idx", "exercise_idx"),)


class WarmupCompletion(db.Model):
    __tablename__ = "warmup_completion"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    step_idx = db.Column(db.Integer, nullable=False)
    done = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("user_id", "week", "day_idx", "step_idx"),)


class RunLog(db.Model):
    __tablename__ = "run_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    log_date = db.Column(db.Date, default=date.today)
    week = db.Column(db.Integer)
    day_idx = db.Column(db.Integer)
    distance_miles = db.Column(db.Float)
    avg_hr = db.Column(db.Integer)
    elevation_ft = db.Column(db.Integer)
    duration_min = db.Column(db.Integer)
    notes = db.Column(db.Text)
    __table_args__ = (db.UniqueConstraint("user_id", "week", "day_idx"),)


class DayCompletion(db.Model):
    """Day-level completion."""
    __tablename__ = "day_completion"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    done = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    workout_started_at = db.Column(db.Text, nullable=True)
    workout_ended_at = db.Column(db.Text, nullable=True)
    workout_duration_min = db.Column(db.Integer, nullable=True)
    __table_args__ = (db.UniqueConstraint("user_id", "week", "day_idx"),)


class MealLog(db.Model):
    """Daily meal tracking."""
    __tablename__ = "meal_log"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    eaten = db.Column(db.JSON, default=list)
    adjustments = db.Column(db.JSON, default=dict)
    food_items = db.Column(db.JSON, default=list)  # Individual food checkboxes
    scheduled_time = db.Column(db.Text, nullable=True)  # Per-meal timing JSON
    actual_time = db.Column(db.Text, nullable=True)
    fasting = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint("user_id", "log_date"),)


class AppState(db.Model):
    """Singleton app state."""
    __tablename__ = "app_state"
    id = db.Column(db.Integer, primary_key=True)
    current_week = db.Column(db.Integer, default=1)
    baseline_done = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.Date, nullable=True)
    traveling = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)


class BodyWeight(db.Model):
    """Morning weigh-ins."""
    __tablename__ = "body_weight"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    weight_lbs = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)


class BodyMeasurement(db.Model):
    """Weekly body measurements."""
    __tablename__ = "body_measurement"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    weight_lbs = db.Column(db.Float, nullable=True)
    waist_inches = db.Column(db.Float, nullable=True)
    chest = db.Column(db.Float, nullable=True)
    bicep_left = db.Column(db.Float, nullable=True)
    bicep_right = db.Column(db.Float, nullable=True)
    thigh_left = db.Column(db.Float, nullable=True)
    thigh_right = db.Column(db.Float, nullable=True)
    hips = db.Column(db.Float, nullable=True)
    neck = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)


class ProgressPhoto(db.Model):
    """Weekly progress photos with AI analysis."""
    __tablename__ = "progress_photo"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    photo_data = db.Column(db.Text, nullable=False)  # base64 encoded
    pose = db.Column(db.String(50))  # "front", "side", "back"
    week = db.Column(db.Integer)
    analysis = db.Column(db.Text, nullable=True)  # AI analysis text
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class WeeklyCheckIn(db.Model):
    """Weekly subjective check-in."""
    __tablename__ = "weekly_checkin"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False)
    energy_level = db.Column(db.Integer)
    sleep_quality = db.Column(db.Integer)
    soreness_level = db.Column(db.Integer)
    adherence_pct = db.Column(db.Integer)
    notes = db.Column(db.Text, nullable=True)
    check_in_date = db.Column(db.Date, default=date.today)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint("user_id", "week"),)


class SupplementLog(db.Model):
    """Daily supplement tracking."""
    __tablename__ = "supplement_log"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    supplement_name = db.Column(db.String(100), nullable=False)
    taken = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    __table_args__ = (db.UniqueConstraint("user_id", "log_date", "supplement_name"),)


class MorningCheckIn(db.Model):
    """Daily psychological check-in."""
    __tablename__ = "morning_checkin"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    sleep_quality = db.Column(db.Integer)       # 1-10
    stress_level = db.Column(db.Integer)        # 1-10
    soreness = db.Column(db.Integer)            # 1-10
    mood = db.Column(db.Integer)                # 0-10 (depressed to manic)
    motivation = db.Column(db.Integer)          # 1-10
    anxiety = db.Column(db.Integer)             # 1-10
    notes = db.Column(db.Text, nullable=True)   # free text "anything on your mind?"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("user_id", "log_date"),)


class PsychIntake(db.Model):
    """Baseline psychological intake data."""
    __tablename__ = "psych_intake"
    id = db.Column(db.Integer, primary_key=True)
    conversation = db.Column(db.JSON, default=list)  # [{role, content}]
    report = db.Column(db.Text, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    locked_until = db.Column(db.Date, nullable=True)  # locked out until this date
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class GarminTokens(db.Model):
    """Stored Garmin auth tokens to avoid re-login."""
    __tablename__ = "garmin_tokens"
    id = db.Column(db.Integer, primary_key=True)
    token_data = db.Column(db.Text, nullable=False)  # garth token dump
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)


class PhysicalAssessment(db.Model):
    """Baseline physical assessment data (gym or bodyweight)."""
    __tablename__ = "physical_assessment"
    id = db.Column(db.Integer, primary_key=True)
    has_gym = db.Column(db.Boolean, default=True)
    has_measuring_tape = db.Column(db.Boolean, default=False)
    height_inches = db.Column(db.Float, nullable=True)
    bodyweight_lbs = db.Column(db.Float, nullable=True)
    waist_inches = db.Column(db.Float, nullable=True)
    stomach_inches = db.Column(db.Float, nullable=True)
    chest_inches = db.Column(db.Float, nullable=True)
    bicep_inches = db.Column(db.Float, nullable=True)
    thigh_inches = db.Column(db.Float, nullable=True)
    hips_inches = db.Column(db.Float, nullable=True)
    neck_inches = db.Column(db.Float, nullable=True)
    # Bodyweight assessment (for no-gym users)
    pushup_count = db.Column(db.Integer, nullable=True)  # 60-second count
    pushup_from_knees = db.Column(db.Boolean, default=False)
    plank_seconds = db.Column(db.Integer, nullable=True)  # max hold
    squat_count = db.Column(db.Integer, nullable=True)  # air squats in 60s
    burpee_count = db.Column(db.Integer, nullable=True)  # 60-second count
    lunge_count_per_leg = db.Column(db.Integer, nullable=True)  # legacy, no longer collected
    pullup_count = db.Column(db.Integer, nullable=True)  # legacy, no longer collected
    # Gym baseline (for gym users) stored in ExerciseLog, just flag here
    gym_baseline_done = db.Column(db.Boolean, default=False)
    actual_bmr = db.Column(db.Float)  # Computed from actual weight loss data, overrides Mifflin-St Jeor
    completed = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class BodyweightRetest(db.Model):
    """Periodic bodyweight assessment retests (week 6, week 12) — compared against PhysicalAssessment baseline."""
    __tablename__ = "bodyweight_retest"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week_number = db.Column(db.Integer, nullable=False)  # 6 or 12
    squat_count = db.Column(db.Integer, nullable=True)  # air squats in 60s
    pushup_count = db.Column(db.Integer, nullable=True)  # 60-second count
    pushup_from_knees = db.Column(db.Boolean, default=False)
    burpee_count = db.Column(db.Integer, nullable=True)  # 60-second count
    plank_seconds = db.Column(db.Integer, nullable=True)  # max hold
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.Index("ix_bwretest_user_week", "user_id", "week_number", unique=True),)


class UserEquipment(db.Model):
    """User's available gym equipment."""
    __tablename__ = "user_equipment"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    available_equipment = db.Column(db.JSON, default=list)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class UserConstraints(db.Model):
    """User dietary and schedule constraints."""
    __tablename__ = "user_constraints"
    id = db.Column(db.Integer, primary_key=True)
    food_restrictions = db.Column(db.JSON, default=list)
    custom_allergies = db.Column(db.Text, nullable=True)
    scheduled_activities = db.Column(db.JSON, default=list)
    schedule_notes = db.Column(db.Text, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class TrainingGoal(db.Model):
    """Computed training goal — calories, macros, projections."""
    __tablename__ = "training_goal"
    id = db.Column(db.Integer, primary_key=True)
    goal_type = db.Column(db.String(20), nullable=False)  # "cut", "bulk", "recomp"
    target_weight = db.Column(db.Float, nullable=True)
    target_bf_pct = db.Column(db.Float, nullable=True)
    daily_calories = db.Column(db.Integer, nullable=True)
    protein_grams = db.Column(db.Integer, nullable=True)
    carb_grams = db.Column(db.Integer, nullable=True)
    fat_grams = db.Column(db.Integer, nullable=True)
    tdee = db.Column(db.Integer, nullable=True)
    phase_plan = db.Column(db.JSON, nullable=True)
    calorie_by_day_type = db.Column(db.JSON, nullable=True)
    fasting_protocol = db.Column(db.String(20), nullable=True)
    electrolyte_supplementation = db.Column(db.Boolean, default=False)
    weight_projection = db.Column(db.JSON, nullable=True)
    plan_accepted = db.Column(db.Boolean, default=False)
    baseline_assessment = db.Column(db.JSON, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class UserFoodSelections(db.Model):
    """User's chosen foods for the 12-week program."""
    __tablename__ = "user_food_selections"
    id = db.Column(db.Integer, primary_key=True)
    selected_foods = db.Column(db.JSON, default=dict)
    completed = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class WeeklyReport(db.Model):
    """Sunday weekly progress report."""
    __tablename__ = "weekly_report"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False)
    report_date = db.Column(db.Date, nullable=False)
    workouts_completed = db.Column(db.Integer, default=0)
    workouts_total = db.Column(db.Integer, default=6)
    weight_start = db.Column(db.Float, nullable=True)
    weight_end = db.Column(db.Float, nullable=True)
    weight_trend = db.Column(db.String(10))
    weight_vs_projected = db.Column(db.String(10))  # "ahead", "on_track", "behind"
    key_lifts_summary = db.Column(db.JSON, nullable=True)
    checkin_avg = db.Column(db.JSON, nullable=True)
    adherence_pct = db.Column(db.Float, nullable=True)
    narrative = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("user_id", "week"),)


class ChatMessage(db.Model):
    """AI coach conversation history."""
    __tablename__ = "chat_message"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # "user" or "assistant"
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(30), default='chat')  # chat, morning_opener, checkin_response, workout_nudge, post_workout, scold
    log_date = db.Column(db.Date, default=date.today, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class DailyCoachState(db.Model):
    """Per-user per-day coach state tracking."""
    __tablename__ = "daily_coach_state"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    state_date = db.Column(db.Date, nullable=False, default=date.today)
    opener_shown_at = db.Column(db.DateTime, nullable=True)
    opener_dismissed_at = db.Column(db.DateTime, nullable=True)
    checkin_completed_at = db.Column(db.DateTime, nullable=True)
    nudge_sent_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'state_date'),)


class WeeklyScheduleOverride(db.Model):
    """Coach-set schedule overrides per day (e.g., workout at 3pm instead of 6am)."""
    __tablename__ = "weekly_schedule_override"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    workout_time = db.Column(db.String(20))
    skip_day = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MealPlanOverride(db.Model):
    """Coach-set meal plan overrides (e.g., fast day on Saturday)."""
    __tablename__ = "meal_plan_override"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    meal_type = db.Column(db.String(30))
    daily_calories = db.Column(db.Integer)
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RunOverride(db.Model):
    """Coach-set run overrides (e.g., longer duration, tempo swap)."""
    __tablename__ = "run_override"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.String(20))
    run_type = db.Column(db.String(20))
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Exercise(db.Model):
    """Canonical exercise catalog — one row per unique physical movement."""
    __tablename__ = "exercise"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    muscle_group = db.Column(db.String(30))
    category = db.Column(db.String(20))  # compound / isolation / core / power
    equipment = db.Column(db.JSON, default=list)
    video_cue = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WeeklyPrescription(db.Model):
    """Per-user, per-week exercise programming. Populated by template or coach."""
    __tablename__ = "weekly_prescription"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    exercise_order = db.Column(db.Integer, nullable=False)
    exercise_name = db.Column(db.String(100), nullable=False)
    sets = db.Column(db.Integer, nullable=False)
    reps = db.Column(db.String(20), nullable=False)
    rest = db.Column(db.String(20))
    target_weight = db.Column(db.Float, nullable=True)
    progression_indicator = db.Column(db.String(20), nullable=True)
    adjustment_reason = db.Column(db.Text, nullable=True)
    note = db.Column(db.Text)
    source = db.Column(db.String(20), default='template')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WeeklyMealPlan(db.Model):
    """Per-user, per-week, per-day meal plans. Generated by meal_generator."""
    __tablename__ = "weekly_meal_plan"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    meal_data = db.Column(db.JSON, nullable=False)
    daily_calories = db.Column(db.Integer)
    daily_protein = db.Column(db.Integer)
    day_type = db.Column(db.String(20))
    source = db.Column(db.String(20), default='generator')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WeeklyRunPlan(db.Model):
    """Per-user, per-week, per-day run plans. Generated by run progression engine."""
    __tablename__ = "weekly_run_plan"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    run_type = db.Column(db.String(20))  # z2, tempo, hiit, long, easy, min
    label = db.Column(db.String(30))  # "Zone 2", "Tempo", "HIIT", "Long"
    duration = db.Column(db.String(20))  # "45 min", "30 min"
    detail = db.Column(db.Text)  # Full coaching cue
    source = db.Column(db.String(20), default='engine')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WeeklyWarmup(db.Model):
    """Per-user, per-week, per-day warmups. Built from day exercises + soreness."""
    __tablename__ = "weekly_warmup"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    warmup_data = db.Column(db.JSON)  # Same shape as WARMUPS entries
    source = db.Column(db.String(20), default='engine')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WeeklyDaySchedule(db.Model):
    """Per-user, per-week day schedule — which muscle groups on which days."""
    __tablename__ = "weekly_day_schedule"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    lift_name = db.Column(db.String(100))  # "Upper A - Chest & Back"
    muscle_groups = db.Column(db.JSON, default=list)  # ["chest", "back", "triceps"]
    is_rest = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(20), default='engine')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
