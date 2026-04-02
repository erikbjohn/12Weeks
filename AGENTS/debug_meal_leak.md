# Meal Data Leak Between Days -- Root Cause Analysis

## VERDICT: BUG CONFIRMED

The hypothesis is correct. Thursday shows Thursday's food list but Wednesday's checkbox state.

---

## The Bug in One Sentence

`getMealDateKey()` (line 212) hardcodes `return todayStr()`, so all meal checkbox reads and writes use today's calendar date, regardless of which day tab the user is viewing.

---

## Trace Through the Code

### CHECK 1: How meals are loaded on init

File: `static/app.js`, lines 3547-3583

```js
fetch('/api/meals?date=' + todayStr()),   // line 3554
...
_mealsCache[todayStr()] = mealsData;      // line 3583
```

On page load, meals are fetched for TODAY only. The cache is keyed by today's date string (e.g. `"2026-03-26"` for Wednesday). No other day's meal data is ever fetched.

### CHECK 2: How getMealDateKey() works

File: `static/app.js`, lines 211-213

```js
function getMealDateKey() {
  return todayStr();   // ALWAYS returns today's date, ignores currentDay
}
```

This is the root cause. It returns today's calendar date unconditionally. When the user taps Thursday's tab, `currentDay` changes to 3 (Thursday = index 3 in Mon-based week), but `getMealDateKey()` still returns Wednesday's date.

### CHECK 3: How loadMealData() works

File: `static/app.js`, lines 215-219

```js
function loadMealData() {
  const key = getMealDateKey();           // always today
  if (_mealsCache[key]) return _mealsCache[key];
  return {};
}
```

When viewing Thursday, this returns Wednesday's `{eaten: [...], foodItems: [...]}` because the key is Wednesday's date and only Wednesday's data was ever fetched/cached.

### CHECK 4: How saveMealData() works

File: `static/app.js`, lines 221-242

```js
function saveMealData(data) {
  const key = getMealDateKey();           // always today
  _mealsCache[key] = data;
  ...
  apiPost('/api/meals', { date: key, ... });  // POSTs to today's date
}
```

When the user checks a food item while viewing Thursday, the POST goes to Wednesday's date. The user's Thursday actions corrupt Wednesday's meal log.

### CHECK 5: How renderMealSection() gets its data

File: `static/app.js`, lines 422-488

`renderMealSection(dayData)` receives the correct day's workout data (Thursday's food list from `workoutData[currentWeek].days[currentDay]`). But inside it:

- `isMealEaten(idx)` calls `loadMealData()` -> `getMealDateKey()` -> `todayStr()` -> Wednesday's state
- `_isFoodItemEaten(foodKey)` calls `loadMealData()` -> same chain -> Wednesday's state

So the food NAMES are Thursday's, but the checkbox STATE is Wednesday's.

### CHECK 6: The backend GET /api/meals

File: `app.py`, lines 1401-1436

```python
@app.route("/api/meals")
def api_meals():
    d = request.args.get("date", date.today().isoformat())
    ml = MealLog.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).first()
```

Backend is correct. It uses whatever date is passed. The bug is purely frontend -- the frontend always passes today's date.

---

## Exact Symptom

1. It is Wednesday. User opens the app. Meal data for Wednesday (2026-03-25) is fetched and cached.
2. User checks off Meal 1 and Meal 2 on Wednesday. Saved to `_mealsCache["2026-03-25"]`.
3. User taps Thursday's tab. `currentDay` changes to 3.
4. `renderDetail()` calls `renderMealSection(weekData.days[3])` -- Thursday's food list renders correctly.
5. Inside `renderMealSection`, `isMealEaten(0)` calls `loadMealData()` which returns `_mealsCache["2026-03-25"]` (Wednesday's data).
6. Wednesday's `eaten: [0, 1]` makes Thursday's Meal 1 and Meal 2 appear checked.
7. If user unchecks a meal on Thursday's view, it actually removes it from Wednesday's record.

---

## Fix Required

`getMealDateKey()` must return a date based on the SELECTED day, not today. This requires:

1. Computing the selected day's actual calendar date from `currentDay` relative to today.
2. Fetching meal data from the backend for that date when switching days (if not cached).
3. Saving meal data to the correct date when checkboxes are toggled.

The simplest approach: derive the selected date from `currentDay` offset from today's weekday index.

```js
function getMealDateKey() {
  const today = new Date();
  const todayMon = today.getDay() === 0 ? 6 : today.getDay() - 1; // Mon=0 index
  const diff = currentDay - todayMon; // e.g. Thu(3) - Wed(2) = +1
  const target = new Date(today);
  target.setDate(target.getDate() + diff);
  return target.getFullYear() + '-' +
    String(target.getMonth() + 1).padStart(2, '0') + '-' +
    String(target.getDate()).padStart(2, '0');
}
```

And `loadMealData()` must fetch from the API if the cache misses for the computed date:

```js
async function loadMealData() {
  const key = getMealDateKey();
  if (_mealsCache[key]) return _mealsCache[key];
  // Fetch from backend for non-today dates
  try {
    const res = await fetch('/api/meals?date=' + key);
    const data = await res.json();
    _mealsCache[key] = data;
    return data;
  } catch(e) { return {}; }
}
```

Note: making `loadMealData` async means all callers (`isMealEaten`, `_isFoodItemEaten`, `toggleMealEaten`, `toggleFoodItem`, `renderMealSection`) must be updated to await it, or a synchronous pattern must be used where the cache is pre-warmed on day switch.

---

## Affected Functions (all in static/app.js)

| Function | Line | Issue |
|---|---|---|
| `getMealDateKey()` | 211 | Returns `todayStr()` unconditionally |
| `loadMealData()` | 215 | Cache lookup uses wrong key |
| `saveMealData()` | 221 | Saves to wrong date |
| `isMealEaten()` | 247 | Reads wrong day's state |
| `_isFoodItemEaten()` | 301 | Reads wrong day's state |
| `toggleMealEaten()` | 252 | Mutates wrong day's state |
| `toggleFoodItem()` | 306 | Mutates wrong day's state |
| `renderMealSection()` | 422 | Renders wrong day's checkboxes |
| DOMContentLoaded | 3554 | Only fetches today's meals |
