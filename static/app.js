// ─── STATE ──────────────────────────────────────────────────────────────────
let workoutData = {};
let currentPhase = 1;
let currentWeek = 1;
let currentDay = null;
let garminConnected = false;
let garminData = null;
let readinessData = null;
let coachHistory = []; // session-only chat history

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
  const errEl = document.getElementById('garmin-error');
  errEl.style.display = 'none';

  // Check if this is an MFA submission
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
      // Show MFA input
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

  // --- Garmin Day Stats section ---
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

  // --- Daily Goals section ---
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

  // --- Coach chat history ---
  let chatMessagesHtml = '';
  if (coachHistory.length > 0) {
    chatMessagesHtml = coachHistory.map(m =>
      `<div class="${m.role === 'coach' ? 'coach-message' : 'user-message'}">${m.text}</div>`
    ).join('');
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
      <h3>Today's Status</h3>
      ${garminStatsHtml}
      ${dailyGoalsHtml}
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

  // Gather context
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

  // Readiness addon
  let readinessNote = '';
  if (riskLevel === 'high') {
    readinessNote = ' Your Garmin data is showing elevated risk today - take the adjustments seriously.';
  } else if (riskLevel === 'moderate') {
    readinessNote = ' Garmin shows moderate readiness - listen to your body but don\'t bail unless something is actually wrong.';
  } else if (riskLevel === 'low') {
    readinessNote = ' Garmin says you\'re good to go. Trust the data.';
  }

  // Keyword matching - order matters, first match wins
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

  // Check each pattern
  for (const p of patterns) {
    for (const k of p.keys) {
      if (t.includes(k)) {
        return typeof p.resp === 'function' ? p.resp() : p.resp;
      }
    }
  }

  // Default fallback
  let fallback = 'Noted. Here\'s the deal: stick to today\'s plan. ';
  if (isLiftDay) {
    fallback += `You've got ${d.exercises.length} exercises to knock out. Focus on controlled reps and full range of motion. `;
  }
  fallback += `Run is ${d ? d.run.label + ' for ' + d.run.time : 'on the schedule'}. `;
  fallback += 'If something feels off, adjust intensity down 10-15% but finish the session. Showing up is 90% of the battle.';
  return fallback + readinessNote;
}
