"""Dataclasses shared across the audit harness."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class PromptCase:
    id: str
    category: str
    user_message: str
    user_fixture: str          # one of: phase_1_newbie, phase_2_mid_program,
                                #         phase_3_cut, no_gym_bw, real_erik
    expected_behavior: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    focus_dimensions: list[str] = field(default_factory=list)
    requires_real_data: bool = False
    # Subtract from BANNED_PHRASES for this prompt only — used when a case
    # legitimately needs the coach to quote a banned phrase back.
    banned_phrase_overrides: list[str] = field(default_factory=list)
    # Multi-agent: when set, the audit invokes that specialist DIRECTLY
    # (bypassing Doctor) so the prompt tests the specialist in isolation.
    # Values: "nutritionist" | "strength" | "running" | "doctor" | None.
    target_specialist: str | None = None


@dataclass
class HeuristicResult:
    passed: bool
    missing_expected: list[str] = field(default_factory=list)
    matched_must_not: list[str] = field(default_factory=list)
    matched_banned: list[str] = field(default_factory=list)


@dataclass
class JudgeResult:
    passed: bool
    scores: dict                    # {accuracy, tone, no_hallucination, follows_must_not}
    violations: list[str] = field(default_factory=list)
    evidence: str = ""


@dataclass
class Finding:
    prompt_id: str
    category: str
    user_message: str
    coach_response: str
    heuristic: HeuristicResult
    judge: JudgeResult | None
    timestamp_iso: str
    fixture: str

    def to_dict(self) -> dict:
        return asdict(self)
