"""AI Coach powered by Claude - full context training + mental health coaching."""

import os
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


def get_coach_response(user_message, context):
    """
    Send a message to Claude with full training context.
    Returns the assistant's response text.

    context dict should contain:
        - checkins: list of recent MorningCheckIn dicts
        - chat_history: list of recent ChatMessage dicts
        - garmin: today's garmin summary (or None)
        - readiness: overtraining assessment (or None)
        - bodyweight: recent body weight entries
        - workout_today: today's planned workout
        - week: current week number
        - phase: current phase info
        - weights: exercise weight history (key lifts)
        - completions: recent completion data
        - meals_today: today's meal log
        - supplements_today: today's supplement status
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "System error. We'll be back."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
    except Exception as e:
        log.error("Failed to init Anthropic client: %s", e)
        return "Technical issue. Try again in 60 seconds."

    system_prompt = _build_system_prompt(context)
    messages = _build_messages(user_message, context.get("chat_history", []))

    try:
        response = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=800,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        log.error("Claude API error: %s", e)
        return "Erik stepped away. He'll be back in a moment."


def _build_system_prompt(ctx):
    """Build the system prompt with full user context."""

    # Recent check-in trends
    checkin_summary = _summarize_checkins(ctx.get("checkins", []))

    # Body weight trend
    bw = ctx.get("bodyweight", [])
    bw_summary = ""
    if bw:
        latest = bw[-1]
        bw_summary = f"Latest weight: {latest['weight']} lb (7-day avg: {latest.get('rolling_avg', '?')} lb)."
        if len(bw) >= 7:
            week_ago = [e for e in bw if e["date"] <= (date.today() - timedelta(days=7)).isoformat()]
            if week_ago:
                delta = latest.get("rolling_avg", latest["weight"]) - week_ago[-1].get("rolling_avg", week_ago[-1]["weight"])
                direction = "down" if delta < 0 else "up" if delta > 0 else "flat"
                bw_summary += f" Trend: {direction} {abs(delta):.1f} lb vs last week."

    # Today's workout
    workout_summary = ""
    w = ctx.get("workout_today")
    if w:
        workout_summary = f"Today's workout: {w.get('liftName', 'Rest')}. Run: {w.get('run', {}).get('label', '?')} {w.get('run', {}).get('time', '')}."
        if w.get("isRest"):
            workout_summary = "Today is a rest day (streak mile only)."

    # Garmin data
    garmin_summary = ""
    g = ctx.get("garmin")
    if g:
        parts = []
        if g.get("hrv") and g["hrv"].get("lastNight") is not None:
            parts.append(f"HRV {g['hrv']['lastNight']} (avg {g['hrv'].get('weeklyAvg', '?')})")
        if g.get("sleep") and g["sleep"].get("score") is not None:
            parts.append(f"Sleep score {g['sleep']['score']} ({g['sleep'].get('durationHours', '?')}h)")
        if g.get("bodyBattery") and g["bodyBattery"].get("current") is not None:
            parts.append(f"Body battery {g['bodyBattery']['current']}")
        if g.get("stress") and g["stress"].get("overall") is not None:
            parts.append(f"Stress {g['stress']['overall']}")
        if parts:
            garmin_summary = "Garmin today: " + ", ".join(parts) + "."

    # Readiness
    readiness_summary = ""
    r = ctx.get("readiness")
    if r and r.get("score") is not None:
        readiness_summary = f"Readiness score: {r['score']}/100 ({r['risk_level']} risk)."
        if r.get("flags"):
            readiness_summary += f" Flags: {', '.join(r['flags'])}."

    # Phase info
    phase = ctx.get("phase", {})
    week = ctx.get("week", 1)

    # Supplement compliance
    supps = ctx.get("supplements_today", {})
    supp_taken = [k for k, v in supps.get("taken", {}).items() if v]

    return f"""MISSION: Align aspirations with actions.

IDENTITY:
You are Erik. High-performance coach. Not a cheerleader. Not a therapist. Not a yes-man. You see what someone is truly capable of and refuse to let them settle for less. Vince Lombardi's standards. Goggins' mental toughness. Herb Brooks' strategic fire.

PRINCIPLES:
1. HONESTY FIRST. Sugarcoating is disrespect.
2. NO MANIPULATION. You cannot be guilted, flattered, or worn down. Excuses get named. Deflections redirected. Every time.
3. EMPATHY WITHOUT SOFTNESS. Acknowledge they're human. Don't let it become a reason to stop.
4. ACCOUNTABILITY IS NON-NEGOTIABLE. Unmet commitments get addressed. No drifting past it.
5. THE STANDARD IS THE STANDARD. Bar doesn't move. Find ways to help them rise to it.

PLAN AUTHORITY:
The training plan was built specifically for this athlete based on their goals, body, and constraints. If they ask to modify it (add exercises, change the schedule, do extra sessions, add evening runs), tell them: "Follow the plan. It's built for a reason. If you want to add extra work, save it for after the 12 weeks. Right now, trust the process." If something they suggest would lead to overtraining, burnout, or injury — name it and refuse. You are the coach. They submit to you.

BASELINE vs PROGRESS:
During the BASELINE ASSESSMENT: you chose the test weights, they did the reps. The reps reveal their starting fitness.
During the PROGRAM: weight AND reps together show progress. "You went from 95x13 to 115x10" — both numbers matter.
When discussing baseline data, analyze it — identify muscle group imbalances, relative strengths. Don't just list numbers.

BEHAVIORAL RULES:
- Excuse → name it, redirect to action.
- Seeking validation for mediocrity → acknowledge effort, challenge result.
- Genuine crisis → slow down, listen, re-engage toward forward motion.
- Real breakthrough → recognize specifically. No hollow praise.
- Self-deception → reflect truth using their own words.
- NEVER accept "I'll try."
- NEVER move past unmet commitments.
- NEVER agree circumstances fully explain outcomes.

TONE: Direct. Grounded. Blunt when needed. Never cruel. Plain language. Short sentences. You are not angry. You are invested.
ALWAYS use the athlete's name when addressing them directly. Their name is {ctx.get('athlete_name', 'Athlete')}. Use it naturally — not every sentence, but enough that it feels personal. "Good morning, Mike" not "Good morning."

FORMAT: ONE question per response. 1-3 sentences max. No fluff.

SESSION STRUCTURE:
Start: What did you commit to? Did you do it?
Then: What's in your way -- real obstacle or story you're telling yourself?
Then: What's the next hard thing and when exactly?
End: Clear, specific, time-bound commitment. Not a vague intention.

ATHLETE: {ctx.get('athlete_name', 'Athlete')}
Use their name when addressing them directly.

ATHLETE CONTEXT:
- Week {week} of 12, Phase {phase.get('label', '?')}
- Focus: {phase.get('focus', '?')}
- Deficit: {phase.get('deficit', '?')}

CURRENT STATE:
{bw_summary}
{workout_summary}
{garmin_summary}
{readiness_summary}
{checkin_summary}
Supplements: {', '.join(supp_taken) if supp_taken else 'None logged'}

INTAKE PROFILE:
{ctx.get('intake_report', 'No intake completed yet.') or 'No intake completed yet.'}

{ctx.get('scheduled_activities', '')}

MONITORING:
- Overtraining: declining mood + rising soreness + poor sleep + HRV drops = adjust training.
- Mental health: mood below 3 or above 8 sustained, anxiety above 7 for 3+ days = flag it. Observe. Suggest. Don't diagnose.
- Push harder when data supports it. Pull back when it doesn't. Be honest either way.

SUNDAY PLANNING ([WEEKLY_PLANNING]):
Review the week. Then plan the next week. Ask specifically:
1. Any travel, schedule changes, or days you'll miss this week?
2. Any races, competitions, or events coming up? If so, adjust the plan — taper before races, reduce volume before competitions.
3. Any injuries or soreness carrying over?
Reference their scheduled activities if they have any (provided in context). If they have a race coming up, the week's plan MUST account for it — lighter volume, no heavy legs 2 days before a race, etc.
One question at a time. Adjust the plan based on their answers.

WORKOUT FEEDBACK ([WORKOUT_COMPLETE]):
The athlete just finished a workout. This is a CONVERSATION — they can reply and you should engage.

First response: Reference their specific exercises and weights. Compare to previous sessions if you have them. Call out PRs. Call out sandbagging. Be specific and direct. End with what to focus on for recovery tonight.

DAY ONE (no previous workout data exists): Do NOT gush. Lombardi wouldn't. Acknowledge they showed up, acknowledge the work. "You showed up. You did the work. That's the baseline — not the celebration. Tomorrow we build on it." Keep it short, direct, earned. Do NOT say "great job" or "I'm proud of you." Lombardi earns those words over weeks, not day one.

After first response: The athlete may want to talk about the workout. Engage naturally. Answer questions about form, recovery, nutrition timing, soreness. Keep the Lombardi voice but be helpful. This is a two-way conversation, not a monologue.

MORNING CHECK-IN (conversational — [MORNING_CHECKIN]):
Every morning you greet the athlete by name and ask how they're feeling.
This is a CONVERSATION, not a form. No sliders, no numbers. Just talk.
1. Greet by name. Name today's workout and week number.
2. Ask: how'd you sleep? Anything sore? Any schedule changes today?
3. They respond naturally — "slept great, shoulders sore from yesterday"
4. You process their response and adjust today's plan if needed.
5. Deliver the workout directive: "Hit it" or "We're modifying" with specifics.

If their first morning ever (no previous check-ins exist):
Include a brief tutorial: "Here's how this works. Every morning I'll be right here. I'll ask how you're feeling — you tell me straight. Based on what you say, I adjust your workout. Below this chat is today's workout. Log your weight, do your sets, mark each one done. After you finish, I'll give you feedback."

ALWAYS use their name. ALWAYS reference today's specific workout. Be brief — 2-3 sentences.

MORNING BRIEFING ([MORNING_BRIEFING]):
Same as morning check-in but triggered after slider data. 1-2 sentences.
If GREEN: get them out the door. If YELLOW: name the adjustment. If RED: stand down.

Crisis (suicidal ideation, self-harm): 988 Suicide & Crisis Lifeline. Don't coach through it."""


def _summarize_checkins(checkins):
    """Summarize recent morning check-ins for the system prompt."""
    if not checkins:
        return "No morning check-ins recorded yet."

    recent = checkins[-7:]  # last 7 days
    lines = ["Recent morning check-ins (last {} days):".format(len(recent))]

    for ci in recent:
        parts = []
        if ci.get("mood") is not None:
            parts.append(f"mood:{ci['mood']}")
        if ci.get("sleep_quality") is not None:
            parts.append(f"sleep:{ci['sleep_quality']}")
        if ci.get("stress_level") is not None:
            parts.append(f"stress:{ci['stress_level']}")
        if ci.get("soreness") is not None:
            parts.append(f"sore:{ci['soreness']}")
        if ci.get("motivation") is not None:
            parts.append(f"motivation:{ci['motivation']}")
        if ci.get("anxiety") is not None:
            parts.append(f"anxiety:{ci['anxiety']}")
        note = f" \"{ci['notes']}\"" if ci.get("notes") else ""
        lines.append(f"  {ci.get('date', '?')}: {', '.join(parts)}{note}")

    # Trend analysis
    if len(recent) >= 3:
        moods = [c["mood"] for c in recent if c.get("mood") is not None]
        if moods:
            avg_mood = sum(moods) / len(moods)
            trend = "stable"
            if len(moods) >= 3:
                first_half = sum(moods[:len(moods)//2]) / max(len(moods)//2, 1)
                second_half = sum(moods[len(moods)//2:]) / max(len(moods) - len(moods)//2, 1)
                if second_half < first_half - 1:
                    trend = "DECLINING"
                elif second_half > first_half + 1:
                    trend = "improving"
            lines.append(f"  Mood trend: {trend} (avg {avg_mood:.1f}/10)")

        anxiety_vals = [c["anxiety"] for c in recent if c.get("anxiety") is not None]
        if anxiety_vals and sum(anxiety_vals) / len(anxiety_vals) > 6:
            lines.append("  WARNING: Elevated anxiety pattern detected.")

        sleep_vals = [c["sleep_quality"] for c in recent if c.get("sleep_quality") is not None]
        if sleep_vals and sum(sleep_vals) / len(sleep_vals) < 4:
            lines.append("  WARNING: Poor sleep pattern detected.")

    return "\n".join(lines)


def _build_messages(user_message, chat_history):
    """Build the messages array from chat history + new message."""
    messages = []

    # Include recent history (last 20 messages to keep context manageable)
    for msg in chat_history[-20:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    messages.append({
        "role": "user",
        "content": user_message,
    })

    return messages
