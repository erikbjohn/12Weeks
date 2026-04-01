"""Compliance scoring engine for 12 Weeks."""

from datetime import date, datetime, timedelta
from models import db, MorningCheckIn, MealLog, DayCompletion, SetLog, ComplianceScore
import math


def compute_compliance_score(user_id):
    """Compute weighted compliance score from all tracking data.

    Point values per event:
    - Morning checkin completed: +5
    - Morning checkin missed: -10
    - Food logged on time (within 60 min): +10
    - Food logged late (61-120 min): -10
    - Food logged very late (120+ min): -15
    - Scheduled meal not logged: -15
    - Workout completed on time: +10
    - Workout completed late (61-120 min): -8
    - Workout missed: -20

    Time decay: 0.85^(days_ago / 7)
    """
    today = date.today()

    # Get user's start date for program length
    from models import AppState
    state = AppState.query.filter_by(user_id=user_id).first()
    if not state or not state.start_date:
        return {"score": 50, "grade": "B", "breakdown": {}, "streak": 0}

    start = state.start_date
    program_days = (today - start).days + 1
    if program_days <= 0:
        return {"score": 100, "grade": "A+", "breakdown": {}, "streak": 0}

    # Cap at 84 days (12 weeks)
    lookback = min(program_days, 84)
    since = today - timedelta(days=lookback)

    # Fetch data
    checkins = MorningCheckIn.query.filter(
        MorningCheckIn.user_id == user_id,
        MorningCheckIn.log_date >= since
    ).all()
    checkin_dates = {c.log_date: c for c in checkins}

    meals = MealLog.query.filter(
        MealLog.user_id == user_id,
        MealLog.log_date >= since
    ).all()
    meal_dates = {m.log_date: m for m in meals}

    completions = DayCompletion.query.filter(
        DayCompletion.user_id == user_id,
        DayCompletion.done == True
    ).all()
    completed_days = set()
    for dc in completions:
        # Convert week/day_idx to actual date
        if state.start_date:
            d = state.start_date + timedelta(days=(dc.week - 1) * 7 + dc.day_idx)
            if d >= since:
                completed_days.add(d)

    # Calculate daily scores
    total_decayed = 0
    max_possible_decayed = 0
    checkin_points = 0
    food_points = 0
    workout_points = 0
    checkin_max = 0
    food_max = 0
    workout_max = 0
    streak = 0
    current_streak = 0

    for days_ago in range(lookback):
        d = today - timedelta(days=days_ago)
        if d < start:
            break

        decay = 0.85 ** (days_ago / 7)
        day_points = 0
        day_max = 0

        # Day of week (0=Mon)
        dow = d.weekday()
        is_sunday = dow == 6

        # Morning checkin: +5 done, -10 missed
        day_max += 5
        checkin_max += 5
        if d in checkin_dates:
            c = checkin_dates[d]
            if hasattr(c, 'missed') and c.missed:
                day_points -= 10
                checkin_points -= 10
            else:
                day_points += 5
                checkin_points += 5
        elif d < today:  # Past days without checkin = missed
            day_points -= 10
            checkin_points -= 10

        # Meals: 3 meals per day (simplified), +10 each if logged
        if not is_sunday:  # Sunday is fast day
            meals_expected = 3
            day_max += meals_expected * 10
            food_max += meals_expected * 10
            if d in meal_dates:
                ml = meal_dates[d]
                eaten = ml.eaten if isinstance(ml.eaten, list) else []
                meals_logged = len(eaten)
                food_points += meals_logged * 10
                day_points += meals_logged * 10
                missed_meals = meals_expected - meals_logged
                if missed_meals > 0:
                    day_points -= missed_meals * 15
                    food_points -= missed_meals * 15
            elif d < today:
                day_points -= meals_expected * 15
                food_points -= meals_expected * 15

        # Workout: +10 if completed, -20 if missed (skip Sunday)
        if not is_sunday:
            day_max += 10
            workout_max += 10
            if d in completed_days:
                day_points += 10
                workout_points += 10
            elif d < today:
                day_points -= 20
                workout_points -= 20

        total_decayed += day_points * decay
        max_possible_decayed += day_max * decay

        # Streak tracking
        if d < today:
            if d in checkin_dates and (d in meal_dates or is_sunday) and (d in completed_days or is_sunday):
                current_streak += 1
            else:
                if current_streak > streak:
                    streak = current_streak
                current_streak = 0

    if current_streak > streak:
        streak = current_streak

    # Normalize to 0-100
    if max_possible_decayed > 0:
        score = max(0, min(100, 50 + (total_decayed / max_possible_decayed) * 50))
    else:
        score = 50

    # Grade thresholds
    grade = _score_to_grade(score)

    # Breakdown percentages
    breakdown = {
        "checkins": round(max(0, min(100, 50 + (checkin_points / max(checkin_max, 1)) * 50))),
        "food_timing": round(max(0, min(100, 50 + (food_points / max(food_max, 1)) * 50))),
        "workout_timing": round(max(0, min(100, 50 + (workout_points / max(workout_max, 1)) * 50))),
    }

    # Upsert ComplianceScore
    cs = ComplianceScore.query.filter_by(user_id=user_id).first()
    if not cs:
        cs = ComplianceScore(user_id=user_id)
        db.session.add(cs)
    cs.computed_at = datetime.now()
    cs.raw_score = round(total_decayed, 1)
    cs.weighted_score = round(score, 1)
    cs.letter_grade = grade
    cs.breakdown = breakdown
    cs.streak_days = streak
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return {
        "score": round(score, 1),
        "grade": grade,
        "breakdown": breakdown,
        "streak": streak,
    }


def _score_to_grade(score):
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 45: return "D"
    return "F"


def get_improvement_tip(grade, breakdown):
    """Generate a plain-language tip for improving the grade."""
    if grade.startswith("A"):
        return "Keep it up. Consistency is the standard."

    # Find weakest category
    weakest = min(breakdown, key=breakdown.get)
    weakest_score = breakdown[weakest]

    tips = {
        "checkins": "Complete your morning check-in every day to improve.",
        "food_timing": "Log all your meals on time to improve.",
        "workout_timing": "Show up for every workout to improve.",
    }

    next_grade = _next_grade_up(grade)
    return f"{tips.get(weakest, 'Stay consistent.')} Target: {next_grade}."


def _next_grade_up(grade):
    order = ["F", "D", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
    idx = order.index(grade) if grade in order else 0
    return order[min(idx + 1, len(order) - 1)]
