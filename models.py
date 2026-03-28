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
