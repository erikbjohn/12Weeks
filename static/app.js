// ─── DATA CACHES ────────────────────────────────────────────────────────────
let _weightsCache = null;
let _completionsCache = null;
let _mealsCache = {};
let _stateCache = null;
let _supplementsCache = null;
let _bodyweightCache = null;
let _morningCheckinCache = null;
let _chatHistory = [];

// ─── STATE ──────────────────────────────────────────────────────────────────
let workoutData = {};
let currentPhase = 1;
let currentWeek = 1;
let currentDay = null;
let garminConnected = false;
let garminData = null;
let readinessData = null;
let warmupTimerInterval = null;
let _chatOverlayOpen = false;
let _mealDetailExpanded = false;
let _milestonesShownThisSession = new Set();

const WEEK_TO_PHASE = {1:1,2:1,3:1,4:1,5:2,6:2,7:2,8:2,9:3,10:3,11:3,12:3};

// ─── API HELPERS ────────────────────────────────────────────────────────────
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

function apiPost(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
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
  return new Date().toISOString().slice(0, 10);
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
  apiPost('/api/meals', { date: key, eaten: data.eaten || [], adjustments: data.adjustments || {}, fasting: data.fasting || false });
}

function isMealEaten(mealIdx) {
  const data = loadMealData();
  return (data.eaten || []).includes(mealIdx);
}

function toggleMealEaten(mealIdx) {
  const data = loadMealData();
  if (!data.eaten) data.eaten = [];
  const idx = data.eaten.indexOf(mealIdx);
  if (idx >= 0) {
    data.eaten.splice(idx, 1);
  } else {
    data.eaten.push(mealIdx);
  }
  saveMealData(data);
  renderDetail();
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

  const isRestDay = dayData.day === 'Sun' || (dayData.isRest && dayData.mealType === 'rest');
  const fasting = isFastingToday();

  let fastToggleHtml = '';
  if (isRestDay) {
    fastToggleHtml = `<div class="fast-toggle">
      <button class="${!fasting ? 'active' : ''}" onclick="toggleFasting(false)">16:8 Eating</button>
      <button class="${fasting ? 'active' : ''}" onclick="toggleFasting(true)">24h Fast</button>
    </div>`;
  }

  const activePlan = (isRestDay && fasting) ? (window._mealPlansCache || {}).fast_day || plan : plan;

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

    const showAdjust = !(isRestDay && fasting);
    const foodRows = meal.foods.map(f => {
      const adjCal = Math.round((f.cal || 0) * multiplier);
      const adjBtns = showAdjust ? `<span class="meal-food-adjust-inline">
        <button onclick="adjustMealPortion(${idx}, -0.25)" title="Less">-</button>
        <button onclick="adjustMealPortion(${idx}, 0.25)" title="More">+</button>
      </span>` : '';
      return `<div class="meal-food-row">
        <span class="meal-food-name">${f.item}</span>
        <span class="meal-food-portion">${f.portion}${multiplier !== 1 ? '<span class="meal-multiplier">x' + multiplier.toFixed(2).replace(/\.?0+$/, '') + '</span>' : ''}</span>
        <span class="meal-food-portion">${adjCal}cal</span>
        ${adjBtns}
      </div>`;
    }).join('');

    mealsHtml += `<div class="meal-item${meal.optional ? ' optional' : ''}">
      <button class="meal-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx})">
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

  const totalsHtml = `<div class="meal-totals">
    <div class="meal-totals-title">Daily Totals${fasting && isRestDay ? ' (Fasting)' : ''}</div>
    <div class="macro-bar-row">
      <span class="macro-bar-label mbl-cal">Cal</span>
      <div class="macro-bar"><div class="macro-bar-fill mbf-cal" style="width:${pctCal}%"></div></div>
      <span class="macro-bar-nums">${totalEaten.cal} / ${target.cal}</span>
    </div>
    <div class="macro-bar-row">
      <span class="macro-bar-label mbl-p">P</span>
      <div class="macro-bar"><div class="macro-bar-fill mbf-p" style="width:${pctP}%"></div></div>
      <span class="macro-bar-nums">${totalEaten.protein}g / ${target.protein}g</span>
    </div>
    <div class="macro-bar-row">
      <span class="macro-bar-label mbl-c">C</span>
      <div class="macro-bar"><div class="macro-bar-fill mbf-c" style="width:${pctC}%"></div></div>
      <span class="macro-bar-nums">${totalEaten.carbs}g / ${target.carbs}g</span>
    </div>
    <div class="macro-bar-row">
      <span class="macro-bar-label mbl-f">F</span>
      <div class="macro-bar"><div class="macro-bar-fill mbf-f" style="width:${pctF}%"></div></div>
      <span class="macro-bar-nums">${totalEaten.fat}g / ${target.fat}g</span>
    </div>
  </div>`;

  // Compact row: meal name checkboxes
  let compactChecks = '';
  meals.forEach((meal, idx) => {
    const eaten = isMealEaten(idx);
    compactChecks += `<button class="meal-compact-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx})">${eaten ? '&#10003; ' : ''}${meal.name}</button>`;
  });

  return `<div class="detail-section">
    <h3>Meal Plan &middot; ${activePlan.label || ''}</h3>
    ${fastToggleHtml}
    ${activePlan.note ? '<div class="meal-plan-note">' + activePlan.note + '</div>' : ''}
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

function recordWeight(exName, weight, setsLabel, rpe, week, dayIdx) {
  if (!_weightsCache) _weightsCache = {};
  if (!_weightsCache[exName]) {
    _weightsCache[exName] = { current: weight, history: [] };
  }
  _weightsCache[exName].current = weight;
  _weightsCache[exName].history.push({
    weight: weight,
    reps: setsLabel,
    rpe: rpe,
    date: todayStr(),
    week: week,
    day: dayIdx,
  });
  apiPost('/api/weights', { exercise: exName, weight, sets_label: setsLabel, rpe, week, day_idx: dayIdx });
}

function getLastRPEs(exName, count) {
  const data = getExerciseData(exName);
  if (!data || !data.history || data.history.length === 0) return [];
  return data.history.slice(-count).map(h => h.rpe);
}

function getSuggestedWeight(exName, currentWeekNum) {
  const data = getExerciseData(exName);
  if (!data) return { weight: null, reason: '' };

  const currentWt = data.current || 0;
  const history = data.history || [];

  if (isDeloadWeek(currentWeekNum)) {
    return { weight: Math.round(currentWt * 0.6), reason: 'deload: 60%' };
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
  if (suggestion.weight !== null) return suggestion;
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
    const [intakeRes, conRes, paRes, goalRes, foodRes] = await Promise.all([
      fetch('/api/psych-intake/status'),
      fetch('/api/constraints'),
      fetch('/api/physical-assessment/status'),
      fetch('/api/goal'),
      fetch('/api/food-selections'),
    ]);
    const intake = await intakeRes.json();
    const con = await conRes.json();
    const pa = await paRes.json();
    const goal = await goalRes.json();
    const food = await foodRes.json();

    return intake.completed && con.completed && pa.completed && goal.computed && food.completed && _stateCache.baseline_done;
  } catch(e) {
    // If we can't check, fall back to baseline_done
    return _stateCache.baseline_done;
  }
}

async function resumeOnboarding() {
  // Check each onboarding step and resume where the user left off
  try {
    // Step 1: Check food selections
    const foodRes = await fetch('/api/food-selections');
    const foodData = await foodRes.json();
    if (foodData.completed) {
      // Food done — show final reveal (profile + projection + plan)
      showFinalReveal();
      return;
    }

    // Step 2: Check goal
    const goalRes = await fetch('/api/goal');
    const goalData = await goalRes.json();
    if (goalData.computed) {
      // Goal computed but food not done — go to food selection
      window._goalData = goalData;
      showFoodSelection();
      return;
    }

    // Check remaining steps in FORWARD order — find the first incomplete one
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

    // Physical done, constraints done — check goal
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
        <span class="bsr-detail">${lift.suggested} lb x ${w.reps} reps</span>
        <span class="bsr-result">Est 1RM: ${oneRM} lb</span>
        <span class="bsr-weight">Working: ${working} lb</span>
      </div>`;
    }
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Your Starting Weights</h2>
        <div class="baseline-desc" style="margin-bottom:12px">
          Working weights are set at ~75% of your estimated 1RM (the right range for 4x10 in Phase 1).
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
  computeGoal();
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
            <input type="number" id="activity-duration" placeholder="e.g. 90" min="10" max="300">
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

function showPhysicalAssessment() {
  _paStep = 0;
  _paData = { has_gym: null, has_tape: null, weight: null, height: null, waist: null, chest: null, bicep: null, thigh: null, hips: null, neck: null };
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

  // Also save body weight to bodyweight tracker
  if (_paData.weight) {
    apiPost('/api/bodyweight', { date: todayStr(), weight: _paData.weight });
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
  computeGoal();
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
      <canvas id="projection-chart" width="320" height="180" style="margin:1rem auto;display:block"></canvas>
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

    // Step 1: Loading
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center;padding:3rem 2rem">
            <h2 style="font-size:1.5rem;margin-bottom:16px">Building Your Plan</h2>
            <div class="chat-typing" style="justify-content:center;margin:1.5rem 0"><span></span><span></span><span></span></div>
            <div style="font-size:14px;color:var(--muted);font-family:'DM Mono',monospace">Analyzing everything you told me...</div>
        </div>
    </div>`;

    // Step 2: Compute goal + generate profile in parallel
    let goalData = window._goalData;
    let profileText = null;

    try {
        // Compute goal if not already done
        if (!goalData) {
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

    // Step 3: Show Athlete Profile
    showRevealProfile(profileText, goalData);
}

function showRevealProfile(profileText, goalData) {
    const el = document.getElementById('baseline-overlay');
    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card psych-intake-card">
            <h2 style="margin-bottom:0.75rem">Your Athlete Profile</h2>
            <div class="psych-report">${profileText ? renderMarkdown(profileText) : '<p style="color:var(--muted)">Profile generation in progress...</p>'}</div>
            <button class="btn btn-primary" style="width:100%;margin-top:1.5rem;font-size:16px;padding:14px" onclick="showRevealProjection()">See Your Projection →</button>
        </div>
    </div>`;
}

function showRevealProjection() {
    const el = document.getElementById('baseline-overlay');
    const goalData = window._goalData;

    if (!goalData || !goalData.weight_projection) {
        showRevealPlan();
        return;
    }

    const proj = goalData.weight_projection;
    const w4 = proj.find(p => p.week === 4);
    const w8 = proj.find(p => p.week === 8);
    const w12 = proj.find(p => p.week === 12);

    el.innerHTML = `<div class="baseline-overlay">
        <div class="baseline-card" style="text-align:center">
            <h2>If You Follow This Plan</h2>
            <div class="projection-milestones">
                <div class="proj-milestone"><span class="proj-week">Week 4</span><span class="proj-weight">${w4 ? Math.round(w4.projected) : '?'} lbs</span></div>
                <div class="proj-milestone"><span class="proj-week">Week 8</span><span class="proj-weight">${w8 ? Math.round(w8.projected) : '?'} lbs</span></div>
                <div class="proj-milestone highlight"><span class="proj-week">Week 12</span><span class="proj-weight">${w12 ? Math.round(w12.projected) : '?'} lbs</span></div>
            </div>
            <canvas id="projection-chart" width="320" height="180" style="margin:1rem auto;display:block"></canvas>
            <button class="btn btn-primary" style="width:100%;margin-top:1.5rem;font-size:16px;padding:14px" onclick="showRevealPlan()">See Your Training Plan →</button>
        </div>
    </div>`;

    setTimeout(() => drawProjectionChart(proj), 100);
}

function showRevealPlan() {
    const el = document.getElementById('baseline-overlay');
    const g = window._goalData || {};

    const goalLabel = (g.goal_type || 'cut').toUpperCase();
    const goalColor = g.goal_type === 'bulk' ? 'var(--blue)' : g.goal_type === 'recomp' ? 'var(--amber)' : 'var(--accent)';

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
        <div class="baseline-card">
            <div style="text-align:center;margin-bottom:1rem">
                <span class="plan-goal-badge" style="background:${goalColor}">${goalLabel}</span>
            </div>
            <h2 style="text-align:center;margin-bottom:1.5rem">Your Training Plan</h2>

            <div class="plan-section">
                <div class="plan-section-label">Daily Targets</div>
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
                <button class="btn btn-primary" style="width:100%;font-size:16px;padding:14px" onclick="acceptPlan()">Let's Do This</button>
                <button class="btn btn-secondary" style="width:100%;font-size:14px;padding:12px" onclick="requestMoreAggressive()">I Want Bigger Results</button>
                <button class="btn btn-secondary" style="width:100%;font-size:13px;padding:10px;opacity:0.6" onclick="handleDialBack()">This Is Too Much</button>
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

function pickStartDate(dateStr) {
    const wakeTime = document.getElementById('wake-time-select')?.value || '5:30';
    apiPost('/api/goal', { plan_accepted: true });
    apiPost('/api/state', { baseline_done: true, start_date: dateStr });
    _stateCache.baseline_done = true;
    _stateCache.start_date = dateStr;
    document.getElementById('baseline-overlay').innerHTML = '';
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

        showRevealProjection();
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
        <input type="text" id="psych-input" placeholder="Type your response..." onkeydown="if(event.key==='Enter')sendPsychMessage()">
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
        // Show welcome back message
        _psychMessages.unshift({ role: 'coach', content: 'Welcome back. Picking up where we left off...' });
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
    if (data.completed) {
      _psychCompleted = true;
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
    <button onclick="exportData()">Export Data</button>
    <button onclick="importData()">Import Data</button>
    <button onclick="window.location='/logout'">Logout</button>
    <button onclick="closeSettingsMenu()">Cancel</button>
  `;
  header.parentNode.appendChild(dd);
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
  const weightInput = document.getElementById('wt-' + week + '-' + dayIdx + '-' + exIdx);
  const weight = weightInput ? parseFloat(weightInput.value) || 0 : 0;
  const weekData = workoutData[String(week)];
  const setsLabel = weekData ? weekData.days[dayIdx].exercises[exIdx].sets : '';
  recordWeight(exName, weight, setsLabel, rpe, week, dayIdx);
  renderDetail();
}

// ─── INIT ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Fetch all data in parallel
  try {
    const [stateRes, weightsRes, compRes, suppRes, bwRes, garminRes, workoutRes, mealsRes] = await Promise.all([
      fetch('/api/state'),
      fetch('/api/weights'),
      fetch('/api/completions'),
      fetch('/api/supplements?date=' + todayStr()),
      fetch('/api/bodyweight'),
      fetch('/api/garmin/status'),
      fetch('/api/workouts'),
      fetch('/api/meals?date=' + todayStr()),
    ]);

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

    // Garmin
    try {
      const garminStatus = await garminRes.json();
      garminConnected = garminStatus.connected;
      if (garminConnected) await refreshGarmin();
    } catch(e) {}

    // Set state from cache
    currentWeek = _stateCache.current_week || 1;
    currentPhase = WEEK_TO_PHASE[currentWeek];

    // Auto-calculate week from start date if set
    if (_stateCache.start_date) {
      const start = new Date(_stateCache.start_date);
      const now = new Date();
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
    const onboardingDone = await checkOnboardingComplete();
    if (!onboardingDone) {
      await resumeOnboarding();
    }

    // Travel banner
    renderTravelBanner();

    renderAll();

    // Morning check-in (only if onboarding fully complete)
    if (onboardingDone) {
      await checkMorningCheckin();
    }

    // Load chat history
    await loadChatHistory();
  } catch(e) {
    console.error('Init failed', e);
    // Fallback: try to render with empty data
    _stateCache = _stateCache || { current_week: 1, baseline_done: false };
    _weightsCache = _weightsCache || {};
    _completionsCache = _completionsCache || { exercises: {}, days: {} };
    _supplementsCache = _supplementsCache || { taken: {}, list: [] };
    _bodyweightCache = _bodyweightCache || [];
    renderAll();
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
          <input type="text" id="mc-coach-input" placeholder="Reply to Erik..." onkeydown="if(event.key==='Enter')sendMorningCoachReply()">
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
        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="document.getElementById('morning-checkin-overlay').innerHTML='';triggerWeeklyPlanning()">Continue to Weekly Planning</button>
      </div>
    </div>`;
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
  const msg = `[WEEKLY_PLANNING] It's Sunday - time for our weekly planning session. I just finished week ${weekNum}. The coming week is week ${nextWeek}. Let's review how this week went and plan for next week. Ask me what I need to know for the week ahead.`;

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
    const res = await fetch('/api/chat/history?days=7');
    const data = await res.json();
    _chatHistory = Array.isArray(data) ? data : (data.messages || []);
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
  _chatOverlayOpen = !_chatOverlayOpen;
  renderChatOverlay();
}

function closeChatOverlay() {
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
      <input type="text" id="chat-overlay-input" placeholder="Ask Erik anything..." onkeydown="if(event.key==='Enter')sendChatMessage('chat-overlay-input','chat-overlay-messages')">
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
  container.scrollTop = container.scrollHeight;
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
        const res = await fetch('/api/chat/stream', {
            method: 'POST',
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
        _chatHistory.push({ role: 'coach', text: fullText || 'No response', time: new Date().toISOString() });
    } catch(e) {
        const typingEl = document.getElementById('chat-typing-' + containerId);
        if (typingEl) typingEl.remove();
        _chatHistory.push({ role: 'coach', text: 'Connection error. Try again.', time: new Date().toISOString() });
    }

    renderChatMessages(containerId);
    syncChatContainers(containerId);
    updateChatFabPulse();
    renderInlineCoach();
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
  document.getElementById('garmin-error').style.display = 'none';
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
}

// ─── BODY WEIGHT / WEIGH-IN ────────────────────────────────────────────────
function renderWeighInBar() {
  const el = document.getElementById('weighin-bar');
  if (!el) return;

  const bwData = Array.isArray(_bodyweightCache) ? _bodyweightCache : [];
  const today = todayStr();
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
    <div class="weighin-chart"><canvas id="weighin-canvas" width="200" height="60"></canvas></div>
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

// ─── SUPPLEMENT TRACKER ─────────────────────────────────────────────────────
function renderSupplementBar() {
  const el = document.getElementById('supplement-bar');
  if (!el) return;
  if (!_supplementsCache || !_supplementsCache.list || _supplementsCache.list.length === 0) {
    el.innerHTML = '';
    return;
  }

  const taken = _supplementsCache.taken || {};
  const pills = _supplementsCache.list.map(s => {
    const name = typeof s === 'string' ? s : s.name;
    const required = typeof s === 'object' && s.required;
    const isTaken = !!taken[name];
    return `<button class="supplement-pill${isTaken ? ' taken' : ''}${required ? ' required' : ''}" onclick="toggleSupplement('${name.replace(/'/g, "\\'")}')">
      ${isTaken ? '&#10003; ' : ''}${name}
    </button>`;
  }).join('');

  el.innerHTML = `<div class="supplement-row">
    <span class="supplement-label">Supplements</span>
    ${pills}
  </div>`;
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
    <button class="warmup-toggle" onclick="document.getElementById('warmup-body').classList.toggle('visible');this.classList.toggle('open')">
      <h3 style="margin:0">Warm-Up${wu.time ? ' - ' + wu.time : ''}</h3>
      <span class="warmup-arrow">\u25BC</span>
    </button>
    <div class="warmup-body" id="warmup-body">
      ${(wu.steps || []).map((step, i) => `<div class="warmup-step">
        <span class="warmup-step-name">${step.name}</span>
        ${step.duration ? `<span class="warmup-step-duration">${step.duration}</span>` : ''}
        ${step.note ? `<div class="warmup-step-note">${step.note}</div>` : ''}
      </div>`).join('')}
      <button class="btn btn-primary warmup-timer-btn" onclick="startWarmupTimer()">Start Warm-Up</button>
    </div>
  </div>`;
}

function startWarmupTimer() {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData || currentDay === null) return;
  const dayData = weekData.days[currentDay];
  if (!dayData || !dayData.warmup || !dayData.warmup.steps) return;

  const steps = dayData.warmup.steps;
  let stepIdx = 0;
  let secondsLeft = parseDuration(steps[0].duration);

  function parseDuration(dur) {
    if (!dur) return 30;
    const m = dur.match(/(\d+)/);
    if (!m) return 30;
    const num = parseInt(m[1]);
    if (dur.includes('min')) return num * 60;
    return num;
  }

  function updateDisplay() {
    const btn = document.querySelector('.warmup-timer-btn');
    if (!btn) { clearInterval(warmupTimerInterval); return; }
    if (stepIdx >= steps.length) {
      btn.textContent = 'Done!';
      btn.disabled = true;
      clearInterval(warmupTimerInterval);
      return;
    }
    const mins = Math.floor(secondsLeft / 60);
    const secs = secondsLeft % 60;
    btn.textContent = `${steps[stepIdx].name} - ${mins}:${secs.toString().padStart(2, '0')}`;
  }

  if (warmupTimerInterval) clearInterval(warmupTimerInterval);
  updateDisplay();
  warmupTimerInterval = setInterval(() => {
    secondsLeft--;
    if (secondsLeft < 0) {
      stepIdx++;
      if (stepIdx < steps.length) {
        secondsLeft = parseDuration(steps[stepIdx].duration);
      }
    }
    updateDisplay();
  }, 1000);
}

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
        <canvas id="progress-bw-chart" width="340" height="180"></canvas>
      </div>
      <div class="progress-chart-section">
        <h3>Key Lifts</h3>
        <canvas id="progress-lifts-chart" width="340" height="180"></canvas>
      </div>
      <div class="progress-chart-section">
        <h3>Waist Measurement</h3>
        <canvas id="progress-waist-chart" width="340" height="120"></canvas>
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
  }

  // Draw lifts chart (multiple lines)
  if (data.lifts) {
    drawLiftsChart('progress-lifts-chart', data.lifts);
  }

  // Draw waist chart
  if (data.measurements && data.measurements.length > 1) {
    drawProgressChart('progress-waist-chart', data.measurements.map(e => e.waist), data.measurements.map(e => e.date), '#f59e0b');
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
  renderInlineCoach();
  checkMilestones();

  // Auto-select today if no day is currently selected
  if (currentDay === null) {
    const todayIdx = new Date().getDay();
    // JS getDay: 0=Sun, convert to Mon=0 format
    const mappedIdx = todayIdx === 0 ? 6 : todayIdx - 1;
    setDay(mappedIdx);
  }
}

function renderInlineCoach() {
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
  if (!garminConnected) {
    el.innerHTML = `<button class="garmin-connect-btn" onclick="showModal()">Connect Garmin \u2014 unlock HRV, sleep &amp; readiness</button>`;
    return;
  }

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
      <span class="tn-week-label">Week ${currentWeek}${isDeload ? ' &middot; Deload' : ''} &middot; Phase ${weekData.phase}</span>
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

  const weekData = workoutData[String(currentWeek)];
  if (!weekData) return;
  const d = weekData.days[currentDay];
  if (!d) return;
  const runClass = `run-${d.run.type}`;
  const isTraveling = _stateCache && _stateCache.traveling;

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
  const displayExercises = travelExercises || d.exercises;

  // Exercise rows with weight tracking and RPE
  const exRows = displayExercises.map((ex, i) => {
    const done = isExDone(currentWeek, currentDay, i);
    const suggestion = getWeightForExercise(ex.name, currentWeek);
    const lastWt = getLastWeight(ex.name);
    const weightVal = suggestion.weight != null ? suggestion.weight : '';

    const exData = getExerciseData(ex.name);
    const hasRPE = exData && exData.history && exData.history.length > 0 &&
      exData.history[exData.history.length - 1].week === currentWeek &&
      exData.history[exData.history.length - 1].day === currentDay;
    const lastRPE = hasRPE ? exData.history[exData.history.length - 1].rpe : null;

    let rpeHtml = '';
    if (done && !hasRPE) {
      rpeHtml = `<div class="rpe-feedback">
        <span class="rpe-label">How was it?</span>
        <button class="rpe-btn rpe-easy" onclick="submitRPE(${currentWeek},${currentDay},${i},'${ex.name.replace(/'/g, "\\'")}','too_easy')">Too Easy</button>
        <button class="rpe-btn rpe-right" onclick="submitRPE(${currentWeek},${currentDay},${i},'${ex.name.replace(/'/g, "\\'")}','just_right')">Just Right</button>
        <button class="rpe-btn rpe-hard" onclick="submitRPE(${currentWeek},${currentDay},${i},'${ex.name.replace(/'/g, "\\'")}','too_hard')">Too Hard</button>
      </div>`;
    } else if (hasRPE) {
      const rpeLabels = { too_easy: 'Too Easy', just_right: 'Just Right', too_hard: 'Too Hard' };
      const rpeCls = { too_easy: 'rpe-easy', just_right: 'rpe-right', too_hard: 'rpe-hard' };
      rpeHtml = `<div class="rpe-feedback">
        <span class="rpe-label">Felt:</span>
        <button class="rpe-btn ${rpeCls[lastRPE] || 'rpe-right'} selected" disabled>${rpeLabels[lastRPE] || lastRPE}</button>
      </div>`;
    }

    return `<div class="exercise-row" style="flex-wrap:wrap">
      <button class="ex-check${done?' done':''}" onclick="toggleEx(${currentWeek},${currentDay},${i})">
        ${done ? '&#10003;' : ''}
      </button>
      <div class="ex-info">
        <div class="ex-name">${ex.name}${ex.video ? ` <a class="ex-video-link" href="https://www.youtube.com/results?search_query=${encodeURIComponent(ex.video)}" target="_blank" rel="noopener" title="Watch form video">&#9654;</a>` : ''}</div>
        ${ex.note ? `<div class="ex-note">${ex.note}</div>` : ''}
      </div>
      <div class="weight-input-wrap">
        <input class="weight-input" type="number" inputmode="decimal" id="wt-${currentWeek}-${currentDay}-${i}" value="${weightVal}" placeholder="lb">
        ${lastWt != null ? `<div class="weight-last">Last: ${lastWt} lb</div>` : ''}
        ${suggestion.reason ? `<div class="weight-suggestion">${suggestion.reason}</div>` : ''}
      </div>
      <div class="ex-sets">${ex.sets}</div>
      ${rpeHtml ? `<div style="width:100%;padding-left:36px">${rpeHtml}</div>` : ''}
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
      const d2 = weights[name];
      if (!d2 || !d2.current) continue;
      const trend = getWeightTrend(name);
      const trendIcon = trend === 'up' ? '<span class="ws-trend-up">\u2191</span>' :
                        trend === 'down' ? '<span class="ws-trend-down">\u2193</span>' :
                        '<span class="ws-trend-same">\u2192</span>';
      const shortName = name.replace('Barbell ', '').replace('Conventional ', '');
      wsRows += `<div class="ws-row"><span class="ws-name">${shortName}</span><span class="ws-val">${d2.current} lb ${trendIcon}</span></div>`;
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
    ${sundaySectionHtml}
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
      ${exRows}
    </div>` : ''}
    <div class="detail-section">
      <h3>Run</h3>
      <div class="run-detail-box">
        <div class="rdl">Type</div>
        <div class="rdt"><span class="run-pill ${runClass}">${d.run.label} &middot; ${d.run.time}</span></div>
        <div class="rdd" style="margin-top:8px">${d.run.detail}</div>
      </div>
    </div>
    ${renderMealSection(d)}
    ${d.timing ? `<div class="detail-section">
      <h3>Session Timing</h3>
      ${timingRows.join('')}
    </div>` : ''}
    ${d.notes ? `
    <div class="detail-section">
      <div class="notes-box"><strong>Coach note:</strong> ${d.notes}</div>
    </div>` : ''}
    ${renderCheckinSection(d, currentDay)}
    <div class="detail-section">
      <h3>Coach</h3>
      <div class="coach-chat">
        <div class="chat-messages" id="coach-messages" style="max-height:300px">${chatMessagesHtml}</div>
        <div class="chat-input-bar" style="border-top:none;padding:8px 0 0 0;background:none">
          <input type="text" id="coach-input-field" placeholder="Ask Erik anything..." onkeydown="if(event.key==='Enter')sendChatMessage('coach-input-field','coach-messages')">
          <button onclick="sendChatMessage('coach-input-field','coach-messages')">Send</button>
        </div>
      </div>
    </div>
  </div>`;

  panel.classList.add('visible');
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  // Init sliders if check-in is present
  initCheckinSliders();

  // Scroll chat to bottom
  const msgContainer = document.getElementById('coach-messages');
  if (msgContainer) msgContainer.scrollTop = msgContainer.scrollHeight;

  // Load Sunday photo previews asynchronously
  if (isSunday(d)) {
    loadSundayPhotoPreviews();
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
