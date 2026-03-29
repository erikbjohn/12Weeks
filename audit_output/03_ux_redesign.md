# UI/UX Redesign

## Current UI Critique

### Structure Overview

The app is a single-page application with a vertical stack layout:

```
Header ("12 Weeks" + settings gear)
├── Baseline/Intake overlay (onboarding, covers everything)
├── Morning check-in overlay (daily, covers everything)
├── Migration banner
├── Weigh-in bar
├── Check-in summary bar (mood/sleep/stress badges)
├── Garmin metrics bar
├── Supplement tracker bar
├── Readiness alert
├── Phase nav (Phase 1/2/3 tabs)
├── Phase banner (week info, deficit, focus)
├── Week tabs (1-12)
├── Day grid (Mon-Sun cards)
├── Detail panel (selected day's workout + meals)
├── Footer (static tips)
├── Progress overlay (triggered from somewhere?)
├── Garmin login modal
├── Chat FAB (floating action button, bottom-right)
└── Chat overlay
```

### What's Good

1. **Dark theme with high contrast** — readable, professional, matches a gym/performance aesthetic
2. **Color-coded run types** — Z2 blue, tempo amber, HIIT red, long purple — excellent at-a-glance differentiation
3. **Garmin metrics grid** — compact, informative, color-coded by readiness score
4. **Morning check-in sliders** — fast to use, conditional follow-ups are smart
5. **Meal plan with macro tracking** — detailed but scannable, portion adjustment buttons are practical
6. **Phase/week/day navigation** — logical hierarchy

### What's Broken

1. **Information overload on the main screen** — 7+ horizontal bars stack before the user even sees their workout. On a phone, the actual workout content is below the fold.

2. **No visual hierarchy for "what should I do RIGHT NOW"** — The app treats weigh-in, supplements, Garmin, and readiness as equally important. None of them are as important as "what's my workout today?" but they all sit above it.

3. **Footer is wasted space** — Static text ("Lift first - Run after - Done by 9am") is repeated every page load. This should be in onboarding, not occupying permanent screen real estate.

4. **Chat FAB is the only way to reach the Coach** — The Coach is the core differentiator of this app, but it's hidden behind a small floating button. No user sees this and thinks "I should talk to my AI coach."

5. **Progress dashboard is orphaned** — The `showProgress()` function exists but there's no visible button to trigger it in the HTML. The settings menu doesn't include it either. Dead feature.

6. **No visual distinction between today and other days** — The day grid shows all 7 days equally. Today should be visually prominent and auto-selected.

7. **Psych intake chat is styled as a "card" in the baseline overlay** — This is a full conversational experience crammed into a small card. On mobile, the chat area is tiny with a small input field at the bottom.

8. **Supplement tracker is flat and forgettable** — Small toggle pills that blend into the surface. "Creatine 5g" means nothing to a user who hasn't memorized the supplement list.

9. **No empty states** — When there's no Garmin data, no check-in history, no weight data, the bars just render with "--" or "?". There's no guidance about what data would be helpful to add.

10. **The settings gear opens a dropdown with critical actions** — "Redo Baseline" and "Redo Psych Intake" are destructive operations sitting next to "Export Data" with no confirmation.

---

## Redesigned User Flow

### Daily Flow (The "Golden Path")

**Step 1: Open app → Coach-First Morning**
```
┌──────────────────────────────────┐
│  Good morning.                   │
│                                  │
│  Your HRV is 52 (↓ from 58 avg) │
│  Sleep: 6.8h, score 72          │
│  Body battery: 45               │
│                                  │
│  Today is Bench day — Week 6.   │
│  How are you feeling?            │
│                                  │
│  ┌─ Sliders (collapsed) ──────┐ │
│  │ Tap to expand check-in     │ │
│  └────────────────────────────┘ │
│                                  │
│  [Skip Check-In]  [Let's Go]    │
└──────────────────────────────────┘
```

The Coach speaks first. Garmin data and today's workout are presented as the Coach's context, not as separate UI bars. The check-in sliders are opt-in, not blocking.

**Step 2: Today's View (Primary Screen)**
```
┌──────────────────────────────────┐
│  12 Weeks          ⚙  📊  💬    │
│  Week 6 · Phase 2 · Bench Day   │
├──────────────────────────────────┤
│  ┌─ Readiness ─────────────────┐│
│  │ 🟢 72/100  Train as planned ││
│  └─────────────────────────────┘│
│                                  │
│  ┌─ Today's Workout ───────────┐│
│  │ Warm-up (5 min)        ▶    ││
│  │ ☐ Bench Press   135lb  RPE  ││
│  │ ☐ Incline DB    55lb   RPE  ││
│  │ ☐ Cable Fly     25lb   RPE  ││
│  │ ☐ Lat Pulldown  100lb  RPE  ││
│  │ ☐ Face Pulls    20lb   RPE  ││
│  │ Run: 30min Z2               ││
│  └─────────────────────────────┘│
│                                  │
│  ┌─ Nutrition ─────────────────┐│
│  │ Heavy Lift Day · 1800 cal   ││
│  │ ☐ Pre (5:30a) ☐ Break Fast  ││
│  │ ☐ Lunch  ☐ Dinner           ││
│  │ P: 45/155g  C: 12/100g     ││
│  └─────────────────────────────┘│
│                                  │
│  ┌─ Quick Actions ─────────────┐│
│  │ ⚖️ 183.2 lb (7d: 184.1)    ││
│  │ 💊 Creatine ✓  Whey ✓      ││
│  └─────────────────────────────┘│
│                                  │
│  ┌─ Coach ─────────────────────┐│
│  │ "Good numbers this morning. ││
│  │  Push the bench today."     ││
│  │ [Reply]                     ││
│  └─────────────────────────────┘│
└──────────────────────────────────┘
```

Key changes:
- **Workout is the hero.** It's the first full-width card, not buried below 7 bars.
- **Readiness is a single-line summary**, not a multi-line alert.
- **Meals are collapsed** to a progress bar + checkboxes. Expand for detail.
- **Weigh-in and supplements are a "Quick Actions" bar** — compact, secondary.
- **Coach's latest message is inline**, not hidden behind a FAB.
- **Navigation is minimal**: settings, progress charts, and full chat are in the header.

**Step 3: Workout Execution**
```
User taps a workout exercise →
  ┌─────────────────────────────┐
  │ Bench Press                 │
  │ 4 x 10 @ 135 lb            │
  │ Last week: 130 lb (↑5 lb)  │
  │                             │
  │ Weight: [135] lb            │
  │                             │
  │ How did it feel?            │
  │ [Too Easy] [Right] [Hard]  │
  │                             │
  │ [✓ Done]                    │
  └─────────────────────────────┘
```

Expanded exercise card shows history, suggestion reason, and RPE in one view. No scrolling to find the weight input.

**Step 4: End of Day**
- If all exercises checked: "Workout complete. Nice work." toast
- If meals tracked: daily macro summary
- If Sunday: Weekly planning chat auto-opens

### Onboarding Flow (Redesigned)

```
Screen 1: Welcome
  "12 Weeks. Align aspirations with actions."
  [I'm Ready]

Screen 2: Coach Intake (Full-Screen Chat)
  Full-height chat interface (not a card inside an overlay)
  Progress indicator: "Getting to know you (4/12)"
  [Continue Later] button in top-right
  Saved state shown on re-entry: "Welcome back. We left off at..."

Screen 3: Psych Report (Scrollable Full-Screen)
  Rendered report with collapsible sections
  [Start Physical Assessment →]

Screen 4: Baseline Lifts
  Same flow but with:
  - "Skip this lift" option for unknown exercises
  - Video/GIF reference for each lift
  - Time estimate: "~10 minutes for 9 lifts"

Screen 5: Measurements + Photos
  Same flow (already well-designed)
  [Start Training →]
```

---

## Component-Level Recommendations

### Remove

1. **Static footer** — move content to onboarding or settings
2. **Migration banner** — one-time migration; remove after v2 deploys
3. **Separate check-in summary bar** — merge into the Coach's morning briefing
4. **Phase nav AND week tabs AND day grid as separate elements** — merge into a unified navigation

### Add

1. **"Today" hero card** — auto-selects today, shows workout + readiness at a glance
2. **Inline Coach message** — latest Coach message visible on main screen without opening overlay
3. **Progress sparklines** — mini charts in the weigh-in bar and lift weight inputs
4. **Milestone banners** — brief celebrations for PRs, streaks, weight milestones
5. **Coach quick-reply buttons** — "How should I modify today?" / "I'm struggling" / "I crushed it" — pre-written prompts below the inline Coach message
6. **Skip/dismiss on morning check-in** — add "Skip today" that records a blank check-in
7. **Empty state guidance** — "Connect Garmin to unlock readiness tracking" with benefit explanation

### Reorder (Main Screen Top to Bottom)

Current order:
1. Header → 2. Weigh-in → 3. Check-in summary → 4. Garmin → 5. Supplements → 6. Readiness → 7. Phase nav → 8. Phase banner → 9. Week tabs → 10. Day grid → 11. Detail panel

Proposed order:
1. Header (with progress + chat icons)
2. Readiness (one-line)
3. Today's workout (hero card, auto-expanded)
4. Nutrition (collapsed macro summary)
5. Quick actions (weigh-in + supplements, single row)
6. Coach (inline latest message + reply)
7. Week navigation (collapsible, for browsing other days)

---

## Copy Rewrites

### Primary CTAs

| Location | Current | Proposed |
|---|---|---|
| Welcome button | "Commit" | "I'm Ready" |
| Psych intake start | (no CTA, auto-starts) | "Meet Your Coach" (before auto-start) |
| Physical assessment start | "Let's Go" | "Start Baseline Test (~10 min)" |
| Baseline lift "Next" | "Next" / "Finish" | "Next Lift →" / "See My Results" |
| Measurements save | "Save & Start Program" | "Start My 12 Weeks" |
| Morning check-in submit | "Submit Check-In" | "Let's Go" |
| Continue to workout | "Continue to Workout" | "Show Me Today's Workout" |
| Chat send button | "Send" | "→" (arrow icon, save space) |

### Empty States

| Location | Current | Proposed |
|---|---|---|
| No Garmin | "Connect Garmin Watch" (button) | "Connect your Garmin to unlock HRV tracking, sleep analysis, and smart readiness scores." [Connect] |
| No body weight | Input field only | "Step on the scale. We track your 7-day rolling average, not daily fluctuations." [Log Weight] |
| No chat history | Empty chat area | "This is where you'll talk to Erik, your coach. He sees everything — your sleep, your lifts, your check-ins. Ask him anything." |
| No progress photos | (not shown) | "Take your first photos. We'll compare them every week so you can see what the mirror doesn't show yet." |
| Coach unavailable | "Coach is temporarily unavailable. Try again in a moment." | "Erik stepped away. He'll be back in a moment. (If this persists, check your API key in settings.)" |

---

## Implementation Checklist (Priority Order)

### Quick Wins (< 1 day each)

- [ ] **Add "Skip" button to morning check-in overlay** — single line of HTML + handler
- [ ] **Auto-select today in day grid** — add `setDay(todayIdx)` to `renderAll()`
- [ ] **Add progress dashboard button** — it's built, just needs a trigger in the header
- [ ] **Fix intake locked dead-end** — add close button + countdown UI
- [ ] **Escape psych intake** — add "Continue Later" to intake chat header
- [ ] **Apply escapeHtml to psych messages** — XSS fix, 1-line change
- [ ] **Rewrite copy** — update all CTA text and empty states per tables above
- [ ] **Confirmation on destructive settings** — add `confirm()` before "Redo Baseline" and "Redo Psych Intake"

### Medium Effort (1-3 days each)

- [ ] **Reorder main screen** — move workout card above Garmin/supplements/weigh-in bars
- [ ] **Collapse nutrition section** — show macro progress bar, expand for meal detail
- [ ] **Inline Coach message on main screen** — show last coach message below workout, with quick-reply buttons
- [ ] **Add typing timeout to Claude API calls** — `timeout=30` on Anthropic client
- [ ] **Add retry logic to critical apiPost calls** — weight saves, check-in saves, completion toggles
- [ ] **Milestone detection system** — PR tracking, streak counting, weight loss milestones
- [ ] **Full-screen psych intake chat** — make it use the full viewport, not a card in an overlay

### Structural Changes (3-7 days each)

- [ ] **Coach-first morning flow** — pre-fetch Garmin, have Coach speak first with data context, make sliders the "response"
- [ ] **Unified "Today" view** — single scrollable screen with workout hero, nutrition summary, vitals, coach
- [ ] **Async Claude API calls** — move to background tasks or streaming responses to prevent worker blocking
- [ ] **Progressive web app improvements** — offline caching for workout data, background sync for data saves
- [ ] **Redesigned navigation** — replace phase nav + week tabs + day grid with a single date-aware navigation component

### Future Considerations

- [ ] **Streaming coach responses** — use Claude streaming API for real-time text appearance
- [ ] **Push notifications** — morning check-in reminder, supplement reminder, weekly planning nudge
- [ ] **Social accountability** — share progress photos or milestones (if user opts in)
- [ ] **Voice input for Coach chat** — gym-friendly, hands-free interaction
