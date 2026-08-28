"""Every athlete-facing agent gets EVERY context section. Non-negotiable.

Built 2026-04-30 (e9696a4, ALL_SECTIONS: "agent-specific opting-out caused the
15.6h-fast hallucination"), lost 2026-05-03 in a wholesale revert (df9c3a4),
and re-learned by hand five times since — most recently 2026-08-28 when the
chat opener nagged for a weigh-in that was logged, said "I can't pull Garmin"
with the row in the DB, and conceded REAL HRV numbers were fabricated because
the replying agent couldn't see what the morning agent saw.

A missing section is not a blank — the persona rules turn it into a confident
lie. So: CORE_SECTIONS == every registered builder (except chat_history, which
stays per-agent), and every agent outside the documented specialist set
requires all of it. Adding a builder without adding it to CORE fails here.
"""
import re


def _registered_builders():
    import coach_assembler
    src = open(coach_assembler.__file__).read()
    return set(re.findall(r'@section_builder\("([a-z_]+)"\)', src))


def test_core_is_every_registered_builder_except_chat_history():
    from coach_agents import CORE_SECTIONS
    expected = _registered_builders() - {"chat_history"}
    assert set(CORE_SECTIONS) == expected, (
        f"missing from CORE: {expected - set(CORE_SECTIONS)}; "
        f"unknown in CORE: {set(CORE_SECTIONS) - expected}")


def test_every_athlete_facing_agent_requires_the_whole_core():
    from coach_agents import AGENTS, CORE_SECTIONS, SPECIALIST_AGENTS
    for name, cfg in AGENTS.items():
        if name in SPECIALIST_AGENTS:
            continue
        missing = set(CORE_SECTIONS) - set(cfg["requires"])
        assert not missing, f"{name} is blind to {sorted(missing)}"


def test_specialist_allowlist_is_only_the_documented_four():
    from coach_agents import SPECIALIST_AGENTS
    assert set(SPECIALIST_AGENTS) == {"crisis", "nutritionist", "strength_coach", "running_coach"}


def test_no_duplicates_in_any_requires():
    from coach_agents import AGENTS
    for name, cfg in AGENTS.items():
        assert len(cfg["requires"]) == len(set(cfg["requires"])), name
