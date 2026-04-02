# Meal Checkbox Persistence Bug -- Full Trace

## 1. What happens when user clicks a meal checkbox

**Function:** `toggleMealEaten(mealIdx, btnEl)` at `static/app.js:254`

1. Calls `loadMealData()` which reads from `_mealsCache[todayStr()]`
2. Modifies `data.eaten` array -- pushes `mealIdx` (an integer) or splices it out
3. Also modifies `data.foodItems` -- auto-checks/unchecks all foods in the meal
4. Calls `saveMealData(data)` at line 279
5. Updates button class in-place for instant feedback
6. Calls `renderDetail()` for full re-render

**Data object modified:** `_mealsCache[todayStr()]` -- specifically `data.eaten` (array of ints) and `data.foodItems` (array of strings like `"0_1"`)

## 2. What saveMealData sends

**Function:** `saveMealData(data)` at `static/app.js:221`

The exact POST body (line 242):
```js
apiPost('/api/meals', {
  date: key,                                              // "2026-03-30"
  eaten: Array.isArray(data.eaten) ? data.eaten : [],     // [0, 1, 2]
  adjustments: data.adjustments || {},                    // {}
  foodItems: Array.isArray(data.foodItems) ? data.foodItems : [],  // ["0_0", "0_1", ...]
  mealTiming: data.mealTiming || {},                      // { "0": { scheduled: "7:00am", actual: "..." } }
  fasting: data.fasting || false                          // false
})
```

`apiPost` at line 160 does `JSON.stringify(body)` -- so the wire format is correct JSON.

## 3. POST /api/meals handler -- field-by-field

**Handler:** `api_meals_update()` at `app.py:1533`

```python
data = request.get_json()  # Flask parses JSON body -> Python dict
d = date.fromisoformat(data.get("date", ...))
ml = MealLog.query.filter_by(user_id=current_user.id, log_date=d).first()
# Creates new row if needed

if "eaten" in data:
    ml.eaten = data["eaten"]        # Python list [0, 1, 2] -> db column "eaten"
if "adjustments" in data:
    ml.adjustments = data["adjustments"]  # Python dict -> db column "adjustments"
if "foodItems" in data:
    ml.food_items = data["foodItems"]     # Python list ["0_0","0_1"] -> db column "food_items"
if "fasting" in data:
    ml.fasting = data["fasting"]
if "mealTiming" in data:
    ml.scheduled_time = json.dumps(data["mealTiming"])  # Manually serialized to string
db.session.commit()
```

| POST field    | Read from data? | Model attribute   | DB column        | Column type             |
|---------------|-----------------|-------------------|------------------|-------------------------|
| date          | Yes             | log_date          | log_date         | Date                    |
| eaten         | Yes             | ml.eaten          | eaten            | JSON (from create_all)  |
| adjustments   | Yes             | ml.adjustments    | adjustments      | JSON (from create_all)  |
| foodItems     | Yes             | ml.food_items     | food_items       | **TEXT (from migration)**|
| mealTiming    | Yes             | ml.scheduled_time | scheduled_time   | TEXT (from migration)   |
| fasting       | Yes             | ml.fasting        | fasting          | Boolean                 |

## 4. THE BUG: `food_items` column type mismatch

### Model declares JSON, migration created TEXT

**Model** (`models.py:197`):
```python
food_items = db.Column(db.JSON, default=list)
```

**Migration** (`app.py:135`):
```python
("meal_log", "food_items", "TEXT"),
```

`db.create_all()` does NOT alter existing columns. Since `food_items` was added via ALTER TABLE as TEXT, the actual PostgreSQL column is TEXT, not JSON/JSONB.

### What happens when SQLAlchemy writes a Python list to a TEXT column

When the model says `db.JSON` but the actual column is `TEXT`:
- SQLAlchemy's JSON type processor calls `json.dumps()` on the value before sending to the DB
- PostgreSQL stores it as the text string `[0, 1, 2]` or `["0_0", "0_1"]`
- This is valid JSON text, so `_ensure_list` can parse it back

**So `food_items` round-trips correctly** despite the type mismatch. The JSON type adapter serializes to string on write and deserializes on read.

### The `eaten` column

`eaten` was NOT in the migrations list -- it was created by `db.create_all()` with the model's `db.JSON` type. On PostgreSQL, this maps to native JSON/JSONB. SQLAlchemy stores Python lists natively. **This also round-trips correctly.**

## 5. GET /api/meals -- does `_ensure_list` parse correctly?

**Handler:** `api_meals()` at `app.py:1495`

```python
def _ensure_list(val):
    if isinstance(val, list): return val       # Native JSON column -> already a list
    if isinstance(val, str):
        try: parsed = _json.loads(val); return parsed if isinstance(parsed, list) else []
        except Exception: return []
    return []
```

- For `eaten` (native JSON column): value is already a Python list -> returns as-is
- For `food_items` (TEXT column): SQLAlchemy JSON adapter deserializes on read -> value is already a Python list -> returns as-is
- Edge case: if somehow stored as raw string, `json.loads` handles it

**`_ensure_list` handles both cases correctly.**

## 6. THE ACTUAL BUG: `isViewingToday` gate on render

**This is the real problem.** At `static/app.js:442-443`:

```js
// Only check eaten state when viewing today -- prevents cross-day data leaking
const eaten = isViewingToday ? isMealEaten(idx) : false;
```

And `isViewingToday` at line 431:
```js
const todayJsDay = new Date().getDay();
const todayMonIdx = todayJsDay === 0 ? 6 : todayJsDay - 1;
const isViewingToday = currentDay === todayMonIdx;
```

**The data saves and loads correctly. The question is whether `currentDay` matches `todayMonIdx` after a refresh.**

On page load:
1. `currentDay` starts as `null` (line 31)
2. `renderAll()` runs at line 5773 which calls `renderDetail()` at line 5681
3. `renderDetail()` at line 6022 checks `if (currentDay === null)` and returns early
4. THEN at line 5687, `renderAll()` auto-selects today: `setDay(mappedIdx)`
5. This sets `currentDay` and calls `renderDetail()` again

**The ordering is correct** -- by the time meals render, `currentDay` IS set to today.

## 7. ROOT CAUSE FOUND: The `_mealsCache` is keyed by `todayStr()` but meals are LOADED before auto-day-select

Looking at init (line 3688-3691):
```js
const mealsData = await mealsRes.json();
_mealsCache[todayStr()] = mealsData;
```

And `loadMealData()` (line 215-218):
```js
function loadMealData() {
  const key = getMealDateKey();
  if (_mealsCache[key]) return _mealsCache[key];
  return {};
}
```

`getMealDateKey()` returns `todayStr()` which uses **local browser time**. The GET request sends `todayStr()` as the date param. The server parses with `date.fromisoformat(d)`.

**No mismatch here** -- same date key is used for load and save.

## 8. VERIFIED: The save path is actually correct

After exhaustive tracing:
- Frontend builds correct JSON body with `eaten: [0, 1, 2]`
- `apiPost` sends it as proper JSON
- Server reads it, assigns to model, commits
- `eaten` column is native JSON on PostgreSQL -- stores correctly
- `food_items` column is TEXT but SQLAlchemy JSON adapter handles serialization
- GET handler reads it back, `_ensure_list` handles both native and string
- Cache key (`todayStr()`) is consistent between load and save
- `isViewingToday` gate works correctly after auto-day-select

## 9. REMAINING SUSPECT: Silent save failures

The save call at line 242-244:
```js
apiPost('/api/meals', { ... })
  .then(r => { if (r && !r.ok) console.error('Meal save failed:', r.status); })
  .catch(e => console.error('Meal save error:', e));
```

This is fire-and-forget. If the save fails (network error, 500, CSRF issue), the user sees the checkbox toggle (in-place DOM update) but the data never reaches the DB. On refresh, the GET returns the old state.

**Check the server logs for 500 errors on POST /api/meals.** The handler has a try/except that returns `{"error": "Save failed"}` with status 500 on commit failure, but the frontend only logs it to console -- no user-visible error.

## 10. SECOND SUSPECT: No CSRF token on apiPost

The `apiPost` function (line 160-186) sends:
```js
headers: {'Content-Type': 'application/json'}
```

There is NO CSRF token header. If Flask has CSRF protection enabled on POST routes, every meal save would be silently rejected. Check if there's a CSRF middleware or if the `@login_required` decorator handles this differently.

Looking at `app.py:52-58`, CSRF tokens are generated but only used in Jinja templates. The API routes don't appear to validate CSRF. So this is NOT the issue unless a middleware was recently added.

## CONCLUSION

The save path is mechanically correct -- data types, serialization, and column types all work. The most likely cause of "checks don't persist on refresh" is:

1. **Silent POST failures** -- the apiPost is fire-and-forget, errors only logged to console
2. **Network/timing** -- if the page is refreshed before the async POST completes, data is lost
3. **Server-side commit failures** -- the try/except at line 1553 catches ALL exceptions and returns 500, which the frontend ignores

**Next step:** Add server-side logging to POST /api/meals to confirm saves are actually committing, or check browser DevTools Network tab for failed POST requests.
