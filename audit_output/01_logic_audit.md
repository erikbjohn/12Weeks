# Agent Logic Audit

## Full Agent Flow Map

### 1. Onboarding Flow
```
User opens app
  → DOMContentLoaded fires
  → 8 parallel API fetches (state, weights, completions, supplements, bodyweight, garmin, workouts, meals)
  → Check: baseline_done && hasWeights?
    ├─ NO  → showWelcome() → "Commit" button
    │         → startOnboardingIntake() → showPsychIntake()
    │           → startPsychConversation()
    │             → POST /api/psych-intake/message (empty body, triggers [START])
    │             → Claude generates opening question ("Why are you here?")
    │             → User responds in chat loop (10-15 exchanges)
    │             → Claude sends [INTAKE_COMPLETE] signal
    │             → generate_intake_report() called with conversation + lifting data
    │             → showPsychReport() displays rendered markdown report
    │             → "Next: Physical Assessment" button
    │               → showBaseline() → 9-lift baseline test (reps at test weight)
    │                 → estimate1RM → workingWeightFrom1RM (75% of est 1RM)
    │                 → Each lift saved immediately via POST /api/weights
    │                 → Summary screen → "Next: Body Measurements"
    │                   → renderBaselineMeasurements()
    │                     → Body weight input, waist input, 3 progress photos (front/side/back)
    │                     → Photos trigger AI analysis via POST /api/photos → Claude Vision
    │                     → "Save & Start Program" → saveBaseline() → baseline_done = true
    └─ YES → renderAll() → checkMorningCheckin()
```

### 2. Daily Flow (Post-Onboarding)
```
User opens app (baseline_done = true)
  → renderAll() (weigh-in, garmin, supplements, phase nav, week tabs, day grid)
  → checkMorningCheckin()
    ├─ Already done today → renderCheckinSummaryBar() (mood/sleep/stress badges)
    └─ Not done → showMorningCheckinOverlay()
        → 6 sliders: sleep, stress, soreness, mood, motivation, anxiety
        → Conditional follow-ups (soreness ≥6, motivation ≤4, anxiety ≥6)
        → submitMorningCheckin()
          → POST /api/morning-checkin (save to DB)
          → POST /api/chat (send summary to Coach)
          → Coach responds with contextual feedback
          → User can reply in mini-chat
          → "Continue to Workout" button → closeMorningCheckin()
            → If Sunday: triggerWeeklyPlanning()
              → Opens chat overlay
              → Sends [WEEKLY_PLANNING] message to Coach
```

### 3. AI Coach Chat (Persistent)
```
User taps chat FAB (💬)
  → toggleChatOverlay() → renderChatOverlay()
  → Loads 7-day history from /api/chat/history
  → User sends message → POST /api/chat
    → _build_coach_context() gathers:
      - 14 days of morning check-ins
      - 14 days of chat history
      - Body weight (all entries, last 14 sent)
      - Garmin data + readiness assessment
      - Current week/phase/workout
      - Supplement status
      - Psych intake report
    → get_coach_response() → Claude Sonnet with full system prompt
    → Response saved to ChatMessage table
```

### 4. Psych Intake Agent
```
Trigger: First-time user OR settings "Redo Psych Intake"
  → POST /api/psych-intake/message with empty body → triggers [START]
  → Claude operates under INTAKE_SYSTEM_PROMPT:
    - Fixed opening sequence (Why here? → Sex → Age → Alcohol commitment → Athlete → Actor)
    - Adaptive middle section (kids, personal questions)
    - 3-strike lockout system for pushback → [INTAKE_LOCKED] → 7-day ban
    - 12-15 exchanges → [INTAKE_COMPLETE]
  → generate_intake_report():
    - REPORT_SYSTEM_PROMPT builds comprehensive psych profile
    - Includes 12-week strategy, game plan, phase breakdowns
    - Fed into Coach context for all future interactions
```

### 5. Overtraining Monitor
```
Trigger: Garmin connected + data available
  → assess_readiness(garmin_data) called on:
    - App load (renderReadiness)
    - Each coach message (_build_coach_context)
  → Weighted composite score:
    - Training Readiness 30%
    - HRV 25%
    - Sleep 20%
    - Body Battery 15%
    - Stress 10%
  → Risk levels: low (≥65), moderate (40-64), high (<40)
  → Displayed in readiness alert bar + fed to Coach
```

### 6. Progress Photo Analysis
```
Trigger: User uploads photo (baseline or weekly)
  → POST /api/photos
  → _analyze_progress_photo():
    - Claude Vision analyzes current pose photo
    - Fetches most recent previous photo of same pose for comparison
    - Includes body weight context
    - Includes psych intake conversation (aspirational body type)
    - Returns: BF% estimate, muscle assessment, progress notes, gap analysis, aesthetic score
```

---

## Logical Gaps, Race Conditions, and Dead Ends

### Critical Issues

1. **Race condition in psych intake conversation storage** (Severity: HIGH)
   - `app.py:708` — The conversation history passed to `get_intake_response()` is `convo[:-1]` (excluding the current user message), but the user message was just appended at line 705. This means Claude sees the conversation *without* the latest user message in its history, but receives it as the `user_message` parameter. This is correct for Claude's `messages` API but fragile — if the list mutation and slicing are ever reordered, messages could be duplicated or lost.

2. **Psych intake role mismatch** (Severity: MEDIUM)
   - Frontend stores messages with role `'coach'` (`app.js:911`), but backend stores them as `'assistant'` (`app.py:726`). The `renderPsychMessages()` function checks for `role === 'user'` vs anything else, so this works, but `renderChatMessages()` checks for `role === 'user'` vs `'coach'` — if psych messages ever flow into the main chat renderer, they'd render incorrectly.

3. **Chat history inconsistency between frontend and backend** (Severity: MEDIUM)
   - Frontend `_chatHistory` uses `{ role: 'coach', text: '...' }` while backend returns `{ role: 'assistant', content: '...' }`. The `renderChatMessages` function handles both (`m.text || m.content`) but `renderChatMessages` checks `m.role === 'user'` and treats everything else as coach. `escapeHtml` is applied to chat messages but NOT to psych intake messages, creating an XSS vector in the psych chat.

4. **No timeout/retry on Claude API calls** (Severity: MEDIUM)
   - `coach.py`, `psych_intake.py`, and `_analyze_progress_photo` all make synchronous Claude API calls with no timeout. A slow response blocks the Flask worker thread. On a single-worker deployment (common on Render free tier), this blocks ALL requests.

5. **Garmin singleton state** (Severity: MEDIUM)
   - `garmin = GarminClient()` at module level means there's one GarminClient instance shared across all requests. The `_mfa_client_state` is stored on this instance — if two users tried to log in simultaneously (unlikely for single-user but possible with multiple tabs), MFA state would be corrupted.

6. **Weekly planning trigger race** (Severity: LOW)
   - `triggerWeeklyPlanning()` uses `localStorage` to prevent duplicate triggers, but the coach message is sent before `localStorage.setItem()`. If the network call fails, the flag is never set and it won't retry. If it succeeds but the user closes the tab during the response, the flag IS set but the user never sees the response.

7. **Dead end: INTAKE_LOCKED with no recovery path shown** (Severity: LOW)
   - When the psych intake locks the user out for 7 days, the frontend receives `locked: true` but `sendPsychMessage()` doesn't handle this — it just displays the response text. The user has no visual indication of what to do next or when they can return. The app effectively stalls at the intake screen with no way forward.

8. **Missing error boundary in morning check-in flow** (Severity: LOW)
   - If the POST to `/api/chat` fails after submitting the morning check-in (line 1540-1569 in app.js), the loading indicator is hidden and the "Continue to Workout" button appears, but the coach response area stays empty. No error message is shown.

### Minor Issues

9. **`apiPost` fire-and-forget** — The helper function at `app.js:25` catches errors but only logs them. No retry, no user notification. Weight recordings, completion toggles, and supplement logs can silently fail.

10. **`_build_coach_context` fetches ALL body weight entries** (`app.py:839`) and then slices to last 14. For a long-running user, this query grows unbounded.

11. **Photo analysis sends up to 2000 chars of psych intake conversation** (`app.py:984`) — this is a truncation that could cut mid-sentence, confusing Claude about the aspirational reference.

12. **`max_tokens=800` on coach responses** (`coach.py:48`) — given the "1-3 sentences, ONE question" format instruction, 800 tokens is generous but could still truncate if the coach goes long (especially early interactions where the system prompt asks for opening sequences).

---

## Error Handling Assessment

### Agents Without Error Handling or Fallback

| Agent/Module | Error Handling | Fallback | Notes |
|---|---|---|---|
| `get_coach_response()` | Try/catch with generic message | Returns "Coach is temporarily unavailable" | **Good** — graceful degradation |
| `get_intake_response()` | Try/catch with generic message | Returns "Intake temporarily unavailable" | **Good** — but no retry |
| `generate_intake_report()` | Try/catch, returns error string | Error string shown as "report" | **Bad** — error message rendered as if it's a report |
| `_analyze_progress_photo()` | Try/catch, returns status string | "Photo saved. Analysis failed" | **Good** — photo still saved |
| `assess_readiness()` | No errors possible (pure logic) | Returns "unknown" risk | **Good** |
| `GarminClient.login()` | Try/catch with rate limiting | Returns (False, error_msg, False) | **Good** — 15-min cooldown on 429 |
| `GarminClient._cached()` | Try/catch, returns stale cache | Falls back to cached data | **Good** — graceful degradation |
| Frontend `apiPost()` | Catch only, logs error | **No fallback** | **Bad** — silent data loss |
| Frontend init (`DOMContentLoaded`) | Try/catch with empty-data fallback | Renders with empty caches | **Acceptable** |
| `submitMorningCheckin()` | No error handling on POST | Fire-and-forget | **Bad** — check-in could be lost |

---

## Confidence Scores (Logic Soundness)

| Agent | Score | Rationale |
|---|---|---|
| **Psych Intake** | 7/10 | Well-structured conversation flow with lockout mechanism. Role mismatch and locked-state dead end are concerns. Report generation is robust. |
| **AI Coach** | 8/10 | Excellent context assembly. System prompt is comprehensive and well-structured. Chat history management works. Main risk: synchronous blocking on Claude API. |
| **Overtraining Monitor** | 9/10 | Clean, stateless, well-weighted algorithm. Handles missing data gracefully. Good risk thresholds. |
| **Progress Photo Analyzer** | 7/10 | Vision analysis is solid. Aspiration context truncation is sloppy. Comparison photo logic works but only looks at most recent — doesn't find best match. |
| **Garmin Integration** | 7/10 | Good caching, token persistence, rate limit handling. Singleton state is a risk. MFA flow works but is fragile. |
| **Onboarding Flow** | 6/10 | Complex multi-step flow that mostly works. The transitions between psych intake → baseline → measurements → start are manually chained with no state machine. If any step fails, recovery is unclear. Locked-out users hit a dead end. |
| **Morning Check-in** | 8/10 | Clean slider UI with smart conditional follow-ups. Coach integration works well. Sunday planning trigger is clever. Minor: fire-and-forget data save. |
| **Weight Progression** | 8/10 | RPE-based progression logic is sound. Phase transitions handle +20%/+10% jumps correctly. Deload detection works. |

---

## Recommendations (Priority Order)

1. **Add request timeout to all Claude API calls** — Use `anthropic.Anthropic(timeout=30)` or similar to prevent worker thread starvation.
2. **Handle INTAKE_LOCKED state in frontend** — Show countdown timer, hide chat input, offer "Return to welcome" or similar escape hatch.
3. **Add retry/confirmation to critical `apiPost` calls** — At minimum, weight recordings and morning check-ins should confirm success or show retry.
4. **Fix XSS in psych chat messages** — Apply `escapeHtml()` to psych intake messages before rendering.
5. **Add error state to `generate_intake_report` rendering** — Don't render error strings as if they're reports.
