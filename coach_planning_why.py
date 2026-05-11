"""Per-exercise WHY generation for the weekly-planning HTML card.

Replaces the deterministic JS lookup (which couldn't see peer state and would
say "Top-set holds while accessories progress" when nothing was progressing).
This runs ONCE per planning regenerate, gets a context-aware sentence per
exercise from Claude Sonnet, and persists into WeeklyPrescription.adjustment_reason
so the client can render it directly without ever calling the model at view time.
"""
from __future__ import annotations
import os
import json
import logging

log = logging.getLogger(__name__)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=3,
    )


def _format_day_for_prompt(day_idx: int, exercises: list[dict],
                            run_label: str | None = None) -> str:
    """Render one day as a compact YAML-ish block for the model."""
    day = _DAY_NAMES[day_idx] if 0 <= day_idx < 7 else f"Day{day_idx}"
    lines = [f"{day}:"]
    for ex in exercises:
        wt = ex.get("target_weight")
        unit = "in" if ex.get("tracked_metric") == "height" else "lb"
        wt_str = f"{wt}{unit}" if wt else ("BW" if ex.get("is_bw") else "—")
        prev = ex.get("prev_weight")
        delta = ""
        if prev is not None and wt is not None:
            d = wt - prev
            if d > 0: delta = f" (was {prev}{unit}, +{d}{unit})"
            elif d < 0: delta = f" (was {prev}{unit}, -{abs(d)}{unit})"
            else: delta = " (held)"
        muscle = ex.get("muscle_group") or "—"
        category = ex.get("category") or "—"
        lines.append(
            f"  - {ex['exercise']}: {ex['sets']}x{ex['reps']} @ {wt_str}"
            f"{delta} [muscle={muscle}, type={category}]"
        )
    if run_label:
        lines.append(f"  - Run: {run_label}")
    return "\n".join(lines)


def generate_week_whys(
    user_id: int,
    week: int,
    program: list[dict],
    user_context: dict,
    run_summary: list[dict] | None = None,
) -> dict[tuple[int, str], str]:
    """Generate one-sentence WHY per exercise for the whole week.

    program: list of {day, exercise, sets, reps, target_weight,
                      tracked_metric, muscle_group, category, prev_weight, is_bw}
    user_context: {phase, deload, goal_type, current_weight, target_weight,
                   weeks_remaining, recent_top_sets (optional)}
    run_summary: optional list of {day, label}

    Returns: {(day_idx, exercise_name): why_string}
    Empty dict on failure — caller should keep the existing reasons.
    """
    if not program:
        return {}

    # Group exercises by day so the prompt sees peer context
    by_day: dict[int, list[dict]] = {}
    for ex in program:
        by_day.setdefault(ex["day"], []).append(ex)
    runs_by_day: dict[int, str] = {}
    for r in (run_summary or []):
        if r.get("label"):
            runs_by_day[r["day"]] = r["label"]

    day_blocks = []
    for day_idx in sorted(by_day.keys()):
        day_blocks.append(
            _format_day_for_prompt(day_idx, by_day[day_idx], runs_by_day.get(day_idx))
        )

    week_block = "\n".join(day_blocks)
    phase = user_context.get("phase", "?")
    deload = user_context.get("deload", False)
    goal_type = user_context.get("goal_type", "recomp")
    current_wt = user_context.get("current_weight")
    target_wt = user_context.get("target_weight")
    weeks_rem = user_context.get("weeks_remaining")

    system = (
        "You are a strength coach writing per-exercise rationale for the athlete's "
        "weekly plan. Each exercise needs ONE sentence (max 20 words) that explains "
        "why THIS exercise at THIS load this week, given the surrounding context.\n\n"
        "CRITICAL: read the WHOLE day before writing each reason. The reason MUST "
        "reflect peer state:\n"
        "- If everything in the day is holding, say 'consolidation' — never claim "
        "  'anchor while accessories progress' (a lie when nothing's progressing).\n"
        "- If only the main lift is bumping, say it leads the day.\n"
        "- If main holds but accessories bump, say accessories carry the load.\n"
        "- If main lift is +5 and accessories are mixed, name the actual pattern.\n"
        "- Reference the athlete's goal (cut/recomp/build) when relevant — "
        "  e.g. 'holds lean mass under the cut', 'recomp anchor as waist tightens'.\n"
        "- Reference phase: P1=base, P2=strength, P3=peak, deload weeks differ.\n"
        "- For Box Jump and other height-tracked plyos: talk about CNS, height, "
        "  power output — never weight.\n"
        "- For bodyweight exercises: rep volume, pattern, durability — never weight.\n\n"
        "BANNED: generic fluff like 'great for shoulders'. Every sentence must "
        "REFER to either the load delta, the day's pattern, the athlete's goal, "
        "or the exercise's role in the week.\n\n"
        "Output: ONE JSON object mapping `<day>:<exercise_name>` to the WHY string. "
        "No prose. No commentary. JSON only."
    )

    user_prompt = (
        f"ATHLETE CONTEXT:\n"
        f"- Goal: {goal_type}"
        f" ({current_wt} lb → {target_wt} lb target, "
        f"{weeks_rem} weeks remaining)\n"
        f"- Phase: {phase}{' (DELOAD)' if deload else ''}\n"
        f"- Week {week}\n\n"
        f"WEEK {week} PRESCRIPTION:\n{week_block}\n\n"
        "Write the JSON. Keys are `day_idx:exercise_name` strings "
        "(e.g. `0:Barbell Back Squat`). One WHY per exercise."
    )

    try:
        client = _anthropic_client()
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
        # Strip markdown fence if present
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("generate_week_whys failed: %s", e)
        return {}

    out: dict[tuple[int, str], str] = {}
    for k, v in parsed.items():
        if ":" not in k or not isinstance(v, str):
            continue
        day_part, _, ex_name = k.partition(":")
        try:
            day_idx = int(day_part)
        except ValueError:
            continue
        out[(day_idx, ex_name.strip())] = v.strip()
    return out
