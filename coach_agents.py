"""Agent definitions for the coaching system.

Each agent specifies max_tokens and temperature. The `requires` list is the
constant ALL_SECTIONS — every agent gets every section. Agent-specific
opting-out caused the 15.6h-fast hallucination (see audit 2026-04-30).
"""

ALL_SECTIONS = [
    "base", "checkins", "event_timeline", "recent_coach_directives",
    "workout_today", "workout_tomorrow", "week_schedule",
    "exercise_history", "exercise_analysis", "today_sets",
    "runs", "physical", "bodyweight", "garmin",
    "meals_today", "fasting", "food_safety", "goal",
    "coach_memories", "user_rules",
    "completed_days", "overrides", "next_week",
    "session_analysis", "missed_checkin", "intake", "supplements", "equipment",
]


AGENTS = {
    "conversation":      {"max_tokens": 800,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "morning_checkin":   {"max_tokens": 400,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "morning_briefing":  {"max_tokens": 300,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "weekly_planning":   {"max_tokens": 1500, "temperature": 0.6, "requires": ALL_SECTIONS},
    "weekly_review":     {"max_tokens": 1000, "temperature": 0.6, "requires": ALL_SECTIONS},
    "workout_feedback":  {"max_tokens": 800,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "run_complete":      {"max_tokens": 400,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "meals_complete":    {"max_tokens": 300,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "end_of_day":        {"max_tokens": 300,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "chat_opened":       {"max_tokens": 400,  "temperature": 0.6, "requires": ALL_SECTIONS},
    "crisis":            {"max_tokens": 300,  "temperature": 0.3, "requires": ALL_SECTIONS},
}
