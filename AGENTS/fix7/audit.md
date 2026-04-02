# Fix 7 Audit -- Coach Chat System

## SECTION 1: DATABASE

### ChatMessage model (`chat_message` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| role | String(20) | "user" or "assistant" |
| content | Text | The message body |
| log_date | Date | Defaults to `date.today()`, indexed |
| user_id | Integer | FK to user, indexed |
| created_at | DateTime | Defaults to `datetime.now(timezone.utc)` |

**No columns for:** message_type/tag (e.g. MORNING_CHECKIN vs normal chat), streaming state, read/unread status.

### MorningCheckIn model (`morning_checkin` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| log_date | Date | Indexed |
| sleep_quality | Integer | 1-10 |
| stress_level | Integer | 1-10 |
| soreness | Integer | 1-10 |
| mood | Integer | 0-10 (depressed to manic) |
| motivation | Integer | 1-10 |
| anxiety | Integer | 1-10 |
| notes | Text | Free text; also used for `[MISSED]` marker |
| user_id | Integer | FK to user, indexed |
| created_at | DateTime | UTC default |

### CoachMemory model (`coach_memory` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK to user, indexed |
| content | Text | The summary text |
| memory_type | String(30) | "summary", "commitment", "injury", "observation" |
| created_at | DateTime | UTC default |
| week | Integer | Which program week this was recorded |

### Daily State Tracking
- **No dedicated daily state table** exists. Daily state is reconstructed from:
  - `MorningCheckIn` for the day
  - `ChatMessage` filtered by `log_date`
  - `MealLog` for the day
  - `SupplementLog` for the day
  - `DayCompletion` / `ExerciseCompletion` for the day
- Morning check-in "missed" status is encoded as a `[MISSED]` string inside the `notes` column, not a boolean field.

---

## SECTION 2: LLM INTEGRATION

### Model
- **Main chat:** `claude-opus-4-20250514` (both `/api/chat` and `/api/chat/stream`)
- **Memory extraction:** `claude-sonnet-4-20250514` (lighter model, called after every 5th message)

### Streaming
- **YES, streaming exists.** Both endpoints are implemented:
  - `POST /api/chat` -- non-streaming, returns full JSON `{response, time}`
  - `POST /api/chat/stream` -- SSE streaming via `client.messages.stream()`

### System Prompt (`_build_system_prompt`)
Full text is ~638 lines (lines 249-638 in coach.py). Key sections in order:

1. **CRITICAL SAFETY WARNING** -- food/allergen safety (lines 432-448)
2. **Food safety details** -- dietary restrictions, fasting protocol, selected food list (lines 337-388)
3. **Minor athlete safety** -- conditional block for under-18 (lines 404-415)
4. **MISSION** -- "Align aspirations with actions."
5. **IDENTITY** -- "Coach Erik." Lombardi/Goggins/Brooks persona.
6. **ABSOLUTE RULE -- DIRECTIVES NOT QUESTIONS** -- Never ask about logistics, tell them.
7. **PRINCIPLES** -- Honesty first, no manipulation, empathy without softness, accountability, standard is the standard.
8. **PLAN AUTHORITY** -- Don't let athlete modify the plan.
9. **BEHAVIORAL RULES** -- Excuse handling, validation seeking, crisis, breakthrough, self-deception.
10. **TONE** -- Dynamically set based on `compliance_grade` (A+ through F, each with distinct tone).
11. **FORMAT** -- "1-2 sentences max. No fluff."
12. **POPUP MODE** -- Messages are one-way popup notifications. Athlete cannot reply. Keep to 1-2 sentences.
13. **CONTEXT AWARENESS** -- Reference specific numbers, compare to history, connect to goals.
14. **SESSION STRUCTURE** -- State commitment, name obstacle, state next hard thing.
15. **ATHLETE CONTEXT** -- Week, phase, focus, deficit.
16. **CURRENT STATE** -- Body weight, workout, Garmin, readiness, check-in summary, session analysis, weekly summary, missed checkin alert, supplements.
17. **Full data blocks** -- Goal, exercise history, today's sets, run history, physical assessment, measurements, equipment, meals, completions, schedule notes, coach memories, intake report, scheduled activities.
18. **MONITORING** -- Overtraining and mental health thresholds.
19. **TRAINING ENGINE** -- Never contradict weight targets.
20. **Event-specific instructions** -- SUNDAY PLANNING, WORKOUT FEEDBACK, MORNING CHECK-IN, MORNING BRIEFING, MEALS COMPLETE, END OF DAY.
21. **Time reference rule** -- Never mention UTC/GMT.
22. **Crisis protocol** -- 988 Lifeline reference.

### Context Passed (`_build_coach_context` in app.py, lines 2321-2589)
The context dict contains **35 keys**:
- `checkins` -- last 14 days of MorningCheckIn
- `chat_history` -- last 14 days of ChatMessage
- `garmin` -- today's Garmin summary (HRV, sleep score, body battery, stress)
- `readiness` -- overtraining assessment derived from Garmin
- `bodyweight` -- last 14 entries of body weight
- `workout_today` -- today's planned workout from the training plan
- `week` -- current week number
- `phase` -- phase info (label, focus, deficit)
- `supplements_today` -- today's supplement log
- `intake_report` -- psych intake report
- `athlete_name` -- user's name
- `user_timezone` -- user's timezone string
- `scheduled_activities` -- committed schedule items
- `food_restrictions` -- dietary restrictions
- `custom_allergies` -- allergy text
- `selected_foods` -- approved food list from onboarding
- `fasting_protocol` -- e.g. "16:8"
- `goal` -- full training goal (type, target weight, calories, macros, fasting)
- `exercise_history` -- last 3 sessions per exercise (up to 200 logs)
- `today_sets` -- per-set data for today
- `run_history` -- last 14 run logs
- `physical_assessment` -- baseline physical data
- `body_measurements` -- latest body measurements
- `equipment` -- available equipment list
- `meals_today` -- today's meal log
- `meal_plan_today` -- today's prescribed meal plan
- `completed_days_this_week` -- which days are done this week
- `schedule_notes` -- schedule notes from constraints
- `coach_memories` -- last 20 coach memories
- `compliance_grade` -- letter grade for tone selection
- `missed_checkin_today` -- boolean if morning checkin was missed
- `session_analysis` -- latest session analysis
- `weekly_summary` -- weekly training summary

### Message History Assembly (`_build_messages`, lines 692-708)
- Takes the last **20 messages** from `chat_history` (which itself is last 14 days).
- Appends the new user message.
- **No deduplication** -- if the chat_history already contains the just-saved user message (it does, since user_chat is committed before `_build_coach_context` is called in the non-streaming path), the user message may appear twice in the messages array.
- **No system message injection per-turn** -- all context is in the single system prompt.

### Memory Extraction
- Called after every response, but only actually runs on every 5th message (`chat_len % 5 != 0`).
- Uses Sonnet with a 15-second timeout.
- Extracts types: injury, commitment, preference, observation, milestone.
- Runs in a background thread (non-blocking).
- Last 20 memories are loaded into the system prompt.

---

## SECTION 3: FRONTEND

### `showCoachPopup(message)` (lines 71-93)
- Creates a **full-screen overlay** (`position: fixed; inset: 0 0 0 0; z-index: 9000`).
- Dark semi-transparent backdrop (`rgba(0,0,0,0.6)`).
- Centered card with max-width 500px.
- Displays "ERIK" label and the message.
- Dismissed **only via X button** -- no auto-dismiss, no tap-to-dismiss.
- Queues popups if one is already showing (`_coachPopupQueue`).
- Pushes message to `_chatHistory` array so it shows in the full chat overlay.
- Uses `escapeHtml()` for XSS protection.

### Chat Overlay (`toggleChatOverlay`, `renderChatOverlay`) (lines 4216-4258)
- **Full-screen overlay** (`position: fixed; inset: 0; z-index: 160`).
- Toggle via `_chatOverlayOpen` boolean.
- Contains: header ("Coach Erik" + close button), messages container, input bar.
- Input bar has: text input, microphone button, send button.
- Preserves scroll position across open/close.
- Input gets auto-focused on open.

### `sendChatMessage()` (lines 4303-4389)
- Gets text from input, clears input.
- Pushes user message to `_chatHistory`, re-renders.
- Shows typing indicator (3 bouncing dots).
- **Uses streaming endpoint** (`/api/chat/stream`) via `fetch` + `ReadableStream` reader.
- 60-second AbortController timeout.
- Parses SSE `data:` lines, handles `[DONE]` and `[ERROR]` sentinels.
- Creates a streaming bubble that updates in real-time as chunks arrive.
- On completion, pushes coach response to `_chatHistory`.
- On error (abort or network): pushes error message to history.
- **NO DOUBLE-SEND PROTECTION** -- user can click Send or press Enter while the coach is still responding. There is no `_chatSending` lock, no button disable, no input disable.

### Typing Indicator
- CSS class `chat-typing` with 3 dots that bounce via CSS animation.
- Shown when waiting for streaming to start.
- Removed once the first streaming chunk arrives (replaced by streaming bubble).

### Chat History Loading (`loadChatHistory`, lines 4193-4202)
- Fetches from `/api/chat/history?days=7&limit=50`.
- Stores in global `_chatHistory` array.
- Called during initial data load (`initData` flow, line 3604).
- Updates FAB pulse state after load.

### Chat FAB (Floating Action Button)
- CSS defined (`.chat-fab` at line 2516 in style.css), styles exist, pulse animation exists.
- **DEAD CODE** -- the FAB element (`#chat-fab`) is never created in HTML or JS. `updateChatFabPulse()` calls `getElementById('chat-fab')` which always returns null. The function silently returns.

### Voice Input
- Implemented via Web Speech API (`webkitSpeechRecognition`).
- Microphone button in chat input bar.
- Supports interim results.
- Falls back with toast error on unsupported browsers.

### Additional Chat Containers
- `syncChatContainers()` syncs between `chat-overlay-messages` and `coach-messages`.
- `renderInlineChat()` renders chat in an inline container (deprecated but code remains).
- `renderCoachTop()` is explicitly a no-op (line 5514): "replaced by popup system".

---

## SECTION 4: COACH PERSONALITY -- WEAK/BROKEN MESSAGES

### System Prompt Strengths
The system prompt is extensive and well-crafted. It explicitly forbids:
- "Great job" and "I'm proud of you" on day one (line 600)
- Asking about logistics/schedule (lines 457-466)
- Moving past unmet commitments
- Accepting "I'll try"
- Hollow praise

### Potential Weakness Points

1. **No explicit "As an AI" prohibition.** The system prompt never says "Do not say 'As an AI'" or "Never break character." Claude's default behavior could surface this, especially under pressure or unusual inputs.

2. **Tone instructions conflict with FORMAT instructions.** The tone section (lines 419-430) describes detailed emotional stances (warm, fatherly, furious), but the FORMAT rule says "1-2 sentences max." These can conflict -- being "furious in the Lombardi tradition" with "short sentences" and "relentlessly confrontational" is hard to do in 1-2 sentences.

3. **POPUP MODE conflict with MORNING CHECK-IN.** The system prompt says popup messages are "one-way" and the athlete "CANNOT reply." But the MORNING CHECK-IN section says "This is a CONVERSATION" and instructs the coach to "Ask ONLY: how'd you sleep? Anything sore?" This contradicts the popup directive. In practice, the morning check-in fires via the non-streaming `/api/chat` endpoint and shows as a popup (which the user can't reply to), so the coach is told to ask questions the user can't answer.

4. **Generic error messages in code (not LLM output):**
   - `"System error. We'll be back."` (coach.py line 209)
   - `"Technical issue. Try again in 60 seconds."` (coach.py line 216)
   - `"Erik stepped away. He'll be back in a moment."` (coach.py line 231)
   - `"Erik stepped away. He'll be back in a moment."` (app.js line 4363, on `[ERROR]`)
   - `"Response took too long. Try again."` (app.js line 4381, on AbortError)
   - `"Connection error. Try again."` (app.js line 4381, on other errors)
   - `"Connection issue. Try again."` (app.js line 5046)
   These are fine for error handling but break character -- Erik wouldn't say "system error."

5. **The coach-popup-label hardcodes "ERIK"** (line 83 in app.js) rather than using the athlete's coach name from context. Not a personality break, but rigid.

6. **"Stay hydrated" is not in the code.** The system prompt doesn't use this phrase. However, there is no explicit prohibition against the LLM generating generic wellness platitudes beyond day-one restrictions. The LLM could still produce "Stay hydrated" or "You've got this" on subsequent days.

---

## SECTION 5: FAILURE MODES

### Slow Connection / Timeout
- **Streaming endpoint (`/api/chat/stream`):**
  - Server-side: `anthropic.Anthropic(timeout=30.0)` -- 30 second timeout to Anthropic API.
  - Client-side: `AbortController` with 60-second timeout.
  - If server times out, `[ERROR]` sentinel is sent. JS shows "Erik stepped away."
  - If client times out (AbortError), JS shows "Response took too long. Try again."
  - **No retry logic** on either side.

- **Non-streaming endpoint (`/api/chat`):**
  - Server-side: same 30-second Anthropic timeout.
  - Client-side: no explicit timeout (default browser timeout, typically 2+ minutes).
  - Returns JSON error string on failure.
  - Used by popup triggers (morning check-in, end-of-day, workout complete).

### User Sends Message While Coach Is Responding
- **NO PROTECTION.** There is no lock, no `_chatSending` flag, no button/input disable.
- User can spam Enter/Send while streaming is active.
- Each send creates a new streaming connection.
- Multiple streaming bubbles could appear simultaneously.
- The `_chatHistory` array will get interleaved user/coach messages in wrong order.
- The typing indicator uses an id (`chat-typing-{containerId}`) so removing it targets the latest one, but multiple could exist.

### Daily Opener Mechanism
1. **Morning popup** (`triggerMorningPopup`, line 5516):
   - Called during `renderAll()` which runs on page load.
   - Before noon: sends `[MORNING_CHECKIN]` message to `/api/chat` (non-streaming).
   - Shows response as full-screen popup via `showCoachPopup()`.
   - Auto-records a morning check-in with all values set to 5 (hardcoded neutral).
   - After noon: if no popup fired, marks as `[MISSED]` with all values 0.
   - Dedup via `localStorage` key `popup_morning_{date}`.
   - Checks if coach already spoke today -- skips if any coach messages exist for today.

2. **End-of-day popup** (`triggerEndOfDayPopup`, line 5578):
   - Only fires after 8pm.
   - Only fires if today's workout is complete.
   - Sends `[END_OF_DAY]` message to `/api/chat`.
   - Shows as popup.
   - Dedup via localStorage.

3. **Workout complete popup** (triggered from workout completion flow):
   - Sends `[WORKOUT_COMPLETE]` to `/api/chat`.
   - Shows as popup.

4. **Meals complete popup** (triggered when all meals checked):
   - Sends `[MEALS_COMPLETE]` to `/api/chat`.
   - Shows as popup.

### Streaming Implementation Details
- **Server:** Uses `client.messages.stream()` context manager with `text_stream` iterator.
- **Wire format:** `data: {text_chunk}\n\n` (SSE-style but plain text chunks, not JSON).
- **Termination:** `data: [DONE]\n\n` on success, `data: [ERROR]\n\n` on failure.
- **Response saved:** In the `finally` block, the full accumulated text is saved as a `ChatMessage` -- even partial text if the stream was interrupted.
- **No memory extraction on streaming path.** The `/api/chat/stream` endpoint does NOT call `extract_memories()`. Only the non-streaming `/api/chat` endpoint does. This means interactive chat messages (all user-initiated) never trigger memory extraction. Only popup-triggered messages (morning, EOD, workout complete, meals) trigger it.
- **GeneratorExit handling:** If client disconnects mid-stream, catches `GeneratorExit` and logs a warning. The `finally` block still saves partial text.

### Other Issues Found

1. **Duplicate user message in context.** In `/api/chat` (non-streaming), the user message is committed to DB *before* `_build_coach_context()` is called. `_build_coach_context()` fetches all ChatMessages from the last 14 days. So the just-saved user message is included in `chat_history`. Then `_build_messages()` appends the user message again. Result: the user's message appears twice in the messages array sent to Claude. The streaming endpoint has the same issue.

2. **Chat history date filter uses server `date.today()`**, not user's local date. If user is in a timezone where their local date differs from UTC, the 14-day window may be off by a day.

3. **No markdown rendering.** Coach responses are rendered via `escapeHtml()` which converts everything to plain text. Any markdown formatting (bold, lists, links) from the LLM appears as raw text.

4. **Morning check-in auto-fills neutral values (all 5).** When the morning popup fires, it auto-records sleep=5, stress=5, soreness=5, mood=5, motivation=5, anxiety=5 with notes "Auto-completed via morning popup." This means the coach gets fake neutral data -- the athlete never actually reported how they feel.

5. **`max_tokens=800` is low.** For a coach that's supposed to give specific workout feedback referencing multiple exercises, 800 tokens is tight. However, the system prompt says "1-2 sentences max," so this may be intentional to enforce brevity.

6. **No error handling on `db.session.commit()` in streaming path.** Line 2266 does `db.session.commit()` with no try/except when saving the user message in the streaming endpoint (unlike the non-streaming path which has try/except).
