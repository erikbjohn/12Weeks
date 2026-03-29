# Executive Summary — 12 Weeks App Audit

**Date:** 2026-03-28
**Scope:** Full codebase audit — agent logic, engagement flow, UI/UX

---

## The Single Biggest Logic Risk

**Synchronous Claude API calls block the entire application.** Every coach message, intake response, photo analysis, and report generation makes a synchronous HTTP call to Claude with no timeout. On Render's single-worker free tier, one slow Claude response (common at 5-15 seconds for Sonnet) freezes the app for ALL users. The intake report generation (`max_tokens=4096`) can block for 30+ seconds.

**Fix:** Add `timeout=30` to the Anthropic client. For photo analysis and report generation, move to background tasks with polling or use Claude's streaming API.

---

## The Single Biggest Engagement Opportunity

**The Coach is hidden behind a floating button.** Erik (the AI coach) is the product's differentiator — a direct, blunt, data-aware coach that sees your sleep, lifts, and psychology. But users only find him through a small 💬 FAB in the corner. The morning check-in sends data TO the coach, but the response feels like an afterthought.

**Fix:** Make the Coach the centerpiece. Show his latest message on the main screen. Have him speak FIRST in the morning check-in (with Garmin data he already has). Add quick-reply buttons so the user doesn't have to think of what to say. The Coach should feel like opening a text from your trainer, not clicking a help widget.

---

## Three Highest-ROI UI/UX Changes

### 1. Auto-select today + move workout above metrics bars
- **Effort:** 2 hours
- **Impact:** The workout is buried below 7 information bars. Most users visit the app to see "what's my workout today?" — make it the first thing they see. Add one line to auto-select today's day in the grid.

### 2. Add "Skip" and "Continue Later" to blocking overlays
- **Effort:** 4 hours
- **Impact:** The morning check-in and psych intake both BLOCK the entire app with no escape. If a user gets interrupted or locked out of the intake, the app is unusable. Add dismiss buttons, save-and-resume messaging, and proper locked-state UI.

### 3. Inline Coach message with quick-reply prompts
- **Effort:** 1 day
- **Impact:** Show the Coach's most recent message on the main screen (below workout), with 3 quick-reply buttons: "How should I modify today?" / "I'm struggling" / "I crushed it". This turns the Coach from a hidden feature into the product's core interaction loop.

---

## Recommended Implementation Order

| Phase | What | Why First |
|---|---|---|
| **Now** | Add timeout to Claude API calls | Prevents app-wide freezes. One-line fix. |
| **Now** | Add Skip/Continue Later to overlays | Unblocks stuck users. Prevents first-day drop-off. |
| **This week** | Auto-select today, reorder main screen | Immediate UX improvement, no backend changes. |
| **This week** | Fix all copy (CTAs, empty states, coach voice) | Low effort, high polish. See tables in 03_ux_redesign.md. |
| **Next week** | Inline Coach + quick replies on main screen | Core engagement improvement. |
| **Next week** | Milestone detection + celebration banners | Uses existing data, adds delight and accountability. |
| **Sprint 2** | Coach-first morning flow | Major UX shift — coach speaks first with data context. |
| **Sprint 2** | Async/streaming Claude responses | Architectural improvement for responsiveness. |

---

## Files Needing Immediate Attention

| File | Issue | Severity |
|---|---|---|
| `coach.py:44-50` | No timeout on Claude API call — blocks worker thread | **Critical** |
| `psych_intake.py:231-244` | No timeout on intake API call — same blocking issue | **Critical** |
| `app.py:949-1048` | No timeout on photo analysis — same blocking issue, worse with Vision | **Critical** |
| `static/app.js:960-963` | XSS vulnerability — psych intake messages not escaped | **High** |
| `static/app.js:1376-1455` | Morning check-in has no dismiss/skip option | **High** |
| `static/app.js:855-921` | Psych intake has no continue-later or progress indicator | **High** |
| `app.py:708` | Intake conversation history slicing is fragile | **Medium** |
| `static/app.js:25-31` | `apiPost` silently drops errors — weight/completion data loss risk | **Medium** |
| `app.py:733` | `generate_intake_report` error renders as report text | **Medium** |

---

*Full details in:*
- `01_logic_audit.md` — Agent flow map, race conditions, confidence scores
- `02_engagement_audit.md` — Drop-off points, latency, copy rewrites, top 3 improvements
- `03_ux_redesign.md` — UI critique, redesigned flows, component recommendations, implementation checklist
