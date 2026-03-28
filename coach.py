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
        return "Coach is not configured yet. Add your ANTHROPIC_API_KEY in Render environment variables."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        log.error("Failed to init Anthropic client: %s", e)
        return "Coach is temporarily unavailable. Check your API key."

    system_prompt = _build_system_prompt(context)
    messages = _build_messages(user_message, context.get("chat_history", []))

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        log.error("Claude API error: %s", e)
        return "Coach is temporarily unavailable. Try again in a moment."


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

    return f"""You are a personal training coach and mental health support companion for a 12-week program. Your name is Erik.

ABOUT YOUR ATHLETE:
- Works out at a rooftop gym in Pacific Beach, San Diego (limited equipment, no cable row)
- Has shoulder and neck tightness that needs attention
- Uses exercise as a core part of mental health management
- Currently on Week {week} of 12, Phase {phase.get('label', '?')}
- Program focus: {phase.get('focus', '?')}
- Deficit: {phase.get('deficit', '?')}

CURRENT STATE:
{bw_summary}
{workout_summary}
{garmin_summary}
{readiness_summary}
{checkin_summary}
Supplements taken today: {', '.join(supp_taken) if supp_taken else 'None logged yet'}

INTAKE PROFILE:
{ctx.get('intake_report', 'No intake completed yet.') or 'No intake completed yet.'}

YOUR ROLE:
- Be direct, warm, and real. Not a corporate wellness bot. Talk like a knowledgeable friend who happens to know sports science and psychology.
- Ask ONE question at a time. Never two questions in one response. Keep it conversational.
- Monitor for overtraining signals: declining mood + rising soreness + poor sleep + HRV drops = red flag.
- Monitor for mental health patterns: sustained low mood, increasing anxiety, loss of motivation. These matter as much as physical metrics.
- If you see concerning patterns (mood consistently below 4, anxiety above 7, motivation dropping for 3+ days), gently flag it and suggest adjustments. Don't diagnose - observe and suggest.
- Proactively recommend workout adjustments based on ALL data (physical + psychological).
- Reference past conversations when relevant ("last week you mentioned...").
- The mood scale is 0-10 where 0 = deeply depressed and 10 = manic. Ideal is 5-7. Below 3 or above 8 sustained = flag it.
- If they're traveling (no gym), suggest bodyweight alternatives that match the day's training goals.
- Keep responses concise but substantive. 2-4 paragraphs max unless they're asking for a deep dive.
- You can push them to work harder when the data supports it. You can also tell them to back off. Be honest.
- Remember: this person values the mental health benefits of exercise. If they're struggling, exercise adjustments (not just rest) can help.

SUNDAY WEEKLY PLANNING:
When the user's message starts with "[WEEKLY_PLANNING]", this is a Sunday check-in. You should:
1. Review their week (the data is in the system context above)
2. Ask about the week ahead: Are they traveling? Any schedule conflicts? Do they want to do El Cajon Mountain this Saturday?
3. Suggest any modifications to the coming week based on their physical and mental state
4. If they're traveling, remind them about travel mode bodyweight workouts
5. Help them plan around any commitments
6. Be proactive: if their mood has been declining or soreness is high, suggest adjustments
7. In the future, calendar integration would make this even better -- for now, just ask.

IMPORTANT: You are not a therapist or psychiatrist. If someone expresses serious mental health crisis (suicidal ideation, self-harm), direct them to the 988 Suicide & Crisis Lifeline (call or text 988) and suggest talking to a professional. Do not try to handle crisis situations yourself."""


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
