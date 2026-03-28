// ─── DATA CACHES ────────────────────────────────────────────────────────────
let _weightsCache = null;
let _completionsCache = null;
let _mealsCache = {};
let _stateCache = null;
let _supplementsCache = null;
let _bodyweightCache = null;

// ─── STATE ──────────────────────────────────────────────────────────────────
let workoutData = {};
let currentPhase = 1;
let currentWeek = 1;
let currentDay = null;
let garminConnected = false;
let garminData = null;
let readinessData = null;
let coachHistory = [];
let warmupTimerInterval = null;

const WEEK_TO_PHASE = {1:1,2:1,3:1,4:1,5:2,6:2,7:2,8:2,9:3,10:3,11:3,12:3};

// ─── API HELPERS ────────────────────────────────────────────────────────────
function apiPost(url, body) {
  fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).catch(e => console.error('POST failed:', url, e));
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

    const foodRows = meal.foods.map(f => {
      const adjCal = Math.round((f.cal || 0) * multiplier);
      return `<div class="meal-food-row">
        <span class="meal-food-name">${f.item}</span>
        <span class="meal-food-portion">${f.portion}${multiplier !== 1 ? '<span class="meal-multiplier">x' + multiplier.toFixed(2).replace(/\.?0+$/, '') + '</span>' : ''}</span>
        <span class="meal-food-portion">${adjCal}cal</span>
      </div>`;
    }).join('');

    const adjustBtns = (isRestDay && fasting) ? '' : `<div class="meal-food-adjust">
      <button onclick="adjustMealPortion(${idx}, -0.25)" title="Less">-</button>
      <button onclick="adjustMealPortion(${idx}, 0.25)" title="More">+</button>
    </div>`;

    mealsHtml += `<div class="meal-item${meal.optional ? ' optional' : ''}">
      <button class="meal-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx})">
        ${eaten ? '&#10003;' : ''}
      </button>
      <div class="meal-time">${meal.time}</div>
      <div class="meal-content">
        <div class="meal-name">${meal.name} ${adjustBtns}</div>
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

  return `<div class="detail-section">
    <h3>Meal Plan &middot; ${activePlan.label || ''}</h3>
    ${fastToggleHtml}
    ${activePlan.note ? '<div class="meal-plan-note">' + activePlan.note + '</div>' : ''}
    <div class="meal-timeline">
      ${mealsHtml}
    </div>
    ${totalsHtml}
  </div>`;
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
        <button class="btn btn-primary" style="width:100%" onclick="baselineStep=1;renderBaseline()">Let's Go</button>
      </div>
    </div>`;
    return;
  }

  const liftIdx = baselineStep - 1;

  if (liftIdx >= BASELINE_LIFTS.length) {
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
        <button class="btn btn-primary" style="width:100%" onclick="saveBaseline()">Start Program</button>
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
        <button class="btn btn-primary" style="flex:1" onclick="baselineNext()">${liftIdx === BASELINE_LIFTS.length - 1 ? 'Finish' : 'Next'}</button>
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
  _stateCache.baseline_done = true;
  apiPost('/api/state', { baseline_done: true });
  baselineStep = -1;
  renderBaseline();
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
  dd.innerHTML = `
    <button onclick="redoBaseline()">Redo Baseline</button>
    <button onclick="showStartDateSetting()">Set Start Date</button>
    <button onclick="exportData()">Export Data</button>
    <button onclick="importData()">Import Data</button>
    <button onclick="closeSettingsMenu()">Cancel</button>
  `;
  header.parentNode.appendChild(dd);
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

    // Check for localStorage migration
    checkLocalStorageMigration();

    if (!_stateCache.baseline_done) {
      showBaseline();
    }

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

// ─── RENDER ─────────────────────────────────────────────────────────────────
function renderAll() {
  renderWeighInBar();
  renderGarminBar();
  renderSupplementBar();
  renderReadiness();
  renderPhaseNav();
  renderPhaseBanner();
  renderWeekTabs();
  renderDayGrid();
  renderDetail();
}

function renderGarminBar() {
  const el = document.getElementById('garmin-bar');
  if (!garminConnected) {
    el.innerHTML = `<button class="garmin-connect-btn" onclick="showModal()">Connect Garmin Watch</button>`;
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

function renderDetail() {
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

  // Exercise rows with weight tracking and RPE
  const exRows = d.exercises.map((ex, i) => {
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
        <div class="ex-name">${ex.name}</div>
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
  if (!d.isRest && d.exercises.length > 0) {
    goalsItems += '<div class="dg-item">Complete all exercises. Rest times matter - don\'t rush heavy sets.</div>';
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

  // Coach chat history
  let chatMessagesHtml = '';
  if (coachHistory.length > 0) {
    chatMessagesHtml = coachHistory.map(m =>
      `<div class="${m.role === 'coach' ? 'coach-message' : 'user-message'}">${m.text}</div>`
    ).join('');
  }

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

  panel.innerHTML = `<div class="detail-inner">
    <div class="detail-header">
      <div class="detail-title">Week ${currentWeek} &middot; ${d.day} &mdash; ${d.liftName}</div>
      <div class="detail-meta">
        ${!d.isRest ? `<span class="meta-chip" style="background:var(--lift-bg);border-color:var(--lift-border);color:var(--lift)">Lift &middot; ${d.exercises.length} exercises</span>` : ''}
        <span class="meta-chip ${runClass}">${d.run.label} &middot; ${d.run.time}</span>
      </div>
    </div>
    <div class="detail-section">
      ${weightSummaryHtml}
      <h3>Today's Status</h3>
      ${garminStatsHtml}
      ${dailyGoalsHtml}
    </div>
    ${renderWarmupSection(d)}
    ${!d.isRest && d.exercises.length > 0 ? `
    <div class="detail-section">
      <h3>Exercises</h3>
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
        <div class="coach-chat-messages" id="coach-messages">${chatMessagesHtml}</div>
        <div class="coach-input">
          <input type="text" id="coach-input-field" placeholder="How are you feeling today? Any extra stress?" onkeydown="if(event.key==='Enter')sendCoachMessage()">
          <button onclick="sendCoachMessage()">Send</button>
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
}

// ─── COACHING CHAT ──────────────────────────────────────────────────────────
function sendCoachMessage() {
  const input = document.getElementById('coach-input-field');
  const text = (input.value || '').trim();
  if (!text) return;

  coachHistory.push({ role: 'user', text });
  const response = generateCoachResponse(text);
  coachHistory.push({ role: 'coach', text: response });

  input.value = '';
  renderDetail();
}

function generateCoachResponse(userText) {
  const t = userText.toLowerCase();

  const weekData = workoutData[String(currentWeek)];
  const d = weekData ? weekData.days[currentDay] : null;
  const isLiftDay = d && !d.isRest && d.exercises.length > 0;
  const runType = d ? d.run.type : '';
  const isHiit = runType === 'hiit';
  const isTempo = runType === 'tempo';
  const isHighIntensity = isHiit || isTempo;
  const hasReadiness = readinessData && readinessData.risk_level !== 'unknown';
  const riskLevel = hasReadiness ? readinessData.risk_level : null;
  const hrvStable = garminData && garminData.hrv && garminData.hrv.lastNight != null &&
    garminData.hrv.weeklyAvg != null && garminData.hrv.lastNight >= garminData.hrv.weeklyAvg * 0.85;
  const bbLow = garminData && garminData.bodyBattery && garminData.bodyBattery.current != null && garminData.bodyBattery.current < 30;

  let readinessNote = '';
  if (riskLevel === 'high') {
    readinessNote = ' Your Garmin data is showing elevated risk today - take the adjustments seriously.';
  } else if (riskLevel === 'moderate') {
    readinessNote = ' Garmin shows moderate readiness - listen to your body but don\'t bail unless something is actually wrong.';
  } else if (riskLevel === 'low') {
    readinessNote = ' Garmin says you\'re good to go. Trust the data.';
  }

  const patterns = [
    {
      keys: ['injured', 'injury', 'sharp pain', 'pulled'],
      resp: 'Stop. Sharp pain or a potential injury is not something to push through. If it\'s acute, skip the affected movement and substitute something that doesn\'t hurt. If it\'s been lingering more than 3 days, see a physio. Training around an injury is smart. Training through one is stupid.'
    },
    {
      keys: ['pain', 'hurts', 'twinge'],
      resp: 'Dull ache or DOMS? Push through the warmup and reassess after 2 sets. If it gets worse or changes your movement pattern, swap the exercise. Joint pain is different from muscle soreness - know the difference. Ice after if needed.'
    },
    {
      keys: ['tired', 'exhausted', 'fatigued', 'drained'],
      resp: function() {
        let base = 'Tired is normal mid-cut. Your body is adapting.';
        if (hrvStable) {
          base += ' HRV is stable - push through, you\'ll feel better after the warmup.';
        } else if (garminData && garminData.hrv) {
          base += ' Your HRV is dipping below average. Respect that signal.';
        }
        base += ' If you\'re dragging after the first 2 sets, drop weight 10% and finish the volume. Getting the reps in matters more than the load today.';
        if (isHighIntensity) {
          base += ' Consider dropping the ' + (isHiit ? 'HIIT to a steady Zone 2' : 'tempo to easy pace') + ' if you\'re still flat after lifting.';
        }
        return base + readinessNote;
      }
    },
    {
      keys: ['stressed', 'stress', 'anxious', 'anxiety', 'overwhelmed'],
      resp: function() {
        let base = 'External stress stacks with training stress. Your nervous system doesn\'t distinguish. Today, focus on form over load.';
        if (isHighIntensity) {
          base += ' You have ' + (isHiit ? 'HIIT' : 'tempo') + ' scheduled - consider swapping to Zone 2 instead. Hammering intervals on top of high life stress is counterproductive.';
        }
        base += ' Sleep is your #1 priority tonight. If you can, 10 min walk outside before bed.';
        return base + readinessNote;
      }
    },
    {
      keys: ['sleep', 'slept bad', 'insomnia', 'didn\'t sleep', 'poor sleep'],
      resp: function() {
        let base = 'Bad sleep night. It happens. One night won\'t kill your gains.';
        if (garminData && garminData.sleep && garminData.sleep.score != null && garminData.sleep.score < 50) {
          base += ' Garmin confirms it - sleep score is rough.';
        }
        base += ' Caffeine is your friend today but cut it off by 1pm. During the session, keep rest periods slightly longer. You may surprise yourself - some of my best sessions have been on bad sleep.';
        if (isHighIntensity) {
          base += ' That said, the ' + (isHiit ? 'HIIT' : 'tempo') + ' might be worth dialing down to easy pace. Recovery debt is real.';
        }
        return base + readinessNote;
      }
    },
    {
      keys: ['sore', 'doms', 'stiff', 'tight'],
      resp: function() {
        let base = 'Soreness means you trained. That\'s the job. Warm up thoroughly - 5 min of light movement before you touch a bar. Foam roll the worst spots for 60 seconds each.';
        if (isLiftDay) {
          base += ' First working set should feel noticeably better than the warmup. If the affected muscles are today\'s target, start lighter and ramp up. Volume is more important than intensity when you\'re this sore.';
        }
        return base;
      }
    },
    {
      keys: ['great', 'amazing', 'fantastic', 'awesome', 'incredible', 'perfect'],
      resp: function() {
        let base = 'Let\'s go. Don\'t change anything - execute the plan as written. Save the PR attempts for test week.';
        if (riskLevel === 'low') {
          base += ' Data backs it up too. Clean session today.';
        }
        base += ' Use this energy to nail your form on every rep. Good days are for building technique, not ego lifting.';
        return base;
      }
    },
    {
      keys: ['good', 'fine', 'decent', 'okay', 'alright', 'not bad'],
      resp: function() {
        return 'Good enough is good enough. Most sessions should feel like a 6 or 7 out of 10. That\'s the steady work that builds the foundation. Hit your numbers, stay tight on form, get out.' + readinessNote;
      }
    },
    {
      keys: ['bad', 'terrible', 'awful', 'horrible', 'rough', 'rough day'],
      resp: function() {
        let base = 'Bad day? Show up anyway. The workout doesn\'t have to be perfect. Rule of 10: do the first 10 minutes. If you still feel terrible after warming up, drop intensity 15-20% and finish the work.';
        if (bbLow) {
          base += ' Your body battery is tanked - this is a "just get it done" day, not a performance day.';
        }
        base += ' The fact that you\'re here when it\'s hard is what separates you from 95% of people. Consistency over intensity, always.';
        return base + readinessNote;
      }
    },
    {
      keys: ['hungry', 'starving', 'appetite', 'cravings'],
      resp: 'You\'re in a deficit. Hunger is expected and it\'s a sign the cut is working. Make sure you\'re hitting your protein target - it\'s the single best tool for managing hunger. If it\'s brutal, add more volume to your veggies and drink more water. Train fasted if you can handle it, otherwise a small protein shake pre-workout is fine. This is temporary.'
    },
    {
      keys: ['motivation', 'unmotivated', 'don\'t want to', 'can\'t be bothered', 'lazy'],
      resp: 'Motivation is unreliable. You don\'t need it. You need a system, and you have one - it\'s this program. Show up, start the warmup, and let momentum take over. Discipline is doing it when you don\'t feel like it. That\'s literally the entire game. 12 weeks is nothing. You\'ve already started.'
    },
    {
      keys: ['weak', 'strength down', 'lost strength', 'weights feel heavy', 'can\'t lift'],
      resp: function() {
        let base = 'Strength dips during a cut are normal - you\'re in a caloric deficit. You\'re not getting weaker, you\'re running on less fuel. Maintain the load as long as form is clean. If you have to drop, keep it to 5-10%. The goal right now is muscle preservation, not PRs.';
        if (currentWeek >= 9) {
          base += ' You\'re in Phase 3 - this is where it gets hard. The body fights back. Trust the process.';
        }
        return base;
      }
    },
    {
      keys: ['skip', 'rest day', 'take a day off', 'skip today'],
      resp: function() {
        if (riskLevel === 'high') {
          return 'Your readiness data actually supports backing off today. If you need to skip the lifting, at least do the run at easy pace. Keep the streak alive even if the session is minimal. One easy day won\'t wreck you but skipping entirely is a slippery slope.';
        }
        return 'Unless you\'re injured or genuinely sick, do the work. Modify if you need to - lighter weights, easier run - but show up. The hardest part is walking through the door. You can always do less once you\'re there, but you can\'t do anything from the couch.';
      }
    },
    {
      keys: ['deload', 'easy week', 'recovery week'],
      resp: 'Deload weeks are programmed for a reason. Drop to 60% of working weight, keep the reps the same. Runs go to easy/Zone 2 only. Your body rebuilds during deloads - this is where the adaptation actually happens. Don\'t skip it and don\'t go harder because you "feel good." Respect the program.'
    },
    {
      keys: ['run', 'running', 'cardio'],
      resp: function() {
        let base = `Today's run is ${d ? d.run.label : 'scheduled'}. `;
        if (isHiit) {
          base += 'HIIT day - go hard during intervals, actually recover during rest. Don\'t jog your rest periods. Full send, full rest.';
        } else if (isTempo) {
          base += 'Tempo pace should feel "comfortably hard." You can speak a few words but not hold a conversation. Stay disciplined on the pace - don\'t start too fast.';
        } else if (runType === 'z2') {
          base += 'Zone 2 means conversational pace. If you\'re breathing hard, you\'re going too fast. Slow down. This builds your aerobic base and aids recovery.';
        } else if (runType === 'long') {
          base += 'Long run - steady effort. Bring water if it\'s over 45 min. Keep it conversational. This is about time on feet, not pace.';
        } else {
          base += 'Easy pace today. Keep it honest - recovery runs should feel genuinely easy.';
        }
        return base + readinessNote;
      }
    },
    {
      keys: ['diet', 'food', 'eating', 'nutrition', 'macros', 'calories', 'protein'],
      resp: 'Stick to the plan. Protein target is non-negotiable - hit it every day. If you\'re struggling with calories, front-load your protein earlier in the day. Meal prep is your weapon. If you\'re going off plan, ask yourself: is this worth adding a day to the cut? Sometimes it is. Usually it isn\'t.'
    },
    {
      keys: ['progress', 'results', 'not seeing', 'plateau', 'stalled'],
      resp: function() {
        let base = 'Progress isn\'t linear, especially in a cut. You\'re losing fat and preserving muscle - the scale may not move but the mirror will. Take weekly photos and measurements.';
        if (currentWeek <= 3) {
          base += ' You\'re still early. Give it 4 weeks minimum before evaluating.';
        } else if (currentWeek >= 8) {
          base += ' At this stage, progress slows. That\'s biology, not failure. Stay the course.';
        }
        return base;
      }
    }
  ];

  for (const p of patterns) {
    for (const k of p.keys) {
      if (t.includes(k)) {
        return typeof p.resp === 'function' ? p.resp() : p.resp;
      }
    }
  }

  let fallback = 'Noted. Here\'s the deal: stick to today\'s plan. ';
  if (isLiftDay) {
    fallback += `You've got ${d.exercises.length} exercises to knock out. Focus on controlled reps and full range of motion. `;
  }
  fallback += `Run is ${d ? d.run.label + ' for ' + d.run.time : 'on the schedule'}. `;
  fallback += 'If something feels off, adjust intensity down 10-15% but finish the session. Showing up is 90% of the battle.';
  return fallback + readinessNote;
}
