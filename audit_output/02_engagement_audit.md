# Engagement Audit

## User Touchpoint Analysis

### Complete Touchpoint Map

| # | Touchpoint | Agent | Type | User Action Required |
|---|---|---|---|---|
| 1 | Welcome screen | None | Static | Tap "Commit" |
| 2 | Psych intake chat | Intake Agent | Conversational (10-15 exchanges) | Type responses |
| 3 | Psych report display | Report Generator | Read-only | Tap "Next" |
| 4 | Baseline lift test (x9) | None | Data entry | Enter reps per lift |
| 5 | Baseline summary | None | Read-only | Tap "Next" |
| 6 | Body measurements + photos | Photo Analyzer | Mixed | Enter data + take photos |
| 7 | Morning check-in (daily) | None | 6 sliders + text | Adjust sliders, submit |
| 8 | Coach morning response | Coach Agent | Read + optional reply | Read, optionally chat |
| 9 | Weigh-in bar (daily) | None | Single input | Enter weight |
| 10 | Supplement tracker (daily) | None | Toggle buttons | Tap pills |
| 11 | Garmin metrics display | Overtraining Monitor | Read-only | None (auto) |
| 12 | Readiness alert | Overtraining Monitor | Read-only | None (auto) |
| 13 | Workout detail view | None | Interactive | View exercises, log RPE/weight |
| 14 | Meal plan tracker | None | Checkbox + adjust | Mark meals, adjust portions |
| 15 | Coach chat (FAB) | Coach Agent | Conversational | Open overlay, type |
| 16 | Weekly check-in (Sat/Sun) | None | Sliders + text | Submit weekly review |
| 17 | Sunday planning | Coach Agent | Auto-triggered chat | Respond to coach |
| 18 | Progress dashboard | None | Charts | View only |
| 19 | Weekly progress photos | Photo Analyzer | Photo upload | Take + upload photos |

---

## Drop-Off and Stuck Points

### 1. Psych Intake — The Biggest Risk (HIGH IMPACT)

**Problem:** The psych intake is a 10-15 message conversation with no progress indicator, no save-resume clarity, and no way to skip. A user who gets interrupted mid-conversation has no idea if their progress is saved.

**Evidence from code:**
- `startPsychConversation()` does check for existing conversations on re-entry (`app.js:880-895`) — so progress IS saved. But nothing in the UI communicates this.
- There's no "X" button, no "Continue later" option, no progress bar.
- If the coach triggers `[INTAKE_LOCKED]`, the user sees the lockout message but has NO way to close the overlay or navigate elsewhere. The app is effectively bricked for 7 days.

**Impact:** This is the FIRST thing a new user experiences. If they drop off here, they never see the product.

### 2. Baseline Lift Test — Tedious for Beginners (MEDIUM IMPACT)

**Problem:** 9 sequential lift tests requiring the user to physically load a barbell and perform max reps. No way to skip individual lifts. No "I don't know this exercise" option. No video/form guidance.

**Evidence:**
- `BASELINE_LIFTS` includes barbell hip thrusts — an exercise many beginners don't know
- The dot-progress indicator helps (`app.js:462`) but there's no time estimate
- Each lift is saved immediately (`baselineNext()` POSTs to `/api/weights`) — good for data safety, but the user doesn't know this

### 3. Morning Check-in — Blocks the Entire App (MEDIUM IMPACT)

**Problem:** The morning check-in overlay (`showMorningCheckinOverlay()`) covers the entire screen with no dismiss option. The user MUST complete it before accessing their workout. There's no "Skip" or "Later" button.

**Evidence:** `app.js:1376-1455` — the overlay has no close button. Only the "Submit Check-In" button provides an exit path.

### 4. Coach Chat — No Conversation Starters (LOW IMPACT)

**Problem:** The chat overlay opens to an empty state (if no history) or old messages. There's no prompt, no suggested questions, no quick-action buttons. The user has to figure out what to say to their coach.

**Evidence:** `renderChatOverlay()` (`app.js:1739-1764`) renders a blank message area and an input placeholder "Talk to Coach..." — that's it.

---

## Latency Bottlenecks

### 1. Synchronous Claude API Calls (CRITICAL)

**Where:** Every coach message, every intake message, every photo analysis, every intake report generation.

**Impact:** Claude Sonnet responses typically take 2-8 seconds. During this time:
- The Flask worker thread is blocked
- On single-worker deployments, ALL other requests queue
- The user sees typing indicators but if they try to navigate, the app freezes

**Specific worst case:** `generate_intake_report()` uses `max_tokens=4096` — this can take 15-30 seconds. During this time, the entire app is unresponsive.

### 2. 8 Parallel Fetches on Load (MEDIUM)

**Where:** `DOMContentLoaded` handler (`app.js:1162-1171`)

**Impact:** The app fires 8 API calls simultaneously. This is actually well-optimized via `Promise.all()`. However, the Garmin status check + subsequent `refreshGarmin()` (2 more fetches) happens sequentially after the initial batch, adding 1-3 seconds to perceived load time.

### 3. Photo Upload + Analysis (MEDIUM)

**Where:** `handleBaselinePhotoCapture()` and `/api/photos` POST

**Impact:** Photo compression happens client-side (good), but then the base64 image is sent in a JSON POST body, followed by synchronous Claude Vision analysis. Total time: 5-15 seconds per photo. During baseline, user might upload 3 photos back-to-back.

**Mitigation already in place:** Photos show "AI Coach is analyzing..." with a spinner. This is good feedback.

### 4. Coach Context Assembly (LOW)

**Where:** `_build_coach_context()` (`app.py:813-888`)

**Impact:** Queries 6 different database tables synchronously. For a mature user with months of data, the `BodyWeight.query.order_by(BodyWeight.log_date).all()` could return hundreds of rows. Not a problem yet, but will degrade over time.

---

## Missing Feedback Loops

### 1. Weight and Completion Saves — No Confirmation

When a user logs a weight or toggles a completion checkbox, `apiPost()` fires and forgets. If the network is flaky (common on phone in a gym), data is silently lost. The UI optimistically updates the cache but never confirms the server received it.

**Fix:** Add a subtle toast or checkbox color flash on successful save. Show a red indicator on failure with retry.

### 2. Supplement Toggles — No Daily Summary

Users can toggle supplements throughout the day, but there's no end-of-day summary or reminder for missed supplements. The Coach doesn't proactively mention missed supplements unless asked.

**Fix:** Add a "You missed: Fish Oil, Vitamin D3" nudge in the evening, or have the Coach mention it if the morning check-in is done but supplements are incomplete by afternoon.

### 3. No Progress Milestones or Celebrations

The app tracks weight loss, lift progression, and completion rates, but never proactively celebrates milestones. No "You've lost 5 lbs!" or "Bench press PR!" or "Perfect week — all workouts completed!"

**Fix:** Check for milestones in `renderAll()` and show a brief banner. Feed milestones into the Coach's context so it can reference them naturally.

### 4. No "Streak" Visibility

The app is called "12 Weeks" and tracks daily completion, but there's no streak counter, no week-over-week comparison, no visual progress toward the 12-week goal. The footer says "Lift first - Run after - Done by 9am" but there's no accountability for the daily running streak.

### 5. Garmin Connection — No Nudge to Connect

If Garmin isn't connected, the bar shows "Connect Garmin Watch" — but there's no explanation of WHY connecting matters. The overtraining monitor, readiness alerts, HRV trends, and sleep analysis all depend on Garmin data.

---

## Robotic/Vague/Unhelpful Copy — Rewrites

### Current → Proposed

**Welcome Screen:**
- Current: `"Commit"` (button)
- Proposed: `"I'm Ready"` — "Commit" is confrontational before the user even knows what they're committing to.

**Morning Check-in Title:**
- Current: `"Good Morning"` → `"Quick check-in before we start"`
- Proposed: `"Before we train"` — connects the check-in to the workout that follows.

**Morning Check-in Coach Loading:**
- Current: `"Coach is reviewing your check-in..."`
- Proposed: `"Erik is looking at your numbers..."` — use the coach's name, make it personal.

**Coach Chat Placeholder:**
- Current: `"Talk to Coach..."`
- Proposed: `"Ask Erik anything..."` — name + permission to ask anything.

**Readiness Alert (Low Risk):**
- Current: `"You're good to go. Train as planned."`
- Proposed: `"Green light. Hit it hard today."` — matches the coach's direct tone.

**Readiness Alert (Moderate):**
- Current: `"Consider reducing volume by 1-2 sets per exercise, or dropping intensity by 10%. Focus on form over load."`
- Proposed: `"Your body's talking — listen. Drop 1-2 sets or 10% weight. Form over ego today."` — coach voice, not medical advice voice.

**Readiness Alert (High):**
- Current: `"Consider swapping today's session for active recovery (20-30 min walk, mobility work). Your body is signaling it needs rest."`
- Proposed: `"Stand down. Walk, stretch, recover. Pushing through this is how you lose a week, not gain a day."` — direct, consequential.

**Garmin Not Connected:**
- Current: `"Connect Garmin Watch"` (button)
- Proposed: `"Connect Garmin — unlock HRV, sleep, and readiness tracking"` — explain the value.

**Check-in Submitted:**
- Current: `"Check-in submitted!"` (weekly)
- Proposed: `"Week ${week} logged. See you Monday."` — specific, forward-looking.

**Intake Locked:**
- Current: `"You're locked out for X more days. Come back when you've been alcohol-free for 7 days."`
- Proposed: Same message but ADD: a close button, a countdown timer, and "Set a reminder" option.

---

## Top 3 Engagement Improvements (Priority Ranked)

### 1. Add Coach-Initiated Morning Briefing (HIGH IMPACT, MEDIUM EFFORT)

**What:** Instead of a silent check-in form, open the morning with the Coach greeting the user based on yesterday's data and today's plan. "You slept 7.5 hours, body battery is 68. Today is bench day. How are you feeling?"

**Why:** The current flow is: fill out form → wait for coach → get generic response. Flipping it so the Coach speaks first makes the interaction feel like a real coaching session, not a medical intake form.

**How:** Pre-fetch Garmin data before showing the check-in overlay. Show the Coach's opening message first, then show sliders as the user's response to the Coach's question. This reframes data entry as conversation.

### 2. Fix the Intake Dead-End and Add Progress Indicator (HIGH IMPACT, LOW EFFORT)

**What:**
- Add a message counter to the intake chat ("4 of ~12")
- Add a "Continue later" button that saves and dismisses
- Handle INTAKE_LOCKED with a proper UI: countdown, close button, return path
- Show "Your progress is saved" on re-entry

**Why:** The psych intake is the first 5-10 minutes of the product experience. If a user gets stuck, interrupted, or locked out, they never come back.

### 3. Add Milestone Detection and Celebration (MEDIUM IMPACT, LOW EFFORT)

**What:** Detect and surface achievements: first week complete, weight PR on any lift, body weight milestones (every 2 lbs lost), streak achievements (7 days, 14 days), perfect adherence weeks.

**Why:** The app collects rich data but never reflects it back as accomplishments. The Coach's personality is "honest, direct, no hollow praise" — but SPECIFIC recognition of REAL achievements is part of the coaching philosophy ("Real breakthrough → recognize it specifically").

**How:** Add a `checkMilestones()` function to `renderAll()` that compares current data against stored thresholds. Show milestones as brief banners. Feed them into Coach context.
