# Fix 7 Schema Changes -- COMPLETE

## 1. ChatMessage.message_type column added (models.py line 418)
- `message_type = db.Column(db.String(30), default='chat')`
- Values: chat, morning_opener, checkin_response, workout_nudge, post_workout, scold

## 2. DailyCoachState model added (models.py lines 424-434)
- Table: `daily_coach_state`
- Columns: id, user_id (FK, indexed), state_date (Date, unique with user_id), opener_shown_at, opener_dismissed_at, checkin_completed_at, nudge_sent_at
- UniqueConstraint on (user_id, state_date)
- Table will be created by `db.create_all()` on startup

## 3. Startup migration added (app.py line 151)
- `("chat_message", "message_type", "VARCHAR(30) DEFAULT 'chat'")`
- Handles existing databases that already have the chat_message table

## 4. DailyCoachState added to app.py imports (line 44)
- Added to the `from models import (...)` block
