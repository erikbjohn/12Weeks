# Debug: Meal Checkbox Cross-Day Leaking

## Bug
Thursday shows Wednesday's meal checkboxes as checked.

## Root Cause
`getMealDateKey()` (line 211) returns `todayStr()` -- always today's actual calendar date. It never uses `currentDay` (the viewed day index). Every load, save, and check operation goes through this function.

This means:
- All meal/food checkbox state is stored and read from a single date key: today.
- When the user views Wednesday (today) and checks items, they are saved under today's date.
- When the user taps Thursday (a different day), `loadMealData()` still reads from today's date key.
- Thursday's meal plan has the same index structure (meal 0, meal 1, etc.), so foodKeys like `"0_0"`, `"0_1"`, `"1_0"` match across days.
- Result: Thursday's checkboxes reflect Wednesday's checked state.

## CHECK 1: How foodItems are keyed

`_isFoodItemEaten(foodKey)` at line 301 calls `loadMealData()` which calls `getMealDateKey()` which returns `todayStr()`. The foodKey format is `"mealIdx_foodIdx"` (e.g., `"0_2"`). There is NO date component in the key -- it relies entirely on `loadMealData()` scoping to the correct date. But `loadMealData()` always returns today's data regardless of which day is being viewed.

**BUG CONFIRMED**: foodKeys have no date component, and `loadMealData()` ignores `currentDay`.

## CHECK 2: toggleFoodItem saves to today, not viewed day

`toggleFoodItem()` at line 306 calls `saveMealData(data)` which calls `getMealDateKey()` -> `todayStr()`. The save always writes to today's actual date. If the user is viewing Thursday but today is Wednesday, checking a food item on Thursday's view saves to Wednesday's MealLog row in the database.

**BUG CONFIRMED**: saves go to today's date, not the viewed day's date.

## CHECK 3: toggleMealEaten uses the same broken path

`toggleMealEaten()` at line 252 calls `loadMealData()` and `saveMealData()`, both routed through `getMealDateKey()` -> `todayStr()`. When checking meal 0 on Wednesday, `eaten=[0]` is saved to today's MealLog. When viewing Thursday, `isMealEaten(0)` loads from the same today-keyed MealLog and returns true. Thursday meal 0 shows as eaten even though it was Wednesday's meal 0 that was checked.

**BUG CONFIRMED**: all meal tracking reads/writes are date-blind with respect to the viewed day.

## CHECK 4: Should meals be editable on non-today days?

There is no `isToday` guard on meal checkboxes. No `disabled` attribute is ever applied. The rendering code at lines 446-461 unconditionally renders clickable buttons for every day's meals.

**Recommendation**: Meal tracking should only be interactive for today. The fix should:
1. Disable meal and food checkboxes when viewing a non-today day (set `disabled` on buttons, skip onclick handlers).
2. Optionally show historical data for past days by loading that day's MealLog from the API (using the date parameter that already exists: `/api/meals?date=YYYY-MM-DD`).

## Code Flow Summary

```
getMealDateKey()        -> todayStr()           [ALWAYS today, ignores currentDay]
loadMealData()          -> _mealsCache[todayStr()]
saveMealData()          -> _mealsCache[todayStr()] + POST /api/meals {date: todayStr()}
_isFoodItemEaten()      -> loadMealData()       [reads today's data]
isMealEaten()           -> loadMealData()       [reads today's data]
toggleFoodItem()        -> saveMealData()       [writes to today's data]
toggleMealEaten()       -> saveMealData()       [writes to today's data]
```

The viewed day (`currentDay`) is never consulted by any meal tracking function.

## Fix Options

**Option A (simple, recommended)**: Disable all meal checkboxes when `currentDay !== todayMon`. Show the meal plan read-only for non-today days. No data model changes needed.

**Option B (full)**: Change `getMealDateKey()` to derive the actual calendar date from `currentWeek` and `currentDay`, load/save per-day meal data, and pre-fetch historical meal data. More complex, enables retroactive meal logging.
