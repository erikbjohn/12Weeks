"""SQLAlchemy models for all tracking data."""

from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ExerciseLog(db.Model):
    """Per-exercise weight/reps/RPE history."""
    __tablename__ = "exercise_log"
    id = db.Column(db.Integer, primary_key=True)
    exercise_name = db.Column(db.String(100), nullable=False, index=True)
    weight = db.Column(db.Float, nullable=False)
    sets_label = db.Column(db.String(50))
    rpe = db.Column(db.String(20))
    week = db.Column(db.Integer)
    day_idx = db.Column(db.Integer)
    logged_date = db.Column(db.Date, default=date.today)
    test_weight = db.Column(db.Float, nullable=True)
    test_reps = db.Column(db.Integer, nullable=True)
    estimated_1rm = db.Column(db.Float, nullable=True)


class ExerciseCompletion(db.Model):
    """Exercise-level completion checkbox."""
    __tablename__ = "exercise_completion"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    exercise_idx = db.Column(db.Integer, nullable=False)
    done = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("week", "day_idx", "exercise_idx"),)


class DayCompletion(db.Model):
    """Day-level completion."""
    __tablename__ = "day_completion"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False)
    day_idx = db.Column(db.Integer, nullable=False)
    done = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("week", "day_idx"),)


class MealLog(db.Model):
    """Daily meal tracking."""
    __tablename__ = "meal_log"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    eaten = db.Column(db.JSON, default=list)
    adjustments = db.Column(db.JSON, default=dict)
    fasting = db.Column(db.Boolean, default=False)


class AppState(db.Model):
    """Singleton app state."""
    __tablename__ = "app_state"
    id = db.Column(db.Integer, primary_key=True)
    current_week = db.Column(db.Integer, default=1)
    baseline_done = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.Date, nullable=True)
    traveling = db.Column(db.Boolean, default=False)


class BodyWeight(db.Model):
    """Morning weigh-ins."""
    __tablename__ = "body_weight"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    weight_lbs = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BodyMeasurement(db.Model):
    """Weekly body measurements."""
    __tablename__ = "body_measurement"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    waist_inches = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)


class ProgressPhoto(db.Model):
    """Weekly progress photos with AI analysis."""
    __tablename__ = "progress_photo"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    photo_data = db.Column(db.Text, nullable=False)  # base64 encoded
    pose = db.Column(db.String(50))  # "front", "side", "back"
    week = db.Column(db.Integer)
    analysis = db.Column(db.Text, nullable=True)  # AI analysis text
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class WeeklyCheckIn(db.Model):
    """Weekly subjective check-in."""
    __tablename__ = "weekly_checkin"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False, unique=True)
    energy_level = db.Column(db.Integer)
    sleep_quality = db.Column(db.Integer)
    soreness_level = db.Column(db.Integer)
    adherence_pct = db.Column(db.Integer)
    notes = db.Column(db.Text, nullable=True)
    check_in_date = db.Column(db.Date, default=date.today)


class SupplementLog(db.Model):
    """Daily supplement tracking."""
    __tablename__ = "supplement_log"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    supplement_name = db.Column(db.String(100), nullable=False)
    taken = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("log_date", "supplement_name"),)


class MorningCheckIn(db.Model):
    """Daily psychological check-in."""
    __tablename__ = "morning_checkin"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    sleep_quality = db.Column(db.Integer)       # 1-10
    stress_level = db.Column(db.Integer)        # 1-10
    soreness = db.Column(db.Integer)            # 1-10
    mood = db.Column(db.Integer)                # 0-10 (depressed to manic)
    motivation = db.Column(db.Integer)          # 1-10
    anxiety = db.Column(db.Integer)             # 1-10
    notes = db.Column(db.Text, nullable=True)   # free text "anything on your mind?"
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class PsychIntake(db.Model):
    """Baseline psychological intake data."""
    __tablename__ = "psych_intake"
    id = db.Column(db.Integer, primary_key=True)
    conversation = db.Column(db.JSON, default=list)  # [{role, content}]
    report = db.Column(db.Text, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    locked_until = db.Column(db.Date, nullable=True)  # locked out until this date
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class GarminTokens(db.Model):
    """Stored Garmin auth tokens to avoid re-login."""
    __tablename__ = "garmin_tokens"
    id = db.Column(db.Integer, primary_key=True)
    token_data = db.Column(db.Text, nullable=False)  # garth token dump
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now())


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
    pushup_count = db.Column(db.Integer, nullable=True)  # full pushups
    pushup_from_knees = db.Column(db.Boolean, default=False)
    plank_seconds = db.Column(db.Integer, nullable=True)
    squat_count = db.Column(db.Integer, nullable=True)  # bodyweight squats
    lunge_count_per_leg = db.Column(db.Integer, nullable=True)
    pullup_count = db.Column(db.Integer, nullable=True)  # 0 if can't
    # Gym baseline (for gym users) stored in ExerciseLog, just flag here
    gym_baseline_done = db.Column(db.Boolean, default=False)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class UserConstraints(db.Model):
    """User dietary and schedule constraints."""
    __tablename__ = "user_constraints"
    id = db.Column(db.Integer, primary_key=True)
    food_restrictions = db.Column(db.JSON, default=list)
    custom_allergies = db.Column(db.Text, nullable=True)
    scheduled_activities = db.Column(db.JSON, default=list)
    schedule_notes = db.Column(db.Text, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


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
    phase_plan = db.Column(db.JSON, nullable=True)
    calorie_by_day_type = db.Column(db.JSON, nullable=True)
    fasting_protocol = db.Column(db.String(20), nullable=True)
    electrolyte_supplementation = db.Column(db.Boolean, default=False)
    weight_projection = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class UserFoodSelections(db.Model):
    """User's chosen foods for the 12-week program."""
    __tablename__ = "user_food_selections"
    id = db.Column(db.Integer, primary_key=True)
    selected_foods = db.Column(db.JSON, default=dict)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class WeeklyReport(db.Model):
    """Sunday weekly progress report."""
    __tablename__ = "weekly_report"
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.Integer, nullable=False, unique=True)
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())


class ChatMessage(db.Model):
    """AI coach conversation history."""
    __tablename__ = "chat_message"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # "user" or "assistant"
    content = db.Column(db.Text, nullable=False)
    log_date = db.Column(db.Date, default=date.today, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())
