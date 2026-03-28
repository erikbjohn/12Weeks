// ─── STATE ──────────────────────────────────────────────────────────────────
let workoutData = {};
let currentPhase = 1;
let currentWeek = 1;
let currentDay = null;
let garminConnected = false;
let garminData = null;
let readinessData = null;

const WEEK_TO_PHASE = {1:1,2:1,3:1,4:1,5:2,6:2,7:2,8:2,9:3,10:3,11:3,12:3};

// ─── INIT ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Load saved state
  const saved = localStorage.getItem('12w_state');
  if (saved) {
    try {
      const s = JSON.parse(saved);
      currentWeek = s.week || 1;
      currentPhase = WEEK_TO_PHASE[currentWeek];
    } catch(e) {}
  }

  // Fetch workout data
  try {
    const res = await fetch('/api/workouts');
    workoutData = await res.json();
  } catch(e) {
    console.error('Failed to load workouts', e);
  }

  // Check Garmin status
  try {
    const res = await fetch('/api/garmin/status');
    const d = await res.json();
    garminConnected = d.connected;
    if (garminConnected) await refreshGarmin();
  } catch(e) {}

  renderAll();
});

function saveState() {
  localStorage.setItem('12w_state', JSON.stringify({ week: currentWeek }));
}

// ─── GARMIN ─────────────────────────────────────────────────────────────────
async function garminLogin() {
  const email = document.getElementById('garmin-email').value;
  const pw = document.getElementById('garmin-password').value;
  const errEl = document.getElementById('garmin-error');
  errEl.style.display = 'none';

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
  document.getElementById('garmin-error').style.display = 'none';
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

// ─── COMPLETION TRACKING ────────────────────────────────────────────────────
function getCompletionKey(week, dayIdx, exIdx) {
  return `12w_done_${week}_${dayIdx}_${exIdx}`;
}

function getDayCompletionKey(week, dayIdx) {
  return `12w_daydone_${week}_${dayIdx}`;
}

function isExDone(week, dayIdx, exIdx) {
  return localStorage.getItem(getCompletionKey(week, dayIdx, exIdx)) === '1';
}

function toggleEx(week, dayIdx, exIdx) {
  const key = getCompletionKey(week, dayIdx, exIdx);
  if (localStorage.getItem(key) === '1') {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, '1');
  }
  renderDetail();
}

function isDayDone(week, dayIdx) {
  return localStorage.getItem(getDayCompletionKey(week, dayIdx)) === '1';
}

function toggleDay(week, dayIdx, e) {
  e.stopPropagation();
  const key = getDayCompletionKey(week, dayIdx);
  if (localStorage.getItem(key) === '1') {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, '1');
  }
  renderDayGrid();
}

// ─── RENDER ─────────────────────────────────────────────────────────────────
function renderAll() {
  renderGarminBar();
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
    // HRV
    const hrv = garminData.hrv;
    if (hrv && hrv.lastNight != null) {
      const color = getMetricColor('hrv', readinessData);
      metricsHtml += metric('HRV', hrv.lastNight, `avg ${hrv.weeklyAvg || '?'}`, color);
    }

    // Sleep
    const sleep = garminData.sleep;
    if (sleep) {
      const color = getMetricColor('sleep', readinessData);
      const score = sleep.score != null ? sleep.score : '?';
      metricsHtml += metric('Sleep', score, `${sleep.durationHours || '?'}h`, color);
    }

    // Body Battery
    const bb = garminData.bodyBattery;
    if (bb && bb.current != null) {
      const color = getMetricColor('bodyBattery', readinessData);
      metricsHtml += metric('Battery', bb.current, '', color);
    }

    // Training Readiness
    const tr = garminData.trainingReadiness;
    if (tr && tr.score != null) {
      const color = getMetricColor('trainingReadiness', readinessData);
      metricsHtml += metric('Ready', tr.score, tr.level || '', color);
    }

    // Stress
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
  ).join('');
}

function renderPhaseBanner() {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData) return;
  const info = weekData.phaseInfo;
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
  const runClass = `run-${d.run.type}`;

  // Exercise rows
  const exRows = d.exercises.map((ex, i) => {
    const done = isExDone(currentWeek, currentDay, i);
    return `<div class="exercise-row">
      <button class="ex-check${done?' done':''}" onclick="toggleEx(${currentWeek},${currentDay},${i})">
        ${done ? '&#10003;' : ''}
      </button>
      <div class="ex-info">
        <div class="ex-name">${ex.name}</div>
        ${ex.note ? `<div class="ex-note">${ex.note}</div>` : ''}
      </div>
      <div class="ex-sets">${ex.sets}</div>
    </div>`;
  }).join('');

  // Timing rows
  const timingRows = [];
  for (let i = 0; i < d.timing.length; i += 2) {
    timingRows.push(`<div class="timing-row">
      <div class="timing-time">${d.timing[i]}</div>
      <div class="timing-desc">${d.timing[i+1]}</div>
    </div>`);
  }

  panel.innerHTML = `<div class="detail-inner">
    <div class="detail-header">
      <div class="detail-title">Week ${currentWeek} &middot; ${d.day} &mdash; ${d.liftName}</div>
      <div class="detail-meta">
        ${!d.isRest ? `<span class="meta-chip" style="background:var(--lift-bg);border-color:var(--lift-border);color:var(--lift)">Lift &middot; ${d.exercises.length} exercises</span>` : ''}
        <span class="meta-chip ${runClass}">${d.run.label} &middot; ${d.run.time}</span>
      </div>
    </div>
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
    <div class="detail-section">
      <h3>Session Timing</h3>
      ${timingRows.join('')}
    </div>
    ${d.notes ? `
    <div class="detail-section">
      <div class="notes-box"><strong>Coach note:</strong> ${d.notes}</div>
    </div>` : ''}
  </div>`;

  panel.classList.add('visible');
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
