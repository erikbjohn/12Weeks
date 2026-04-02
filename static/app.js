// ─── DATA CACHES ────────────────────────────────────────────────────────────
let _weightsCache = null;
let _completionsCache = null;
let _mealsCache = {};
let _stateCache = null;
let _supplementsCache = null;
let _bodyweightCache = null;
let _morningCheckinCache = null;
let _chatHistory = [];
let _warmupCache = {};
let _runLogCache = {};
let _setCache = {};      // Per-set completion: "week_day_ex_set" → { done, reps, weight }
let _restTimerInterval = null;
let _exerciseSwapsLoaded = false;
let _complianceCache = null;
let _morningCheckinDone = true; // Gate disabled for now
let _focusExIdx = null;
let _focusSetIdx = null;
let _focusSetCount = null;
let _focusExName = '';
let _focusRestSec = 60;
let _focusTargetReps = 10;
let _focusWeightVal = '';
let _focusLastWeight = null;
let _focusTimerInterval = null;

// ─── STATE ──────────────────────────────────────────────────────────────────
let workoutData = {};
let currentPhase = 1;
let currentWeek = 1;
let currentDay = null;
let garminConnected = false; // Garmin disabled
let garminData = null;
let readinessData = null;
let warmupTimerInterval = null;
let _chatOverlayOpen = false;
let _chatScrollPos = null;
let _mealDetailExpanded = false;
let _milestonesShownThisSession = new Set();

const WEEK_TO_PHASE = {1:1,2:1,3:1,4:1,5:2,6:2,7:2,8:2,9:3,10:3,11:3,12:3};

// ─── API HELPERS ────────────────────────────────────────────────────────────
function checkAuth(res) {
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Session expired');
  }
  return res;
}

function showToast(msg, type) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + (type || 'info');
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.add('fade-out'); setTimeout(() => toast.remove(), 300); }, 3000);
}

// ─── COACH POPUP (one-way notifications) ──────────────────────────────────
let _coachPopupTimeout = null;
let _coachPopupQueue = [];

function showCoachPopup(message) {
  // If a popup is already showing, queue this one
  const existing = document.getElementById('coach-opener-panel');
  if (existing) {
    _coachPopupQueue.push(message);
    return;
  }

  const panel = document.createElement('div');
  panel.id = 'coach-opener-panel';
  panel.className = 'coach-opener';
  panel.innerHTML = `
    <div class="coach-opener__inner">
      <div class="coach-opener__header">
        <div class="coach-opener__avatar">E</div>
        <div class="coach-opener__meta">
          <span class="coach-opener__name">Erik</span>
          <span class="coach-opener__status">Online</span>
        </div>
        <button class="coach-opener__dismiss" onclick="dismissCoachPopup()" aria-label="Dismiss">&times;</button>
      </div>
      <div class="coach-opener__body">
        <p class="coach-opener__message">${escapeHtml(message)}</p>
      </div>
    </div>`;

  // Insert at top of page, after header
  const header = document.querySelector('header');
  if (header && header.nextSibling) {
    header.parentNode.insertBefore(panel, header.nextSibling);
  } else {
    document.body.prepend(panel);
  }

  // Push to chat history
  _chatHistory.push({ role: 'coach', text: message, time: new Date().toISOString(), date: todayStr() });
}

function dismissCoachPopup() {
  if (_coachPopupTimeout) { clearTimeout(_coachPopupTimeout); _coachPopupTimeout = null; }
  const panel = document.getElementById('coach-opener-panel');
  if (panel) {
    panel.style.opacity = '0';
    panel.style.maxHeight = '0';
    setTimeout(() => {
      panel.remove();
      // Show next queued
      if (_coachPopupQueue.length > 0) {
        showCoachPopup(_coachPopupQueue.shift());
      }
    }, 300);
  }
  // Mark as dismissed
  fetch('/api/coach/dismiss-opener', { method: 'POST' }).catch(() => {});
}

// Dedup: prevent duplicate popups per day
function hasPopupFired(key) {
  return localStorage.getItem('popup_' + key + '_' + todayStr()) === '1';
}
function markPopupFired(key) {
  localStorage.setItem('popup_' + key + '_' + todayStr(), '1');
}

function showPreStartLockout(startDateStr) {
  const startDate = new Date(startDateStr + 'T00:00:00');
  const now = new Date();
  const diffMs = startDate - now;
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));

  const dateLabel = startDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

  document.body.innerHTML = `
    <div style="min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:2rem;text-align:center;background:var(--bg,#0d0f0e);color:var(--text,#e8ede9)">
      <div style="max-width:400px">
        <div style="font-family:'DM Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;margin-bottom:1rem">COACH ERIK</div>
        <h1 style="font-size:1.8rem;font-weight:700;margin-bottom:0.5rem">YOUR PROGRAM STARTS</h1>
        <div style="font-size:1.4rem;color:#4ade80;font-weight:600;margin-bottom:2rem">${dateLabel}</div>
        <div style="font-family:'DM Mono',monospace;font-size:3rem;font-weight:800;color:#4ade80;margin-bottom:0.5rem">${days}d ${hours}h</div>
        <div style="font-size:13px;color:#6b7280;margin-bottom:2rem">until Day 1</div>
        <div style="background:#1a2e24;border:2px solid #3a7a56;border-radius:12px;padding:20px;margin-bottom:2rem;text-align:left;font-size:15px;line-height:1.6;color:#e8ede9">
          Rest up. Eat clean. Hydrate. When that clock hits zero, we go. No warm-up period. No easing in. Day 1 is full speed. Be ready.
        </div>
        <button onclick="window.location='/logout'" style="background:none;border:1px solid #3a3f3c;color:#6b7280;padding:10px 24px;border-radius:8px;font-size:14px;cursor:pointer">Logout</button>
      </div>
    </div>`;
}

function apiPost(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(res => {
    if (res.status === 401) { window.location.href = '/login'; return; }
    if (!res.ok) { console.error('API error:', res.status, url); }
    return res;
  }).catch(e => {
    console.warn('POST failed (attempt 1), retrying:', url, e);
    return new Promise(resolve => setTimeout(resolve, 1000)).then(() =>
      fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      })
    ).catch(e2 => {
      console.error('POST failed (attempt 2):', url, e2);
      showToast('Save failed. Check your connection.', 'error');
      // Queue for background sync if available
      if ('serviceWorker' in navigator && 'SyncManager' in window) {
        queueForSync(url, body);
      }
    });
  });
}

async function queueForSync(url, body) {
    try {
        const db = await new Promise((resolve, reject) => {
            const req = indexedDB.open('12weeks-sync', 1);
            req.onupgradeneeded = () => { req.result.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true }); };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
        const tx = db.transaction('outbox', 'readwrite');
        tx.objectStore('outbox').add({ url, body: JSON.stringify(body), timestamp: Date.now() });
        const reg = await navigator.serviceWorker.ready;
        await reg.sync.register('sync-posts');
    } catch (e) {
        console.warn('Failed to queue for sync:', e);
    }
}

function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

// ─── MEAL TRACKING ─────────────────────────────────────────────────────────
function getMealDateKey() {
  return todayStr();
}

function loadMealData() {
  const key = getMealDateKey();
  if (_mealsCache[key]) return _mealsCache[key];
  return {};
}

function saveMealData(data) {
  const key = getMealDateKey();
  _mealsCache[key] = data;
  apiPost('/api/meals', { date: key, eaten: Array.isArray(data.eaten) ? data.eaten : [], adjustments: data.adjustments || {}, foodItems: Array.isArray(data.foodItems) ? data.foodItems : [], fasting: data.fasting || false });
  // Refresh compliance badge
  fetch('/api/compliance').then(r => r.json()).then(d => { _complianceCache = d; renderTodayNav(); }).catch(() => {});
}

function isMealEaten(mealIdx) {
  const data = loadMealData();
  return Array.isArray(data.eaten) && data.eaten.includes(mealIdx);
}

function toggleMealEaten(mealIdx, btnEl) {
  const data = loadMealData();
  if (!Array.isArray(data.eaten)) data.eaten = [];
  if (!Array.isArray(data.foodItems)) data.foodItems = [];
  const idx = data.eaten.indexOf(mealIdx);
  const marking = idx < 0;

  if (marking) {
    data.eaten.push(mealIdx);
    // Auto-check all food items in this meal
    const weekData = workoutData[String(currentWeek)];
    const dayData = weekData ? weekData.days[currentDay] : null;
    const mp = dayData ? dayData.mealPlan : null;
    if (mp && mp.meals && mp.meals[mealIdx]) {
      const meal = mp.meals[mealIdx];
      (meal.foods || []).forEach((f, fi) => {
        const foodKey = `${mealIdx}_${fi}`;
        if (!data.foodItems.includes(foodKey)) data.foodItems.push(foodKey);
      });
    }
  } else {
    data.eaten.splice(idx, 1);
    data.foodItems = data.foodItems.filter(k => !k.startsWith(mealIdx + '_'));
  }

  saveMealData(data);

  // Update button in-place immediately (don't wait for async renderDetail)
  if (btnEl) {
    if (marking) {
      btnEl.classList.add('eaten');
      btnEl.innerHTML = '&#10003; ' + btnEl.textContent.replace('✓ ', '').trim();
    } else {
      btnEl.classList.remove('eaten');
      btnEl.innerHTML = btnEl.textContent.replace('✓ ', '').trim();
    }
  }

  // Full re-render to sync food checkboxes
  renderDetail();

  if (marking) {
    const totalMeals = _getTotalMealCount();
    if (totalMeals > 0 && data.eaten.length >= totalMeals) {
      _triggerKitchenClosed();
    }
  }
}

function _isFoodItemEaten(foodKey) {
  const data = loadMealData();
  return Array.isArray(data.foodItems) && data.foodItems.includes(foodKey);
}

function toggleFoodItem(foodKey, mealIdx, totalFoodsInMeal, btnEl) {
  const data = loadMealData();
  if (!Array.isArray(data.foodItems)) data.foodItems = [];
  if (!Array.isArray(data.eaten)) data.eaten = [];
  const idx = data.foodItems.indexOf(foodKey);
  const checking = idx < 0;

  if (checking) {
    data.foodItems.push(foodKey);
  } else {
    data.foodItems.splice(idx, 1);
  }

  // Auto-check meal if all foods in it are checked
  const mealFoodsChecked = data.foodItems.filter(k => k.startsWith(mealIdx + '_')).length;
  if (checking && mealFoodsChecked >= totalFoodsInMeal && !data.eaten.includes(mealIdx)) {
    data.eaten.push(mealIdx);
  } else if (!checking && data.eaten.includes(mealIdx)) {
    data.eaten.splice(data.eaten.indexOf(mealIdx), 1);
  }

  saveMealData(data);

  // Update in-place using the button element directly
  const btn = btnEl;
  const row = btn ? btn.closest('.meal-food-row') : null;
  if (checking) {
    if (btn) { btn.classList.add('checked'); btn.innerHTML = '&#10003;'; }
    if (row) row.classList.add('food-eaten');
  } else {
    if (btn) { btn.classList.remove('checked'); btn.innerHTML = ''; }
    if (row) row.classList.remove('food-eaten');
  }

  // If all meals auto-completed, re-render to update compact row
  if (checking && mealFoodsChecked >= totalFoodsInMeal) {
    renderDetail();
  }

  // Check if all meals done → coach closes kitchen
  const totalMeals = _getTotalMealCount();
  if (checking && totalMeals > 0 && data.eaten.length >= totalMeals) {
    _triggerKitchenClosed();
  }
}

function _getTotalMealCount() {
  const weekData = workoutData[String(currentWeek)];
  const dayData = weekData && currentDay !== null ? weekData.days[currentDay] : null;
  const mp = dayData ? dayData.mealPlan : null;
  return mp && mp.meals ? mp.meals.length : 0;
}

async function _triggerKitchenClosed() {
  if (hasPopupFired('meals')) return;
  markPopupFired('meals');
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: '[MEALS_COMPLETE] All meals eaten for the day. 1-2 sentences. Popup — no questions.' }),
    });
    const data = await res.json();
    if (data.response) showCoachPopup(data.response);
  } catch(e) {}
}

function getMealMultiplier(mealIdx) {
  const data = loadMealData();
  if (data.adjustments && data.adjustments[String(mealIdx)]) {
    return data.adjustments[String(mealIdx)].multiplier || 1;
  }
  return 1;
}

function adjustMealPortion(mealIdx, delta) {
  const data = loadMealData();
  if (!data.adjustments) data.adjustments = {};
  const key = String(mealIdx);
  if (!data.adjustments[key]) data.adjustments[key] = { multiplier: 1 };
  let m = data.adjustments[key].multiplier + delta;
  if (m < 0.25) m = 0.25;
  if (m > 3) m = 3;
  data.adjustments[key].multiplier = Math.round(m * 100) / 100;
  saveMealData(data);
  renderDetail();
}

function isFastingToday() {
  const data = loadMealData();
  return data.fasting === true;
}

function toggleFasting(fasting) {
  const data = loadMealData();
  data.fasting = fasting;
  saveMealData(data);
  renderDetail();
}

function calcMealMacros(foods, multiplier) {
  let cal = 0, protein = 0, carbs = 0, fat = 0;
  for (const f of foods) {
    cal += (f.cal || 0) * multiplier;
    protein += (f.protein || 0) * multiplier;
    carbs += (f.carbs || 0) * multiplier;
    fat += (f.fat || 0) * multiplier;
  }
  return {
    cal: Math.round(cal),
    protein: Math.round(protein),
    carbs: Math.round(carbs),
    fat: Math.round(fat),
  };
}

function renderMealSection(dayData) {
  const plan = dayData.mealPlan;
  if (!plan) return '';

  // Sunday = automatic fast day (no toggle — it's the plan)
  const isSundayFast = dayData.day === 'Sun';
  const activePlan = isSundayFast ? ((window._mealPlansCache || {}).fast_day || plan) : plan;

  let totalEaten = { cal: 0, protein: 0, carbs: 0, fat: 0 };
  let mealsHtml = '';

  const meals = activePlan.meals || [];
  meals.forEach((meal, idx) => {
    const eaten = isMealEaten(idx);
    const multiplier = getMealMultiplier(idx);
    const macros = calcMealMacros(meal.foods, multiplier);

    if (eaten) {
      totalEaten.cal += macros.cal;
      totalEaten.protein += macros.protein;
      totalEaten.carbs += macros.carbs;
      totalEaten.fat += macros.fat;
    }

    const foodRows = meal.foods.map((f, fIdx) => {
      const adjCal = Math.round((f.cal || 0) * multiplier);
      const foodKey = idx + '_' + fIdx;
      const foodEaten = _isFoodItemEaten(foodKey);
      return `<div class="meal-food-row${foodEaten ? ' food-eaten' : ''}">
        <button class="food-check${foodEaten ? ' checked' : ''}" onclick="toggleFoodItem('${foodKey}',${idx},${meal.foods.length},this)">${foodEaten ? '&#10003;' : ''}</button>
        <span class="meal-food-name">${f.item}</span>
        <span class="meal-food-portion">${f.portion}</span>
        <span class="meal-food-portion">${adjCal}cal</span>
      </div>`;
    }).join('');

    mealsHtml += `<div class="meal-item${meal.optional ? ' optional' : ''}">
      <button class="meal-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx},this)">
        ${eaten ? '&#10003;' : ''}
      </button>
      <div class="meal-time">${meal.time}</div>
      <div class="meal-content">
        <div class="meal-name">${meal.name}</div>
        <div class="meal-foods">${foodRows}</div>
        <div class="meal-macros">
          <span class="mm-cal">${macros.cal} cal</span>
          <span class="mm-p">${macros.protein}P</span>
          <span class="mm-c">${macros.carbs}C</span>
          <span class="mm-f">${macros.fat}F</span>
        </div>
      </div>
    </div>`;
  });

  const target = {
    cal: activePlan.targetCal || 0,
    protein: activePlan.targetProtein || 0,
    carbs: activePlan.targetCarbs || 0,
    fat: activePlan.targetFat || 0,
  };

  const pctCal = target.cal > 0 ? Math.min(100, Math.round(totalEaten.cal / target.cal * 100)) : 0;
  const pctP = target.protein > 0 ? Math.min(100, Math.round(totalEaten.protein / target.protein * 100)) : 0;
  const pctC = target.carbs > 0 ? Math.min(100, Math.round(totalEaten.carbs / target.carbs * 100)) : 0;
  const pctF = target.fat > 0 ? Math.min(100, Math.round(totalEaten.fat / target.fat * 100)) : 0;

  const totalsHtml = ''; // Daily totals removed — eat the plan, check it off

  // Compact row: meal name checkboxes
  let compactChecks = '';
  meals.forEach((meal, idx) => {
    const eaten = isMealEaten(idx);
    compactChecks += `<button class="meal-compact-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx},this)">${eaten ? '&#10003; ' : ''}${meal.name}</button>`;
  });

  return `<div class="detail-section">
    <h3>Meal Plan &middot; ${activePlan.label || ''}</h3>
    ${isSundayFast ? '<div class="meal-plan-note" style="color:var(--accent)">Fast day. Water, black coffee, electrolytes only.</div>' : ''}
    ${!isSundayFast && activePlan.note ? '<div class="meal-plan-note">' + activePlan.note + '</div>' : ''}
    ${totalsHtml}
    <div class="meal-compact-row">${compactChecks}</div>
    <button class="meal-detail-toggle" onclick="toggleMealDetails()">
      ${_mealDetailExpanded ? 'Hide details \u25B2' : 'Show meal details \u25BC'}
    </button>
    <div class="meal-detail-body${_mealDetailExpanded ? ' visible' : ''}">
      <div class="meal-timeline">
        ${mealsHtml}
      </div>
    </div>
  </div>`;
}

function toggleMealDetails() {
  _mealDetailExpanded = !_mealDetailExpanded;
  renderDetail();
}

// ─── BASELINE CONFIG ────────────────────────────────────────────────────────
const BASELINE_LIFTS = [
  { name: 'Barbell Bench Press', suggested: 95 },
  { name: 'Barbell Back Squat', suggested: 95 },
  { name: 'Conventional Deadlift', suggested: 135 },
  { name: 'DB Overhead Press', suggested: 30 },
  { name: 'Barbell Bent-Over Row', suggested: 95 },
  { name: 'Lat Pulldown', suggested: 80 },
  { name: 'Barbell Hip Thrust', suggested: 95 },
  { name: 'EZ-Bar Curl', suggested: 40 },
  { name: 'Cable Tricep Pushdown', suggested: 30 },
];

const SMALL_ISOLATION = ['ez-bar curl', 'cable tricep pushdown', 'lateral raise', 'face pull', 'rear delt fly', 'hammer curl', 'concentration curl'];
const COMPOUND_BARBELL = ['barbell bench press', 'barbell back squat', 'conventional deadlift', 'db overhead press', 'barbell bent-over row', 'barbell hip thrust', 'cable row'];

function getProgressionIncrement(exName) {
  const lower = exName.toLowerCase();
  for (const s of SMALL_ISOLATION) {
    if (lower.includes(s)) return 2.5;
  }
  return 5;
}

function isDeloadWeek(week) {
  return week === 4 || week === 8 || week === 12;
}

// ─── WEIGHT DATA HELPERS (cache-based) ─────────────────────────────────────
function loadWeights() {
  return _weightsCache || {};
}

function getExerciseData(exName) {
  const weights = loadWeights();
  return weights[exName] || null;
}

function recordWeight(exName, weight, setsLabel, rpe, week, dayIdx, rpeScore, repsCompleted) {
  if (!_weightsCache) _weightsCache = {};
  if (!_weightsCache[exName]) {
    _weightsCache[exName] = { current: weight, history: [] };
  }
  _weightsCache[exName].current = weight;
  _weightsCache[exName].history.push({
    weight: weight,
    reps: setsLabel,
    rpe: rpe,
    rpe_score: rpeScore,
    reps_completed: repsCompleted,
    date: todayStr(),
    week: week,
    day: dayIdx,
  });
  apiPost('/api/weights', { exercise: exName, weight, sets_label: setsLabel, rpe, rpe_score: rpeScore, reps_completed: repsCompleted, week, day_idx: dayIdx });
}

function saveWeightInput(week, dayIdx, exIdx, exName) {
  const input = document.getElementById('wt-' + week + '-' + dayIdx + '-' + exIdx);
  if (!input) return;
  const weight = parseFloat(input.value) || 0;
  if (weight <= 0) return;
  // Update cache
  if (!_weightsCache) _weightsCache = {};
  if (!_weightsCache[exName]) _weightsCache[exName] = { current: 0, history: [] };
  _weightsCache[exName].current = weight;
  // Save to backend (without RPE — that comes later)
  apiPost('/api/weights', { exercise: exName, weight, week, day_idx: dayIdx });
}

function parseRestSeconds(rest) {
  if (!rest) return 60;
  // Handle "60-90s" → use the lower bound
  const m = rest.match(/(\d+)/);
  return m ? parseInt(m[1]) : 60;
}

function saveSetField(week, dayIdx, exIdx, setIdx, exName) {
  const wtInput = document.getElementById(`wt-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const repsInput = document.getElementById(`reps-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const weight = wtInput ? parseFloat(wtInput.value) || 0 : 0;
  const repsTyped = repsInput ? parseInt(repsInput.value) : 0;
  const repsTarget = repsInput ? parseInt(repsInput.placeholder) || 0 : 0;
  const reps = repsTyped || repsTarget;
  if (weight <= 0 && reps <= 0) return;
  const key = `${week}_${dayIdx}_${exIdx}_${setIdx}`;
  const done = !!(_setCache && _setCache[key] && _setCache[key].done);
  apiPost('/api/sets', { exercise: exName, week, day_idx: dayIdx, set_number: setIdx, weight, reps, done });
}

function toggleSet(week, dayIdx, exIdx, setIdx, restSec, exName, btn) {
  const key = `${week}_${dayIdx}_${exIdx}_${setIdx}`;
  const wtInput = document.getElementById(`wt-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const repsInput = document.getElementById(`reps-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const weight = wtInput ? parseFloat(wtInput.value) || 0 : 0;
  // If user didn't type reps, use the target reps (placeholder) — they hit the target
  const repsTyped = repsInput ? parseInt(repsInput.value) : 0;
  const repsTarget = repsInput ? parseInt(repsInput.placeholder) || 0 : 0;
  const reps = repsTyped || repsTarget;

  if (_setCache[key]) {
    // Un-check
    delete _setCache[key];
    btn.classList.remove('done');
    btn.innerHTML = '';
    btn.closest('.set-row').classList.remove('set-done');
    // Save un-done state to DB
    apiPost('/api/sets', { exercise: exName, week, day_idx: dayIdx, set_number: setIdx, weight, reps, done: false });
  } else {
    // Check — mark set done
    _setCache[key] = { done: true, weight, reps };
    btn.classList.add('done');
    btn.innerHTML = '&#10003;';
    btn.closest('.set-row').classList.add('set-done');

    // Save set to DB (every set, every rep, every weight)
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    const isSwapped = !!swaps[`${week}_${dayIdx}_${exIdx}`];
    apiPost('/api/sets', { exercise: exName, week, day_idx: dayIdx, set_number: setIdx, weight, reps, done: true, exercise_swapped: isSwapped });
    // Refresh compliance badge
    fetch('/api/compliance').then(r => r.json()).then(d => { _complianceCache = d; renderTodayNav(); }).catch(() => {});

    // Also update the exercise-level weight cache
    if (weight > 0) {
      if (!_weightsCache) _weightsCache = {};
      if (!_weightsCache[exName]) _weightsCache[exName] = { current: 0, history: [] };
      _weightsCache[exName].current = weight;
    }

    // Start rest timer
    startRestTimer(exIdx, restSec);

    // Check if all sets done → mark exercise complete + show RPE
    const setsMatch = document.querySelectorAll(`[id^="wt-${week}-${dayIdx}-${exIdx}-"]`);
    const totalSets = setsMatch.length;
    let allDone = true;
    for (let s = 0; s < totalSets; s++) {
      if (!_setCache[`${week}_${dayIdx}_${exIdx}_${s}`]) { allDone = false; break; }
    }
    if (allDone && !isExDone(week, dayIdx, exIdx)) {
      // Auto-mark exercise as complete
      if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
      if (!_completionsCache.exercises) _completionsCache.exercises = {};
      _completionsCache.exercises[`${week}_${dayIdx}_${exIdx}`] = true;
      apiPost('/api/completions/exercise', { week, day_idx: dayIdx, exercise_idx: exIdx });
      renderDetail();
    }
  }
}

let _activeTimerEl = null;

function startRestTimer(exIdx, seconds) {
  const el = document.getElementById('rest-timer-' + exIdx);
  if (!el) return;

  // Kill previous timer — both interval AND DOM
  if (_restTimerInterval) clearInterval(_restTimerInterval);
  if (_activeTimerEl && _activeTimerEl !== el) {
    _activeTimerEl.innerHTML = '';
    _activeTimerEl.style.display = 'none';
  }
  _activeTimerEl = el;

  let remaining = seconds;
  el.innerHTML = `<div class="rest-countdown">${formatTimer(remaining)}</div>`;
  el.style.display = 'block';

  _restTimerInterval = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(_restTimerInterval);
      _restTimerInterval = null;
      el.innerHTML = `<div class="rest-countdown rest-done">GO</div>`;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      setTimeout(() => { el.style.display = 'none'; _activeTimerEl = null; }, 3000);
    } else {
      el.innerHTML = `<div class="rest-countdown">${formatTimer(remaining)}</div>`;
    }
  }, 1000);
}

function formatTimer(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;
}

// ─── WEIGHT ROUNDING (valid plate combinations) ─────────────────────────
function isBarbell(exName) {
  const nl = exName.toLowerCase();
  return nl.includes('barbell') || nl.includes('ez-bar') || nl.includes('deadlift') ||
         nl.includes('squat') && !nl.includes('goblet') || nl.includes('ohp') ||
         nl.includes('bench press') && !nl.includes('db') && !nl.includes('dumbbell');
}

function roundWeight(weight, exName) {
  if (!weight || weight <= 0) return weight;
  if (isBarbell(exName)) {
    // Barbell: bar = 45, plates come in 2.5, 5, 10, 25, 35, 45
    // Valid total weights: 45 (empty bar), then bar + plates on each side
    // Smallest increment = 5 lbs (2.5 per side)
    // Round to nearest 5
    return Math.round(weight / 5) * 5;
  }
  // Dumbbell / cable / machine: 5 lb increments
  return Math.round(weight / 5) * 5;
}

function getLastRPEs(exName, count) {
  const data = getExerciseData(exName);
  if (!data || !data.history || data.history.length === 0) return [];
  return data.history.slice(-count).map(h => h.rpe);
}

// Fallback weight estimates for exercises without history
const WEIGHT_ESTIMATES = {
  "Incline DB Press": (cache) => { const bench = cache["Barbell Bench Press"]; return bench ? Math.round(bench.current * 0.35) : null; },
  "Cable Seated Row": (cache) => { const lat = cache["Lat Pulldown"]; return lat ? Math.round(lat.current * 0.8) : null; },
  "Face Pull": () => 25,
  "Lateral Raise": () => 15,
  "EZ-Bar Curl": (cache) => { const bench = cache["Barbell Bench Press"]; return bench ? Math.round(bench.current * 0.35) : null; },
  "Cable Tricep Pushdown": (cache) => { const bench = cache["Barbell Bench Press"]; return bench ? Math.round(bench.current * 0.4) : null; },
  "Leg Press": (cache) => { const squat = cache["Barbell Back Squat"]; return squat ? Math.round(squat.current * 1.5) : null; },
  "Romanian Deadlift": (cache) => { const dl = cache["Conventional Deadlift"]; return dl ? Math.round(dl.current * 0.65) : null; },
  "Leg Curl": () => 50,
  "Leg Extension": () => 50,
  "Calf Raise": () => 100,
  "Dumbbell Shoulder Press": (cache) => { const bench = cache["Barbell Bench Press"]; return bench ? Math.round(bench.current * 0.3) : null; },
  "Cable Lateral Raise": () => 10,
  "Barbell Row": (cache) => { const dl = cache["Conventional Deadlift"]; return dl ? Math.round(dl.current * 0.5) : null; },
  "Dumbbell Row": (cache) => { const lat = cache["Lat Pulldown"]; return lat ? Math.round(lat.current * 0.4) : null; },
  "Hammer Curl": () => 25,
  "Overhead Tricep Extension": () => 25,
  "Walking Lunge": () => 20,
  "Standing Calf Raise": () => 25,
  "Nordic Hamstring Curl": () => 0,
  "Bulgarian Split Squat": () => 20,
  "Glute Bridge": () => 0,
  "Hip Thrust": (cache) => { const sq = cache["Barbell Back Squat"]; return sq ? Math.round(sq.current * 0.6) : 95; },
  "Seated Calf Raise": () => 45,
  "Goblet Squat": () => 35,
  "Step-Up": () => 20,
};

function getSuggestedWeight(exName, currentWeekNum) {
  const data = getExerciseData(exName);
  if (!data) {
    // No history — try to estimate from related exercises
    const estimator = WEIGHT_ESTIMATES[exName];
    if (estimator) {
      const cache = _weightsCache || {};
      const est = estimator(cache);
      if (est != null) return { weight: est, reason: est > 0 ? 'estimated' : 'bodyweight' };
    }
    // Generic fallback: guess based on exercise name keywords
    const nl = exName.toLowerCase();
    const cache = _weightsCache || {};
    const bench = cache["Barbell Bench Press"];
    const squat = cache["Barbell Back Squat"];
    const dl = cache["Conventional Deadlift"];
    if (nl.includes('curl') || nl.includes('raise') || nl.includes('fly') || nl.includes('extension')) {
      return { weight: bench ? Math.round(bench.current * 0.25) : 20, reason: 'estimated' };
    }
    if (nl.includes('press') || nl.includes('row')) {
      return { weight: bench ? Math.round(bench.current * 0.5) : 50, reason: 'estimated' };
    }
    if (nl.includes('squat') || nl.includes('lunge') || nl.includes('step')) {
      return { weight: squat ? Math.round(squat.current * 0.3) : 25, reason: 'estimated' };
    }
    if (nl.includes('deadlift') || nl.includes('hip') || nl.includes('thrust')) {
      return { weight: dl ? Math.round(dl.current * 0.5) : 65, reason: 'estimated' };
    }
    return { weight: null, reason: '' };
  }

  const currentWt = data.current || 0;
  const history = data.history || [];

  if (isDeloadWeek(currentWeekNum)) {
    return { weight: Math.round(currentWt * 0.6), reason: 'Deload week \u2014 60% weight, focus on form & recovery' };
  }

  if (history.length > 0) {
    const lastEntry = history[history.length - 1];
    const lastWeek = lastEntry.week || 0;
    const lastPhase = WEEK_TO_PHASE[lastWeek] || 1;
    const curPhase = WEEK_TO_PHASE[currentWeekNum] || 1;
    if (curPhase > lastPhase && !isDeloadWeek(lastWeek)) {
      if (lastPhase === 1 && curPhase === 2) {
        return { weight: Math.round(currentWt * 1.20), reason: 'phase 2: +20%' };
      }
      if (lastPhase === 2 && curPhase === 3) {
        return { weight: Math.round(currentWt * 1.10), reason: 'phase 3: +10%' };
      }
    }
  }

  const lastTwo = getLastRPEs(exName, 2);
  const inc = getProgressionIncrement(exName);

  if (lastTwo.length >= 2 && lastTwo[lastTwo.length - 1] === 'too_easy' && lastTwo[lastTwo.length - 2] === 'too_easy') {
    return { weight: currentWt + inc, reason: '\u2191' + inc + ' lb (easy x2)' };
  }
  if (lastTwo.length >= 2 && lastTwo[lastTwo.length - 1] === 'too_hard' && lastTwo[lastTwo.length - 2] === 'too_hard') {
    return { weight: Math.max(0, currentWt - inc), reason: '\u2193' + inc + ' lb (hard x2)' };
  }

  return { weight: currentWt, reason: '' };
}

function getWeightForExercise(exName, weekNum) {
  const suggestion = getSuggestedWeight(exName, weekNum);
  if (suggestion.weight !== null) {
    suggestion.weight = roundWeight(suggestion.weight, exName);
    return suggestion;
  }
  return { weight: null, reason: '' };
}

function getLastWeight(exName) {
  const data = getExerciseData(exName);
  if (!data || !data.history || data.history.length === 0) return null;
  return data.history[data.history.length - 1].weight;
}

function getWeightTrend(exName) {
  const data = getExerciseData(exName);
  if (!data || !data.history || data.history.length < 2) return 'same';
  const hist = data.history;
  const last = hist[hist.length - 1].weight;
  for (let i = hist.length - 2; i >= 0; i--) {
    if (hist[i].week !== hist[hist.length - 1].week) {
      if (last > hist[i].weight) return 'up';
      if (last < hist[i].weight) return 'down';
      return 'same';
    }
  }
  return 'same';
}

// ─── WELCOME & ONBOARDING ──────────────────────────────────────────────────

async function checkOnboardingComplete() {
  // Onboarding is only truly complete when ALL steps are done
  try {
    const [intakeRes, conRes, paRes, goalRes, foodRes, eqRes] = await Promise.all([
      fetch('/api/psych-intake/status'),
      fetch('/api/constraints'),
      fetch('/api/physical-assessment/status'),
      fetch('/api/goal'),
      fetch('/api/food-selections'),
      fetch('/api/equipment'),
    ]);
    const intake = await intakeRes.json();
    const con = await conRes.json();
    const pa = await paRes.json();
    const goal = await goalRes.json();
    const food = await foodRes.json();
    const eq = await eqRes.json();

    // plan_accepted is the FINAL gate — user must have reviewed and accepted the training plan
    const planAccepted = goal.plan_accepted || false;
    return intake.completed && con.completed && pa.completed && eq.completed && goal.computed && food.completed && planAccepted;
  } catch(e) {
    // If we can't check, fall back to baseline_done
    return _stateCache.baseline_done;
  }
}

async function resumeOnboarding() {
  // Check steps in FORWARD order — first incomplete step gets shown
  try {
    const intakeRes = await fetch('/api/psych-intake/status');
    const intakeData = await intakeRes.json();
    if (!intakeData.completed) {
      if (intakeData.started && intakeData.message_count > 0) {
        showPsychIntake(); // resume in-progress chat
      } else {
        showWelcome(); // not started
      }
      return;
    }

    const conRes = await fetch('/api/constraints');
    const conData = await conRes.json();
    if (!conData.completed) {
      showConstraints();
      return;
    }

    const paRes = await fetch('/api/physical-assessment/status');
    const paData = await paRes.json();
    if (!paData.completed) {
      showPhysicalAssessment();
      return;
    }

    // Physical done — check equipment
    const eqRes = await fetch('/api/equipment');
    const eqData = await eqRes.json();
    if (!eqData.completed) {
      showEquipmentSelection();
      return;
    }

    // Equipment done, constraints done — check goal
    const gRes = await fetch('/api/goal');
    const gData = await gRes.json();
    if (!gData.computed) {
      computeGoal();
      return;
    }
    window._goalData = gData;

    // Goal computed — check food
    const fRes = await fetch('/api/food-selections');
    const fData = await fRes.json();
    if (!fData.completed) {
      showFoodSelection();
      return;
    }

    // Everything done but baseline_done not set — show final reveal
    showFinalReveal();
  } catch(e) {
    console.error('Resume onboarding error:', e);
    showWelcome();
  }
}

function showWelcome() {
  const el = document.getElementById('baseline-overlay');
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
      <h2 style="font-size:2.2rem;margin-bottom:12px;letter-spacing:-0.02em">12 Weeks.</h2>
      <div style="font-size:15px;color:var(--muted);font-family:'DM Mono',monospace;margin-bottom:2.5rem">Align aspirations with actions.</div>
      <button class="btn btn-primary" style="width:100%;font-size:18px;padding:16px;font-weight:700" onclick="startOnboardingIntake()">I'm Ready</button>
    </div>
  </div>`;
}

function startOnboardingIntake() {
  showPsychIntake();
}

function skipToPhysicalBaseline() {
  showBaseline();
}

// ─── BASELINE ASSESSMENT ────────────────────────────────────────────────────
let baselineStep = 0;
let baselineWeights = {};

function showBaseline() {
  baselineStep = 0;
  baselineWeights = {};
  renderBaseline();
}

function estimate1RM(weight, reps) {
  if (reps <= 0) return 0;
  if (reps === 1) return weight;
  return Math.round(weight * (1 + reps / 30));
}

function workingWeightFrom1RM(oneRM) {
  return Math.round(oneRM * 0.75 / 5) * 5;
}

function renderBaseline() {
  const el = document.getElementById('baseline-overlay');
  if (baselineStep < 0) {
    el.innerHTML = '';
    return;
  }

  if (baselineStep === 0) {
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Baseline Assessment</h2>
        <div class="baseline-desc">
          Let's find your starting weights.<br><br>
          For each lift, load the test weight shown and do <strong>as many reps as you can</strong> with good form. Stop when form breaks down.<br><br>
          We'll calculate your working weights from there.
        </div>
        <button class="btn btn-primary" style="width:100%" onclick="baselineStep=1;renderBaseline()">Start Baseline Test (~10 min)</button>
      </div>
    </div>`;
    return;
  }

  const liftIdx = baselineStep - 1;

  // ─── MEASUREMENTS & PHOTOS STEP (after summary) ───
  if (liftIdx > BASELINE_LIFTS.length) {
    renderBaselineMeasurements(el);
    return;
  }

  // ─── SUMMARY SCREEN ───
  if (liftIdx === BASELINE_LIFTS.length) {
    let rows = '';
    for (const lift of BASELINE_LIFTS) {
      const w = baselineWeights[lift.name] || { reps: 0 };
      const oneRM = estimate1RM(lift.suggested, w.reps);
      const working = workingWeightFrom1RM(oneRM);
      rows += `<div class="baseline-summary-row">
        <span class="bsr-name">${lift.name}</span>
        <span class="bsr-detail"><strong>${w.reps} reps</strong> at ${lift.suggested} lb</span>
        <span class="bsr-weight">→ ${working} lb working</span>
      </div>`;
    }
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Your Baseline Results</h2>
        <div class="baseline-desc" style="margin-bottom:12px">
          Your reps determine your working weights. We set the test weight — you showed us what you can do.
        </div>
        <div class="baseline-summary">${rows}</div>
        <button class="btn btn-primary" style="width:100%" onclick="saveBaseline()">Start My 12 Weeks</button>
      </div>
    </div>`;
    return;
  }

  const lift = BASELINE_LIFTS[liftIdx];
  const existing = baselineWeights[lift.name] || {};

  let dots = '';
  for (let i = 0; i < BASELINE_LIFTS.length; i++) {
    const cls = i < liftIdx ? 'done' : i === liftIdx ? 'active' : '';
    dots += `<div class="bp-dot ${cls}"></div>`;
  }

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card">
      <div class="baseline-progress">${dots}</div>
      <div class="baseline-progress-text">${liftIdx + 1} / ${BASELINE_LIFTS.length}</div>
      <div class="baseline-exercise-name">${lift.name}</div>
      <div class="baseline-test-weight">Load <strong>${lift.suggested} lb</strong></div>
      <div class="baseline-hint">Do as many reps as you can with good form. Stop when form breaks.</div>
      <div class="baseline-inputs">
        <label>How many reps did you get?
          <input type="number" inputmode="numeric" id="bl-reps" value="${existing.reps || ''}" placeholder="e.g. 12" min="0" max="50">
        </label>
      </div>
      ${existing.reps ? `<div class="baseline-calc">
        Est 1RM: ${estimate1RM(lift.suggested, existing.reps)} lb &rarr; Working weight: ${workingWeightFrom1RM(estimate1RM(lift.suggested, existing.reps))} lb
      </div>` : ''}
      <div style="display:flex;gap:8px">
        ${liftIdx > 0 ? '<button class="btn btn-secondary" onclick="baselineBack()">Back</button>' : ''}
        <button class="btn btn-primary" style="flex:1" onclick="baselineNext()">${liftIdx === BASELINE_LIFTS.length - 1 ? 'See My Results' : 'Next Lift \u2192'}</button>
      </div>
    </div>
  </div>`;

  setTimeout(() => { const inp = document.getElementById('bl-reps'); if (inp) inp.focus(); }, 100);

  const repsInput = document.getElementById('bl-reps');
  if (repsInput) {
    repsInput.addEventListener('input', () => {
      const reps = parseInt(repsInput.value) || 0;
      baselineWeights[lift.name] = { reps };
      const calcEl = document.querySelector('.baseline-calc');
      if (reps > 0) {
        const oneRM = estimate1RM(lift.suggested, reps);
        const working = workingWeightFrom1RM(oneRM);
        if (calcEl) {
          calcEl.innerHTML = `Est 1RM: ${oneRM} lb &rarr; Working weight: ${working} lb`;
        } else {
          const btns = document.querySelector('.baseline-card div:last-child');
          const div = document.createElement('div');
          div.className = 'baseline-calc';
          div.innerHTML = `Est 1RM: ${oneRM} lb &rarr; Working weight: ${working} lb`;
          btns.parentNode.insertBefore(div, btns);
        }
      }
    });
  }
}

function baselineNext() {
  const liftIdx = baselineStep - 1;
  const lift = BASELINE_LIFTS[liftIdx];
  const repsVal = parseInt(document.getElementById('bl-reps').value) || 0;
  baselineWeights[lift.name] = { reps: repsVal };

  // Save this lift immediately to the DB so nothing is lost
  const oneRM = estimate1RM(lift.suggested, repsVal);
  const working = workingWeightFrom1RM(oneRM);
  apiPost('/api/weights', {
    exercise: lift.name,
    weight: working,
    sets_label: `baseline: ${lift.suggested}lb x ${repsVal}`,
    rpe: 'just_right',
    week: 0,
    day_idx: 0,
  });

  baselineStep++;
  renderBaseline();
}

function baselineBack() {
  baselineStep--;
  renderBaseline();
}

function saveBaseline() {
  const exercises = [];
  if (!_weightsCache) _weightsCache = {};
  for (const lift of BASELINE_LIFTS) {
    const bw = baselineWeights[lift.name] || { reps: 0 };
    const reps = bw.reps || 10;
    const oneRM = estimate1RM(lift.suggested, reps);
    const working = workingWeightFrom1RM(oneRM);
    _weightsCache[lift.name] = {
      current: working,
      history: [{
        weight: working,
        reps: `baseline: ${lift.suggested}lb x ${reps}`,
        rpe: 'just_right',
        date: todayStr(),
        week: 0,
        day: 0,
        testWeight: lift.suggested,
        testReps: reps,
        estimated1RM: oneRM,
      }],
    };
    exercises.push({
      name: lift.name,
      working_weight: working,
      test_weight: lift.suggested,
      test_reps: reps,
      estimated_1rm: oneRM,
    });
  }
  apiPost('/api/weights/baseline', { exercises });
  apiPost('/api/physical-assessment', { gym_baseline_done: true, completed: true });
  _stateCache.baseline_done = true;
  apiPost('/api/state', { baseline_done: true });
  showEquipmentSelection();
}

// ─── BASELINE MEASUREMENTS & PHOTOS STEP ────────────────────────────────────
let _baselinePhotoData = {}; // { front: base64, side: base64, back: base64 }
let _baselinePhotoResults = {}; // { front: {id, analysis}, ... }

function renderBaselineMeasurements(el) {
  const poses = ['front', 'side', 'back'];
  let photoSlotsHtml = '';
  for (const pose of poses) {
    let slotContent;
    if (_baselinePhotoData[pose]) {
      const result = _baselinePhotoResults[pose];
      let analysisHtml = '';
      if (result && result.analysis) {
        analysisHtml = `<div class="photo-analysis">
          <div class="photo-analysis-label">AI Coach Analysis</div>
          ${result.analysis}
        </div>`;
      }
      slotContent = `<div class="photo-preview">
        <img src="${_baselinePhotoData[pose]}" alt="${pose}">
        <button class="photo-retake" onclick="retakeBaselinePhoto('${pose}')">Retake</button>
      </div>${analysisHtml}`;
    } else {
      slotContent = `<div class="photo-upload-btn" onclick="this.querySelector('input').click()">
        <div class="photo-icon">&#128247;</div>
        <div>Tap to capture</div>
        <input type="file" accept="image/*" capture="environment" onchange="handleBaselinePhotoCapture('${pose}', this)">
      </div>`;
    }
    photoSlotsHtml += `<div class="photo-slot">
      <div class="photo-slot-label">${pose}</div>
      <div id="bl-photo-slot-${pose}">${slotContent}</div>
    </div>`;
  }

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card baseline-measurements-card">
      <h2>Baseline Measurements &amp; Photos</h2>
      <div class="baseline-desc" style="margin-bottom:1rem">
        Record your starting measurements and Day 1 photos. You can skip this and do it later.
      </div>

      <div class="bl-measure-section">
        <div class="bl-measure-row">
          <label for="bl-bodyweight" class="bl-measure-label">Body Weight (lbs)</label>
          <input type="number" inputmode="decimal" id="bl-bodyweight" class="bl-measure-input bl-measure-input-lg" placeholder="e.g. 185" step="0.1" min="50" max="500">
        </div>
        <div class="bl-measure-row">
          <label for="bl-waist" class="bl-measure-label">Waist (inches)</label>
          <input type="number" inputmode="decimal" id="bl-waist" class="bl-measure-input" placeholder="e.g. 34" step="0.1" min="15" max="80">
        </div>
        <div class="bl-measure-row">
          <label for="bl-notes" class="bl-measure-label">Notes (optional)</label>
          <textarea id="bl-notes" class="bl-measure-textarea" rows="2" placeholder="e.g. Measured at navel, morning before eating"></textarea>
        </div>
      </div>

      <div class="bl-photo-section">
        <div class="bl-photo-heading">Day 1 Photos</div>
        <div class="bl-photo-desc">Take your Day 1 photos. You'll retake these every Sunday to track progress.</div>
        <div class="photo-grid">${photoSlotsHtml}</div>
      </div>

      <div id="bl-measure-status" class="bl-measure-status" style="display:none"></div>

      <div style="display:flex;flex-direction:column;gap:10px;margin-top:1.25rem">
        <button class="btn btn-primary" style="width:100%;font-size:16px;padding:14px" onclick="saveBaselineMeasurementsAndStart()">Start My 12 Weeks</button>
        <button class="btn btn-secondary bl-skip-btn" style="width:100%;font-size:15px;padding:12px" onclick="skipBaselineMeasurements()">Skip for Now</button>
      </div>
    </div>
  </div>`;
}

function retakeBaselinePhoto(pose) {
  delete _baselinePhotoData[pose];
  delete _baselinePhotoResults[pose];
  const slotEl = document.getElementById(`bl-photo-slot-${pose}`);
  if (slotEl) {
    slotEl.innerHTML = `<div class="photo-upload-btn" onclick="this.querySelector('input').click()">
      <div class="photo-icon">&#128247;</div>
      <div>Tap to capture</div>
      <input type="file" accept="image/*" capture="environment" onchange="handleBaselinePhotoCapture('${pose}', this)">
    </div>`;
  }
}

async function handleBaselinePhotoCapture(pose, inputEl) {
  const file = inputEl.files[0];
  if (!file) return;

  const slotEl = document.getElementById(`bl-photo-slot-${pose}`);
  if (!slotEl) return;

  slotEl.innerHTML = `<div class="photo-loading"><div class="spinner"></div><div>Compressing...</div></div>`;

  try {
    const base64 = await compressImage(file, 800, 0.7);
    _baselinePhotoData[pose] = base64;

    slotEl.innerHTML = `
      <div class="photo-preview">
        <img src="${base64}" alt="${pose}">
        <button class="photo-retake" onclick="retakeBaselinePhoto('${pose}')">Retake</button>
      </div>
      <div class="photo-loading" id="bl-photo-analysis-loading-${pose}">
        <div class="spinner"></div>
        <div>Your AI Coach is analyzing...</div>
      </div>`;

    const res = await fetch('/api/photos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_data: base64, pose: pose })
    });
    const result = await res.json();
    _baselinePhotoResults[pose] = result;
    _photosCache = null;
    _photoImagesCache[result.id] = base64;

    const loadingEl = document.getElementById(`bl-photo-analysis-loading-${pose}`);
    if (loadingEl) {
      if (result.analysis) {
        loadingEl.outerHTML = `<div class="photo-analysis">
          <div class="photo-analysis-label">AI Coach Analysis</div>
          ${result.analysis}
        </div>`;
      } else {
        loadingEl.remove();
      }
    }
  } catch (e) {
    console.error('Baseline photo upload failed:', e);
    slotEl.innerHTML = `<div style="color:var(--run-hiit);font-size:14px;padding:10px">Upload failed. Tap to retry.</div>`;
    delete _baselinePhotoData[pose];
  }
}

async function saveBaselineMeasurementsAndStart() {
  const statusEl = document.getElementById('bl-measure-status');
  const weightVal = parseFloat(document.getElementById('bl-bodyweight').value);
  const waistVal = parseFloat(document.getElementById('bl-waist').value);
  const notesVal = (document.getElementById('bl-notes').value || '').trim();
  const today = todayStr();

  // Show loading
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.innerHTML = `<div class="photo-loading"><div class="spinner"></div><div>Saving measurements...</div></div>`;
  }

  try {
    // Save body weight
    if (weightVal && weightVal > 0) {
      await fetch('/api/bodyweight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: today, weight: weightVal })
      });
      _bodyweightCache = null;
    }

    // Save waist measurement
    if (waistVal && waistVal > 0) {
      await fetch('/api/measurements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: today, waist: waistVal, notes: notesVal })
      });
    }

    // Upload any photos that haven't been uploaded yet (they're uploaded on capture, but just in case)
    const poses = ['front', 'side', 'back'];
    const photoAnalyses = [];
    for (const pose of poses) {
      if (_baselinePhotoData[pose] && !_baselinePhotoResults[pose]) {
        if (statusEl) {
          statusEl.innerHTML = `<div class="photo-loading"><div class="spinner"></div><div>Uploading ${pose} photo...</div></div>`;
        }
        const res = await fetch('/api/photos', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ photo_data: _baselinePhotoData[pose], pose: pose })
        });
        const result = await res.json();
        _baselinePhotoResults[pose] = result;
        _photosCache = null;
        _photoImagesCache[result.id] = _baselinePhotoData[pose];
      }
      if (_baselinePhotoResults[pose] && _baselinePhotoResults[pose].analysis) {
        photoAnalyses.push({ pose, analysis: _baselinePhotoResults[pose].analysis });
      }
    }

    // Show brief analysis summary if photos were uploaded
    if (photoAnalyses.length > 0) {
      let summaryHtml = '<div class="bl-analysis-summary"><div class="bl-analysis-summary-title">Photo Analysis Summary</div>';
      for (const pa of photoAnalyses) {
        summaryHtml += `<div class="bl-analysis-item"><strong>${pa.pose}:</strong> ${pa.analysis}</div>`;
      }
      summaryHtml += '</div>';

      if (statusEl) {
        statusEl.innerHTML = summaryHtml + `<div style="margin-top:12px"><div class="photo-loading"><div class="spinner"></div><div>Starting program...</div></div></div>`;
      }
      // Brief pause so user can see the summary
      await new Promise(r => setTimeout(r, 2000));
    }

    // Psych intake already happened, finish onboarding
    _baselinePhotoData = {};
    _baselinePhotoResults = {};
    saveBaseline();
  } catch (e) {
    console.error('Error saving baseline measurements:', e);
    if (statusEl) {
      statusEl.innerHTML = `<div style="color:var(--run-hiit);font-size:15px;padding:10px">Error saving. Please try again.</div>`;
      statusEl.style.display = 'block';
    }
  }
}

function skipBaselineMeasurements() {
  _baselinePhotoData = {};
  _baselinePhotoResults = {};
  saveBaseline();
}

function skipMorningCheckin() {
  document.getElementById('morning-checkin-overlay').innerHTML = '';
}

// ─── PHYSICAL ASSESSMENT FLOW ──────────────────────────────────────────────
let _paStep = 0; // 0 = questions, 1 = measurements, 2 = baseline
let _paData = { has_gym: null, has_tape: null, weight: null, height: null, waist: null };
let _bwBaselineStep = 0;
let _bwBaselineData = {};

// ─── CONSTRAINTS STEP ──────────────────────────────────────────────────────
let _constraintStep = 0;
let _constraintData = { food_restrictions: [], custom_allergies: '', scheduled_activities: [], schedule_notes: '' };

function showConstraints() {
  _constraintStep = 0;
  _constraintData = { food_restrictions: [], custom_allergies: '', scheduled_activities: [], schedule_notes: '' };
  renderConstraints();
}

function renderConstraints() {
  const el = document.getElementById('baseline-overlay');

  if (_constraintStep === 0) {
    // Food restrictions
    const restrictions = [
      {id: 'vegetarian', label: 'Vegetarian'},
      {id: 'vegan', label: 'Vegan'},
      {id: 'no_dairy', label: 'No Dairy'},
      {id: 'no_gluten', label: 'No Gluten'},
      {id: 'halal', label: 'Halal'},
      {id: 'kosher', label: 'Kosher'},
    ];

    const checkboxes = restrictions.map(r => `<label class="constraint-checkbox">
      <input type="checkbox" value="${r.id}" ${_constraintData.food_restrictions.includes(r.id) ? 'checked' : ''} onchange="toggleConstraint('${r.id}')">
      <span>${r.label}</span>
    </label>`).join('');

    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Food Restrictions</h2>
        <div class="baseline-desc">Any dietary restrictions we need to know about?</div>
        <div class="constraint-list">${checkboxes}</div>
        <div class="pa-measure-row" style="margin-top:1rem">
          <label>Any allergies? (optional)</label>
          <input type="text" id="constraint-allergies" placeholder="e.g. shellfish, tree nuts" value="${_constraintData.custom_allergies}">
        </div>
        <div style="display:flex;gap:8px;margin-top:1.5rem">
          <button class="btn btn-secondary" onclick="_constraintStep=1;renderConstraints()">No Restrictions</button>
          <button class="btn btn-primary" style="flex:1" onclick="constraintFoodNext()">Next</button>
        </div>
      </div>
    </div>`;
    return;
  }

  if (_constraintStep === 1) {
    // Scheduled activities
    const actList = _constraintData.scheduled_activities.map((a, i) =>
      `<div class="scheduled-activity-row">
        <span>${a.day} — ${a.activity} (${a.duration_min}min)</span>
        <button onclick="removeScheduledActivity(${i})" class="remove-btn">&times;</button>
      </div>`
    ).join('') || '<div style="color:var(--muted);font-size:14px">No activities added yet</div>';

    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Scheduled Commitments</h2>
        <div class="baseline-desc">Any group runs, races, or activities we need to build around?</div>

        <div id="scheduled-list">${actList}</div>

        <div class="add-activity-form" style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)">
          <div class="pa-measure-row">
            <label>Day</label>
            <select id="activity-day" class="pa-select">
              <option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option><option selected>Saturday</option><option>Sunday</option>
            </select>
          </div>
          <div class="pa-measure-row">
            <label>Activity</label>
            <input type="text" id="activity-name" placeholder="e.g. Group trail run">
          </div>
          <div class="pa-measure-row">
            <label>Duration (minutes)</label>
            <input type="number" inputmode="numeric" id="activity-duration" placeholder="e.g. 90" min="10" max="300">
          </div>
          <button class="btn btn-secondary" style="width:100%;margin-top:8px" onclick="addScheduledActivity()">+ Add Activity</button>
        </div>

        <div class="pa-measure-row" style="margin-top:1rem">
          <label>Anything else about your schedule? (optional)</label>
          <textarea id="constraint-schedule-notes" rows="2" placeholder="e.g. I travel every other Thursday" style="width:100%;background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:8px;border-radius:6px;font-size:14px">${_constraintData.schedule_notes}</textarea>
        </div>

        <button class="btn btn-primary" style="width:100%;margin-top:1.5rem" onclick="constraintScheduleNext()">Next: Physical Assessment</button>
      </div>
    </div>`;
    return;
  }
}

function toggleConstraint(id) {
  const idx = _constraintData.food_restrictions.indexOf(id);
  if (idx >= 0) _constraintData.food_restrictions.splice(idx, 1);
  else _constraintData.food_restrictions.push(id);
}

function constraintFoodNext() {
  const allergies = (document.getElementById('constraint-allergies')?.value || '').trim();
  _constraintData.custom_allergies = allergies;
  _constraintStep = 1;
  renderConstraints();
}

function addScheduledActivity() {
  const day = document.getElementById('activity-day').value;
  const name = (document.getElementById('activity-name')?.value || '').trim();
  const duration = parseInt(document.getElementById('activity-duration')?.value) || 60;
  if (!name) return;
  _constraintData.scheduled_activities.push({ day, activity: name, duration_min: duration, type: 'activity' });
  renderConstraints();
}

function removeScheduledActivity(idx) {
  _constraintData.scheduled_activities.splice(idx, 1);
  renderConstraints();
}

async function constraintScheduleNext() {
  _constraintData.schedule_notes = (document.getElementById('constraint-schedule-notes')?.value || '').trim();
  // Save constraints and WAIT for it to complete before moving on
  await fetch('/api/constraints', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ ..._constraintData, completed: true }),
  });
  // Clear food catalog cache so it re-fetches with these restrictions
  _foodCatalog = null;
  showPhysicalAssessment();
}

async function showPhysicalAssessment() {
  _paData = { has_gym: null, has_tape: null, weight: null, height: null, waist: null, chest: null, bicep: null, thigh: null, hips: null, neck: null };
  // Check if gym/tape questions were already answered — skip to measurements if so
  try {
    const res = await fetch('/api/physical-assessment/status');
    const status = await res.json();
    if (status.started && status.has_gym !== null) {
      _paData.has_gym = status.has_gym;
      _paData.has_tape = status.has_measuring_tape;
      _paStep = 1; // Skip to measurements
    } else {
      _paStep = 0;
    }
  } catch(e) {
    _paStep = 0;
  }
  renderPhysicalAssessment();
}

function renderPhysicalAssessment() {
  const el = document.getElementById('baseline-overlay');

  if (_paStep === 0) {
    // Step 1: Questions
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Physical Assessment</h2>
        <div class="baseline-desc" style="margin-bottom:1.5rem">A few quick questions so we can set up the right baseline test for you.</div>

        <div class="pa-question">
          <div class="pa-question-text">Do you have access to a gym with barbells and machines?</div>
          <div class="pa-choices">
            <div class="pa-choice${_paData.has_gym === true ? ' selected' : ''}" onclick="_paData.has_gym=true;paUpdateChoices()">Yes</div>
            <div class="pa-choice${_paData.has_gym === false ? ' selected' : ''}" onclick="_paData.has_gym=false;paUpdateChoices()">No</div>
          </div>
        </div>

        <div class="pa-question">
          <div class="pa-question-text">Do you have a measuring tape?</div>
          <div class="pa-choices">
            <div class="pa-choice${_paData.has_tape === true ? ' selected' : ''}" onclick="_paData.has_tape=true;paUpdateChoices()">Yes</div>
            <div class="pa-choice${_paData.has_tape === false ? ' selected' : ''}" onclick="_paData.has_tape=false;paUpdateChoices()">No</div>
          </div>
        </div>

        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="paNextFromQuestions()" ${_paData.has_gym === null || _paData.has_tape === null ? 'disabled' : ''}>Next</button>
      </div>
    </div>`;
    return;
  }

  if (_paStep === 1) {
    // Step 2: Measurements
    const tapeRows = _paData.has_tape ? `
        <div class="pa-measure-section-label">Tape Measurements</div>
        <div class="pa-measure-hint">Measure relaxed, standing straight, tape flat against skin. Don't suck in.</div>
        <div class="pa-measure-row">
          <label>Waist — narrowest point above hip bones (inches)</label>
          <input type="number" inputmode="decimal" id="pa-waist" placeholder="e.g. 34" step="0.25" min="15" max="80" value="${_paData.waist || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Chest — at nipple line, arms down (inches)</label>
          <input type="number" inputmode="decimal" id="pa-chest" placeholder="e.g. 42" step="0.25" min="20" max="70" value="${_paData.chest || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Bicep — flexed, widest point, right arm (inches)</label>
          <input type="number" inputmode="decimal" id="pa-bicep" placeholder="e.g. 14" step="0.25" min="6" max="30" value="${_paData.bicep || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Thigh — widest point, right leg (inches)</label>
          <input type="number" inputmode="decimal" id="pa-thigh" placeholder="e.g. 24" step="0.25" min="10" max="45" value="${_paData.thigh || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Hips — widest point around glutes (inches)</label>
          <input type="number" inputmode="decimal" id="pa-hips" placeholder="e.g. 40" step="0.25" min="20" max="70" value="${_paData.hips || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Neck — around Adam's apple (inches)</label>
          <input type="number" inputmode="decimal" id="pa-neck" placeholder="e.g. 16" step="0.25" min="8" max="30" value="${_paData.neck || ''}">
        </div>` : '';

    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Body Measurements</h2>
        <div class="baseline-desc" style="margin-bottom:1rem">Let's get your starting numbers. These are your Day 1 benchmarks.</div>

        <div class="pa-measure-row">
          <label>Body Weight (lbs)</label>
          <input type="number" inputmode="decimal" id="pa-weight" placeholder="e.g. 185" step="0.1" min="50" max="500" value="${_paData.weight || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Height (inches)</label>
          <input type="number" inputmode="decimal" id="pa-height" placeholder="e.g. 70 (5'10 = 70)" step="0.1" min="48" max="96" value="${_paData.height || ''}">
        </div>
        ${tapeRows}

        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="paNextFromMeasurements()">Next</button>
      </div>
    </div>`;
    return;
  }

  if (_paStep === 2) {
    // Step 3: Route to gym or bodyweight baseline
    if (_paData.has_gym) {
      showBaseline();
    } else {
      _bwBaselineStep = 0;
      _bwBaselineData = {};
      renderBodyweightBaseline();
    }
  }
}

function paUpdateChoices() {
  // Update selected states without re-rendering the whole page
  const choices = document.querySelectorAll('.pa-question');
  if (choices[0]) {
    const gymBtns = choices[0].querySelectorAll('.pa-choice');
    gymBtns[0].classList.toggle('selected', _paData.has_gym === true);
    gymBtns[1].classList.toggle('selected', _paData.has_gym === false);
  }
  if (choices[1]) {
    const tapeBtns = choices[1].querySelectorAll('.pa-choice');
    tapeBtns[0].classList.toggle('selected', _paData.has_tape === true);
    tapeBtns[1].classList.toggle('selected', _paData.has_tape === false);
  }
  // Enable/disable next button
  const nextBtn = document.querySelector('.pa-question ~ .btn-primary, .baseline-card > .btn-primary');
  if (nextBtn) nextBtn.disabled = (_paData.has_gym === null || _paData.has_tape === null);
}

function paNextFromQuestions() {
  if (_paData.has_gym === null || _paData.has_tape === null) return;
  // Save questions to backend
  apiPost('/api/physical-assessment', { has_gym: _paData.has_gym, has_measuring_tape: _paData.has_tape });
  _paStep = 1;
  renderPhysicalAssessment();
}

async function paNextFromMeasurements() {
  const getVal = (id) => { const el = document.getElementById(id); return el ? parseFloat(el.value) || null : null; };

  _paData.weight = getVal('pa-weight');
  _paData.height = getVal('pa-height');
  _paData.waist = getVal('pa-waist');
  _paData.chest = getVal('pa-chest');
  _paData.bicep = getVal('pa-bicep');
  _paData.thigh = getVal('pa-thigh');
  _paData.hips = getVal('pa-hips');
  _paData.neck = getVal('pa-neck');

  // Save measurements
  const payload = {};
  if (_paData.weight) payload.bodyweight = _paData.weight;
  if (_paData.height) payload.height = _paData.height;
  if (_paData.waist) payload.waist = _paData.waist;
  if (_paData.chest) payload.chest = _paData.chest;
  if (_paData.bicep) payload.bicep = _paData.bicep;
  if (_paData.thigh) payload.thigh = _paData.thigh;
  if (_paData.hips) payload.hips = _paData.hips;
  if (_paData.neck) payload.neck = _paData.neck;
  apiPost('/api/physical-assessment', payload);

  // Save body weight to bodyweight tracker — AWAIT to ensure it's stored
  if (_paData.weight) {
    await fetch('/api/bodyweight', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ date: todayStr(), weight: _paData.weight }) });
    if (!Array.isArray(_bodyweightCache)) _bodyweightCache = [];
    _bodyweightCache.push({ date: todayStr(), weight: _paData.weight });
  }

  _paStep = 2;
  renderPhysicalAssessment();
}

// ─── BODYWEIGHT BASELINE FLOW ──────────────────────────────────────────────
const BW_BASELINE_EXERCISES = [
  {
    key: 'pushups',
    name: 'Pushups',
    hint: 'Do as many pushups as you can with good form. If you can\'t do a full pushup, do them from your knees.',
    inputLabel: 'Reps',
    hasKneesCheckbox: true,
  },
  {
    key: 'plank',
    name: 'Plank Hold',
    hint: 'Hold a plank as long as you can. Time yourself.',
    inputLabel: 'Seconds',
  },
  {
    key: 'squats',
    name: 'Bodyweight Squats',
    hint: 'Do as many bodyweight squats as you can. Full depth, heels on the ground.',
    inputLabel: 'Reps',
  },
  {
    key: 'lunges',
    name: 'Lunges',
    hint: 'Do as many walking lunges as you can per leg.',
    inputLabel: 'Per leg',
  },
  {
    key: 'pullups',
    name: 'Pull-ups',
    hint: 'If you have access to a bar, how many pull-ups can you do? Enter 0 if none or no bar available.',
    inputLabel: 'Reps',
  },
];

function renderBodyweightBaseline() {
  const el = document.getElementById('baseline-overlay');
  const total = BW_BASELINE_EXERCISES.length;

  if (_bwBaselineStep < total) {
    const ex = BW_BASELINE_EXERCISES[_bwBaselineStep];
    const existing = _bwBaselineData[ex.key] || {};

    let dots = '';
    for (let i = 0; i < total; i++) {
      const cls = i < _bwBaselineStep ? 'done' : i === _bwBaselineStep ? 'active' : '';
      dots += '<div class="bp-dot ' + cls + '"></div>';
    }

    const checkboxHtml = ex.hasKneesCheckbox ? `<div class="bw-assess-checkbox">
        <input type="checkbox" id="bw-knees" ${existing.from_knees ? 'checked' : ''}>
        <label for="bw-knees">These were from my knees</label>
      </div>` : '';

    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card bw-assess-card">
        <div class="baseline-progress">${dots}</div>
        <div class="baseline-progress-text">${_bwBaselineStep + 1} / ${total}</div>
        <div class="bw-assess-exercise">${ex.name}</div>
        <div class="bw-assess-hint">${ex.hint}</div>
        <div class="bw-assess-input">
          <label>${ex.inputLabel}</label>
          <input type="number" inputmode="numeric" id="bw-input" value="${existing.value || ''}" placeholder="0" min="0">
        </div>
        ${checkboxHtml}
        <div style="display:flex;gap:8px">
          ${_bwBaselineStep > 0 ? '<button class="btn btn-secondary" onclick="bwBaselineBack()">Back</button>' : ''}
          <button class="btn btn-primary" style="flex:1" onclick="bwBaselineNext()">${_bwBaselineStep === total - 1 ? 'See My Results' : 'Next \u2192'}</button>
        </div>
      </div>
    </div>`;

    setTimeout(() => { const inp = document.getElementById('bw-input'); if (inp) inp.focus(); }, 100);
    return;
  }

  // Summary screen
  let rows = '';
  for (const ex of BW_BASELINE_EXERCISES) {
    const data = _bwBaselineData[ex.key] || {};
    let valStr = (data.value || 0) + (ex.key === 'plank' ? ' sec' : ' reps');
    if (ex.hasKneesCheckbox && data.from_knees) valStr += ' (from knees)';
    rows += `<div class="bw-assess-summary-row">
      <span>${ex.name}</span>
      <span>${valStr}</span>
    </div>`;
  }

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card bw-assess-card">
      <h2>Your Bodyweight Baseline</h2>
      <div class="bw-assess-summary">${rows}</div>
      <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="saveBwBaseline()">Start My 12 Weeks</button>
    </div>
  </div>`;
}

function bwBaselineNext() {
  const ex = BW_BASELINE_EXERCISES[_bwBaselineStep];
  const val = parseInt(document.getElementById('bw-input').value) || 0;
  const kneesEl = document.getElementById('bw-knees');
  _bwBaselineData[ex.key] = { value: val, from_knees: kneesEl ? kneesEl.checked : false };

  // Save immediately — map to backend field names
  const keyMap = { pushups: 'pushup_count', plank: 'plank_seconds', squats: 'squat_count', lunges: 'lunge_count_per_leg', pullups: 'pullup_count' };
  const payload = {};
  payload[keyMap[ex.key] || ex.key] = val;
  if (ex.hasKneesCheckbox) payload.pushup_from_knees = kneesEl ? kneesEl.checked : false;
  apiPost('/api/physical-assessment', payload);

  _bwBaselineStep++;
  renderBodyweightBaseline();
}

function bwBaselineBack() {
  _bwBaselineStep--;
  renderBodyweightBaseline();
}

function saveBwBaseline() {
  apiPost('/api/physical-assessment', { completed: true });
  _stateCache.baseline_done = true;
  apiPost('/api/state', { baseline_done: true });
  showEquipmentSelection();
}

// ─── FULL ATHLETE PROFILE ──────────────────────────────────────────────────
async function showFullProfile() {
  const el = document.getElementById('baseline-overlay');
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
      <h2 style="font-size:1.5rem;margin-bottom:16px">Building Your Athlete Profile</h2>
      <div class="chat-typing" style="justify-content:center;margin:1.5rem 0"><span></span><span></span><span></span></div>
      <div style="font-size:14px;color:var(--muted);font-family:'DM Mono',monospace">Combining your psych intake + physical assessment...</div>
    </div>
  </div>`;

  try {
    // Start profile generation (returns job_id immediately)
    const startRes = await fetch('/api/full-profile/generate', { method: 'POST' });
    const startData = await startRes.json();
    if (!startData.job_id) throw new Error('No job_id');

    // Poll for result
    let profile = null;
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const pollRes = await fetch('/api/full-profile/result/' + startData.job_id);
      const pollData = await pollRes.json();
      if (pollData.status === 'pending') continue;
      profile = pollData.profile;
      break;
    }

    if (profile) {
      el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card psych-intake-card">
          <h2 style="margin-bottom:0.75rem">Your Athlete Profile</h2>
          <div class="psych-report">${renderMarkdown(profile)}</div>
          <div style="margin-top:1.5rem">
            <button class="btn btn-primary" style="width:100%;font-size:16px;padding:14px" onclick="showWeightProjection()">Next: Weight Projection</button>
          </div>
        </div>
      </div>`;
    } else {
      finishOnboarding();
    }
  } catch (e) {
    console.error('Full profile error:', e);
    finishOnboarding();
  }
}

// ─── EQUIPMENT SELECTION ──────────────────────────────────────────────────
let _equipCatalog = null;
let _equipSelections = [];
let _equipStep = 0;

async function showEquipmentSelection() {
    const el = document.getElementById('baseline-overlay');

    if (!_equipCatalog) {
        el.innerHTML = `<div class="baseline-overlay"><div class="baseline-card" style="text-align:center;padding:2rem"><div class="chat-typing" style="justify-content:center"><span></span><span></span><span></span></div><div style="margin-top:8px;color:var(--muted);font-size:13px">Loading equipment list...</div></div></div>`;
        try {
            const res = await fetch('/api/equipment/catalog');
            if (!res.ok) throw new Error('Failed');
            _equipCatalog = await res.json();
        } catch(e) {
            computeGoal(); // Skip on error
            return;
        }
    }

    _equipStep = 0;
    _equipCategories = Object.keys(_equipCatalog);
    renderEquipmentSelection();
}

let _equipCategories = [];

function equipNext() { _equipStep++; renderEquipmentSelection(); }
function equipBack() { _equipStep--; renderEquipmentSelection(); }
function equipRestart() { _equipStep = 0; renderEquipmentSelection(); }

function renderEquipmentSelection() {
    const el = document.getElementById('baseline-overlay');
    const categories = _equipCategories;

    if (_equipStep >= categories.length) {
        const selectedNames = _equipSelections.map(id => {
            for (const cat of Object.values(_equipCatalog)) {
                const item = cat.items.find(i => i.id === id);
                if (item) return item.name;
            }
            return id;
        });

        el.innerHTML = `<div class="baseline-overlay">
            <div class="baseline-card">
                <h2>Your Equipment</h2>
                <div class="baseline-desc" style="margin-bottom:1rem">This is what we'll program for. You can swap exercises anytime during workouts.</div>
                <div class="equip-confirm-list">${selectedNames.length > 0 ? selectedNames.map(n => '<div class="equip-confirm-item">' + n + '</div>').join('') : '<div style="color:var(--muted)">No equipment selected — bodyweight only</div>'}</div>
                <div style="display:flex;gap:8px;margin-top:1.5rem">
                    <button class="btn btn-secondary" onclick="equipRestart()">Change</button>
                    <button class="btn btn-primary" style="flex:1" onclick="saveEquipmentSelections()">Confirm Equipment</button>
                </div>
            </div>
        </div>`;
        return;
    }

    const catKey = categories[_equipStep];
    const cat = _equipCatalog[catKey];

    let dots = '';
    for (let i = 0; i < categories.length; i++) {
        dots += '<div class="bp-dot ' + (i < _equipStep ? 'done' : i === _equipStep ? 'active' : '') + '"></div>';
    }

    const items = cat.items.map(item => {
        const isSelected = _equipSelections.includes(item.id);
        return '<div class="food-item' + (isSelected ? ' selected' : '') + '" onclick="toggleEquip(\'' + item.id + '\')">' +
            '<div class="food-item-name">' + item.name + '</div>' +
        '</div>';
    }).join('');

    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card">
            <div class="baseline-progress">${dots}</div>
            <h2>${cat.label}</h2>
            <div class="baseline-desc">Tap everything your gym has.</div>
            <div class="food-grid">${items}</div>
            <div style="display:flex;gap:8px;margin-top:1rem">
                ${_equipStep > 0 ? '<button class="btn btn-secondary" onclick="equipBack()">Back</button>' : ''}
                <button class="btn btn-primary" style="flex:1" onclick="equipNext()">${_equipStep === categories.length - 1 ? 'Review' : 'Next'}</button>
            </div>
        </div>
    </div>`;
}

function toggleEquip(id) {
    const idx = _equipSelections.indexOf(id);
    if (idx >= 0) {
        _equipSelections.splice(idx, 1);
    } else {
        _equipSelections.push(id);
    }
    // Update in-place
    document.querySelectorAll('.food-item').forEach(item => {
        const oc = item.getAttribute('onclick') || '';
        const m = oc.match(/toggleEquip\('([^']+)'\)/);
        if (m) {
            item.classList.toggle('selected', _equipSelections.includes(m[1]));
        }
    });
}

async function saveEquipmentSelections() {
    await fetch('/api/equipment', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ available_equipment: _equipSelections, completed: true }),
    });
    computeGoal();
}

// ─── COMPUTE GOAL ──────────────────────────────────────────────────────────
async function computeGoal() {
  const el = document.getElementById('baseline-overlay');
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
      <h2 style="font-size:1.5rem;margin-bottom:16px">Computing Your Plan</h2>
      <div class="chat-typing" style="justify-content:center;margin:1.5rem 0"><span></span><span></span><span></span></div>
      <div style="font-size:14px;color:var(--muted);font-family:'DM Mono',monospace">Analyzing your goals and building your program...</div>
    </div>
  </div>`;

  try {
    const res = await fetch('/api/goal/compute', { method: 'POST' });
    const goalData = await res.json();
    window._goalData = goalData;
    showFoodSelection();
  } catch(e) {
    console.error('Goal computation failed:', e);
    showFoodSelection(); // Continue anyway
  }
}

// ─── FOOD SELECTION ────────────────────────────────────────────────────────
let _foodCatalog = null;
let _foodSelections = { proteins: [], carbs: [], vegetables: [], fats: [] };
let _foodStep = 0;
const FOOD_CATEGORIES = ['proteins', 'carbs', 'vegetables', 'fats'];
const FOOD_MIN = 3;
const FOOD_MAX = 5;

async function showFoodSelection() {
  const el = document.getElementById('baseline-overlay');

  if (!_foodCatalog || !_foodCatalog.proteins) {
    el.innerHTML = `<div class="baseline-overlay"><div class="baseline-card" style="text-align:center;padding:2rem"><div class="chat-typing" style="justify-content:center"><span></span><span></span><span></span></div><div style="margin-top:8px;color:var(--muted);font-size:13px">Loading food catalog...</div></div></div>`;
    try {
      const res = await fetch('/api/food-catalog');
      if (!res.ok) throw new Error('Food catalog returned ' + res.status);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      if (!data.proteins || data.proteins.length === 0) throw new Error('Empty catalog');
      _foodCatalog = data;
    } catch(e) {
      console.error('Food catalog error:', e);
      el.innerHTML = `<div class="baseline-overlay"><div class="baseline-card" style="text-align:center;padding:2rem">
        <h2 style="color:var(--amber)">Food Catalog Error</h2>
        <p style="color:var(--muted)">${e.message}</p>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="_foodCatalog=null;showFoodSelection()">Retry</button>
      </div></div>`;
      return;
    }
  }

  _foodStep = 0;
  renderFoodSelection();
}

function renderFoodSelection() {
  const el = document.getElementById('baseline-overlay');
  const category = FOOD_CATEGORIES[_foodStep];

  if (_foodStep >= FOOD_CATEGORIES.length) {
    // Confirm screen
    let summary = '';
    for (const cat of FOOD_CATEGORIES) {
      const items = _foodSelections[cat].map(id => {
        const food = _foodCatalog[cat]?.find(f => f.id === id);
        return food ? food.name : id;
      }).join(', ');
      summary += `<div class="food-confirm-row"><strong>${cat}:</strong> ${items}</div>`;
    }

    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Your Foods for 12 Weeks</h2>
        <div class="baseline-desc" style="color:var(--amber);margin-bottom:1rem">This is it. These are the only foods you'll eat. Make sure you like them.</div>
        <div class="food-confirm-list">${summary}</div>
        <div style="display:flex;gap:8px;margin-top:1.5rem">
          <button class="btn btn-secondary" onclick="_foodStep=0;renderFoodSelection()">Change</button>
          <button class="btn btn-primary" style="flex:1" onclick="saveFoodSelections()">Lock It In</button>
        </div>
      </div>
    </div>`;
    return;
  }

  const foods = _foodCatalog[category] || [];
  const selected = _foodSelections[category] || [];
  const catLabel = category.charAt(0).toUpperCase() + category.slice(1);
  const count = selected.length;

  const foodItems = foods.map(f => {
    const isSelected = selected.includes(f.id);
    const portionInfo = `${f.default_portion} ${f.unit} = ${Math.round(f.cal * f.default_portion)} cal, ${Math.round(f.protein * f.default_portion)}P`;
    return `<div class="food-item${isSelected ? ' selected' : ''}" onclick="toggleFood('${category}','${f.id}')">
      <div class="food-item-name">${f.name}</div>
      <div class="food-item-macros">${portionInfo}</div>
    </div>`;
  }).join('');

  const canProceed = count >= FOOD_MIN;
  const statusText = count < FOOD_MIN ? `Pick at least ${FOOD_MIN - count} more` : count >= FOOD_MAX ? 'Maximum reached' : `${count} selected`;
  const statusClass = count < FOOD_MIN ? 'food-status-warning' : 'food-status-good';

  // Progress dots
  let dots = '';
  for (let i = 0; i < FOOD_CATEGORIES.length; i++) {
    dots += `<div class="bp-dot ${i < _foodStep ? 'done' : i === _foodStep ? 'active' : ''}"></div>`;
  }

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card">
      <div class="baseline-progress">${dots}</div>
      <h2>Pick Your ${catLabel}</h2>
      <div class="baseline-desc">This is all you'll eat for 12 weeks. Pick ${FOOD_MIN}-${FOOD_MAX} ${category} you actually like.</div>
      <div class="food-status ${statusClass}">${statusText}</div>
      <div class="food-grid">${foodItems}</div>
      <div style="display:flex;gap:8px;margin-top:1rem">
        ${_foodStep > 0 ? '<button class="btn btn-secondary" onclick="_foodStep--;renderFoodSelection()">Back</button>' : ''}
        <button class="btn btn-primary" style="flex:1" onclick="foodCategoryNext()" ${!canProceed ? 'disabled' : ''}>${_foodStep === FOOD_CATEGORIES.length - 1 ? 'Review Selections' : 'Next'}</button>
      </div>
    </div>
  </div>`;
}

function toggleFood(category, foodId) {
  const sel = _foodSelections[category];
  const idx = sel.indexOf(foodId);
  if (idx >= 0) {
    sel.splice(idx, 1);
  } else if (sel.length < FOOD_MAX) {
    sel.push(foodId);
  }
  // Update in-place — no re-render, no flicker
  document.querySelectorAll('.food-item').forEach(item => {
    const oc = item.getAttribute('onclick') || '';
    const m = oc.match(/toggleFood\('([^']+)','([^']+)'\)/);
    if (m && m[1] === category) {
      item.classList.toggle('selected', sel.includes(m[2]));
    }
  });
  const count = sel.length;
  const statusEl = document.querySelector('.food-status');
  if (statusEl) {
    statusEl.textContent = count < FOOD_MIN ? 'Pick at least ' + (FOOD_MIN - count) + ' more' : count >= FOOD_MAX ? 'Maximum reached' : count + ' selected';
    statusEl.className = 'food-status ' + (count < FOOD_MIN ? 'food-status-warning' : 'food-status-good');
  }
  const btn = document.querySelector('.baseline-card .btn-primary');
  if (btn) btn.disabled = count < FOOD_MIN;
}

function foodCategoryNext() {
  _foodStep++;
  renderFoodSelection();
}

async function saveFoodSelections() {
  await fetch('/api/food-selections', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ selected_foods: _foodSelections, completed: true }),
  });
  showFinalReveal();
}

// ─── WEIGHT PROJECTION ────────────────────────────────────────────────────
async function showWeightProjection() {
  const el = document.getElementById('baseline-overlay');
  const goalData = window._goalData;

  if (!goalData || !goalData.weight_projection) {
    finishOnboarding();
    return;
  }

  const proj = goalData.weight_projection;
  const startWeight = proj.length > 0 ? proj[0].projected : '?';
  const endWeight = proj.length > 0 ? proj[proj.length - 1].projected : '?';
  const w4 = proj.find(p => p.week === 4);
  const w8 = proj.find(p => p.week === 8);
  const w12 = proj.find(p => p.week === 12);

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center">
      <h2>Your Weight Projection</h2>
      <div class="baseline-desc" style="margin-bottom:1rem">If you follow this plan exactly:</div>
      <div class="projection-milestones">
        <div class="proj-milestone"><span class="proj-week">Week 4</span><span class="proj-weight">${w4 ? w4.projected : '?'} lbs</span></div>
        <div class="proj-milestone"><span class="proj-week">Week 8</span><span class="proj-weight">${w8 ? w8.projected : '?'} lbs</span></div>
        <div class="proj-milestone highlight"><span class="proj-week">Week 12</span><span class="proj-weight">${w12 ? w12.projected : '?'} lbs</span></div>
      </div>
      <canvas id="projection-chart" height="180" style="width:100%;margin:1rem auto;display:block"></canvas>
      <div style="font-size:13px;color:var(--muted);margin-top:0.5rem">
        ${goalData.goal_type === 'cut' ? 'Deficit: ' + goalData.calories + ' cal/day' : goalData.goal_type === 'bulk' ? 'Surplus: ' + goalData.calories + ' cal/day' : goalData.calories + ' cal/day'}
        ${goalData.fasting_protocol !== 'none' ? ' · Fasting: ' + goalData.fasting_protocol.replace('_',':') : ''}
        ${goalData.electrolytes ? ' · Electrolytes required' : ''}
      </div>
      <button class="btn btn-primary" style="width:100%;margin-top:1.5rem;font-size:16px;padding:14px" onclick="finishOnboarding()">Let's Get After It</button>
    </div>
  </div>`;

  // Draw projection chart
  setTimeout(() => drawProjectionChart(proj), 100);
}

function drawProjectionChart(projection) {
  const canvas = document.getElementById('projection-chart');
  if (!canvas || projection.length < 2) return;
  canvas.width = canvas.offsetWidth;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, pad = 20;
  ctx.clearRect(0, 0, W, H);

  const weights = projection.map(p => p.projected);
  const min = Math.min(...weights) - 2;
  const max = Math.max(...weights) + 2;
  const range = max - min || 1;
  const xStep = (W - pad * 2) / (projection.length - 1);
  const y = (v) => H - pad - ((v - min) / range) * (H - pad * 2);

  // Line
  ctx.strokeStyle = '#4ade80';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  projection.forEach((p, i) => {
    const px = pad + i * xStep;
    const py = y(p.projected);
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.stroke();

  // Dots + labels for key weeks
  ctx.fillStyle = '#4ade80';
  projection.forEach((p, i) => {
    const px = pad + i * xStep;
    const py = y(p.projected);
    if (p.week === 1 || p.week === 4 || p.week === 8 || p.week === 12) {
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#e8ede9';
      ctx.font = '11px Inter';
      ctx.textAlign = 'center';
      ctx.fillText(Math.round(p.projected), px, py - 10);
      ctx.fillStyle = '#4ade80';
    }
  });

  // Week labels
  ctx.fillStyle = '#9aaa9d';
  ctx.font = '10px DM Mono';
  ctx.textAlign = 'center';
  projection.forEach((p, i) => {
    if (p.week === 1 || p.week === 4 || p.week === 8 || p.week === 12) {
      ctx.fillText('W' + p.week, pad + i * xStep, H - 4);
    }
  });
}

// ─── FINAL REVEAL FLOW ────────────────────────────────────────────────────

async function showFinalReveal() {
    const el = document.getElementById('baseline-overlay');

    // Step 1: Loading with animated progress
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
            <h2 style="font-size:1.5rem;margin-bottom:16px">Building Your Plan</h2>
            <div class="plan-progress-bar"><div class="plan-progress-fill" id="plan-progress-fill" style="width:5%"></div></div>
            <div class="plan-progress-step" id="plan-progress-step">Analyzing your intake conversation...</div>
        </div>
    </div>`;

    const _planSteps = [
        { text: 'Running psychological assessment...', pct: 15 },
        { text: 'Examining current fitness level...', pct: 30 },
        { text: 'Computing metabolic rate...', pct: 45 },
        { text: 'Analyzing nutritional preferences...', pct: 55 },
        { text: 'Building workout programming...', pct: 65 },
        { text: 'Calculating calorie targets...', pct: 75 },
        { text: 'Projecting your 12-week transformation...', pct: 85 },
        { text: 'Finalizing your plan...', pct: 95 },
    ];
    let _planStepIdx = 0;
    const _planInterval = setInterval(() => {
        if (_planStepIdx < _planSteps.length) {
            const fill = document.getElementById('plan-progress-fill');
            const label = document.getElementById('plan-progress-step');
            if (fill) fill.style.width = _planSteps[_planStepIdx].pct + '%';
            if (label) label.textContent = _planSteps[_planStepIdx].text;
            _planStepIdx++;
        }
    }, 2000);

    // Step 2: ALWAYS recompute goal + generate profile
    let goalData = null;
    let profileText = null;

    try {
        {
            const goalRes = await fetch('/api/goal/compute', { method: 'POST' });
            goalData = await goalRes.json();
            window._goalData = goalData;
        }

        // Generate profile
        const profileRes = await fetch('/api/full-profile/generate', { method: 'POST' });
        const profileStart = await profileRes.json();
        if (profileStart.job_id) {
            for (let i = 0; i < 120; i++) {
                await new Promise(r => setTimeout(r, 500));
                const pollRes = await fetch('/api/full-profile/result/' + profileStart.job_id);
                const pollData = await pollRes.json();
                if (pollData.status !== 'pending') {
                    profileText = pollData.profile;
                    break;
                }
            }
        }
    } catch(e) {
        console.error('Final reveal error:', e);
    }

    // Stop progress animation
    clearInterval(_planInterval);
    const fill = document.getElementById('plan-progress-fill');
    if (fill) fill.style.width = '100%';

    // Brief pause at 100% before transitioning
    await new Promise(r => setTimeout(r, 500));

    // Step 3: Show Athlete Profile
    showRevealProfile(profileText, goalData);
}

function showRevealProfile(profileText, goalData) {
    const el = document.getElementById('baseline-overlay');
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card psych-intake-card" style="position:relative">
            <button style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1" onclick="document.getElementById('baseline-overlay').innerHTML='';renderAll()">&times;</button>
            <h2 style="margin-bottom:0.75rem">Your Athlete Profile</h2>
            <div class="psych-report">${profileText ? renderMarkdown(profileText) : '<p style="color:var(--muted)">Profile generation in progress...</p>'}</div>
            <button class="btn btn-primary" style="width:100%;margin-top:1.5rem;font-size:16px;padding:14px" onclick="showBaselineAssessment()">See Your Baseline →</button>
        </div>
    </div>`;
}

async function showBaselineAssessment() {
    const el = document.getElementById('baseline-overlay');
    el.innerHTML = `<div class="baseline-overlay"><div class="baseline-card" style="text-align:center;padding:2rem"><div class="chat-typing" style="justify-content:center"><span></span><span></span><span></span></div><div style="margin-top:8px;color:var(--muted);font-size:13px">Analyzing your data...</div></div></div>`;
    try {
        const res = await fetch('/api/baseline-assessment');
        const data = await res.json();
        renderBaselineAssessment(data);
    } catch(e) {
        console.error('Assessment error:', e);
        showRevealPlan();
    }
}

function renderBaselineAssessment(data) {
    const el = document.getElementById('baseline-overlay');
    const bc = data.body_comp || {};
    const strength = data.strength || [];
    const measurements = data.measurements || [];
    const summary = data.summary || {};

    let bodyCompHtml = '';
    if (bc.body_fat_pct) {
        bodyCompHtml = `<div class="assess-section">
            <div class="assess-section-label">Body Composition</div>
            <div class="assess-grid">
                <div class="assess-stat"><span class="assess-stat-val">${bc.body_fat_pct}%</span><span class="assess-stat-label">Body Fat</span><span class="assess-stat-sub">${bc.category}</span></div>
                <div class="assess-stat"><span class="assess-stat-val">${bc.body_weight}</span><span class="assess-stat-label">Weight (lbs)</span></div>
                <div class="assess-stat"><span class="assess-stat-val">${bc.lean_mass || '?'}</span><span class="assess-stat-label">Lean Mass (lbs)</span></div>
                <div class="assess-stat"><span class="assess-stat-val">${bc.fat_mass || '?'}</span><span class="assess-stat-label">Fat Mass (lbs)</span></div>
            </div>
        </div>`;
    } else {
        bodyCompHtml = `<div class="assess-section">
            <div class="assess-section-label">Body Composition</div>
            <div class="assess-grid">
                <div class="assess-stat"><span class="assess-stat-val">${bc.body_weight || '?'}</span><span class="assess-stat-label">Weight (lbs)</span></div>
                <div class="assess-stat"><span class="assess-stat-val">?</span><span class="assess-stat-label">Body Fat</span><span class="assess-stat-sub">Need waist + neck measurements</span></div>
            </div>
        </div>`;
    }

    let strengthHtml = '';
    if (strength.length > 0) {
        const rows = strength.map(s => {
            const barWidth = Math.max(5, Math.min(100, s.percentile));
            const shortName = s.exercise.replace('Barbell ', '').replace('Conventional ', '').replace('DB ', '');
            return `<div class="assess-lift-row">
                <div class="assess-lift-name">${shortName}</div>
                <div class="assess-lift-data">
                    <span class="assess-lift-1rm">${s.estimated_1rm} lb 1RM</span>
                    <span class="assess-lift-ratio">${s.relative_strength}x BW</span>
                </div>
                <div class="assess-lift-pct-bar"><div class="assess-lift-pct-fill" style="width:${barWidth}%;background:#4ade80"></div></div>
                <div class="assess-lift-pct-label">${s.percentile}th percentile · ${s.rating}</div>
            </div>`;
        }).join('');
        strengthHtml = `<div class="assess-section"><div class="assess-section-label">Strength (Est. 1RM vs Population)</div>${rows}</div>`;
    }

    let measureHtml = '';
    if (measurements.length > 0) {
        const mRows = measurements.map(m => {
            const waistLike = ['Waist', 'Hips'];
            const goodDir = waistLike.includes(m.label) ? (m.diff < 0 ? 'var(--accent)' : 'var(--amber)') : (m.diff > 0 ? 'var(--accent)' : 'var(--amber)');
            return `<div class="assess-measure-row">
                <span class="assess-measure-label">${m.label}</span>
                <span class="assess-measure-val">${m.value}"</span>
                <span class="assess-measure-avg">avg: ${m.avg}"</span>
                <span class="assess-measure-diff" style="color:${goodDir}">${m.status}</span>
            </div>`;
        }).join('');
        measureHtml = `<div class="assess-section"><div class="assess-section-label">Measurements vs Population Average</div>${mRows}</div>`;
    }

    let summaryHtml = '';
    if (summary.strongest) {
        const strongShort = summary.strongest.replace('Barbell ', '').replace('Conventional ', '');
        const weakShort = summary.weakest ? summary.weakest.replace('Barbell ', '').replace('Conventional ', '') : '?';
        summaryHtml = `<div class="assess-section assess-summary">
            <div class="assess-section-label">Analysis</div>
            <div class="assess-summary-text">
                Strongest: <strong>${strongShort}</strong> (${summary.strongest_percentile}th percentile).
                Needs work: <strong>${weakShort}</strong> (${summary.weakest_percentile}th percentile).
                ${bc.body_fat_pct ? 'Body fat: ' + bc.body_fat_pct + '% (' + bc.category + ').' : ''}
            </div>
        </div>`;
    }

    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:left;max-width:600px;position:relative">
            <button style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1" onclick="document.getElementById('baseline-overlay').innerHTML='';renderAll()">&times;</button>
            <h2 style="text-align:center;margin-bottom:0.5rem">Your Baseline Assessment</h2>
            <div class="baseline-desc" style="text-align:center;margin-bottom:1.5rem">Here's where you stand. Every Sunday we remeasure.</div>
            ${bodyCompHtml}
            ${strengthHtml}
            ${measureHtml}
            ${summaryHtml}
            <button class="btn btn-primary" style="width:100%;margin-top:1.5rem;font-size:16px;padding:14px" onclick="showRevealPlan()">See Your Training Plan →</button>
        </div>
    </div>`;
}

function showRevealPlan() {
    const el = document.getElementById('baseline-overlay');
    const g = window._goalData || {};

    const goalLabel = (g.goal_type || 'cut').toUpperCase();
    const goalColor = g.goal_type === 'bulk' ? 'var(--blue)' : g.goal_type === 'recomp' ? 'var(--amber)' : 'var(--accent)';

    // Projected outcomes
    const proj = g.weight_projection || [];
    const w4 = proj.find(p => p.week === 4);
    const w8 = proj.find(p => p.week === 8);
    const w12 = proj.find(p => p.week === 12);
    const startWt = g.starting_weight || (proj.length > 0 ? Math.round(proj[0].projected) : '?');
    const targetWt = g.target_weight ? Math.round(g.target_weight) : '?';
    const tdee = g.tdee || 2500;
    const targetBf = g.target_bf_pct ? Math.round(g.target_bf_pct * 100) : '?';
    // Compute what it TAKES to hit the goal weight in 12 weeks
    const totalLoss = (typeof startWt === 'number' && typeof targetWt === 'number') ? startWt - targetWt : 0;
    const weeklyLossNeeded = totalLoss > 0 ? Math.round(totalLoss / 12 * 10) / 10 : 0;
    const dailyDeficitNeeded = Math.round(weeklyLossNeeded * 3500 / 7);
    const dailyCalories = Math.round(tdee - dailyDeficitNeeded);

    // Strength projections from baseline (same as assessment but projected forward)
    const weights = _weightsCache || {};
    let strengthProjections = '';
    const keyLifts = [
        { name: 'Barbell Bench Press', short: 'Bench' },
        { name: 'Barbell Back Squat', short: 'Squat' },
        { name: 'Conventional Deadlift', short: 'Deadlift' },
    ];
    for (const lift of keyLifts) {
        const data = weights[lift.name];
        if (!data || !data.history || data.history.length === 0) continue;
        const last = data.history[data.history.length - 1];
        const setsLabel = String(last.reps || '');
        let current1RM = 0;
        const m = setsLabel.match(/(\d+)\s*(?:lb)?\s*x\s*(\d+)/i);
        if (m) current1RM = Math.round(parseInt(m[1]) * (1 + parseInt(m[2]) / 30));
        else current1RM = Math.round(data.current / 0.75);
        if (current1RM <= 0) continue;
        const wk12_1rm = Math.round(current1RM * 1.35);
        strengthProjections += `<div class="plan-outcome-row">
            <span>${lift.short} 1RM</span>
            <span>${current1RM} → <strong>${wk12_1rm} lbs</strong></span>
        </div>`;
    }

    // Day type calorie table
    const dayTypes = g.calorie_by_day_type || {};
    let calRows = '';
    const dayLabels = {heavy_lift: 'Heavy Lift', long_run: 'Long Run', moderate: 'Moderate', rest: 'Rest', deload: 'Deload'};
    for (const [dt, vals] of Object.entries(dayTypes)) {
        const v = typeof vals === 'object' ? vals : {calories: vals};
        calRows += `<div class="plan-cal-row"><span>${dayLabels[dt] || dt}</span><span>${v.calories || g.calories || '?'} cal</span></div>`;
    }

    const fastingLabel = (g.fasting_protocol || 'none').replace(/_/g, ':');
    const electrolyteNote = g.electrolytes ? '<div class="plan-note plan-note-warn">Electrolyte supplementation required (sodium, potassium, magnesium)</div>' : '';

    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:left;position:relative">
            <button style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1" onclick="document.getElementById('baseline-overlay').innerHTML='';renderAll()">&times;</button>
            <div style="text-align:center;margin-bottom:1rem">
                <span class="plan-goal-badge" style="background:${goalColor}">${goalLabel}</span>
            </div>
            <h2 style="text-align:center;margin-bottom:1.5rem">Your Training Plan</h2>

            <div class="plan-section">
                <div class="plan-section-label">The Goal (12 Weeks)</div>
                <div class="plan-outcomes">
                    <div class="plan-outcome-row">
                        <span>Body Weight</span>
                        <span>${startWt} → <strong>${targetWt} lbs</strong> (−${totalLoss} lbs)</span>
                    </div>
                    <div class="plan-outcome-row">
                        <span>Target Body Fat</span>
                        <span><strong>${targetBf}%</strong></span>
                    </div>
                    <div class="plan-outcome-row">
                        <span>Required Loss Rate</span>
                        <span><strong>${weeklyLossNeeded} lbs/week</strong></span>
                    </div>
                    ${strengthProjections}
                </div>
            </div>

            <div class="plan-section">
                <div class="plan-section-label">What It Takes</div>
                <div class="plan-outcomes">
                    <div class="plan-outcome-row">
                        <span>Your TDEE (burn)</span>
                        <span><strong>${tdee}</strong> cal/day</span>
                    </div>
                    <div class="plan-outcome-row" style="color:var(--accent)">
                        <span>Required Deficit</span>
                        <span><strong>${dailyDeficitNeeded}</strong> cal/day</span>
                    </div>
                    <div class="plan-outcome-row" style="color:var(--accent);font-weight:700">
                        <span>Daily Intake to Hit Goal</span>
                        <span><strong>${dailyCalories}</strong> cal/day</span>
                    </div>
                </div>
                ${dailyCalories < 1200 ? '<div class="plan-note plan-note-warn">This is an aggressive deficit. Extended fasting days, strict meal discipline, and electrolyte supplementation are required.</div>' : ''}
                ${dailyCalories < 800 ? '<div class="plan-note plan-note-warn">This requires OMAD or alternate-day fasting. Not for beginners. You committed to this.</div>' : ''}
            </div>

            <div class="plan-section">
                <div class="plan-section-label">Daily Macros</div>
                <div class="plan-macros">
                    <div class="plan-macro"><span class="plan-macro-val">${g.calories || '?'}</span><span class="plan-macro-label">Calories</span></div>
                    <div class="plan-macro"><span class="plan-macro-val">${g.protein || '?'}g</span><span class="plan-macro-label">Protein</span></div>
                    <div class="plan-macro"><span class="plan-macro-val">${g.carbs || '?'}g</span><span class="plan-macro-label">Carbs</span></div>
                    <div class="plan-macro"><span class="plan-macro-val">${g.fat || '?'}g</span><span class="plan-macro-label">Fat</span></div>
                </div>
            </div>

            <div class="plan-section">
                <div class="plan-section-label">Calories by Day Type</div>
                <div class="plan-cal-table">${calRows}</div>
            </div>

            <div class="plan-section">
                <div class="plan-section-label">Fasting Protocol</div>
                <div class="plan-value">${fastingLabel === 'none' ? 'No fasting' : fastingLabel + ' intermittent fasting'}</div>
                ${electrolyteNote}
            </div>

            <div class="plan-section">
                <div class="plan-section-label">Training Structure</div>
                <div class="plan-value">6 days lifting + daily mile minimum</div>
                <div class="plan-value" style="font-size:13px;color:var(--muted)">No days off from running. The streak mile is sacred.</div>
            </div>

            <div class="plan-section">
                <div class="plan-section-label">Non-Negotiables</div>
                <div class="plan-nonneg">No alcohol. 5:30am daily. Follow the plan exactly.</div>
            </div>

            <h3 style="text-align:center;margin:1.5rem 0 1rem;color:var(--text)">Does this plan work for you?</h3>
            <div style="display:flex;flex-direction:column;gap:10px">
                <button class="btn btn-primary" style="width:100%;font-size:15px;padding:14px;font-family:'DM Mono',monospace" onclick="acceptPlan()">Let's Do This</button>
                <button class="btn btn-secondary" style="width:100%;font-size:15px;padding:14px;font-family:'DM Mono',monospace;color:var(--text)" onclick="requestMoreAggressive()">I Want Bigger Results</button>
                <button class="btn btn-secondary" style="width:100%;font-size:15px;padding:14px;font-family:'DM Mono',monospace;opacity:0.4" onclick="handleDialBack()">This Is Too Much</button>
            </div>
        </div>
    </div>`;
}

function acceptPlan() {
    showStartDatePicker();
}

function showStartDatePicker() {
    const el = document.getElementById('baseline-overlay');
    const today = new Date();
    const dayOfWeek = today.getDay();

    const daysUntilThisMon = dayOfWeek === 0 ? 1 : dayOfWeek === 1 ? 0 : 8 - dayOfWeek;
    const thisMon = new Date(today); thisMon.setDate(today.getDate() + daysUntilThisMon);
    const nextMon = new Date(thisMon); nextMon.setDate(thisMon.getDate() + 7);

    const fmt = (d) => d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
    const iso = (d) => d.toISOString().slice(0, 10);

    const thisMonLabel = daysUntilThisMon === 0 ? 'Today (Monday)' : 'This Monday \u2014 ' + fmt(thisMon);

    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center">
            <h2>When Do We Start?</h2>
            <div class="baseline-desc" style="margin-bottom:1.5rem">Pick your Day 1. Programs start on Monday.</div>
            <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:1.5rem">
                <button class="pa-choice" style="padding:16px" onclick="pickStartDate('${iso(thisMon)}')">${thisMonLabel}</button>
                <button class="pa-choice" style="padding:16px" onclick="pickStartDate('${iso(nextMon)}')">Next Monday \u2014 ${fmt(nextMon)}</button>
            </div>
            <div style="border-top:1px solid var(--border);padding-top:1rem">
                <div class="plan-section-label">Wake-up Time</div>
                <div style="font-size:14px;color:var(--muted);margin-bottom:8px">Default is 5:30am. You can go earlier. Never later.</div>
                <select id="wake-time-select" style="background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:10px 16px;border-radius:8px;font-size:16px;text-align:center">
                    <option value="4:00">4:00 AM</option>
                    <option value="4:30">4:30 AM</option>
                    <option value="5:00">5:00 AM</option>
                    <option value="5:30" selected>5:30 AM</option>
                </select>
            </div>
            <div style="font-size:12px;color:var(--dim);margin-top:1rem;font-family:'DM Mono',monospace">No later than 5:30. Early is earned.</div>
        </div>
    </div>`;
}

async function pickStartDate(dateStr) {
    const wakeTime = document.getElementById('wake-time-select')?.value || '5:30';
    await apiPost('/api/goal', { plan_accepted: true });
    await apiPost('/api/state', { baseline_done: true, start_date: dateStr });
    _stateCache.baseline_done = true;
    _stateCache.start_date = dateStr;
    document.getElementById('baseline-overlay').innerHTML = '';

    // Check if start date is in the future → show lockout
    const start = new Date(dateStr + 'T00:00:00');
    if (start > new Date()) {
        showPreStartLockout(dateStr);
        return;
    }
    renderAll();
}

function requestMoreAggressive() {
    const el = document.getElementById('baseline-overlay');
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center">
            <h2>What Results Do You Want?</h2>
            <div class="baseline-desc" style="margin-bottom:1rem">Tell me your goal. I'll build the plan to get you there.</div>
            <div class="pa-measure-row">
                <input type="text" id="aggressive-goal-input" placeholder="e.g. I want to be 175 lbs at 8% body fat" style="text-align:center">
            </div>
            <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="submitMoreAggressive()">Build My New Plan</button>
        </div>
    </div>`;
    setTimeout(() => { const inp = document.getElementById('aggressive-goal-input'); if (inp) inp.focus(); }, 100);
}

async function submitMoreAggressive() {
    const input = document.getElementById('aggressive-goal-input');
    const goal = (input?.value || '').trim();
    if (!goal) return;

    const el = document.getElementById('baseline-overlay');
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
            <h2>Recalculating</h2>
            <div class="chat-typing" style="justify-content:center;margin:1.5rem 0"><span></span><span></span><span></span></div>
        </div>
    </div>`;

    try {
        // Parse target weight from the input if possible
        const weightMatch = goal.match(/(\d{2,3})\s*(lbs?|pounds?)/i);
        const bfMatch = goal.match(/(\d{1,2})\s*%/);

        const payload = {};
        if (weightMatch) payload.target_weight = parseInt(weightMatch[1]);
        if (bfMatch) payload.target_bf = parseInt(bfMatch[1]) / 100;
        payload.aggressive_request = goal;

        const res = await fetch('/api/goal/compute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const newGoal = await res.json();
        window._goalData = newGoal;

        showBaselineAssessment();
    } catch(e) {
        showRevealPlan();
    }
}

function handleDialBack() {
    const el = document.getElementById('baseline-overlay');
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
            <h2 style="color:var(--muted)">12 Weeks Isn't For You</h2>
            <p style="color:var(--muted);margin:1rem 0 1.5rem;font-size:15px;line-height:1.6">That's okay. Not everyone is ready.<br>Come back in a week if you change your mind.</p>
            <div style="font-size:13px;color:var(--dim);font-family:'DM Mono',monospace">Locked until ${new Date(Date.now() + 7*24*60*60*1000).toLocaleDateString()}</div>
        </div>
    </div>`;

    // Lock out for 1 week
    fetch('/api/psych-intake/message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ message: '[PLAN_REJECTED]' }),
    });

    // Set lockout via direct API
    apiPost('/api/plan/lockout', {});
}

function finishOnboarding() {
  document.getElementById('baseline-overlay').innerHTML = '';
  renderAll();
}

// ─── SIMPLE MARKDOWN RENDERER ──────────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return '';
  const lines = text.split('\n');
  let html = '';
  let inUl = false;
  let paragraph = [];

  function flushParagraph() {
    if (paragraph.length > 0) {
      const pText = paragraph.join(' ').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html += `<p>${pText}</p>`;
      paragraph = [];
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith('## ')) {
      flushParagraph();
      if (inUl) { html += '</ul>'; inUl = false; }
      const heading = trimmed.slice(3).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html += `<h3>${heading}</h3>`;
    } else if (trimmed.startsWith('# ')) {
      flushParagraph();
      if (inUl) { html += '</ul>'; inUl = false; }
      const heading = trimmed.slice(2).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html += `<h2>${heading}</h2>`;
    } else if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph();
      if (!inUl) { html += '<ul>'; inUl = true; }
      const item = trimmed.replace(/^[-*]\s+/, '').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html += `<li>${item}</li>`;
    } else if (trimmed === '') {
      flushParagraph();
      if (inUl) { html += '</ul>'; inUl = false; }
    } else {
      paragraph.push(trimmed);
    }
  }
  flushParagraph();
  if (inUl) html += '</ul>';
  return html;
}

// ─── FETCH WITH TIMEOUT + RETRY ───────────────────────────────────────────
async function fetchWithRetry(url, options, timeoutMs, retries) {
  timeoutMs = timeoutMs || 30000;
  retries = retries || 2;
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) throw new Error('Server returned ' + res.status);
      return await res.json();
    } catch (e) {
      if (attempt < retries - 1) {
        console.warn('Fetch attempt ' + (attempt+1) + ' failed, retrying...', e.message);
        await new Promise(r => setTimeout(r, 2000));
      } else {
        throw e;
      }
    }
  }
}

// ─── FETCH INTAKE WITH ASYNC POLL ─────────────────────────────────────────
async function fetchIntakeWithPoll(url, options) {
    // Step 1: Submit the request (returns immediately with job_id)
    const submitRes = await fetch(url, options);
    const submitData = await submitRes.json();

    // If the response already has the result (e.g. locked state), return it
    if (submitData.response !== undefined || submitData.error) {
        return submitData;
    }

    // Step 2: Poll for result
    const jobId = submitData.job_id;
    if (!jobId) throw new Error('No job_id returned');

    const maxAttempts = 120; // 120 * 500ms = 1 minute max
    for (let i = 0; i < maxAttempts; i++) {
        await new Promise(r => setTimeout(r, 500));
        try {
            const pollRes = await fetch('/api/psych-intake/result/' + jobId);
            const pollData = await pollRes.json();
            if (pollData.status === 'pending') continue;
            return pollData; // done or error
        } catch (e) {
            // Network hiccup, keep polling
            continue;
        }
    }
    throw new Error('Timed out waiting for response');
}

// ─── PSYCHOLOGICAL INTAKE CHAT ─────────────────────────────────────────────
let _psychMessages = [];
let _psychCompleted = false;

function showPsychIntake() {
  _psychMessages = [];
  _psychCompleted = false;
  // Skip intro screen -- go straight to conversation
  startPsychConversation();
}

function skipPsychIntake() {
  showBaseline();
}

async function startPsychConversation() {
  const el = document.getElementById('baseline-overlay');
  el.innerHTML = `<div class="psych-intake-fullscreen">
    <div class="psych-header">
        <div class="psych-progress" id="psych-progress">Getting to know you</div>
        <button class="psych-continue-later" onclick="dismissPsychIntake()" style="position:static">Continue Later</button>
    </div>
    <div class="psych-chat-messages" id="psych-chat-messages"></div>
    <div class="psych-input-bar" id="psych-input-bar">
        <input type="text" id="psych-input" placeholder="Type your response..." enterkeyhint="send" onkeydown="if(event.key==='Enter')sendPsychMessage()">
        <button onclick="sendPsychMessage()">Send</button>
    </div>
  </div>`;

  updatePsychProgress();

  // Check if there's an existing conversation
  try {
    const statusRes = await fetch('/api/psych-intake/status');
    const status = await statusRes.json();

    // Handle locked state
    if (status.locked) {
      showPsychLockedState(status.locked_until);
      return;
    }

    if (status.started && status.message_count > 0) {
      const convRes = await fetch('/api/psych-intake/conversation');
      const convData = await convRes.json();
      if (convData.conversation && convData.conversation.length > 0) {
        _psychMessages = convData.conversation;
        _psychCompleted = convData.completed;
        // Show welcome back message — different if returning from lockout
        const welcomeMsg = status.lockout_expired
          ? "You came back. Good. Let's pick up where we left off."
          : "Welcome back. Picking up where we left off...";
        _psychMessages.unshift({ role: 'coach', content: welcomeMsg });
        renderPsychMessages();
        updatePsychProgress();
        if (_psychCompleted) {
          showConstraints();
          return;
        }
        return;
      }
    }
  } catch (e) {
    console.error('Error checking psych intake status:', e);
  }

  // Start fresh - send empty message to get opening question
  showPsychTyping();
  try {
    const data = await fetchIntakeWithPoll('/api/psych-intake/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '' })
    });
    hidePsychTyping();
    if (data.response) {
      _psychMessages.push({ role: 'coach', content: data.response });
      renderPsychMessages();
      updatePsychProgress();
    }
    if (data.completed) {
      _psychCompleted = true;
      showConstraints();
    }
  } catch (e) {
    hidePsychTyping();
    console.error('Error starting psych conversation:', e);
  }
}

function dismissPsychIntake() {
  document.getElementById('baseline-overlay').innerHTML = '';
}

function updatePsychProgress() {
  const el = document.getElementById('psych-progress');
  if (!el) return;
  const userMsgs = _psychMessages.filter(m => m.role === 'user').length;
  el.textContent = 'Getting to know you (' + userMsgs + ' of ~12)';
}

function showPsychLockedState(lockedUntil) {
  const el = document.getElementById('baseline-overlay');
  const lockDate = lockedUntil ? new Date(lockedUntil) : null;
  const daysLeft = lockDate ? Math.max(0, Math.ceil((lockDate - new Date()) / (1000 * 60 * 60 * 24))) : '?';
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card psych-intake-card">
      <div class="psych-locked-overlay">
        <h3>Intake Paused</h3>
        <p style="color:var(--muted);margin:1rem 0">You're locked out for <strong>${daysLeft}</strong> more day${daysLeft !== 1 ? 's' : ''}.</p>
        <p style="color:var(--muted);margin-bottom:1.5rem">Come back when you've been alcohol-free for 7 days.</p>
        <button class="btn btn-secondary" style="width:100%" onclick="dismissPsychIntake()">Close</button>
      </div>
    </div>
  </div>`;
}

async function sendPsychMessage() {
  const input = document.getElementById('psych-input');
  if (!input) return;
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  _psychMessages.push({ role: 'user', content: msg });
  renderPsychMessages();
  updatePsychProgress();

  showPsychTyping();
  try {
    const data = await fetchIntakeWithPoll('/api/psych-intake/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg })
    });
    hidePsychTyping();
    if (data.locked) {
      showPsychLockedState(data.locked_until);
      return;
    }
    if (data.response) {
      _psychMessages.push({ role: 'coach', content: data.response });
      renderPsychMessages();
      updatePsychProgress();
    }
    if (data.report_error) {
      _psychMessages.push({ role: 'coach', content: 'Intake complete, but report generation failed. You can continue — it will retry automatically.' });
      renderPsychMessages();
    }
    if (data.completed) {
      _psychCompleted = true;
      // Brief coach transition before constraints screen
      const el = document.getElementById('baseline-overlay');
      if (el) {
        el.innerHTML = `<div class="baseline-overlay">
          <div class="baseline-card" style="text-align:center;padding:2rem">
            <div style="font-size:15px;color:var(--text);line-height:1.6">
              Good. Now I need to know what we're working with.<br>
              <span style="color:var(--muted);font-size:13px">A few quick questions about your setup.</span>
            </div>
          </div>
        </div>`;
        await new Promise(r => setTimeout(r, 1500));
      }
      showConstraints();
    }
  } catch (e) {
    hidePsychTyping();
    console.error('Error sending psych message:', e);
    // Show tappable error instead of silent fail
    _psychMessages.push({ role: 'coach', content: 'Connection timed out. Tap here to retry.' });
    renderPsychMessages();
    const container = document.getElementById('psych-chat-messages');
    if (container && container.lastElementChild) {
      const errBubble = container.lastElementChild;
      errBubble.style.cssText = 'cursor:pointer;color:var(--amber);border-color:var(--run-tempo-border)';
      errBubble.onclick = () => {
        _psychMessages.pop();
        const lastUser = [..._psychMessages].reverse().find(m => m.role === 'user');
        if (lastUser) {
          _psychMessages.pop();
          const input = document.getElementById('psych-input');
          if (input) input.value = lastUser.content;
          sendPsychMessage();
        }
      };
    }
  }
}

function renderPsychMessages() {
  const container = document.getElementById('psych-chat-messages');
  if (!container) return;
  container.innerHTML = _psychMessages.map(m => {
    const cls = m.role === 'user' ? 'user' : 'coach';
    return `<div class="psych-chat-bubble ${cls}">${escapeHtml(m.content)}</div>`;
  }).join('');
  container.scrollTop = container.scrollHeight;
  // Auto-focus the input so user can just type
  const input = document.getElementById('psych-input');
  if (input) setTimeout(() => input.focus(), 100);
}

function showPsychTyping() {
  const container = document.getElementById('psych-chat-messages');
  if (!container) return;
  const existing = container.querySelector('.psych-typing');
  if (existing) return;
  const typing = document.createElement('div');
  typing.className = 'psych-typing';
  typing.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
  container.appendChild(typing);
  container.scrollTop = container.scrollHeight;
  // Disable input while waiting
  const input = document.getElementById('psych-input');
  const btn = document.querySelector('.psych-input-bar button');
  if (input) input.disabled = true;
  if (btn) btn.disabled = true;
}

function hidePsychTyping() {
  const container = document.getElementById('psych-chat-messages');
  if (!container) return;
  const typing = container.querySelector('.psych-typing');
  if (typing) typing.remove();
  // Re-enable input
  const input = document.getElementById('psych-input');
  const btn = document.querySelector('.psych-input-bar button');
  if (input) input.disabled = false;
  if (btn) btn.disabled = false;
}

async function showPsychReport() {
  // Hide input bar
  const inputBar = document.getElementById('psych-input-bar');
  if (inputBar) inputBar.style.display = 'none';

  const el = document.getElementById('baseline-overlay');

  // Show loading screen while report generates
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
      <h2 style="font-size:1.5rem;margin-bottom:16px">Building Your Athlete Profile</h2>
      <div class="chat-typing" style="justify-content:center;margin:1.5rem 0"><span></span><span></span><span></span></div>
      <div style="font-size:14px;color:var(--muted);font-family:'DM Mono',monospace">Analyzing your intake conversation...</div>
    </div>
  </div>`;

  try {
    const res = await fetch('/api/psych-intake/report');
    const data = await res.json();
    if (data.error || !data.report) {
      // Report generation failed — show error with retry
      el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card psych-intake-card" style="text-align:center">
          <h2 style="margin-bottom:0.75rem;color:var(--amber)">Report Generation Failed</h2>
          <p style="color:var(--muted);margin-bottom:1.5rem">Your intake conversation was saved. The report couldn't be generated right now.</p>
          <div style="display:flex;flex-direction:column;gap:10px">
            <button class="btn btn-primary" style="width:100%;font-size:16px;padding:14px" onclick="showPsychReport()">Retry Report</button>
            <button class="btn btn-secondary" style="width:100%;font-size:15px;padding:12px" onclick="showConstraints()">Skip Report — Continue to Constraints</button>
          </div>
        </div>
      </div>`;
      return;
    }
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card psych-intake-card">
        <h2 style="margin-bottom:0.75rem">Your Psych Profile</h2>
        <div class="psych-report">${renderMarkdown(data.report)}</div>
        <div style="display:flex;flex-direction:column;gap:10px;margin-top:1.25rem">
          <button class="btn btn-primary" style="width:100%;font-size:16px;padding:14px" onclick="showConstraints()">Next: Constraints</button>
        </div>
      </div>
    </div>`;
  } catch (e) {
    console.error('Error fetching psych report:', e);
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card psych-intake-card" style="text-align:center">
        <h2 style="margin-bottom:0.75rem;color:var(--amber)">Report Generation Failed</h2>
        <p style="color:var(--muted);margin-bottom:1.5rem">Your intake conversation was saved. The report couldn't be generated right now.</p>
        <div style="display:flex;flex-direction:column;gap:10px">
          <button class="btn btn-primary" style="width:100%;font-size:16px;padding:14px" onclick="showPsychReport()">Retry Report</button>
          <button class="btn btn-secondary" style="width:100%;font-size:15px;padding:12px" onclick="showConstraints()">Skip Report — Continue to Constraints</button>
        </div>
      </div>
    </div>`;
  }
}

async function redoPsychIntake() {
  closeSettingsMenu();
  try {
    await fetch('/api/psych-intake/reset', { method: 'POST' });
  } catch (e) {
    console.error('Error resetting psych intake:', e);
  }
  showPsychIntake();
}

function showSettingsMenu() {
  const el = document.getElementById('settings-dropdown');
  if (el) {
    el.classList.toggle('visible');
    return;
  }
  // Build settings dropdown
  const header = document.querySelector('.header-row');
  const dd = document.createElement('div');
  dd.id = 'settings-dropdown';
  dd.className = 'settings-dropdown visible';
  const travelOn = _stateCache && _stateCache.traveling;
  dd.innerHTML = `
    <button onclick="if(confirm('This will reset your baseline weights. Continue?'))redoBaseline()">Redo Baseline</button>
    <button onclick="if(confirm('This will reset your psych intake. Continue?'))redoPsychIntake()">Redo Psych Intake</button>
    <button onclick="showStartDateSetting()">Set Start Date</button>
    <button onclick="toggleTravelMode()" id="travel-toggle-btn">${travelOn ? '✈️ Traveling: ON' : '🏠 Traveling: OFF'}</button>
    <button onclick="regenerateProfile()">Regenerate Profile</button>
    <button onclick="restartFromReveal()">Restart from Plan Review</button>
    <button onclick="showGroceryList()">Grocery List</button>
    <button onclick="exportData()">Export Data</button>
    <button onclick="importData()">Import Data</button>
    <button onclick="window.location='/logout'">Logout</button>
    <button onclick="closeSettingsMenu()">Cancel</button>
  `;
  header.parentNode.appendChild(dd);
}

async function showGroceryList() {
  closeSettingsMenu();
  const overlay = document.getElementById('morning-checkin-overlay');
  overlay.innerHTML = `<div class="morning-checkin-overlay"><div class="morning-checkin-card" style="max-width:500px"><h2>Loading...</h2></div></div>`;

  try {
    const res = await fetch('/api/shopping-list');
    const data = await res.json();

    let html = '';
    for (const cat of (data.categories || [])) {
      html += `<div class="shop-category"><div class="shop-cat-label">${cat.category}</div>`;
      for (const item of cat.items) {
        const safeId = item.item.replace(/[^a-zA-Z0-9]/g, '_');
        html += `<div class="shop-item" onclick="this.classList.toggle('shop-done')">
          <button class="shop-check" aria-label="Check off ${item.item}"></button>
          <span class="shop-item-name">${item.item}</span>
          <span class="shop-item-qty">${item.total}</span>
        </div>`;
      }
      html += `</div>`;
    }

    overlay.innerHTML = `<div class="morning-checkin-overlay">
      <div class="morning-checkin-card" style="max-width:500px">
        <button style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1" onclick="document.getElementById('morning-checkin-overlay').innerHTML=''">&times;</button>
        <h2>Grocery List — Week ${data.week}</h2>
        <div class="shop-list">${html || '<div style="color:var(--muted)">No meal plan data for this week.</div>'}</div>
      </div>
    </div>`;
  } catch(e) {
    overlay.innerHTML = '';
    showToast('Failed to load grocery list', 'error');
  }
}

// ─── INVITE SYSTEM ────────────────────────────────────────────────────────
async function toggleInviteDropdown() {
    const el = document.getElementById('invite-dropdown');
    if (el.classList.contains('visible')) {
        el.classList.remove('visible');
        el.innerHTML = '';
        return;
    }

    // Fetch invite status
    try {
        const res = await fetch('/api/invite-status');
        const status = await res.json();
        const remaining = status.is_admin ? '∞' : status.remaining;

        el.innerHTML = `<div class="invite-card">
            <div class="invite-header">
                <span>Invite a Friend</span>
                <span class="invite-remaining">${remaining} remaining</span>
            </div>
            <input type="email" id="invite-email" placeholder="friend@email.com" class="invite-input">
            <button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="sendInvite()">Send Invite</button>
            <div id="invite-result" class="invite-result"></div>
        </div>`;
        el.classList.add('visible');
    } catch(e) {
        console.error('Invite status error:', e);
    }
}

async function sendInvite() {
    const emailInput = document.getElementById('invite-email');
    const email = (emailInput?.value || '').trim();
    const resultEl = document.getElementById('invite-result');

    try {
        const res = await fetch('/api/invite', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ email: email || null }),
        });
        const data = await res.json();

        if (data.error) {
            resultEl.innerHTML = `<div style="color:var(--red)">${data.error}</div>`;
            return;
        }

        let html = '';
        if (data.email_sent) {
            html = '<div style="color:var(--accent)">Invite sent!</div>';
        }
        html += `<div class="invite-link-box">
            <input type="text" value="${data.invite_url}" readonly onclick="this.select();document.execCommand('copy')" class="invite-link-input">
            <div style="font-size:11px;color:var(--muted);margin-top:4px">Click to copy link</div>
        </div>`;

        if (!data.is_admin && data.remaining >= 0) {
            const badge = document.querySelector('.invite-remaining');
            if (badge) badge.textContent = data.remaining + ' remaining';
        }

        resultEl.innerHTML = html;
    } catch(e) {
        resultEl.innerHTML = '<div style="color:var(--red)">Failed to create invite</div>';
    }
}

async function restartFromReveal() {
  closeSettingsMenu();
  // Reset plan_accepted so onboarding gate reopens
  await fetch('/api/goal', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ plan_accepted: false }),
  });
  // Go straight to the final reveal (recompute goal + profile)
  showFinalReveal();
}

async function regenerateProfile() {
  closeSettingsMenu();
  const el = document.getElementById('baseline-overlay');
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
      <h2 style="font-size:1.5rem;margin-bottom:16px">Rebuilding Your Profile</h2>
      <div class="plan-progress-bar"><div class="plan-progress-fill" style="width:30%"></div></div>
      <div class="plan-progress-step">Regenerating athlete profile...</div>
    </div>
  </div>`;

  try {
    const res = await fetch('/api/full-profile/generate', { method: 'POST' });
    const startData = await res.json();
    let profile = null;

    if (startData.job_id) {
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 500));
        const pollRes = await fetch('/api/full-profile/result/' + startData.job_id);
        const pollData = await pollRes.json();
        if (pollData.status !== 'pending') {
          profile = pollData.profile;
          break;
        }
      }
    }

    if (profile) {
      el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card psych-intake-card">
          <h2 style="margin-bottom:0.75rem">Your Athlete Profile</h2>
          <div class="psych-report">${renderMarkdown(profile)}</div>
          <button class="btn btn-primary" style="width:100%;margin-top:1.5rem" onclick="document.getElementById('baseline-overlay').innerHTML=''">Close</button>
        </div>
      </div>`;
    } else {
      el.innerHTML = '';
      showToast('Profile generation failed', 'error');
    }
  } catch(e) {
    el.innerHTML = '';
    showToast('Profile generation failed', 'error');
  }
}

function closeSettingsMenu() {
  const el = document.getElementById('settings-dropdown');
  if (el) el.remove();
}

function redoBaseline() {
  closeSettingsMenu();
  _stateCache.baseline_done = false;
  apiPost('/api/state', { baseline_done: false });
  showBaseline();
}

function showStartDateSetting() {
  closeSettingsMenu();
  const current = _stateCache.start_date || '';
  const date = prompt('Enter program start date (YYYY-MM-DD):', current);
  if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
    _stateCache.start_date = date;
    apiPost('/api/state', { start_date: date });
    // Recalculate current week
    const start = new Date(date);
    const now = new Date();
    const diffDays = Math.floor((now - start) / (1000 * 60 * 60 * 24));
    const week = Math.min(12, Math.max(1, Math.floor(diffDays / 7) + 1));
    currentWeek = week;
    currentPhase = WEEK_TO_PHASE[week];
    renderAll();
  }
}

async function exportData() {
  closeSettingsMenu();
  try {
    const res = await fetch('/api/export');
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '12week_backup_' + todayStr() + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch(e) {
    alert('Export failed: ' + e.message);
  }
}

function importData() {
  closeSettingsMenu();
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const res = await fetch('/api/import', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
      });
      if (res.ok) {
        alert('Import successful. Reloading...');
        location.reload();
      } else {
        alert('Import failed.');
      }
    } catch(err) {
      alert('Import error: ' + err.message);
    }
  };
  input.click();
}

// ─── RPE FEEDBACK ───────────────────────────────────────────────────────────
function submitRPE(week, dayIdx, exIdx, exName, rpe) {
  // Read from per-set inputs — use the last set's weight
  let weight = 0;
  let totalReps = 0;
  for (let s = 0; s < 20; s++) {
    const wtEl = document.getElementById(`wt-${week}-${dayIdx}-${exIdx}-${s}`);
    if (!wtEl) break;
    const w = parseFloat(wtEl.value) || 0;
    if (w > 0) weight = w;
    const rEl = document.getElementById(`reps-${week}-${dayIdx}-${exIdx}-${s}`);
    if (rEl) totalReps += parseInt(rEl.value) || 0;
  }
  const weekData = workoutData[String(week)];
  const setsLabel = weekData ? weekData.days[dayIdx].exercises[exIdx].sets : '';
  const rpeScore = rpe === 'too_easy' ? 5 : rpe === 'just_right' ? 7 : 9;
  recordWeight(exName, weight, setsLabel, rpe, week, dayIdx, rpeScore, totalReps || null);
  renderDetail();
}

async function showExerciseSwap(exIdx, exerciseName, event) {
    if (event) event.stopPropagation();
    const swapContainer = document.getElementById('swap-container-' + exIdx);
    if (!swapContainer) return;
    if (swapContainer.innerHTML.trim()) { swapContainer.innerHTML = ''; return; }
    swapContainer.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:4px 0">Loading...</div>';

    // Always look up alternatives for the ORIGINAL exercise, not the current swap
    const weekData = workoutData[String(currentWeek)];
    const dayData = weekData ? weekData.days[currentDay] : null;
    const originalName = dayData && dayData.exercises && dayData.exercises[exIdx] ? dayData.exercises[exIdx].name : exerciseName;
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    const isCurrentlySwapped = !!swaps[`${currentWeek}_${currentDay}_${exIdx}`];

    try {
        const res = await fetch('/api/exercise/alternatives/' + encodeURIComponent(originalName));
        const data = await res.json();

        let options = [];

        // If currently swapped, offer "Revert to original" first
        if (isCurrentlySwapped) {
            options.push(`<div class="swap-option" onclick="revertExerciseSwap(${currentWeek},${currentDay},${exIdx})" style="border-left:3px solid var(--accent)">
                <span class="swap-name">${escapeHtml(originalName)}</span>
                <span class="swap-note">Original exercise</span>
            </div>`);
        }

        // Add all alternatives (excluding the one currently displayed)
        if (data.alternatives) {
            for (const alt of data.alternatives) {
                if (alt.name === exerciseName) continue; // Skip current
                options.push(`<div class="swap-option" onclick="swapExercise(${currentWeek},${currentDay},${exIdx},'${alt.name.replace(/'/g, "\\'")}')">
                    <span class="swap-name">${alt.name}</span>
                    <span class="swap-note">${alt.note}</span>
                </div>`);
            }
        }

        if (options.length === 0) {
            swapContainer.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:4px 0">No alternatives available</div>';
            return;
        }

        swapContainer.innerHTML = `<div class="swap-options">${options.join('')}</div>`;
    } catch(e) {
        swapContainer.innerHTML = '<div style="color:var(--red);font-size:13px">Failed to load alternatives</div>';
    }
}

function revertExerciseSwap(week, day, exIdx) {
    const key = week + '_' + day + '_' + exIdx;
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    delete swaps[key];
    sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
    // Also remove from DB
    apiPost('/api/exercise-swap', { week, day_idx: day, exercise_idx: exIdx, swapped_to: '' });
    renderDetail();
}

// Hotel room bodyweight workouts — no equipment, no excuses
const BW_WORKOUTS = {
    upper: [
        {name: 'Push-Ups', sets: '4x15-20', rest: '60s', note: 'Slow eccentric, chest to floor'},
        {name: 'Diamond Push-Ups', sets: '3x10-12', rest: '60s', note: 'Hands together, tricep focus'},
        {name: 'Pike Push-Ups', sets: '3x10', rest: '60s', note: 'Hips high, shoulders are the prime mover'},
        {name: 'Inverted Row (table edge)', sets: '3x12', rest: '60s', note: 'Grab table edge, pull chest to it'},
        {name: 'Tricep Dips (chair)', sets: '3x12-15', rest: '45s', note: 'Hands on chair edge, feet forward'},
        {name: 'Plank Shoulder Taps', sets: '3x20', rest: '45s', note: 'Plank position, tap opposite shoulder'},
    ],
    lower: [
        {name: 'Bodyweight Squats', sets: '4x20', rest: '60s', note: 'Full depth, heels down'},
        {name: 'Bulgarian Split Squats', sets: '3x12 each', rest: '60s', note: 'Rear foot on bed or chair'},
        {name: 'Walking Lunges', sets: '3x12 each', rest: '60s', note: 'Long stride, knee just off floor'},
        {name: 'Single Leg Glute Bridge', sets: '3x15 each', rest: '45s', note: 'One leg, squeeze at top'},
        {name: 'Jump Squats', sets: '3x10', rest: '60s', note: 'Explode up, soft landing'},
        {name: 'Wall Sit', sets: '3x45s', rest: '30s', note: 'Back flat, thighs parallel'},
    ],
    full: [
        {name: 'Burpees', sets: '4x10', rest: '60s', note: 'Full burpee — chest to floor, jump up'},
        {name: 'Push-Ups', sets: '3x15', rest: '60s', note: 'Strict form, full ROM'},
        {name: 'Bodyweight Squats', sets: '3x20', rest: '60s', note: 'Full depth'},
        {name: 'Mountain Climbers', sets: '3x30s', rest: '30s', note: 'Fast, drive knees to chest'},
        {name: 'Plank', sets: '3x60s', rest: '30s', note: 'Tight core, neutral spine'},
        {name: 'Lunges', sets: '3x12 each', rest: '45s', note: 'Alternating, controlled'},
    ],
};

function toggleBodyweightMode(on) {
    sessionStorage.setItem('bw_only_mode', on ? 'true' : 'false');
    if (on) {
        // Determine workout type from today's lift name
        const weekData = workoutData[String(currentWeek)];
        if (weekData && weekData.days[currentDay]) {
            const liftName = (weekData.days[currentDay].liftName || '').toLowerCase();
            let bwType = 'full';
            if (liftName.includes('upper') || liftName.includes('chest') || liftName.includes('push') || liftName.includes('pull') || liftName.includes('shoulder')) bwType = 'upper';
            else if (liftName.includes('lower') || liftName.includes('squat') || liftName.includes('leg') || liftName.includes('hinge')) bwType = 'lower';

            const bwExercises = BW_WORKOUTS[bwType];
            const swaps = {};
            bwExercises.forEach((ex, i) => {
                swaps[currentWeek + '_' + currentDay + '_' + i] = ex.name;
            });
            sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
            sessionStorage.setItem('bw_exercises', JSON.stringify(bwExercises));
        }
    } else {
        const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
        const prefix = currentWeek + '_' + currentDay + '_';
        Object.keys(swaps).filter(k => k.startsWith(prefix)).forEach(k => delete swaps[k]);
        sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
        sessionStorage.removeItem('bw_exercises');
    }
    renderDetail();
}

function swapExercise(week, day, exIdx, newName) {
    const key = week + '_' + day + '_' + exIdx;
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    swaps[key] = newName;
    sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
    // Persist to DB
    apiPost('/api/exercise-swap', { week, day_idx: day, exercise_idx: exIdx, swapped_to: newName });
    renderDetail();
}

// ─── INIT ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Fetch all data in parallel
  try {
    const [stateRes, weightsRes, compRes, suppRes, bwRes, workoutRes, mealsRes] = await Promise.all([
      fetch('/api/state'),
      fetch('/api/weights'),
      fetch('/api/completions'),
      fetch('/api/supplements?date=' + todayStr()),
      fetch('/api/bodyweight'),
      fetch('/api/workouts'),
      fetch('/api/meals?date=' + todayStr()),
    ]);

    if (stateRes.status === 401) {
      window.location.href = '/login';
      return;
    }

    // Detect and send browser timezone
    try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (tz) {
            fetch('/api/user/timezone', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({timezone: tz})
            }).catch(() => {});
        }
    } catch(e) {}

    _stateCache = await stateRes.json();
    _weightsCache = await weightsRes.json();
    _completionsCache = await compRes.json();
    _supplementsCache = await suppRes.json();
    _bodyweightCache = await bwRes.json();
    workoutData = await workoutRes.json();

    try {
      const mealsData = await mealsRes.json();
      _mealsCache[todayStr()] = mealsData;
    } catch(e) {}

    // Warm-up completions
    try { const wuRes = await fetch('/api/warmup-completions'); _warmupCache = await wuRes.json(); } catch(e) { _warmupCache = {}; }

    // Run logs
    try { const rlRes = await fetch('/api/run-log'); _runLogCache = await rlRes.json(); } catch(e) { _runLogCache = {}; }

    // Compliance grade
    try { const complianceRes = await fetch('/api/compliance'); _complianceCache = await complianceRes.json(); } catch(e) { _complianceCache = null; }

    // Per-set completion cache — loaded per-day in renderDetail()
    _setCache = {};

    // Set state from cache
    currentWeek = _stateCache.current_week || 1;
    currentPhase = WEEK_TO_PHASE[currentWeek];

    // Auto-calculate week from start date if set
    if (_stateCache.start_date) {
      const start = new Date(_stateCache.start_date + 'T00:00:00');
      const now = new Date();
      // If start date is in the future, show lockout screen
      if (start > now) {
        showPreStartLockout(_stateCache.start_date);
        return; // Don't render the app
      }
      const diffDays = Math.floor((now - start) / (1000 * 60 * 60 * 24));
      const week = Math.min(12, Math.max(1, Math.floor(diffDays / 7) + 1));
      currentWeek = week;
      currentPhase = WEEK_TO_PHASE[week];
    }

    // Cache meal plans for fasting toggle
    for (const wk of Object.values(workoutData)) {
      for (const d of (wk.days || [])) {
        if (d.mealType === 'rest' && d.mealPlan) {
          window._mealPlansCache = window._mealPlansCache || {};
          window._mealPlansCache.rest = d.mealPlan;
        }
      }
    }
    if (!window._mealPlansCache) window._mealPlansCache = {};
    if (!window._mealPlansCache.fast_day) {
      window._mealPlansCache.fast_day = {
        label: '24h Fast Day',
        targetCal: 0, targetProtein: 0, targetCarbs: 0, targetFat: 0,
        note: 'Full 24h fast. Water, black coffee, electrolytes only.',
        meals: [{
          time: 'All Day', name: 'Fast - Liquids Only', optional: false,
          foods: [
            { item: 'Water', portion: 'Unlimited', cal: 0, protein: 0, carbs: 0, fat: 0 },
            { item: 'Black coffee', portion: 'As needed', cal: 5, protein: 0, carbs: 0, fat: 0 },
            { item: 'Electrolytes (salt, potassium)', portion: 'As needed', cal: 0, protein: 0, carbs: 0, fat: 0 },
          ]
        }]
      };
    }

    // Always check if onboarding is truly complete
    // Check for ?action=restart-plan query param
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('action') === 'restart-plan') {
      // Clear the query param from URL
      window.history.replaceState({}, '', '/');
      showFinalReveal();
    } else {
      const onboardingDone = await checkOnboardingComplete();
      if (!onboardingDone) {
        await resumeOnboarding();
      }
    }

    // Travel banner
    renderTravelBanner();

    // Load chat history BEFORE rendering so coach has messages
    await loadChatHistory();

    // Morning checkin gate disabled — always unlocked
    _morningCheckinDone = true;

    renderAll();
  } catch(e) {
    console.error('Init failed', e);
    // Fallback: try to render with empty data
    _stateCache = _stateCache || { current_week: 1, baseline_done: false };
    _weightsCache = _weightsCache || {};
    _completionsCache = _completionsCache || { exercises: {}, days: {} };
    _supplementsCache = _supplementsCache || { taken: {}, list: [] };
    _bodyweightCache = _bodyweightCache || [];
    renderAll();
  } finally {
    // ALWAYS hide loading spinner — even on error, redirect, or early return
    const appLoading = document.getElementById('app-loading');
    if (appLoading) appLoading.style.display = 'none';
  }
});

function saveState() {
  _stateCache.current_week = currentWeek;
  apiPost('/api/state', { current_week: currentWeek });
}

// ─── LOCALSTORAGE MIGRATION ────────────────────────────────────────────────
function checkLocalStorageMigration() {
  const hasLocalData = localStorage.getItem('12w_weights') || localStorage.getItem('12w_baseline_done');
  const dbEmpty = !_stateCache.baseline_done && (!_weightsCache || Object.keys(_weightsCache).length === 0);
  if (hasLocalData && dbEmpty) {
    renderMigrationBanner();
  }
}

function renderMigrationBanner() {
  const banner = document.getElementById('migration-banner');
  if (!banner) return;
  banner.innerHTML = `
    <div class="migration-inner">
      <span>Local data found. Migrate to cloud storage?</span>
      <div class="migration-actions">
        <button class="btn btn-primary" onclick="migrateLocalStorage()">Migrate</button>
        <button class="btn btn-secondary" onclick="dismissMigration()">Dismiss</button>
      </div>
    </div>
  `;
  banner.classList.add('visible');
}

async function migrateLocalStorage() {
  const data = {};
  // Gather all localStorage keys
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('12w_')) {
      try {
        data[key] = JSON.parse(localStorage.getItem(key));
      } catch(e) {
        data[key] = localStorage.getItem(key);
      }
    }
  }
  try {
    const res = await fetch('/api/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ localStorage: data }),
    });
    if (res.ok) {
      document.getElementById('migration-banner').classList.remove('visible');
      alert('Migration successful. Reloading...');
      location.reload();
    }
  } catch(e) {
    alert('Migration failed: ' + e.message);
  }
}

function dismissMigration() {
  const banner = document.getElementById('migration-banner');
  if (banner) banner.classList.remove('visible');
}

// ─── TRAVEL MODE ───────────────────────────────────────────────────────────
function toggleTravelMode() {
  if (!_stateCache) _stateCache = {};
  _stateCache.traveling = !_stateCache.traveling;
  apiPost('/api/state', { traveling: _stateCache.traveling });
  closeSettingsMenu();
  renderTravelBanner();
  renderAll();
}

function renderTravelBanner() {
  let banner = document.getElementById('travel-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'travel-banner';
    banner.className = 'travel-banner';
    const header = document.querySelector('header');
    header.parentNode.insertBefore(banner, header.nextSibling);
  }
  if (_stateCache && _stateCache.traveling) {
    banner.textContent = '\uD83C\uDFD6\uFE0F Travel Mode \u2014 Bodyweight workouts';
    banner.classList.add('visible');
  } else {
    banner.classList.remove('visible');
  }
}

// ─── MORNING PSYCHOLOGICAL CHECK-IN ────────────────────────────────────────
async function checkMorningCheckin() {
  const today = todayStr();
  try {
    const res = await fetch('/api/morning-checkin?date=' + today);
    const data = await res.json();
    if (data.exists) {
      _morningCheckinCache = data.checkin || data;
      renderCheckinSummaryBar();
    } else {
      showMorningCheckinOverlay();
    }
  } catch(e) {
    console.error('Morning checkin check failed', e);
  }
}

function buildMorningBriefing() {
  let lines = [];
  if (garminConnected && garminData) {
    const hrv = garminData.hrv;
    const sleep = garminData.sleep;
    const bb = garminData.bodyBattery;
    if (hrv && hrv.lastNight != null) {
      lines.push('Your HRV is ' + hrv.lastNight + ' (avg ' + (hrv.weeklyAvg || '?') + ').');
    }
    if (sleep) {
      lines.push('Sleep: ' + (sleep.durationHours || '?') + ' hours, score ' + (sleep.score != null ? sleep.score : '?') + '.');
    }
    if (bb && bb.current != null) {
      lines.push('Body battery: ' + bb.current + '.');
    }
  }
  // Today's workout info
  const weekData = workoutData[String(currentWeek)];
  if (weekData) {
    const todayIdx = new Date().getDay();
    const mappedIdx = todayIdx === 0 ? 6 : todayIdx - 1;
    const dayData = weekData.days[mappedIdx];
    if (dayData) {
      lines.push('Today is ' + dayData.liftName + ' -- Week ' + currentWeek + '.');
    }
  }
  lines.push('How are you feeling?');
  return lines.join(' ');
}

function showMorningCheckinOverlay() {
  const el = document.getElementById('morning-checkin-overlay');
  if (!el) return;

  const briefing = buildMorningBriefing();

  el.innerHTML = `<div class="morning-checkin-overlay">
    <div class="morning-checkin-card">
      <div class="morning-briefing">
        <div class="morning-briefing-label">Coach Erik</div>
        <div class="morning-briefing-bubble">${briefing}</div>
      </div>
      <div class="mc-subtitle">Your check-in</div>

      <div class="mc-slider-row">
        <label>Sleep</label>
        <div class="mc-range-wrap">
          <input type="range" class="mc-slider" id="mc-sleep" min="1" max="10" value="5">
          <div class="mc-range-labels"><span>Terrible</span><span>Amazing</span></div>
        </div>
        <span class="mc-slider-val" id="mc-sleep-val">5</span>
      </div>

      <div class="mc-slider-row">
        <label>Stress</label>
        <div class="mc-range-wrap">
          <input type="range" class="mc-slider" id="mc-stress" min="1" max="10" value="5">
          <div class="mc-range-labels"><span>Calm</span><span>Overwhelmed</span></div>
        </div>
        <span class="mc-slider-val" id="mc-stress-val">5</span>
      </div>

      <div class="mc-slider-row">
        <label>Soreness</label>
        <div class="mc-range-wrap">
          <input type="range" class="mc-slider" id="mc-soreness" min="1" max="10" value="5">
          <div class="mc-range-labels"><span>Fresh</span><span>Wrecked</span></div>
        </div>
        <span class="mc-slider-val" id="mc-soreness-val">5</span>
      </div>
      <div class="mc-followup" id="mc-soreness-followup" style="display:none">
        <label>Where are you sore?</label>
        <input type="text" class="mc-followup-input" id="mc-soreness-where" placeholder="e.g. shoulders, quads, lower back...">
      </div>

      <div class="mc-slider-row">
        <label>Mood</label>
        <div class="mc-range-wrap">
          <input type="range" class="mc-slider" id="mc-mood" min="0" max="10" value="5">
          <div class="mc-range-labels"><span>Very Low</span><span>Very High</span></div>
        </div>
        <span class="mc-slider-val" id="mc-mood-val">5</span>
      </div>

      <div class="mc-slider-row">
        <label>Motivation</label>
        <div class="mc-range-wrap">
          <input type="range" class="mc-slider" id="mc-motivation" min="1" max="10" value="5">
          <div class="mc-range-labels"><span>Zero</span><span>On Fire</span></div>
        </div>
        <span class="mc-slider-val" id="mc-motivation-val">5</span>
      </div>
      <div class="mc-followup" id="mc-motivation-followup" style="display:none">
        <label>What's draining your motivation?</label>
        <input type="text" class="mc-followup-input" id="mc-motivation-why" placeholder="e.g. tired, bored, work stress, no progress...">
      </div>

      <div class="mc-slider-row">
        <label>Anxiety</label>
        <div class="mc-range-wrap">
          <input type="range" class="mc-slider" id="mc-anxiety" min="1" max="10" value="3">
          <div class="mc-range-labels"><span>None</span><span>Severe</span></div>
        </div>
        <span class="mc-slider-val" id="mc-anxiety-val">3</span>
      </div>
      <div class="mc-followup" id="mc-anxiety-followup" style="display:none">
        <label>What's causing the anxiety?</label>
        <input type="text" class="mc-followup-input" id="mc-anxiety-why" placeholder="e.g. work deadline, relationship, health, finances...">
      </div>

      <div class="mc-textarea-label">Anything else on your mind today?</div>
      <textarea class="mc-textarea" id="mc-notes" placeholder="Optional \u2014 free text..."></textarea>

      <button class="btn btn-primary" style="width:100%" onclick="submitMorningCheckin()">Let's Go</button>
      <button class="btn btn-secondary" style="width:100%;margin-top:8px;opacity:0.7" onclick="skipMorningCheckin()">Skip Today</button>
    </div>
  </div>`;

  // Wire up slider value displays and follow-up questions
  const sliders = ['sleep', 'stress', 'soreness', 'mood', 'motivation', 'anxiety'];
  sliders.forEach(name => {
    const slider = document.getElementById('mc-' + name);
    const valEl = document.getElementById('mc-' + name + '-val');
    if (slider && valEl) {
      slider.addEventListener('input', () => {
        valEl.textContent = slider.value;
        const val = parseInt(slider.value);
        // Show follow-up for concerning values
        if (name === 'soreness') {
          const fu = document.getElementById('mc-soreness-followup');
          if (fu) fu.style.display = val >= 6 ? 'block' : 'none';
        }
        if (name === 'motivation') {
          const fu = document.getElementById('mc-motivation-followup');
          if (fu) fu.style.display = val <= 4 ? 'block' : 'none';
        }
        if (name === 'anxiety') {
          const fu = document.getElementById('mc-anxiety-followup');
          if (fu) fu.style.display = val >= 6 ? 'block' : 'none';
        }
      });
    }
  });
}

function submitMorningCheckin() {
  // Build notes from follow-ups + free text
  const parts = [];
  const sorenessWhere = (document.getElementById('mc-soreness-where')?.value || '').trim();
  if (sorenessWhere) parts.push('Sore: ' + sorenessWhere);
  const motivationWhy = (document.getElementById('mc-motivation-why')?.value || '').trim();
  if (motivationWhy) parts.push('Low motivation: ' + motivationWhy);
  const anxietyWhy = (document.getElementById('mc-anxiety-why')?.value || '').trim();
  if (anxietyWhy) parts.push('Anxiety: ' + anxietyWhy);
  const freeText = (document.getElementById('mc-notes').value || '').trim();
  if (freeText) parts.push(freeText);

  const data = {
    date: todayStr(),
    sleep_quality: parseInt(document.getElementById('mc-sleep').value) || 5,
    stress_level: parseInt(document.getElementById('mc-stress').value) || 5,
    soreness: parseInt(document.getElementById('mc-soreness').value) || 5,
    mood: parseInt(document.getElementById('mc-mood').value) || 5,
    motivation: parseInt(document.getElementById('mc-motivation').value) || 5,
    anxiety: parseInt(document.getElementById('mc-anxiety').value) || 3,
    notes: parts.join(' | '),
  };

  fetch('/api/morning-checkin', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data),
  }).catch(e => console.error('Morning checkin submit failed', e));

  _morningCheckinCache = data;

  // Transition to Coach response -- don't just close, show feedback
  const el = document.getElementById('morning-checkin-overlay');
  const card = el.querySelector('.morning-checkin-card');
  if (card) {
    // Build a summary of what they entered
    const summary = `Morning check-in: Sleep ${data.sleep_quality}/10, Stress ${data.stress_level}/10, Soreness ${data.soreness}/10, Mood ${data.mood}/10, Motivation ${data.motivation}/10, Anxiety ${data.anxiety}/10.${data.notes ? ' Notes: ' + data.notes : ''}`;

    card.innerHTML = `
      <h2>Check-In Received</h2>
      <div class="mc-coach-loading">
        <div class="chat-typing"><span></span><span></span><span></span></div>
        <div style="margin-top:8px;color:var(--muted);font-size:14px;">Erik is looking at your numbers...</div>
      </div>
      <div id="mc-coach-response" style="display:none"></div>
      <div id="mc-coach-chat" style="display:none">
        <div id="mc-coach-messages" class="mc-coach-messages"></div>
        <div class="mc-coach-input-bar">
          <input type="text" id="mc-coach-input" placeholder="Reply to Erik..." enterkeyhint="send" onkeydown="if(event.key==='Enter')sendMorningCoachReply()">
          <button class="chat-mic-btn" onclick="toggleVoiceInput('mc-coach-input')" title="Voice input">&#127908;</button>
          <button onclick="sendMorningCoachReply()">Send</button>
        </div>
      </div>
      <button class="btn btn-primary mc-continue-btn" id="mc-continue-btn" style="display:none;width:100%;margin-top:12px" onclick="closeMorningCheckin()">Show Me Today's Workout</button>
    `;

    // Fetch morning briefing
    fetch('/api/morning-briefing', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    }).then(r => r.json()).then(d => {
      const loading = card.querySelector('.mc-coach-loading');
      if (loading) loading.style.display = 'none';

      const statusColor = d.status === 'GREEN' ? 'var(--accent)' : d.status === 'YELLOW' ? 'var(--amber)' : 'var(--red)';
      const responseEl = document.getElementById('mc-coach-response');
      if (responseEl) {
        responseEl.style.display = 'block';
        responseEl.innerHTML = `<div class="morning-briefing-card">
            <div class="briefing-status" style="color:${statusColor}">${d.status}</div>
            <div class="briefing-message">${d.message || ''}</div>
            <div class="briefing-workout">${d.workout || ''}</div>
        </div>`;
      }
      const continueBtn = document.getElementById('mc-continue-btn');
      if (continueBtn) continueBtn.style.display = 'block';
    }).catch(() => {
      const loading = card.querySelector('.mc-coach-loading');
      if (loading) loading.style.display = 'none';
      const continueBtn = document.getElementById('mc-continue-btn');
      if (continueBtn) continueBtn.style.display = 'block';
    });
  }
}

async function sendMorningCoachReply() {
  const input = document.getElementById('mc-coach-input');
  const text = (input.value || '').trim();
  if (!text) return;
  input.value = '';

  // Show user message
  const messagesEl = document.getElementById('mc-coach-messages');
  if (messagesEl) {
    messagesEl.innerHTML += `<div class="mc-user-bubble">${escapeHtml(text)}</div>`;
    messagesEl.innerHTML += `<div class="mc-typing-indicator"><div class="chat-typing"><span></span><span></span><span></span></div></div>`;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text }),
    });

    if (messagesEl) {
      const typing = messagesEl.querySelector('.mc-typing-indicator');
      if (typing) typing.remove();
    }

    const streamBubble = document.createElement('div');
    streamBubble.className = 'mc-coach-bubble';
    if (messagesEl) {
      messagesEl.appendChild(streamBubble);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    let fullText = '';
    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') break;
          if (data === '[ERROR]') {
            fullText = fullText || 'Connection issue. Try again.';
            break;
          }
          fullText += data;
          if (streamBubble) {
            streamBubble.textContent = fullText;
            if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
          }
        }
      }
    }

    if (_chatHistory) {
      _chatHistory.push({ role: 'user', content: text, date: todayStr() });
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    if (messagesEl) {
      const typing = messagesEl.querySelector('.mc-typing-indicator');
      if (typing) typing.remove();
    }
  }
}

function closeMorningCheckin() {
  document.getElementById('morning-checkin-overlay').innerHTML = '';
  renderCheckinSummaryBar();

  const today = new Date();
  if (today.getDay() === 0) {
    showSundayFlow();
  }
}

async function showSundayFlow() {
  // Step 1: Generate and show weekly report
  try {
    const reportRes = await fetch('/api/weekly-report/generate', { method: 'POST' });
    const reportData = await reportRes.json();

    // Poll for narrative
    let narrative = null;
    if (reportData.job_id) {
      for (let i = 0; i < 30; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const pollRes = await fetch('/api/weekly-report/result/' + reportData.job_id);
        const pollData = await pollRes.json();
        if (pollData.status !== 'pending') {
          narrative = pollData.narrative;
          break;
        }
      }
    }

    // Show report card
    const m = reportData.metrics || {};
    const overlay = document.getElementById('morning-checkin-overlay');
    overlay.innerHTML = `<div class="morning-checkin-overlay">
      <div class="morning-checkin-card" style="max-width:500px">
        <h2>Week ${m.week || currentWeek} Summary</h2>
        <div class="report-stats">
          <div class="report-stat"><span class="report-stat-label">Workouts</span><span class="report-stat-val">${m.workouts_completed || 0}/${m.workouts_total || 6}</span></div>
          <div class="report-stat"><span class="report-stat-label">Weight</span><span class="report-stat-val">${m.weight_change ? (m.weight_change > 0 ? '+' : '') + m.weight_change + ' lbs' : '--'}</span></div>
          <div class="report-stat"><span class="report-stat-label">vs Target</span><span class="report-stat-val">${m.weight_vs_projected || '--'}</span></div>
          <div class="report-stat"><span class="report-stat-label">Adherence</span><span class="report-stat-val">${m.adherence_pct || 0}%</span></div>
        </div>
        ${narrative ? '<div class="report-narrative">' + narrative + '</div>' : ''}
        <div id="shopping-list-section"></div>
        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="document.getElementById('morning-checkin-overlay').innerHTML='';triggerWeeklyPlanning()">Continue to Weekly Planning</button>
      </div>
    </div>`;
    // Load shopping list
    try {
      const shopRes = await fetch('/api/shopping-list');
      const shopData = await shopRes.json();
      const shopEl = document.getElementById('shopping-list-section');
      if (shopEl && shopData.categories && shopData.categories.length > 0) {
        let shopHtml = '';
        for (const cat of shopData.categories) {
          shopHtml += `<div class="shop-category"><div class="shop-cat-label">${cat.category}</div>`;
          for (const item of cat.items) {
            shopHtml += `<div class="shop-item"><span class="shop-item-name">${item.item}</span><span class="shop-item-qty">${item.total}</span></div>`;
          }
          shopHtml += `</div>`;
        }
        shopEl.innerHTML = `<div class="plan-section" style="margin-top:1rem">
          <div class="plan-section-label">Grocery List — Week ${shopData.week}</div>
          <div class="shop-list">${shopHtml}</div>
        </div>`;
      }
    } catch(e) {}

  } catch(e) {
    triggerWeeklyPlanning();
  }
}

async function triggerWeeklyPlanning() {
  // Check if we already did weekly planning today
  const planKey = '12w_weekly_plan_' + todayStr();
  if (localStorage.getItem(planKey)) return;

  // Open the chat overlay with a weekly planning prompt
  toggleChatOverlay();

  // Wait a beat for the overlay to render
  await new Promise(r => setTimeout(r, 500));

  // Send the weekly planning trigger to Coach
  const weekNum = currentWeek;
  const nextWeek = Math.min(weekNum + 1, 12);
  const msg = `[WEEKLY_PLANNING] It's Sunday. Week ${weekNum} is done, week ${nextWeek} starts tomorrow. Review my week, then let's plan. Ask me about any travel, races, schedule changes, or injuries for the coming week. Adjust the plan based on what I tell you.`;

  // Find the chat input and programmatically send
  const inputEl = document.getElementById('chat-overlay-input') || document.getElementById('chat-input-field');
  if (inputEl) {
    inputEl.value = msg;
  }

  // Actually send it
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: msg }),
    });
    const d = await res.json();

    if (_chatHistory) {
      _chatHistory.push({ role: 'user', content: 'Weekly planning check-in', date: todayStr() });
      _chatHistory.push({ role: 'assistant', content: d.response, date: todayStr(), time: d.time });
    }

    // Re-render the chat to show the response
    if (typeof renderChatOverlay === 'function') renderChatOverlay();

    localStorage.setItem(planKey, '1');
  } catch(e) {
    console.error('Weekly planning failed', e);
  }
}

function renderCheckinSummaryBar() {
  const el = document.getElementById('checkin-summary-bar');
  if (!el || !_morningCheckinCache) {
    if (el) el.classList.remove('visible');
    return;
  }
  const c = _morningCheckinCache;

  function scoreClass(val, reversed) {
    if (reversed) {
      if (val < 4) return 'score-good';
      if (val <= 6) return 'score-mid';
      return 'score-bad';
    }
    if (val > 6) return 'score-good';
    if (val >= 4) return 'score-mid';
    return 'score-bad';
  }

  const items = [
    { label: 'Mood', val: c.mood, rev: false },
    { label: 'Sleep', val: c.sleep, rev: false },
    { label: 'Stress', val: c.stress, rev: true },
    { label: 'Motivation', val: c.motivation, rev: false },
    { label: 'Soreness', val: c.soreness, rev: true },
    { label: 'Anxiety', val: c.anxiety, rev: true },
  ];

  const badges = items.map(i =>
    `<span class="checkin-score ${scoreClass(i.val, i.rev)}">${i.label}: ${i.val}</span>`
  ).join('');

  el.innerHTML = `<div class="checkin-summary-inner">
    <span class="checkin-summary-label">Today</span>
    ${badges}
  </div>`;
  el.classList.add('visible');
}

// ─── AI COACH CHAT ─────────────────────────────────────────────────────────
async function loadChatHistory() {
  try {
    const res = await fetch('/api/coach/today-history');
    const data = await res.json();
    const raw = Array.isArray(data) ? data : (data.messages || []);
    _chatHistory = raw.map(m => ({ ...m, text: m.text || m.content || '' }));
  } catch(e) {
    _chatHistory = [];
  }
  updateChatFabPulse();
}

function updateChatFabPulse() {
  const fab = document.getElementById('chat-fab');
  if (!fab) return;
  const today = todayStr();
  const todayMessages = _chatHistory.filter(m => m.time && m.time.startsWith(today));
  if (todayMessages.length === 0) {
    fab.classList.add('pulse');
  } else {
    fab.classList.remove('pulse');
  }
}

function toggleChatOverlay() {
  if (_chatOverlayOpen) {
    const msgs = document.getElementById('chat-overlay-messages');
    if (msgs) _chatScrollPos = msgs.scrollTop;
  }
  _chatOverlayOpen = !_chatOverlayOpen;
  renderChatOverlay();
}

function closeChatOverlay() {
  const msgs = document.getElementById('chat-overlay-messages');
  if (msgs) _chatScrollPos = msgs.scrollTop;
  _chatOverlayOpen = false;
  renderChatOverlay();
}

function renderChatOverlay() {
  const el = document.getElementById('chat-overlay');
  if (!el) return;
  if (!_chatOverlayOpen) {
    el.classList.remove('visible');
    el.innerHTML = '';
    return;
  }

  el.classList.add('visible');
  el.innerHTML = `
    <div class="chat-header">
      <h2>Coach Erik</h2>
      <button class="chat-close" onclick="closeChatOverlay()">&times;</button>
    </div>
    <div class="chat-messages" id="chat-overlay-messages"></div>
    <div class="chat-input-bar">
      <input type="text" id="chat-overlay-input" placeholder="Ask Erik anything..." enterkeyhint="send" onkeydown="if(event.key==='Enter')sendChatMessage('chat-overlay-input','chat-overlay-messages')">
      <button class="chat-mic-btn" id="chat-mic-btn" onclick="toggleVoiceInput('chat-overlay-input')" title="Voice input">&#127908;</button>
      <button onclick="sendChatMessage('chat-overlay-input','chat-overlay-messages')">Send</button>
    </div>
  `;

  renderChatMessages('chat-overlay-messages');
  const input = document.getElementById('chat-overlay-input');
  if (input) setTimeout(() => input.focus(), 100);
}

function renderChatMessages(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  let html = '';
  for (const m of _chatHistory) {
    const isUser = m.role === 'user';
    const bubbleCls = isUser ? 'chat-bubble user' : 'chat-bubble coach';
    const tsCls = isUser ? 'chat-timestamp ts-user' : 'chat-timestamp ts-coach';
    html += `<div class="${bubbleCls}">${escapeHtml(m.text || m.content || '')}</div>`;
    if (m.time) {
      const timeStr = formatChatTime(m.time);
      html += `<div class="${tsCls}">${timeStr}</div>`;
    }
  }
  container.innerHTML = html;
  if (_chatScrollPos !== null) {
    container.scrollTop = _chatScrollPos;
    _chatScrollPos = null;
  } else {
    container.scrollTop = container.scrollHeight;
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatChatTime(timeStr) {
  try {
    const d = new Date(timeStr);
    const today = todayStr();
    const dateStr = d.toISOString().slice(0, 10);
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (dateStr === today) return time;
    return dateStr.slice(5) + ' ' + time;
  } catch(e) {
    return timeStr;
  }
}

async function sendChatMessage(inputId, containerId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const text = (input.value || '').trim();
    if (!text) return;
    input.value = '';

    const now = new Date().toISOString();
    _chatHistory.push({ role: 'user', text: text, time: now });
    renderChatMessages(containerId);
    syncChatContainers(containerId);

    // Show typing indicator
    const container = document.getElementById(containerId);
    if (container) {
        const typing = document.createElement('div');
        typing.className = 'chat-typing';
        typing.id = 'chat-typing-' + containerId;
        typing.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
        container.appendChild(typing);
        container.scrollTop = container.scrollHeight;
    }

    try {
        const _chatAbort = new AbortController();
        const _chatTimeout = setTimeout(() => _chatAbort.abort(), 60000); // 60s timeout
        const res = await fetch('/api/chat/stream', {
            method: 'POST',
            signal: _chatAbort.signal,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: text }),
        });

        // Remove typing indicator and add streaming bubble
        const typingEl = document.getElementById('chat-typing-' + containerId);
        if (typingEl) typingEl.remove();

        const streamBubble = document.createElement('div');
        streamBubble.className = 'chat-bubble coach';
        streamBubble.id = 'stream-bubble-' + containerId;
        if (container) {
            container.appendChild(streamBubble);
            container.scrollTop = container.scrollHeight;
        }

        let fullText = '';
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') break;
                    if (data === '[ERROR]') {
                        fullText = fullText || 'Erik stepped away. He\'ll be back in a moment.';
                        break;
                    }
                    fullText += data;
                    if (streamBubble) {
                        streamBubble.textContent = fullText;
                        if (container) container.scrollTop = container.scrollHeight;
                    }
                }
            }
        }

        // Finalize
        clearTimeout(_chatTimeout);
        _chatHistory.push({ role: 'coach', text: fullText || 'No response', time: new Date().toISOString() });
    } catch(e) {
        const typingEl = document.getElementById('chat-typing-' + containerId);
        if (typingEl) typingEl.remove();
        const errMsg = e.name === 'AbortError' ? 'Response took too long. Try again.' : 'Connection error. Try again.';
        _chatHistory.push({ role: 'coach', text: errMsg, time: new Date().toISOString() });
    }

    renderChatMessages(containerId);
    syncChatContainers(containerId);
    updateChatFabPulse();
    renderCoachTop();
}

function syncChatContainers(sourceId) {
  // Keep both containers in sync
  const ids = ['chat-overlay-messages', 'coach-messages'];
  for (const id of ids) {
    if (id !== sourceId) {
      renderChatMessages(id);
    }
  }
}

function renderInlineChat() {
  let chatMessagesHtml = '';
  for (const m of _chatHistory) {
    const isUser = m.role === 'user';
    const bubbleCls = isUser ? 'chat-bubble user' : 'chat-bubble coach';
    const tsCls = isUser ? 'chat-timestamp ts-user' : 'chat-timestamp ts-coach';
    chatMessagesHtml += `<div class="${bubbleCls}">${escapeHtml(m.text || m.content || '')}</div>`;
    if (m.time) {
      chatMessagesHtml += `<div class="${tsCls}">${formatChatTime(m.time)}</div>`;
    }
  }
  return chatMessagesHtml;
}

// ─── VOICE INPUT ──────────────────────────────────────────────────────────
let _voiceRecognition = null;
let _voiceActive = false;

function toggleVoiceInput(inputId) {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        showToast('Voice input not supported in this browser', 'error');
        return;
    }

    if (_voiceActive && _voiceRecognition) {
        _voiceRecognition.stop();
        _voiceActive = false;
        updateMicButton(false);
        return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    _voiceRecognition = new SpeechRecognition();
    _voiceRecognition.continuous = false;
    _voiceRecognition.interimResults = true;
    _voiceRecognition.lang = 'en-US';

    const input = document.getElementById(inputId);
    let finalTranscript = '';

    _voiceRecognition.onstart = () => {
        _voiceActive = true;
        updateMicButton(true);
    };

    _voiceRecognition.onresult = (event) => {
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
            } else {
                interim += event.results[i][0].transcript;
            }
        }
        if (input) {
            input.value = finalTranscript + interim;
        }
    };

    _voiceRecognition.onend = () => {
        _voiceActive = false;
        updateMicButton(false);
        if (input && finalTranscript.trim()) {
            input.value = finalTranscript.trim();
        }
    };

    _voiceRecognition.onerror = (e) => {
        _voiceActive = false;
        updateMicButton(false);
        if (e.error !== 'no-speech') {
            showToast('Voice error: ' + e.error, 'error');
        }
    };

    finalTranscript = '';
    _voiceRecognition.start();
}

function updateMicButton(active) {
    const btns = document.querySelectorAll('.chat-mic-btn');
    btns.forEach(btn => {
        if (active) {
            btn.classList.add('recording');
            btn.innerHTML = '&#9899;'; // red circle
        } else {
            btn.classList.remove('recording');
            btn.innerHTML = '&#127908;'; // microphone
        }
    });
}

// ─── GARMIN ─────────────────────────────────────────────────────────────────
async function garminLogin() {
  const errEl = document.getElementById('garmin-error');
  errEl.style.display = 'none';

  const mfaField = document.getElementById('garmin-mfa');
  if (mfaField && mfaField.style.display !== 'none') {
    const code = mfaField.value.trim();
    if (!code) {
      errEl.textContent = 'Enter your verification code';
      errEl.style.display = 'block';
      return;
    }
    const btn = document.getElementById('garmin-submit');
    btn.textContent = 'Verifying...';
    btn.disabled = true;
    try {
      const res = await fetch('/api/garmin/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ mfa_code: code }),
      });
      const d = await res.json();
      if (d.connected) {
        garminConnected = true;
        closeModal();
        await refreshGarmin();
        renderAll();
      } else {
        errEl.textContent = d.error || 'Verification failed';
        errEl.style.display = 'block';
      }
    } catch(e) {
      errEl.textContent = 'Connection error';
      errEl.style.display = 'block';
    }
    btn.textContent = 'Verify';
    btn.disabled = false;
    return;
  }

  const email = document.getElementById('garmin-email').value;
  const pw = document.getElementById('garmin-password').value;

  if (!email || !pw) {
    errEl.textContent = 'Email and password required';
    errEl.style.display = 'block';
    return;
  }

  const btn = document.getElementById('garmin-submit');
  btn.textContent = 'Connecting...';
  btn.disabled = true;

  try {
    const res = await fetch('/api/garmin/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ email, password: pw }),
    });
    const d = await res.json();
    if (d.connected) {
      garminConnected = true;
      closeModal();
      await refreshGarmin();
      renderAll();
    } else if (d.needs_mfa) {
      document.getElementById('garmin-email').style.display = 'none';
      document.getElementById('garmin-password').style.display = 'none';
      document.getElementById('garmin-mfa').style.display = 'block';
      document.getElementById('garmin-mfa').focus();
      btn.textContent = 'Verify';
      btn.disabled = false;
      errEl.textContent = 'Enter the code from your authenticator app';
      errEl.style.display = 'block';
      errEl.style.color = 'var(--run-tempo)';
      return;
    } else {
      errEl.textContent = d.error || 'Login failed';
      errEl.style.display = 'block';
    }
  } catch(e) {
    errEl.textContent = 'Connection error';
    errEl.style.display = 'block';
  }
  btn.textContent = 'Connect';
  btn.disabled = false;
}

async function garminLogout() {
  try {
    await fetch('/api/garmin/logout', { method: 'POST' });
  } catch(e) {}
  garminConnected = false;
  garminData = null;
  readinessData = null;
  renderAll();
}

async function refreshGarmin() {
  try {
    const [todayRes, readyRes] = await Promise.all([
      fetch('/api/garmin/today'),
      fetch('/api/garmin/readiness'),
    ]);
    if (todayRes.ok) garminData = await todayRes.json();
    if (readyRes.ok) readinessData = await readyRes.json();
  } catch(e) {
    console.error('Garmin refresh failed', e);
  }
}

function showModal() {
  document.getElementById('garmin-modal').classList.add('visible');
}

function closeModal() {
  document.getElementById('garmin-modal').classList.remove('visible');
  document.getElementById('garmin-email').value = '';
  document.getElementById('garmin-password').value = '';
  document.getElementById('garmin-email').style.display = 'block';
  document.getElementById('garmin-password').style.display = 'block';
  const mfa = document.getElementById('garmin-mfa');
  mfa.value = '';
  mfa.style.display = 'none';
  const errEl = document.getElementById('garmin-error');
  errEl.style.display = 'none';
  errEl.textContent = '';
  document.getElementById('garmin-error').style.color = '';
}

// ─── NAVIGATION ─────────────────────────────────────────────────────────────
function setPhase(p) {
  currentPhase = p;
  currentWeek = p === 1 ? 1 : p === 2 ? 5 : 9;
  currentDay = null;
  saveState();
  renderAll();
}

function setWeek(w) {
  currentWeek = w;
  currentPhase = WEEK_TO_PHASE[w];
  currentDay = null;
  saveState();
  renderAll();
}

function setDay(d) {
  currentDay = currentDay === d ? null : d;
  renderTodayNav();
  renderDayGrid();
  renderDetail();
}

// ─── COMPLETION TRACKING (cache-based) ─────────────────────────────────────
function isExDone(week, dayIdx, exIdx) {
  if (!_completionsCache || !_completionsCache.exercises) return false;
  return !!_completionsCache.exercises[week + '_' + dayIdx + '_' + exIdx];
}

function toggleEx(week, dayIdx, exIdx) {
  if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
  if (!_completionsCache.exercises) _completionsCache.exercises = {};
  const key = week + '_' + dayIdx + '_' + exIdx;
  if (_completionsCache.exercises[key]) {
    delete _completionsCache.exercises[key];
  } else {
    _completionsCache.exercises[key] = true;
  }
  apiPost('/api/completions/exercise', { week, day_idx: dayIdx, exercise_idx: exIdx });
  renderDetail();
}

function isDayDone(week, dayIdx) {
  if (!_completionsCache || !_completionsCache.days) return false;
  return !!_completionsCache.days[week + '_' + dayIdx];
}

function toggleDay(week, dayIdx, e) {
  e.stopPropagation();
  if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
  if (!_completionsCache.days) _completionsCache.days = {};
  const key = week + '_' + dayIdx;
  if (_completionsCache.days[key]) {
    delete _completionsCache.days[key];
  } else {
    _completionsCache.days[key] = true;
  }
  apiPost('/api/completions/day', { week, day_idx: dayIdx });
  renderDayGrid();

  // If day just marked complete (not uncompleting), trigger coach feedback — once per session
  if (_completionsCache.days[key] && !sessionStorage.getItem('workout_sent_' + key)) {
    sessionStorage.setItem('workout_sent_' + key, '1');
    const weekData = workoutData[String(week)];
    if (weekData && weekData.days[dayIdx]) {
      const d = weekData.days[dayIdx];
      const summary = `[WORKOUT_COMPLETE] Just finished ${d.liftName}. ` +
          `${d.exercises ? d.exercises.length : 0} exercises completed.`;
      // Send to coach via chat (don't open overlay, just send)
      fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ message: summary }),
      }).then(r => r.json()).then(data => {
        if (data.response) {
          showCoachPopup(data.response);
        }
      }).catch(() => {});
    }
  }
}

// ─── BODY WEIGHT / WEIGH-IN ────────────────────────────────────────────────
function renderWeighInBar() {
  const el = document.getElementById('weighin-bar');
  if (!el) return;

  const bwData = Array.isArray(_bodyweightCache) ? _bodyweightCache : [];
  const today = todayStr();
  const isSunday = new Date().getDay() === 0;

  if (!isSunday) {
    // Only weigh in on Sundays
    const lastEntry = bwData.length > 0 ? bwData[bwData.length - 1] : null;
    el.innerHTML = `<div class="weighin-row">
      <div class="weighin-label">Weight</div>
      <div class="weighin-controls"><span class="weighin-today-val">${lastEntry ? lastEntry.weight + ' lb' : '--'}</span></div>
      <div class="weighin-stats"><span style="font-size:12px;color:var(--muted)">Next weigh-in: ${(7 - new Date().getDay()) % 7 || 7} day${(7 - new Date().getDay()) % 7 === 1 ? '' : 's'}</span></div>
    </div>`;
    return;
  }

  if (bwData.length === 0) {
    el.innerHTML = `
      <div class="weighin-row">
        <div class="weighin-label">Weigh-In</div>
        <div class="weighin-controls">
          <input type="number" inputmode="decimal" id="weighin-input" class="weighin-input" placeholder="lbs" step="0.1">
          <button class="btn btn-primary weighin-log-btn" onclick="logWeighIn()">Log</button>
        </div>
        <div class="weighin-stats"><span class="weighin-avg" style="opacity:0.5">No weigh-ins yet</span></div>
      </div>`;
    return;
  }

  const todayEntry = bwData.find(e => e.date === today);

  // Calculate 7-day rolling average
  const last7 = bwData.slice(-7);
  const avg7 = last7.length > 0 ? (last7.reduce((s, e) => s + (e.weight || 0), 0) / last7.length).toFixed(1) : '--';

  // Trend: this week vs last week average
  const last14 = bwData.slice(-14);
  const thisWeekEntries = last14.slice(-7);
  const lastWeekEntries = last14.slice(0, Math.max(0, last14.length - 7));
  let trendHtml = '';
  if (thisWeekEntries.length > 0 && lastWeekEntries.length > 0) {
    const thisAvg = thisWeekEntries.reduce((s, e) => s + e.weight, 0) / thisWeekEntries.length;
    const lastAvg = lastWeekEntries.reduce((s, e) => s + e.weight, 0) / lastWeekEntries.length;
    const diff = thisAvg - lastAvg;
    const arrow = diff > 0.2 ? '\u2191' : diff < -0.2 ? '\u2193' : '\u2192';
    const cls = diff > 0.2 ? 'trend-up' : diff < -0.2 ? 'trend-down' : 'trend-flat';
    trendHtml = `<span class="weighin-trend ${cls}">${arrow} ${Math.abs(diff).toFixed(1)} lb</span>`;
  }

  let inputHtml;
  if (todayEntry) {
    inputHtml = `<span class="weighin-today-val">${todayEntry.weight} lb</span>
      <button class="weighin-edit-btn" onclick="editWeighIn()" title="Edit">&#9998;</button>`;
  } else {
    inputHtml = `<input type="number" inputmode="decimal" id="weighin-input" class="weighin-input" placeholder="lbs" step="0.1">
      <button class="btn btn-primary weighin-log-btn" onclick="logWeighIn()">Log</button>`;
  }

  el.innerHTML = `
    <div class="weighin-row">
      <div class="weighin-label">Weigh-In</div>
      <div class="weighin-controls">${inputHtml}</div>
      <div class="weighin-stats">
        <span class="weighin-avg">7d avg: ${avg7} lb</span>
        ${trendHtml}
      </div>
    </div>
    <div class="weighin-chart"><canvas id="weighin-canvas" height="60" style="width:100%"></canvas></div>
  `;

  // Draw sparkline
  drawWeighInSparkline(bwData);
}

function logWeighIn() {
  const input = document.getElementById('weighin-input');
  if (!input) return;
  const weight = parseFloat(input.value);
  if (!weight || weight < 50 || weight > 500) return;

  const today = todayStr();
  // Update cache
  if (!Array.isArray(_bodyweightCache)) _bodyweightCache = [];
  const existing = _bodyweightCache.findIndex(e => e.date === today);
  if (existing >= 0) {
    _bodyweightCache[existing].weight = weight;
  } else {
    _bodyweightCache.push({ date: today, weight });
  }
  apiPost('/api/bodyweight', { date: today, weight });
  renderWeighInBar();
}

function editWeighIn() {
  const bwData = Array.isArray(_bodyweightCache) ? _bodyweightCache : [];
  const today = todayStr();
  const entry = bwData.find(e => e.date === today);
  const current = entry ? entry.weight : '';
  const val = prompt('Edit today\'s weight (lbs):', current);
  if (val !== null) {
    const weight = parseFloat(val);
    if (weight && weight >= 50 && weight <= 500) {
      const idx = _bodyweightCache.findIndex(e => e.date === today);
      if (idx >= 0) {
        _bodyweightCache[idx].weight = weight;
      } else {
        _bodyweightCache.push({ date: today, weight });
      }
      apiPost('/api/bodyweight', { date: today, weight });
      renderWeighInBar();
    }
  }
}

function drawWeighInSparkline(bwData) {
  const canvas = document.getElementById('weighin-canvas');
  if (!canvas || bwData.length < 2) return;
  canvas.width = canvas.parentElement.offsetWidth;
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const last30 = bwData.slice(-30);
  if (last30.length < 2) return;

  const weights = last30.map(e => e.weight);
  const min = Math.min(...weights) - 1;
  const max = Math.max(...weights) + 1;
  const range = max - min || 1;

  const xStep = W / (last30.length - 1);
  const yScale = (v) => H - ((v - min) / range) * (H - 8) - 4;

  // Draw dots
  ctx.fillStyle = '#4ade80';
  last30.forEach((e, i) => {
    ctx.beginPath();
    ctx.arc(i * xStep, yScale(e.weight), 2, 0, Math.PI * 2);
    ctx.fill();
  });

  // Draw rolling average line
  if (last30.length >= 3) {
    ctx.strokeStyle = '#60a5fa';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < last30.length; i++) {
      const windowStart = Math.max(0, i - 6);
      const window = last30.slice(windowStart, i + 1);
      const avg = window.reduce((s, e) => s + e.weight, 0) / window.length;
      const x = i * xStep;
      const y = yScale(avg);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}

// ─── SUPPLEMENT TRACKER (disabled) ──────────────────────────────────────────
function renderSupplementBar() {
  const el = document.getElementById('supplement-bar');
  if (el) el.innerHTML = '';
}

function toggleSupplement(name) {
  if (!_supplementsCache) _supplementsCache = { taken: {}, list: [] };
  if (!_supplementsCache.taken) _supplementsCache.taken = {};
  if (_supplementsCache.taken[name]) {
    delete _supplementsCache.taken[name];
  } else {
    _supplementsCache.taken[name] = true;
  }
  apiPost('/api/supplements', { date: todayStr(), name });
  renderSupplementBar();
}

// ─── WARM-UP SECTION ────────────────────────────────────────────────────────
function renderWarmupSection(dayData) {
  if (!dayData.warmup) return '';
  const wu = dayData.warmup;
  return `<div class="detail-section warmup-section">
    <button class="warmup-toggle open" onclick="document.getElementById('warmup-body').classList.toggle('visible');this.classList.toggle('open')">
      <h3 style="margin:0">Warm-Up${wu.time ? ' - ' + wu.time : ''}</h3>
      <span class="warmup-arrow">\u25BC</span>
    </button>
    <div class="warmup-body visible" id="warmup-body">
      ${(wu.steps || []).map((step, i) => {
        const isWuDone = _warmupCache[currentWeek + '_' + currentDay + '_' + i];
        const hasDuration = !!step.duration;
        return `<div class="warmup-step" id="wu-step-${i}">
        <button class="wu-check${isWuDone ? ' done' : ''}" onclick="toggleWarmup(${currentWeek},${currentDay},${i},this)">${isWuDone ? '&#10003;' : ''}
        </button>
        <div class="wu-step-content">
          <span class="warmup-step-name">${step.name} <a class="ex-video-link" href="https://www.youtube.com/results?search_query=${encodeURIComponent(step.name + ' form short')}&sp=EgIYAQ%253D%253D" target="_blank" rel="noopener" title="Watch form video">&#9654;</a></span>
          ${step.note ? `<div class="warmup-step-note">${step.note}</div>` : ''}
        </div>
        ${hasDuration && !isWuDone ? `<button class="wu-start-btn" onclick="startWuStepTimer(${i},'${step.duration.replace(/'/g, "\\'")}')" id="wu-start-${i}">${step.duration}</button>` : ''}
        ${hasDuration && isWuDone ? `<span class="warmup-step-duration" style="opacity:0.5">${step.duration}</span>` : ''}
        ${!hasDuration ? '' : ''}
        <div class="wu-timer" id="wu-timer-${i}"></div>
      </div>`;
      }).join('')}
    </div>
  </div>`;
}

function toggleWarmup(week, dayIdx, stepIdx, btn) {
  const key = week + '_' + dayIdx + '_' + stepIdx;
  _warmupCache[key] = !_warmupCache[key];
  btn.classList.toggle('done');
  btn.innerHTML = _warmupCache[key] ? '&#10003;' : '';
  apiPost('/api/warmup-completions', { week, day_idx: dayIdx, step_idx: stepIdx });
  // Stop timer for this step if running
  if (_warmupCache[key] && warmupTimerInterval) {
    clearInterval(warmupTimerInterval);
    warmupTimerInterval = null;
    const timerEl = document.getElementById('wu-timer-' + stepIdx);
    if (timerEl) timerEl.innerHTML = '';
  }
  // Hide the start button for completed steps
  const startBtn = document.getElementById('wu-start-' + stepIdx);
  if (startBtn && _warmupCache[key]) {
    startBtn.style.display = 'none';
  }
}

function startWuStepTimer(stepIdx, durationStr) {
  // Stop any existing timer
  if (warmupTimerInterval) clearInterval(warmupTimerInterval);

  const timerEl = document.getElementById('wu-timer-' + stepIdx);
  const startBtn = document.getElementById('wu-start-' + stepIdx);
  if (!timerEl) return;

  // Parse duration
  let seconds = 30;
  const m = durationStr.match(/(\d+)/);
  if (m) {
    seconds = parseInt(m[1]);
    if (durationStr.includes('min')) seconds *= 60;
  }

  // Hide start button, show timer
  if (startBtn) startBtn.style.display = 'none';

  let remaining = seconds;
  timerEl.innerHTML = `<span class="wu-countdown">${formatWuTimer(remaining)}</span>`;

  warmupTimerInterval = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(warmupTimerInterval);
      warmupTimerInterval = null;
      timerEl.innerHTML = `<span class="wu-countdown wu-done">DONE</span>`;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      // Auto-check this step
      const checkBtn = document.querySelector(`#wu-step-${stepIdx} .wu-check`);
      if (checkBtn && !checkBtn.classList.contains('done')) {
        toggleWarmup(currentWeek, currentDay, stepIdx, checkBtn);
      }
      setTimeout(() => { timerEl.innerHTML = ''; }, 2000);
    } else {
      timerEl.innerHTML = `<span class="wu-countdown">${formatWuTimer(remaining)}</span>`;
    }
  }, 1000);
}

function formatWuTimer(sec) {
  if (sec >= 60) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
  return `${sec}s`;
}

function renderPostWorkoutCoach() {
  return ''; // Replaced by popup system

  // Only visible after the run is logged (workout complete)
  const runKey = currentWeek + '_' + currentDay;
  const hasRun = _runLogCache && _runLogCache[runKey];
  if (!hasRun) return '';

  // Show only Erik's last post-workout message
  const coachMsgs = _chatHistory.filter(m =>
    (m.role === 'coach' || m.role === 'assistant') &&
    !(m.text || m.content || '').startsWith('[')
  );
  let bubblesHtml = '';
  if (coachMsgs.length > 0) {
    const last = coachMsgs[coachMsgs.length - 1];
    bubblesHtml = `<div class="coach-top-bubble coach">${escapeHtml(last.text || last.content || '')}</div>`;
  }

  return `<div class="detail-section">
    <div class="coach-top-card">
      <div class="coach-top-label">ERIK</div>
      <div class="coach-top-messages" id="post-workout-messages" style="max-height:300px">${bubblesHtml || '<div style="color:var(--muted);font-size:13px;padding:8px 0">Coach feedback will appear here after you log your run.</div>'}</div>
      <div class="coach-top-input-bar">
        <input type="text" id="post-workout-input" placeholder="Talk to Erik about your workout..." enterkeyhint="send" onkeydown="if(event.key==='Enter')sendPostWorkoutMessage()">
        <button onclick="sendPostWorkoutMessage()">Send</button>
      </div>
    </div>
  </div>`;
}

async function sendPostWorkoutMessage() { return; // Replaced by popup system
  const input = document.getElementById('post-workout-input');
  if (!input) return;
  const text = (input.value || '').trim();
  if (!text) return;
  input.value = '';

  const msgsEl = document.getElementById('post-workout-messages');
  if (msgsEl) {
    msgsEl.innerHTML = `<div class="coach-top-loading"><div class="chat-typing"><span></span><span></span><span></span></div></div>`;
  }

  _chatHistory.push({ role: 'user', text, time: new Date().toISOString() });

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    if (data.response) {
      _chatHistory.push({ role: 'coach', text: data.response, time: data.time || new Date().toISOString() });
      if (msgsEl) msgsEl.innerHTML = `<div class="coach-top-bubble coach">${escapeHtml(data.response)}</div>`;
      renderCoachTop();
    }
  } catch(e) {
    _chatHistory.push({ role: 'coach', text: 'Connection issue. Try again.', time: new Date().toISOString() });
    if (msgsEl) msgsEl.innerHTML = `<div class="coach-top-bubble coach" style="color:var(--muted)">Connection issue. Try again.</div>`;
  }
}

async function saveRunLog() {
  const dist = parseFloat(document.getElementById('run-dist')?.value) || null;
  const hr = parseInt(document.getElementById('run-hr')?.value) || null;
  const elev = parseInt(document.getElementById('run-elev')?.value) || null;

  await apiPost('/api/run-log', {
    week: currentWeek, day_idx: currentDay,
    distance_miles: dist, avg_hr: hr, elevation_ft: elev,
  });

  const key = currentWeek + '_' + currentDay;
  if (!_runLogCache) _runLogCache = {};
  _runLogCache[key] = { distance_miles: dist, avg_hr: hr, elevation_ft: elev };

  showToast('Run logged!', 'success');

  // Re-render to show the post-workout coach section
  renderDetail();

  // Trigger post-workout coach feedback
  const weekData = workoutData[String(currentWeek)];
  const dayData = weekData ? weekData.days[currentDay] : null;
  const workoutName = dayData ? dayData.liftName : 'workout';

  // Build a summary of the workout for the coach
  let exerciseSummary = '';
  if (dayData && dayData.exercises) {
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    for (let i = 0; i < dayData.exercises.length; i++) {
      const ex = dayData.exercises[i];
      const swapKey = currentWeek + '_' + currentDay + '_' + i;
      const name = swaps[swapKey] || ex.name;
      const exData = getExerciseData(name);
      const wt = exData ? exData.current : 0;
      if (wt > 0) exerciseSummary += `${name}: ${wt}lb. `;
    }
  }

  const triggerMsg = `[WORKOUT_COMPLETE] ${workoutName} done. ${exerciseSummary}Run: ${dist || '?'} mi, HR ${hr || '?'}, elev ${elev || '?'} ft. Give post-workout feedback.`;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: triggerMsg }),
    });
    const data = await res.json();
    if (data.response) {
      showCoachPopup(data.response);
    }
  } catch(e) {
    console.error('Post-workout feedback failed:', e);
    if (false) {
      msgsEl.innerHTML = `<div class="coach-top-bubble coach" style="color:var(--muted)">Couldn't reach Erik. Tap below to try again.</div>`;
    }
  }

  // Show session summary after coach popup
  setTimeout(() => showSessionSummary(), 3000);
}

// startWarmupTimer removed — each warm-up step now has its own Start button

// ─── WEEKLY CHECK-IN ────────────────────────────────────────────────────────
function renderCheckinSection(dayData, dayIdx) {
  // Show on last day of week (index 6 = Sunday, or 5 = Saturday)
  if (dayIdx < 5) return '';
  return `<div class="detail-section checkin-form-section">
    <h3>Weekly Check-In</h3>
    <div class="checkin-form" id="checkin-form">
      <div class="checkin-slider-row">
        <label>Energy</label>
        <input type="range" class="checkin-slider" id="checkin-energy" min="1" max="5" value="3">
        <span class="checkin-val" id="checkin-energy-val">3</span>
      </div>
      <div class="checkin-slider-row">
        <label>Sleep Quality</label>
        <input type="range" class="checkin-slider" id="checkin-sleep" min="1" max="5" value="3">
        <span class="checkin-val" id="checkin-sleep-val">3</span>
      </div>
      <div class="checkin-slider-row">
        <label>Soreness</label>
        <input type="range" class="checkin-slider" id="checkin-soreness" min="1" max="5" value="3">
        <span class="checkin-val" id="checkin-soreness-val">3</span>
      </div>
      <div class="checkin-slider-row">
        <label>Adherence</label>
        <input type="range" class="checkin-slider" id="checkin-adherence" min="0" max="100" value="80" step="5">
        <span class="checkin-val" id="checkin-adherence-val">80%</span>
      </div>
      <div class="checkin-slider-row">
        <label>Waist (inches)</label>
        <input type="number" inputmode="decimal" id="checkin-waist" class="checkin-waist-input" placeholder="e.g. 34.5" step="0.25">
      </div>
      <div class="checkin-slider-row">
        <label>Notes</label>
        <textarea id="checkin-notes" class="checkin-notes" placeholder="How did this week go?" rows="2"></textarea>
      </div>
      <button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="submitCheckin()">Submit Check-In</button>
    </div>
  </div>`;
}

function initCheckinSliders() {
  const sliders = ['energy', 'sleep', 'soreness', 'adherence'];
  sliders.forEach(name => {
    const el = document.getElementById('checkin-' + name);
    const valEl = document.getElementById('checkin-' + name + '-val');
    if (el && valEl) {
      el.addEventListener('input', () => {
        valEl.textContent = name === 'adherence' ? el.value + '%' : el.value;
      });
    }
  });
}

function submitCheckin() {
  const energy = parseInt(document.getElementById('checkin-energy').value) || 3;
  const sleep = parseInt(document.getElementById('checkin-sleep').value) || 3;
  const soreness = parseInt(document.getElementById('checkin-soreness').value) || 3;
  const adherence = parseInt(document.getElementById('checkin-adherence').value) || 80;
  const notes = (document.getElementById('checkin-notes').value || '').trim();
  const waist = parseFloat(document.getElementById('checkin-waist').value) || null;

  apiPost('/api/checkins', { week: currentWeek, energy, sleep, soreness, adherence, notes });

  if (waist) {
    apiPost('/api/measurements', { date: todayStr(), waist, notes });
  }

  // Visual feedback
  const form = document.getElementById('checkin-form');
  if (form) {
    form.innerHTML = '<div style="text-align:center;color:var(--accent);padding:1rem;">Check-in submitted!</div>';
  }
}

// ─── PROGRESS DASHBOARD ────────────────────────────────────────────────────
function showProgress() {
  const overlay = document.getElementById('progress-overlay');
  if (!overlay) return;
  overlay.classList.add('visible');
  overlay.innerHTML = '<div class="progress-loading">Loading progress data...</div>';

  fetch('/api/progress')
    .then(r => r.json())
    .then(data => renderProgressDashboard(data))
    .catch(e => {
      overlay.innerHTML = '<div class="progress-loading">Failed to load progress.</div>';
    });
}

function closeProgress() {
  const overlay = document.getElementById('progress-overlay');
  if (overlay) overlay.classList.remove('visible');
}

function renderProgressDashboard(data) {
  const overlay = document.getElementById('progress-overlay');
  if (!overlay) return;

  overlay.innerHTML = `
    <div class="progress-header">
      <h2>Progress Dashboard</h2>
      <button class="progress-share" onclick="shareWeeklySummary()">Share</button>
      <button class="progress-close" onclick="closeProgress()">&times;</button>
    </div>
    <div class="progress-content">
      <div class="progress-chart-section">
        <h3>Body Weight</h3>
        <canvas id="progress-bw-chart" height="180" style="width:100%"></canvas>
      </div>
      <div class="progress-chart-section">
        <h3>Key Lifts</h3>
        <canvas id="progress-lifts-chart" height="180" style="width:100%"></canvas>
      </div>
      <div class="progress-chart-section">
        <h3>Waist Measurement</h3>
        <canvas id="progress-waist-chart" height="120" style="width:100%"></canvas>
      </div>
      <div class="progress-chart-section">
        <h3>Weekly Check-Ins</h3>
        <div id="progress-checkins"></div>
      </div>
    </div>
  `;

  // Draw body weight chart
  if (data.bodyweight && data.bodyweight.length > 1) {
    drawProgressChart('progress-bw-chart', data.bodyweight.map(e => e.weight), data.bodyweight.map(e => e.date), '#4ade80');
  } else {
    const bwCanvas = document.getElementById('progress-bw-chart');
    if (bwCanvas) bwCanvas.parentElement.innerHTML += '<p style="text-align:center;color:#9aaa9d;font-size:0.9rem">Need more data for chart</p>';
  }

  // Draw lifts chart (multiple lines)
  if (data.lifts) {
    drawLiftsChart('progress-lifts-chart', data.lifts);
  } else {
    const liftsCanvas = document.getElementById('progress-lifts-chart');
    if (liftsCanvas) liftsCanvas.parentElement.innerHTML += '<p style="text-align:center;color:#9aaa9d;font-size:0.9rem">Need more data for chart</p>';
  }

  // Draw waist chart
  if (data.measurements && data.measurements.length > 1) {
    drawProgressChart('progress-waist-chart', data.measurements.map(e => e.waist), data.measurements.map(e => e.date), '#f59e0b');
  } else {
    const waistCanvas = document.getElementById('progress-waist-chart');
    if (waistCanvas) waistCanvas.parentElement.innerHTML += '<p style="text-align:center;color:#9aaa9d;font-size:0.9rem">Need more data for chart</p>';
  }

  // Render checkins
  if (data.checkins && data.checkins.length > 0) {
    const el = document.getElementById('progress-checkins');
    el.innerHTML = data.checkins.map(c => `
      <div class="progress-checkin-row">
        <span class="pc-week">Wk ${c.week}</span>
        <span class="pc-score">E:${c.energy} S:${c.sleep} So:${c.soreness} A:${c.adherence}%</span>
      </div>
    `).join('');
  }
}

function drawProgressChart(canvasId, values, labels, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || values.length < 2) return;
  canvas.width = canvas.offsetWidth;
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const pad = 10;
  ctx.clearRect(0, 0, W, H);

  const min = Math.min(...values) - 1;
  const max = Math.max(...values) + 1;
  const range = max - min || 1;
  const xStep = (W - pad * 2) / (values.length - 1);
  const yScale = (v) => H - pad - ((v - min) / range) * (H - pad * 2);

  // Line
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = pad + i * xStep;
    const y = yScale(v);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Dots
  ctx.fillStyle = color;
  values.forEach((v, i) => {
    ctx.beginPath();
    ctx.arc(pad + i * xStep, yScale(v), 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function drawLiftsChart(canvasId, liftsData) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.width = canvas.offsetWidth;
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const pad = 10;
  ctx.clearRect(0, 0, W, H);

  const colors = ['#4ade80', '#60a5fa', '#f59e0b', '#f87171', '#a78bfa', '#94a3b8'];
  let colorIdx = 0;

  // Find global min/max across all lifts
  let allVals = [];
  for (const name in liftsData) {
    const hist = liftsData[name];
    if (Array.isArray(hist)) {
      hist.forEach(e => allVals.push(e.weight || 0));
    }
  }
  if (allVals.length < 2) return;

  const min = Math.min(...allVals) - 5;
  const max = Math.max(...allVals) + 5;
  const range = max - min || 1;
  const yScale = (v) => H - pad - ((v - min) / range) * (H - pad * 2);

  for (const name in liftsData) {
    const hist = liftsData[name];
    if (!Array.isArray(hist) || hist.length < 2) continue;
    const color = colors[colorIdx % colors.length];
    colorIdx++;

    const xStep = (W - pad * 2) / (hist.length - 1);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    hist.forEach((e, i) => {
      const x = pad + i * xStep;
      const y = yScale(e.weight);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

// ─── MILESTONE DETECTION ────────────────────────────────────────────────────
function checkMilestones() {
  const milestones = [];

  // 1. Weight PR: latest weight > max of all previous
  const weights = loadWeights();
  for (const exName in weights) {
    const data = weights[exName];
    if (!data || !data.history || data.history.length < 2) continue;
    const hist = data.history;
    const latest = hist[hist.length - 1].weight;
    const previousMax = Math.max(...hist.slice(0, -1).map(h => h.weight));
    if (latest > previousMax) {
      milestones.push('PR: ' + exName + ' at ' + latest + ' lb!');
    }
  }

  // 2. Body weight milestones: every 2 lbs lost from starting weight
  if (Array.isArray(_bodyweightCache) && _bodyweightCache.length >= 2) {
    const startWeight = _bodyweightCache[0].weight;
    const currentWeight = _bodyweightCache[_bodyweightCache.length - 1].weight;
    const lost = startWeight - currentWeight;
    if (lost >= 2) {
      const milestone = Math.floor(lost / 2) * 2;
      milestones.push(milestone + ' lbs lost from starting weight!');
    }
  }

  // 3. Streak: consecutive days with at least one exercise completion
  if (_completionsCache && _completionsCache.days) {
    const dayKeys = Object.keys(_completionsCache.days).filter(k => _completionsCache.days[k]);
    if (dayKeys.length >= 7) {
      milestones.push(dayKeys.length + '-day workout streak!');
    }
  }

  // 4. Perfect week: all 6 workout days completed in current week
  if (_completionsCache && _completionsCache.days) {
    let completedDays = 0;
    for (let di = 0; di < 6; di++) {
      if (_completionsCache.days[currentWeek + '_' + di]) completedDays++;
    }
    if (completedDays === 6) {
      milestones.push('Perfect week ' + currentWeek + '! All 6 workout days completed.');
    }
  }

  // Show first unseen milestone
  const banner = document.getElementById('milestone-banner');
  if (!banner) return;
  banner.innerHTML = '';

  for (const m of milestones) {
    if (!_milestonesShownThisSession.has(m)) {
      _milestonesShownThisSession.add(m);
      banner.innerHTML = '<div class="milestone-card"><span>' + escapeHtml(m) + '</span><button class="milestone-share-btn" onclick="shareMilestone(\'' + escapeHtml(m).replace(/'/g, "\\'") + '\')">Share</button></div>';
      setTimeout(() => { banner.innerHTML = ''; }, 5000);
      break;
    }
  }
}

// ─── SOCIAL SHARE ─────────────────────────────────────────────────────────
function shareMilestone(text) {
    const shareData = {
        title: '12 Weeks',
        text: text + ' #12Weeks #FitnessJourney',
    };

    if (navigator.share) {
        navigator.share(shareData).catch(() => {});
    } else {
        // Fallback: copy to clipboard
        navigator.clipboard.writeText(shareData.text).then(() => {
            showToast('Copied to clipboard!', 'success');
        }).catch(() => {
            showToast('Could not share', 'error');
        });
    }
}

function shareWeeklySummary() {
    const bw = Array.isArray(_bodyweightCache) ? _bodyweightCache : [];
    const latest = bw.length > 0 ? bw[bw.length - 1].weight : '?';
    const first = bw.length > 0 ? bw[0].weight : '?';
    const diff = (typeof latest === 'number' && typeof first === 'number') ? (first - latest).toFixed(1) : '?';

    const text = `Week ${currentWeek} of 12 complete.\nStarting weight: ${first} lb\nCurrent weight: ${latest} lb\nProgress: ${diff} lb\n#12Weeks`;

    if (navigator.share) {
        navigator.share({ title: '12 Weeks Progress', text }).catch(() => {});
    } else {
        navigator.clipboard.writeText(text).then(() => {
            showToast('Copied to clipboard!', 'success');
        }).catch(() => {});
    }
}

function renderMilestonesForCoach() {
  const milestones = [];
  const weights = loadWeights();
  for (const exName in weights) {
    const data = weights[exName];
    if (!data || !data.history || data.history.length < 2) continue;
    const hist = data.history;
    const latest = hist[hist.length - 1].weight;
    const previousMax = Math.max(...hist.slice(0, -1).map(h => h.weight));
    if (latest > previousMax) {
      milestones.push('PR on ' + exName + ': ' + latest + ' lb');
    }
  }
  if (Array.isArray(_bodyweightCache) && _bodyweightCache.length >= 2) {
    const lost = _bodyweightCache[0].weight - _bodyweightCache[_bodyweightCache.length - 1].weight;
    if (lost >= 2) milestones.push(Math.floor(lost / 2) * 2 + ' lbs lost');
  }
  if (_completionsCache && _completionsCache.days) {
    let completedDays = 0;
    for (let di = 0; di < 6; di++) {
      if (_completionsCache.days[currentWeek + '_' + di]) completedDays++;
    }
    if (completedDays === 6) milestones.push('Perfect week ' + currentWeek);
  }
  return milestones.length > 0 ? 'Recent milestones: ' + milestones.join(', ') + '.' : '';
}

// ─── RENDER ─────────────────────────────────────────────────────────────────
function renderAll() {
  renderWeighInBar();
  renderCheckinSummaryBar();
  renderGarminBar();
  renderSupplementBar();
  renderReadiness();
  renderTravelBanner();
  renderTodayNav();
  renderTodayHero();
  // Legacy renderers (hidden containers, kept for data compatibility)
  renderPhaseNav();
  renderPhaseBanner();
  renderWeekTabs();
  renderDayGrid();
  renderDetail();
  triggerMorningPopup();
  triggerEndOfDayPopup();
  checkMilestones();

  // Auto-select today if no day is currently selected
  if (currentDay === null) {
    const todayIdx = new Date().getDay();
    // JS getDay: 0=Sun, convert to Mon=0 format
    const mappedIdx = todayIdx === 0 ? 6 : todayIdx - 1;
    setDay(mappedIdx);
  }
}

// renderCoachTop — replaced by popup system
function renderCoachTop() { /* no-op — coach uses popups now */ }

async function triggerMorningPopup() {
    // Missed session detection — if after noon and no checkin, mark as missed
    const hour = new Date().getHours();
    if (hour >= 12 && !hasPopupFired('morning') && !_morningCheckinDone) {
        markPopupFired('morning');
        _morningCheckinDone = true; // Don't gate after noon
        apiPost('/api/morning-checkin', {
            date: todayStr(),
            sleep_quality: 0, stress_level: 0, soreness: 0,
            mood: 0, motivation: 0, anxiety: 0,
            notes: '[MISSED] Morning check-in not completed before noon',
            missed: true,
        });
        // Recompute compliance
        fetch('/api/compliance/refresh', { method: 'POST' }).catch(() => {});
        return;
    }
    if (hasPopupFired('morning')) return;
    const today = todayStr();
    const todayCoachMsgs = _chatHistory.filter(m =>
        (m.role === 'coach' || m.role === 'assistant') &&
        ((m.date && m.date === today) || (m.time && m.time.startsWith(today)))
    );
    if (todayCoachMsgs.length > 0) return; // Coach already spoke today

    const weekData = workoutData[String(currentWeek)];
    const todayJsDay = new Date().getDay();
    const todayMon = todayJsDay === 0 ? 6 : todayJsDay - 1;
    const dayData = weekData && weekData.days ? weekData.days[todayMon] : null;
    const workoutName = dayData ? dayData.liftName : 'Rest';
    const timing = dayData && dayData.timing ? dayData.timing[0] : '6:00';
    const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const dayName = dayNames[todayMon];
    const isRest = dayData ? dayData.isRest : false;

    const triggerMsg = `[MORNING_CHECKIN] Today is ${dayName}, ${today}. ${isRest ? 'Rest day.' : `Workout: ${workoutName}. Session starts at ${timing}.`} Week ${currentWeek}. Greet the athlete and state the schedule. 1-2 sentences max — this is a popup, not a conversation.`;

    markPopupFired('morning');

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: triggerMsg }),
        });
        const data = await res.json();
        if (data.response) {
            showCoachPopup(data.response);
            _morningCheckinDone = true;
            // Save morning checkin completion
            apiPost('/api/morning-checkin', {
                date: todayStr(),
                sleep_quality: 5, stress_level: 5, soreness: 5,
                mood: 5, motivation: 5, anxiety: 5,
                notes: 'Auto-completed via morning popup'
            });
        }
    } catch(e) {
        console.error('Morning popup failed:', e);
    }
}

async function triggerEndOfDayPopup() {
    const hour = new Date().getHours();
    if (hour < 20) return; // Only after 8pm
    if (hasPopupFired('eod')) return;

    // Check if workout was done today
    const todayJsDay = new Date().getDay();
    const todayMon = todayJsDay === 0 ? 6 : todayJsDay - 1;
    const dayKey = `${currentWeek}_${todayMon}`;
    const dayDone = _completionsCache && _completionsCache.days && _completionsCache.days[dayKey];
    if (!dayDone) return; // Only fire if workout is complete

    markPopupFired('eod');

    const weekData = workoutData[String(currentWeek)];
    const dayData = weekData && weekData.days ? weekData.days[todayMon] : null;
    const workoutName = dayData ? dayData.liftName : 'workout';
    const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const tomorrowMon = (todayMon + 1) % 7;
    const tomorrowData = weekData && weekData.days ? weekData.days[tomorrowMon] : null;
    const tomorrowName = tomorrowData ? tomorrowData.liftName : 'Rest';

    const triggerMsg = `[END_OF_DAY] Today's workout (${workoutName}) is done. Tomorrow is ${dayNames[tomorrowMon]}: ${tomorrowName}. Give a brief end-of-day summary. 1-2 sentences. This is a popup — no questions.`;

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: triggerMsg }),
        });
        const data = await res.json();
        if (data.response) {
            showCoachPopup(data.response);
        }
    } catch(e) {}
}

function renderInlineCoach() {
  // DEPRECATED — coach is now at the top via renderCoachTop()
  return;
  const el = document.getElementById('coach-inline');
  if (!el) return;

  // Find the last coach message
  const coachMsgs = _chatHistory.filter(m => m.role === 'assistant' || m.role === 'coach');
  const lastMsg = coachMsgs.length > 0 ? coachMsgs[coachMsgs.length - 1] : null;

  if (!lastMsg) {
    el.innerHTML = `<div class="coach-inline-empty">
      <div class="coach-inline-label">Coach Erik</div>
      <div class="coach-inline-text">This is where you'll talk to Erik. He sees your sleep, lifts, and check-ins. Ask him anything.</div>
      <button class="btn btn-primary" style="margin-top:8px" onclick="toggleChatOverlay()">Start a Conversation</button>
    </div>`;
    return;
  }

  const text = escapeHtml(lastMsg.text || lastMsg.content || '');
  const milestoneStr = renderMilestonesForCoach();
  el.innerHTML = `<div class="coach-inline-card">
    <div class="coach-inline-label">Coach Erik</div>
    ${milestoneStr ? '<div class="coach-inline-milestones" style="font-size:13px;color:var(--accent);margin-bottom:6px">' + escapeHtml(milestoneStr) + '</div>' : ''}
    <div class="coach-inline-text">"${text}"</div>
    <div class="coach-quick-replies">
      <button onclick="quickCoachReply('How should I modify today\\'s workout?')">Modify today?</button>
      <button onclick="quickCoachReply('I\\'m struggling today.')">I'm struggling</button>
      <button onclick="quickCoachReply('I crushed it today!')">I crushed it</button>
    </div>
  </div>`;
}

function quickCoachReply(msg) {
  toggleChatOverlay();
  setTimeout(() => {
    const input = document.getElementById('chat-overlay-input');
    if (input) {
      input.value = msg;
      sendChatMessage('chat-overlay-input', 'chat-overlay-messages');
    }
  }, 300);
}

function renderGarminBar() {
  const el = document.getElementById('garmin-bar');
  if (el) el.innerHTML = '';
  return;
  // Garmin disabled — original code below
  if (!garminConnected) {

  let metricsHtml = '<div class="garmin-header"><span class="gh-label">Garmin Connected</span><button class="garmin-disconnect" onclick="garminLogout()">Disconnect</button></div>';
  metricsHtml += '<div class="garmin-metrics">';

  if (garminData) {
    const hrv = garminData.hrv;
    if (hrv && hrv.lastNight != null) {
      const color = getMetricColor('hrv', readinessData);
      metricsHtml += metric('HRV', hrv.lastNight, `avg ${hrv.weeklyAvg || '?'}`, color);
    }
    const sleep = garminData.sleep;
    if (sleep) {
      const color = getMetricColor('sleep', readinessData);
      const score = sleep.score != null ? sleep.score : '?';
      metricsHtml += metric('Sleep', score, `${sleep.durationHours || '?'}h`, color);
    }
    const bb = garminData.bodyBattery;
    if (bb && bb.current != null) {
      const color = getMetricColor('bodyBattery', readinessData);
      metricsHtml += metric('Battery', bb.current, '', color);
    }
    const tr = garminData.trainingReadiness;
    if (tr && tr.score != null) {
      const color = getMetricColor('trainingReadiness', readinessData);
      metricsHtml += metric('Ready', tr.score, tr.level || '', color);
    }
    const stress = garminData.stress;
    if (stress && stress.overall != null) {
      const color = getMetricColor('stress', readinessData);
      metricsHtml += metric('Stress', stress.overall, '', color);
    }
  } else {
    metricsHtml += '<div style="color:var(--dim);font-size:11px;padding:4px;">Loading Garmin data...</div>';
  }

  metricsHtml += '</div>';
  el.innerHTML = metricsHtml;
}

function metric(label, value, sub, color) {
  return `<div class="garmin-metric">
    <div class="gm-label">${label}</div>
    <div class="gm-value" style="color:${color}">${value}</div>
    ${sub ? `<div class="gm-sub">${sub}</div>` : ''}
  </div>`;
}

function getMetricColor(key, rd) {
  if (!rd || !rd.metrics || rd.metrics[key] == null) return 'var(--text)';
  const score = rd.metrics[key];
  if (score >= 65) return 'var(--risk-low)';
  if (score >= 40) return 'var(--risk-moderate)';
  return 'var(--risk-high)';
}

function renderReadiness() {
  const el = document.getElementById('readiness-alert');
  el.className = 'readiness-alert';

  if (!readinessData || readinessData.risk_level === 'unknown') {
    return;
  }

  el.classList.add('visible', `risk-${readinessData.risk_level}`);
  let flagsHtml = '';
  if (readinessData.flags && readinessData.flags.length) {
    flagsHtml = `<div class="readiness-flags">${readinessData.flags.join(' &middot; ')}</div>`;
  }

  el.innerHTML = `<div class="readiness-inner">
    <span class="readiness-score">${readinessData.score}/100</span>
    ${readinessData.suggestion}
    ${flagsHtml}
  </div>`;
}

// ─── UNIFIED TODAY NAV ────────────────────────────────────────────────────
function renderTodayNav() {
  const el = document.getElementById('today-nav');
  if (!el) return;
  const weekData = workoutData[String(currentWeek)];
  if (!weekData || !weekData.days) return;
  const days = weekData.days;

  const todayJsDay = new Date().getDay(); // 0=Sun
  const todayMon = todayJsDay === 0 ? 6 : todayJsDay - 1; // convert to Mon=0

  const dayBtns = days.map((d, i) => {
    const isToday = i === todayMon;
    const isActive = i === currentDay;
    const done = isDayDone(currentWeek, i);
    return `<button class="tn-day${isActive ? ' active' : ''}${isToday ? ' today' : ''}${done ? ' done' : ''}${d.isRest ? ' rest' : ''}" onclick="setDay(${i})">
      <span class="tn-day-abbr">${d.day}</span>
      ${done ? '<span class="tn-check">&#10003;</span>' : ''}
    </button>`;
  }).join('');

  const info = weekData.phaseInfo || {};
  const isDeload = currentWeek === 4 || currentWeek === 8 || currentWeek === 12;

  el.innerHTML = `
    <div class="tn-week-row">
      <button class="tn-week-arrow" onclick="setWeek(Math.max(1, currentWeek-1))">&lsaquo;</button>
      <span class="tn-week-label">Week ${currentWeek}${isDeload ? ' &middot; Deload' : ''} &middot; Phase ${weekData.phase}</span>${_complianceCache && _complianceCache.grade ? `<span class="grade-badge grade-${_getGradeClass(_complianceCache.grade)}" onclick="showComplianceBreakdown()">${_complianceCache.grade}</span>` : ''}
      <button class="tn-week-arrow" onclick="setWeek(Math.min(12, currentWeek+1))">&rsaquo;</button>
    </div>
    <div class="tn-days">${dayBtns}</div>
    <div class="tn-focus">${info.focus || ''} &middot; ${info.deficit || ''}</div>
  `;
}

function renderTodayHero() {
  const el = document.getElementById('today-hero');
  if (!el) return;
  const weekData = workoutData[String(currentWeek)];
  if (!weekData || !weekData.days) { el.innerHTML = ''; return; }

  // If no day selected, don't show hero (auto-select will fix this)
  if (currentDay === null) { el.innerHTML = ''; return; }

  const d = weekData.days[currentDay];
  if (!d) { el.innerHTML = ''; return; }

  const todayJsDay = new Date().getDay();
  const todayMon = todayJsDay === 0 ? 6 : todayJsDay - 1;
  const isToday = currentDay === todayMon;
  const dayLabel = isToday ? 'Today' : d.day;

  if (d.isRest) {
    el.innerHTML = `<div class="th-card th-rest">
      <div class="th-label">${dayLabel}</div>
      <div class="th-title">Rest Day</div>
      <div class="th-sub">Streak mile only &middot; Recovery &middot; Hydrate</div>
    </div>`;
    return;
  }

  const runClass = 'run-' + d.run.type;
  const done = isDayDone(currentWeek, currentDay);
  const exCount = (d.exercises || []).length;
  const exDone = (d.exercises || []).filter((_, i) => isExDone(currentWeek, currentDay, i)).length;

  el.innerHTML = `<div class="th-card${done ? ' th-done' : ''}">
    <div class="th-top">
      <div>
        <div class="th-label">${dayLabel}</div>
        <div class="th-title">${d.liftName}</div>
      </div>
      <div class="th-progress-ring">${exDone}/${exCount}</div>
    </div>
    <div class="th-run">
      <span class="run-pill ${runClass}">${d.run.label} &middot; ${d.run.time}</span>
    </div>
  </div>`;
}

function renderPhaseNav() {
  const el = document.getElementById('phase-nav');
  el.innerHTML = [1,2,3].map(p =>
    `<button class="phase-btn${p===currentPhase?' active':''}" onclick="setPhase(${p})">
      Phase ${p} &middot; Wks ${p===1?'1-4':p===2?'5-8':'9-12'}
    </button>`
  ).join('') + `<button class="phase-btn progress-btn" onclick="showProgress()">Progress</button>`;
}

function renderPhaseBanner() {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData) return;
  const info = weekData.phaseInfo;
  if (!info) return;
  const el = document.getElementById('phase-banner');
  el.innerHTML = `Focus: <span>${info.focus}</span> Lifting: <span>${info.lifting}</span> Deficit: <span>${info.deficit}</span> Protein: <span>${info.protein}</span>`;
}

function renderWeekTabs() {
  const weeks = currentPhase === 1 ? [1,2,3,4] : currentPhase === 2 ? [5,6,7,8] : [9,10,11,12];
  const el = document.getElementById('week-tabs');
  el.innerHTML = weeks.map(w => {
    const isDeload = w === 4 || w === 8 || w === 12;
    return `<button class="week-tab${isDeload?' deload':''}${w===currentWeek?' active':''}" onclick="setWeek(${w})">
      Wk ${w}${isDeload ? ' Deload' : ''}
    </button>`;
  }).join('');
}

function renderDayGrid() {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData) return;
  const days = weekData.days;
  if (!days) return;
  const el = document.getElementById('day-grid');

  el.innerHTML = days.map((d, i) => {
    const isRest = d.isRest;
    const done = isDayDone(currentWeek, i);
    const runClass = `run-${d.run.type}`;

    return `<div class="day-card${isRest?' rest':''}${done?' completed':''}${currentDay===i?' active':''}" onclick="setDay(${i})">
      <div class="day-card-left">
        <div class="day-abbr">${d.day}</div>
      </div>
      <div class="day-card-center">
        <div class="day-lift-label">${d.liftName}</div>
        <div class="day-run-label">
          <span class="run-pill ${runClass}">${d.run.label} &middot; ${d.run.time}</span>
        </div>
      </div>
      <div class="day-card-right" onclick="toggleDay(${currentWeek},${i},event)">
        ${done ? '&#10003;' : '&#9675;'}
      </div>
    </div>`;
  }).join('');
}

async function renderDetail() {
  const panel = document.getElementById('detail-panel');
  if (currentDay === null) {
    panel.classList.remove('visible');
    return;
  }

  try {

  // Morning check-in gate — lock until done
  const todayJsDay = new Date().getDay();
  const todayMonIdx = todayJsDay === 0 ? 6 : todayJsDay - 1;
  if (currentDay === todayMonIdx && !_morningCheckinDone) {
      panel.innerHTML = `<div class="detail-inner" style="padding:2rem;text-align:center">
          <div style="font-size:48px;margin-bottom:1rem">&#x1F512;</div>
          <h3 style="color:var(--text);margin-bottom:0.5rem">Morning Check-In Required</h3>
          <div style="color:var(--muted);font-size:14px;margin-bottom:1.5rem">Complete your morning session with Erik to unlock today's tracking.</div>
          <button class="btn btn-primary" onclick="toggleChatOverlay()">Talk to Erik</button>
      </div>`;
      panel.classList.add('visible');
      return;
  }

  const weekData = workoutData[String(currentWeek)];
  if (!weekData) return;
  const d = weekData.days[currentDay];
  if (!d) return;
  const runClass = d.run ? `run-${d.run.type}` : 'run-z2';
  const isTraveling = _stateCache && _stateCache.traveling;

  // Load per-set data from DB for this day (if not already loaded)
  const setDayKey = `${currentWeek}_${currentDay}`;
  if (!_setCache._loadedDay || _setCache._loadedDay !== setDayKey) {
    try {
      const setRes = await fetch(`/api/sets/${currentWeek}/${currentDay}`);
      if (setRes.ok) {
        const setData = await setRes.json();
        // Convert DB format to _setCache format
        // DB: { "1_0_Barbell Bench Press": { "0": {weight, reps, done}, "1": {...} } }
        // Cache: { "1_0_0_0": {done, weight, reps}, "1_0_0_1": {...} }
        const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
        const displayExercises = d.exercises || [];
        for (let i = 0; i < displayExercises.length; i++) {
          const swapKey = currentWeek + '_' + currentDay + '_' + i;
          const exName = swaps[swapKey] || displayExercises[i].name;
          const dbKey = `${currentWeek}_${currentDay}_${exName}`;
          if (setData[dbKey]) {
            for (const [setNum, setInfo] of Object.entries(setData[dbKey])) {
              if (setInfo.done) {
                _setCache[`${currentWeek}_${currentDay}_${i}_${setNum}`] = {
                  done: true, weight: setInfo.weight, reps: setInfo.reps,
                };
              }
            }
          }
        }
      }
      _setCache._loadedDay = setDayKey;
    } catch(e) {
      _setCache._loadedDay = setDayKey; // Mark loaded even on failure to prevent retry loops
    }
  }

  // If traveling, try to load travel workout
  if (isTraveling && !d._travelLoaded) {
    fetch('/api/travel/workout?day=' + encodeURIComponent(d.day))
      .then(r => r.json())
      .then(tw => {
        d._travelWorkout = tw;
        d._travelLoaded = true;
        renderDetail();
      })
      .catch(() => { d._travelLoaded = true; renderDetail(); });
    // Show loading placeholder
    panel.innerHTML = `<div class="detail-inner"><div class="detail-header"><div class="detail-title">Loading travel workout...</div></div></div>`;
    panel.classList.add('visible');
    return;
  }

  const travelExercises = isTraveling && d._travelWorkout && d._travelWorkout.exercises ? d._travelWorkout.exercises : null;
  const bwMode = sessionStorage.getItem('bw_only_mode') === 'true';
  const bwExercises = bwMode ? JSON.parse(sessionStorage.getItem('bw_exercises') || 'null') : null;
  const displayExercises = bwExercises || travelExercises || d.exercises || [];

  // Bodyweight-only toggle
  const bwOnly = sessionStorage.getItem('bw_only_mode') === 'true';
  const bwToggleHtml = `<div class="bw-toggle-bar">
    <label class="bw-toggle-label">
      <input type="checkbox" ${bwOnly ? 'checked' : ''} onchange="toggleBodyweightMode(this.checked)">
      <span>Bodyweight Only</span>
    </label>
  </div>`;

  // Exercise rows with weight tracking and RPE
  if (!_exerciseSwapsLoaded) {
    try {
      const swapRes = await fetch('/api/exercise-swaps');
      if (swapRes.ok) {
        const swapData = await swapRes.json();
        sessionStorage.setItem('exercise_swaps', JSON.stringify(swapData));
        _exerciseSwapsLoaded = true;
      }
    } catch(e) {}
  }
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  const exRows = displayExercises.map((ex, i) => {
    const swapKey = currentWeek + '_' + currentDay + '_' + i;
    const displayName = swaps[swapKey] || ex.name;
    const isSwapped = !!swaps[swapKey];
    const done = isExDone(currentWeek, currentDay, i);
    let suggestion = getWeightForExercise(displayName, currentWeek);
    let lastWt = getLastWeight(displayName);
    // Fallback: if swapped exercise has no history, use original exercise's weight
    if (isSwapped && suggestion.weight == null) {
      suggestion = getWeightForExercise(ex.name, currentWeek);
      if (!lastWt) lastWt = getLastWeight(ex.name);
    }
    const weightVal = suggestion.weight != null ? suggestion.weight : '';

    const exData = getExerciseData(displayName);
    const lastEntry = exData && exData.history && exData.history.length > 0 ? exData.history[exData.history.length - 1] : null;
    const hasRPE = lastEntry && lastEntry.week === currentWeek && lastEntry.day === currentDay && lastEntry.rpe;
    const lastRPE = hasRPE ? lastEntry.rpe : null;

    let rpeHtml = '';
    if (done && !hasRPE) {
      rpeHtml = `<div class="rpe-feedback">
        <span class="rpe-label">How was it?</span>
        <button class="rpe-btn rpe-easy" onclick="submitRPE(${currentWeek},${currentDay},${i},'${displayName.replace(/'/g, "\\'")}','too_easy')">Too Easy</button>
        <button class="rpe-btn rpe-right" onclick="submitRPE(${currentWeek},${currentDay},${i},'${displayName.replace(/'/g, "\\'")}','just_right')">Just Right</button>
        <button class="rpe-btn rpe-hard" onclick="submitRPE(${currentWeek},${currentDay},${i},'${displayName.replace(/'/g, "\\'")}','too_hard')">Too Hard</button>
      </div>`;
    } else if (hasRPE) {
      const rpeLabels = { too_easy: 'Too Easy', just_right: 'Just Right', too_hard: 'Too Hard' };
      const rpeCls = { too_easy: 'rpe-easy', just_right: 'rpe-right', too_hard: 'rpe-hard' };
      rpeHtml = `<div class="rpe-feedback">
        <span class="rpe-label">Felt:</span>
        <button class="rpe-btn ${rpeCls[lastRPE] || 'rpe-right'} selected" disabled>${rpeLabels[lastRPE]}</button>
      </div>`;
    }

    // Parse sets format: "4x10" → { count: 4, reps: "10" }
    const setsMatch = (ex.sets || '').match(/^(\d+)x(.+)/);
    const setCount = setsMatch ? parseInt(setsMatch[1]) : 1;
    const targetReps = setsMatch ? setsMatch[2] : ex.sets;
    const restSeconds = parseRestSeconds(ex.rest);
    const escapedName = displayName.replace(/'/g, "\\'");

    // Build per-set rows — carry weight forward from earlier sets
    let setRowsHtml = '';
    let carryWeight = weightVal; // Start with suggestion, override with actual logged weights
    for (let s = 0; s < setCount; s++) {
      const setKey = `${currentWeek}_${currentDay}_${i}_${s}`;
      const setData = _setCache && _setCache[setKey];
      const setDone = !!(setData && setData.done);
      // Priority: 1) this set's saved weight, 2) previous set's weight, 3) suggestion
      const setWeight = setData && setData.weight ? setData.weight : carryWeight;
      const setReps = setData && setData.reps ? setData.reps : '';
      // Carry this set's weight forward to next set
      if (setData && setData.weight) carryWeight = setData.weight;
      setRowsHtml += `<div class="set-row${setDone ? ' set-done' : ''}" ${!setDone ? `onclick="enterExerciseFocus(${i})"` : ''} style="${!setDone ? 'cursor:pointer' : ''}">
        <button class="set-check${setDone ? ' done' : ''}" onclick="toggleSet(${currentWeek},${currentDay},${i},${s},${restSeconds},'${escapedName}',this)">
          ${setDone ? '&#10003;' : ''}
        </button>
        <span class="set-label">Set ${s + 1}</span>
        <input class="weight-input set-wt" type="number" inputmode="decimal" id="wt-${currentWeek}-${currentDay}-${i}-${s}" value="${setWeight}" placeholder="lb" onblur="saveSetField(${currentWeek},${currentDay},${i},${s},'${escapedName}')">
        <span class="set-x">&times;</span>
        <input class="reps-input set-reps" type="number" inputmode="numeric" id="reps-${currentWeek}-${currentDay}-${i}-${s}" value="${setReps}" placeholder="${targetReps}" min="0" max="100" onblur="saveSetField(${currentWeek},${currentDay},${i},${s},'${escapedName}')">
      </div>`;
    }

    return `<div class="exercise-block">
      <div class="exercise-header">
        <div class="ex-info">
          <div class="ex-name">${displayName}${isSwapped ? '<span class="exercise-swapped">(swapped)</span>' : ''} <a class="ex-video-link" href="https://www.youtube.com/results?search_query=${encodeURIComponent(displayName + ' form short')}&sp=EgIYAQ%253D%253D" target="_blank" rel="noopener" title="Watch form video">&#9654;</a> <span class="ex-swap-icon" onclick="showExerciseSwap(${i},'${escapedName}',event)" title="Swap exercise">&#128260;</span></div>
          ${ex.note ? `<div class="ex-note">${ex.note}</div>` : ''}
        </div>
        <div class="ex-sets">${ex.sets}${ex.rest ? ' · ' + ex.rest + ' rest' : ''}${!done ? ` <button class="ex-start-btn" onclick="enterExerciseFocus(${i})">START</button>` : ''}${suggestion.reason && suggestion.reason !== 'estimated' ? `<span class="ex-prog-indicator" title="${escapeHtml(suggestion.reason)}">${suggestion.reason.includes('↑') || suggestion.reason.includes('+') ? '↑' : suggestion.reason.includes('↓') || suggestion.reason.includes('-') ? '↓' : suggestion.reason.includes('Deload') ? '○' : '—'}</span>` : ''}</div>
      </div>
      ${lastWt != null ? `<div class="ex-last-weight">Last: ${lastWt} lb${suggestion.reason && suggestion.reason !== 'estimated' ? ' · ' + suggestion.reason : ''}</div>` : (suggestion.reason ? `<div class="ex-last-weight">${suggestion.reason}</div>` : '')}
      <div class="set-rows">${setRowsHtml}</div>
      <div id="rest-timer-${i}" class="rest-timer"></div>
      ${rpeHtml ? `<div>${rpeHtml}</div>` : ''}
      <div id="swap-container-${i}"></div>
    </div>`;
  }).join('');

  // Timing rows
  const timingRows = [];
  if (d.timing) {
    for (let i = 0; i < d.timing.length; i += 2) {
      timingRows.push(`<div class="timing-row">
        <div class="timing-time">${d.timing[i]}</div>
        <div class="timing-desc">${d.timing[i+1]}</div>
      </div>`);
    }
  }

  // Garmin Day Stats
  let garminStatsHtml = '';
  if (garminConnected && garminData) {
    garminStatsHtml += '<div class="garmin-day-stats">';
    const hrv = garminData.hrv;
    if (hrv && hrv.lastNight != null) {
      const c = getMetricColor('hrv', readinessData);
      garminStatsHtml += `<div class="gds-card"><div class="gds-label">HRV</div><div class="gds-value" style="color:${c}">${hrv.lastNight}</div><div class="gds-sub">avg ${hrv.weeklyAvg || '?'}</div></div>`;
    }
    const sleep = garminData.sleep;
    if (sleep) {
      const c = getMetricColor('sleep', readinessData);
      garminStatsHtml += `<div class="gds-card"><div class="gds-label">Sleep</div><div class="gds-value" style="color:${c}">${sleep.score != null ? sleep.score : '?'}</div><div class="gds-sub">${sleep.durationHours || '?'}h</div></div>`;
    }
    const bb = garminData.bodyBattery;
    if (bb && bb.current != null) {
      const c = getMetricColor('bodyBattery', readinessData);
      garminStatsHtml += `<div class="gds-card"><div class="gds-label">Battery</div><div class="gds-value" style="color:${c}">${bb.current}</div></div>`;
    }
    const tr = garminData.trainingReadiness;
    if (tr && tr.score != null) {
      const c = getMetricColor('trainingReadiness', readinessData);
      garminStatsHtml += `<div class="gds-card"><div class="gds-label">Ready</div><div class="gds-value" style="color:${c}">${tr.score}</div><div class="gds-sub">${tr.level || ''}</div></div>`;
    }
    const stress = garminData.stress;
    if (stress && stress.overall != null) {
      const c = getMetricColor('stress', readinessData);
      garminStatsHtml += `<div class="gds-card"><div class="gds-label">Stress</div><div class="gds-value" style="color:${c}">${stress.overall}</div></div>`;
    }
    garminStatsHtml += '</div>';
  } else if (!garminConnected) {
    garminStatsHtml = '<div class="garmin-nudge">Connect Garmin for personalized readiness data</div>';
  }

  // Daily Goals
  let goalsItems = '';
  if (displayExercises.length > 0) {
    goalsItems += `<div class="dg-item">${isTraveling ? 'Complete all bodyweight exercises.' : 'Complete all exercises. Rest times matter - don\'t rush heavy sets.'}</div>`;
  }
  goalsItems += `<div class="dg-item">Run: ${d.run.label} &middot; ${d.run.time}${d.run.detail ? ' &middot; ' + d.run.detail : ''}</div>`;

  let adjustmentHtml = '';
  if (readinessData && (readinessData.risk_level === 'moderate' || readinessData.risk_level === 'high') && readinessData.suggestion) {
    adjustmentHtml = `<div class="adjustment-banner risk-${readinessData.risk_level}">
      <div class="ab-label">Adjustment Suggested</div>
      ${readinessData.suggestion}
    </div>`;
  }

  const dailyGoalsHtml = `<div class="daily-goals">
    <div class="dg-title">Daily Goals</div>
    ${goalsItems}
    ${adjustmentHtml}
  </div>`;

  // AI Coach chat
  let chatMessagesHtml = renderInlineChat();

  // Weight summary dashboard
  let weightSummaryHtml = '';
  const summaryLifts = ['Barbell Bench Press', 'Barbell Back Squat', 'Conventional Deadlift', 'DB Overhead Press', 'Barbell Bent-Over Row', 'Barbell Hip Thrust'];
  const weights = loadWeights();
  const hasSomeWeights = summaryLifts.some(n => weights[n] && weights[n].current);
  if (hasSomeWeights) {
    let wsRows = '';
    for (const name of summaryLifts) {
      const suggestion = getWeightForExercise(name, currentWeek);
      const wt = suggestion.weight || (weights[name] && weights[name].current);
      if (!wt) continue;
      const trend = getWeightTrend(name);
      const trendIcon = trend === 'up' ? '<span class="ws-trend-up">\u2191</span>' :
                        trend === 'down' ? '<span class="ws-trend-down">\u2193</span>' :
                        '<span class="ws-trend-same">\u2192</span>';
      const shortName = name.replace('Barbell ', '').replace('Conventional ', '');
      // Estimate 1RM from last logged weight × reps
      const exData = getExerciseData(name);
      let est1rm = '';
      if (exData && exData.history && exData.history.length > 0) {
        const last = exData.history[exData.history.length - 1];
        const lastWt = last.weight || wt;
        const lastReps = last.reps_completed || 10;
        const oneRM = estimate1RM(lastWt, lastReps);
        if (oneRM > 0) est1rm = `<span class="ws-1rm">${oneRM} 1RM</span>`;
      }
      wsRows += `<div class="ws-row"><span class="ws-name">${shortName}</span><span class="ws-val">${wt} lb ${est1rm} ${trendIcon}</span></div>`;
    }
    weightSummaryHtml = `<div class="weight-summary" id="weight-summary">
      <button class="weight-summary-toggle" onclick="document.getElementById('weight-summary').classList.toggle('open')">
        Working Weights <span class="ws-arrow">\u25BC</span>
      </button>
      <div class="weight-summary-body">${wsRows}</div>
    </div>`;
  }

  // Build Sunday section (async)
  let sundaySectionHtml = '';
  if (isSunday(d)) {
    sundaySectionHtml = await renderSundaySection(d);
  }

  panel.innerHTML = `<div class="detail-inner">
    <div class="detail-header">
      <div class="detail-title">Week ${currentWeek} &middot; ${d.day} &mdash; ${d.liftName}</div>
      <div class="detail-meta">
        ${!d.isRest || travelExercises ? `<span class="meta-chip" style="background:var(--lift-bg);border-color:var(--lift-border);color:var(--lift)">${isTraveling ? 'Travel' : 'Lift'} &middot; ${displayExercises.length} exercises</span>` : ''}
        <span class="meta-chip ${runClass}">${d.run.label} &middot; ${d.run.time}</span>
      </div>
    </div>
    ${d.notes ? `<div class="detail-section"><div class="notes-box"><strong>Coach note:</strong> ${d.notes}</div></div>` : ''}
    ${sundaySectionHtml}
    ${d.timing ? `<div class="detail-section">
      <h3>Session Timing</h3>
      ${timingRows.join('')}
    </div>` : ''}
    <div class="detail-section">
      ${weightSummaryHtml}
      <h3>Today's Status</h3>
      ${garminStatsHtml}
      ${dailyGoalsHtml}
    </div>
    ${renderWarmupSection(d)}
    ${displayExercises.length > 0 ? `
    <div class="detail-section">
      <h3>${isTraveling ? 'Travel Workout' : 'Exercises'}</h3>
      ${bwToggleHtml}
      ${exRows}
    </div>` : ''}
    <div class="detail-section">
      <h3>Run</h3>
      <div class="run-detail-box">
        <div class="rdl">Type</div>
        <div class="rdt"><span class="run-pill ${runClass}">${d.run.label} &middot; ${d.run.time}</span></div>
        <div class="rdd" style="margin-top:8px">${d.run.detail}</div>
      </div>
      ${(() => { const runKey = currentWeek + '_' + currentDay; const existingRun = _runLogCache ? _runLogCache[runKey] : null;
        if (existingRun && (existingRun.distance_miles || existingRun.avg_hr || existingRun.elevation_ft)) {
          return `<div class="run-log-form" style="margin-top:10px">
            <div style="display:flex;gap:12px;align-items:center;padding:8px 0;color:var(--accent);font-family:'DM Mono',monospace;font-size:13px">
              <span>&#10003; Logged</span>
              ${existingRun.distance_miles ? `<span>${existingRun.distance_miles} mi</span>` : ''}
              ${existingRun.avg_hr ? `<span>HR ${existingRun.avg_hr}</span>` : ''}
              ${existingRun.elevation_ft ? `<span>${existingRun.elevation_ft} ft</span>` : ''}
            </div>
            <button class="btn btn-secondary" style="width:100%;font-size:13px;padding:6px" onclick="document.getElementById('run-edit-form').style.display='block';this.style.display='none'">Edit</button>
            <div id="run-edit-form" style="display:none;margin-top:8px">
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
                <div><label style="font-size:12px;color:var(--muted)">Distance (mi)</label><input type="number" inputmode="decimal" step="0.1" id="run-dist" class="weight-input" style="width:100%" value="${existingRun.distance_miles || ''}" placeholder="mi"></div>
                <div><label style="font-size:12px;color:var(--muted)">Avg HR</label><input type="number" inputmode="numeric" id="run-hr" class="weight-input" style="width:100%" value="${existingRun.avg_hr || ''}" placeholder="bpm"></div>
                <div><label style="font-size:12px;color:var(--muted)">Elevation (ft)</label><input type="number" inputmode="numeric" id="run-elev" class="weight-input" style="width:100%" value="${existingRun.elevation_ft || ''}" placeholder="ft"></div>
              </div>
              <button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="saveRunLog()">Update Run</button>
            </div>
          </div>`;
        }
        return `<div class="run-log-form" style="margin-top:10px">
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
          <div><label style="font-size:12px;color:var(--muted)">Distance (mi)</label><input type="number" inputmode="decimal" step="0.1" id="run-dist" class="weight-input" style="width:100%" placeholder="mi"></div>
          <div><label style="font-size:12px;color:var(--muted)">Avg HR</label><input type="number" inputmode="numeric" id="run-hr" class="weight-input" style="width:100%" placeholder="bpm"></div>
          <div><label style="font-size:12px;color:var(--muted)">Elevation (ft)</label><input type="number" inputmode="numeric" id="run-elev" class="weight-input" style="width:100%" placeholder="ft"></div>
        </div>
        <button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="saveRunLog()">Log Run</button>
      </div>`; })()}
    </div>
    ${renderMealSection(d)}
    ${renderCheckinSection(d, currentDay)}
    ${renderPostWorkoutCoach()}
  </div>`;

  panel.classList.add('visible');

  // Init sliders if check-in is present
  initCheckinSliders();

  // Load Sunday photo previews asynchronously
  if (isSunday(d)) {
    loadSundayPhotoPreviews();
  }

  } catch(e) {
    console.error('renderDetail crashed:', e);
    panel.innerHTML = `<div class="detail-inner" style="padding:1rem;color:var(--muted)">Error loading day details. Try refreshing.</div>`;
    panel.classList.add('visible');
  }
}

// ─── COACHING CHAT (old client-side logic removed — now uses /api/chat) ────

// Old generateCoachResponse removed — AI chat now handled by /api/chat

// ─── SUNDAY MEASUREMENT & PHOTOS ─────────────────────────────────────────────
let _photosCache = null;
let _photoImagesCache = {};
let _sundayCompareOpen = false;

function isSunday(dayData) {
  return dayData && dayData.day === 'Sun';
}

function getTodayBodyweight() {
  if (!Array.isArray(_bodyweightCache)) return '';
  const today = todayStr();
  const entry = _bodyweightCache.find(e => e.date === today);
  return entry ? entry.weight : '';
}

async function loadPhotos() {
  if (_photosCache !== null) return _photosCache;
  try {
    const res = await fetch('/api/photos');
    _photosCache = await res.json();
  } catch (e) {
    console.error('Failed to load photos:', e);
    _photosCache = [];
  }
  return _photosCache;
}

async function loadPhotoImage(photoId) {
  if (_photoImagesCache[photoId]) return _photoImagesCache[photoId];
  try {
    const res = await fetch(`/api/photos/${photoId}/image`);
    const data = await res.json();
    _photoImagesCache[photoId] = data.photo_data;
    return data.photo_data;
  } catch (e) {
    console.error('Failed to load photo image:', e);
    return null;
  }
}

function compressImage(file, maxWidth, quality) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = function(e) {
      const img = new Image();
      img.onload = function() {
        const canvas = document.createElement('canvas');
        let w = img.width;
        let h = img.height;
        if (w > maxWidth) {
          h = Math.round(h * maxWidth / w);
          w = maxWidth;
        }
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        const dataUrl = canvas.toDataURL('image/jpeg', quality);
        resolve(dataUrl);
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function handlePhotoCapture(pose, inputEl) {
  const file = inputEl.files[0];
  if (!file) return;

  const slotEl = document.getElementById(`photo-slot-${pose}`);
  if (!slotEl) return;

  // Show loading in the slot
  slotEl.innerHTML = `<div class="photo-loading"><div class="spinner"></div><div>Compressing...</div></div>`;

  try {
    const base64 = await compressImage(file, 800, 0.7);

    // Show preview immediately
    slotEl.innerHTML = `
      <div class="photo-preview">
        <img src="${base64}" alt="${pose}">
        <button class="photo-retake" onclick="retakePhoto('${pose}')">Retake</button>
      </div>
      <div class="photo-loading" id="photo-analysis-loading-${pose}">
        <div class="spinner"></div>
        <div>Your AI Coach is analyzing your photo...</div>
      </div>`;

    // Upload to server
    const res = await fetch('/api/photos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_data: base64, pose: pose })
    });
    const result = await res.json();

    // Cache the result
    _photosCache = null; // invalidate cache so next load is fresh
    _photoImagesCache[result.id] = base64;

    // Show analysis
    const loadingEl = document.getElementById(`photo-analysis-loading-${pose}`);
    if (loadingEl) {
      if (result.analysis) {
        loadingEl.outerHTML = `<div class="photo-analysis">
          <div class="photo-analysis-label">AI Coach Analysis</div>
          ${result.analysis}
        </div>`;
      } else {
        loadingEl.remove();
      }
    }
  } catch (e) {
    console.error('Photo upload failed:', e);
    slotEl.innerHTML = `<div style="color:var(--run-hiit);font-size:14px;padding:10px">Upload failed. Tap to retry.</div>`;
  }
}

function retakePhoto(pose) {
  const slotEl = document.getElementById(`photo-slot-${pose}`);
  if (!slotEl) return;
  slotEl.innerHTML = renderPhotoUploadButton(pose);
}

function renderPhotoUploadButton(pose) {
  return `<div class="photo-upload-btn" onclick="this.querySelector('input').click()">
    <div class="photo-icon">&#128247;</div>
    <div>Tap to capture</div>
    <input type="file" accept="image/*" capture="environment" onchange="handlePhotoCapture('${pose}', this)">
  </div>`;
}

async function saveMeasurements() {
  const weightEl = document.getElementById('sunday-weight');
  const waistEl = document.getElementById('sunday-waist');
  const notesEl = document.getElementById('sunday-measure-notes');
  const btn = document.getElementById('btn-save-measurements');

  const body = {
    date: todayStr(),
    weight: weightEl ? parseFloat(weightEl.value) || null : null,
    waist: waistEl ? parseFloat(waistEl.value) || null : null,
    notes: notesEl ? notesEl.value : ''
  };

  btn.textContent = 'Saving...';
  btn.disabled = true;

  try {
    await fetch('/api/measurements', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    btn.textContent = 'Saved!';
    btn.classList.add('saved');
    setTimeout(() => {
      btn.textContent = 'Save Measurements';
      btn.disabled = false;
      btn.classList.remove('saved');
    }, 2000);
  } catch (e) {
    console.error('Save measurements failed:', e);
    btn.textContent = 'Failed - Retry';
    btn.disabled = false;
  }
}

function togglePhotoCompare() {
  _sundayCompareOpen = !_sundayCompareOpen;
  const btn = document.getElementById('photo-compare-toggle-btn');
  const grid = document.getElementById('photo-compare-grid');
  if (btn) btn.classList.toggle('active', _sundayCompareOpen);
  if (grid) grid.classList.toggle('visible', _sundayCompareOpen);
}

async function renderSundaySection(dayData) {
  if (!isSunday(dayData)) return '';

  const bw = getTodayBodyweight();
  const photos = await loadPhotos();
  const currentWeekNum = currentWeek;

  // Get this week's and last week's photos
  const thisWeekPhotos = photos.filter(p => p.week === currentWeekNum);
  const lastWeekPhotos = photos.filter(p => p.week === currentWeekNum - 1);

  const poses = ['front', 'side', 'back'];

  // Build photo slots
  let photoSlotsHtml = '';
  for (const pose of poses) {
    const existing = thisWeekPhotos.find(p => p.pose === pose);
    let slotContent;
    if (existing && existing.has_photo) {
      // We'll load the image async and fill it in
      slotContent = `<div class="photo-loading"><div class="spinner"></div></div>`;
    } else {
      slotContent = renderPhotoUploadButton(pose);
    }
    let analysisHtml = '';
    if (existing && existing.analysis) {
      analysisHtml = `<div class="photo-analysis">
        <div class="photo-analysis-label">AI Coach Analysis</div>
        ${existing.analysis}
      </div>`;
    }
    photoSlotsHtml += `<div class="photo-slot">
      <div class="photo-slot-label">${pose}</div>
      <div id="photo-slot-${pose}">${slotContent}</div>
      ${analysisHtml}
    </div>`;
  }

  // Build comparison section
  let compareHtml = '';
  if (lastWeekPhotos.length > 0) {
    compareHtml = `<div class="photo-compare">
      <button class="photo-compare-toggle${_sundayCompareOpen ? ' active' : ''}" id="photo-compare-toggle-btn" onclick="togglePhotoCompare()">
        Compare with Last Week
      </button>
      <div class="photo-compare-grid${_sundayCompareOpen ? ' visible' : ''}" id="photo-compare-grid">
      </div>
    </div>`;
  }

  const html = `<div class="sunday-section">
    <h3>Weekly Measurement &amp; Photos</h3>
    <div class="sunday-subtitle">Sunday is reflection day. Track your progress and let your AI Coach assess your physique changes.</div>

    <div class="measurement-form">
      <label>
        <span>Body Weight (lb)</span>
        <input type="number" id="sunday-weight" inputmode="decimal" step="0.1" placeholder="e.g. 185.5" value="${bw}">
      </label>
      <label>
        <span>Waist (inches)</span>
        <input type="number" id="sunday-waist" inputmode="decimal" step="0.1" placeholder="e.g. 34.0">
      </label>
      <button class="btn-save-measurements" id="btn-save-measurements" onclick="saveMeasurements()">Save Measurements</button>
    </div>

    <h3 style="margin-top:20px">Progress Photos</h3>
    <div class="photo-grid">
      ${photoSlotsHtml}
    </div>
    ${compareHtml}
  </div>`;

  return html;
}

async function loadSundayPhotoPreviews() {
  const photos = await loadPhotos();
  const thisWeekPhotos = photos.filter(p => p.week === currentWeek);
  const lastWeekPhotos = photos.filter(p => p.week === currentWeek - 1);
  const poses = ['front', 'side', 'back'];

  // Load this week's existing photos into their slots
  for (const pose of poses) {
    const existing = thisWeekPhotos.find(p => p.pose === pose);
    if (existing && existing.has_photo) {
      const imgData = await loadPhotoImage(existing.id);
      const slotEl = document.getElementById(`photo-slot-${pose}`);
      if (slotEl && imgData) {
        slotEl.innerHTML = `<div class="photo-preview">
          <img src="${imgData}" alt="${pose}">
          <button class="photo-retake" onclick="retakePhoto('${pose}')">Retake</button>
        </div>`;
      }
    }
  }

  // Load comparison images if compare grid exists
  const compareGrid = document.getElementById('photo-compare-grid');
  if (compareGrid && lastWeekPhotos.length > 0) {
    let compareHtml = '';
    for (const pose of poses) {
      const lastPhoto = lastWeekPhotos.find(p => p.pose === pose);
      const thisPhoto = thisWeekPhotos.find(p => p.pose === pose);
      if (lastPhoto && lastPhoto.has_photo) {
        const lastImg = await loadPhotoImage(lastPhoto.id);
        let thisImg = null;
        if (thisPhoto && thisPhoto.has_photo) {
          thisImg = await loadPhotoImage(thisPhoto.id);
        }
        if (lastImg) {
          compareHtml += `<div class="photo-compare-col">
            <div class="compare-label">Wk ${currentWeek - 1} ${pose}</div>
            <img src="${lastImg}" alt="Week ${currentWeek - 1} ${pose}">
          </div>`;
          if (thisImg) {
            compareHtml += `<div class="photo-compare-col">
              <div class="compare-label">Wk ${currentWeek} ${pose}</div>
              <img src="${thisImg}" alt="Week ${currentWeek} ${pose}">
            </div>`;
          }
        }
      }
    }
    if (compareHtml) {
      compareGrid.innerHTML = compareHtml;
    } else {
      compareGrid.innerHTML = '<div style="grid-column:1/-1;color:var(--muted);font-size:14px;padding:10px">No comparison photos available yet.</div>';
    }
  }
}

// ─── SERVICE WORKER REGISTRATION ──────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js', { scope: '/' })
      .then(reg => {
        console.log('SW registered:', reg.scope);
        initPushNotifications(reg);
      })
      .catch(err => console.warn('SW registration failed:', err));
  });
}

// ─── PUSH NOTIFICATIONS ──────────────────────────────────────────────────
async function initPushNotifications(reg) {
  try {
    const res = await fetch('/api/push/vapid-key');
    if (!res.ok) return;
    const { publicKey } = await res.json();
    if (!publicKey) return;

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return;

    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });

    await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription: sub.toJSON() }),
    });
    console.log('Push subscription registered');
  } catch (e) {
    console.warn('Push setup failed:', e);
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

// ─── COMPLIANCE GRADE ─────────────────────────────────────────────────────────

function _getGradeClass(grade) {
    if (grade.startsWith('A')) return 'a';
    if (grade.startsWith('B')) return 'b';
    if (grade.startsWith('C')) return 'c';
    if (grade === 'D') return 'd';
    return 'f';
}

async function showComplianceBreakdown() {
    // Refresh compliance data
    try {
        const res = await fetch('/api/compliance/refresh', { method: 'POST' });
        _complianceCache = await res.json();
    } catch(e) {}

    if (!_complianceCache) return;
    const c = _complianceCache;
    const b = c.breakdown || {};

    const overlay = document.getElementById('morning-checkin-overlay');
    overlay.innerHTML = `<div class="morning-checkin-overlay">
        <div class="morning-checkin-card" style="max-width:400px">
            <button style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1" onclick="document.getElementById('morning-checkin-overlay').innerHTML=''">&times;</button>
            <div style="text-align:center;margin-bottom:1.5rem">
                <span class="grade-badge-large grade-${_getGradeClass(c.grade)}">${c.grade}</span>
                <div style="font-family:'DM Mono',monospace;font-size:14px;color:var(--muted);margin-top:8px">${c.score} / 100</div>
                ${c.streak > 0 ? `<div style="font-size:12px;color:var(--accent);margin-top:4px">${c.streak} day streak</div>` : ''}
            </div>
            <div style="margin-bottom:1.5rem">
                ${_renderProgressBar('Morning Check-ins', b.checkins || 0)}
                ${_renderProgressBar('Food Tracking', b.food_timing || 0)}
                ${_renderProgressBar('Workout Completion', b.workout_timing || 0)}
            </div>
            <div style="font-size:13px;color:var(--muted);text-align:center;padding-top:1rem;border-top:1px solid var(--border)">
                ${_getImprovementTip(c.grade, b)}
            </div>
        </div>
    </div>`;
}

function _renderProgressBar(label, score) {
    const color = score >= 80 ? 'var(--accent)' : score >= 60 ? 'var(--amber,#f59e0b)' : 'var(--red,#ef4444)';
    return `<div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
            <span style="color:var(--text)">${label}</span>
            <span style="color:var(--muted);font-family:'DM Mono',monospace">${score}%</span>
        </div>
        <div style="height:6px;background:var(--surface2);border-radius:3px;overflow:hidden">
            <div style="height:100%;width:${score}%;background:${color};border-radius:3px;transition:width 0.3s"></div>
        </div>
    </div>`;
}

function _getImprovementTip(grade, breakdown) {
    if (grade.startsWith('A')) return 'Excellence is the standard. Maintain it.';
    const b = breakdown || {};
    const weakest = Object.entries(b).sort((a, b) => a[1] - b[1])[0];
    if (!weakest) return 'Stay consistent.';
    const tips = {
        checkins: 'Complete your morning check-in every day.',
        food_timing: 'Log all your meals consistently.',
        workout_timing: 'Show up for every scheduled workout.',
    };
    return tips[weakest[0]] || 'Stay consistent.';
}

// ─── SESSION SUMMARY OVERLAY ──────────────────────────────────────────────
async function showSessionSummary() {
    try {
        const res = await fetch(`/api/session-summary/${currentWeek}/${currentDay}`);
        if (!res.ok) return;
        const data = await res.json();

        const overlay = document.getElementById('morning-checkin-overlay');

        let exerciseHtml = '';
        for (const [name, info] of Object.entries(data.exercises || {})) {
            const tw = info.target_weight;
            const sets = info.sets || [];
            const avgWeight = sets.length > 0 ? Math.round(sets.reduce((s, x) => s + (x.weight || 0), 0) / sets.length) : 0;
            const avgReps = sets.length > 0 ? Math.round(sets.reduce((s, x) => s + (x.reps || 0), 0) / sets.length) : 0;
            const direction = sets.find(s => s.direction)?.direction;

            let deviation = '';
            if (direction === 'increased_weight') deviation = '<span style="color:var(--accent)">↑ Went heavier</span>';
            else if (direction === 'decreased_weight') deviation = '<span style="color:#f59e0b">↓ Reduced weight</span>';
            else if (direction === 'decreased_reps') deviation = '<span style="color:#f59e0b">↓ Fewer reps</span>';
            else if (direction === 'as_prescribed') deviation = '<span style="color:var(--accent)">✓ As prescribed</span>';

            exerciseHtml += `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)">
                <div>
                    <div style="font-size:14px;color:var(--text)">${escapeHtml(name)}</div>
                    <div style="font-size:12px;color:var(--muted);font-family:'DM Mono',monospace">${sets.length} sets · ${avgWeight} lb × ${avgReps}</div>
                    ${deviation ? `<div style="font-size:11px;margin-top:2px">${deviation}</div>` : ''}
                </div>
                <div style="font-size:12px;color:var(--muted);font-family:'DM Mono',monospace;text-align:right">
                    ${tw ? `Target: ${Math.round(tw)} lb` : ''}
                </div>
            </div>`;
        }

        let muscleHtml = '';
        for (const [mg, info] of Object.entries(data.muscle_scores || {})) {
            const pct = Math.round(Math.min((info.score || 1) * 50, 100));
            const color = info.strength === 'strong' ? 'var(--accent)' : (info.strength === 'weak' || info.weak) ? '#f59e0b' : info.strength === 'very_weak' ? '#ef4444' : 'var(--muted)';
            muscleHtml += `<div style="margin-bottom:6px">
                <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px">
                    <span style="color:var(--text);text-transform:capitalize">${mg.replace(/_/g, ' ')}</span>
                    <span style="color:var(--muted)">${info.strength}${info.weak ? ' ⚑' : ''}</span>
                </div>
                <div style="height:4px;background:var(--surface2);border-radius:2px;overflow:hidden">
                    <div style="height:100%;width:${pct}%;background:${color};border-radius:2px"></div>
                </div>
            </div>`;
        }

        overlay.innerHTML = `<div class="morning-checkin-overlay">
            <div class="morning-checkin-card" style="max-width:500px">
                <button style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1" onclick="document.getElementById('morning-checkin-overlay').innerHTML=''">&times;</button>
                <h2 style="margin-bottom:4px">Session Complete</h2>
                ${data.compliance != null ? `<div style="font-family:'DM Mono',monospace;font-size:14px;color:var(--accent);margin-bottom:1rem">${Math.round(data.compliance)}% compliance</div>` : ''}
                <div style="margin-bottom:1.5rem">${exerciseHtml || '<div style="color:var(--muted)">No exercises logged.</div>'}</div>
                ${muscleHtml ? `<div style="margin-bottom:1rem"><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--accent);margin-bottom:8px">Muscle Groups</div>${muscleHtml}</div>` : ''}
                ${data.summary ? `<div style="font-size:13px;color:var(--muted);border-top:1px solid var(--border);padding-top:0.75rem">${escapeHtml(data.summary)}</div>` : ''}
            </div>
        </div>`;
    } catch(e) {
        console.error('Session summary failed:', e);
    }
}

// ─── EXERCISE FOCUS MODE ───────────────────────────────────────────────────
async function enterExerciseFocus(exIdx) {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData || currentDay === null) return;
  const dayData = weekData.days[currentDay];
  if (!dayData || !dayData.exercises || !dayData.exercises[exIdx]) return;

  const ex = dayData.exercises[exIdx];
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  const swapKey = currentWeek + '_' + currentDay + '_' + exIdx;
  const displayName = swaps[swapKey] || ex.name;

  const setsMatch = (ex.sets || '').match(/^(\d+)x(.+)/);
  _focusSetCount = setsMatch ? parseInt(setsMatch[1]) : 1;
  _focusTargetReps = setsMatch ? setsMatch[2] : ex.sets;
  _focusRestSec = parseRestSeconds(ex.rest);
  _focusExName = displayName;
  _focusExIdx = exIdx;

  let suggestion = getWeightForExercise(displayName, currentWeek);
  _focusLastWeight = getLastWeight(displayName);
  // Fallback: swapped exercise with no history → use original
  if (suggestion.weight == null && swaps[swapKey]) {
    suggestion = getWeightForExercise(ex.name, currentWeek);
    if (!_focusLastWeight) _focusLastWeight = getLastWeight(ex.name);
  }
  _focusWeightVal = suggestion.weight != null ? suggestion.weight : '';

  // Fetch adaptive targets from training engine
  try {
      const targetRes = await fetch('/api/targets/' + encodeURIComponent(displayName));
      if (targetRes.ok) {
          const targets = await targetRes.json();
          if (targets.target_weight) {
              _focusWeightVal = roundWeight(targets.target_weight, displayName);
          }
          window._focusTargetReps = targets.target_reps || _focusTargetReps;
          window._focusReason = targets.adjustment_reason || '';
          window._focusIndicator = targets.progression_indicator || 'hold';
      }
  } catch(e) {}

  // Carry forward from earlier completed sets in this session
  for (let s = 0; s < (_focusSetCount || 4); s++) {
    const sd = _setCache[`${currentWeek}_${currentDay}_${exIdx}_${s}`];
    if (sd && sd.weight) _focusWeightVal = sd.weight;
  }

  // Find first uncompleted set
  _focusSetIdx = 0;
  for (let s = 0; s < _focusSetCount; s++) {
    const key = `${currentWeek}_${currentDay}_${exIdx}_${s}`;
    if (!_setCache[key] || !_setCache[key].done) {
      _focusSetIdx = s;
      break;
    }
    if (s === _focusSetCount - 1) _focusSetIdx = _focusSetCount; // All done
  }

  // Push history state for back button
  history.pushState({ focus: true }, '');

  renderExerciseFocus();
}

function renderExerciseFocus() {
  const el = document.getElementById('exercise-focus');
  if (!el) return;

  // Check if all sets done → show RPE
  if (_focusSetIdx >= _focusSetCount) {
    showFocusRPE();
    return;
  }

  // Get saved weight for this set (if previously entered)
  const setKey = `${currentWeek}_${currentDay}_${_focusExIdx}_${_focusSetIdx}`;
  const setData = _setCache && _setCache[setKey];
  const wt = setData && setData.weight ? setData.weight : _focusWeightVal;
  const rp = setData && setData.reps ? setData.reps : '';

  el.innerHTML = `
    <button class="focus-back" onclick="exitExerciseFocus()">&#8249;</button>
    <div class="focus-content">
      <div class="focus-ex-name">${escapeHtml(_focusExName)}</div>
      <div class="focus-set-counter">Set ${_focusSetIdx + 1} of ${_focusSetCount}</div>
      ${_focusLastWeight ? `<div class="focus-last-perf">Last: ${_focusLastWeight} lb</div>` : '<div style="height:20px"></div>'}
      ${window._focusReason ? `<div class="focus-reason"><span class="focus-indicator focus-${window._focusIndicator || 'hold'}">${{'up':'↑','hold':'—','deload':'○','weak':'⚑','down':'↓'}[window._focusIndicator] || '—'}</span> ${escapeHtml(window._focusReason)}</div>` : ''}
      <div class="focus-input-group">
        <input class="focus-input" type="number" inputmode="decimal" id="focus-wt" value="${wt}" placeholder="lb" autofocus>
        <span class="focus-input-label">lb</span>
      </div>
      <div class="focus-x">&times;</div>
      <div class="focus-input-group">
        <input class="focus-input" type="number" inputmode="numeric" id="focus-reps" value="${rp}" placeholder="${_focusTargetReps}">
        <span class="focus-input-label">reps</span>
      </div>
      <button class="focus-log-btn" onclick="logFocusSet()">LOG SET</button>
    </div>`;
  el.classList.add('visible');
}

function logFocusSet() {
  const wtInput = document.getElementById('focus-wt');
  const repsInput = document.getElementById('focus-reps');
  const weight = wtInput ? parseFloat(wtInput.value) || 0 : 0;
  const repsTyped = repsInput ? parseInt(repsInput.value) : 0;
  const reps = repsTyped || parseInt(_focusTargetReps) || 0;

  const key = `${currentWeek}_${currentDay}_${_focusExIdx}_${_focusSetIdx}`;
  _setCache[key] = { done: true, weight, reps };

  // Carry weight forward to next set
  if (weight > 0) _focusWeightVal = weight;

  // Save to DB
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  const isSwapped = !!swaps[`${currentWeek}_${currentDay}_${_focusExIdx}`];
  apiPost('/api/sets', {
    exercise: _focusExName, week: currentWeek, day_idx: currentDay,
    set_number: _focusSetIdx, weight, reps, done: true, exercise_swapped: isSwapped
  });

  // Update weight cache
  if (weight > 0) {
    if (!_weightsCache) _weightsCache = {};
    if (!_weightsCache[_focusExName]) _weightsCache[_focusExName] = { current: 0, history: [] };
    _weightsCache[_focusExName].current = weight;
  }

  // Check if all sets done
  let allDone = true;
  for (let s = 0; s < _focusSetCount; s++) {
    if (!_setCache[`${currentWeek}_${currentDay}_${_focusExIdx}_${s}`]) {
      allDone = false; break;
    }
  }

  if (allDone) {
    // Mark exercise complete
    if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
    if (!_completionsCache.exercises) _completionsCache.exercises = {};
    _completionsCache.exercises[`${currentWeek}_${currentDay}_${_focusExIdx}`] = true;
    apiPost('/api/completions/exercise', { week: currentWeek, day_idx: currentDay, exercise_idx: _focusExIdx });

    // Show rest timer then RPE
    _focusSetIdx = _focusSetCount;
    if (_focusRestSec > 0) {
      showFocusRestTimer(_focusRestSec, true); // true = show RPE after
    } else {
      showFocusRPE();
    }
  } else {
    // Advance to next set after rest
    _focusSetIdx++;
    if (_focusRestSec > 0) {
      showFocusRestTimer(_focusRestSec, false); // false = show next set after
    } else {
      renderExerciseFocus();
    }
  }
}

function showFocusRestTimer(seconds, showRpeAfter) {
  const el = document.getElementById('exercise-focus');
  if (!el) return;

  let remaining = seconds;

  function render() {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    const timeStr = m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;

    el.innerHTML = `
      <div class="focus-content">
        <div class="focus-timer-label">REST</div>
        <div class="focus-timer-display">${timeStr}</div>
        <button class="focus-skip-btn" onclick="skipFocusRest()">Skip Rest &rarr;</button>
      </div>`;
  }

  render();

  if (_focusTimerInterval) clearInterval(_focusTimerInterval);
  window._focusShowRpeAfter = showRpeAfter;

  _focusTimerInterval = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(_focusTimerInterval);
      _focusTimerInterval = null;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);

      // Show GO briefly
      el.innerHTML = `<div class="focus-content"><div class="focus-timer-display focus-timer-done" style="font-size:72px">GO</div></div>`;
      setTimeout(() => {
        if (window._focusShowRpeAfter) {
          showFocusRPE();
        } else {
          renderExerciseFocus();
        }
      }, 1000);
    } else {
      render();
    }
  }, 1000);
}

function skipFocusRest() {
  if (_focusTimerInterval) clearInterval(_focusTimerInterval);
  _focusTimerInterval = null;
  if (window._focusShowRpeAfter) {
    showFocusRPE();
  } else {
    renderExerciseFocus();
  }
}

function showFocusRPE() {
  const el = document.getElementById('exercise-focus');
  if (!el) return;

  const escapedName = _focusExName.replace(/'/g, "\\'");
  el.innerHTML = `
    <div class="focus-content">
      <div class="focus-ex-name">${escapeHtml(_focusExName)}</div>
      <div class="focus-done-label">COMPLETE</div>
      <div class="focus-rpe-title">How did it feel?</div>
      <div class="focus-rpe-btns">
        <button class="rpe-btn rpe-easy" onclick="submitFocusRPE('too_easy')">Too Easy</button>
        <button class="rpe-btn rpe-right" onclick="submitFocusRPE('just_right')">Just Right</button>
        <button class="rpe-btn rpe-hard" onclick="submitFocusRPE('too_hard')">Too Hard</button>
      </div>
    </div>`;
}

function submitFocusRPE(rpe) {
  // Read all set weights to get the working weight
  let weight = 0;
  let totalReps = 0;
  for (let s = 0; s < _focusSetCount; s++) {
    const setData = _setCache[`${currentWeek}_${currentDay}_${_focusExIdx}_${s}`];
    if (setData) {
      if (setData.weight > 0) weight = setData.weight;
      totalReps += setData.reps || 0;
    }
  }

  const weekData = workoutData[String(currentWeek)];
  const setsLabel = weekData ? weekData.days[currentDay].exercises[_focusExIdx].sets : '';
  const rpeScore = rpe === 'too_easy' ? 5 : rpe === 'just_right' ? 7 : 9;
  recordWeight(_focusExName, weight, setsLabel, rpe, currentWeek, currentDay, rpeScore, totalReps || null);

  exitExerciseFocus();
}

function exitExerciseFocus() {
  const el = document.getElementById('exercise-focus');
  if (el) {
    el.classList.remove('visible');
    el.innerHTML = '';
  }
  if (_focusTimerInterval) {
    clearInterval(_focusTimerInterval);
    _focusTimerInterval = null;
  }
  _focusExIdx = null;
  _focusSetIdx = null;

  // Re-render session overview
  renderDetail();
}

// Handle browser back button
window.addEventListener('popstate', (e) => {
  const el = document.getElementById('exercise-focus');
  if (el && el.classList.contains('visible')) {
    exitExerciseFocus();
  }
});
