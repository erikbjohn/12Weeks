"""Prompt corpus. Add cases freely — harness loops over `ALL_PROMPTS`."""
from __future__ import annotations
from .types import PromptCase

ALL_PROMPTS: list[PromptCase] = [
    PromptCase(
        id="smoke_001",
        category="smoke",
        user_message="ping",
        user_fixture="phase_2_mid_program",
        expected_behavior=["pong"],
        must_not=["ERROR"],
        focus_dimensions=["accuracy"],
    ),
    PromptCase(
        id="cross_day_001",
        category="cross_day_hallucination",
        user_message="What lift is on Monday this week and what's the scheme?",
        user_fixture="phase_2_mid_program",
        expected_behavior=["front squat", "4x3"],
        must_not=["back squat 4x5", "back squat 5x5"],
        focus_dimensions=["accuracy", "no_hallucination"],
    ),
]
