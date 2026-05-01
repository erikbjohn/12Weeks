"""Agent definitions for the coaching system.

Each agent specifies:
- max_tokens: Token limit for the Claude response
- temperature: Sampling temperature
- requires: List of context sections to fetch (see coach_assembler.py)
"""

AGENTS = {
    "conversation": {
        "max_tokens": 800,
        "temperature": 0.6,
        "requires": [
            "base", "checkins", "chat_history", "workout_today", "workout_tomorrow",
            "week_schedule", "meals_today", "bodyweight", "coach_memories", "goal",
            "food_safety", "fasting", "user_rules",
            "today_sets", "completed_days", "overrides",
        ],
    },
    "morning_checkin": {
        "max_tokens": 300,
        "temperature": 0.6,
        "requires": [
            "base", "checkins", "chat_history", "workout_today", "workout_tomorrow",
            "week_schedule", "bodyweight", "garmin", "coach_memories", "missed_checkin",
            "food_safety", "fasting", "user_rules",
        ],
    },
    "morning_briefing": {
        "max_tokens": 200,
        "temperature": 0.6,
        "requires": [
            "base", "checkins", "workout_today", "garmin",
            "fasting", "user_rules",
        ],
    },
    "weekly_planning": {
        "max_tokens": 1500,
        "temperature": 0.6,
        "requires": [
            "base", "checkins", "chat_history", "bodyweight", "workout_today",
            "week_schedule", "exercise_history", "exercise_analysis",
            "today_sets", "runs", "physical", "meals_today",
            "coach_memories", "goal", "food_safety", "fasting",
            "completed_days", "overrides", "next_week",
            "session_analysis", "equipment", "user_rules",
        ],
    },
    "weekly_review": {
        "max_tokens": 1000,
        "temperature": 1.0,
        "requires": [
            "base", "checkins", "chat_history", "bodyweight", "workout_today",
            "week_schedule", "exercise_history", "runs", "physical",
            "meals_today", "coach_memories", "goal", "food_safety",
            "completed_days", "session_analysis", "user_rules",
        ],
    },
    "workout_feedback": {
        "max_tokens": 800,
        "temperature": 0.6,
        "requires": [
            "base", "chat_history", "workout_today", "today_sets",
            "exercise_history", "exercise_analysis",
            "week_schedule", "next_week", "coach_memories",
            "fasting", "user_rules",
        ],
    },
    "run_complete": {
        "max_tokens": 400,
        "temperature": 0.6,
        "requires": [
            "base", "chat_history", "workout_today", "runs",
            "coach_memories", "fasting", "user_rules",
        ],
    },
    "meals_complete": {
        "max_tokens": 200,
        "temperature": 0.6,
        "requires": [
            "base", "meals_today", "goal", "food_safety",
            "fasting", "user_rules",
        ],
    },
    "end_of_day": {
        "max_tokens": 200,
        "temperature": 0.6,
        "requires": [
            "base", "workout_today", "week_schedule", "completed_days",
            "next_week", "fasting", "user_rules",
        ],
    },
    "chat_opened": {
        "max_tokens": 300,
        "temperature": 0.6,
        "requires": [
            "base", "checkins", "chat_history", "workout_today",
            "meals_today", "completed_days", "coach_memories",
            "fasting", "user_rules",
            "today_sets", "overrides",
        ],
    },
    "crisis": {
        "max_tokens": 300,
        "temperature": 0.3,
        "requires": ["base", "chat_history"],
    },
}
