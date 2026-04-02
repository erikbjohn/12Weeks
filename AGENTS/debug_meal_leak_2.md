# Meal Leak Bug: Thursday shows Wednesday's eaten data

## Verdict: The meal PLANS are correct. The TRACKING data leaks across days.

---

## CHECK 1: Are meal plans different per day?

YES -- each day gets a distinct meal type and distinct meal plan.

`workout_data.py` lines 304-311:
```python
DAY_MEAL_TYPES = {
    "Mon": "heavy_lift",
    "Tue": "long_run",
    "Wed": "heavy_lift",
    "Thu": "moderate",
    "Fri": "heavy_lift",
    "Sat": "moderate",
    "Sun": "rest",
}
```

Each type maps to a completely different `MEAL_PLANS` entry with different labels,
target macros, meal names, and food lists. For example:
- `heavy_lift`: 1800 cal, 155P, 5 meals (Pre-Workout, Post-Workout Shake, Chicken Salad, Eggs+Greens, Chicken+Rice)
- `moderate`: 1700 cal, 145P, 4 meals (Pre-Workout, Eggs+Greens, Chicken+Greens, Chicken+Veggies)
- `long_run`: 2050 cal, 160P, 5 meals (Pre-Workout, Shake+Banana, Omelette+Salad, Chicken+Sweet Potato, Chicken Salad Bowl)

The plan injection happens at `workout_data.py` lines 605-611: each day object gets
`d["mealType"]` and `d["mealPlan"]` set from the mapping. This is correct.

## CHECK 2: How does renderMealSection get the day's meal plan?

CORRECT -- the meal plan itself comes from the right day.

`renderDetail()` at `app.js` line 5963:
```js
const d = weekData.days[currentDay];
```
Then at line 6299:
```js
${renderMealSection(d)}
```
And `renderMealSection(dayData)` at line 423:
```js
const plan = dayData.mealPlan;
```

When the user taps Thursday (currentDay=3), `d` is `weekData.days[3]` which is
Thursday's data, and `d.mealPlan` is the "moderate" plan. The plan itself is correct.

## CHECK 3: Are meal checkboxes indexed by meal position?

YES -- and this is where the bug lives.

`isMealEaten(idx)` checks if index `idx` exists in the `eaten` array.
Both Wednesday (heavy_lift, 5 meals) and Thursday (moderate, 4 meals) use
indices starting at 0. If Wednesday's MealLog has `eaten=[0,1,2,3,4]`,
and the code loads Wednesday's MealLog while viewing Thursday, then
meals 0-3 would all show as eaten on Thursday's view.

## CHECK 4: Is there a per-day MealLog or one per date?

ONE PER DATE -- which is correct in principle but the client always queries today's date.

`models.py` lines 190-199:
```python
class MealLog(db.Model):
    log_date = db.Column(db.Date, nullable=False, index=True)
    eaten = db.Column(db.JSON, default=list)
```

Server `app.py` line 1404:
```python
d = request.args.get("date", date.today().isoformat())
ml = MealLog.query.filter_by(user_id=current_user.id, log_date=date.fromisoformat(d)).first()
```

The server correctly accepts a `date` parameter and queries by it.

## CHECK 5: The isMealEaten() function -- ROOT CAUSE

THIS IS THE BUG. `isMealEaten()` always reads today's data regardless of which
day tab the user is viewing.

The call chain:

1. `isMealEaten(mealIdx)` (line 247) calls `loadMealData()` (line 248)
2. `loadMealData()` (line 215) calls `getMealDateKey()` (line 216)
3. `getMealDateKey()` (line 211) returns `todayStr()` (line 212)
4. `todayStr()` (line 205) returns the current calendar date as YYYY-MM-DD

```js
function getMealDateKey() {
  return todayStr();  // <-- ALWAYS today, ignores currentDay
}

function loadMealData() {
  const key = getMealDateKey();
  if (_mealsCache[key]) return _mealsCache[key];
  return {};
}

function isMealEaten(mealIdx) {
  const data = loadMealData();
  return Array.isArray(data.eaten) && data.eaten.includes(mealIdx);
}
```

The same problem affects:
- `toggleMealEaten()` (line 252) -- saves to wrong date
- `saveMealData()` (line 221) -- saves to wrong date
- `_isFoodItemEaten()` (line 301) -- reads wrong date
- `toggleFoodItem()` (line 306) -- saves to wrong date
- `getMealMultiplier()` (line 373) -- reads wrong date

Additionally, at init (line 3554), meal data is only fetched for today:
```js
fetch('/api/meals?date=' + todayStr()),
```
and cached under today's key (line 3583):
```js
_mealsCache[todayStr()] = mealsData;
```

So if you view Wednesday on a Thursday, the cache only has Thursday's MealLog data.
All checks show Thursday's eaten state overlaid on Wednesday's meal plan.

---

## Summary

The meal PLAN displayed is correct per day (different foods, macros, labels).

The meal TRACKING (eaten checkboxes) always reads/writes today's calendar date,
not the date corresponding to the day tab the user is viewing.

Result: If today is Thursday, viewing any day tab (Mon/Tue/Wed/Thu/Fri/Sat/Sun)
shows Thursday's eaten checkboxes overlaid on that day's meal plan. Wednesday's
meal plan shows with Thursday's check marks.

## Fix Required

`getMealDateKey()` needs to compute the actual calendar date for the viewed day tab,
not just return `todayStr()`. The viewed day's date can be computed from the program
start date + (currentWeek - 1) * 7 + currentDay offset. The meal data for that date
also needs to be fetched from the server if not already cached.
