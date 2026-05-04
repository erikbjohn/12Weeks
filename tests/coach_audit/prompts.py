"""Prompt corpus. Add cases freely — harness loops over `ALL_PROMPTS`."""
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
]
