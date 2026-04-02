# Fix 7 Backend Changes -- COMPLETE

## 1. Daily opener endpoint added (app.py line ~2346)
- `GET /api/coach/daily-opener`
- Checks `DailyCoachState` for today, returns existing opener or signals `needs_generation: true`
- Returns `already_seen` flag based on `opener_dismissed_at`

## 2. Dismiss opener endpoint added (app.py line ~2378)
- `POST /api/coach/dismiss-opener`
- Sets `opener_dismissed_at` on today's `DailyCoachState` record

## 3. message_type saved on all ChatMessage objects
- `/api/chat` route: reads `mode` from request data, sets `message_type=mode` on both user and assistant `ChatMessage` objects
- `/api/chat/stream` route: reads `mode` from request data, sets `message_type=mode` on user message and captures `_mode` for the generator closure, sets it on assistant message in `finally` block

## 4. Double-send protection added (app.py line ~2169, ~2205, ~2277)
- `_chat_rate_limit` dict added at module level (in-memory, user_id -> timestamp)
- Both `/api/chat` and `/api/chat/stream` check for 2-second cooldown per user
- Returns 429 with `"Too fast -- wait a moment"` if violated

## 5. Today-only history endpoint added (app.py line ~2391)
- `GET /api/coach/today-history`
- Returns today's `ChatMessage` records excluding internal triggers (`[MORNING_CHECKIN]`, `[WORKOUT_COMPLETE]`, `[MEALS_COMPLETE]`, `[END_OF_DAY]`)
- Each message includes `role`, `content`, `type` (from `message_type` column), and formatted `time`
