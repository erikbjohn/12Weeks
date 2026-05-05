"""Prompt corpus. Add cases freely — harness loops over `ALL_PROMPTS`."""
from __future__ import annotations
from .types import PromptCase


_smoke = [
    PromptCase(
        id="smoke_001", category="smoke",
        user_message="ping",
        user_fixture="phase_2_mid_program",
        expected_behavior=["pong"],
        must_not=["ERROR"],
        focus_dimensions=["accuracy"],
    ),
]

_cross_day = [
    PromptCase(
        id="cross_day_001", category="cross_day_hallucination",
        user_message="What lift is on Monday this week and what's the scheme?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["front squat", "4x3"],
        must_not=["back squat 4x5", "back squat 5x5"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="cross_day_002", category="cross_day_hallucination",
        user_message="Tell me Friday's lift, sets, and reps.",
        user_fixture="phase_2_mid_program",
        expected_behavior=["back squat", "4x5"],
        must_not=["front squat 4x3", "deadlift"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="cross_day_003", category="cross_day_hallucination",
        user_message="What am I doing Thursday?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["pull"],
        must_not=["squat"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="cross_day_004", category="cross_day_hallucination",
        user_message="Walk me through the whole week.",
        user_fixture="phase_2_mid_program",
        expected_behavior=["monday", "tuesday", "wednesday", "thursday", "friday"],
        must_not=["bench press monday", "deadlift"],
        focus_dimensions=["accuracy"],
    ),
]

_banned_phrases = [
    PromptCase(
        id="banned_001", category="banned_phrases",
        user_message="I'm tired today.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great work", "let's get after it", "you've got this", "what's on your mind"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="banned_002", category="banned_phrases",
        user_message="Just finished my squats.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great work", "crushing it", "keep grinding", "done. tomorrow:"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="banned_003", category="banned_phrases",
        user_message="Hi.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["what's on your mind", "speak."],
        focus_dimensions=["tone"],
    ),
]

_schedule_leak = [
    PromptCase(
        id="schedule_001", category="schedule_leak",
        user_message="What's the plan today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["<schedule>", "</schedule>", "<directive>"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="schedule_002", category="schedule_leak",
        user_message="Give me my full week schedule.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["<schedule>", "</schedule>"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="schedule_003", category="schedule_leak",
        user_message="When is my next workout?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["<schedule>", "<directive>", "<motivation>"],
        focus_dimensions=["tone"],
    ),
]

_session_status = [
    PromptCase(
        id="session_001", category="session_status",
        user_message="Should I lift now?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="session_002", category="session_status",
        user_message="What's left for me to do today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="session_003", category="session_status",
        user_message="Did I finish my workout already?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_swap_logic = [
    PromptCase(
        id="swap_001", category="swap_logic",
        user_message="Bench is taken, give me a substitute.",
        user_fixture="phase_2_mid_program",
        expected_behavior=["dumbbell"],
        must_not=["barbell bench"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="swap_002", category="swap_logic",
        user_message="No barbell today. What can I do for squats?",
        user_fixture="phase_2_mid_program",
        # Coach legitimately mentions "barbell" in the swap-reason marker and
        # when describing what to swap OUT of. The real bug to catch would be
        # PRESCRIBING a barbell movement as the substitute. Judge handles the
        # semantic "did it actually propose a non-barbell alt" check.
        expected_behavior=[],
        must_not=["barbell back squat 4x", "barbell front squat 4x"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="swap_003", category="swap_logic",
        user_message="Swap front squat for something easier on my knees.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["front squat"],
        focus_dimensions=["accuracy"],
    ),
]

_progression = [
    PromptCase(
        id="prog_001", category="progression_citation",
        # Was "...today?" but Monday isn't bench day; coach correctly redirected
        # which made the test fail on a false positive. Reword as a historical
        # question so the day-context doesn't matter.
        user_message="What did I hit on my last bench session?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["75", "72"],   # last DB bench peak in fixture
        must_not=["315", "405"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="prog_002", category="progression_citation",
        user_message="What did I hit last front squat session?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["170"],
        must_not=["315"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="prog_003", category="progression_citation",
        user_message="What's my next bench target?",
        user_fixture="phase_3_cut",
        expected_behavior=[],
        must_not=["205"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
]

_run_pacing = [
    PromptCase(
        id="run_001", category="run_pacing",
        user_message="What's the run today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_002", category="run_pacing",
        user_message="How long is my Sunday run?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_003", category="run_pacing",
        user_message="Tempo run pace target?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_deload = [
    PromptCase(
        id="deload_001", category="deload_handling",
        user_message="What's this week's stress level?",
        user_fixture="phase_3_cut",
        expected_behavior=[],
        must_not=["push for PR", "personal record"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="deload_002", category="deload_handling",
        user_message="Should I PR today?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["yes"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="deload_003", category="deload_handling",
        user_message="I want to add weight every set.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_psych = [
    PromptCase(
        id="psych_001", category="psych_intake_resume",
        user_message="My job is super stressful and I'm not sleeping.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great work", "you've got this"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="psych_002", category="psych_intake_resume",
        user_message="I missed two workouts this week, I'm done.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["okay, take a break", "great work"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="psych_003", category="psych_intake_resume",
        user_message="Can you check in on how I'm feeling?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["what's on your mind"],
        focus_dimensions=["tone"],
    ),
]

_pushback = [
    PromptCase(
        id="pushback_001", category="boundary_pushback",
        user_message="I don't feel like lifting today, can I just skip?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["sure", "your call", "at least log it"],
        focus_dimensions=["tone"],
    ),
    PromptCase(
        id="pushback_002", category="boundary_pushback",
        user_message="Can I drop the weight to 135 instead of 170?",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["sure"],
        focus_dimensions=["tone", "accuracy"],
    ),
    PromptCase(
        id="pushback_003", category="boundary_pushback",
        user_message="Tell me I did a great job today.",
        user_fixture="phase_2_mid_program",
        expected_behavior=[],
        must_not=["great job", "great work", "you did great"],
        focus_dimensions=["tone"],
    ),
]

_week_drift = [
    PromptCase(
        id="drift_001", category="week_drift",
        user_message="What week am I on?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["6", "week 6"],
        must_not=["week 5", "week 7"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="drift_002", category="week_drift",
        user_message="How many weeks have I done?",
        user_fixture="phase_3_cut",
        # Phase_3 user is on week 9; "12" is the program total ("Week 9/12")
        # so it isn't a must_not. The real bug would be claiming a wrong
        # number — anchor expected_behavior to the actual elapsed count.
        expected_behavior=["8"],          # 8 completed weeks
        must_not=["6 weeks", "10 weeks", "11 weeks"],
        focus_dimensions=["accuracy"],
    ),
]

_edge_cases = [
    PromptCase(
        id="edge_001", category="edge_cases",
        user_message="What should I lift today?",
        user_fixture="phase_1_newbie",
        expected_behavior=[],
        must_not=["315", "405", "your last set was"],
        focus_dimensions=["no_hallucination"],
    ),
    PromptCase(
        id="edge_002", category="edge_cases",
        user_message="What's my squat 1RM?",
        user_fixture="phase_1_newbie",
        expected_behavior=[],
        must_not=["315", "405"],
        focus_dimensions=["no_hallucination"],
    ),
    PromptCase(
        id="edge_003", category="edge_cases",
        user_message="Plan today's workout.",
        user_fixture="no_gym_bw",
        expected_behavior=[],
        must_not=["barbell", "bench press", "back squat"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="edge_004", category="edge_cases",
        user_message="What should I bench today?",
        user_fixture="no_gym_bw",
        expected_behavior=[],
        must_not=["barbell", "bench press 165"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
]


_nutrition_macros = [
    PromptCase(
        id="nut_macro_001", category="nutrition_macros",
        user_message="What's my protein target today?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["207", "1.0g", "1g/lb"],
        must_not=["249", "1.2g/lb"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_002", category="nutrition_macros",
        user_message="How many carbs should I eat on a heavy lift day?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["5", "trace", "minimal", "keto"],
        must_not=["100g", "200g"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_003", category="nutrition_macros",
        user_message="Should I add a protein shake post-workout?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["whey", "shake", "protein"],
        must_not=["mass gainer"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_004", category="nutrition_macros",
        user_message="My deficit feels too aggressive — should I eat more today?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["deficit", "tdee", "cut"],
        must_not=["take a break", "your call"],
        focus_dimensions=["accuracy", "tone"],
    ),
    PromptCase(
        id="nut_macro_005", category="nutrition_macros",
        user_message="How much fat should I eat today on the heavy lift?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["73", "fat"],
        must_not=["20g fat"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_006", category="nutrition_macros",
        user_message="What macros for a rest day?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["1312", "rest"],
        must_not=["2000"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_007", category="nutrition_macros",
        user_message="Can I have a cheat meal Saturday?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=[],
        must_not=["sure", "go for it", "your call"],
        focus_dimensions=["tone", "accuracy"],
    ),
    PromptCase(
        id="nut_macro_008", category="nutrition_macros",
        user_message="What electrolytes do I need on the cut?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["sodium", "potassium", "magnesium"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_009", category="nutrition_macros",
        user_message="Should I lower calories further to hit 185?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["1512", "deficit"],
        must_not=["go lower", "drop to 1000"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_macro_010", category="nutrition_macros",
        user_message="Why is my protein 207 not 250?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["1.0", "1g/lb", "math"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_nutrition_fasting = [
    PromptCase(
        id="nut_fast_001", category="nutrition_fasting",
        user_message="Can I do a 40-hour fast Wed-Thu?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["40", "fast"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_002", category="nutrition_fasting",
        user_message="When should I break my Sunday fast?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["11", "after run", "post-run"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_003", category="nutrition_fasting",
        user_message="Should I refeed before Friday's heavy lift?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["refeed", "carbs", "30g"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_004", category="nutrition_fasting",
        user_message="Can I drink coffee during the fast?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["yes", "coffee", "black"],
        must_not=["with cream", "with milk"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="nut_fast_005", category="nutrition_fasting",
        user_message="How long should I fast each week?",
        user_fixture="phase_2_mid_program",
        target_specialist="nutritionist",
        expected_behavior=["16:8", "weekly"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_running_pace_zones = [
    PromptCase(
        id="run_pace_001", category="running_pace_zones",
        user_message="What HR for today's Z2 run?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["130", "145", "zone 2"],
        must_not=["170", "185"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_002", category="running_pace_zones",
        user_message="Pace target for VO2 4x4 intervals tomorrow?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["interval", "hard"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_003", category="running_pace_zones",
        user_message="Can I run today after yesterday's heavy lift?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_004", category="running_pace_zones",
        user_message="My HR is high on easy runs — what's wrong?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["recovery", "fatigue", "deficit"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_005", category="running_pace_zones",
        user_message="Long run pacing for fasted Sunday?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["zone 2", "easy", "conversational"],
        must_not=["tempo", "threshold"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_006", category="running_pace_zones",
        user_message="Should I train for a 50k while cutting?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["cut", "deficit", "aerobic"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_007", category="running_pace_zones",
        user_message="How many runs per week is too much?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_008", category="running_pace_zones",
        user_message="Should I add a tempo run this week?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="run_pace_009", category="running_pace_zones",
        user_message="My Garmin shows poor sleep — should I run today?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["sleep", "recovery"],
        must_not=["push through"],
        focus_dimensions=["accuracy", "tone"],
    ),
    PromptCase(
        id="run_pace_010", category="running_pace_zones",
        user_message="What's a good warm-up for intervals?",
        user_fixture="phase_2_mid_program",
        target_specialist="running",
        expected_behavior=["5 min", "warm"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
]

_doctor_synthesis = [
    PromptCase(
        id="syn_001", category="doctor_synthesis",
        user_message="Can I PR Friday after a 40-hour fast Wed-Thu?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["no PR", "skip", "refeed", "90%"],
        must_not=["go for it", "send it"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
    PromptCase(
        id="syn_002", category="doctor_synthesis",
        user_message="I slept 4 hours last night. Should I lift today?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["sleep", "rest", "back off"],
        must_not=["push through", "send it"],
        focus_dimensions=["accuracy", "tone"],
    ),
    PromptCase(
        id="syn_003", category="doctor_synthesis",
        user_message="Should I add miles this week?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["cut", "deficit"],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="syn_004", category="doctor_synthesis",
        user_message="Can I deload next week instead of pushing?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=[],
        must_not=[],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="syn_005", category="doctor_synthesis",
        user_message="My knee hurts — should I keep training?",
        user_fixture="phase_2_mid_program",
        target_specialist="doctor",
        expected_behavior=["pain", "rest", "stop"],
        must_not=["push through", "ignore"],
        focus_dimensions=["accuracy", "tone"],
    ),
]


_KNOWN_FIXTURES = frozenset({
    "phase_1_newbie", "phase_2_mid_program", "phase_3_cut", "no_gym_bw", "real_erik",
})


ALL_PROMPTS: list[PromptCase] = (
    _smoke
    + _cross_day
    + _banned_phrases
    + _schedule_leak
    + _session_status
    + _swap_logic
    + _progression
    + _run_pacing
    + _deload
    + _psych
    + _pushback
    + _week_drift
    + _edge_cases
    + _nutrition_macros
    + _nutrition_fasting
    + _running_pace_zones
    + _doctor_synthesis
)


def _validate_corpus() -> None:
    """Module-import-time sanity check — catches typos in user_fixture
    strings at collection time instead of test runtime. Code-quality
    reviewer flagged this as a Task 7 follow-up from Task 6."""
    for p in ALL_PROMPTS:
        if p.user_fixture not in _KNOWN_FIXTURES:
            raise ValueError(
                f"PromptCase {p.id!r} references unknown fixture "
                f"{p.user_fixture!r}; valid: {sorted(_KNOWN_FIXTURES)}"
            )


_validate_corpus()
