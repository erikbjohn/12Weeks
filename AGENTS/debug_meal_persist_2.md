# Meal Checkbox Reset on Refresh -- Root Cause Analysis

## The Bug

Meal checkboxes reset to unchecked on every page refresh.

## Root Cause: `scheduled_time` not declared in MealLog model

**GET /api/meals crashes with an uncaught `AttributeError` on every request
where a MealLog record exists.**

### The smoking gun: `app.py` line 1525

```python
meal_timing = {}
if ml.scheduled_time:       # <-- THIS LINE CRASHES
    try:
        _parsed = _json.loads(ml.scheduled_time)
        ...
```

`scheduled_time` is NOT declared as a column in the `MealLog` model
(`models.py` line 190-199). It only exists in the database via an ALTER TABLE
migration (`app.py` line 136). SQLAlchemy does not map undeclared columns.
Accessing `ml.scheduled_time` raises `AttributeError`.

The `try/except` on line 1526 does NOT catch this because the `if` check on
line 1525 is OUTSIDE the try block.

### Verified with SQLAlchemy directly

```python
ml = session.query(MealLog).first()
ml.scheduled_time  # --> AttributeError: 'MealLog' object has no attribute 'scheduled_time'
```

### The crash cascade

1. User checks a meal checkbox
2. POST /api/meals saves `eaten` and `foodItems` to DB successfully (line 1559-1563)
3. Frontend shows checkbox as checked (from in-memory `_mealsCache`)
4. User refreshes the page
5. GET /api/meals hits line 1525 -> `AttributeError` -> unhandled -> Flask returns 500
6. Frontend `mealsRes.json()` fails on the 500 HTML error page
7. The `catch(e) {}` at line 3688-3691 in app.js swallows the error silently
8. `_mealsCache[todayStr()]` is never populated
9. `loadMealData()` returns `{}` -> all checkboxes render as unchecked
10. The data is still in the DB -- it just can't be read

## CHECK 1: Model vs Migration Column Types

### MealLog model columns (models.py lines 190-199)

| Column     | Model Type  | Origin       | Actual DB Type        |
|------------|-------------|--------------|-----------------------|
| id         | Integer     | CREATE TABLE | INTEGER (PK)          |
| log_date   | Date        | CREATE TABLE | DATE                  |
| eaten      | db.JSON     | CREATE TABLE | JSON (native)         |
| adjustments| db.JSON     | CREATE TABLE | JSON (native)         |
| food_items | db.JSON     | CREATE TABLE | JSON (native)*        |
| fasting    | Boolean     | CREATE TABLE | BOOLEAN               |
| user_id    | Integer/FK  | migration    | INTEGER               |

*`food_items` was added to the model AND as a TEXT migration. If the table
existed before the model change, the migration ran first and created it as
TEXT. If the table was created fresh, `db.create_all()` created it as JSON.

### Columns in DB but NOT in model (migration-only)

| Column         | Migration Type | Model? | Accessed in app.py? |
|----------------|---------------|--------|---------------------|
| scheduled_time | VARCHAR(10)*  | NO     | YES (lines 1525, 1569) |
| actual_time    | VARCHAR(30)*  | NO     | NO                  |

*A subsequent migration at line 166-167 attempts to ALTER both to TEXT.

### Migrations for meal_log table (app.py lines 135-137, 166-167)

```python
("meal_log", "food_items", "TEXT"),
("meal_log", "scheduled_time", "VARCHAR(10)"),
("meal_log", "actual_time", "VARCHAR(30)"),
```

Fix migration (lines 164-170):
```python
db.session.execute(text('ALTER TABLE "meal_log" ALTER COLUMN scheduled_time TYPE TEXT'))
db.session.execute(text('ALTER TABLE "meal_log" ALTER COLUMN actual_time TYPE TEXT'))
```

## CHECK 2: food_items TEXT vs JSON

The `food_items` column has a type mismatch (model says JSON, migration says
TEXT), but this is NOT the cause of the checkbox bug. The `_ensure_list()`
wrapper at line 1511-1516 handles both cases (parses strings, passes lists
through). The read side works correctly for `food_items`.

## CHECK 3: The VARCHAR(10) scheduled_time issue

The original migration created `scheduled_time` as VARCHAR(10). The POST
handler writes JSON dicts like `{"0": {"scheduled": "11:00am", "actual":
"2026-04-01T..."}}` which far exceeds 10 characters. However:

1. A fix migration at line 166 already changes it to TEXT
2. The POST handler already separates timing saves from core data (lines 1565-1572)
3. **This is moot anyway because `scheduled_time` is not in the model, so
   SQLAlchemy never reads or writes it regardless of the column type**

## Fix Required

Add `scheduled_time` and `actual_time` to the MealLog model in `models.py`:

```python
class MealLog(db.Model):
    __tablename__ = "meal_log"
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    eaten = db.Column(db.JSON, default=list)
    adjustments = db.Column(db.JSON, default=dict)
    food_items = db.Column(db.JSON, default=list)
    scheduled_time = db.Column(db.Text, nullable=True)   # <-- ADD THIS
    actual_time = db.Column(db.Text, nullable=True)       # <-- ADD THIS
    fasting = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
```

AND wrap the `if ml.scheduled_time:` in a try/except as defense:

```python
meal_timing = {}
try:
    if ml.scheduled_time:
        _parsed = _json.loads(ml.scheduled_time)
        if isinstance(_parsed, dict):
            meal_timing = _parsed
except Exception:
    pass
```

## Secondary Issues Found

1. **POST timing writes are no-ops**: `ml.scheduled_time = _json.dumps(...)`
   sets a Python attribute but SQLAlchemy does not track or persist it because
   the column is unmapped. Meal timing data is silently lost on every save.

2. **Service worker caches stale 500 responses**: The SW caches GET /api/meals
   responses (sw.js line 61-69). If a 500 error is cached, subsequent requests
   might return the cached error even after a fix is deployed. Users may need
   to clear their browser cache or force a SW update.
