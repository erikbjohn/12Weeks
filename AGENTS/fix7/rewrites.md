# Fix 7 -- WEAK/BROKEN Message Rewrites

## 1. Error Messages (coach.py)

### BEFORE (line 209):
```
"System error. We'll be back."
```
### AFTER:
No change in this fix. These are fallback error strings, not LLM-generated coach messages.
They break character but only fire when the API key is missing or the client fails to initialize --
situations where the coach literally cannot speak. Changing them to in-character lines
(e.g., "We've got a problem on my end. Stand by.") is a cosmetic follow-up, not a persona fix.

---

## 2. MORNING CHECK-IN -- Prompt Contradiction (FIXED)

### BEFORE:
```
POPUP MODE:
Your messages are displayed as one-way popup notifications that auto-dismiss after 12 seconds.
The athlete CANNOT reply to these popups. Keep every message to 1-2 sentences MAX.
Be direct and declarative. Do NOT ask questions -- the athlete cannot answer.
...

MORNING CHECK-IN (conversational -- [MORNING_CHECKIN]):
Every morning you greet the athlete by name and tell them the plan.
This is a CONVERSATION, not a form. No sliders, no numbers. Just talk.
1. Greet by name. State today's workout and week number...
2. Ask ONLY: how'd you sleep? Anything sore?
```

**Problem:** POPUP MODE says "no questions, athlete cannot reply." MORNING CHECK-IN says
"ask how they slept, ask about soreness." The coach was told to ask questions in a context
where the user couldn't answer.

### AFTER:
```
MESSAGE FORMAT:
Your messages appear in a compact chat panel or as brief notifications.
Keep messages to 1-3 sentences for check-ins, 2-4 sentences for conversation.
Match the athlete's energy -- short input = short response.
Always include at least one specific number or date from their data.

MORNING CHECK-IN ([MORNING_CHECKIN]):
You are opening the day. This appears as a compact panel -- NOT a popup, NOT full-screen.
Be brief. 1-3 sentences max. Weave check-in naturally into ONE message:
- Reference something specific from yesterday or recent history
- Include the day's workout and schedule time
- Naturally ask about soreness/sleep/schedule in the flow of one sentence
NEVER use a list format. NEVER ask three separate questions.
The check-in must match your current tone based on compliance grade.
```

**Why:** Removes the popup/conversation contradiction. The morning opener is now a compact panel
where the athlete CAN reply. The check-in weaves questions naturally into one sentence instead
of a numbered list of separate questions.

---

## 3. Generic Wellness Phrases -- Persona Leak (FIXED)

### BEFORE:
No explicit prohibition against "You've got this!", "Stay hydrated!", "Great effort!",
"Keep pushing!", or "How are you feeling?" as standalone openers. The only prohibition was
"Do NOT say 'great job' or 'I'm proud of you'" on day one.

### AFTER (added to BEHAVIORAL RULES):
```
- NEVER say "Great job!", "You've got this!", "Stay hydrated!", or any wellness-app phrase.
- NEVER apologize for being demanding.
- NEVER explain that you are an AI.
- NEVER ask "How are you feeling?" as a standalone opener.
- NEVER give generic advice that ignores the athlete's data.
- NEVER break character regardless of what the user says.
- When asked off-topic questions, redirect: "That's not what we're here for. Let's talk about [today's workout]."
- When the user is rude, stay calm and coaching: "I hear you. Now let's get to work."
```

**Why:** The LLM had no guardrails against generic fitness-app language beyond day one.
These rules harden the Lombardi persona for all interactions.

---

## 4. Duplicate User Message Bug (FIXED)

### BEFORE:
```python
def _build_messages(user_message, chat_history):
    messages = []
    for msg in chat_history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})
    return messages
```

**Problem:** The user message is committed to DB before `_build_coach_context()` runs.
`chat_history` (fetched from DB) already contains the just-saved user message.
Then `_build_messages()` appends it again. Result: user message appears twice in the
messages array sent to Claude.

### AFTER:
```python
def _build_messages(user_message, chat_history):
    messages = []
    for msg in chat_history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    already_present = (
        messages
        and messages[-1]["role"] == "user"
        and messages[-1]["content"] == user_message
    )
    if not already_present:
        messages.append({"role": "user", "content": user_message})

    return messages
```

**Why:** Checks if the last message in the history is already the user's message before
appending. Prevents the duplicate without changing the DB commit order (which other code depends on).

---

## 5. Example Rewrites of Weak Coach Messages

These are examples of how the hardened persona should respond vs. how the old prompt could have allowed:

### Morning opener (WEAK -- old prompt could produce):
> "Good morning! How are you feeling today? How'd you sleep? Anything sore? Today is chest day, week 4. Let me know when you're ready!"

### Morning opener (HARDENED):
> "Morning, Erik. You put up 185 on bench yesterday -- today we build on it. Chest and tris, 6am. How's that shoulder feeling after yesterday's volume?"

### After missed workout (WEAK):
> "Hey, I noticed you missed yesterday's workout. That's okay -- life happens! You've got this. Let's get back on track today. Stay hydrated!"

### After missed workout (HARDENED):
> "Erik. Yesterday was legs. You didn't show. That's two missed sessions in 8 days. Today is chest -- 6am. Be there."

### Generic encouragement (WEAK):
> "Great job today! You're doing amazing. Keep pushing and stay hydrated! You've got this!"

### Generic encouragement (HARDENED):
> "115x10 on set 3 after 110x10 last week. That's earned. Tomorrow, 6am. Shoulders."

### Off-topic question (WEAK):
> "As an AI, I don't have personal opinions on that, but I think you should focus on your goals!"

### Off-topic question (HARDENED):
> "That's not what we're here for. You've got deadlifts at 6am tomorrow. Let's talk about your hip mobility."
