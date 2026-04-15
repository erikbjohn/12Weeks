"""Trigger router with crisis detection for coaching interactions.

Routes incoming messages to the appropriate agent based on:
1. Crisis keyword detection (highest priority)
2. System trigger tags ([MORNING_CHECKIN], [WEEKLY_PLANNING], etc.)
3. Message content inference
4. Default to freeform conversation
"""

import re

# Crisis patterns — always checked first, highest priority
CRISIS_PATTERNS = [
    re.compile(r'\b(suicid|kill\s*my\s*self|end\s*(my|it\s*all))\b', re.IGNORECASE),
    re.compile(r'\b(want\s*to\s*die|no\s*reason\s*to\s*live|better\s*off\s*dead)\b', re.IGNORECASE),
    re.compile(r'\b(self.harm|hurt\s*my\s*self|not\s*worth\s*living)\b', re.IGNORECASE),
]

# Trigger tag extraction
_TRIGGER_RE = re.compile(r'^\[([A-Z_]+)\]')

# Map trigger tags to agent names
_TRIGGER_MAP = {
    "MORNING_CHECKIN": "morning_checkin",
    "MORNING_BRIEFING": "morning_briefing",
    "WEEKLY_PLANNING": "weekly_planning",
    "WEEKLY_REVIEW": "weekly_review",
    "SUNDAY_REVIEW": "weekly_review",
    "WORKOUT_COMPLETE": "workout_feedback",
    "RUN_COMPLETE": "run_complete",
    "MEALS_COMPLETE": "meals_complete",
    "END_OF_DAY": "end_of_day",
    "CHAT_OPENED": "chat_opened",
}


def route_trigger(message, context=None):
    """
    Determine which agent handles this message.

    Args:
        message: Raw user message string (may contain trigger tags)
        context: Optional dict with app state

    Returns:
        dict: {agent_name, trigger, is_crisis, cleaned_message}
    """
    # 1. Crisis detection — always first
    for pattern in CRISIS_PATTERNS:
        if pattern.search(message):
            return {
                "agent_name": "crisis",
                "trigger": "CRISIS",
                "is_crisis": True,
                "cleaned_message": message,
            }

    # 2. Extract trigger tag from message
    trigger_match = _TRIGGER_RE.match(message.strip())
    trigger = trigger_match.group(1) if trigger_match else None

    # Strip trigger tag(s) from message
    cleaned = message
    if trigger_match:
        cleaned = message[trigger_match.end():].strip()
        # Handle compound triggers: [MORNING_CHECKIN] [WEEKLY_PLANNING]
        second_match = _TRIGGER_RE.match(cleaned)
        if second_match:
            second_trigger = second_match.group(1)
            cleaned = cleaned[second_match.end():].strip()
            # Weekly planning takes precedence over morning checkin
            if second_trigger == "WEEKLY_PLANNING":
                trigger = second_trigger

    # 3. Map trigger to agent
    agent_name = _TRIGGER_MAP.get(trigger or "", "conversation")

    return {
        "agent_name": agent_name,
        "trigger": trigger,
        "is_crisis": False,
        "cleaned_message": cleaned,
    }
