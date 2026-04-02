# 500 Internal Server Error - Root Cause Analysis

## PRIMARY BUG: Unquoted `user` table in migration SQL (line 159)

**File:** `app.py` line 150 + line 159
**Severity:** CRITICAL - breaks ALL authenticated routes on PostgreSQL

### What happens

Line 150 defines a migration:
```python
("user", "timezone", "VARCHAR(64) DEFAULT 'UTC'"),
```

Line 159 generates raw SQL:
```python
db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}'))
```

This produces:
```sql
ALTER TABLE user ADD COLUMN timezone VARCHAR(64) DEFAULT 'UTC'
```

In PostgreSQL, `user` is a reserved keyword (alias for `current_user`). Without double-quotes, PostgreSQL does NOT interpret it as a table name. The statement fails with a syntax error.

### Why this crashes ALL routes

1. The migration fails silently (caught by `except Exception: db.session.rollback()` at line 161-162).
2. The `timezone` column never gets added to the `"user"` table in the database.
3. The `chat_message.message_type` column (line 151) also never gets added, because it's in the same try/except block and comes AFTER the failing `user` migration.
4. The SQLAlchemy `User` model (models.py line 22) maps `timezone` as a column.
5. Every `User.query.get()` generates SQL selecting `"user".timezone`, which does not exist.
6. `load_user()` (app.py line 72-74) calls `User.query.get()` on EVERY authenticated request.
7. Every `@login_required` route fails with `ProgrammingError: column user.timezone does not exist`.

### The fix

Line 159 - quote the table name:
```python
db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {col_type}'))
```

This also fixes the `chat_message.message_type` migration (line 151), which was silently skipped because it comes after the crashing `user` line in the same loop iteration block.

---

## SECONDARY BUG: `_send_prestart_email` called before definition (line 257)

**File:** `app.py` line 257 (call) vs line 262 (definition)
**Severity:** LOW - does not cause 500, but pre-start emails never send

Line 257 calls `_send_prestart_email(_user)` inside the `with app.app_context():` block (module-level code, runs at import time). The function is defined at line 262, AFTER the `with` block ends. At the time of the call, the name does not exist.

This raises `NameError`, which IS caught by `except Exception: pass` on lines 258-259, so it does not crash the app. But it means pre-start emails silently never send.

### The fix

Move the function definition ABOVE the `with app.app_context():` block, or move the pre-start email logic out of the startup block entirely (e.g., into a scheduled task or a before-first-request handler).

---

## SUMMARY: Priority order

| # | Bug | Line | Impact | Causes 500? |
|---|-----|------|--------|-------------|
| 1 | Unquoted `user` in ALTER TABLE | 159 | All auth routes broken | YES |
| 2 | `_send_prestart_email` undefined at call site | 257 | Pre-start emails never send | No (caught) |

### Additional notes

- `db.create_all()` at line 116 is NOT wrapped in try/except. If it ever fails (e.g., database connection issue), the entire app module fails to import and ALL routes return 500. This is a minor hardening issue.
- The `chat_message.message_type` column also fails to get added (same root cause as bug #1), which means any code writing `message_type` to ChatMessage will fail on commit, and any query selecting from chat_message will include the nonexistent column.
- All model imports (line 36-45) match classes defined in models.py - no missing class issues.
- The `DailyCoachState` model is correctly defined and `db.create_all()` handles its creation properly.
