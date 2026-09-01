"""Agent definitions for the coaching system.

Each agent specifies:
- max_tokens: Token limit for the Claude response
- temperature: Sampling temperature
- requires: List of context sections to fetch (see coach_assembler.py)

EVERY ATHLETE-FACING AGENT GETS EVERY SECTION (CORE_SECTIONS). This is the
2026-04-30 ALL_SECTIONS design (e9696a4: "agent-specific opting-out caused
the 15.6h-fast hallucination"), lost in the 2026-05-03 wholesale revert and
re-learned by hand five times since — 2026-08-28 being the worst: the chat
opener nagged for a weigh-in already logged, the reply agent said "I can't
pull Garmin" with last night's row in the DB, and it conceded REAL HRV
numbers were fabricated because it couldn't see what the morning agent saw.

A missing section is NOT a blank. The persona rules (chase the scale, never
hedge) turn it into a confident lie. Token cost is not a reason to blind the
coach. tests/test_core_sections_every_agent.py fails if any builder is added
without joining CORE, or any non-specialist agent drops a core section.

Only the four SPECIALIST_AGENTS keep narrow slices: crisis (deliberately
minimal) and the three consult-tool specialists, whose slices were tuned
against an eval (2026-05-05: widening nutritionist regressed 80% -> 57%).
"""

# Every registered @section_builder in coach_assembler.py except chat_history
# (which stays per-agent: popups don't carry the thread, chat does).
CORE_SECTIONS = [
    "base", "checkins", "today_status", "today_sets",
    "workout_today", "workout_tomorrow", "week_schedule", "next_week",
    "exercise_history", "exercise_analysis", "exercise_deltas", "lift_trend",
    "session_analysis", "runs", "physical", "equipment",
    "bodyweight", "garmin", "cut_status", "protocol_status", "goal",
    "meals_today", "fasting", "food_safety", "supplements",
    "coach_memories", "user_rules", "overrides", "completed_days",
    "missed_checkin", "intake", "marker_outcomes",
]

SPECIALIST_AGENTS = ("crisis", "nutritionist", "strength_coach", "running_coach")

_WITH_CHAT = ["chat_history"] + CORE_SECTIONS   # conversational moments
_NO_CHAT = list(CORE_SECTIONS)                   # one-shot popups

AGENTS = {
    "conversation": {
        "max_tokens": 800,
        "temperature": 0.6,
        "requires": _WITH_CHAT,

    },
    "morning_checkin": {
        "max_tokens": 300,
        "temperature": 0.6,
        "requires": _WITH_CHAT,

    },
    "morning_briefing": {
        "max_tokens": 200,
        "temperature": 0.6,
        "requires": _NO_CHAT,

    },
    "weekly_planning": {
        "max_tokens": 1500,
        "temperature": 0.6,
        "requires": _WITH_CHAT,

    },
    "weekly_review": {
        "max_tokens": 1000,
        "temperature": 0.6,  # was 1.0 and never sent (S096); a review must not be the loosest agent
        "requires": _WITH_CHAT,

    },
    "workout_feedback": {
        "max_tokens": 800,
        "temperature": 0.6,
        "requires": _WITH_CHAT,

    },
    "run_complete": {
        "max_tokens": 400,
        "temperature": 0.6,
        "requires": _WITH_CHAT,

    },
    "meals_complete": {
        "max_tokens": 200,
        "temperature": 0.6,
        "requires": _NO_CHAT,

    },
    "end_of_day": {
        "max_tokens": 200,
        "temperature": 0.6,
        "requires": _NO_CHAT,

    },
    "chat_opened": {
        "max_tokens": 300,
        "temperature": 0.6,
        "requires": _WITH_CHAT,

    },
    "crisis": {
        "max_tokens": 300,
        "temperature": 0.3,
        "requires": ["base", "chat_history"],
    },
    "nutritionist": {
        "max_tokens": 600,
        "temperature": 0.4,
        "requires": [
            "base", "goal", "cut_status", "protocol_status", "bodyweight",
            "meals_today", "weekly_meals", "food_safety",
            "fasting", "today_status", "lift_trend",
            # NOTE: workout_today + week_schedule were tried in round 5
            # to give the nutritionist visibility into today's prescribed
            # session. That regressed pass rate from 80% to 57% because
            # week_schedule pulls in the system's computed moderate-day
            # meal plan (1700 kcal / 145g protein), which is real but
            # not in the archetype description, so the judge flags it
            # as hallucination on every nutrition prompt. Better fix is
            # to expand ARCHETYPE_DESCRIPTIONS to include computed meal
            # numbers — left as future work.
        ],
    },
    "strength_coach": {
        "max_tokens": 600,
        "temperature": 0.4,
        "requires": [
            "base", "goal", "fasting", "today_status",
            "workout_today", "workout_tomorrow", "today_sets",
            "exercise_history", "exercise_analysis", "equipment",
            "session_analysis",
            # The dedicated lifting specialist agent — the recomp lift-decline
            # tripwire (Task 11) belongs here even more than the 4 cut-adjacent
            # agents above: this is the agent literally reasoning over
            # exercise_history/exercise_analysis/today_sets to judge lifting
            # performance, so it must see the codified decline signal rather
            # than eyeball a trend itself. running_coach (running-specific) and
            # workout_feedback/weekly_planning/weekly_review (general, not
            # strength-specific despite also requiring workout_today) are left
            # out — out of scope for this task, add explicitly if needed later.
            "lift_trend",
        ],
    },
    "running_coach": {
        "max_tokens": 600,
        "temperature": 0.4,
        "requires": [
            "base", "goal", "fasting", "today_status",
            "workout_today", "runs", "garmin",
            # week_schedule reverted alongside nutritionist — same
            # archetype-description-vs-computed-data mismatch risk.
        ],
    },
}
