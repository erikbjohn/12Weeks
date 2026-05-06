"""Typed claims that back cited output. Each claim is a verified fact
the model can cite by claim_id; the validator checks both that the
claim exists and that the value cited in prose matches.

Architectural premise (per 2026-05-06 review): the slice should not
be a free-text blob the model re-derives facts from. It should be a
table of pre-computed (claim_id, predicate, value, source, derivation)
rows that the model selects from and cites explicitly.

Scope strings (the optional `scope` arg to `build_claims`) let callers
build a focused set: ("body_weight",), ("goal",), ("today_status",),
("week_program",), etc. An empty scope means "all available."
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class Claim:
    """A pre-computed fact citable by the model.

    Fields:
        claim_id:   stable, deterministic ID like "body.weight.current"
        predicate:  human-readable predicate name; the model sees this
                    when selecting a claim and the validator uses it to
                    detect mis-attribution
        value:      typed value (int, float, str, bool); validator
                    string-matches this against any number cited in prose
        source:     where the value came from — table#row OR "derived"
        derivation: when source=="derived", the formula used (free-text);
                    None for direct facts
    """
    claim_id: str
    predicate: str
    value: Any
    source: str
    derivation: str | None = None


def _fetch_latest_bodyweight(user_id: int):
    """Indirection so tests can mock without hitting the DB."""
    from models import BodyWeight
    return (BodyWeight.query
            .filter_by(user_id=user_id)
            .order_by(BodyWeight.log_date.desc())
            .first())


def _fetch_training_goal(user_id: int):
    from models import TrainingGoal
    return TrainingGoal.query.filter_by(user_id=user_id).first()


def build_claims(user_id: int, scope: tuple[str, ...] = ()) -> list[Claim]:
    """Build the claims table for this user. `scope` filters which
    sections to include; empty = all.

    Order matters: claims are emitted in dependency order (raw before
    derived) so the model reads them top-down.
    """
    out: list[Claim] = []
    want = lambda s: not scope or s in scope

    bw = _fetch_latest_bodyweight(user_id) if want("body_weight") else None
    goal = _fetch_training_goal(user_id) if want("body_weight") or want("goal") else None

    if bw and want("body_weight"):
        out.append(Claim(
            claim_id="body.weight.current",
            predicate="athlete.current_weight_lb",
            value=float(bw.weight_lbs),
            source=f"BodyWeight#{getattr(bw, 'id', '?')} ({bw.log_date.isoformat()})",
        ))

    if goal and want("goal"):
        out.append(Claim(
            claim_id="body.weight.target",
            predicate="athlete.target_weight_lb",
            value=float(goal.target_weight),
            source=f"TrainingGoal#{getattr(goal, 'id', '?')}",
        ))
        out.append(Claim(
            claim_id="goal.daily_calories",
            predicate="athlete.daily_calorie_target",
            value=int(goal.daily_calories),
            source=f"TrainingGoal#{getattr(goal, 'id', '?')}",
        ))
        out.append(Claim(
            claim_id="goal.type",
            predicate="athlete.goal_type",
            value=str(goal.goal_type),
            source=f"TrainingGoal#{getattr(goal, 'id', '?')}",
        ))

    # Derived claims (only when inputs are present)
    if bw and goal and want("body_weight") and want("goal"):
        delta = round(float(bw.weight_lbs) - float(goal.target_weight), 1)
        out.append(Claim(
            claim_id="body.weight.lb_to_target",
            predicate="athlete.lb_to_target",
            value=delta,
            source="derived",
            derivation=f"{bw.weight_lbs} - {goal.target_weight} = {delta}",
        ))

    return out


def format_claims_block(claims: list[Claim]) -> str:
    """Render claims as the <claims> section of the slice.

    Format is structured so the model can parse it deterministically:
        <claims>
          - id=body.weight.current  pred=athlete.current_weight_lb  value=207.2  source=BodyWeight#4821
          - id=body.weight.target   pred=athlete.target_weight_lb   value=185.0  source=TrainingGoal#12
          ...
        </claims>
    """
    if not claims:
        return ""
    lines = ["<claims>"]
    for c in claims:
        line = f"  - id={c.claim_id}  pred={c.predicate}  value={c.value!r}  source={c.source}"
        if c.derivation:
            line += f"  derivation={c.derivation!r}"
        lines.append(line)
    lines.append("</claims>")
    return "\n".join(lines)
