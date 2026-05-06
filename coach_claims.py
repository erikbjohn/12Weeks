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


def _fetch_today_status(user_id: int) -> dict | None:
    """Returns the same dict shape build_filtered_context produces for
    'today_status'. Indirection for testability."""
    from coach_assembler import build_filtered_context
    ctx = build_filtered_context("conversation")
    return ctx.get("today_status")


def _fetch_week_program(user_id: int) -> tuple[int, list[dict]] | None:
    """Returns (current_week, list of per-day dicts with day_idx, weekday,
    lift_name, run_type, run_label, run_duration)."""
    from coach_assembler import _resolve_workout_for_day, _current_week
    from models import WeeklyRunPlan
    week = _current_week()
    days = []
    weekday_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for d in range(7):
        wt = _resolve_workout_for_day(week, d) or {}
        run_plan = WeeklyRunPlan.query.filter_by(
            user_id=user_id, week=week, day_idx=d,
        ).first()
        run_type = run_plan.run_type if run_plan else (wt.get("run") or {}).get("type")
        run_label = run_plan.label if run_plan else (wt.get("run") or {}).get("label")
        run_duration = run_plan.duration if run_plan else (wt.get("run") or {}).get("duration")
        days.append({
            "day_idx": d,
            "weekday": weekday_short[d],
            "lift_name": wt.get("liftName"),
            "run_type": run_type,
            "run_label": run_label,
            "run_duration": run_duration,
        })
    return week, days


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

    if want("today_status"):
        ts = _fetch_today_status(user_id)
        if ts:
            out.append(Claim(
                claim_id="today.weekday",
                predicate="today.weekday_name",
                value=str(ts["weekday"]),
                source="today_status",
            ))
            out.append(Claim(
                claim_id="today.date",
                predicate="today.iso_date",
                value=str(ts.get("date", "")),
                source="today_status",
            ))
            if ts.get("workout_prescribed"):
                if "workout_lift_name" in ts:
                    out.append(Claim(
                        claim_id="today.workout.lift_name",
                        predicate="today.workout.lift_name",
                        value=str(ts["workout_lift_name"]),
                        source="today_status",
                    ))
            else:
                out.append(Claim(
                    claim_id="today.workout.is_rest",
                    predicate="today.workout.is_rest_day",
                    value=True,
                    source="today_status",
                ))
            if ts.get("run_prescribed"):
                out.append(Claim(
                    claim_id="today.run.type",
                    predicate="today.run.type",
                    value=str(ts["run_prescribed"]),
                    source="today_status",
                ))
                if ts.get("run_label"):
                    out.append(Claim(
                        claim_id="today.run.label",
                        predicate="today.run.label",
                        value=str(ts["run_label"]),
                        source="today_status",
                    ))
                if ts.get("run_duration"):
                    out.append(Claim(
                        claim_id="today.run.duration",
                        predicate="today.run.duration",
                        value=str(ts["run_duration"]),
                        source="today_status",
                    ))

    if want("week_program"):
        result = _fetch_week_program(user_id)
        if result:
            week, days = result
            day_short = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            for day in days:
                short = day_short[day["day_idx"]]
                if day.get("lift_name"):
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.lift.name",
                        predicate=f"program.week{week}.{short}.lift_name",
                        value=str(day["lift_name"]),
                        source=f"WeeklyDaySchedule(week={week},day_idx={day['day_idx']})",
                    ))
                if day.get("run_type"):
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.run.type",
                        predicate=f"program.week{week}.{short}.run_type",
                        value=str(day["run_type"]),
                        source=f"WeeklyRunPlan(week={week},day_idx={day['day_idx']})",
                    ))
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.run.label",
                        predicate=f"program.week{week}.{short}.run_label",
                        value=str(day["run_label"] or ""),
                        source=f"WeeklyRunPlan(week={week},day_idx={day['day_idx']})",
                    ))
                    out.append(Claim(
                        claim_id=f"week{week}.{short}.run.duration",
                        predicate=f"program.week{week}.{short}.run_duration",
                        value=str(day["run_duration"] or ""),
                        source=f"WeeklyRunPlan(week={week},day_idx={day['day_idx']})",
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
