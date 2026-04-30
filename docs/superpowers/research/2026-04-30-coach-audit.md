# Coach System — Adversarial Audit

> Three parallel agents on 2026-04-30 after Erik's report:
> "Coach references runs that don't exist, has no idea of current time,
> asks me what time I'm working out tomorrow which is ridiculous —
> he tells me when to work out. Honestly this coach has been such a
> disappointment, I am getting ready to scrap it."

## Core failure modes (cross-agent convergence)

### 1. Time grounding gap (CRITICAL)
- `coach_assembler.py:841` CORE_PROMPT rule #6 says "the current time is in `<athlete_data>`" but the actual time is embedded in a prose sentence (e.g. "Sunday, April 27, 2025 at 9:14 PM"). No structured `current_time` field. LLM must parse prose.
- `_build_base()` (line 68-82) injects `local_today` and `today_idx` but no time of day or scheduled workout time.
- Result: coach asks "what time are you training tomorrow?" because the prompt doesn't tell it.

### 2. Scheduled-workout-time gap (CRITICAL)
- `_build_week_schedule()` (line 300-318) returns `{day_idx, day, liftName, isRest}` per day. **No `workout_time` field.**
- The default 6am AM-stacked window is never injected as a fact.
- The coach has no evidence Erik trains at 6am unless it appeared in stale chat history.

### 3. Hallucination from empty sections (CRITICAL — already producing visible bugs)
- `_build_runs()` (line 427-437) returns last 14 RunLog rows. When list is empty, the section is omitted.
- `_format_runs()` (coach.py:85-98) returns empty string for empty list.
- Protocols then instruct the LLM to "cite recent runs" / "discuss last session" with no data in scope.
- LLM fills the void by inventing distances, paces, and sessions that never happened.
- Same pattern applies to `exercise_history`, `meals_today`, `garmin`, `coach_memories` whenever empty/missing.

### 4. Fasting hours bug (CRITICAL — fixed today, but symptomatic)
- The "15.6 hours into your 16-hour fast" hallucination wasn't a math bug — `run_complete` agent didn't include `fasting` in its requires list, so `_build_fasting()` never ran. LLM filled the void with a made-up number.
- Fixed in commit `e52511f` (added fasting to run_complete + 4 other agents).
- Pattern is the underlying disease: any time an agent's requires list omits a section the LLM thinks it should reference, it invents.

### 5. PROTOCOL violations of CORE_PROMPT (HIGH)
- CORE_PROMPT line 835 (Rule 4): "DIRECTIVES NOT QUESTIONS — Tell the athlete what to do. Do not ask 'would you like to...'"
- Direct violations in PROTOCOL_MAP:
  - line 1036: run_complete: "Ask ONE question about how it felt."
  - line 1082: chat_opened: "ask what they need."
  - line 883, 979, 983: weekly_planning: "Ready to see Monday?", "Anything else for [this day]?", "End each day with a question."
- The PROTOCOL_MAP literally instructs the LLM to do what CORE_PROMPT bans. LLM resolves contradictions by following the more recent / specific instruction (the protocol).

### 6. No banned-phrase enforcement (HIGH)
- CORE_PROMPT line 827 lists banned capitulation phrases ("your call", "if you feel up to it", etc).
- `assemble_prompt()` concatenates rules + protocol + data. **No post-generation validation, no token filter, no rejection layer.**
- The LLM's default behavior is collaborative/deferential. Without enforcement, banned phrases slip through.

### 7. Chat history persistence of hallucinations (HIGH)
- `_build_chat_history()` loads up to 45 messages (today 20 + this week 15 + older 10).
- If the coach hallucinated "your 8-miler Tuesday" two weeks ago, that lie sits in chat_history forever.
- Future calls treat the past hallucination as established truth and elaborate. Secondary hallucinations build on primary.
- No correction-memory mechanism. No "this past message was wrong" flag.

### 8. Stale coach memories (HIGH)
- `_build_coach_memories()` (line 626-632) pulls last 50 by created_at desc, no week/date filter, no expiry.
- Memory from week 2 ("granted exception, traveling") still applies in week 12.
- Coach references stale rules as current.

### 9. Temperature 1.0 on weekly_review (MEDIUM)
- `coach_agents.py:51` — weekly_review temperature 1.0 (max randomness). All other agents 0.6.
- Higher temperature increases collaborative/question-asking deviation from tone instructions.
- No clear rationale for the 1.0 setting.

### 10. Stale time inside the prompt (MEDIUM)
- Time injected at prompt-build time. If the coach's response takes 30s and the user asks "what time is it now?" mid-conversation, the LLM still sees prompt-build time.
- Minor but shows up in long sessions.

---

## Top priority fixes (cross-agent ranking)

1. **Inject structured current_time + scheduled_workout_time** as explicit fields (not prose). Eliminates "what time?" asking and time hallucination.
2. **Replace "ask the user X" instructions in PROTOCOL_MAP** with directives that match CORE_PROMPT. The protocols are the smoking gun for posture violations.
3. **Add explicit "no data" sentinels** in every section that can be empty. Tell the LLM "you have NO recent run logs — do not reference any" rather than omitting the section.
4. **Time-window the chat history and coach_memories.** Aggressive recency weighting. Possibly summarize older context instead of injecting raw messages.
5. **Add a post-generation banned-phrase guard.** Scan output for "your call", "if you feel up to it", future-tense capitulation phrases. Reject + retry, or strip + log.
6. **Lower weekly_review temperature to 0.6**.

---

## Open architectural questions (for brainstorm)

1. **Patch in place vs rewrite the coach from scratch?** Erik said he's ready to scrap it. The audit shows the bones are OK; the problems are surface-level (data injection gaps, contradictory protocols, no enforcement). Rewrite might over-correct.
2. **Validation layer architecture.** Post-generation banned-phrase scan? Or structured-output coercion (force the LLM to return JSON with specific fields)?
3. **Memory model.** Should coach memories be auto-pruned after N weeks? Should there be a "this is stale" flag the user can apply? Or should memories be replaced with a summarized state document the LLM rebuilds weekly?
4. **Chat history strategy.** Truncate to 24h? Replace with a coach-summarized "what's relevant" snippet? Or build a structured "recent events" timeline that's bounded and grounded in real data?
5. **Hallucination prevention as a contract.** Should every claim the coach makes be required to cite a specific field from the prompt context? CORE_PROMPT says "every claim must cite a number from `<athlete_data>`" but there's no enforcement.
