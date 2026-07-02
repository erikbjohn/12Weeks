// ─── COACH FEEDBACK FLAG (👎 button on coach bubbles) ───────────────────────
// Delegated click handler — works on every coach bubble regardless of which
// SSE consumer rendered it. Adds 👎 button on hover, opens category picker on
// click, posts to /api/coach/flag.
(function setupCoachFlagging() {
  if (typeof document === 'undefined') return;

  function injectFlagButton(bubble) {
    if (bubble.querySelector('.mc-flag-btn')) return;
    var btn = document.createElement('button');
    btn.className = 'mc-flag-btn';
    btn.title = 'Flag this response';
    btn.textContent = '👎';
    btn.onclick = function(e) {
      e.stopPropagation();
      openFlagPicker(bubble, btn);
    };
    bubble.appendChild(btn);
  }

  function getRecentUserMessage(bubble) {
    // Walk previous siblings to find the nearest user bubble
    var el = bubble.previousElementSibling;
    while (el) {
      if (el.classList && el.classList.contains('mc-user-bubble')) {
        return (el.textContent || '').trim();
      }
      el = el.previousElementSibling;
    }
    return '';
  }

  function openFlagPicker(bubble, btn) {
    // Close any other open picker
    document.querySelectorAll('.mc-flag-picker').forEach(function(p) { p.remove(); });

    var picker = document.createElement('div');
    picker.className = 'mc-flag-picker';
    var categories = [
      ['robotic',      'Robotic / one-word'],
      ['hollow',       'Hollow / no substance'],
      ['wrong',        'Wrong info / hallucination'],
      ['sycophantic',  'Sycophantic / soft'],
      ['capitulation', 'Capitulation / negotiating'],
      ['repetitive',   'Repetitive / boring'],
      ['other',        'Other'],
    ];
    categories.forEach(function(cat) {
      var b = document.createElement('button');
      b.textContent = cat[1];
      b.onclick = function(e) {
        e.stopPropagation();
        submitFlag(bubble, btn, cat[0]);
        picker.remove();
      };
      picker.appendChild(b);
    });
    bubble.appendChild(picker);

    // Click outside to close
    setTimeout(function() {
      function close(ev) {
        if (!picker.contains(ev.target)) {
          picker.remove();
          document.removeEventListener('click', close);
        }
      }
      document.addEventListener('click', close);
    }, 0);
  }

  function submitFlag(bubble, btn, category) {
    // Strip flag button text from coach_text
    var clone = bubble.cloneNode(true);
    clone.querySelectorAll('.mc-flag-btn, .mc-flag-picker').forEach(function(el) { el.remove(); });
    var coachText = (clone.textContent || '').trim();
    var userMessage = getRecentUserMessage(bubble);
    fetch('/api/coach/flag', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        coach_text: coachText,
        user_message: userMessage,
        category: category,
      }),
    }).then(function(r) {
      btn.classList.add('flagged');
      btn.textContent = '✓';
      btn.title = 'Flagged: ' + category;
      setTimeout(function() {
        btn.textContent = '👎';
      }, 1500);
    }).catch(function() {
      btn.title = 'Flag failed — try again';
    });
  }

  // Inject buttons into existing bubbles (already rendered)
  function scan() {
    document.querySelectorAll('.mc-coach-bubble').forEach(injectFlagButton);
  }

  // Watch for new bubbles via MutationObserver
  document.addEventListener('DOMContentLoaded', function() {
    scan();
    var mo = new MutationObserver(function(muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var n = added[j];
          if (n.nodeType !== 1) continue;
          if (n.classList && n.classList.contains('mc-coach-bubble')) {
            injectFlagButton(n);
          } else if (n.querySelectorAll) {
            n.querySelectorAll('.mc-coach-bubble').forEach(injectFlagButton);
          }
        }
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
  });
  // If the script runs after DOMContentLoaded already fired:
  if (document.readyState !== 'loading') {
    setTimeout(scan, 0);
  }
})();

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
let _setSaving = {};     // key: ${week}_${day}_${exIdx}_${setIdx}, value: true while toggleSet API call in flight
let _restTimerInterval = null;
let _exerciseSwapsLoaded = false;
let _scheduleOverrides = [];
let _mealOverrides = [];
let _runOverrides = [];
let _morningCheckinDone = false;
let _focusExIdx = null;
let _focusRealExIdx = null;
let _focusSetIdx = null;
let _focusSetCount = null;
let _focusExName = '';
let _focusRestSec = 60;
let _focusTargetReps = 10;
let _focusWeightVal = '';
let _focusLastWeight = null;
let _focusTimerInterval = null;
let _workoutActive = false;
let _workoutStartTime = null;
let _workoutExercises = [];
let _workoutExIdx = 0;
let _advancePending = false;

// ─── STATE ──────────────────────────────────────────────────────────────────
let workoutData = {};
let currentPhase = 1;
let currentWeek = 1;
let currentDay = null;
let garminConnected = false; // Garmin disabled
let garminData = null;
let _wellnessToday = null; // most-recent GarminWellness row (today's if present, else latest in the last 7 days; rendered with a date tag when not today)
let readinessData = null;
let _chatOverlayOpen = false;
let _chatScrollPos = null;
let _mealDetailExpanded = false;
let _milestonesShownThisSession = new Set();

const WEEK_TO_PHASE = {1:1,2:1,3:1,4:1,5:2,6:2,7:2,8:2,9:3,10:3,11:3,12:3};

// ALWAYS bodyweight — no weight input regardless of gym access
const _BW_ALWAYS = [
  'Push-Ups', 'Push-ups', 'Push Ups', 'Pushups',
  'Decline Push-Ups', 'Pike Push-Ups', 'Diamond Push-Ups', 'Clap Push-Ups',
  'Pull-Ups', 'Pull-ups', 'Pull Ups', 'Chin-Ups', 'Chin-ups',
  'Ring Row', 'Inverted Row', 'Inverted Row (table/ledge)', 'Inverted Row (table edge)', 'TRX Row',
  'Dips', 'Bench Dips', 'Tricep Dips', 'Tricep Dips (chair/bench)', 'Tricep Dips (chair)',
  'Plank', 'Plank Shoulder Taps', 'Side Plank', 'Hollow Hold', 'Dead Bug',
  'Mountain Climbers', 'Bird Dog', 'Superman', 'L-Sit', 'L Sit',
  'Hanging Leg Raises', 'Hanging Knee Raises',
  'Ab Wheel Rollout', 'Ab Wheel Rollouts', 'Ab Wheel',
  'Bodyweight Squats', 'Jump Squats', 'Pistol Squat (or assisted)',
  'Squat Jump', 'Squat Jumps', 'Lunge Jump', 'Lunge Jumps',
  'Bodyweight Lunges', 'Glute Bridges', 'Wall Sit', 'Burpees',
  'Band Pull-Apart', 'Band Curl', 'Band Row', 'Band Face Pull',
  'Band Lateral Raise', 'Band Tricep Extension', 'Band Seated Row',
  'Band Tricep Pushdown',
];
// BW ONLY when user has no gym — gym users get weight inputs for these
const _BW_NO_GYM_ONLY = [
  'Bulgarian Split Squat', 'Bulgarian Split Squats',
  'Walking Lunge', 'Walking Lunges',
  'Step-Up', 'Step Up',
  'Single-Leg Glute Bridge', 'Single Leg Glute Bridge',
  'Hip Thrust', 'Nordic Hamstring Curl', 'Standing Calf Raise',
];
const _BW_ALWAYS_NORM = new Set(_BW_ALWAYS.map(n => n.toLowerCase().replace(/[-()\/]/g, '').replace(/\s+/g, ' ').trim()));
const _BW_NOGYM_NORM = new Set(_BW_NO_GYM_ONLY.map(n => n.toLowerCase().replace(/[-()\/]/g, '').replace(/\s+/g, ' ').trim()));
const BODYWEIGHT_EXERCISES = new Set(_BW_ALWAYS); // legacy compat

function isBodyweightExercise(name, note) {
  if (!name) return false;
  var normalized = name.toLowerCase().replace(/[-()\/]/g, '').replace(/\s+/g, ' ').trim();
  // Always BW regardless of gym
  if (_BW_ALWAYS_NORM.has(normalized)) return true;
  // BW only for no-gym users
  if (_BW_NOGYM_NORM.has(normalized)) {
    var bwOnly = sessionStorage.getItem('bw_only_mode') === 'true';
    var pa = window._paCache || {};
    var hasGym = pa.has_gym !== false && !bwOnly;
    if (!hasGym) return true;
    return false; // gym user — show weight input
  }
  // Intentionally NOT note-based: notes like "BW 4×6-10 if not yet weighted"
  // for Weighted Pull-Up were falsely flipping the whole exercise to BW-only.
  // The exercise list above is the source of truth.
  return false;
}

// ── PER-EXERCISE WHY (planning HTML cards) ──
// Deterministic 1-sentence rationale tied to exercise role + delta + phase.
// No model call — pure mapping. Drives the per-row italic blurb under each
// exercise on the weekly-planning day card.
var _ROLE_PATTERNS = [
  // Order matters: more specific patterns FIRST. "Romanian Deadlift" must
  // match posterior_chain before the broader "deadlift" hits main_compound.
  { re: /romanian deadlift|stiff.leg|good morning|hip thrust|glute bridge/i, role: 'posterior_chain' },
  { re: /barbell back squat|front squat|conventional deadlift|bench press|overhead press/i, role: 'main_compound' },
  { re: /power clean|hang clean|snatch|clean and jerk/i, role: 'oly' },
  { re: /box jump|broad jump|depth jump/i, role: 'plyo' },
  { re: /bulgarian|split squat|lunge|step.up|pistol/i, role: 'unilateral_leg' },
  { re: /pull.up|chin.up|lat pulldown|row(?!ing)/i, role: 'pull' },
  { re: /face pull|rear delt|reverse fly|band pull.apart/i, role: 'rear_delt' },
  { re: /lateral raise|side raise/i, role: 'lateral_delt' },
  { re: /curl(?!.up)|preacher|hammer curl/i, role: 'biceps' },
  { re: /pushdown|tricep|skullcrush|dip(?!s)/i, role: 'triceps' },
  { re: /chest fly|cable fly|pec deck|chest cross/i, role: 'chest_iso' },
  { re: /leg curl|hamstring curl/i, role: 'hamstring_iso' },
  { re: /leg extension|quad extension/i, role: 'quad_iso' },
  { re: /calf raise|calf press/i, role: 'calf' },
  { re: /pallof|anti.rotat|woodchop|farmers/i, role: 'anti_rotation' },
  { re: /plank|hollow|dead bug|hanging leg|ab wheel|crunch|sit.up|bird dog/i, role: 'core' },
  { re: /run|sprint|tempo|interval/i, role: 'run' },
];

function _exerciseRole(name) {
  if (!name) return 'accessory';
  for (var i = 0; i < _ROLE_PATTERNS.length; i++) {
    if (_ROLE_PATTERNS[i].re.test(name)) return _ROLE_PATTERNS[i].role;
  }
  return 'accessory';
}

function _isDeloadWeek(week) { return week === 4 || week === 8; }

function exerciseWhy(name, ex, prev, week) {
  var role = _exerciseRole(name);
  var deload = _isDeloadWeek(week);
  // Determine delta direction
  var delta = 'hold';
  if (deload) {
    delta = 'deload';
  } else if (prev && prev.weight && ex.target_weight) {
    var dw = ex.target_weight - prev.weight;
    var dr = (parseInt(ex.reps) || 0) - (parseInt(prev.reps) || 0);
    if (dw > 0) delta = 'up_weight';
    else if (dw < 0) delta = 'down_weight';
    else if (dr > 0) delta = 'up_reps';
    else if (dr < 0) delta = 'down_reps';
  } else if (ex.target_weight && (!prev || !prev.weight)) {
    delta = 'establish';
  }

  // Role × delta → reason. Default: short generic accessory line.
  var WHY = {
    main_compound: {
      up_weight: 'Strength anchor — moving the ceiling holds lean mass under the cut.',
      hold: 'Top-set holds while accessories progress around it. Pattern lock.',
      up_reps: 'Volume bump on the same load — earns the next weight jump.',
      down_weight: 'Pulled back vs last week — recovery or technique reset.',
      deload: 'Deload — 70-85% of working weight to clear fatigue before next phase.',
      establish: 'Setting the working weight. Confirm RPE 7 before bumping.',
    },
    oly: {
      up_weight: 'Power output bump — speed off the floor matters more than load here.',
      hold: 'Technique-priority — refining bar path before adding weight.',
      deload: 'Lighter speed work — keep the pattern crisp, drop intensity.',
      establish: 'Build the position first. Speed > load until the catch is clean.',
    },
    plyo: {
      up_weight: 'CNS primer — explosive opener for the heavy lower work that follows.',
      up_reps: 'CNS primer — more contacts, same intent: snap off the ground.',
      hold: 'CNS primer for the heavy lower session.',
      deload: 'Reduced volume — keep the spring without the fatigue.',
      establish: 'CNS primer. Quality over quantity — every rep should be max-intent.',
    },
    unilateral_leg: {
      up_weight: 'Single-leg strength — defends hips and corrects asymmetries while the cut runs.',
      hold: 'Unilateral pattern lock — preserves single-leg strength while bilateral lifts progress.',
      up_reps: 'More volume per side — durability work before the load comes back up.',
      deload: 'Deload — drop load, keep the pattern.',
      establish: 'Single-leg baseline. Match left and right within 1 rep.',
    },
    posterior_chain: {
      up_weight: 'Posterior chain volume — protects the squat and locks in hamstring/glute strength.',
      hold: 'Hinge pattern lock at RPE 7 — recomp anchor as waist tightens and hips hold.',
      up_reps: 'Hinge volume up — building the engine for the next strength block.',
      deload: 'Deload — preserve the pattern, drop the load.',
      establish: 'Hinge baseline. Hips back, neutral spine, RPE 7.',
    },
    pull: {
      up_weight: 'Pulling strength — back size + posture, supports every press.',
      hold: 'Pull volume held — back doesn\'t need a bump every week.',
      up_reps: 'More reps — earning the next weight bump on pulls.',
      deload: 'Deload — back recovers, set up for the next progression.',
      establish: 'Set the working pull weight. Lats first, biceps last.',
    },
    rear_delt: {
      up_weight: 'Rear-delt detail — keeps shoulders healthy under heavy press volume.',
      hold: 'Posture work — keeps the rear delts firing while bigger lifts progress.',
      up_reps: 'More volume on rear delts — small accessory, big posture impact.',
      deload: 'Deload — light maintenance for rear delts.',
      establish: 'Rear delts and external rotators — set a sustainable weight.',
    },
    lateral_delt: {
      up_weight: 'Shoulder cap volume — small accessories never get more than 2.5 lb at a time.',
      hold: 'Lateral raise hold — accessory progression is slow by design.',
      up_reps: 'More reps — earning the next 2.5 lb bump.',
      deload: 'Deload — light shoulder maintenance.',
      establish: 'Lateral raise baseline. Light, controlled, no swing.',
    },
    biceps: {
      up_weight: 'Biceps volume — supports pulls and adds arm size during recomp.',
      hold: 'Biceps hold — small accessory, slow progression.',
      up_reps: 'More volume — building before the next weight bump.',
      deload: 'Deload — light arm maintenance.',
      establish: 'Biceps baseline. Strict form > load.',
    },
    triceps: {
      up_weight: 'Triceps volume — drives pressing strength and arm size.',
      hold: 'Triceps hold — accessory progression is slow.',
      up_reps: 'More volume — earning the next jump.',
      deload: 'Deload — light maintenance.',
      establish: 'Triceps baseline. Lock out clean, no momentum.',
    },
    chest_iso: {
      up_weight: 'Chest detail volume — supports bench progression and adds upper-body size.',
      hold: 'Chest fly hold — main pressing carries the week.',
      up_reps: 'More volume — pec hypertrophy stimulus.',
      deload: 'Deload — light chest maintenance.',
      establish: 'Chest fly baseline. Stretch the pec, no shoulder roll.',
    },
    hamstring_iso: {
      up_weight: 'Hamstring isolation — knee health and posterior chain detail.',
      hold: 'Hamstring hold — accessory.',
      up_reps: 'More volume — hamstring durability.',
      deload: 'Deload — light maintenance.',
      establish: 'Hamstring baseline. Slow eccentric.',
    },
    quad_iso: {
      up_weight: 'Quad isolation — knee health and quad detail.',
      hold: 'Quad iso hold — main lower work carries the load.',
      up_reps: 'More volume — quad hypertrophy.',
      deload: 'Deload — light maintenance.',
      establish: 'Quad baseline. Squeeze at the top.',
    },
    calf: {
      up_weight: 'Calf volume — small driver, big aesthetic and ankle health payoff.',
      hold: 'Calf hold.',
      up_reps: 'More volume — calf hypertrophy.',
      deload: 'Deload — light.',
      establish: 'Calf baseline.',
    },
    anti_rotation: {
      up_weight: 'Anti-rotation core — protects the spine under loaded carries and unilateral work.',
      hold: 'Core anti-rotation hold — protects every other lift.',
      up_reps: 'More volume — building deep-core endurance.',
      deload: 'Deload — light core.',
      establish: 'Anti-rotation baseline. Brace, don\'t crunch.',
    },
    core: {
      hold: 'Core volume — keeps the trunk strong under everything else.',
      up_reps: 'More volume — building core endurance.',
      deload: 'Deload — light core work.',
      establish: 'Core baseline. Quality contractions.',
      up_weight: 'Loaded core — supports heavy compound work.',
    },
    accessory: {
      up_weight: 'Accessory bump — small driver of overall progression.',
      hold: 'Accessory hold — main lifts carry the week.',
      up_reps: 'More volume — building before the next weight jump.',
      deload: 'Deload — light maintenance.',
      establish: 'Accessory baseline.',
    },
  };
  var byRole = WHY[role] || WHY.accessory;
  return byRole[delta] || byRole.hold || '';
}

// ── STATS PANEL: CLIENT-SIDE FORMULAS ──

/**
 * Compute TDEE using Mifflin-St Jeor equation.
 * @param {number} weightLbs - Body weight in pounds
 * @param {number} heightIn - Height in inches
 * @param {number} age - Age in years
 * @param {string} sex - "male" or "female"
 * @param {number} [activityMultiplier=1.55] - Activity factor
 * @returns {{bmr: number, tdee: number}}
 */
function _computeTdee(weightLbs, heightIn, age, sex, activityMultiplier) {
  if (activityMultiplier === undefined) activityMultiplier = 1.55;
  var weightKg = weightLbs / 2.205;
  var heightCm = heightIn * 2.54;
  var bmr;
  if (sex === "male") {
    bmr = 10 * weightKg + 6.25 * heightCm - 5 * age - 5;
  } else {
    bmr = 10 * weightKg + 6.25 * heightCm - 5 * age - 161;
  }
  var tdee = bmr * activityMultiplier;
  return { bmr: Math.round(bmr), tdee: Math.round(tdee) };
}

/**
 * Compute daily macro targets based on goal type.
 * @param {number} tdee - Total daily energy expenditure in calories
 * @param {string} goalType - "cut", "bulk", or "recomp"
 * @param {number} weightLbs - Current body weight in pounds
 * @param {number} targetWeight - Goal weight in lbs
 * @param {number} [weeks=12] - Weeks remaining in program
 * @returns {{calories: number, protein: number, carbs: number, fat: number}}
 */
function _computeTargets(tdee, goalType, weightLbs, targetWeight, weeks) {
  if (weeks === undefined) weeks = 12;
  var protein, fat, calories, proteinCal, fatCal, remainingCal, carbs;

  if (goalType === "cut") {
    protein = Math.round(1.0 * weightLbs);
    fat = Math.round(0.3 * weightLbs);
    if (targetWeight && targetWeight < weightLbs && weeks > 0) {
      var weightToLose = weightLbs - targetWeight;
      var requiredWeekly = weightToLose / weeks;
      var requiredDailyDeficit = (requiredWeekly * 3500) / 7;
      calories = Math.max(Math.round(tdee - requiredDailyDeficit), 1200);
    } else {
      calories = Math.max(Math.round(tdee * 0.65), 1200);
    }
    proteinCal = protein * 4;
    fatCal = fat * 9;
    remainingCal = Math.max(calories - proteinCal - fatCal, 0);
    carbs = Math.max(Math.floor(remainingCal / 4), 20);
  } else if (goalType === "bulk") {
    calories = Math.round(tdee + 400);
    protein = Math.round(1.0 * weightLbs);
    fat = Math.round(0.4 * weightLbs);
    proteinCal = protein * 4;
    fatCal = fat * 9;
    remainingCal = Math.max(calories - proteinCal - fatCal, 0);
    carbs = Math.floor(remainingCal / 4);
  } else if (goalType === "recomp") {
    calories = Math.round(tdee - 100);
    protein = Math.round(1.2 * weightLbs);
    fat = Math.round(0.35 * weightLbs);
    proteinCal = protein * 4;
    fatCal = fat * 9;
    remainingCal = Math.max(calories - proteinCal - fatCal, 0);
    carbs = Math.floor(remainingCal / 4);
  } else {
    // Fallback to cut
    return _computeTargets(tdee, "cut", weightLbs, targetWeight, weeks);
  }

  return { calories: calories, protein: protein, carbs: carbs, fat: fat };
}

/**
 * Project week-by-week weight change with metabolic modeling.
 * Models water/glycogen effects weeks 1-2, recalculates BMR as weight
 * changes, and factors in training adaptation.
 * @param {number} startWeight - Starting weight in lbs
 * @param {number} targetWeight - Target weight in lbs
 * @param {number} tdee - Starting TDEE in calories
 * @param {number} dailyCal - Daily calorie intake target
 * @param {number} [weeks=12] - Number of weeks to project
 * @param {number} [heightIn=70] - Height in inches (for BMR recalc)
 * @param {number} [age=30] - Age in years (for BMR recalc)
 * @param {string} [sex="male"] - "male" or "female" (for BMR recalc)
 * @returns {Array<{week: number, projected: number, tdee: number}>}
 */
function _projectWeightCurve(startWeight, targetWeight, tdee, dailyCal, weeks, heightIn, age, sex, programWeekOffset) {
  if (weeks === undefined) weeks = 12;
  if (heightIn === undefined) heightIn = 70;
  if (age === undefined) age = 30;
  if (sex === undefined) sex = "male";
  if (programWeekOffset === undefined) programWeekOffset = 0;

  var projection = [];
  var currentWeight = startWeight;
  var currentTdee = tdee;
  var gaining = dailyCal > tdee; // bulk mode

  for (var week = 1; week <= weeks; week++) {
    var absoluteWeek = week + programWeekOffset;

    // Daily deficit/surplus
    var dailyDeltaCal = dailyCal - currentTdee;

    // Convert to lbs: 3500 cal = 1 lb of fat
    var weeklyDeltaLbs = (dailyDeltaCal * 7) / 3500;

    // Water/glycogen boost: continuous decay rather than a hard week-2 cliff.
    // weight = 1 + 0.5*exp(-(absWeek-1)/1.5) for cuts, so absWeek=1 → 1.5x,
    // absWeek=2 → ~1.26x, absWeek=4 → ~1.07x, absWeek=8+ → ~1.0x. No kink.
    if (!gaining) {
      weeklyDeltaLbs *= 1 + 0.5 * Math.exp(-(absoluteWeek - 1) / 1.5);
    } else {
      weeklyDeltaLbs *= 1 + 0.3 * Math.exp(-(absoluteWeek - 1) / 1.5);
    }

    // Training adaptation: smooth logistic ramp to +100 cal/day, centered at
    // absolute week 5. No step function, no piecewise cap.
    var adaptationBump = 100 / (1 + Math.exp(-(absoluteWeek - 5) / 1.2));

    currentWeight += weeklyDeltaLbs;
    currentWeight = Math.round(currentWeight * 10) / 10;

    // Recalculate TDEE based on new weight
    var newBmrData = _computeTdee(currentWeight, heightIn, age, sex);
    currentTdee = newBmrData.tdee + adaptationBump;

    projection.push({
      week: week,
      projected: currentWeight,
      tdee: currentTdee,
    });
  }

  return projection;
}

/**
 * Estimate body fat percentage using the US Navy circumference method.
 * @param {number} waist - Waist circumference in inches
 * @param {number} neck - Neck circumference in inches
 * @param {number} heightIn - Height in inches
 * @param {string} sex - "male" or "female"
 * @param {number} [hips] - Hip circumference in inches (required for female)
 * @returns {number|null} Estimated body fat percentage, or null if inputs invalid
 */
function _estimateBodyFatNavy(waist, neck, heightIn, sex, hips) {
  if (!waist || !neck || !heightIn) return null;
  if (waist <= neck) return null;

  try {
    var bf;
    if (sex === "female") {
      if (!hips) return null;
      bf = 163.205 * Math.log10(waist + hips - neck) - 97.684 * Math.log10(heightIn) - 78.387;
    } else {
      bf = 86.010 * Math.log10(waist - neck) - 70.041 * Math.log10(heightIn) + 36.76;
    }
    return Math.round(Math.max(3.0, Math.min(50.0, bf)) * 10) / 10;
  } catch (e) {
    return null;
  }
}

/**
 * Strength percentile lookup tables.
 * General population 1RM / bodyweight ratios by percentile.
 * Derived from PubMed study of 809,986 powerlifting entries,
 * adjusted down ~1.5x for general population.
 */
var _STRENGTH_PERCENTILES = {
  male: {
    "Barbell Bench Press": {
      percentiles: [[10, 0.40], [25, 0.57], [50, 0.80], [75, 1.03], [90, 1.30], [95, 1.50]],
    },
    "Barbell Back Squat": {
      percentiles: [[10, 0.55], [25, 0.83], [50, 1.17], [75, 1.50], [90, 1.89], [95, 2.20]],
    },
    "Conventional Deadlift": {
      percentiles: [[10, 0.70], [25, 1.00], [50, 1.33], [75, 1.67], [90, 2.17], [95, 2.50]],
    },
    "Barbell Bent-Over Row": {
      percentiles: [[10, 0.35], [25, 0.50], [50, 0.70], [75, 0.90], [90, 1.10], [95, 1.25]],
    },
    "DB Overhead Press": {
      percentiles: [[10, 0.20], [25, 0.30], [50, 0.45], [75, 0.60], [90, 0.75], [95, 0.85]],
    },
    "Barbell OHP": {
      percentiles: [[10, 0.25], [25, 0.40], [50, 0.55], [75, 0.70], [90, 0.85], [95, 1.00]],
    },
    "Lat Pulldown": {
      percentiles: [[10, 0.35], [25, 0.50], [50, 0.65], [75, 0.85], [90, 1.00], [95, 1.15]],
    },
    "Barbell Hip Thrust": {
      percentiles: [[10, 0.50], [25, 0.75], [50, 1.00], [75, 1.35], [90, 1.70], [95, 2.00]],
    },
    "EZ-Bar Curl": {
      percentiles: [[10, 0.15], [25, 0.25], [50, 0.35], [75, 0.45], [90, 0.55], [95, 0.65]],
    },
    "Cable Tricep Pushdown": {
      percentiles: [[10, 0.15], [25, 0.22], [50, 0.30], [75, 0.40], [90, 0.50], [95, 0.55]],
    },
  },
  female: {
    "Barbell Bench Press": {
      percentiles: [[10, 0.25], [25, 0.38], [50, 0.55], [75, 0.72], [90, 0.90], [95, 1.05]],
    },
    "Barbell Back Squat": {
      percentiles: [[10, 0.40], [25, 0.60], [50, 0.85], [75, 1.10], [90, 1.40], [95, 1.65]],
    },
    "Conventional Deadlift": {
      percentiles: [[10, 0.50], [25, 0.75], [50, 1.00], [75, 1.30], [90, 1.65], [95, 1.95]],
    },
    "Barbell Bent-Over Row": {
      percentiles: [[10, 0.25], [25, 0.35], [50, 0.50], [75, 0.65], [90, 0.80], [95, 0.95]],
    },
    "DB Overhead Press": {
      percentiles: [[10, 0.12], [25, 0.20], [50, 0.30], [75, 0.42], [90, 0.55], [95, 0.65]],
    },
  },
};

/**
 * Age adjustment factors (relative to 18-35 peak).
 */
var _AGE_FACTORS = [
  [0, 18, 0.75],
  [18, 35, 1.00],
  [35, 45, 0.95],
  [45, 55, 0.88],
  [55, 65, 0.80],
  [65, 100, 0.70],
];

function _getAgeFactor(age) {
  for (var i = 0; i < _AGE_FACTORS.length; i++) {
    var lo = _AGE_FACTORS[i][0];
    var hi = _AGE_FACTORS[i][1];
    var factor = _AGE_FACTORS[i][2];
    if (lo <= age && age < hi) return factor;
  }
  return 0.85;
}

/**
 * Compute population percentile for a given 1RM.
 * @param {number} oneRm - Estimated one-rep max in lbs
 * @param {number} bodyWeight - Body weight in lbs
 * @param {string} exercise - Exercise name
 * @param {number} age - Age in years
 * @param {string} sex - "male" or "female"
 * @returns {{percentile: number, relativeStrength: number, rating: string}}
 */
function _compute1rmPercentile(oneRm, bodyWeight, exercise, age, sex) {
  if (!oneRm || !bodyWeight || bodyWeight <= 0) {
    return { percentile: 0, relativeStrength: 0, rating: "Unknown" };
  }

  var relative = oneRm / bodyWeight;
  var ageFactor = _getAgeFactor(age);
  // Adjust relative strength for age -- older lifters get credit
  var adjustedRelative = relative / ageFactor;

  var sexData = _STRENGTH_PERCENTILES[sex] || _STRENGTH_PERCENTILES["male"];
  var exData = sexData[exercise] || null;
  if (!exData) {
    // Try to find closest match
    var keys = Object.keys(sexData);
    for (var k = 0; k < keys.length; k++) {
      if (keys[k].toLowerCase().indexOf(exercise.toLowerCase()) !== -1 ||
          exercise.toLowerCase().indexOf(keys[k].toLowerCase()) !== -1) {
        exData = sexData[keys[k]];
        break;
      }
    }
  }
  if (!exData) {
    return { percentile: 50, relativeStrength: Math.round(relative * 100) / 100, rating: "N/A" };
  }

  var percentiles = exData.percentiles;

  // Interpolate percentile
  var pct = 5; // below minimum
  var matched = false;
  for (var i = 0; i < percentiles.length; i++) {
    var p = percentiles[i][0];
    var ratio = percentiles[i][1];
    if (adjustedRelative <= ratio) {
      if (i === 0) {
        pct = Math.max(1, Math.floor(p * adjustedRelative / ratio));
      } else {
        var prevP = percentiles[i - 1][0];
        var prevR = percentiles[i - 1][1];
        var frac = (ratio !== prevR) ? (adjustedRelative - prevR) / (ratio - prevR) : 0;
        pct = Math.floor(prevP + frac * (p - prevP));
      }
      matched = true;
      break;
    }
  }
  if (!matched) {
    var lastP = percentiles[percentiles.length - 1][0];
    var lastR = percentiles[percentiles.length - 1][1];
    pct = Math.min(99, Math.floor(lastP + (adjustedRelative - lastR) * 10));
  }

  // Rating
  var rating;
  if (pct >= 90) {
    rating = "Elite";
  } else if (pct >= 75) {
    rating = "Advanced";
  } else if (pct >= 50) {
    rating = "Intermediate";
  } else if (pct >= 25) {
    rating = "Novice";
  } else {
    rating = "Beginner";
  }

  return {
    percentile: Math.max(1, Math.min(99, pct)),
    relativeStrength: Math.round(relative * 100) / 100,
    rating: rating,
  };
}

/**
 * Compute the phase split for the 12-week program.
 * @param {string} goalType - "cut", "bulk", or "recomp"
 * @param {number} startingWeight - Current weight in lbs
 * @param {number} targetWeight - Goal weight in lbs
 * @param {number} [startingBf] - Estimated starting body fat as decimal (e.g. 0.25)
 * @returns {Array<{weeks: string, type: string, weekly_rate: number, notes: string}>}
 */
function _computePhasePlan(goalType, startingWeight, targetWeight, startingBf) {
  var totalChange = targetWeight - startingWeight; // negative for cut
  var weeklyRate = Math.abs(totalChange) / 12;

  var phases = [];

  if (goalType === "cut") {
    if (weeklyRate <= 3.0) {
      // Manageable deficit -- straight 12-week cut
      phases.push({
        weeks: "1-12",
        type: "cut",
        weekly_rate: Math.round(weeklyRate * 10) / 10,
        notes: "Straight cut: " + Math.abs(totalChange).toFixed(0) + " lbs in 12 weeks " +
               "(" + weeklyRate.toFixed(1) + " lbs/week).",
      });
    } else {
      // Extreme deficit -- break into aggressive phases
      var p1Rate = weeklyRate * 1.3;
      var p3Rate = weeklyRate * 1.1;
      var p2Rate = weeklyRate * 0.7;
      phases.push({
        weeks: "1-4",
        type: "aggressive_cut",
        weekly_rate: Math.round(p1Rate * 10) / 10,
        notes: "Aggressive fasting phase. OMAD or 20:4. " +
               "Electrolyte supplementation required. " +
               "High protein to preserve muscle.",
      });
      phases.push({
        weeks: "5-8",
        type: "cut",
        weekly_rate: Math.round(p2Rate * 10) / 10,
        notes: "Moderate cut with weekly refeed day. " +
               "18:6 fasting. Prevents metabolic adaptation.",
      });
      phases.push({
        weeks: "9-12",
        type: "aggressive_cut",
        weekly_rate: Math.round(p3Rate * 10) / 10,
        notes: "Final push. Tighten up for the finish. " +
               "20:4 fasting. Visual results lock in here.",
      });
    }
  } else if (goalType === "bulk") {
    if (startingBf !== undefined && startingBf !== null && startingBf > 0.20) {
      // Too fat to bulk right away -- mini cut first
      phases.push({
        weeks: "1-4",
        type: "cut",
        weekly_rate: 2.0,
        notes: "Mini-cut first. Starting BF " + (startingBf * 100).toFixed(0) + "% " +
               "is too high to bulk cleanly. Drop to ~18% then bulk.",
      });
      phases.push({
        weeks: "5-12",
        type: "bulk",
        weekly_rate: totalChange > 0 ? Math.round((Math.abs(totalChange) / 8) * 10) / 10 : 0.5,
        notes: "Clean bulk phase. Surplus of 300-500 cal. " +
               "Progressive overload focus.",
      });
    } else {
      phases.push({
        weeks: "1-12",
        type: "bulk",
        weekly_rate: Math.round(weeklyRate * 10) / 10,
        notes: "Straight bulk: " + totalChange.toFixed(0) + " lbs in 12 weeks. " +
               "Controlled surplus, progressive overload.",
      });
    }
  } else if (goalType === "recomp") {
    phases.push({
      weeks: "1-12",
      type: "recomp",
      weekly_rate: Math.round(weeklyRate * 10) / 10,
      notes: "12-week recomp. Slight deficit on rest days, " +
             "maintenance on training days. Body composition " +
             "shifts without dramatic scale change.",
    });
  }

  return phases;
}

// ─── ACCORDION STATE ───
const _accordionState = JSON.parse(sessionStorage.getItem('accordion_state') || '{}');

function renderAccordion(id, title, contentHtml, defaultOpen) {
    if (defaultOpen === undefined) defaultOpen = false;
    const isOpen = _accordionState[id] !== undefined ? _accordionState[id] : defaultOpen;
    return '<div class="accordion-section' + (isOpen ? ' open' : '') + '" id="acc-' + id + '">' +
      '<button class="accordion-toggle" onclick="toggleAccordion(\'' + id + '\')">' +
        '<h3>' + title + '</h3>' +
        '<span class="accordion-arrow">' + (isOpen ? '\u25B2' : '\u25BC') + '</span>' +
      '</button>' +
      '<div class="accordion-body' + (isOpen ? ' visible' : '') + '" id="acc-body-' + id + '">' +
        contentHtml +
      '</div>' +
    '</div>';
}

function toggleAccordion(id) {
    const section = document.getElementById('acc-' + id);
    const body = document.getElementById('acc-body-' + id);
    if (!section || !body) return;
    const isOpen = section.classList.toggle('open');
    body.classList.toggle('visible');
    _accordionState[id] = isOpen;
    sessionStorage.setItem('accordion_state', JSON.stringify(_accordionState));
    const arrow = section.querySelector('.accordion-arrow');
    if (arrow) arrow.textContent = isOpen ? '\u25B2' : '\u25BC';
}

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
    if (!message) return;
    _chatHistory.push({ role: 'assistant', content: message, date: todayStr(), time: new Date().toISOString() });
    renderDetail();
    var accSection = document.getElementById('acc-coach');
    if (accSection) {
        if (!accSection.classList.contains('open')) toggleAccordion('coach');
        accSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function sendOpenerReply() {
    return;
}

function dismissCoachPopup() {
    return;
}

// Dedup: prevent duplicate popups per day
function hasPopupFired(key) {
  return localStorage.getItem('popup_' + key + '_' + todayStr()) === '1';
}
function markPopupFired(key) {
  localStorage.setItem('popup_' + key + '_' + todayStr(), '1');
}

async function showPreStartLockout(startDateStr) {
  const startDate = new Date(startDateStr + 'T00:00:00');
  const now = new Date();
  const diffMs = startDate - now;
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  const dateLabel = startDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

  // Fetch Week 1 schedule for preview
  var previewHtml = '';
  try {
    const wkRes = await fetch('/api/workouts');
    if (wkRes.ok) {
      const wkData = await wkRes.json();
      const week1 = wkData['1'];
      if (week1 && week1.days) {
        const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
        var schedRows = '';
        for (var di = 0; di < Math.min(week1.days.length, 7); di++) {
          var dd = week1.days[di];
          var liftName = dd.liftName || (dd.isRest ? 'Rest' : 'Workout');
          var runInfo = dd.run ? dd.run.label + ' ' + dd.run.time : '';
          var exCount = (dd.exercises || []).length;
          var mealInfo = dd.mealPlan ? (dd.mealPlan.targetCal || dd.mealPlan.label || '') : '';
          schedRows += '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #2a2e2c">' +
            '<div><span style="color:#4ade80;font-weight:600;font-size:13px">' + dayNames[di].slice(0,3) + '</span> <span style="color:#e8ede9;font-size:13px">' + liftName + '</span>' +
            (exCount > 0 ? '<span style="color:#6b7280;font-size:11px;margin-left:6px">' + exCount + ' exercises</span>' : '') + '</div>' +
            '<span style="color:#6b7280;font-size:12px;font-family:\'DM Mono\',monospace">' + runInfo + '</span>' +
          '</div>';
        }
        previewHtml = '<div style="margin-top:1.5rem;text-align:left">' +
          '<div style="font-family:\'DM Mono\',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;margin-bottom:8px">WEEK 1 PREVIEW</div>' +
          schedRows +
          '<button onclick="showGroceryListPreStart()" style="width:100%;margin-top:12px;background:#1a2e24;border:1px solid #3a7a56;color:#4ade80;padding:10px;border-radius:8px;font-size:14px;cursor:pointer;font-family:\'DM Mono\',monospace">View Grocery List</button>' +
        '</div>';
      }
    }
  } catch(e) {}

  document.body.innerHTML = `
    <div style="min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:2rem;text-align:center;background:#0d0f0e;color:#e8ede9">
      <div style="max-width:420px;width:100%;padding-top:2rem">
        <div style="font-family:'DM Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;margin-bottom:1rem">COACH ERIK</div>
        <h1 style="font-size:1.8rem;font-weight:700;margin-bottom:0.5rem">YOUR PROGRAM STARTS</h1>
        <div style="font-size:1.4rem;color:#4ade80;font-weight:600;margin-bottom:1.5rem">${dateLabel}</div>
        <div style="font-family:'DM Mono',monospace;font-size:3rem;font-weight:800;color:#4ade80;margin-bottom:0.5rem">${days}d ${hours}h</div>
        <div style="font-size:13px;color:#6b7280;margin-bottom:1.5rem">until Day 1</div>
        <div style="background:#1a2e24;border:2px solid #3a7a56;border-radius:12px;padding:20px;margin-bottom:1rem;text-align:left;font-size:15px;line-height:1.6;color:#e8ede9">
          Rest up. Eat clean. Hydrate. When that clock hits zero, we go. No warm-up period. No easing in. Day 1 is full speed. Be ready.
        </div>
        ${previewHtml}
        <button onclick="localStorage.clear();sessionStorage.clear();window.location='/logout'" style="margin-top:1.5rem;background:none;border:1px solid #3a3f3c;color:#6b7280;padding:10px 24px;border-radius:8px;font-size:14px;cursor:pointer">Logout</button>
      </div>
    </div>`;
}

async function showGroceryListPreStart() {
  try {
    const res = await fetch('/api/shopping-list');
    if (!res.ok) return;
    const data = await res.json();
    var html = '<div style="position:fixed;inset:0;background:rgba(0,0,0,0.9);z-index:9999;overflow-y:auto;padding:2rem">' +
      '<div style="max-width:420px;margin:0 auto">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">' +
        '<h2 style="color:#4ade80;font-size:1.2rem">Grocery List — Week 1</h2>' +
        '<button onclick="this.closest(\'div[style*=fixed]\').remove()" style="background:none;border:none;color:#6b7280;font-size:24px;cursor:pointer">&times;</button>' +
      '</div>';
    if (data.categories) {
      for (var cat in data.categories) {
        html += '<div style="font-family:\'DM Mono\',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;margin:12px 0 6px">' + cat + '</div>';
        for (var ii = 0; ii < data.categories[cat].length; ii++) {
          var item = data.categories[cat][ii];
          html += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #2a2e2c;font-size:14px">' +
            '<span style="color:#e8ede9">' + item.name + '</span>' +
            '<span style="color:#6b7280;font-family:\'DM Mono\',monospace">' + item.amount + '</span></div>';
        }
      }
    } else if (Array.isArray(data)) {
      for (var ji = 0; ji < data.length; ji++) {
        html += '<div style="padding:6px 0;border-bottom:1px solid #2a2e2c;font-size:14px;color:#e8ede9">' + (data[ji].name || data[ji]) + '</div>';
      }
    }
    html += '</div></div>';
    document.body.insertAdjacentHTML('beforeend', html);
  } catch(e) {
    alert('Could not load grocery list.');
  }
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

function stripCoachMarkers(text) {
  // Strip ALL [TAG: ...] and [TAG] markers from coach output
  // Also strip timestamp prefixes like [Apr 07 03:32 PM] or (sent Apr 07 8:32 AM)
  return text.replace(/\[[A-Z_]+(?::[^\]]*)?\]/g, '')
    .replace(/\[\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}\s*(?:AM|PM)\]/gi, '')
    .replace(/\(sent\s+\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}\s*(?:AM|PM)\)/gi, '')
    .replace(/\s{2,}/g, ' ').trim();
}

// cache-buster bump 2026-05-10/v2 — force phone re-fetch for planning WHYs
function renderCoachMarkdown(text) {
  var clean = stripCoachMarkers(text);
  // Unescape literal \n sequences (from SSE transport)
  clean = clean.replace(/\\n/g, '\n');

  // Insert line breaks before known exercise names
  if (window._exerciseNames && window._exerciseNames.length) {
      for (var _en = 0; _en < window._exerciseNames.length; _en++) {
          var exName = window._exerciseNames[_en];
          var escaped = exName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          clean = clean.replace(new RegExp('([.:])\\s+(' + escaped + '\\s*[:—→])', 'g'), '$1\n\n$2');
      }
  }

  // Insert line breaks between exercises using BOUNDARY DETECTION.
  var _colonPat = /:\s*\d+\s*[x×]\s*\d+/g;
  var _cm;
  var _breaks = [];
  while ((_cm = _colonPat.exec(clean)) !== null) {
    var _cpos = _cm.index;
    var _lbStart = Math.max(0, _cpos - 50);
    var _lookback = clean.substring(_lbStart, _cpos);
    var _best = -1;
    var _bp = /(?:lb|reps|hold|UP|HOLD|DOWN|sets|minutes|min)\s/gi;
    var _bm;
    while ((_bm = _bp.exec(_lookback)) !== null) {
      _best = _lbStart + _bm.index + _bm[0].length - 1;
    }
    var _sp = /[.?!]\s/g;
    while ((_bm = _sp.exec(_lookback)) !== null) {
      var _spos = _lbStart + _bm.index + _bm[0].length - 1;
      if (_spos > _best) _best = _spos;
    }
    var _pp = /[)]\s|[*]+\s/g;
    while ((_bm = _pp.exec(_lookback)) !== null) {
      var _ppos = _lbStart + _bm.index + _bm[0].length - 1;
      if (_ppos > _best) _best = _ppos;
    }
    if (_best >= 0 && clean[_best] !== '\n') {
      _breaks.push(_best);
    }
  }
  for (var _bi = _breaks.length - 1; _bi >= 0; _bi--) {
    clean = clean.substring(0, _breaks[_bi]) + '\n' + clean.substring(_breaks[_bi] + 1);
  }

  clean = clean.replace(/\n+((?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*[?.!])/gi, ' $1');
  clean = clean.replace(/([^\n])\s*(?=\*{0,2}(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*[\-—:\*])/g, '$1\n\n');
  clean = clean.replace(/\n[-*]\s*\n/g, '\n');
  clean = clean.replace(/([^\n])\s+(?=(?:Zone \d|HIIT run|Run:|Min mile|Tempo run|Easy run|Long run))/g, '$1\n');
  clean = clean.replace(/([^\n])\s+(?=(?:Any swaps|Any questions|Questions on|Move to|Ready for|Want to))/g, '$1\n\n');
  clean = clean.replace(/\.\s+(?=(?:Anything|Any injuries|Schedule conflicts|Any schedule))/g, '.\n\n');
  clean = clean.replace(/\.\s+(?=(?:You need|Your target|After dropping|Deficit))/g, '.\n\n');

  // Escape HTML
  var safe = clean.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // Bold: **text** → <strong>text</strong>
  safe = safe.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic: *text* → <em>text</em>
  safe = safe.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Line breaks: newlines → <br>
  safe = safe.replace(/\n/g, '<br>');
  return safe;
}

function localTimeContext() {
  var d = new Date();
  var day = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][d.getDay()];
  var time = d.toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});
  return 'RIGHT NOW it is ' + day + ' ' + time + ' local time.';
}

// ─── MEAL TRACKING ─────────────────────────────────────────────────────────
// Calendar date for the currently-viewed week/day. Falls back to today if
// start_date isn't set yet. Keeps per-day meal state separate in _mealsCache.
function getViewDateStr() {
  try {
    const sd = _stateCache && _stateCache.start_date;
    if (!sd || currentWeek == null || currentDay == null) return todayStr();
    const d = new Date(sd + 'T00:00:00');
    d.setDate(d.getDate() + (currentWeek - 1) * 7 + currentDay);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  } catch(e) { return todayStr(); }
}

function getMealDateKey() {
  return getViewDateStr();
}

// Lazy-fetch past-day meal state on demand. Idempotent — only fetches once
// per date. Re-renders the detail panel when the data arrives.
const _mealsFetchInFlight = {};
function ensureMealDataLoaded(dateKey) {
  if (!dateKey) return;
  if (_mealsCache[dateKey]) return;
  if (_mealsFetchInFlight[dateKey]) return;
  _mealsFetchInFlight[dateKey] = true;
  fetch('/api/meals?date=' + encodeURIComponent(dateKey))
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && typeof data === 'object') _mealsCache[dateKey] = data;
    })
    .catch(() => {})
    .finally(() => {
      delete _mealsFetchInFlight[dateKey];
      // Re-render if the viewed day is still the one we fetched for
      if (getMealDateKey() === dateKey) {
        try { renderDetail(); } catch(e) {}
      }
    });
}

function loadMealData() {
  const key = getMealDateKey();
  if (_mealsCache[key]) return _mealsCache[key];
  ensureMealDataLoaded(key);
  return {};
}

function saveMealData(data) {
  const key = getMealDateKey();
  _mealsCache[key] = data;
  // Build per-meal timing: { mealIdx: { scheduled: "2:30pm", actual: "2026-04-01T18:30:00Z" } }
  if (!data.mealTiming) data.mealTiming = {};
  try {
    const weekData = workoutData[String(currentWeek)];
    const dayData = weekData && currentDay !== null ? weekData.days[currentDay] : null;
    const mp = dayData ? dayData.mealPlan : null;
    if (mp && mp.meals && Array.isArray(data.eaten)) {
      const now = new Date().toISOString();
      for (const mealIdx of data.eaten) {
        if (!data.mealTiming[String(mealIdx)] && mp.meals[mealIdx]) {
          data.mealTiming[String(mealIdx)] = {
            scheduled: mp.meals[mealIdx].time || '',
            actual: now,
          };
        }
      }
    }
  } catch(e) {}
  apiPost('/api/meals', { date: key, eaten: Array.isArray(data.eaten) ? data.eaten : [], adjustments: data.adjustments || {}, foodItems: Array.isArray(data.foodItems) ? data.foodItems : [], mealTiming: data.mealTiming || {}, fasting: data.fasting || false })
    .then(r => { if (r && !r.ok) console.error('Meal save failed:', r.status); })
    .catch(e => console.error('Meal save error:', e));
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

function renderMealInner(dayData) {
  const plan = dayData.mealPlan;
  // FAIL LOUD: no static template meals. If the coach hasn't planned this
  // day's meals, say so — never render hardcoded template food as the plan.
  if (!plan && dayData.mealStatus === 'unplanned') {
    return '<div class="plan-missing">' +
        '<div>&#9888; Your coach hasn’t planned these meals yet.</div>' +
        '<button class="btn btn-primary" style="width:100%;margin-top:10px" onclick="launchWeeklyPlanning(currentWeek)">Plan this week</button>' +
    '</div>';
  }
  if (!plan) return '';

  // Determine if we're viewing today's meals
  const todayMonIdx = _userTodayMonIdx();  // user-tz "today", not device-local
  const isViewingToday = currentDay === todayMonIdx;

  // Fast day based on meal type (no toggle — it's the plan)
  const isSundayFast = dayData.mealType && dayData.mealType.toLowerCase().includes('fast');
  // Prefer the SERVER's fast-day plan (real foods/calories — e.g. a protein-
  // sparing 130-cal whey day); only fall back to the hardcoded water-only card
  // if the server provided nothing. Don't discard the real plan.
  const activePlan = plan || (isSundayFast ? (window._mealPlansCache || {}).fast_day : null);

  let totalEaten = { cal: 0, protein: 0, carbs: 0, fat: 0 };
  let mealsHtml = '';

  const meals = activePlan.meals || [];
  meals.forEach((meal, idx) => {
    // Show saved state on every day. Editing is gated to today separately.
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
      const checkBtn = isViewingToday
        ? `<button class="food-check${foodEaten ? ' checked' : ''}" onclick="toggleFoodItem('${foodKey}',${idx},${meal.foods.length},this)">${foodEaten ? '&#10003;' : ''}</button>`
        : `<span class="food-check${foodEaten ? ' checked' : ''}" style="pointer-events:none;opacity:${foodEaten ? '1' : '0.3'}">${foodEaten ? '&#10003;' : ''}</span>`;
      return `<div class="meal-food-row${foodEaten ? ' food-eaten' : ''}">
        ${checkBtn}
        <span class="meal-food-name">${f.item}</span>
        <span class="meal-food-portion">${f.portion}</span>
        <span class="meal-food-portion">${adjCal}cal</span>
      </div>`;
    }).join('');

    const mealCheck = isViewingToday
      ? `<button class="meal-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx},this)">${eaten ? '&#10003;' : ''}</button>`
      : `<span class="meal-check${eaten ? ' eaten' : ''}" style="pointer-events:none;opacity:${eaten ? '1' : '0.3'}">${eaten ? '&#10003;' : ''}</span>`;
    mealsHtml += `<div class="meal-item${meal.optional ? ' optional' : ''}">
      ${mealCheck}
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

  // Compact row: meal name checkboxes. Today = clickable, past = read-only badges.
  let compactChecks = '';
  meals.forEach((meal, idx) => {
    const eaten = isMealEaten(idx);
    if (isViewingToday) {
      compactChecks += `<button class="meal-compact-check${eaten ? ' eaten' : ''}" onclick="toggleMealEaten(${idx},this)">${eaten ? '&#10003; ' : ''}${meal.name}</button>`;
    } else {
      compactChecks += `<span class="meal-compact-check${eaten ? ' eaten' : ''}" style="pointer-events:none;opacity:${eaten ? '1' : '0.5'}">${eaten ? '&#10003; ' : ''}${meal.name}</span>`;
    }
  });

  const notTodayNote = '';

  // Calorie + deficit summary
  const goalData = window._goalData || {};
  const tdee = goalData.tdee || 0;
  const deficit = tdee > 0 ? tdee - target.cal : 0;
  const deficitStr = deficit > 0 ? `<span style="color:var(--accent);font-size:13px;margin-left:6px">\u2212${deficit} cal deficit</span>`
    : deficit < 0 ? `<span style="color:#4ade80;font-size:13px;margin-left:6px">+${Math.abs(deficit)} cal surplus</span>` : '';
  const calHeader = `<span style="font-family:'DM Mono',monospace;font-size:14px;color:var(--text)">${target.cal} cal</span>${deficitStr}`;

  return `<h3>Meal Plan &middot; ${activePlan.label || ''}</h3>
    ${calHeader ? '<div style="margin:-4px 0 8px 0">' + calHeader + '</div>' : ''}
    ${isSundayFast ? '<div class="meal-plan-note" style="color:var(--accent)">Fast day. Water, black coffee, electrolytes only.</div>' : ''}
    ${!isSundayFast && activePlan.note ? '<div class="meal-plan-note">' + activePlan.note + '</div>' : ''}
    ${notTodayNote}
    ${totalsHtml}
    <div class="meal-compact-row">${compactChecks}</div>
    <div class="meal-detail-body visible">
      <div class="meal-timeline">
        ${mealsHtml}
      </div>
    </div>`;
}

function renderMealSection(dayData) {
    const inner = renderMealInner(dayData);
    if (!inner) return '';
    return '<div class="detail-section meal-section">' + inner + '</div>';
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
  // Weeks 4 & 8 only — week 12 is a PEAK in the engine (training_engine
  // _is_peak_week==12), not a deload. Labeling 12 "Deload/60%" contradicted the
  // full-weight prescription the engine/coach actually generate.
  return week === 4 || week === 8;
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
  if (!rest) return 0;
  const s = String(rest);
  // Use the FIRST value and ITS OWN unit. "90s-2 min" is 90 SECONDS, not 90
  // minutes — the old code saw "min" anywhere in the string and multiplied the
  // first number (90s) by 60, producing a 90-MINUTE rest timer.
  const m = s.match(/(\d+)/);
  if (!m) return 60;
  const n = parseInt(m[1], 10);
  // Unit for THIS number: the letters immediately after it (up to the next
  // digit). "90s-2 min" -> "s"; "2 min" -> "min". If the first value carries no
  // unit (e.g. "2-3 min"), fall back to the first time-unit later in the string.
  const after = s.slice(m.index + m[1].length);
  let unit = (after.match(/^\s*([a-z]+)/i) || [, ''])[1].toLowerCase();
  if (unit[0] !== 's' && unit[0] !== 'm') {
    unit = ((after.match(/\b(min(?:ute)?s?|s(?:ec(?:ond)?s?)?)\b/i) || [, ''])[1] || '').toLowerCase();
  }
  return unit[0] === 'm' ? n * 60 : n;  // m/min/minute(s) -> minutes; else seconds
}

// Format the rest the way the TIMER actually uses it, so the displayed rest
// never disagrees with the countdown (a "2-3 min" range showed but the timer
// counted 2 min — show "2 min").
function _fmtRest(sec) {
  if (!sec) return '';
  return (sec % 60 === 0) ? (sec / 60) + ' min' : sec + 's';
}

// Confirm suspicious set entries. Returns true to proceed, false to bail.
// Caller passes repsTyped (what the user actually typed; 0 if not) so we don't
// nag when the target placeholder is filled in by default.
function _confirmSetIfSuspicious(exName, weight, reps, repsTyped) {
  var warnings = [];
  // Reps typo: most weighted exercises top out well below 50. Timed holds
  // (planks) and bodyweight high-rep work (weight=0) are excluded.
  if (repsTyped > 50 && weight > 0) {
    warnings.push('You logged ' + repsTyped + ' reps of ' + exName + ' at ' + weight + ' lb. Typo?');
  }
  // Weight typo: absolute guardrail.
  if (weight > 500) {
    warnings.push('You logged ' + weight + ' lb on ' + exName + '. Typo?');
  }
  // Weight typo: relative to this exercise's history.
  if (window._weightsCache && _weightsCache[exName] && _weightsCache[exName].current > 0) {
    var prev = _weightsCache[exName].current;
    if (weight >= prev * 2.5 && weight - prev >= 30) {
      warnings.push('Last recorded weight for ' + exName + ' was ' + prev + ' lb. You entered ' + weight + ' lb. Typo?');
    }
  }
  if (!warnings.length) return true;
  return confirm(warnings.join('\n\n') + '\n\nOK to save anyway, Cancel to fix.');
}

function saveSetField(week, dayIdx, exIdx, setIdx, exName) {
  const key = `${week}_${dayIdx}_${exIdx}_${setIdx}`;
  // If toggleSet is mid-flight, let it own the save — don't double-write
  if (_setSaving[key]) return;
  const wtInput = document.getElementById(`wt-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const repsInput = document.getElementById(`reps-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const weight = wtInput ? parseFloat(wtInput.value) || 0 : 0;
  const repsTyped = repsInput ? parseInt(repsInput.value) : 0;
  const repsTarget = repsInput ? parseInt(repsInput.placeholder) || 0 : 0;
  const reps = repsTyped || repsTarget;
  if (weight <= 0 && reps <= 0) return;
  if (!_confirmSetIfSuspicious(exName, weight, reps, repsTyped)) return;
  // Update local cache so the value persists across re-renders even before toggleSet
  if (!_setCache[key]) _setCache[key] = { done: false, weight, reps };
  else { _setCache[key].weight = weight; _setCache[key].reps = reps; }
  // Send WITHOUT the done flag — backend will preserve the existing done state
  apiPost('/api/sets', { exercise: exName, week, day_idx: dayIdx, set_number: setIdx, weight, reps });
}

function toggleSet(week, dayIdx, exIdx, setIdx, restSec, exName, btn) {
  if (typeof event !== 'undefined' && event && event.stopPropagation) event.stopPropagation();
  const key = `${week}_${dayIdx}_${exIdx}_${setIdx}`;
  const wtInput = document.getElementById(`wt-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const repsInput = document.getElementById(`reps-${week}-${dayIdx}-${exIdx}-${setIdx}`);
  const weight = wtInput ? parseFloat(wtInput.value) || 0 : 0;
  // If user didn't type reps, use the target reps (placeholder) — they hit the target
  const repsTyped = repsInput ? parseInt(repsInput.value) : 0;
  const repsTarget = repsInput ? parseInt(repsInput.placeholder) || 0 : 0;
  const reps = repsTyped || repsTarget;

  if (_setCache[key] && _setCache[key].done) {
    // Un-check
    _setCache[key] = { done: false, weight, reps };
    btn.classList.remove('done');
    btn.innerHTML = '';
    btn.closest('.set-row').classList.remove('set-done');
    // Save un-done state to DB — mark in-flight so blur-triggered saveSetField doesn't double-write
    _setSaving[key] = true;
    const _p1 = apiPost('/api/sets', { exercise: exName, week, day_idx: dayIdx, set_number: setIdx, weight, reps, done: false });
    if (_p1 && typeof _p1.finally === 'function') {
      _p1.finally(() => { delete _setSaving[key]; });
    } else {
      setTimeout(() => { delete _setSaving[key]; }, 1500);
    }
  } else {
    // Check — mark set done. Flag obvious typos before persisting.
    if (!_confirmSetIfSuspicious(exName, weight, reps, repsTyped)) return;
    _setCache[key] = { done: true, weight, reps };
    btn.classList.add('done');
    btn.innerHTML = '&#10003;';
    btn.closest('.set-row').classList.add('set-done');

    // Save set to DB (every set, every rep, every weight)
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    const isSwapped = !!swaps[`${week}_${dayIdx}_${exIdx}`];
    _setSaving[key] = true;
    const _p2 = apiPost('/api/sets', { exercise: exName, week, day_idx: dayIdx, set_number: setIdx, weight, reps, done: true, exercise_swapped: isSwapped });
    if (_p2 && typeof _p2.finally === 'function') {
      _p2.finally(() => { delete _setSaving[key]; });
    } else {
      setTimeout(() => { delete _setSaving[key]; }, 1500);
    }
    // Also update the exercise-level weight cache
    if (weight > 0) {
      if (!_weightsCache) _weightsCache = {};
      if (!_weightsCache[exName]) _weightsCache[exName] = { current: 0, history: [] };
      _weightsCache[exName].current = weight;
    }

    // Check if all sets done → mark exercise complete + show RPE
    // Use reps-* IDs (exist for ALL exercise types including BW — wt-* only exists for weighted)
    const setsMatch = document.querySelectorAll(`[id^="reps-${week}-${dayIdx}-${exIdx}-"]`);
    const totalSets = setsMatch.length;

    // Start rest timer — but NOT after the last set of an exercise
    if (setIdx < totalSets - 1) {
      startRestTimer(exIdx, restSec);
    }
    let allDone = true;
    for (let s = 0; s < totalSets; s++) {
      const _sd = _setCache[`${week}_${dayIdx}_${exIdx}_${s}`];
      if (!_sd || !_sd.done) { allDone = false; break; }
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

  const endTime = Date.now() + seconds * 1000;
  el.innerHTML = `<div class="rest-countdown">${formatTimer(seconds)}</div>`;
  el.style.display = 'block';

  _restTimerInterval = setInterval(() => {
    const remaining = Math.max(0, Math.ceil((endTime - Date.now()) / 1000));
    if (remaining <= 0) {
      clearInterval(_restTimerInterval);
      _restTimerInterval = null;
      el.innerHTML = `<div class="rest-countdown rest-done">GO</div>`;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      setTimeout(() => { el.style.display = 'none'; _activeTimerEl = null; }, 3000);
    } else {
      el.innerHTML = `<div class="rest-countdown">${formatTimer(remaining)}</div>`;
    }
  }, 250);
}

function formatTimer(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;
}

// ─── HIIT INTERVAL TIMER (full-screen work/rest cycle for planks, timed core) ─
var _hiitState = null;
var _hiitLastWholeSec = null;

function _hiitBeep(freq, duration) {
  try {
    var ctx = _hiitState && _hiitState.audioCtx;
    if (!ctx) return;
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq || 880;
    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + (duration || 0.15));
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + (duration || 0.15));
  } catch (e) {}
}

function startExerciseHiit(exName, week, dayIdx, exIdx, workSec, restSec, totalSets, startSet) {
  if (_hiitState && _hiitState.iv) clearInterval(_hiitState.iv);
  if (_hiitState && _hiitState.audioCtx) { try { _hiitState.audioCtx.close(); } catch (e) {} }

  var overlay = document.getElementById('hiit-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'hiit-overlay';
    overlay.className = 'hiit-overlay';
    document.body.appendChild(overlay);
  }
  overlay.classList.add('visible');

  var audioCtx = null;
  try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}

  _hiitState = {
    exName: exName, week: week, dayIdx: dayIdx, exIdx: exIdx,
    workSec: workSec, restSec: restSec, totalSets: totalSets,
    setIdx: startSet || 0,
    phase: 'work',
    remaining: workSec,
    paused: false,
    iv: null,
    audioCtx: audioCtx,
  };
  _hiitLastWholeSec = null;

  overlay.innerHTML =
    '<div class="hiit-card hiit-work" id="hiit-card">' +
      '<div class="hiit-ex-name">' + String(exName).replace(/</g, '&lt;') + '</div>' +
      '<div class="hiit-set-meta" id="hiit-set-n"></div>' +
      '<div class="hiit-phase-label" id="hiit-phase">WORK</div>' +
      '<div class="hiit-countdown" id="hiit-count">00</div>' +
      '<div class="hiit-controls">' +
        '<button class="hiit-btn" onclick="_hiitSkip()">Skip</button>' +
        '<button class="hiit-btn" id="hiit-pause-btn" onclick="_hiitPause()">Pause</button>' +
        '<button class="hiit-btn hiit-btn-close" onclick="_hiitClose()">Close</button>' +
      '</div>' +
    '</div>';

  _hiitRenderPhase();
  _hiitBeep(1200, 0.2);
  if (navigator.vibrate) navigator.vibrate(150);

  _hiitState.iv = setInterval(_hiitTick, 250);
}

function _hiitRenderPhase() {
  var s = _hiitState;
  if (!s) return;
  var card = document.getElementById('hiit-card');
  if (card) {
    card.classList.toggle('hiit-work', s.phase === 'work');
    card.classList.toggle('hiit-rest', s.phase === 'rest');
  }
  var phaseEl = document.getElementById('hiit-phase');
  var setMeta = document.getElementById('hiit-set-n');
  if (phaseEl) phaseEl.textContent = s.phase === 'work' ? 'WORK' : 'REST';
  if (setMeta) setMeta.textContent = 'Set ' + (s.setIdx + 1) + ' of ' + s.totalSets;
  _hiitRenderCount();
}

function _hiitRenderCount() {
  var s = _hiitState;
  if (!s) return;
  var el = document.getElementById('hiit-count');
  if (!el) return;
  var n = Math.max(0, Math.ceil(s.remaining));
  el.textContent = n < 10 ? '0' + n : '' + n;
  el.classList.toggle('hiit-urgent', n <= 3 && n > 0);
}

function _hiitTick() {
  var s = _hiitState;
  if (!s || s.paused) return;
  s.remaining -= 0.25;
  var wholeSec = Math.ceil(s.remaining);
  if (wholeSec !== _hiitLastWholeSec) {
    _hiitLastWholeSec = wholeSec;
    if (wholeSec > 0 && wholeSec <= 3) {
      _hiitBeep(880, 0.1);
      if (navigator.vibrate) navigator.vibrate(80);
    }
  }
  if (s.remaining <= 0) {
    _hiitAdvance();
  } else {
    _hiitRenderCount();
  }
}

function _hiitAdvance() {
  var s = _hiitState;
  if (!s) return;
  if (s.phase === 'work') {
    _hiitMarkSetDone(s.setIdx);
    _hiitBeep(1200, 0.3);
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    if (s.setIdx >= s.totalSets - 1) {
      _hiitFinish();
      return;
    }
    s.phase = 'rest';
    s.remaining = s.restSec || 0;
    if (s.remaining <= 0) { return _hiitAdvance(); }
  } else {
    s.phase = 'work';
    s.setIdx++;
    s.remaining = s.workSec;
    _hiitBeep(1400, 0.2);
    if (navigator.vibrate) navigator.vibrate(200);
  }
  _hiitLastWholeSec = null;
  _hiitRenderPhase();
}

function _hiitMarkSetDone(setIdx) {
  var s = _hiitState;
  if (!s) return;
  var key = s.week + '_' + s.dayIdx + '_' + s.exIdx + '_' + setIdx;
  if (_setCache[key] && _setCache[key].done) return;
  _setCache[key] = { done: true, weight: 0, reps: s.workSec };
  apiPost('/api/sets', {
    exercise: s.exName, week: s.week, day_idx: s.dayIdx,
    set_number: setIdx, weight: 0, reps: s.workSec, done: true,
  });
  // Sync DOM behind the overlay so checkmarks appear when user closes
  var inline = document.getElementById('inline-timer-' + s.exIdx + '-' + setIdx);
  if (inline) {
    var row = inline.closest('.set-row');
    if (row) {
      row.classList.add('set-done');
      var cb = row.querySelector('.set-check');
      if (cb) { cb.classList.add('done'); cb.innerHTML = '&#10003;'; }
    }
  }
}

function _hiitPause() {
  var s = _hiitState;
  if (!s) return;
  s.paused = !s.paused;
  var btn = document.getElementById('hiit-pause-btn');
  if (btn) btn.textContent = s.paused ? 'Resume' : 'Pause';
}

function _hiitSkip() {
  if (!_hiitState) return;
  _hiitState.remaining = 0;
  _hiitAdvance();
}

function _hiitFinish() {
  var s = _hiitState;
  if (!s) return;
  if (s.iv) clearInterval(s.iv);
  if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
  _completionsCache.exercises = _completionsCache.exercises || {};
  _completionsCache.exercises[s.week + '_' + s.dayIdx + '_' + s.exIdx] = true;
  apiPost('/api/completions/exercise', { week: s.week, day_idx: s.dayIdx, exercise_idx: s.exIdx });
  _hiitClose();
  if (typeof renderDetail === 'function') try { renderDetail(); } catch (e) {}
}

function _hiitClose() {
  if (_hiitState && _hiitState.iv) clearInterval(_hiitState.iv);
  if (_hiitState && _hiitState.audioCtx) { try { _hiitState.audioCtx.close(); } catch (e) {} }
  _hiitState = null;
  _hiitLastWholeSec = null;
  var overlay = document.getElementById('hiit-overlay');
  if (overlay) overlay.classList.remove('visible');
}

// ─── INLINE TIMED SET TIMER (single-set holds, warmups) ────────────────────
function startInlineTimer(seconds, btn, exName, week, dayIdx, exIdx, setIdx, restSec) {
    var el = document.getElementById('inline-timer-' + exIdx + '-' + setIdx);
    if (!el) return;
    btn.style.display = 'none';
    var endTime = Date.now() + seconds * 1000;
    el.textContent = formatTimer(seconds);
    if (navigator.vibrate) navigator.vibrate(100);
    var iv = setInterval(function() {
        var rem = Math.max(0, Math.ceil((endTime - Date.now()) / 1000));
        el.textContent = formatTimer(rem);
        if (rem <= 3 && rem > 0) {
            el.style.color = '#ef4444';
        }
        if (rem <= 0) {
            clearInterval(iv);
            el.textContent = 'DONE';
            el.style.color = '#22c55e';
            if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
            // Auto-check the set as done
            var checkBtn = document.querySelector('#wu-step-' + exIdx + ' .set-check') ||
                           el.closest('.set-row')?.querySelector('.set-check');
            // Mark set done via toggleSet
            var cacheKey = week + '_' + dayIdx + '_' + exIdx + '_' + setIdx;
            if (!_setCache[cacheKey] || !_setCache[cacheKey].done) {
                _setCache[cacheKey] = { done: true, weight: 0, reps: seconds };
                apiPost('/api/sets', { exercise: exName, week: week, day_idx: dayIdx, set_number: setIdx, weight: 0, reps: seconds, done: true });
                var row = el.closest('.set-row');
                if (row) {
                    row.classList.add('set-done');
                    var cb = row.querySelector('.set-check');
                    if (cb) { cb.classList.add('done'); cb.innerHTML = '&#10003;'; }
                }
            }
            // Start rest timer
            if (restSec > 0) startRestTimer(exIdx, restSec);
            setTimeout(function() { el.textContent = ''; }, 3000);
        }
    }, 250);
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

// COACH-OR-NOTHING: the old WEIGHT_ESTIMATES table (Face Pull 25 lb, Leg Curl
// 50 lb, bench*0.35 ratios, ...) silently prefilled weight inputs with static
// guesses for any exercise with no history and no prescribed target_weight —
// then checking the set logged that invented weight into SetLog as performance
// data. Removed: with no prescription and no history, the input stays EMPTY
// and the athlete types what they actually lift.

/**
 * Resolve the value to display in a set's weight input.
 *
 * Priority:
 *   1. ex.target_weight if explicitly set (handles 0 = bodyweight as
 *      "empty input, athlete fills if adding load")
 *   2. suggestion.weight from history/estimator
 *   3. empty string
 *
 * Returns a number, or '' for an empty input. Pass `displayName` (optional)
 * to round the prescription weight to a sensible plate increment via
 * roundWeight() — useful for the focused-set view; the inline session view
 * displays raw numbers without rounding.
 *
 * Pure function — direct unit-testable. See tests/js/weight_prefill.test.mjs.
 */
function resolveDisplayWeight(ex, suggestion, displayName) {
  if (ex && ex.target_weight != null) {
    if (ex.target_weight === 0) return ''; // bodyweight; leave input empty
    return displayName ? roundWeight(ex.target_weight, displayName) : ex.target_weight;
  }
  if (suggestion && suggestion.weight != null) return suggestion.weight;
  return '';
}

function getSuggestedWeight(exName, currentWeekNum) {
  const data = getExerciseData(exName);
  if (!data) {
    // No logged history for this lift. COACH-OR-NOTHING: never invent a
    // static estimate (the old table + keyword ratios prefilled e.g. 25 lb
    // for Face Pull with no indication it was a guess). Leave it empty.
    return { weight: null, reason: '' };
  }

  const currentWt = data.current || 0;
  const history = data.history || [];

  if (isDeloadWeek(currentWeekNum)) {
    // Only a fallback when the coach/engine set no weight. Use 85% to match the
    // engine's deload (training_engine _round_weight(last*0.85)) \u2014 the old 60%
    // contradicted the engine's actual deload prescription on the same screen.
    return { weight: Math.round(currentWt * 0.85), reason: 'Deload week \u2014 ~85% weight, recovery focus' };
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
  // Most recent entry from a session BEFORE the one being viewed — never today's
  // just-logged set (same week+day) or a later week, which made "Last:" show the
  // value the athlete is entering right now.
  for (let i = data.history.length - 1; i >= 0; i--) {
    const h = data.history[i];
    const hw = (h.week != null ? h.week : 0);
    const hd = (h.day != null ? h.day : 0);
    if (hw < currentWeek || (hw === currentWeek && hd < currentDay)) {
      return h.weight;
    }
  }
  return null;
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

// ─── WEIGHT DETAIL ACCORDION ───────────────────────────────────────────────

async function toggleWeightDetail(exerciseName, rowEl) {
    const detailId = 'ws-detail-' + exerciseName.replace(/\s/g, '-');
    const detail = document.getElementById(detailId);
    if (!detail) return;

    // Toggle
    if (detail.style.display !== 'none') {
        detail.style.display = 'none';
        return;
    }

    detail.style.display = 'block';
    detail.innerHTML = '<div style="padding:8px 0;color:var(--muted);font-size:12px">Loading...</div>';

    try {
        const res = await fetch('/api/weight-detail/' + encodeURIComponent(exerciseName));
        const data = await res.json();

        let html = '';

        // Baseline vs Current
        if (data.baseline_1rm && data.current_1rm) {
            const change = data.current_1rm - data.baseline_1rm;
            const pct = data.baseline_1rm > 0 ? Math.round((change / data.baseline_1rm) * 100) : 0;
            const dir = change > 0 ? '+' : '';
            html += `<div class="ws-baseline">
                <span>Baseline 1RM: ${data.baseline_1rm} lb</span>
                <span style="color:var(--accent)">→ Current est 1RM: ${data.current_1rm} lb (${dir}${pct}%)</span>
            </div>`;
        } else if (data.current_1rm) {
            html += `<div class="ws-baseline">Current est 1RM: ${data.current_1rm} lb</div>`;
        }

        // Percentile bar
        if (data.percentile != null) {
            const pctWidth = Math.min(data.percentile, 100);
            const color = pctWidth >= 75 ? 'var(--accent)' : pctWidth >= 50 ? '#f59e0b' : 'var(--muted)';
            html += `<div class="ws-percentile">
                <div class="ws-pct-bar"><div class="ws-pct-fill" style="width:${pctWidth}%;background:${color}"></div></div>
                <div class="ws-pct-label">${data.percentile}th percentile${data.rating ? ' · ' + data.rating : ''}</div>
            </div>`;
        }

        // Weekly e1RM timeline
        if (data.timeline && data.timeline.length > 0) {
            html += '<div class="ws-timeline">';
            for (const e of data.timeline) {
                if (!e.est_1rm) continue; // Skip entries with no data
                // is_current comes from the API (matches user's actual program week)
                const isCurrent = !!e.is_current;
                const sourceTag = e.source === 'scheduled' ? '<span class="ws-tl-tag" style="background:var(--accent-bg);color:var(--accent)">scheduled</span>' : '';
                html += `<div class="ws-timeline-entry${isCurrent ? ' ws-baseline-entry' : ''}">
                    <span class="ws-tl-week">Wk ${e.week}</span>
                    <span class="ws-tl-weight">${e.est_1rm} lb e1RM</span>
                    ${sourceTag}
                    ${isCurrent ? '<span class="ws-tl-tag">current</span>' : ''}
                </div>`;
            }
            html += '</div>';
        }

        detail.innerHTML = html || '<div style="color:var(--muted);font-size:12px">No history yet</div>';
    } catch(e) {
        detail.innerHTML = '<div style="color:var(--muted);font-size:12px">Failed to load</div>';
    }
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
  // Hide the main app header — user shouldn't see progress/coach/settings during onboarding
  var _hdr = document.querySelector('header');
  if (_hdr) _hdr.style.display = 'none';
  var _appLoading = document.getElementById('app-loading');
  if (_appLoading) _appLoading.style.display = 'none';
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
    if (!gData.computed || (gData.computed && !gData.calories)) {
      // Goal doesn't exist OR exists with null macros — (re)compute
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
  const cappedReps = Math.min(reps, 15); // Epley unreliable above 15 reps
  return Math.round(weight * (1 + cappedReps / 30));
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

async function saveBaseline() {
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
  await apiPost('/api/weights/baseline', { exercises });
  await apiPost('/api/physical-assessment', { gym_baseline_done: true, completed: true });
  _stateCache.baseline_done = true;
  await apiPost('/api/state', { baseline_done: true });
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

    // Save waist measurement (may be gated to Sundays — silently continue on 403 for baseline)
    if (waistVal && waistVal > 0) {
      var _blRes = await fetch('/api/measurements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: today, waist: waistVal, notes: notesVal })
      });
      if (_blRes && _blRes.status === 403) {
        console.info('Baseline waist not saved — measurements are Sunday-only. User can record on next Sunday.');
      } else {
        window._measurementsCache = null;
      }
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
    // Step 2: Weight + height only (tape measurements moved to step 3, after BW tests)
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Body Weight &amp; Height</h2>
        <div class="baseline-desc" style="margin-bottom:1rem">Starting numbers. Day 1 benchmarks.</div>

        <div class="pa-measure-row">
          <label>Body Weight (lbs)</label>
          <input type="number" inputmode="decimal" id="pa-weight" placeholder="e.g. 185" step="0.1" min="50" max="500" value="${_paData.weight || ''}">
        </div>
        <div class="pa-measure-row">
          <label>Height (inches)</label>
          <input type="number" inputmode="decimal" id="pa-height" placeholder="e.g. 70 (5'10 = 70)" step="0.1" min="48" max="96" value="${_paData.height || ''}">
        </div>

        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="paNextFromBasics()">Next</button>
      </div>
    </div>`;
    return;
  }

  if (_paStep === 2) {
    // Step 3: Bodyweight tests (universal — both gym and no-gym users)
    _bwBaselineStep = 0;
    _bwBaselineData = {};
    renderBodyweightBaseline();
    return;
  }

  if (_paStep === 3) {
    // Step 4: Tape measurements (conditional on has_tape) — the LAST step
    if (!_paData.has_tape) {
      // Skip directly to completion if no tape
      completePhysicalAssessment();
      return;
    }
    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card">
        <h2>Tape Measurements</h2>
        <div class="baseline-desc" style="margin-bottom:0.5rem">Final step. Measure relaxed, standing straight, tape flat against skin. Don't suck in.</div>

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
        </div>

        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="paNextFromTape()">Finish</button>
      </div>
    </div>`;
    return;
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

async function paNextFromQuestions() {
  if (_paData.has_gym === null || _paData.has_tape === null) return;
  // Save questions to backend
  await apiPost('/api/physical-assessment', { has_gym: _paData.has_gym, has_measuring_tape: _paData.has_tape });
  _paStep = 1;
  renderPhysicalAssessment();
}

async function paNextFromBasics() {
  const getVal = (id) => { const el = document.getElementById(id); return el ? parseFloat(el.value) || null : null; };

  _paData.weight = getVal('pa-weight');
  _paData.height = getVal('pa-height');

  if (!_paData.weight || !_paData.height) {
    alert('Please enter both weight and height to continue.');
    return;
  }

  const payload = { bodyweight: _paData.weight, height: _paData.height };
  await apiPost('/api/physical-assessment', payload);

  const bwRes = await fetch('/api/bodyweight', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ date: todayStr(), weight: _paData.weight }) });
  if (!bwRes.ok) {
    alert('Failed to save body weight. Please try again.');
    return;
  }
  if (!Array.isArray(_bodyweightCache)) _bodyweightCache = [];
  _bodyweightCache.push({ date: todayStr(), weight: _paData.weight });

  _paStep = 2;
  renderPhysicalAssessment();
}

async function paNextFromTape() {
  const getVal = (id) => { const el = document.getElementById(id); return el ? parseFloat(el.value) || null : null; };

  _paData.waist = getVal('pa-waist');
  _paData.chest = getVal('pa-chest');
  _paData.bicep = getVal('pa-bicep');
  _paData.thigh = getVal('pa-thigh');
  _paData.hips = getVal('pa-hips');
  _paData.neck = getVal('pa-neck');

  const payload = {};
  if (_paData.waist) payload.waist = _paData.waist;
  if (_paData.chest) payload.chest = _paData.chest;
  if (_paData.bicep) payload.bicep = _paData.bicep;
  if (_paData.thigh) payload.thigh = _paData.thigh;
  if (_paData.hips) payload.hips = _paData.hips;
  if (_paData.neck) payload.neck = _paData.neck;
  if (Object.keys(payload).length) {
    await apiPost('/api/physical-assessment', payload);
  }

  await completePhysicalAssessment();
}

async function completePhysicalAssessment() {
  await apiPost('/api/physical-assessment', { completed: true });
  _stateCache.baseline_done = true;
  await apiPost('/api/state', { baseline_done: true });
  showEquipmentSelection();
}

// ─── BODYWEIGHT BASELINE FLOW ──────────────────────────────────────────────
// Universal timed bodyweight assessment. 60-second rep tests + plank hold.
const BW_BASELINE_EXERCISES = [
  {
    key: 'squats',
    name: 'Air Squats',
    hint: 'Full depth, heels on the ground. Count every rep you complete in 60 seconds.',
    mode: 'timed_reps',
    duration: 60,
  },
  {
    key: 'pushups',
    name: 'Pushups',
    hint: 'Good form — chest to the floor. Count every rep in 60 seconds. If you can only do them from your knees, check the box.',
    mode: 'timed_reps',
    duration: 60,
    hasKneesCheckbox: true,
  },
  {
    key: 'burpees',
    name: 'Burpees',
    hint: 'Squat, kick out, pushup, jump back, stand up, jump. Count every full rep in 60 seconds.',
    mode: 'timed_reps',
    duration: 60,
  },
  {
    key: 'plank',
    name: 'Plank Hold',
    hint: 'Forearms down, body straight, core engaged. Start the timer and stop when you can\'t hold the line.',
    mode: 'stopwatch',
  },
];

let _bwTimerHandle = null;
let _bwTimerStartMs = 0;
let _bwTimerPhase = 'idle';  // 'idle' | 'running' | 'finished'
let _bwTimerElapsed = 0;      // seconds (for plank)

function _bwClearTimer() {
  if (_bwTimerHandle) { clearInterval(_bwTimerHandle); _bwTimerHandle = null; }
}

function renderBodyweightBaseline() {
  _bwClearTimer();
  _bwTimerPhase = 'idle';
  _bwTimerElapsed = 0;

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

    const checkboxHtml = ex.hasKneesCheckbox ? `<div class="bw-assess-checkbox" style="margin-top:12px">
        <input type="checkbox" id="bw-knees" ${existing.from_knees ? 'checked' : ''}>
        <label for="bw-knees">These were from my knees</label>
      </div>` : '';

    const initialTimerText = ex.mode === 'timed_reps' ? `0:${String(ex.duration).padStart(2,'0')}` : '0:00';
    const startLabel = ex.mode === 'timed_reps' ? `Start ${ex.duration}s Timer` : 'Start';
    const inputLabel = ex.mode === 'timed_reps' ? `Reps completed (${ex.duration}s)` : 'Seconds held';

    el.innerHTML = `<div class="baseline-overlay">
      <div class="baseline-card bw-assess-card">
        <div class="baseline-progress">${dots}</div>
        <div class="baseline-progress-text">${_bwBaselineStep + 1} / ${total}</div>
        <div class="bw-assess-exercise">${ex.name}</div>
        <div class="bw-assess-hint">${ex.hint}</div>

        <div id="bw-timer-display" style="font-family:'DM Mono',monospace;font-size:3rem;text-align:center;margin:1rem 0;letter-spacing:0.05em;color:#4ade80">${initialTimerText}</div>

        <div id="bw-timer-controls" style="display:flex;gap:8px;margin-bottom:1rem">
          <button class="btn btn-primary" style="flex:1" id="bw-timer-start" onclick="bwTimerStart()">${startLabel}</button>
          ${ex.mode === 'stopwatch' ? '<button class="btn btn-secondary" id="bw-timer-stop" onclick="bwTimerStop()" style="display:none;flex:1">Stop</button>' : ''}
        </div>

        <div id="bw-assess-input-wrap" style="${existing.value ? '' : 'display:none'}">
          <label>${inputLabel}</label>
          <input type="number" inputmode="numeric" id="bw-input" value="${existing.value || ''}" placeholder="0" min="0">
          ${checkboxHtml}
          <div style="display:flex;gap:8px;margin-top:12px">
            ${_bwBaselineStep > 0 ? '<button class="btn btn-secondary" onclick="bwBaselineBack()">Back</button>' : ''}
            <button class="btn btn-primary" style="flex:1" onclick="bwBaselineNext()">${_bwBaselineStep === total - 1 ? 'See My Results' : 'Next \u2192'}</button>
          </div>
        </div>
      </div>
    </div>`;
    return;
  }

  // Summary screen
  let rows = '';
  for (const ex of BW_BASELINE_EXERCISES) {
    const data = _bwBaselineData[ex.key] || {};
    let valStr = ex.mode === 'stopwatch'
      ? (data.value || 0) + ' sec'
      : (data.value || 0) + ' reps';
    if (ex.hasKneesCheckbox && data.from_knees) valStr += ' (from knees)';
    rows += `<div class="bw-assess-summary-row">
      <span>${ex.name}</span>
      <span>${valStr}</span>
    </div>`;
  }

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card bw-assess-card">
      <h2>Bodyweight Baseline</h2>
      <div class="bw-assess-summary">${rows}</div>
      <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="bwBaselineContinueFromSummary()">${_paData.has_tape ? 'Next — Tape Measurements' : 'Finish'}</button>
    </div>
  </div>`;
}

function _bwFormatTime(totalSec) {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2,'0')}`;
}

function bwTimerStart() {
  const ex = BW_BASELINE_EXERCISES[_bwBaselineStep];
  if (!ex) return;
  _bwClearTimer();
  _bwTimerPhase = 'running';
  _bwTimerStartMs = Date.now();
  const startBtn = document.getElementById('bw-timer-start');
  const stopBtn = document.getElementById('bw-timer-stop');
  const disp = document.getElementById('bw-timer-display');
  if (startBtn) startBtn.style.display = 'none';
  if (stopBtn) stopBtn.style.display = '';

  if (ex.mode === 'timed_reps') {
    const duration = ex.duration;
    const tick = () => {
      const elapsed = Math.floor((Date.now() - _bwTimerStartMs) / 1000);
      const remaining = Math.max(0, duration - elapsed);
      if (disp) disp.textContent = _bwFormatTime(remaining);
      if (remaining <= 0) {
        _bwClearTimer();
        _bwTimerPhase = 'finished';
        if (disp) { disp.textContent = 'TIME'; disp.style.color = '#ef4444'; }
        try { if (navigator.vibrate) navigator.vibrate([200, 100, 200]); } catch(e) {}
        const wrap = document.getElementById('bw-assess-input-wrap');
        if (wrap) wrap.style.display = '';
        setTimeout(() => { const inp = document.getElementById('bw-input'); if (inp) inp.focus(); }, 100);
      }
    };
    tick();
    _bwTimerHandle = setInterval(tick, 250);
  } else {
    // stopwatch (plank)
    const tick = () => {
      const elapsed = Math.floor((Date.now() - _bwTimerStartMs) / 1000);
      _bwTimerElapsed = elapsed;
      if (disp) disp.textContent = _bwFormatTime(elapsed);
    };
    tick();
    _bwTimerHandle = setInterval(tick, 250);
  }
}

function bwTimerStop() {
  _bwClearTimer();
  _bwTimerPhase = 'finished';
  const ex = BW_BASELINE_EXERCISES[_bwBaselineStep];
  if (ex && ex.mode === 'stopwatch') {
    const inp = document.getElementById('bw-input');
    if (inp) inp.value = _bwTimerElapsed;
    const wrap = document.getElementById('bw-assess-input-wrap');
    if (wrap) wrap.style.display = '';
    const stopBtn = document.getElementById('bw-timer-stop');
    if (stopBtn) stopBtn.style.display = 'none';
  }
}

async function bwBaselineNext() {
  const ex = BW_BASELINE_EXERCISES[_bwBaselineStep];
  const inpEl = document.getElementById('bw-input');
  const val = inpEl ? (parseInt(inpEl.value) || 0) : 0;
  const kneesEl = document.getElementById('bw-knees');
  _bwBaselineData[ex.key] = { value: val, from_knees: kneesEl ? kneesEl.checked : false };

  const keyMap = { pushups: 'pushup_count', plank: 'plank_seconds', squats: 'squat_count', burpees: 'burpee_count' };
  const payload = {};
  payload[keyMap[ex.key] || ex.key] = val;
  if (ex.hasKneesCheckbox) payload.pushup_from_knees = kneesEl ? kneesEl.checked : false;

  if (_bwRetestWeek) {
    payload.week_number = _bwRetestWeek;
    await apiPost('/api/bodyweight-retest', payload);
  } else {
    await apiPost('/api/physical-assessment', payload);
  }

  _bwClearTimer();
  _bwBaselineStep++;
  renderBodyweightBaseline();
}

function bwBaselineBack() {
  _bwClearTimer();
  _bwBaselineStep--;
  renderBodyweightBaseline();
}

function bwBaselineContinueFromSummary() {
  _bwClearTimer();
  if (_bwRetestWeek) {
    completeBwRetest();
    return;
  }
  _paStep = 3;
  renderPhysicalAssessment();
}

// ─── BODYWEIGHT RETEST (week 6 / week 12) ──────────────────────────────────
let _bwRetestWeek = null;

function showBodyweightRetestIntro(week) {
  _bwRetestWeek = week;
  const el = document.getElementById('baseline-overlay');
  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center">
      <h2>Week ${week} Retest</h2>
      <div class="baseline-desc" style="margin:1rem 0 1.5rem">
        Same four tests as your baseline. Same rules. Same 60 seconds.<br><br>
        <strong>This is the point of the program.</strong> We see what changed.
      </div>
      <button class="btn btn-primary" style="width:100%" onclick="startBodyweightRetest()">Start Retest</button>
    </div>
  </div>`;
}

function startBodyweightRetest() {
  _bwBaselineStep = 0;
  _bwBaselineData = {};
  renderBodyweightBaseline();
}

async function completeBwRetest() {
  await apiPost('/api/bodyweight-retest', { week_number: _bwRetestWeek, completed: true });
  _bwRetestWeek = null;
  const el = document.getElementById('baseline-overlay');
  if (el) el.innerHTML = '';
  renderAll();
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
    const res = await fetch('/api/equipment', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ available_equipment: _equipSelections, completed: true }),
    });
    if (!res.ok) {
        alert('Could not save equipment. Please try again.');
        return;
    }
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

// Track touch movement to prevent scroll-triggers-click on mobile
let _foodTouchStartY = null;
document.addEventListener('touchstart', function(e) { _foodTouchStartY = e.touches[0].clientY; }, { passive: true });
document.addEventListener('touchend', function(e) {
  if (_foodTouchStartY !== null && e.changedTouches.length > 0) {
    const dy = Math.abs(e.changedTouches[0].clientY - _foodTouchStartY);
    if (dy > 10) window._foodScrolled = true;
    else window._foodScrolled = false;
  }
  _foodTouchStartY = null;
}, { passive: true });

function toggleFood(category, foodId) {
  // If the user scrolled, this click is from the scroll ending — ignore it
  if (window._foodScrolled) { window._foodScrolled = false; return; }
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
  const res = await fetch('/api/food-selections', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ selected_foods: _foodSelections, completed: true }),
  });
  if (!res.ok) {
    alert('Could not save food selections. Please try again.');
    return;
  }
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
  // Milestones from the projection's ACTUAL (absolute) weeks — never "?".
  // Prefer the 4/8/12 markers when they're in range; otherwise fall back to the
  // first / middle / last projected points (e.g. mid-program: weeks 10/11/12).
  const _ppts = proj.filter(p => p && p.projected != null);
  let _mks = [4, 8, 12].map(w => _ppts.find(p => p.week === w)).filter(Boolean);
  if (_mks.length < 2 && _ppts.length) {
    const _seen = new Set(); _mks = [];
    [_ppts[0], _ppts[Math.floor((_ppts.length - 1) / 2)], _ppts[_ppts.length - 1]]
      .forEach(p => { if (p && !_seen.has(p.week)) { _seen.add(p.week); _mks.push(p); } });
  }
  const _milestonesHtml = _mks.map((p, i) =>
    `<div class="proj-milestone${i === _mks.length - 1 ? ' highlight' : ''}">` +
    `<span class="proj-week">Week ${p.week}</span>` +
    `<span class="proj-weight">${p.projected} lbs</span></div>`).join('');

  el.innerHTML = `<div class="baseline-overlay">
    <div class="baseline-card" style="text-align:center">
      <h2>Your Weight Projection</h2>
      <div class="baseline-desc" style="margin-bottom:1rem">If you follow this plan exactly:</div>
      <div class="projection-milestones">
        ${_milestonesHtml}
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

    // Generate Week 1 program (exercises + meals) so user can preview and prep
    try {
        await fetch('/api/weekly-program/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ week: 1 }),
        });
    } catch(e) {}

    document.getElementById('baseline-overlay').innerHTML = '';

    // Check if start date is in the future → show lockout with preview
    const start = new Date(dateStr + 'T00:00:00');
    if (start > new Date()) {
        await showPreStartLockout(dateStr);
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
        <input type="text" id="psych-input" placeholder="Type your response..." enterkeyhint="send" onkeydown="if(event.key==='Enter'){event.preventDefault();sendPsychMessage()}">
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
  // Every button closes the menu first
  var _c = 'closeSettingsMenu();';
  dd.innerHTML = `
    <button onclick="${_c}if(confirm('This will reset your baseline weights. Continue?'))redoBaseline()">Redo Baseline</button>
    <button onclick="${_c}if(confirm('This will reset your psych intake. Continue?'))redoPsychIntake()">Redo Psych Intake</button>
    <button onclick="${_c}showStartDateSetting()">Set Start Date</button>
    <button onclick="${_c}toggleTravelMode()" id="travel-toggle-btn">${travelOn ? '✈️ Traveling: ON' : '🏠 Traveling: OFF'}</button>
    <button onclick="${_c}recomputeGoal()">Recompute Calories</button>
    <button onclick="${_c}launchWeeklyPlanning(currentWeek)">Re-plan This Week</button>
    <button onclick="${_c}launchWeeklyPlanning()">Plan Next Week</button>
    <button onclick="${_c}regenerateProfile()">Regenerate Profile</button>
    <button onclick="${_c}restartFromReveal()">Restart from Plan Review</button>
    <button onclick="${_c}showGroceryList()">Grocery List</button>
    <button onclick="${_c}showGarminPanel()">&#8986; Garmin Sync</button>
    <button onclick="${_c}exportData()">Export Data</button>
    <button onclick="${_c}importData()">Import Data</button>
    <button onclick="localStorage.clear();sessionStorage.clear();window.location='/logout'">Logout</button>
    <button onclick="closeSettingsMenu()">Cancel</button>
  `;
  header.parentNode.appendChild(dd);
  // Close on click outside
  setTimeout(() => {
    document.addEventListener('click', function _settingsOutside(e) {
      const menu = document.getElementById('settings-dropdown');
      if (!menu) { document.removeEventListener('click', _settingsOutside); return; }
      if (!menu.contains(e.target) && !e.target.closest('[onclick*="showSettingsMenu"]')) {
        closeSettingsMenu();
        document.removeEventListener('click', _settingsOutside);
      }
    });
  }, 10);
}

async function recomputeGoal() {
  closeSettingsMenu();
  try {
    const res = await fetch('/api/goal/compute', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      // Auto-regenerate meal plans with new calories (doesn't touch exercises)
      try {
        var mealRes = await fetch('/api/meals/regenerate', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ week: currentWeek }),
        });
        var mealData = mealRes.ok ? await mealRes.json() : null;
      } catch(e) {}
      // Reload workout data to pick up new meals
      try {
        var wRes = await fetch('/api/workouts');
        if (wRes.ok) {
          workoutData = await wRes.json();
          window._exerciseNames = workoutData._exerciseNames || [];
          delete workoutData._exerciseNames;
        }
      } catch(e) {}
      alert('Calories: ' + (data.calories || '?') + ' cal/day. Deficit: ' + (data.daily_deficit || '?') + ' cal/day (' + (data.weekly_loss_lbs || '?') + ' lb/week). Meals regenerated. Reloading...');
      window.location.reload();
    } else {
      var errData = await res.json().catch(function() { return {}; });
      alert('Failed: ' + (errData.error || 'Unknown error. Status ' + res.status));
    }
  } catch(e) {
    alert('Error: ' + e.message);
  }
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
        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function _inviteOutside(e) {
                var menu = document.getElementById('invite-dropdown');
                if (!menu || !menu.classList.contains('visible')) { document.removeEventListener('click', _inviteOutside); return; }
                if (!menu.contains(e.target) && !e.target.closest('#invite-btn')) {
                    menu.classList.remove('visible');
                    menu.innerHTML = '';
                    document.removeEventListener('click', _inviteOutside);
                }
            });
        }, 10);
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
  // No-op: RPE removed from workout flow
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

async function revertExerciseSwap(week, day, exIdx) {
    const key = week + '_' + day + '_' + exIdx;
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    delete swaps[key];
    sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
    // Also remove from DB — await so it's saved before user can close tab
    await apiPost('/api/exercise-swap', { week, day_idx: day, exercise_idx: exIdx, swapped_to: '' });
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

async function swapExercise(week, day, exIdx, newName) {
    const key = week + '_' + day + '_' + exIdx;
    const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
    swaps[key] = newName;
    sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
    // Persist to DB — await so it's saved before user can close tab
    await apiPost('/api/exercise-swap', { week, day_idx: day, exercise_idx: exIdx, swapped_to: newName });
    renderDetail();
}

// ─── INIT ───────────────────────────────────────────────────────────────────
async function safeFetch(url, fallback) {
    try {
        const res = await fetch(url);
        if (!res.ok) return { _status: res.status, data: fallback };
        return { _status: res.status, data: await res.json() };
    } catch(e) {
        console.error('Failed to load:', url, e);
        return { _status: 0, data: fallback };
    }
}

document.addEventListener('DOMContentLoaded', async () => {
  // Fetch all data in parallel — each fetch is independent, failures don't block others
  try {
    const [stateW, weightsW, compW, suppW, bwW, workoutW, mealsW, paW] = await Promise.all([
      safeFetch('/api/state', { current_week: 1, baseline_done: false }),
      safeFetch('/api/weights', {}),
      safeFetch('/api/completions', { exercises: {}, days: {} }),
      safeFetch('/api/supplements?date=' + todayStr(), { taken: {}, list: [] }),
      safeFetch('/api/bodyweight', []),
      safeFetch('/api/workouts', {}),
      safeFetch('/api/meals?date=' + todayStr(), {}),
      safeFetch('/api/physical-assessment/status', {}),
    ]);

    if (stateW._status === 401) {
      window.location.href = '/login';
      return;
    }

    // Detect and send browser timezone — MUST complete before any date-dependent calls
    try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (tz) {
            await fetch('/api/user/timezone', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({timezone: tz})
            }).catch(() => {});
        }
    } catch(e) {}

    // Unwrap safeFetch results — already parsed, no .json() needed
    _stateCache = stateW.data;
    _weightsCache = weightsW.data;
    _completionsCache = compW.data;
    _supplementsCache = suppW.data;
    _bodyweightCache = bwW.data;
    workoutData = workoutW.data;
    window._exerciseNames = workoutData._exerciseNames || [];
    delete workoutData._exerciseNames;
    window._paCache = paW.data || {};

    if (mealsW.data && Object.keys(mealsW.data).length > 0) {
      _mealsCache[todayStr()] = mealsW.data;
    }

    // Warm-up completions
    try { const wuRes = await fetch('/api/warmup-completions'); _warmupCache = await wuRes.json(); } catch(e) { _warmupCache = {}; }

    // Garmin auto-pull (server throttles to 15 min). Fire-and-forget; if new
    // runs landed, refresh the cache + card. 401 (not connected) is silent.
    fetch('/api/garmin/sync-activities', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (d && (d.days_filled || []).length) {
          return fetch('/api/run-log').then(r => r.json())
            .then(j => { _runLogCache = j; renderDetail(); })
            .then(() => d);
        }
        return d;
      })
      .then(d => {
        if (d && !d.throttled) {
          return fetch('/api/garmin/wellness?days=7').then(r => (r.ok ? r.json() : []))
            .then(w => { _wellnessToday = (w && w.length) ? w[0] : null; renderGarminBar(); });
        }
      })
      .catch(() => {});

    // Run logs
    try { const rlRes = await fetch('/api/run-log'); _runLogCache = await rlRes.json(); } catch(e) { _runLogCache = {}; }

    // Wellness strip data (DB-only). Pull the last 7 days and use the most
    // recent row — today's if synced, otherwise the latest reading (tagged with
    // its date in the strip) so the strip never blanks out just because today's
    // Garmin sync hasn't landed yet.
    try {
      const wRes = await fetch('/api/garmin/wellness?days=7');
      const w = wRes.ok ? await wRes.json() : [];
      _wellnessToday = (w && w.length) ? w[0] : null;
      renderGarminBar();
    } catch(e) { _wellnessToday = null; }

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

    // Fetch overrides for current week
    try {
        var [schedRes2, mealOvRes, runOvRes] = await Promise.all([
            fetch('/api/schedule-overrides?week=' + currentWeek),
            fetch('/api/meal-overrides?week=' + currentWeek),
            fetch('/api/run-overrides?week=' + currentWeek),
        ]);
        if (schedRes2.ok) _scheduleOverrides = await schedRes2.json();
        if (mealOvRes.ok) _mealOverrides = await mealOvRes.json();
        if (runOvRes.ok) _runOverrides = await runOvRes.json();
    } catch(e) { /* overrides are optional — ignore failures */ }

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
        return; // STOP — don't load chat, check-ins, or render the main app
      }
    }

    // Travel banner
    renderTravelBanner();

    // COACH-OR-NOTHING: no template seeding on load. An unplanned week stays
    // unplanned and renders the 'Plan this week' empty state — the old
    // /api/prescription/seed call here silently converted it into a static
    // template week the coach never designed.

    // Load chat history BEFORE rendering so coach has messages
    await loadChatHistory();

    // Load today's measurements if already submitted (for Sunday display)
    try {
      var measRes = await fetch('/api/measurements?date=' + todayStr());
      if (measRes.ok) {
        var measData = await measRes.json();
        if (measData && measData.length > 0) {
          var latest = measData[measData.length - 1];
          // Weight comes from bodyweight cache, not measurements
          var todayBw = '';
          if (Array.isArray(_bodyweightCache)) {
            var bwEntry = _bodyweightCache.find(function(e) { return e.date === todayStr(); });
            if (bwEntry) todayBw = bwEntry.weight;
          }
          window._sundayMeasurements = {
            weight: todayBw || latest.weight || '', waist: latest.waist_inches || latest.waist,
            chest: latest.chest, hips: latest.hips, neck: latest.neck,
            bicep_left: latest.bicep_left, bicep_right: latest.bicep_right,
            thigh_left: latest.thigh_left, thigh_right: latest.thigh_right,
          };
        }
      }
    } catch(e) {}

    // Morning check-in gate — check if already done today
    await checkMorningCheckin();

    // Bodyweight retest gate — weeks 6 and 12
    try {
      const rtRes = await fetch('/api/bodyweight-retest/status');
      if (rtRes.ok) {
        const rtData = await rtRes.json();
        if (rtData && rtData.due_and_pending) {
          showBodyweightRetestIntro(rtData.due_week);
          return;
        }
      }
    } catch(e) {}

    renderAll();
  } catch(e) {
    console.error('Init failed', e);
    // safeFetch handles individual endpoint failures; this catches remaining errors
    // (e.g., rendering bugs, post-fetch logic). Ensure caches have safe defaults.
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
  if (_morningCheckinDone) return;
  var dow = new Date().getDay();
  // Sunday uses a separate key — measurements are mandatory even if check-in was dismissed
  var dismissKey = dow === 0 ? 'sunday_measurements_' + todayStr() : 'checkin_done_' + todayStr();
  if (localStorage.getItem(dismissKey)) {
    _morningCheckinDone = true;
    return;
  }
  // All morning check-ins are mandatory — no activity-based skip
  const today = todayStr();
  try {
    const res = await fetch('/api/morning-checkin?date=' + today);
    const data = await res.json();
    if (data.exists) {
      _morningCheckinDone = true;
      localStorage.setItem(dismissKey, '1');
      _morningCheckinCache = data.checkin || data;
      renderCheckinSummaryBar();
    } else if (dow === 0) {
      // Sunday fallback: measurements might have been submitted (via submitSundayMeasurements)
      // without completing the coach conversation (finishMorningCheckin never ran).
      // Check BodyMeasurement table as a secondary signal.
      try {
        const mRes = await fetch('/api/measurements?date=' + today);
        const mData = await mRes.json();
        if (Array.isArray(mData) && mData.length > 0) {
          _morningCheckinDone = true;
          localStorage.setItem(dismissKey, '1');
          // Backfill MorningCheckIn so future checks find it immediately
          fetch('/api/morning-checkin', { method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ date: today, sleep_quality: 5, stress_level: 5, soreness: 5, mood: 5, motivation: 5, anxiety: 3, notes: '[Sunday measurements auto-backfill]' })
          }).catch(function(){});
          return;
        }
      } catch(e2) {}
      _morningCheckinDone = false;
      await showMorningCheckinOverlay();
    } else {
      _morningCheckinDone = false;
      await showMorningCheckinOverlay();
    }
  } catch(e) {
    console.error('Morning checkin check failed', e);
    _morningCheckinDone = true;
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
    const mappedIdx = _userTodayMonIdx();  // user-tz "today", not device-local
    const dayData = weekData.days[mappedIdx];
    if (dayData) {
      lines.push('Today is ' + (dayData.liftName || (dayData.isRest ? 'a rest day' : 'not planned yet')) + ' -- Week ' + currentWeek + '.');
    }
  }
  lines.push('How are you feeling?');
  return lines.join(' ');
}

let _mcExchangeCount = 0;

async function startMorningCheckin() {
  await showMorningCheckinOverlay();
}

async function showMorningCheckinOverlay() {
  const el = document.getElementById('morning-checkin-overlay');
  if (!el) return;
  _mcExchangeCount = 0;
  var dayOfWeek = new Date().getDay();
  var _planningDay = (dayOfWeek === 1) || (dayOfWeek === 0 && new Date().getHours() >= 12);
  var buttonText = _planningDay ? "Let's Start This Week" : "Start Today's Workout";

  if (dayOfWeek === 0) {
    // Sunday — but first check if measurements were already submitted (cross-device).
    // If so, skip the form entirely and just open the coach review (or dismiss).
    try {
      const _mCheck = await fetch('/api/measurements?date=' + todayStr());
      const _mArr = await _mCheck.json();
      if (Array.isArray(_mArr) && _mArr.length > 0) {
        // Already submitted on another device — don't show the form
        _morningCheckinDone = true;
        var _dk = 'sunday_measurements_' + todayStr();
        localStorage.setItem(_dk, '1');
        // Backfill MorningCheckIn if missing
        fetch('/api/morning-checkin', { method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ date: todayStr(), sleep_quality: 5, stress_level: 5, soreness: 5, mood: 5, motivation: 5, anxiety: 3, notes: '[Sunday measurements auto-backfill]' })
        }).catch(function(){});
        el.innerHTML = '';
        renderAll();
        return;
      }
    } catch(e) {}

    // Show measurement form with dismiss button
    el.innerHTML = `<div class="morning-checkin-overlay">
      <div class="morning-checkin-card" style="max-width:500px;display:flex;flex-direction:column;max-height:85vh">
        <div class="morning-briefing" style="flex-shrink:0;display:flex;justify-content:space-between;align-items:center">
          <div class="morning-briefing-label">Sunday Measurements</div>
          <button style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px 8px" onclick="closeMorningCheckin()">&times;</button>
        </div>
        <div style="flex:1;overflow-y:auto;padding:12px 0">
          <div style="font-size:13px;color:var(--muted);margin-bottom:12px">Take all measurements before your coach review.</div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Weight (lb)</label>
            <input type="number" inputmode="decimal" id="sun-weight" class="weight-input" style="width:80px" placeholder="lbs">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Waist (in)</label>
            <input type="number" inputmode="decimal" id="sun-waist" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Chest (in)</label>
            <input type="number" inputmode="decimal" id="sun-chest" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Hips (in)</label>
            <input type="number" inputmode="decimal" id="sun-hips" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Neck (in)</label>
            <input type="number" inputmode="decimal" id="sun-neck" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Bicep L (in)</label>
            <input type="number" inputmode="decimal" id="sun-bicep-l" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Bicep R (in)</label>
            <input type="number" inputmode="decimal" id="sun-bicep-r" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Thigh L (in)</label>
            <input type="number" inputmode="decimal" id="sun-thigh-l" class="weight-input" style="width:80px" placeholder="inches">
          </div>
          <div class="mc-slider-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
            <label style="color:var(--text);font-size:14px;min-width:80px">Thigh R (in)</label>
            <input type="number" inputmode="decimal" id="sun-thigh-r" class="weight-input" style="width:80px" placeholder="inches">
          </div>
        </div>
        <button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="submitSundayMeasurements()">Submit & Start Review</button>
      </div>
    </div>`;
    return; // Don't start coach chat yet — wait for measurement submission
  }

  el.innerHTML = `<div class="morning-checkin-overlay">
    <div class="morning-checkin-card" style="max-width:500px;display:flex;flex-direction:column;max-height:85vh">
      <div class="morning-briefing" style="flex-shrink:0;display:flex;justify-content:space-between;align-items:center">
        <div class="morning-briefing-label">Check-In with Erik</div>
        <button style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px 8px" onclick="finishMorningCheckin()">&times;</button>
      </div>
      <div id="mc-chat-messages" class="mc-coach-messages" style="flex:1;overflow-y:auto;padding:12px 0">
        <div class="mc-typing-indicator"><div class="chat-typing"><span></span><span></span><span></span></div></div>
      </div>
      <div style="flex-shrink:0;padding-top:8px">
        <div class="mc-coach-input-bar">
          <input type="text" id="mc-chat-input" placeholder="Reply to Erik..." enterkeyhint="send" onkeydown="if(event.key==='Enter'){event.preventDefault();sendMcChat()}">
          <button class="chat-mic-btn" onclick="toggleVoiceInput('mc-chat-input')" title="Voice input">&#127908;</button>
          <button onclick="sendMcChat()">Send</button>
        </div>
        <button class="btn btn-primary mc-continue-btn" id="mc-continue-btn" style="display:none;width:100%;margin-top:8px" onclick="finishMorningCheckin()">${buttonText}</button>
      </div>
    </div>
  </div>`;

  // Send trigger to coach to start the check-in conversation
  _startMcChat();
}

async function submitSundayMeasurements() {
  var submitBtn = document.querySelector('.morning-checkin-card .btn-primary');
  if (submitBtn) submitBtn.disabled = true;
  var data = {
    date: todayStr(),
    weight: parseFloat(document.getElementById('sun-weight')?.value) || null,
    waist: parseFloat(document.getElementById('sun-waist')?.value) || null,
    chest: parseFloat(document.getElementById('sun-chest')?.value) || null,
    hips: parseFloat(document.getElementById('sun-hips')?.value) || null,
    neck: parseFloat(document.getElementById('sun-neck')?.value) || null,
    bicep_left: parseFloat(document.getElementById('sun-bicep-l')?.value) || null,
    bicep_right: parseFloat(document.getElementById('sun-bicep-r')?.value) || null,
    thigh_left: parseFloat(document.getElementById('sun-thigh-l')?.value) || null,
    thigh_right: parseFloat(document.getElementById('sun-thigh-r')?.value) || null,
  };

  // Save measurements — MUST verify the save succeeded before proceeding.
  // If this fails silently, the phone shows measurements from memory but the DB
  // has nothing, and no other device can see them.
  var _measSaved = false;
  for (var _attempt = 0; _attempt < 3 && !_measSaved; _attempt++) {
    try {
      var _measRes = await fetch('/api/measurements', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
      });
      if (_measRes.ok) {
        _measSaved = true;
      } else if (_measRes.status === 403) {
        // Should not happen (backend gating removed) but handle gracefully
        alert('Measurements save was blocked by the server. Please try again.');
        if (submitBtn) submitBtn.disabled = false;
        return;
      } else {
        console.error('Measurements save failed (attempt ' + (_attempt+1) + '):', _measRes.status);
        if (_attempt < 2) await new Promise(r => setTimeout(r, 1000));
      }
    } catch(e) {
      console.error('Measurements save network error (attempt ' + (_attempt+1) + '):', e);
      if (_attempt < 2) await new Promise(r => setTimeout(r, 1000));
    }
  }
  if (!_measSaved) {
    alert('Could not save measurements. Check your connection and try again.');
    if (submitBtn) submitBtn.disabled = false;
    return;
  }
  // Clear the cache so the Stats section picks up the new entry
  window._measurementsCache = null;
  window._sundayMeasurements = data;

  // Also save weight to bodyweight tracker
  if (data.weight) {
    await apiPost('/api/bodyweight', { date: todayStr(), weight: data.weight });
  }

  // Create MorningCheckIn record NOW — don't wait for coach conversation to finish.
  // This way even if the user closes the app mid-conversation, the gate is cleared
  // on all devices.
  await fetch('/api/morning-checkin', { method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ date: todayStr(), sleep_quality: 5, stress_level: 5, soreness: 5, mood: 5, motivation: 5, anxiety: 3, notes: '[Sunday measurements submitted]' })
  }).catch(function(){});
  var _sunDk = 'sunday_measurements_' + todayStr();
  localStorage.setItem(_sunDk, '1');
  _morningCheckinDone = true;

  // Transition to the Sunday review coach conversation
  _showSundayReviewChat(data);
}

function _showSundayReviewChat(measurements) {
  var el = document.getElementById('morning-checkin-overlay');
  if (!el) return;
  _mcExchangeCount = 0;

  el.innerHTML = `<div class="morning-checkin-overlay">
    <div class="morning-checkin-card" style="max-width:500px;display:flex;flex-direction:column;max-height:85vh">
      <div class="morning-briefing" style="flex-shrink:0;display:flex;justify-content:space-between;align-items:center">
        <div class="morning-briefing-label">Sunday Review with Erik</div>
        <button style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px 8px" onclick="finishMorningCheckin()">&times;</button>
      </div>
      <div id="mc-chat-messages" class="mc-coach-messages" style="flex:1;overflow-y:auto;padding:12px 0">
        <div class="mc-typing-indicator"><div class="chat-typing"><span></span><span></span><span></span></div></div>
      </div>
      <div style="flex-shrink:0;padding-top:8px">
        <div class="mc-coach-input-bar">
          <input type="text" id="mc-chat-input" placeholder="Reply to Erik..." enterkeyhint="send" onkeydown="if(event.key==='Enter'){event.preventDefault();sendMcChat()}">
          <button class="chat-mic-btn" onclick="toggleVoiceInput('mc-chat-input')" title="Voice input">&#127908;</button>
          <button onclick="sendMcChat()">Send</button>
        </div>
        <button class="btn btn-primary mc-continue-btn" id="mc-continue-btn" style="display:none;width:100%;margin-top:8px" onclick="finishMorningCheckin()">Done</button>
      </div>
    </div>
  </div>`;

  // Build measurement summary string for the trigger
  var measStr = 'Weight: ' + (measurements.weight || '?') + 'lb';
  if (measurements.waist) measStr += ', Waist: ' + measurements.waist + '"';
  if (measurements.chest) measStr += ', Chest: ' + measurements.chest + '"';
  if (measurements.hips) measStr += ', Hips: ' + measurements.hips + '"';
  if (measurements.neck) measStr += ', Neck: ' + measurements.neck + '"';
  if (measurements.bicep_left) measStr += ', Bicep L: ' + measurements.bicep_left + '"';
  if (measurements.bicep_right) measStr += ', Bicep R: ' + measurements.bicep_right + '"';
  if (measurements.thigh_left) measStr += ', Thigh L: ' + measurements.thigh_left + '"';
  if (measurements.thigh_right) measStr += ', Thigh R: ' + measurements.thigh_right + '"';

  // Send Sunday review trigger with measurements — same streaming pattern as _startMcChat
  var trigger = '[SUNDAY_REVIEW] ' + localTimeContext() + ' Measurements just submitted: ' + measStr + '. This is the weekly review session. Cover ALL of the following IN ORDER: 1) MEASUREMENTS — analyze each body part vs last week and baseline, explain hypertrophy vs fat loss indicators. 2) WEIGHT PROGRESS — on pace for target? If not, how far off? 3) WEEK IN REVIEW — each day completed, weights lifted, PRs, missed days. 4) NUTRITION COMPLIANCE — ask directly. 5) What went well. 6) What needs work. One topic at a time. Let me respond before moving on.';

  _startSundayReviewStream(trigger);
}

async function _startSundayReviewStream(trigger) {
  try {
    var res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: trigger }),
    });
    var messagesEl = document.getElementById('mc-chat-messages');
    if (!messagesEl) return;
    var typing = messagesEl.querySelector('.mc-typing-indicator');
    if (typing) typing.remove();

    var bubble = document.createElement('div');
    bubble.className = 'mc-coach-bubble';
    messagesEl.appendChild(bubble);

    var fullText = '';
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      var chunk = decoder.decode(result.value, { stream: true });
      var lines = chunk.split('\n');
      var stop = false;
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('data: ')) {
          var data = lines[i].slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            bubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          bubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory) {
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    var messagesEl = document.getElementById('mc-chat-messages');
    if (messagesEl) {
      var typing = messagesEl.querySelector('.mc-typing-indicator');
      if (typing) typing.remove();
      messagesEl.innerHTML += '<div class="mc-coach-bubble">Let\'s review your week. How are you feeling about your progress?</div>';
    }
  }
  var input = document.getElementById('mc-chat-input');
  if (input) setTimeout(function() { input.focus(); }, 100);
}

async function _startMcChat() {
  var dayOfWeek = new Date().getDay(); // 0=Sun, 1=Mon
  var trigger;

  // Weekly planning is NEVER auto-triggered from morning check-in.
  // Use "Plan Next Week" or "Re-plan This Week" buttons instead.
  var _doWeeklyPlanning = false;

  if (_doWeeklyPlanning) {
    var nextWeek = currentWeek + 1;
    var programData = null;
    if (nextWeek <= 12) {
        try {
            var progRes = await fetch('/api/weekly-program/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ week: nextWeek }),
            });
            if (progRes.ok) programData = await progRes.json();
        } catch(e) {}
    }

    var programSummary = '';
    if (programData && programData.program) {
        var dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        var currentDayP = -1;
        for (var pi = 0; pi < programData.program.length; pi++) {
            var p = programData.program[pi];
            if (p.day !== currentDayP) {
                currentDayP = p.day;
                programSummary += '\n' + dayNames[p.day] + ':';
            }
            var weightStr = p.target_weight ? ' -> ' + p.target_weight + 'lb' : '';
            var reasonStr = p.reason ? ' (' + p.reason + ')' : '';
            programSummary += '\n  ' + p.exercise + ': ' + p.sets + 'x' + p.reps + weightStr + reasonStr;
        }
    }

    var deficitStr = '';
    if (programData && programData.deficit) {
        var dd = programData.deficit;
        deficitStr = '\nDEFICIT: ' + dd.current_weight + 'lb -> ' + dd.target_weight + 'lb, ' +
                     dd.weeks_remaining + ' weeks left, need ' + dd.required_weekly_loss + ' lb/week.';
    }

    var mealSummaryStr = '';
    if (programData && programData.meal_summary) {
        mealSummaryStr = '\n\nMEAL PLAN:';
        var dayNamesM = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        for (var mi = 0; mi < programData.meal_summary.length; mi++) {
            var md = programData.meal_summary[mi];
            mealSummaryStr += '\n  ' + dayNamesM[md.day] + ': ' + md.calories + ' cal, ' + md.protein + 'g protein (' + md.type + ')';
        }
    }

    var runSummaryStr = '';
    if (programData && programData.run_summary) {
        runSummaryStr = '\n\nRUN PLAN:';
        var dayNamesR = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        for (var ri = 0; ri < programData.run_summary.length; ri++) {
            var rd = programData.run_summary[ri];
            runSummaryStr += '\n  ' + dayNamesR[rd.day] + ': ' + rd.label + ' ' + rd.duration + ' (' + rd.type + ')';
        }
    }

    var scheduleSummaryStr = '';
    if (programData && programData.schedule_summary) {
        scheduleSummaryStr = '\n\nDAY SCHEDULE:';
        var dayNamesS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        for (var si = 0; si < programData.schedule_summary.length; si++) {
            var sd = programData.schedule_summary[si];
            var mgStr = sd.muscle_groups && sd.muscle_groups.length ? ' [' + sd.muscle_groups.join(', ') + ']' : '';
            scheduleSummaryStr += '\n  ' + dayNamesS[sd.day] + ': ' + sd.lift_name + (sd.is_rest ? ' (REST)' : '') + mgStr;
        }
    }

    trigger = '[MORNING_CHECKIN] [WEEKLY_PLANNING] ' + localTimeContext() +
        '\nThis is the Monday weekly planning session.' +
        '\n\nPROPOSED PROGRAM FOR WEEK ' + nextWeek + ':' + programSummary +
        deficitStr +
        mealSummaryStr +
        runSummaryStr +
        scheduleSummaryStr +
        '\n\nReview this program with the athlete. For each key exercise, explain WHY the weight/reps changed from last week. Cover the run plan progression and day schedule. Ask about schedule changes. Apply adjustments via [PRESCRIPTION: week=' + nextWeek + ', day=X, exercise=Name, sets=N, reps=R, rest=Xs, weight=X] markers. Use [DAY_SCHEDULE: day=X, lift_name=Name, muscle_groups=a,b,c] to adjust the daily split.';
  } else {
    // Sunday is handled by measurement form + _startSundayReviewStream, so this branch covers Tue-Sat
    // Normal day
    trigger = '[MORNING_CHECKIN] ' + localTimeContext() + ' Start the check-in. Ask how I slept, how I feel physically, my mood and motivation. One question at a time. Be brief. After 2-3 exchanges, transition to today\'s workout — tell me what we\'re doing, what to focus on, any technique cues or mindset notes for the session. End with energy and intent.';
  }

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: trigger }),
    });
    const messagesEl = document.getElementById('mc-chat-messages');
    if (!messagesEl) return;
    // Remove loading indicator
    const typing = messagesEl.querySelector('.mc-typing-indicator');
    if (typing) typing.remove();

    const bubble = document.createElement('div');
    bubble.className = 'mc-coach-bubble';
    messagesEl.appendChild(bubble);

    let fullText = '';
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      let stop = false;
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            const errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            bubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          bubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory) {
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    const messagesEl = document.getElementById('mc-chat-messages');
    if (messagesEl) {
      const typing = messagesEl.querySelector('.mc-typing-indicator');
      if (typing) typing.remove();
      messagesEl.innerHTML += '<div class="mc-coach-bubble">Good morning. How did you sleep?</div>';
    }
  }
  // Focus the input
  const input = document.getElementById('mc-chat-input');
  if (input) setTimeout(() => input.focus(), 100);
}

async function sendMcChat() {
  const input = document.getElementById('mc-chat-input');
  const text = (input.value || '').trim();
  if (!text) return;
  input.value = '';

  const messagesEl = document.getElementById('mc-chat-messages');
  if (!messagesEl) return;

  // Show user message
  messagesEl.innerHTML += '<div class="mc-user-bubble">' + escapeHtml(text) + '</div>';
  messagesEl.innerHTML += '<div class="mc-typing-indicator"><div class="chat-typing"><span></span><span></span><span></span></div></div>';
  messagesEl.scrollTop = messagesEl.scrollHeight;

  _mcExchangeCount++;

  // After 2+ exchanges, show continue button
  if (_mcExchangeCount >= 2) {
    const btn = document.getElementById('mc-continue-btn');
    if (btn) btn.style.display = 'block';
  }

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text }),
    });

    const typing = messagesEl.querySelector('.mc-typing-indicator');
    if (typing) typing.remove();

    const bubble = document.createElement('div');
    bubble.className = 'mc-coach-bubble';
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    let fullText = '';
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      let stop = false;
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            const errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            bubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          bubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory) {
      _chatHistory.push({ role: 'user', content: text, date: todayStr() });
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    const typing = messagesEl.querySelector('.mc-typing-indicator');
    if (typing) typing.remove();
    messagesEl.innerHTML += '<div class="mc-coach-bubble" style="color:var(--muted)">Connection issue. Try again.</div>';
  }

  if (input) input.focus();
}

async function finishMorningCheckin() {
  // Save check-in record — MUST succeed or the overlay will reappear on reload
  try {
    await fetch('/api/morning-checkin', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        date: todayStr(),
        sleep_quality: 5, stress_level: 5, soreness: 5,
        mood: 5, motivation: 5, anxiety: 3,
        notes: '[Coach conversation check-in]',
      }),
    });
  } catch(e) {
    console.error('Morning checkin save failed, retrying...', e);
    // Retry once
    try {
      await fetch('/api/morning-checkin', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          date: todayStr(),
          sleep_quality: 5, stress_level: 5, soreness: 5,
          mood: 5, motivation: 5, anxiety: 3,
          notes: '[Coach conversation check-in]',
        }),
      });
    } catch(e2) { console.error('Morning checkin retry also failed', e2); }
  }

  // Extract real values from the coach conversation (best-effort, async)
  var messagesEl = document.getElementById('mc-chat-messages');
  if (messagesEl) {
      var convo = messagesEl.textContent || '';
      if (convo.length > 20) {
          fetch('/api/morning-checkin/extract', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ conversation: convo }),
          }).catch(function() {}); // Best-effort extraction
      }
  }

  // Mark as done in localStorage so it survives reload even if DB save failed
  var _dow = new Date().getDay();
  var _dismissKey = _dow === 0 ? 'sunday_measurements_' + todayStr() : 'checkin_done_' + todayStr();
  localStorage.setItem(_dismissKey, '1');
  closeMorningCheckin();
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
          <input type="text" id="mc-coach-input" placeholder="Reply to Erik..." enterkeyhint="send" onkeydown="if(event.key==='Enter'){event.preventDefault();sendMorningCoachReply()}">
          <button class="chat-mic-btn" onclick="toggleVoiceInput('mc-coach-input')" title="Voice input">&#127908;</button>
          <button onclick="sendMorningCoachReply()">Send</button>
        </div>
      </div>
      <button class="btn btn-primary mc-continue-btn" id="mc-continue-btn" style="display:none;width:100%;margin-top:12px" onclick="closeMorningCheckin()">Start Today's Workout</button>
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
      let stop = false;
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            const errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            if (streamBubble) streamBubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          if (streamBubble) {
            streamBubble.innerHTML = renderCoachMarkdown(fullText);
            if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
          }
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      if (streamBubble) streamBubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
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
  _morningCheckinDone = true;
  // Persist dismiss key BEFORE re-rendering so lock screen can't reappear
  var _dow = new Date().getDay();
  var _dk = _dow === 0 ? 'sunday_measurements_' + todayStr() : 'checkin_done_' + todayStr();
  localStorage.setItem(_dk, '1');
  document.getElementById('morning-checkin-overlay').innerHTML = '';
  renderCheckinSummaryBar();
  renderDetail(); // Unlock the daily view

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
          <div class="report-stat"><span class="report-stat-label">Workouts</span><span class="report-stat-val">${m.workouts_completed || 0}/${m.workouts_total != null ? m.workouts_total : '&mdash;'}</span></div>
          <div class="report-stat"><span class="report-stat-label">Weight</span><span class="report-stat-val">${m.weight_change ? (m.weight_change > 0 ? '+' : '') + m.weight_change + ' lbs' : '--'}</span></div>
          <div class="report-stat"><span class="report-stat-label">vs Target</span><span class="report-stat-val">${m.weight_vs_projected || '--'}</span></div>
          <div class="report-stat"><span class="report-stat-label">Adherence</span><span class="report-stat-val">${m.adherence_pct != null ? m.adherence_pct + '%' : '&mdash;'}</span></div>
        </div>
        ${narrative ? '<div class="report-narrative">' + narrative + '</div>' : ''}
        <div id="bw-progression-section"></div>
        <div id="shopping-list-section"></div>
        <button class="btn btn-primary" style="width:100%;margin-top:1rem" onclick="document.getElementById('morning-checkin-overlay').innerHTML='';triggerWeeklyPlanning()">Continue to Weekly Planning</button>
      </div>
    </div>`;
    // Load bodyweight progression (baseline vs retests)
    try {
      const bwRes = await fetch('/api/bodyweight-retest/deltas');
      const bwData = await bwRes.json();
      const bwEl = document.getElementById('bw-progression-section');
      if (bwEl && bwData.baseline && bwData.retests && bwData.retests.length > 0) {
        const LABELS = {
          squat_count: 'Air Squats (60s)',
          pushup_count: 'Pushups (60s)',
          burpee_count: 'Burpees (60s)',
          plank_seconds: 'Plank (sec)',
        };
        // Use most recent retest
        const latest = bwData.retests[bwData.retests.length - 1];
        let rows = '';
        for (const field of ['squat_count','pushup_count','burpee_count','plank_seconds']) {
          const d = latest.deltas[field];
          if (!d) continue;
          const sign = d.delta > 0 ? '+' : '';
          const cls = d.delta > 0 ? 'bw-up' : (d.delta < 0 ? 'bw-down' : 'bw-flat');
          rows += `<div class="bw-prog-row">
            <span class="bw-prog-label">${LABELS[field]}</span>
            <span class="bw-prog-vals">${d.baseline} → ${d.current}</span>
            <span class="bw-prog-delta ${cls}">${sign}${d.delta}</span>
          </div>`;
        }
        if (rows) {
          bwEl.innerHTML = `<div class="plan-section" style="margin-top:1rem">
            <div class="plan-section-label">Bodyweight progression — Week ${latest.week_number} retest</div>
            <div class="bw-prog-list">${rows}</div>
          </div>`;
        }
      }
    } catch(e) {}

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

  // Send the weekly planning trigger to Coach
  const weekNum = currentWeek;
  const nextWeek = Math.min(weekNum + 1, 12);

  // Include bodyweight progression deltas if a retest landed this week
  let bwLine = '';
  try {
    const bwRes = await fetch('/api/bodyweight-retest/deltas');
    const bwData = await bwRes.json();
    if (bwData.retests && bwData.retests.length > 0) {
      const latest = bwData.retests[bwData.retests.length - 1];
      const parts = [];
      const LBL = { squat_count: 'squats', pushup_count: 'pushups', burpee_count: 'burpees', plank_seconds: 'plank(s)' };
      for (const f of ['squat_count','pushup_count','burpee_count','plank_seconds']) {
        const d = latest.deltas[f];
        if (!d) continue;
        const sign = d.delta > 0 ? '+' : '';
        parts.push(`${LBL[f]} ${d.baseline}→${d.current} (${sign}${d.delta})`);
      }
      if (parts.length) {
        bwLine = ` Week ${latest.week_number} bodyweight retest: ${parts.join(', ')}.`;
      }
    }
  } catch(e) {}

  const msg = `[WEEKLY_PLANNING] It's Sunday. Week ${weekNum} is done, week ${nextWeek} starts tomorrow.${bwLine} Review my week, then let's plan. Ask me about any travel, races, schedule changes, or injuries for the coming week. Adjust the plan based on what I tell you.`;

  // Send via API, then show result in Coach accordion
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

    // Show the response in the Coach accordion
    renderDetail();
    toggleChatOverlay();

    localStorage.setItem(planKey, '1');
  } catch(e) {
    console.error('Weekly planning failed', e);
  }
}

function renderCheckinSummaryBar() {
  return; // Removed from UI
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

function _getChatOpener() {
  try {
    const weekData = workoutData[String(currentWeek)];
    const todayJsDay = new Date().getDay();
    const todayMon = todayJsDay === 0 ? 6 : todayJsDay - 1;
    const dayData = weekData && weekData.days ? weekData.days[todayMon] : null;
    if (dayData) {
      const name = dayData.liftName || 'Rest';
      if (dayData.isRest) return "Rest day. What's on your mind?";
      return `${name} today. Talk to me.`;
    }
  } catch(e) {}
  return "Talk to me.";
}

function toggleChatOverlay() {
    // If morning check-in isn't done, start it directly
    if (!_morningCheckinDone) {
        showMorningCheckinOverlay();
        return;
    }
    var accSection = document.getElementById('acc-coach');
    if (accSection) {
        if (!accSection.classList.contains('open')) {
            toggleAccordion('coach');
        }
        accSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        var chatContainer = document.getElementById('coach-inline-chat');
        if (chatContainer && chatContainer.querySelector('button')) {
            openInlineCoachChat();
        }
    }
}

function closeChatOverlay() {
  return;
}

function renderChatOverlay() {
  return;
}

async function _fetchChatOpener() {
  return;
}

function renderChatMessages(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  let html = '';
  for (const m of _chatHistory) {
    const isUser = m.role === 'user';
    const bubbleCls = isUser ? 'chat-bubble user' : 'chat-bubble coach';
    const tsCls = isUser ? 'chat-timestamp ts-user' : 'chat-timestamp ts-coach';
    const rawText = m.text || m.content || '';
    // Coach messages get markdown rendering (bold, headers, line breaks);
    // user messages get raw-escape since they're verbatim.
    const body = isUser ? escapeHtml(rawText) : renderCoachMarkdown(rawText);
    html += `<div class="${bubbleCls}">${body}</div>`;
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
    // Append user bubble directly — don't re-render all history
    const container = document.getElementById(containerId);
    if (container) {
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble user';
        bubble.textContent = text;
        container.appendChild(bubble);
        container.scrollTop = container.scrollHeight;
    }

    // Show typing indicator
    const msgContainer = document.getElementById(containerId);
    if (msgContainer) {
        const typing = document.createElement('div');
        typing.className = 'chat-typing';
        typing.id = 'chat-typing-' + containerId;
        typing.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
        msgContainer.appendChild(typing);
        msgContainer.scrollTop = msgContainer.scrollHeight;
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
            let stop = false;
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') { stop = true; break; }
                    if (data.startsWith('[ERROR')) {
                        const errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
                        fullText += '\n\n[Coach error: ' + errMsg + ']';
                        if (streamBubble) {
                            streamBubble.innerHTML = renderCoachMarkdown(fullText);
                            if (container) container.scrollTop = container.scrollHeight;
                        }
                        stop = true; break;
                    }
                    fullText += data.replace(/\\n/g, '\n');
                    if (streamBubble) {
                        streamBubble.innerHTML = renderCoachMarkdown(fullText);
                        if (container) container.scrollTop = container.scrollHeight;
                    }
                }
            }
            if (stop) break;
        }
        if (!fullText.trim()) {
            if (streamBubble) streamBubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
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

    // Don't re-render history — messages were appended during streaming
    updateChatFabPulse();
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
    const rawText = m.text || m.content || '';
    const body = isUser ? escapeHtml(rawText) : renderCoachMarkdown(rawText);
    chatMessagesHtml += `<div class="${bubbleCls}">${body}</div>`;
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
function closeGarminPanel() {
  const el = document.getElementById('garmin-panel');
  if (el) el.remove();
}

async function showGarminPanel() {
  closeGarminPanel();
  const wrap = document.createElement('div');
  wrap.id = 'garmin-panel';
  wrap.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px';
  wrap.innerHTML = '<div style="background:var(--card,#16181d);border:1px solid var(--border);border-radius:12px;max-width:440px;width:100%;max-height:85vh;overflow-y:auto;padding:20px" onclick="event.stopPropagation()">' +
      '<h3 style="font-size:20px;margin-bottom:14px">&#8986; Garmin Sync</h3>' +
      '<div id="garmin-panel-body" style="font-size:16px">Loading&hellip;</div>' +
      '<button class="btn btn-secondary" style="width:100%;margin-top:14px;font-size:16px" onclick="closeGarminPanel()">Close</button>' +
    '</div>';
  wrap.onclick = closeGarminPanel;
  document.body.appendChild(wrap);
  await renderGarminPanelBody();
}

async function renderGarminPanelBody() {
  const body = document.getElementById('garmin-panel-body');
  if (!body) return;
  let st = null;
  try { st = await (await fetch('/api/garmin/sync-status?week=' + currentWeek)).json(); } catch(e) {}
  if (!st || !st.connected) {
    body.innerHTML =
      '<div style="color:var(--muted);margin-bottom:10px;font-size:16px">Not connected.</div>' +
      '<input id="garmin-email" type="email" placeholder="Garmin email" class="weight-input" style="width:100%;margin-bottom:8px;font-size:16px">' +
      '<input id="garmin-password" type="password" placeholder="Password" class="weight-input" style="width:100%;margin-bottom:8px;font-size:16px">' +
      '<input id="garmin-mfa" type="text" placeholder="MFA code" class="weight-input" style="width:100%;margin-bottom:8px;font-size:16px;display:none">' +
      '<div id="garmin-error" style="display:none;color:#e66;margin-bottom:8px;font-size:15px"></div>' +
      '<button id="garmin-submit" class="btn btn-primary" style="width:100%;font-size:16px" onclick="garminLogin()">Connect</button>';
    return;
  }
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const rows = (st.workouts || []).map(w =>
    '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:15px">' +
      '<span>' + days[w.day_idx] + (w.scheduled_date ? ' &middot; ' + w.scheduled_date : '') + '</span>' +
      (w.status === 'ok'
        ? '<span style="color:var(--accent)">&#10003; on watch</span>'
        : '<span style="color:#e66" title="' + String(w.error || '').replace(/"/g, '&quot;') + '">&#10007; failed</span>') +
    '</div>').join('');
  var connLine = (st.live === false)
    ? '<div style="margin-bottom:10px;color:var(--run-tempo);font-size:16px">&#10003; Connected &middot; reconnecting&hellip;</div>'
    : '<div style="margin-bottom:10px;color:var(--accent);font-size:16px">&#10003; Connected</div>';
  body.innerHTML =
    connLine +
    '<div style="color:var(--muted);font-size:14px;margin-bottom:12px">Last run sync: ' +
      (st.last_activity_sync ? st.last_activity_sync.replace('T', ' ').slice(0, 16) + ' UTC' : 'not yet (this server session)') + '</div>' +
    '<button class="btn btn-primary" style="width:100%;font-size:16px;margin-bottom:8px" onclick="garminSyncNow(this)">Sync runs now</button>' +
    '<button class="btn btn-primary" style="width:100%;font-size:16px;margin-bottom:12px" onclick="garminPushWeek(this)">Push Week ' + currentWeek + ' to watch</button>' +
    '<div style="font-size:14px;color:var(--muted);margin-bottom:4px">Week ' + st.week + ' workouts on Garmin:</div>' +
    (rows || '<div style="color:var(--muted);font-size:15px">None pushed yet.</div>') +
    '<button class="btn btn-secondary" style="width:100%;margin-top:12px;font-size:14px" onclick="garminLogout().then(renderGarminPanelBody)">Disconnect Garmin</button>';
}

async function garminSyncNow(btn) {
  btn.disabled = true; btn.textContent = 'Syncing…';
  try {
    const d = await (await fetch('/api/garmin/sync-activities', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({force: true}),
    })).json();
    if (d.error) { showToast('Garmin sync failed: ' + d.error, 'error'); }
    else {
      showToast('Synced. ' + (d.days_filled || []).length + ' day(s) filled' +
        ((d.days_skipped_manual || []).length ? ', ' + d.days_skipped_manual.length + ' manual day(s) untouched' : ''), 'success');
      const rl = await fetch('/api/run-log');
      if (rl.ok) { _runLogCache = await rl.json(); renderDetail(); }
    }
  } catch(e) { showToast('Garmin sync failed', 'error'); }
  btn.disabled = false; btn.textContent = 'Sync runs now';
  renderGarminPanelBody();
}

async function garminPushWeek(btn) {
  btn.disabled = true; btn.textContent = 'Pushing…';
  try {
    const d = await (await fetch('/api/garmin/push-week', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({week: currentWeek}),
    })).json();
    if (d.error) { showToast('Push failed: ' + d.error, 'error'); }
    else {
      showToast('Pushed ' + (d.pushed || []).length + ', skipped ' + (d.skipped || []).length +
        ', failed ' + (d.failed || []).length, (d.failed || []).length ? 'error' : 'success');
    }
  } catch(e) { showToast('Push failed', 'error'); }
  btn.disabled = false; btn.textContent = 'Push Week ' + currentWeek + ' to watch';
  renderGarminPanelBody();
}

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
        await renderGarminPanelBody();
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
      await renderGarminPanelBody();
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

// User's actual program week — computed from start_date, NOT the week the user is viewing.
// Returns the week number (1-12) or null if state not loaded.
function getActualProgramWeek() {
  // Prefer the SERVER's current_week — it's computed in the user's stored
  // timezone (_user_today). Computing from device-local new Date() drifted at
  // the midnight boundary / across timezones, putting the header a week off.
  if (_stateCache && _stateCache.current_week) return _stateCache.current_week;
  if (!_stateCache || !_stateCache.start_date) return null;
  const originDate = (_stateCache.user_date || _stateCache.server_date);
  const nowDt = originDate ? new Date(originDate + 'T00:00:00') : new Date();
  const startDt = new Date(_stateCache.start_date + 'T00:00:00');
  const diffDays = Math.floor((nowDt - startDt) / (1000 * 60 * 60 * 24));
  return Math.min(12, Math.max(1, Math.floor(diffDays / 7) + 1));
}

// The user's "today" weekday (Mon=0..Sun=6) from the SERVER's user-timezone
// date, not device-local time — so day-nav/streak don't drift at midnight.
function _userTodayMonIdx() {
  var ud = _stateCache && _stateCache.user_date;
  var jsDay = ud ? new Date(ud + 'T00:00:00').getDay() : new Date().getDay();
  return jsDay === 0 ? 6 : jsDay - 1;
}

// Used by swipe gestures — always navigates (no toggle), clamps at week boundaries
function navigateDay(direction) {
  if (currentDay === null) return;
  const next = currentDay + direction;
  if (next < 0 || next > 6) return;
  currentDay = next;
  renderTodayNav();
  renderDayGrid();
  renderDetail();
}

// Attach swipe handlers to the detail panel — call once after first render
let _swipeHandlersAttached = false;
function attachSwipeHandlers() {
  if (_swipeHandlersAttached) return;
  const panel = document.getElementById('detail-panel');
  if (!panel) return;
  _swipeHandlersAttached = true;

  let startX = 0, startY = 0, startT = 0;
  let tracking = false;   // actively touching, intent undecided
  let committed = false;  // committed to a horizontal swipe
  let lastDx = 0;

  function innerEl() { return panel.querySelector('.detail-inner'); }

  function setDrag(px) {
    const el = innerEl();
    if (!el) return;
    // Resistance past 120px so it doesn't slide off forever
    const clamped = Math.sign(px) * Math.min(Math.abs(px), 120 + Math.abs(px) * 0.15);
    el.style.transition = 'none';
    el.style.transform = 'translateX(' + clamped + 'px)';
    el.style.opacity = String(Math.max(0.55, 1 - Math.abs(px) / 400));
  }

  function settle(commit) {
    const el = innerEl();
    if (!el) return;
    el.style.transition = 'transform 0.18s ease, opacity 0.18s ease';
    if (commit) {
      // Slide fully off in the swipe direction, then renderDetail will replace content
      const dir = lastDx < 0 ? -1 : 1;
      el.style.transform = 'translateX(' + (dir * window.innerWidth) + 'px)';
      el.style.opacity = '0';
      setTimeout(function() {
        el.style.transition = 'none';
        el.style.transform = '';
        el.style.opacity = '';
      }, 200);
    } else {
      el.style.transform = '';
      el.style.opacity = '';
    }
  }

  panel.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) { tracking = false; committed = false; return; }
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'button' || tag === 'textarea' || tag === 'select') {
      tracking = false; committed = false; return;
    }
    // Don't intercept if the touch started inside a scrollable horizontal list
    if (e.target.closest && e.target.closest('.tn-days, .hiit-overlay, [data-no-swipe]')) {
      tracking = false; committed = false; return;
    }
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    startT = Date.now();
    tracking = true;
    committed = false;
    lastDx = 0;
  }, { passive: true });

  panel.addEventListener('touchmove', (e) => {
    if (!tracking) return;
    const dx = e.touches[0].clientX - startX;
    const dy = e.touches[0].clientY - startY;
    lastDx = dx;
    if (!committed) {
      // Decide intent once we've moved >10px in either axis
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (Math.abs(dy) > Math.abs(dx) * 1.2) {
        // Vertical intent — let the page scroll, abort swipe tracking
        tracking = false;
        return;
      }
      committed = true;
    }
    setDrag(dx);
  }, { passive: true });

  panel.addEventListener('touchend', (e) => {
    if (!tracking) { if (committed) settle(false); committed = false; return; }
    tracking = false;
    if (!committed) return;
    committed = false;
    const dt = Date.now() - startT;
    const dx = lastDx;
    // Commit if: moved >40px OR fast flick (>25px in <250ms)
    const distOk = Math.abs(dx) > 40;
    const flickOk = Math.abs(dx) > 25 && dt < 250;
    if ((distOk || flickOk) && dt < 700) {
      settle(true);
      navigateDay(dx < 0 ? 1 : -1);
    } else {
      settle(false);
    }
  }, { passive: true });

  panel.addEventListener('touchcancel', () => {
    if (committed) settle(false);
    tracking = false; committed = false;
  }, { passive: true });
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
      const summary = `[WORKOUT_COMPLETE] Just finished ${d.liftName || 'the workout'}. ` +
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
  return; // Removed from UI
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
function renderWarmupInner(dayData) {
  if (!dayData.warmup) return '';
  const wu = dayData.warmup;
  return `<button class="warmup-toggle open" onclick="document.getElementById('warmup-body').classList.toggle('visible');this.classList.toggle('open')">
      <h3 style="margin:0">Warm-Up${wu.time ? ' - ' + wu.time : ''}</h3>
      <span class="warmup-arrow">\u25BC</span>
    </button>
    <div class="warmup-body visible" id="warmup-body">
      ${(wu.steps || []).map((step, i) => {
        const isWuDone = _warmupCache[currentWeek + '_' + currentDay + '_' + i];
        // Show REPS. Bare numbers get a "reps" suffix ("15" -> "15 reps");
        // qualified counts pass through ("10 per leg"); a genuine time hold
        // ("30s") shows as-is. Never label a duration as "reps".
        const _m = step.reps != null && step.reps !== '' ? String(step.reps) : (step.duration || '');
        const repsHtml = _m
          ? `<span class="warmup-step-reps">${/^\d+$/.test(_m.trim()) ? _m + ' reps' : _m}</span>`
          : '';
        return `<div class="warmup-step" id="wu-step-${i}">
        <button class="wu-check${isWuDone ? ' done' : ''}" onclick="toggleWarmup(${currentWeek},${currentDay},${i},this)">${isWuDone ? '&#10003;' : ''}
        </button>
        <div class="wu-step-content" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="warmup-step-name">${step.name}</span>${repsHtml}${step.note ? `<span class="warmup-step-note">· ${step.note}</span>` : ''}<a class="ex-video-link" href="https://www.youtube.com/results?search_query=${encodeURIComponent(step.name + ' form short')}&sp=EgIYAQ%253D%253D" target="_blank" rel="noopener" title="Watch form video">&#9654;</a>
        </div>
      </div>`;
      }).join('')}
    </div>`;
}

function renderWarmupSection(dayData) {
    const inner = renderWarmupInner(dayData);
    if (!inner) return '';
    return '<div class="detail-section warmup-section">' + inner + '</div>';
}

function toggleWarmup(week, dayIdx, stepIdx, btn) {
  const key = week + '_' + dayIdx + '_' + stepIdx;
  _warmupCache[key] = !_warmupCache[key];
  btn.classList.toggle('done');
  btn.innerHTML = _warmupCache[key] ? '&#10003;' : '';
  apiPost('/api/warmup-completions', { week, day_idx: dayIdx, step_idx: stepIdx });
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
        <input type="text" id="post-workout-input" placeholder="Talk to Erik about your workout..." enterkeyhint="send" onkeydown="if(event.key==='Enter'){event.preventDefault();sendPostWorkoutMessage()}">
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
  const dur = parseInt(document.getElementById('run-dur')?.value) || null;

  // Check if this is an edit (cache already has data for this key)
  var key = currentWeek + '_' + currentDay;
  var isEdit = _runLogCache && _runLogCache[key] && (_runLogCache[key].distance_miles || _runLogCache[key].avg_hr);

  await apiPost('/api/run-log', {
    week: currentWeek, day_idx: currentDay,
    distance_miles: dist, avg_hr: hr, elevation_ft: elev, duration_min: dur,
  });

  if (!_runLogCache) _runLogCache = {};
  _runLogCache[key] = { distance_miles: dist, avg_hr: hr, elevation_ft: elev, duration_min: dur, source: 'manual' };

  showToast('Run logged!', 'success');

  if (!isEdit) {
    // First save — open inline coach run chat
    _openInlineRunCoachChat(dist, hr, elev);
  } else {
    // Edit — just re-render, no coach trigger
    renderDetail();
  }
}

function _openInlineRunCoachChat(dist, hr, elev) {
  // Open the exercise-focus overlay with an inline coach chat for run feedback
  var el = document.getElementById('exercise-focus');
  if (!el) { renderDetail(); return; }

  window._runChatExchanges = 0;

  var triggerMsg = '[RUN_COMPLETE] The run is FINISHED. Actual results: ' + (dist || '?') + ' mi, avg HR ' + (hr || '?') + ', elev ' + (elev || '?') + ' ft. ANALYZE the completed run — do NOT prescribe or say "get the run done." The run is done. Compare actual distance and HR to the prescription. State what went well or didn\'t based on the numbers. One question about how it felt. No praise.';

  el.innerHTML =
    '<button class="focus-back" onclick="exitExerciseFocus()">&larr;</button>' +
    '<div class="focus-content" style="max-width:400px;width:100%">' +
      '<div style="font-size:36px;text-align:center;margin-bottom:4px">&#127939;</div>' +
      '<div class="focus-ex-name" style="margin-bottom:4px">Run Complete</div>' +
      '<div style="font-family:\'DM Mono\',monospace;font-size:14px;color:var(--accent);text-align:center;margin-bottom:12px">' + (dist || '?') + ' mi \u00B7 HR ' + (hr || '?') + '</div>' +
      '<div id="run-coach-messages" style="max-height:40vh;overflow-y:auto;padding:8px 0;width:100%">' +
        '<div class="chat-bubble coach" style="background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px"><div class="chat-typing"><span></span><span></span><span></span></div></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:8px;width:100%">' +
        '<input type="text" id="run-coach-input" placeholder="Reply to Erik..." enterkeyhint="send" ' +
          'onkeydown="if(event.key===\'Enter\')sendRunCoachMsg()" ' +
          'style="flex:1;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;padding:10px 14px;color:var(--text);font-size:15px;outline:none">' +
        '<button onclick="sendRunCoachMsg()" style="background:var(--coach);color:#000;border:none;border-radius:8px;padding:10px 16px;font-weight:600;cursor:pointer;font-size:14px">Send</button>' +
      '</div>' +
      '<div id="run-coach-done-btn-container" style="width:100%;margin-top:12px"></div>' +
    '</div>';
  el.classList.add('visible');

  _fetchRunCoachOpener(triggerMsg);
}

async function _fetchRunCoachOpener(triggerMsg) {
  var messagesEl = document.getElementById('run-coach-messages');
  if (!messagesEl) return;
  var bubble = messagesEl.querySelector('.chat-bubble.coach');
  try {
    var res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: triggerMsg }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    if (bubble) bubble.innerHTML = '';
    var fullText = '';
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      var chunk = decoder.decode(result.value, { stream: true });
      var lines = chunk.split('\n');
      var stop = false;
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('data: ')) {
          var data = lines[i].slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      if (bubble) bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory && fullText.trim()) {
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    if (bubble) bubble.textContent = 'Nice run! How did it feel out there?';
  }
  var input = document.getElementById('run-coach-input');
  if (input) setTimeout(function() { input.focus(); }, 100);
}

async function sendRunCoachMsg() {
  var input = document.getElementById('run-coach-input');
  var text = (input.value || '').trim();
  if (!text) return;
  input.value = '';

  var messagesEl = document.getElementById('run-coach-messages');
  if (!messagesEl) return;

  // User bubble
  var userBubble = document.createElement('div');
  userBubble.style.cssText = 'background:var(--surface2);border:1px solid var(--border2);border-radius:12px;padding:10px 14px;font-size:14px;line-height:1.5;color:var(--text);margin-bottom:8px;align-self:flex-end;text-align:right';
  userBubble.textContent = text;
  messagesEl.appendChild(userBubble);

  // Typing indicator
  var typingBubble = document.createElement('div');
  typingBubble.className = 'chat-bubble coach';
  typingBubble.style.cssText = 'background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px';
  typingBubble.innerHTML = '<div class="chat-typing"><span></span><span></span><span></span></div>';
  messagesEl.appendChild(typingBubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  try {
    var res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text }),
    });
    typingBubble.innerHTML = '';
    var fullText = '';
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      var chunk = decoder.decode(result.value, { stream: true });
      var lines = chunk.split('\n');
      var stop = false;
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('data: ')) {
          var data = lines[i].slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            typingBubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          typingBubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      typingBubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory) {
      _chatHistory.push({ role: 'user', content: text, date: todayStr() });
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    typingBubble.textContent = 'Connection issue. Try again.';
  }

  window._runChatExchanges = (window._runChatExchanges || 0) + 1;

  // After 2+ exchanges, show "Back to Schedule" button
  if (window._runChatExchanges >= 2) {
    var btnContainer = document.getElementById('run-coach-done-btn-container');
    if (btnContainer && !btnContainer.querySelector('button')) {
      var btn = document.createElement('button');
      btn.className = 'focus-log-btn';
      btn.textContent = 'Back to Schedule';
      btn.onclick = function() {
        exitExerciseFocus();
      };
      btnContainer.appendChild(btn);
    }
  }

  if (input) input.focus();
}

// startWarmupTimer removed — each warm-up step now has its own Start button

// ─── WEEKLY CHECK-IN ────────────────────────────────────────────────────────
function renderCheckinInner(dayData, dayIdx) {
  // Sunday-only — gate by ACTUAL today (not the day the user is viewing).
  // JS getDay(): Sun=0. The entry form should only appear on real Sundays;
  // history/deltas live in renderMeasurementsSection (always visible).
  if (new Date().getDay() !== 0) return '';
  // Also require that the user is viewing Sunday in the grid (Mon=0, Sun=6)
  if (dayIdx !== 6) return '';
  // Check if measurements already saved today (from Sunday morning flow)
  var saved = window._sundayMeasurements || null;
  var fields = [
    {id: 'checkin-weight', label: 'Weight (lb)', key: 'weight', type: 'number', step: '0.1', placeholder: 'lbs'},
    {id: 'checkin-waist', label: 'Waist (in)', key: 'waist', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-chest', label: 'Chest (in)', key: 'chest', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-hips', label: 'Hips (in)', key: 'hips', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-neck', label: 'Neck (in)', key: 'neck', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-bicep-l', label: 'Bicep L (in)', key: 'bicep_left', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-bicep-r', label: 'Bicep R (in)', key: 'bicep_right', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-thigh-l', label: 'Thigh L (in)', key: 'thigh_left', type: 'number', step: '0.25', placeholder: 'inches'},
    {id: 'checkin-thigh-r', label: 'Thigh R (in)', key: 'thigh_right', type: 'number', step: '0.25', placeholder: 'inches'},
  ];
  if (saved) {
    // Already submitted — show read-only values
    var readRows = fields.map(function(f) {
      var val = saved[f.key] || '';
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">' +
        '<span style="color:var(--text);font-size:14px">' + f.label + '</span>' +
        '<span style="color:var(--accent);font-family:\'DM Mono\',monospace;font-size:14px">' + (val || '--') + '</span>' +
      '</div>';
    }).join('');
    return '<h3>Sunday Measurements</h3>' +
      '<div style="font-size:12px;color:var(--accent);margin-bottom:8px">Submitted today</div>' +
      readRows;
  }
  var rows = fields.map(function(f) {
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">' +
      '<label style="color:var(--text);font-size:14px;min-width:90px">' + f.label + '</label>' +
      '<input type="' + f.type + '" inputmode="decimal" id="' + f.id + '" class="weight-input" style="width:80px" placeholder="' + f.placeholder + '" step="' + f.step + '">' +
    '</div>';
  }).join('');
  return '<h3>Sunday Measurements</h3>' +
    '<div class="checkin-form" id="checkin-form">' +
      '<div style="font-size:12px;color:var(--muted);margin-bottom:8px">Measure everything. Coach reviews on Sunday.</div>' +
      rows +
      '<div style="padding:6px 0"><label style="color:var(--text);font-size:14px">Notes</label>' +
        '<textarea id="checkin-notes" class="checkin-notes" placeholder="How did this week go?" rows="2" style="width:100%;margin-top:4px"></textarea>' +
      '</div>' +
      '<button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="submitWeeklyMeasurements()">Submit Measurements</button>' +
    '</div>';
}

function renderCheckinSection(dayData, dayIdx) {
    const inner = renderCheckinInner(dayData, dayIdx);
    if (!inner) return '';
    return '<div class="detail-section checkin-form-section">' + inner + '</div>';
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
  // Legacy — kept for compatibility
  submitWeeklyMeasurements();
}

async function submitWeeklyMeasurements() {
  var submitBtn = document.querySelector('#checkin-form .btn-primary');
  if (submitBtn) submitBtn.disabled = true;
  var data = {
    date: todayStr(),
    weight: parseFloat(document.getElementById('checkin-weight')?.value) || null,
    waist: parseFloat(document.getElementById('checkin-waist')?.value) || null,
    chest: parseFloat(document.getElementById('checkin-chest')?.value) || null,
    hips: parseFloat(document.getElementById('checkin-hips')?.value) || null,
    neck: parseFloat(document.getElementById('checkin-neck')?.value) || null,
    bicep_left: parseFloat(document.getElementById('checkin-bicep-l')?.value) || null,
    bicep_right: parseFloat(document.getElementById('checkin-bicep-r')?.value) || null,
    thigh_left: parseFloat(document.getElementById('checkin-thigh-l')?.value) || null,
    thigh_right: parseFloat(document.getElementById('checkin-thigh-r')?.value) || null,
    notes: (document.getElementById('checkin-notes')?.value || '').trim(),
  };

  var _wmSaved = false;
  for (var _wma = 0; _wma < 3 && !_wmSaved; _wma++) {
    try {
      var _wmRes = await fetch('/api/measurements', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
      });
      if (_wmRes.ok) {
        _wmSaved = true;
      } else {
        var _wmErr = '';
        try { _wmErr = (await _wmRes.json()).error || ''; } catch(e) {}
        console.error('Measurements save failed (attempt ' + (_wma+1) + '):', _wmRes.status, _wmErr);
        if (_wma < 2) await new Promise(r => setTimeout(r, 1000));
      }
    } catch(e) {
      console.error('Measurements save network error (attempt ' + (_wma+1) + '):', e);
      if (_wma < 2) await new Promise(r => setTimeout(r, 1000));
    }
  }
  if (!_wmSaved) {
    alert('Could not save measurements. Check your connection and try again.');
    if (submitBtn) submitBtn.disabled = false;
    return;
  }
  window._measurementsCache = null;

  if (data.weight) {
    await fetch('/api/bodyweight', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ date: todayStr(), weight: data.weight }),
    }).catch(function(){});
  }

  // Visual feedback — only shown AFTER confirmed save
  var form = document.getElementById('checkin-form');
  if (form) {
    form.innerHTML = '<div style="text-align:center;color:var(--accent);padding:1rem">Measurements saved.</div>';
  }
}

// ─── PROGRESS DASHBOARD ────────────────────────────────────────────────────
function showProgress() {
  // Don't show progress if onboarding isn't complete
  if (!_stateCache || !_stateCache.baseline_done) return;
  var overlay = document.getElementById('progress-overlay');
  if (!overlay) return;
  overlay.classList.add('visible');
  overlay.innerHTML = '<div class="progress-loading">Loading progress data...</div>';

  // Timeout: if API doesn't respond in 8 seconds, render from local caches
  var _rendered = false;
  var _timeout = setTimeout(function() {
    if (!_rendered) { _rendered = true; _renderNewDashboard(null); }
  }, 8000);

  fetch('/api/progress/dashboard')
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) {
      clearTimeout(_timeout);
      if (!_rendered) { _rendered = true; try { _renderNewDashboard(data); } catch(e) { console.error('Dashboard render error:', e); _renderNewDashboard(null); } }
    })
    .catch(function(e) {
      console.error('Dashboard fetch error:', e);
      clearTimeout(_timeout);
      if (!_rendered) { _rendered = true; _renderNewDashboard(null); }
    });
}

function closeProgress() {
  var overlay = document.getElementById('progress-overlay');
  if (overlay) overlay.classList.remove('visible');
}

/* ─── NEW PROGRESS DASHBOARD ─────────────────────────────────────────────── */

function _renderNewDashboard(apiData) {
  var overlay = document.getElementById('progress-overlay');
  if (!overlay) return;
  try { _renderNewDashboardInner(apiData, overlay); } catch(e) {
    console.error('Dashboard render crash:', e);
    overlay.innerHTML = '<div class="pd-header"><button class="pd-close" onclick="closeProgress()">&times;</button><span class="pd-title">Progress</span></div><div style="padding:2rem;color:#ef4444">Dashboard error: ' + e.message + '</div>';
  }
}
function _renderNewDashboardInner(apiData, overlay) {
  // Backend is the authoritative source. Local caches are only used when the
  // endpoint is unreachable (offline / timeout fallback).
  var d = apiData || {};
  var bwData = d.bodyweight || {};
  var bw = bwData.series || _bodyweightCache || [];
  var measurements = d.measurements || window._measurementsCache || [];
  var training = d.training || {};
  var lifts = d.lifts || _weightsCache || {};
  var projections = d.projections || {};
  var startDate = projections.start_date || (_stateCache ? _stateCache.start_date : null) || null;
  var targetWeight = bwData.target_weight || null;
  var psychHighlights = d.psych_highlights || {};
  var psychQuote = psychHighlights.quote || null;

  var startWeight = bwData.start_weight || (bw.length > 0 ? bw[0].weight : null);
  var currentWeight = bwData.current_weight || (bw.length > 0 ? bw[bw.length - 1].weight : null);

  var html = '';
  html += '<div class="pd-header">';
  html += '<button class="pd-close" onclick="closeProgress()" aria-label="Close">&times;</button>';
  html += '<span class="pd-title">Progress</span>';
  html += '<button class="progress-share" onclick="shareWeeklySummary()">Share</button>';
  html += '</div>';

  // ── TAB BAR ──
  html += '<div class="sp-tabs">';
  html += '<button class="sp-tab active" onclick="_spSwitchTab(\'dashboard\',this)">Dashboard</button>';
  html += '<button class="sp-tab" onclick="_spSwitchTab(\'lab\',this)">Lab</button>';
  html += '</div>';

  // ── DASHBOARD TAB ──
  html += '<div class="sp-tab-content active" id="sp-dashboard">';

  // 1. HERO CARD — uses backend on_pace + projected_final_weight
  html += _pdHeroCard(startWeight, currentWeight, targetWeight, projections);

  // 2. WEIGHT CHART — plan line from linear_plan, actual trajectory from bw series
  html += _pdWeightChart(bw, projections, targetWeight, startDate);

  // 3. BODY COMPOSITION GRID (weight lives in the hero, not here)
  html += _pdBodyComp(measurements);

  // 4. TRAINING STREAK — trust training.current_streak / completed_days from API
  html += _pdStreakGrid(training, startDate);

  // 5. LIFT PROGRESSION
  html += _pdLiftProgression(lifts);

  // 6. Optional quiet quote pulled from psych intake — no cheerleading.
  if (psychQuote) {
    html += '<div class="pd-quote"><div class="pd-section-label">Why you started</div>' +
            '<div class="pd-quote-text">"' + psychQuote.replace(/</g, '&lt;') + '"</div></div>';
  }

  html += '</div>'; // end dashboard tab

  // ── LAB TAB (lazy-loaded on first click) ──
  html += '<div class="sp-tab-content" id="sp-lab">';
  html += '<div id="sp-lab-content"><div class="sp-ephemeral">Explore mode — nothing saves. Play with the numbers.</div><div style="text-align:center;padding:2rem;color:var(--muted)">Loading Lab data...</div></div>';
  html += '</div>';

  overlay.innerHTML = html;
}

/* ── HERO CARD ── */
function _pdHeroCard(startWeight, currentWeight, targetWeight, projections) {
  if (startWeight == null || currentWeight == null) {
    return '<div class="pd-hero"><div class="pd-hero-delta">--</div><div class="pd-hero-sub">No weigh-ins yet</div></div>';
  }
  projections = projections || {};
  var delta = currentWeight - startWeight;
  var deltaStr = (delta <= 0 ? '' : '+') + delta.toFixed(1) + ' lb';
  // Color by progress TOWARD target, not by sign: a bulk user gaining toward a
  // higher target is on-plan (green), as is a cut user losing toward a lower one.
  var _toward = (targetWeight != null && targetWeight !== startWeight)
      ? ((targetWeight - startWeight) >= 0 ? delta >= 0 : delta <= 0)
      : (delta <= 0);
  var deltaClass = _toward ? 'pd-green' : 'pd-red';

  var pct = 0;
  if (targetWeight && startWeight !== targetWeight) {
    pct = Math.max(0, Math.min(100, ((startWeight - currentWeight) / (startWeight - targetWeight)) * 100));
  }
  var barPct = Math.round(pct);

  // Trust backend extrapolation. Fall back to nothing rather than guessing.
  var projText = '';
  var projected = projections.projected_final_weight;
  if (projected != null && targetWeight != null) {
    var onPace = projections.on_pace;
    var paceClass = onPace === true ? 'pd-green' : onPace === false ? 'pd-red' : '';
    var label = onPace === true ? 'On pace' : onPace === false ? 'Off pace' : 'Projected';
    projText = '<span class="pd-hero-pace ' + paceClass + '">' + label + '</span> — tracking to ' +
               Math.round(projected) + ' lb by Week 12 (goal ' + Math.round(targetWeight) + ')';
  }

  var h = '<div class="pd-hero">';
  h += '<div class="pd-hero-delta ' + deltaClass + '">' + deltaStr + '</div>';
  h += '<div class="pd-hero-range">' + startWeight + ' &rarr; ' + currentWeight.toFixed(1) + ' lb</div>';
  h += '<div class="pd-hero-bar-wrap">' +
         '<div class="pd-hero-bar-track"><div class="pd-hero-bar-fill" style="width:' + barPct + '%"></div></div>' +
         '<div class="pd-hero-bar-pct">' + barPct + '%</div>' +
       '</div>';
  if (projText) h += '<div class="pd-hero-proj">' + projText + '</div>';
  h += '</div>';
  return h;
}

/* ── WEIGHT CHART (inline SVG) ── */
function _pdWeightChart(bw, projections, targetWeight, startDate) {
  if (!bw || bw.length < 2) {
    return '<div class="pd-section"><div class="pd-section-label">Weight</div><div class="pd-empty">Need 2+ weigh-ins for chart</div></div>';
  }
  projections = projections || {};
  var linearPlan = projections.linear_plan || [];

  var W = 340, H = 200, padL = 48, padR = 16, padT = 16, padB = 28;

  // Y axis spans from goal-2 to start+2 so both endpoints have breathing room.
  var startWt = bw[0].weight;
  var goalWt = targetWeight || startWt - 30;
  var yMin = Math.min(goalWt, startWt) - 2;
  var yMax = Math.max(goalWt, startWt) + 2;
  var yRange = yMax - yMin || 1;

  // X axis: start_date → start_date + 84 days (12 weeks) so the plan line has a fixed frame.
  var xStart = startDate ? new Date(startDate + 'T00:00:00') : new Date(bw[0].date + 'T00:00:00');
  var xEnd = new Date(xStart); xEnd.setDate(xEnd.getDate() + 84);
  var xRangeMs = xEnd - xStart || 1;

  function xPosDate(dateStr) {
    var d = new Date(dateStr + 'T00:00:00');
    var pct = (d - xStart) / xRangeMs;
    return padL + Math.max(0, Math.min(1, pct)) * (W - padL - padR);
  }
  function xPosWeek(wk) {
    var d = new Date(xStart); d.setDate(d.getDate() + (wk - 1) * 7);
    return padL + Math.max(0, Math.min(1, (d - xStart) / xRangeMs)) * (W - padL - padR);
  }
  function yPos(v) {
    return padT + (1 - (v - yMin) / yRange) * (H - padT - padB);
  }

  var svg = '<svg class="pd-weight-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">';

  // Y-axis: round ticks at 5- or 10-lb steps so gridlines land on recognizable numbers.
  var tickStep = yRange > 30 ? 10 : 5;
  var tickLo = Math.ceil(yMin / tickStep) * tickStep;
  var tickHi = Math.floor(yMax / tickStep) * tickStep;
  var yLabels = [];
  for (var tv = tickLo; tv <= tickHi; tv += tickStep) yLabels.push(tv);
  for (var yi = 0; yi < yLabels.length; yi++) {
    var ly = yPos(yLabels[yi]);
    svg += '<text x="' + (padL - 6) + '" y="' + (ly + 4) + '" text-anchor="end" fill="#c5d0c7" font-size="12" font-family="DM Mono,monospace">' + yLabels[yi] + '</text>';
    svg += '<line x1="' + padL + '" y1="' + ly + '" x2="' + (W - padR) + '" y2="' + ly + '" stroke="#2a2e2c" stroke-width="0.5"/>';
  }

  // Goal weight horizontal reference
  var goalY = yPos(goalWt);
  svg += '<line x1="' + padL + '" y1="' + goalY + '" x2="' + (W - padR) + '" y2="' + goalY + '" stroke="#4ade80" stroke-width="1" stroke-dasharray="6,4" opacity="0.4"/>';
  svg += '<text x="' + (W - padR - 2) + '" y="' + (goalY - 4) + '" text-anchor="end" fill="#4ade80" font-size="10" font-family="DM Mono,monospace" opacity="0.8">goal ' + Math.round(goalWt) + '</text>';

  // Plan line: prefer backend linear_plan. Fall back to a simple start→goal line.
  if (linearPlan.length >= 2) {
    var planPts = linearPlan.map(function(p) {
      return xPosWeek(p.week).toFixed(1) + ',' + yPos(p.planned_weight).toFixed(1);
    });
    svg += '<polyline points="' + planPts.join(' ') + '" fill="none" stroke="#9aaa9d" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.4"/>';
  } else if (goalWt && startWt && goalWt < startWt) {
    svg += '<line x1="' + padL + '" y1="' + yPos(startWt) + '" x2="' + (W - padR) + '" y2="' + yPos(goalWt) + '" stroke="#9aaa9d" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.35"/>';
  }

  // Trajectory: connect actual weigh-ins. Line + dots share the same y so nothing looks orphaned.
  var pts = [];
  for (var ai = 0; ai < bw.length; ai++) {
    pts.push(xPosDate(bw[ai].date).toFixed(1) + ',' + yPos(bw[ai].weight).toFixed(1));
  }
  svg += '<polyline points="' + pts.join(' ') + '" fill="none" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>';

  for (var di = 0; di < bw.length - 1; di++) {
    svg += '<circle cx="' + xPosDate(bw[di].date).toFixed(1) + '" cy="' + yPos(bw[di].weight).toFixed(1) + '" r="3" fill="#4ade80" opacity="0.7"/>';
  }

  // Current-weight annotation on the rightmost dot
  if (bw.length > 0) {
    var last = bw[bw.length - 1];
    var lx = xPosDate(last.date);
    var ly = yPos(last.weight);
    svg += '<circle cx="' + lx.toFixed(1) + '" cy="' + ly.toFixed(1) + '" r="5" fill="#4ade80"/>';
    // Prefer right-of-dot placement when there's horizontal room — avoids crashing into the y-axis labels on the left.
    var plotRight = W - padR;
    var annX, annAnchor;
    if (lx + 40 < plotRight) { annX = lx + 8; annAnchor = 'start'; }
    else                     { annX = lx - 8; annAnchor = 'end'; }
    var annY = ly - 10;
    if (annY < padT + 12) annY = ly + 18; // flip below the dot if it would collide with the top tick
    svg += '<text x="' + annX.toFixed(1) + '" y="' + annY.toFixed(1) + '" text-anchor="' + annAnchor + '" fill="#4ade80" font-size="12" font-family="DM Mono,monospace" font-weight="600">' + last.weight.toFixed(1) + '</text>';
  }

  var xWeeks = [1, 4, 8, 12];
  for (var xi = 0; xi < xWeeks.length; xi++) {
    var xlab = xPosWeek(xWeeks[xi]);
    svg += '<text x="' + xlab.toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle" fill="#c5d0c7" font-size="11" font-family="DM Mono,monospace">W' + xWeeks[xi] + '</text>';
  }

  svg += '</svg>';
  return '<div class="pd-section"><div class="pd-section-label">Weight</div>' + svg + '</div>';
}

/* ── BODY COMPOSITION GRID ── */
function _pdBodyComp(measurements) {
  if (!measurements || measurements.length === 0) {
    return '<div class="pd-section"><div class="pd-section-label">Body Composition</div><div class="pd-empty">No measurements recorded yet</div></div>';
  }

  var latest = measurements[measurements.length - 1];
  var baseline = measurements[0];

  var fields = [
    { key: 'waist', label: 'Waist', unit: 'in', lower: true },
    { key: 'chest', label: 'Chest', unit: 'in', lower: false },
    { key: 'hips', label: 'Hips', unit: 'in', lower: true },
    { key: 'neck', label: 'Neck', unit: 'in', lower: true },
    { key: 'bicep_avg', label: 'Biceps', unit: 'in', lower: false, computed: true },
    { key: 'thigh_avg', label: 'Thighs', unit: 'in', lower: false, computed: true }
  ];

  function getVal(entry, field) {
    if (field.computed) {
      if (field.key === 'bicep_avg') {
        var bl = entry.bicep_left, br = entry.bicep_right;
        if (bl != null && br != null) return (bl + br) / 2;
        return bl || br || null;
      }
      if (field.key === 'thigh_avg') {
        var tl = entry.thigh_left, tr = entry.thigh_right;
        if (tl != null && tr != null) return (tl + tr) / 2;
        return tl || tr || null;
      }
    }
    var v = entry[field.key];
    if (v == null && field.altKey) v = entry[field.altKey];
    return v;
  }

  var cards = '';
  for (var i = 0; i < fields.length; i++) {
    var f = fields[i];
    var cur = getVal(latest, f);
    if (cur == null) continue;

    // Sparkline values
    var sparkVals = [];
    for (var j = 0; j < measurements.length; j++) {
      var sv = getVal(measurements[j], f);
      if (sv != null) sparkVals.push(sv);
    }
    var sparkHtml = _buildSparkline(sparkVals, f.lower);

    // Delta vs baseline
    var deltaHtml = '';
    var baseVal = getVal(baseline, f);
    if (baseVal != null && measurements.length > 1) {
      var dd = cur - baseVal;
      if (dd !== 0) {
        var sign = dd > 0 ? '+' : '';
        var goodDir = f.lower ? (dd < 0) : (dd > 0);
        var dColor = goodDir ? '#4ade80' : '#ef4444';
        deltaHtml = '<span class="pd-comp-delta" style="color:' + dColor + '">' + sign + dd.toFixed(1) + '</span>';
      } else {
        deltaHtml = '<span class="pd-comp-delta" style="color:#9aaa9d">0</span>';
      }
    }

    cards += '<div class="pd-comp-card">';
    cards += '<div class="pd-comp-label">' + f.label + '</div>';
    cards += '<div class="pd-comp-val">' + cur.toFixed(1) + ' <span class="pd-comp-unit">' + f.unit + '</span></div>';
    cards += deltaHtml;
    cards += '<div class="pd-comp-spark">' + sparkHtml + '</div>';
    cards += '</div>';
  }

  return '<div class="pd-section"><div class="pd-section-label">Body Composition</div><div class="pd-comp-grid">' + cards + '</div></div>';
}

/* ── TRAINING STREAK (GitHub-style grid) ── */
function _pdStreakGrid(training, startDate) {
  if (!startDate) {
    return '<div class="pd-section"><div class="pd-section-label">Training Streak</div><div class="pd-empty">Set a start date first</div></div>';
  }
  training = training || {};

  // Authority: backend has already computed current_streak and best_streak from
  // DayCompletion. Frontend only renders — it does NOT recompute.
  var streak = training.current_streak != null ? training.current_streak : 0;
  var best = training.best_streak != null ? training.best_streak : 0;

  // Build exact (week, day_idx) completion set from backend.
  var doneCells = {};
  if (Array.isArray(training.completed_days)) {
    for (var ci = 0; ci < training.completed_days.length; ci++) {
      var cd = training.completed_days[ci];
      doneCells[cd.week + '_' + cd.day_idx] = true;
    }
  } else if (Array.isArray(training.weekly_adherence)) {
    // Fallback: only have counts, not positions — mark the first N days of each week.
    for (var ai = 0; ai < training.weekly_adherence.length; ai++) {
      var wa = training.weekly_adherence[ai];
      for (var di = 0; di < wa.days_done && di < 6; di++) {
        doneCells[wa.week + '_' + di] = true;
      }
    }
  }

  var startDt = new Date(startDate + 'T00:00:00');
  var today = new Date();
  today.setHours(0, 0, 0, 0);

  // Render a full 12-week frame (6 workout days + rest column).
  var dayLabels = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  var grid = '<div class="pd-streak-header">';
  for (var li = 0; li < 7; li++) {
    grid += '<span class="pd-streak-day-label">' + dayLabels[li] + '</span>';
  }
  grid += '</div>';

  grid += '<div class="pd-streak-grid">';
  for (var wi = 0; wi < 12; wi++) {
    for (var dj = 0; dj < 7; dj++) {
      var cellDate = new Date(startDt);
      cellDate.setDate(cellDate.getDate() + wi * 7 + dj);
      var cellClass = 'pd-streak-cell';
      if (dj === 6) {
        cellClass += ' pd-streak-rest';
      } else if (cellDate > today) {
        cellClass += ' pd-streak-future';
      } else if (doneCells[(wi + 1) + '_' + dj]) {
        cellClass += ' pd-streak-done';
      } else {
        cellClass += ' pd-streak-missed';
      }
      grid += '<div class="' + cellClass + '"></div>';
    }
  }
  grid += '</div>';

  return '<div class="pd-section">' +
    '<div class="pd-section-label">Training Streak</div>' +
    '<div class="pd-streak-count">' +
      '<span class="pd-streak-num">' + streak + '</span>' +
      '<span class="pd-streak-unit">day streak</span>' +
      '<span class="pd-streak-best">best ' + best + '</span>' +
    '</div>' +
    grid +
    '</div>';
}

/* ── LIFT PROGRESSION (compact rows with inline sparkline + horizontal bar) ── */
function _pdLiftProgression(lifts) {
  if (!lifts || Object.keys(lifts).length === 0) {
    return '<div class="pd-section"><div class="pd-section-label">Lift Progression</div><div class="pd-empty">No lift data yet</div></div>';
  }

  var liftEntries = [];
  for (var name in lifts) {
    var hist = lifts[name];
    if (!hist) continue;
    var entries = Array.isArray(hist) ? hist : (hist.history || []);
    if (entries.length === 0) continue;
    var weekMap = {};
    for (var ei = 0; ei < entries.length; ei++) {
      var e = entries[ei];
      var w = e.week || 1;
      var e1rm;
      if (e.estimated1RM) {
        // Baseline entries have a properly computed e1RM — use it directly
        e1rm = Math.round(e.estimated1RM);
      } else {
        var wt = e.weight || 0;
        var reps = 1;
        if (e.reps_completed) reps = parseInt(e.reps_completed) || 1;
        else if (e.reps) {
          var rm = String(e.reps).match(/(\d+)/);
          reps = rm ? parseInt(rm[1]) : 1;
        }
        e1rm = Math.round(wt * (1 + Math.min(reps, 15) / 30));
      }
      if (!weekMap[w] || e1rm > weekMap[w]) weekMap[w] = e1rm;
    }
    var weeks = Object.keys(weekMap).map(Number).sort(function(a, b) { return a - b; });
    if (weeks.length === 0) continue;
    var weekVals = weeks.map(function(wk) { return { week: wk, e1rm: weekMap[wk] }; });
    var maxE1rm = Math.max.apply(null, weekVals.map(function(v) { return v.e1rm; }));
    liftEntries.push({ name: name, data: weekVals, maxE1rm: maxE1rm });
  }

  liftEntries.sort(function(a, b) { return b.maxE1rm - a.maxE1rm; });
  liftEntries = liftEntries.slice(0, 8);

  if (liftEntries.length === 0) {
    return '<div class="pd-section"><div class="pd-section-label">Lift Progression</div><div class="pd-empty">No lift data yet</div></div>';
  }

  // Find global max for bar scaling
  var globalMax = Math.max.apply(null, liftEntries.map(function(l) { return l.maxE1rm; }));

  var html = '';
  for (var li = 0; li < liftEntries.length; li++) {
    var lift = liftEntries[li];
    var latestVal = lift.data[lift.data.length - 1].e1rm;
    var firstVal = lift.data[0].e1rm;
    // PR only when the latest STRICTLY beats every prior week — not a tie/plateau
    // (maxE1rm includes the latest point, so >= flagged ties as PRs).
    var _priorVals = lift.data.slice(0, -1).map(function(v){ return v.e1rm; });
    var _priorMax = _priorVals.length ? Math.max.apply(null, _priorVals) : -Infinity;
    var isPR = latestVal > _priorMax;
    var delta = latestVal - firstVal;
    var deltaStr = delta > 0 ? '+' + delta : delta === 0 ? '' : '' + delta;
    var deltaColor = delta > 0 ? '#4ade80' : delta < 0 ? '#ef4444' : 'var(--muted)';
    var barPct = globalMax > 0 ? Math.round(latestVal / globalMax * 100) : 0;
    var shortName = lift.name.replace('Barbell ', '').replace('Conventional ', '').replace('Cable ', '');

    // Build sparkline from weekly e1RM values
    var sparkVals = lift.data.map(function(d) { return d.e1rm; });
    var spark = _buildSparkline(sparkVals, false);

    html += '<div class="pd-lift-row">' +
      '<div class="pd-lift-top">' +
        '<span class="pd-lift-name">' + shortName + (isPR ? ' <span class="pd-pr-badge">PR</span>' : '') + '</span>' +
        '<span class="pd-lift-vals">' +
          '<span class="pd-lift-e1rm">' + latestVal + ' <span class="pd-lift-unit">lb</span></span>' +
          (deltaStr ? '<span class="pd-lift-delta" style="color:' + deltaColor + '">' + deltaStr + '</span>' : '') +
        '</span>' +
      '</div>' +
      '<div class="pd-lift-bottom">' +
        '<div class="pd-lift-bar-bg"><div class="pd-lift-bar-fill" style="width:' + barPct + '%"></div></div>' +
        '<div class="pd-lift-spark">' + spark + '</div>' +
      '</div>' +
    '</div>';
  }

  return '<div class="pd-section"><div class="pd-section-label">Lift Progression</div>' + html + '</div>';
}

// ─── STATS PANEL: TAB SWITCHING + LAB ──────────────────────────────────────

var _spLabLoaded = false;
var _spLabData = {};

function _spSwitchTab(tab, btn) {
  document.querySelectorAll('.sp-tab').forEach(function(t) { t.classList.remove('active'); });
  document.querySelectorAll('.sp-tab-content').forEach(function(c) { c.classList.remove('active'); });
  btn.classList.add('active');
  var target = document.getElementById('sp-' + tab);
  if (target) target.classList.add('active');

  // Lazy-load Lab data on first click
  if (tab === 'lab' && !_spLabLoaded) {
    _spLabLoaded = true;
    Promise.all([
      fetch('/api/stats/projection-inputs').then(function(r) { return r.ok ? r.json() : {}; }),
      fetch('/api/stats/body-comp').then(function(r) { return r.ok ? r.json() : {}; }),
    ]).then(function(results) {
      var projData = results[0];
      var bcData = results[1];
      // Merge body-comp measurements into projection data
      _spLabData = projData;
      _spLabData.measurements = bcData.measurements || [];
      if (!_spLabData.height_in && bcData.height_in) _spLabData.height_in = bcData.height_in;
      if (!_spLabData.sex && bcData.sex) _spLabData.sex = bcData.sex;
      var mount = document.getElementById('sp-lab-content');
      if (mount) mount.innerHTML = _spRenderLab(_spLabData);
    }).catch(function(e) {
      var mount = document.getElementById('sp-lab-content');
      if (mount) mount.innerHTML = '<div style="padding:2rem;color:#ef4444">Failed to load Lab data</div>';
    });
  }
}

function _spRenderLab(data) {
  var html = '<div class="sp-ephemeral">Explore mode — nothing saves. Play with the numbers.</div>';

  // ── WEIGHT PROJECTION SLIDER ──
  html += _spWeightProjection(data);

  // ── BODY COMPOSITION CALCULATOR ──
  html += _spBodyCompCalc(data);

  // ── SCENARIO PLANNER ──
  html += _spScenarioPlanner(data);

  return html;
}

/* ── WEIGHT PROJECTION SLIDER ── */
function _spWeightProjection(data) {
  var cal = data.daily_calories || 1800;
  var tdee = data.tdee || 2500;
  var startW = data.start_weight || 220;
  var targetW = data.target_weight || 195;
  var curW = data.current_weight || startW;
  var heightIn = data.height_in || 70;
  var age = data.age || 30;
  var sex = data.sex || 'male';
  var curWeek = data.current_week || 1;

  var h = '<div class="pd-section"><div class="pd-section-label">Weight Projection</div>';

  // Calorie slider
  h += '<div class="sp-slider-row">';
  h += '<span class="sp-slider-label">Calories</span>';
  h += '<input type="range" class="sp-slider" id="sp-cal-slider" min="1000" max="3500" step="25" value="' + cal + '" oninput="_spUpdateProjection()">';
  h += '<span class="sp-slider-val" id="sp-cal-val">' + cal + '</span>';
  h += '</div>';

  // Running slider — miles per week. Running burn ~100 cal/mile so this
  // directly drives the aerobic half of TDEE.
  var defRun = data.weekly_miles || 20;
  h += '<div class="sp-slider-row">';
  h += '<span class="sp-slider-label">Running</span>';
  h += '<input type="range" class="sp-slider" id="sp-run-slider" min="0" max="80" step="5" value="' + defRun + '" oninput="_spUpdateProjection()">';
  h += '<span class="sp-slider-val" id="sp-run-val">' + defRun + ' mi/wk</span>';
  h += '</div>';

  // Lifting slider — sessions per week. Lifting burns less (~350 cal/session)
  // but protects lean mass, which shifts the body-comp projection.
  var defLift = data.lifts_per_week || 3;
  h += '<div class="sp-slider-row">';
  h += '<span class="sp-slider-label">Lifting</span>';
  h += '<input type="range" class="sp-slider" id="sp-lift-slider" min="0" max="6" step="1" value="' + defLift + '" oninput="_spUpdateProjection()">';
  h += '<span class="sp-slider-val" id="sp-lift-val">' + defLift + ' sess/wk</span>';
  h += '</div>';

  // Projection chart placeholder
  h += '<div id="sp-proj-chart" style="margin:16px 0">';
  // Render initial chart
  if (typeof _projectWeightCurve === 'function') {
    var proj = _projectWeightCurve(curW, targetW, tdee, cal, 12 - curWeek + 1, heightIn, age, sex, curWeek - 1);
    h += _spRenderProjChart(data.weight_series || [], proj, targetW, startW, data.start_date);
  } else {
    h += '<div style="color:var(--muted);text-align:center;padding:1rem">Projection engine loading...</div>';
  }
  h += '</div>';

  // Dynamic insight text
  h += '<div class="sp-insight" id="sp-proj-insight">';
  var deficit = tdee - cal;
  var weeklyLoss = (deficit * 7 / 3500).toFixed(1);
  h += 'At ' + cal + ' cal/day with TDEE ' + tdee + ', your deficit is ' + deficit + ' cal/day (' + weeklyLoss + ' lb/week).';
  h += '</div>';

  h += '</div>';
  return h;
}

function _spUpdateProjection() {
  var calSlider = document.getElementById('sp-cal-slider');
  var runSlider = document.getElementById('sp-run-slider');
  var liftSlider = document.getElementById('sp-lift-slider');
  if (!calSlider || !runSlider || !liftSlider) return;

  var cal = parseInt(calSlider.value);
  var miles = parseInt(runSlider.value);
  var lifts = parseInt(liftSlider.value);

  document.getElementById('sp-cal-val').textContent = cal;
  document.getElementById('sp-run-val').textContent = miles + ' mi/wk';
  document.getElementById('sp-lift-val').textContent = lifts + ' sess/wk';

  var d = _spLabData;
  var heightIn = d.height_in || 70;
  var age = d.age || 30;
  var sex = d.sex || 'male';
  var curW = d.current_weight || 220;
  var targetW = d.target_weight || 195;
  var curWeek = d.current_week || 1;
  var weeksLeft = 12 - curWeek + 1;

  // TDEE = sedentary-ish BMR baseline (1.3) + calories burned from running +
  // from lifting. Treats the two modalities separately because they have
  // very different effects on both burn and body-comp outcomes.
  var bmr = typeof _computeTdee === 'function' ? _computeTdee(curW, heightIn, age, sex, 1.0).bmr : 1700;
  var baseTdee = Math.round(bmr * 1.3);
  var runBurn = Math.round(miles * 100 / 7);     // ~100 cal/mile
  var liftBurn = Math.round(lifts * 350 / 7);    // ~350 cal per 1h session
  var tdee = baseTdee + runBurn + liftBurn;

  // Recompute weight projection with new TDEE.
  var proj = null;
  if (typeof _projectWeightCurve === 'function') {
    proj = _projectWeightCurve(curW, targetW, tdee, cal, weeksLeft, heightIn, age, sex, curWeek - 1);
    var chartEl = document.getElementById('sp-proj-chart');
    if (chartEl) chartEl.innerHTML = _spRenderProjChart(d.weight_series || [], proj, targetW, d.start_weight || curW, d.start_date);
  }

  // Project body-comp forward: push the projected end weight into the BC
  // calculator, and estimate tape deltas. More lifting → more of the loss
  // comes from fat vs lean, so tape shrinks more per pound lost.
  if (proj && proj.length > 0) {
    var endWt = proj[proj.length - 1].projected;
    var totalLoss = Math.max(0, curW - endWt);
    var fatRatio = lifts >= 3 ? 0.85 : (lifts >= 1 ? 0.75 : 0.65);
    var fatLost = totalLoss * fatRatio;

    // Rough inches-per-pound-of-fat ratios. Males carry more abdominal fat,
    // females more gluteofemoral — flipped ratios for waist vs hips.
    var waistPerLb = sex === 'male' ? 0.4 : 0.3;
    var neckPerLb = 0.1;
    var hipsPerLb = sex === 'male' ? 0.3 : 0.4;

    var bcWaist = document.getElementById('sp-bc-waist');
    var bcNeck = document.getElementById('sp-bc-neck');
    var bcHips = document.getElementById('sp-bc-hips');
    var bcWeight = document.getElementById('sp-bc-weight');

    var measurements = d.measurements || [];
    var latest = measurements.length > 0 ? measurements[measurements.length - 1] : {};
    var curWaist = parseFloat(latest.waist) || parseFloat(bcWaist && bcWaist.getAttribute('data-base')) || 38;
    var curNeck = parseFloat(latest.neck) || parseFloat(bcNeck && bcNeck.getAttribute('data-base')) || 16;
    var curHips = parseFloat(latest.hips) || parseFloat(bcHips && bcHips.getAttribute('data-base')) || 40;

    if (bcWeight) bcWeight.value = endWt.toFixed(1);
    if (bcWaist) bcWaist.value = Math.max(24, curWaist - fatLost * waistPerLb).toFixed(1);
    if (bcNeck) bcNeck.value = Math.max(12, curNeck - fatLost * neckPerLb).toFixed(1);
    if (bcHips) bcHips.value = Math.max(26, curHips - fatLost * hipsPerLb).toFixed(1);
    if (typeof _spUpdateBodyComp === 'function') _spUpdateBodyComp();
  }

  // Insight line with the TDEE breakdown so the user can see where the burn comes from.
  var deficit = tdee - cal;
  var weeklyLoss = (deficit * 7 / 3500).toFixed(1);
  var insightEl = document.getElementById('sp-proj-insight');
  if (insightEl) {
    var endWeight = proj ? proj[proj.length - 1].projected.toFixed(1) : '?';
    var header = 'TDEE ' + tdee + ' = base ' + baseTdee + ' + run ' + runBurn + ' + lift ' + liftBurn + '. ';
    if (deficit > 0) {
      insightEl.innerHTML = header + 'Deficit ' + deficit + ' cal/day (' + weeklyLoss + ' lb/week). Projected Week 12: ' + endWeight + ' lb.';
    } else {
      insightEl.innerHTML = header + 'Surplus ' + Math.abs(deficit) + ' cal/day. Projected Week 12: ' + endWeight + ' lb.';
    }
  }
}

function _spRenderProjChart(weightSeries, projection, targetWeight, startWeight, startDate) {
  // Visually matches the Progress Dashboard weight chart: proper 5- or 10-lb
  // gridlines, multi-tick y-axis, W1/W4/W8/W12 x-axis. Adds an interactive
  // blue projection line on top (the dashboard chart has only actual + plan).
  var W = 340, H = 220, padL = 48, padR = 16, padT = 16, padB = 28;
  var maxW = startWeight + 2;
  var minW = targetWeight ? Math.min(targetWeight, startWeight) - 2 : startWeight - 20;
  if (minW >= maxW) minW = maxW - 20;
  var yRange = maxW - minW || 1;

  var yScale = function(w) { return padT + (maxW - w) / yRange * (H - padT - padB); };
  var xScale = function(dayIdx) { return padL + Math.max(0, Math.min(1, dayIdx / 84)) * (W - padL - padR); };
  var xPosWeek = function(wk) { return xScale((wk - 1) * 7); };

  var svg = '<svg class="pd-weight-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">';

  // Y-axis: round tick steps matching dashboard chart.
  var tickStep = yRange > 30 ? 10 : 5;
  var tickLo = Math.ceil(minW / tickStep) * tickStep;
  var tickHi = Math.floor(maxW / tickStep) * tickStep;
  for (var tv = tickLo; tv <= tickHi; tv += tickStep) {
    var ly = yScale(tv);
    svg += '<text x="' + (padL - 6) + '" y="' + (ly + 4) + '" text-anchor="end" fill="#c5d0c7" font-size="12" font-family="DM Mono,monospace">' + tv + '</text>';
    svg += '<line x1="' + padL + '" y1="' + ly + '" x2="' + (W - padR) + '" y2="' + ly + '" stroke="#2a2e2c" stroke-width="0.5"/>';
  }

  // Goal reference line
  if (targetWeight) {
    var gy = yScale(targetWeight);
    svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" stroke="#4ade80" stroke-width="1" stroke-dasharray="6,4" opacity="0.4"/>';
    svg += '<text x="' + (W - padR - 2) + '" y="' + (gy - 4) + '" text-anchor="end" fill="#4ade80" font-size="10" font-family="DM Mono,monospace" opacity="0.8">goal ' + Math.round(targetWeight) + '</text>';
  }

  // Linear plan from start to goal (gray dashed) — same reference line the
  // dashboard chart shows so the two views tell the same story.
  if (targetWeight && startWeight && targetWeight < startWeight) {
    svg += '<line x1="' + xPosWeek(1) + '" y1="' + yScale(startWeight) + '" x2="' + xPosWeek(12) + '" y2="' + yScale(targetWeight) + '" stroke="#9aaa9d" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.4"/>';
  }

  // Actual data (green)
  var anchorDayOff = null;
  var anchorWt = null;
  if (weightSeries && weightSeries.length > 1) {
    // Anchor on PROGRAM START (not the first weigh-in) so weigh-ins line up
    // with the W1/W4/W8/W12 x-axis and the projection's absolute weeks.
    var firstDate = startDate ? new Date(startDate + 'T00:00:00')
                              : new Date(weightSeries[0].date + 'T00:00:00');
    var pts = [];
    for (var i = 0; i < weightSeries.length; i++) {
      var dt = new Date(weightSeries[i].date + 'T00:00:00');
      var dayOff = Math.round((dt - firstDate) / (1000 * 60 * 60 * 24));
      var wt = weightSeries[i].rolling_avg || weightSeries[i].weight;
      if (wt && dayOff >= 0) pts.push(xScale(dayOff).toFixed(1) + ',' + yScale(wt).toFixed(1));
    }
    if (pts.length > 0) {
      svg += '<polyline points="' + pts.join(' ') + '" fill="none" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>';
      // Intermediate dots for each weigh-in
      for (var di = 0; di < weightSeries.length - 1; di++) {
        var d2 = new Date(weightSeries[di].date + 'T00:00:00');
        var doff = Math.round((d2 - firstDate) / (1000 * 60 * 60 * 24));
        var wt2 = weightSeries[di].rolling_avg || weightSeries[di].weight;
        svg += '<circle cx="' + xScale(doff).toFixed(1) + '" cy="' + yScale(wt2).toFixed(1) + '" r="3" fill="#4ade80" opacity="0.7"/>';
      }
      var last = weightSeries[weightSeries.length - 1];
      var lastDt = new Date(last.date + 'T00:00:00');
      anchorDayOff = Math.round((lastDt - firstDate) / (1000 * 60 * 60 * 24));
      anchorWt = last.rolling_avg || last.weight;
      var lx = xScale(anchorDayOff), ly2 = yScale(anchorWt);
      svg += '<circle cx="' + lx.toFixed(1) + '" cy="' + ly2.toFixed(1) + '" r="5" fill="#4ade80"/>';
      var annX, annAnchor;
      if (lx + 40 < W - padR) { annX = lx + 8; annAnchor = 'start'; }
      else                    { annX = lx - 8; annAnchor = 'end'; }
      svg += '<text x="' + annX.toFixed(1) + '" y="' + (ly2 - 10).toFixed(1) + '" text-anchor="' + annAnchor + '" fill="#4ade80" font-size="12" font-family="DM Mono,monospace" font-weight="600">' + anchorWt.toFixed(1) + '</text>';
    }
  }

  // Projection line (blue dashed) — starts at the end of the green line.
  if (projection && projection.length > 0) {
    var projPts = [];
    if (anchorDayOff != null && anchorWt != null) {
      projPts.push(xScale(anchorDayOff).toFixed(1) + ',' + yScale(anchorWt).toFixed(1));
    } else {
      anchorDayOff = 0;
    }
    for (var j = 0; j < projection.length; j++) {
      var pw = projection[j];
      // Position by ABSOLUTE program week (days from program start), aligned to
      // the same x-axis as the weigh-ins and the W1..W12 ticks.
      var dayOff2 = pw.week ? (pw.week - 1) * 7 : (anchorDayOff + (j + 1) * 7);
      if (dayOff2 > 84) dayOff2 = 84;
      projPts.push(xScale(dayOff2).toFixed(1) + ',' + yScale(pw.projected).toFixed(1));
    }
    svg += '<polyline points="' + projPts.join(' ') + '" fill="none" stroke="#60a5fa" stroke-width="2" stroke-dasharray="6,3" stroke-linecap="round"/>';
    var ep = projPts[projPts.length - 1].split(',');
    svg += '<circle cx="' + ep[0] + '" cy="' + ep[1] + '" r="4" fill="#60a5fa"/>';
  }

  // X-axis labels (dashboard-style: W1, W4, W8, W12)
  var xWeeks = [1, 4, 8, 12];
  for (var xi = 0; xi < xWeeks.length; xi++) {
    var xlab = xPosWeek(xWeeks[xi]);
    svg += '<text x="' + xlab.toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle" fill="#c5d0c7" font-size="11" font-family="DM Mono,monospace">W' + xWeeks[xi] + '</text>';
  }

  svg += '</svg>';
  return svg;
}

/* ── BODY COMPOSITION CALCULATOR ── */
function _spBodyCompCalc(data) {
  var curW = data.current_weight || 200;
  var heightIn = data.height_in || 70;
  var sex = data.sex || 'male';

  // Get latest measurements if available
  var measurements = data.measurements || [];
  var latest = measurements.length > 0 ? measurements[measurements.length - 1] : {};
  var baseline = measurements.length > 0 ? measurements[0] : {};
  var waist = latest.waist || 38;
  var neck = latest.neck || 16;
  var hips = latest.hips || 40;

  var h = '<div class="pd-section"><div class="pd-section-label">Body Composition</div>';

  // Measurement inputs
  h += '<div class="sp-input-grid">';
  h += '<div class="sp-input-group"><label>Waist (in)</label><input type="number" step="0.5" id="sp-bc-waist" value="' + waist + '" oninput="_spUpdateBodyComp()"></div>';
  h += '<div class="sp-input-group"><label>Neck (in)</label><input type="number" step="0.5" id="sp-bc-neck" value="' + neck + '" oninput="_spUpdateBodyComp()"></div>';
  h += '<div class="sp-input-group"><label>Hips (in)</label><input type="number" step="0.5" id="sp-bc-hips" value="' + hips + '" oninput="_spUpdateBodyComp()"></div>';
  h += '<div class="sp-input-group"><label>Weight (lb)</label><input type="number" step="0.1" id="sp-bc-weight" value="' + curW + '" oninput="_spUpdateBodyComp()"></div>';
  h += '</div>';

  // Results
  h += '<div id="sp-bc-results">';
  h += _spBodyCompResults(waist, neck, heightIn, sex, hips, curW, baseline);
  h += '</div>';

  h += '</div>';
  return h;
}

function _spUpdateBodyComp() {
  var waist = parseFloat(document.getElementById('sp-bc-waist').value) || 0;
  var neck = parseFloat(document.getElementById('sp-bc-neck').value) || 0;
  var hips = parseFloat(document.getElementById('sp-bc-hips').value) || 0;
  var weight = parseFloat(document.getElementById('sp-bc-weight').value) || 0;
  var d = _spLabData;
  var heightIn = d.height_in || 70;
  var sex = d.sex || 'male';
  var measurements = d.measurements || [];
  var baseline = measurements.length > 0 ? measurements[0] : {};

  var el = document.getElementById('sp-bc-results');
  if (el) el.innerHTML = _spBodyCompResults(waist, neck, heightIn, sex, hips, weight, baseline);
}

function _spBodyCompResults(waist, neck, heightIn, sex, hips, weight, baseline) {
  var bf = typeof _estimateBodyFatNavy === 'function' ? _estimateBodyFatNavy(waist, neck, heightIn, sex, hips) : null;
  var h = '';

  if (bf != null && weight > 0) {
    var fatMass = Math.round(weight * bf / 100 * 10) / 10;
    var leanMass = Math.round((weight - fatMass) * 10) / 10;
    var leanPct = Math.round(leanMass / weight * 100);
    var fatPct = Math.round(fatMass / weight * 100);

    h += '<div class="sp-result-row"><span class="sp-result-label">Body Fat</span><span class="sp-result-val">' + bf.toFixed(1) + '%</span></div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">Lean Mass</span><span class="sp-result-val">' + leanMass + ' lb</span></div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">Fat Mass</span><span class="sp-result-val">' + fatMass + ' lb</span></div>';

    // Stacked bar
    h += '<div class="sp-bar-container">';
    h += '<div class="sp-bar-segment sp-bar-lean" style="width:' + leanPct + '%"></div>';
    h += '<div class="sp-bar-segment sp-bar-fat" style="width:' + fatPct + '%"></div>';
    h += '</div>';
    h += '<div style="display:flex;justify-content:space-between;font-family:\'DM Mono\',monospace;font-size:11px;color:var(--muted)">';
    h += '<span style="color:var(--lift)">Lean ' + leanPct + '%</span>';
    h += '<span style="color:#ef4444">Fat ' + fatPct + '%</span>';
    h += '</div>';

    // Baseline comparison
    if (baseline && baseline.waist && baseline.neck) {
      var baseBf = typeof _estimateBodyFatNavy === 'function' ? _estimateBodyFatNavy(baseline.waist, baseline.neck, heightIn, sex, baseline.hips || hips) : null;
      if (baseBf != null) {
        var baseWeight = baseline.weight_lbs || baseline.weight || weight;
        var baseFat = Math.round(baseWeight * baseBf / 100 * 10) / 10;
        var baseLean = Math.round((baseWeight - baseFat) * 10) / 10;
        var bfDelta = bf - baseBf;
        var leanDelta = leanMass - baseLean;
        var fatDelta = fatMass - baseFat;

        h += '<div style="margin-top:12px;padding-top:8px;border-top:1px solid var(--border)">';
        h += '<div style="font-family:\'DM Mono\',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:6px">vs Baseline</div>';
        h += '<div class="sp-result-row"><span class="sp-result-label">BF%</span><span class="sp-result-val">' + baseBf.toFixed(1) + '% &rarr; ' + bf.toFixed(1) + '% <span class="sp-result-delta ' + (bfDelta < 0 ? 'positive' : 'negative') + '">' + (bfDelta > 0 ? '+' : '') + bfDelta.toFixed(1) + '</span></span></div>';
        h += '<div class="sp-result-row"><span class="sp-result-label">Lean</span><span class="sp-result-val">' + baseLean + ' &rarr; ' + leanMass + ' <span class="sp-result-delta ' + (leanDelta > 0 ? 'positive' : 'negative') + '">' + (leanDelta > 0 ? '+' : '') + leanDelta.toFixed(1) + '</span></span></div>';
        h += '<div class="sp-result-row"><span class="sp-result-label">Fat</span><span class="sp-result-val">' + baseFat + ' &rarr; ' + fatMass + ' <span class="sp-result-delta ' + (fatDelta < 0 ? 'positive' : 'negative') + '">' + (fatDelta > 0 ? '+' : '') + fatDelta.toFixed(1) + '</span></span></div>';
        h += '</div>';
      }
    }
  } else {
    h += '<div style="color:var(--muted);font-size:13px;padding:8px 0">Enter measurements to calculate body composition.</div>';
  }
  return h;
}

/* ── SCENARIO PLANNER ── */
function _spScenarioPlanner(data) {
  var goalType = data.goal_type || 'cut';
  var fasting = data.fasting_protocol || '16_8';
  var cal = data.daily_calories || 1800;
  var tdee = data.tdee || 2500;
  var curW = data.current_weight || 220;
  var targetW = data.target_weight || 195;
  var heightIn = data.height_in || 70;
  var age = data.age || 30;
  var sex = data.sex || 'male';

  var h = '<div class="pd-section"><div class="pd-section-label">Scenario Planner</div>';

  // Goal type toggles
  h += '<div style="font-family:\'DM Mono\',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:4px">Goal Type</div>';
  h += '<div class="sp-toggle-row">';
  ['cut', 'recomp', 'bulk'].forEach(function(g) {
    h += '<button class="sp-toggle' + (g === goalType ? ' active' : '') + '" onclick="_spSetScenario(\'goal\',\'' + g + '\')">' + g.charAt(0).toUpperCase() + g.slice(1) + '</button>';
  });
  h += '</div>';

  // Fasting toggles
  h += '<div style="font-family:\'DM Mono\',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-top:10px;margin-bottom:4px">Fasting Protocol</div>';
  h += '<div class="sp-toggle-row">';
  ['none', '16_8', '18_6', '20_4', 'omad'].forEach(function(f) {
    var label = f === 'none' ? 'None' : f === 'omad' ? 'OMAD' : f.replace('_', ':');
    h += '<button class="sp-toggle' + (f === fasting ? ' active' : '') + '" onclick="_spSetScenario(\'fasting\',\'' + f + '\')">' + label + '</button>';
  });
  h += '</div>';

  // Target weight slider
  h += '<div class="sp-slider-row" style="margin-top:12px">';
  h += '<span class="sp-slider-label">Target</span>';
  h += '<input type="range" class="sp-slider" id="sp-target-slider" min="' + Math.round(curW * 0.7) + '" max="' + Math.round(curW * 1.15) + '" step="1" value="' + Math.round(targetW) + '" oninput="_spUpdateScenario()">';
  h += '<span class="sp-slider-val" id="sp-target-val">' + Math.round(targetW) + ' lb</span>';
  h += '</div>';

  // Scenario results
  h += '<div id="sp-scenario-results">';
  h += _spScenarioResults(goalType, fasting, curW, targetW, tdee, heightIn, age, sex, cal);
  h += '</div>';

  h += '</div>';
  return h;
}

var _spScenarioState = { goal: null, fasting: null };

function _spSetScenario(key, val) {
  _spScenarioState[key] = val;
  // Update toggle visuals
  var row = event.target.parentElement;
  row.querySelectorAll('.sp-toggle').forEach(function(b) { b.classList.remove('active'); });
  event.target.classList.add('active');
  _spUpdateScenario();
}

function _spUpdateScenario() {
  var d = _spLabData;
  var goalType = _spScenarioState.goal || d.goal_type || 'cut';
  var fasting = _spScenarioState.fasting || d.fasting_protocol || '16_8';
  var curW = d.current_weight || 220;
  var tdee = d.tdee || 2500;
  var heightIn = d.height_in || 70;
  var age = d.age || 30;
  var sex = d.sex || 'male';
  var origCal = d.daily_calories || 1800;

  var targetSlider = document.getElementById('sp-target-slider');
  var targetW = targetSlider ? parseInt(targetSlider.value) : (d.target_weight || 195);
  var targetValEl = document.getElementById('sp-target-val');
  if (targetValEl) targetValEl.textContent = targetW + ' lb';

  var el = document.getElementById('sp-scenario-results');
  if (el) el.innerHTML = _spScenarioResults(goalType, fasting, curW, targetW, tdee, heightIn, age, sex, origCal);
}

function _spScenarioResults(goalType, fasting, curW, targetW, tdee, heightIn, age, sex, origCal) {
  var h = '';

  // Compute new targets
  var curWeek = _spLabData.current_week || 1;
  var weeksLeft = 12 - curWeek + 1;

  if (typeof _computeTargets === 'function') {
    var targets = _computeTargets(tdee, goalType, curW, targetW, weeksLeft);
    var proj = typeof _projectWeightCurve === 'function' ? _projectWeightCurve(curW, targetW, tdee, targets.calories, weeksLeft, heightIn, age, sex, curWeek - 1) : [];
    var endWeight = proj.length > 0 ? proj[proj.length - 1].projected.toFixed(1) : '?';
    var deficit = tdee - targets.calories;

    // Daily targets
    h += '<div style="margin:12px 0;padding:12px;background:var(--surface);border-radius:8px">';
    h += '<div style="font-family:\'DM Mono\',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:8px">Scenario Daily Targets</div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">Calories</span><span class="sp-result-val">' + targets.calories + '</span></div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">Protein</span><span class="sp-result-val">' + targets.protein + 'g</span></div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">Carbs</span><span class="sp-result-val">' + targets.carbs + 'g</span></div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">Fat</span><span class="sp-result-val">' + targets.fat + 'g</span></div>';
    h += '<div class="sp-result-row"><span class="sp-result-label">' + (deficit > 0 ? 'Deficit' : 'Surplus') + '</span><span class="sp-result-val">' + Math.abs(deficit) + ' cal/day</span></div>';
    h += '</div>';

    // Projected outcome
    h += '<div class="sp-result-row" style="margin-top:8px"><span class="sp-result-label">Week 12 Weight</span><span class="sp-result-val" style="font-size:22px;color:var(--lift)">' + endWeight + ' lb</span></div>';

    // Compare vs current plan
    h += '<div class="sp-compare" style="margin-top:12px">';
    h += '<div class="sp-compare-card"><div class="sp-compare-title">Current Plan</div>';
    h += '<div style="font-family:\'DM Mono\',monospace;font-size:14px;color:var(--text)">' + origCal + ' cal/day</div>';
    var origProj = typeof _projectWeightCurve === 'function' ? _projectWeightCurve(curW, _spLabData.target_weight || 195, tdee, origCal, weeksLeft, heightIn, age, sex, curWeek - 1) : [];
    var origEnd = origProj.length > 0 ? origProj[origProj.length - 1].projected.toFixed(1) : '?';
    h += '<div style="font-family:\'DM Mono\',monospace;font-size:12px;color:var(--muted)">W12: ' + origEnd + ' lb</div>';
    h += '</div>';

    h += '<div class="sp-compare-card scenario"><div class="sp-compare-title">This Scenario</div>';
    h += '<div style="font-family:\'DM Mono\',monospace;font-size:14px;color:var(--lift)">' + targets.calories + ' cal/day</div>';
    h += '<div style="font-family:\'DM Mono\',monospace;font-size:12px;color:var(--lift)">W12: ' + endWeight + ' lb</div>';
    var diff = origEnd !== '?' && endWeight !== '?' ? (parseFloat(endWeight) - parseFloat(origEnd)).toFixed(1) : null;
    if (diff != null) {
      h += '<div style="font-family:\'DM Mono\',monospace;font-size:11px;color:' + (parseFloat(diff) < 0 ? 'var(--lift)' : '#ef4444') + ';margin-top:4px">' + (parseFloat(diff) > 0 ? '+' : '') + diff + ' lb</div>';
    }
    h += '</div>';
    h += '</div>';
  } else {
    h += '<div style="color:var(--muted);padding:1rem">Computation engine loading...</div>';
  }

  return h;
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
    const workoutName = dayData ? (dayData.liftName || 'not planned yet') : 'Rest';
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
    const workoutName = (dayData && dayData.liftName) || 'workout';
    const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const tomorrowMon = (todayMon + 1) % 7;
    const tomorrowData = weekData && weekData.days ? weekData.days[tomorrowMon] : null;
    const tomorrowName = tomorrowData ? (tomorrowData.liftName || 'not planned yet') : 'Rest';

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
    const input = document.getElementById('coach-inline-input');
    if (input) {
      input.value = msg;
      sendInlineCoachMsg();
    }
  }, 500);
}

function renderGarminBar() {
  const el = document.getElementById('garmin-bar');
  if (!el) return;
  const w = _wellnessToday;
  if (!w) { el.style.display = 'none'; return; }
  const GOOD = '#4ade80', WARN = '#fbbf24', BAD = '#ef4444', NEUTRAL = 'var(--text)';
  const dim = '<span style="color:var(--muted)">&mdash;</span>';
  function band(v, good, warn) { return v == null ? NEUTRAL : (v >= good ? GOOD : (v >= warn ? WARN : BAD)); }
  function chip(html, color) {
    return '<div class="garmin-metric" style="font-family:\'DM Mono\',monospace;font-size:16px;text-align:center;padding:6px 4px;color:' + color + '">' + html + '</div>';
  }
  let hrvColor = NEUTRAL;
  if (w.hrv != null && w.hrv_weekly_avg) {
    const ratio = w.hrv / w.hrv_weekly_avg;
    hrvColor = ratio >= 1 ? GOOD : (ratio >= 0.85 ? WARN : BAD);
  }
  // Honest staleness tag: if the latest reading isn't today's, label the day so
  // we never present an old reading as "today" but also never blank the strip.
  let dateTag = '';
  try {
    const todayIso = new Date().toLocaleDateString('en-CA');  // YYYY-MM-DD, local
    if (w.date && w.date !== todayIso) {
      const dn = new Date(w.date + 'T00:00:00').toLocaleDateString(undefined, {weekday: 'short'});
      dateTag = '<div class="garmin-metric" style="font-family:\'DM Mono\',monospace;font-size:13px;text-align:center;padding:6px 4px;color:var(--muted)">' + dn + ' &#8635;</div>';
    }
  } catch(e) {}
  el.innerHTML = '<div class="garmin-metrics">' +
    chip(w.sleep_hours != null
      ? '&#128564; ' + w.sleep_hours + 'h' + (w.sleep_score != null ? ' &middot; ' + w.sleep_score : '')
      : '&#128564; ' + dim, band(w.sleep_score, 80, 60)) +
    chip(w.hrv != null ? 'HRV ' + w.hrv : 'HRV ' + dim, hrvColor) +
    chip(w.body_battery != null ? '&#128267; ' + w.body_battery : '&#128267; ' + dim, band(w.body_battery, 60, 30)) +
    chip(w.readiness != null ? 'Ready ' + w.readiness : 'Ready ' + dim, band(w.readiness, 70, 40)) +
    dateTag +
    '</div>';
  el.style.display = '';
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

  const done = isDayDone(currentWeek, currentDay);
  const exCount = (d.exercises || []).length;
  const exDone = (d.exercises || []).filter((_, i) => isExDone(currentWeek, currentDay, i)).length;

  el.innerHTML = `<div class="th-card${done ? ' th-done' : ''}">
    <div class="th-top">
      <div>
        <div class="th-label">${dayLabel}</div>
        <div class="th-title">${liftTitleHtml(d)}</div>
      </div>
      <div class="th-progress-ring">${exDone}/${exCount}</div>
    </div>
    <div class="th-run">
      ${runPillHtml(d)}
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

// Fail-loud lift title: on an unplanned day the server nulls liftName
// (coach-or-nothing — the template workout name is not the user's plan).
// Render a loud marker instead of 'null' or a template name.
function liftTitleHtml(d) {
  if (d && d.liftName) return d.liftName;
  if (d && d.liftStatus === 'unplanned') return '&#9888; Not planned';
  if (d && d.isRest) return 'Rest Day';
  return '';
}

// Fail-loud run pill: the static template is never shown as the plan. When a
// run has no real coach/engine plan (runStatus 'unplanned' or run missing),
// render a loud marker instead of a fabricated duration.
function runPillHtml(d) {
  if (!d || !d.run || d.runStatus === 'unplanned') {
    return '<span class="run-pill run-unplanned">&#9888; Run not planned</span>';
  }
  return '<span class="run-pill run-' + d.run.type + '">' + d.run.label + ' &middot; ' + d.run.time + '</span>';
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

    return `<div class="day-card${isRest?' rest':''}${done?' completed':''}${currentDay===i?' active':''}" onclick="setDay(${i})">
      <div class="day-card-left">
        <div class="day-abbr">${d.day}</div>
      </div>
      <div class="day-card-center">
        <div class="day-lift-label">${liftTitleHtml(d)}</div>
        <div class="day-run-label">
          ${runPillHtml(d)}
        </div>
      </div>
      <div class="day-card-right" onclick="toggleDay(${currentWeek},${i},event)">
        ${done ? '&#10003;' : '&#9675;'}
      </div>
    </div>`;
  }).join('');
}

// ─── ACCORDION CONTENT BUILDERS ───
let _lastCoachMsgTime = 0;

function buildCoachContent(d) {
    var html = '';
    if (d.notes) html += '<div class="notes-box"><strong>Coach note:</strong> ' + d.notes + '</div>';
    // Show last coach message only (compact), not full history
    var lastCoachMsg = '';
    var lastCoachTime = 0;
    for (var i = _chatHistory.length - 1; i >= 0; i--) {
        if (_chatHistory[i].role === 'coach' || _chatHistory[i].role === 'assistant') {
            lastCoachMsg = _chatHistory[i].text || _chatHistory[i].content || '';
            if (_chatHistory[i].time) lastCoachTime = new Date(_chatHistory[i].time).getTime();
            break;
        }
    }
    // No auto-refresh — coach only speaks when you tap "Talk to Erik"
    // Show "Plan Next Week" button on Sunday afternoon or Monday
    html += '<div id="coach-inline-chat" style="margin-top:12px">';
    // Show Plan Week button only on Sunday/Monday AND only if next week isn't planned yet.
    // Check if next week has meal plans — meals are only generated during planning.
    var _cDow = new Date().getDay(); // 0=Sun, 1=Mon
    var _isSunOrMon = _cDow === 0 || _cDow === 1;
    var _nextWk = currentWeek + 1;
    var _nextWkData = workoutData && workoutData[String(_nextWk)];
    var _nextWkPlanned = false;
    if (_nextWkData && _nextWkData.days) {
      for (var _ndi = 0; _ndi < _nextWkData.days.length && !_nextWkPlanned; _ndi++) {
        if (_nextWkData.days[_ndi] && _nextWkData.days[_ndi].mealPlan) _nextWkPlanned = true;
      }
    }
    if (_isSunOrMon && !_nextWkPlanned && _nextWk <= 12) {
      html += '<button class="btn btn-primary" style="width:100%;font-size:15px;padding:12px;margin-bottom:8px;background:var(--accent);color:#0d0f0e" onclick="launchWeeklyPlanning()">Plan Week ' + _nextWk + '</button>';
    }
    html += '<button class="btn btn-primary" style="width:100%;font-size:15px;padding:12px" onclick="openInlineCoachChat()">Talk to Erik</button>' +
    '</div>';
    return html;
}

async function launchWeeklyPlanning(weekOverride) {
    // Manually trigger the weekly planning flow
    var container = document.getElementById('coach-inline-chat');
    if (!container) return;
    var targetWeek = weekOverride || currentWeek + 1;
    var isReplan = targetWeek === currentWeek;
    container.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--muted)"><div class="chat-typing"><span></span><span></span><span></span></div><div style="margin-top:8px">' + (isReplan ? 'Re-generating this week\'s program...' : 'Generating next week\'s program...') + '</div></div>';

    var nextWeek = targetWeek;
    var programData = null;
    if (nextWeek <= 12) {
        try {
            // Re-planning the current week: force a fresh coach regen of the
            // REST of the week. The server preserves today + earlier days
            // (rest_of_week), so a completed day is never overwritten.
            var _body = isReplan
                ? { week: nextWeek, force_regen: true, rest_of_week: true }
                : { week: nextWeek };
            var progRes = await fetch('/api/weekly-program/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(_body),
            });
            if (progRes.ok) {
                var _pd = await progRes.json();
                if (_pd && _pd.status === 'started') {
                    // Heavy coach generation runs server-side in the background
                    // (so the request can't 502 on the ~25s edge timeout). Poll
                    // for the result — it normally lands in 30-60s.
                    for (var _att = 0; _att < 60; _att++) {
                        await new Promise(function(r){ setTimeout(r, 3000); });
                        try {
                            var _st = await fetch('/api/weekly-program/generate-status?week=' + nextWeek);
                            if (!_st.ok) continue;
                            var _stj = await _st.json();
                            if (_stj.status === 'done') { programData = _stj; break; }
                            if (_stj.status === 'error') { programData = null; break; }
                            // Show what the coaches are actually doing on the load page.
                            if (_stj.status === 'running' && _stj.progress) {
                                container.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--muted)">'
                                    + '<div class="chat-typing"><span></span><span></span><span></span></div>'
                                    + '<div style="margin-top:10px;font-size:13px;line-height:1.5;max-width:340px;margin-left:auto;margin-right:auto">'
                                    + escapeHtml(_stj.progress) + '</div></div>';
                            }
                        } catch(e) {}
                    }
                } else {
                    programData = _pd;
                }
            }
        } catch(e) {}
    }

    // Belt-and-suspenders: if polling ended WITHOUT a program — a lost job (server
    // restart wiped the in-process status), an errored job that still committed, or
    // a 3-min timeout — but the week was generated and PERSISTED, recover it
    // directly so the plan ALWAYS renders right after running. generate-status now
    // falls back to the saved program, so this returns it if it exists. Never leave
    // a saved week showing a blank screen.
    if (nextWeek <= 12 && (!programData || !programData.program)) {
        try {
            var _rec = await fetch('/api/weekly-program/generate-status?week=' + nextWeek);
            if (_rec.ok) {
                var _recj = await _rec.json();
                if (_recj && _recj.status === 'done' && _recj.program) programData = _recj;
            }
        } catch(e) {}
    }

    // Build the program summary WITH last week's actual data for comparison
    var programSummary = '';
    // Gather last week's actual set data from cache
    var lastWeekActual = {};
    if (_weightsCache) {
        for (var exName in _weightsCache) {
            var hist = _weightsCache[exName];
            var entries = hist && hist.history ? hist.history : (Array.isArray(hist) ? hist : []);
            // Find entries from previous week
            var prevEntries = entries.filter(function(e) { return e.week === currentWeek; });
            if (prevEntries.length > 0) {
                var last = prevEntries[prevEntries.length - 1];
                lastWeekActual[exName] = {
                    weight: last.weight,
                    reps: last.reps_completed || last.reps || '?',
                };
            }
        }
    }
    if (programData && programData.program) {
        var dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        var currentDayP = -1;
        for (var pi = 0; pi < programData.program.length; pi++) {
            var p = programData.program[pi];
            if (p.day !== currentDayP) { currentDayP = p.day; programSummary += '\n' + dayNames[p.day] + ':'; }
            var weightStr = p.target_weight ? ' @ ' + p.target_weight + 'lb' : '';
            var reasonStr = p.reason ? ' (' + p.reason + ')' : '';
            // Include what they ACTUALLY lifted last week
            var prevStr = '';
            var prev = lastWeekActual[p.exercise];
            if (prev && prev.weight) {
                var delta = p.target_weight ? (p.target_weight - prev.weight) : 0;
                var changeLabel = delta > 0 ? ' [UP ' + delta + 'lb]' : delta < 0 ? ' [DOWN ' + Math.abs(delta) + 'lb]' : ' [HOLD]';
                prevStr = ' (last week: ' + prev.weight + 'lb x ' + prev.reps + ' reps' + changeLabel + ')';
            }
            programSummary += '\n  ' + p.exercise + ': ' + p.sets + 'x' + p.reps + weightStr + reasonStr + prevStr;
        }
    }
    var deficitStr = '';
    if (programData && programData.deficit) {
        var dd = programData.deficit;
        deficitStr = '\n\nWEIGHT STATUS: ' + dd.current_weight + 'lb now. Target: ' + dd.target_weight + 'lb. ' + dd.weeks_remaining + ' weeks remaining. Required rate: ' + dd.required_weekly_loss + ' lb/week.';
    }
    var calorieStr = '';
    if (programData && programData.calorie_change) {
        var cc = programData.calorie_change;
        if (cc.previous_calories && cc.new_calories) {
            var calDelta = cc.new_calories - cc.previous_calories;
            var calDir = calDelta > 0 ? 'UP' : calDelta < 0 ? 'DOWN' : 'UNCHANGED';
            calorieStr = '\n\nCALORIE RECALIBRATION: ' + cc.previous_calories + ' -> ' + cc.new_calories + ' cal/day (' + calDir + ' ' + Math.abs(calDelta) + ' cal). ';
            if (cc.previous_protein && cc.new_protein) {
                calorieStr += 'Protein: ' + cc.previous_protein + ' -> ' + cc.new_protein + 'g. ';
            }
            calorieStr += cc.reason || '';
        }
    }
    var mealStr = '';
    if (programData && programData.meal_summary) {
        mealStr = '\n\nMEAL PLAN:';
        var dn = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        for (var mi = 0; mi < programData.meal_summary.length; mi++) {
            var md = programData.meal_summary[mi];
            mealStr += '\n  ' + dn[md.day] + ': ' + md.calories + ' cal, ' + md.protein + 'g protein (' + md.type + ')';
        }
    }

    // The coach ONLY provides a brief overview. The exercise list is rendered
    // programmatically — the LLM never touches exercise formatting.
    var trigger = '[MORNING_CHECKIN] [WEEKLY_PLANNING] ' + localTimeContext() +
        '\n\n' + (isReplan ? 'Re-planning Week ' + nextWeek + '.' :
        'Weekly planning for Week ' + nextWeek + '.') +
        deficitStr + calorieStr +
        '\n\nThe exercise list will be shown separately by the app. Your job is ONLY to give a 2-3 sentence overview:' +
        '\n- What changed this week vs last (weight progress, calorie adjustments)' +
        '\n- Key progression highlights (which lifts went up, any holds)' +
        '\n- One motivational line' +
        '\nKeep it under 4 sentences. Do NOT list any exercises — the app handles that.';

    // BUILD the exercise list as HTML directly from programData — never let the LLM format it.
    // The coach only provides commentary (overview, progression notes).
    var _dayHtmlBlocks = {};
    var _dayOrder = [];
    var _dayLabels = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    // Load exercise swaps to apply to the plan view
    var _planSwaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');

    if (programData && programData.program) {
        var _curDay = -1;
        var _dayHtml = '';
        var _exIdxInDay = 0;
        for (var _ei = 0; _ei < programData.program.length; _ei++) {
            var _ex = programData.program[_ei];
            if (_ex.day !== _curDay) {
                _exIdxInDay = 0;
                if (_curDay >= 0) { _dayHtmlBlocks[_curDay] = _dayHtml; }
                _curDay = _ex.day;
                _dayOrder.push(_curDay);
                var _schedInfo = programData.schedule_summary ? programData.schedule_summary[_curDay] : null;
                var _liftName = _schedInfo ? _schedInfo.lift_name || '' : '';
                _dayHtml = '<div style="font-weight:700;font-size:15px;color:var(--accent);margin-bottom:6px">' + _dayLabels[_curDay] + (_liftName ? ' — ' + _liftName : '') + '</div>';
            }
            var _swapKeyPre = nextWeek + '_' + _ex.day + '_' + _exIdxInDay;
            var _displayNameForWt = _planSwaps[_swapKeyPre] || _ex.exercise;
            var _prevForWt = lastWeekActual[_displayNameForWt] || lastWeekActual[_ex.exercise];
            // Unit handling: height-tracked plyometrics (Box Jump) use "in",
            // bodyweight exercises show "BW", everything else is lb. Without
            // this Box Jump prescriptions showed "25lb" — the value is box
            // height in inches, not pounds on the bar.
            var _isHeight = _ex.tracked_metric === 'height';
            var _isBW = isBodyweightExercise(_displayNameForWt, _ex.note);
            var _unit = _isHeight ? 'in' : 'lb';
            var _wt;
            if (_isBW) {
                _wt = 'BW';
            } else if (_ex.target_weight) {
                _wt = _ex.target_weight + _unit;
            } else if (_prevForWt && _prevForWt.weight) {
                _wt = _prevForWt.weight + _unit;
            } else {
                _wt = '—';
            }
            // Plan-vs-plan baseline: compare to last week's PRESCRIPTION
            // (prev_target_weight/prev_reps served from the server), NOT logged
            // work — that mismatch produced the phantom "was 38". Null when there
            // is genuinely no prior plan (week 1 / new lift) -> no baseline shown.
            var _prev = (_ex.prev_target_weight != null)
                ? { weight: _ex.prev_target_weight, reps: _ex.prev_reps }
                : null;
            var _changeHtml = '';
            if (_isBW) {
                // Bodyweight: no weight delta — just show rep change if any
                if (_prev && _prev.reps) {
                    var _bwPrevReps = parseInt(_prev.reps) || 0;
                    var _bwNewReps = parseInt(_ex.reps) || 0;
                    if (_bwNewReps > _bwPrevReps) {
                        _changeHtml = '<span style="color:#4ade80"> — reps UP (' + _bwPrevReps + '→' + _bwNewReps + ')</span>';
                    } else if (_bwNewReps < _bwPrevReps) {
                        _changeHtml = '<span style="color:#ef4444"> — reps DOWN (' + _bwPrevReps + '→' + _bwNewReps + ')</span>';
                    } else {
                        _changeHtml = '<span style="color:var(--muted)"> — HOLD (BW × ' + _prev.reps + ')</span>';
                    }
                }
            } else if (_prev && _prev.weight && _ex.target_weight) {
                var _dw = _ex.target_weight - _prev.weight;
                var _prevReps = parseInt(_prev.reps) || 0;
                var _newReps = parseInt(_ex.reps) || 0;
                var _dr = _newReps - _prevReps;
                var _changeWord = _isHeight ? 'height' : 'weight';
                if (_dw > 0) {
                    _changeHtml = '<span style="color:#4ade80"> — ' + _changeWord + ' UP ' + _dw + _unit + '</span> <span style="color:var(--muted)">(last plan ' + _prev.weight + _unit + ' × ' + _prev.reps + ')</span>';
                } else if (_dw < 0) {
                    _changeHtml = '<span style="color:#ef4444"> — ' + _changeWord + ' DOWN ' + Math.abs(_dw) + _unit + '</span> <span style="color:var(--muted)">(last plan ' + _prev.weight + _unit + ' × ' + _prev.reps + ')</span>';
                } else if (_dr > 0) {
                    _changeHtml = '<span style="color:#4ade80"> — reps UP (' + _prevReps + '→' + _newReps + ')</span> <span style="color:var(--muted)">(last plan ' + _prev.weight + _unit + ' × ' + _prev.reps + ')</span>';
                } else if (_dr < 0) {
                    _changeHtml = '<span style="color:#ef4444"> — reps DOWN (' + _prevReps + '→' + _newReps + ')</span> <span style="color:var(--muted)">(last plan ' + _prev.weight + _unit + ' × ' + _prev.reps + ')</span>';
                } else {
                    _changeHtml = '<span style="color:var(--muted)"> — HOLD (last plan ' + _prev.weight + _unit + ' × ' + _prev.reps + ')</span>';
                }
            }
            // NOTE: do NOT put _ex.reason in _changeHtml here — it is rendered
            // once below as _whyHtml. Having both double-printed the why (the
            // "why is this repeating itself?" bug). _changeHtml is delta-only.
            // Apply swap overlay — check if this exercise was swapped
            var _swapKey = nextWeek + '_' + _ex.day + '_' + _exIdxInDay;
            var _displayExName = _planSwaps[_swapKey] || _ex.exercise;
            _exIdxInDay++;

            // Per-exercise WHY: prefer the strength-coach agent's reason
            // (server-side, peer-aware, generated at planning time). Falls
            // back to the deterministic client-side mapping only when the
            // server didn't return one. The deterministic fallback exists
            // because it can't see peer state and will lie when the whole
            // day is holding ("anchor while accessories progress" — when
            // nothing's progressing).
            var _why = _ex.why || _ex.reason || exerciseWhy(_displayExName, _ex, _prev, nextWeek);
            var _whyHtml = _why ? '<div style="padding:0 0 4px 12px;font-size:12px;color:var(--muted);line-height:1.4;font-style:italic">' + _why + '</div>' : '';
            _dayHtml += '<div style="padding:2px 0;font-size:14px">- ' + _displayExName + ': ' + _ex.sets + '×' + _ex.reps + ' @ ' + _wt + (_displayExName !== _ex.exercise ? ' <span style="color:var(--muted)">(swapped)</span>' : '') + _changeHtml + '</div>' + _whyHtml;
        }
        if (_curDay >= 0) { _dayHtmlBlocks[_curDay] = _dayHtml; }
    }
    // Add run info with last-week comparison
    // Get last week's runs from workoutData
    var _lastWeekRuns = {};
    var _lwData = workoutData && workoutData[String(currentWeek)];
    if (_lwData && _lwData.days) {
        for (var _lri = 0; _lri < _lwData.days.length; _lri++) {
            var _lrd = _lwData.days[_lri];
            if (_lrd && _lrd.run) {
                _lastWeekRuns[_lri] = { label: _lrd.run.label, time: _lrd.run.time };
            }
        }
    }
    if (programData && programData.run_summary) {
        for (var _ri = 0; _ri < programData.run_summary.length; _ri++) {
            var _run = programData.run_summary[_ri];
            if (_dayHtmlBlocks[_run.day] !== undefined) {
                var _runLabel = _run.label || _run.type || '?';
                var _runTime = _run.time || _run.duration || '?';
                var _runChange = '';
                // Plan-vs-plan: compare to LAST WEEK'S PRESCRIBED run duration
                // (served as prev_duration), NOT the stale same-week cache that
                // produced the phantom "was 38". No prior plan -> no baseline.
                var _prevDur = _run.prev_duration;
                // Only a minute-delta when BOTH sides are minute-based — never
                // "UP 46 min (last plan 1 mile)".
                if (_prevDur && /min/i.test(String(_prevDur)) && /min/i.test(String(_runTime))) {
                    var _prevMin = parseInt(_prevDur) || 0;
                    var _newMin = parseInt(_runTime) || 0;
                    if (_prevMin > 0 && _newMin > 0 && _newMin !== _prevMin) {
                        var _runDelta = _newMin - _prevMin;
                        _runChange = _runDelta > 0
                            ? ' <span style="color:#4ade80">UP ' + _runDelta + ' min</span> <span style="color:var(--muted)">(last plan ' + _prevDur + ')</span>'
                            : ' <span style="color:#ef4444">DOWN ' + Math.abs(_runDelta) + ' min</span> <span style="color:var(--muted)">(last plan ' + _prevDur + ')</span>';
                    }
                }
                _dayHtmlBlocks[_run.day] += '<div style="padding:2px 0;font-size:14px;color:var(--accent)">Run: ' + _runLabel + ', ' + _runTime + _runChange + '</div>';
            }
        }
    }
    // Store for day-by-day reveal
    window._planDayBlocks = _dayHtmlBlocks;
    window._planDayOrder = _dayOrder;
    window._planDayIdx = 0;

    // Now open the inline chat — show coach overview first, then reveal days one at a time
    container.innerHTML =
      '<div id="coach-inline-messages" style="max-height:60vh;overflow-y:auto;padding:8px 0">' +
        '<div class="chat-bubble coach" style="background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px"><div class="chat-typing"><span></span><span></span><span></span></div></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:8px">' +
        '<input type="text" id="coach-inline-input" placeholder="Message Erik..." enterkeyhint="send" onkeydown="if(event.key===\'Enter\'){event.preventDefault();sendInlineCoachMsg()}" style="flex:1;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;padding:10px 14px;color:var(--text);font-size:15px;outline:none">' +
        '<button onclick="sendInlineCoachMsg()" style="background:var(--surface2);border:1px solid var(--border2);color:var(--text);border-radius:8px;padding:10px 16px;font-weight:600;cursor:pointer;font-size:14px">Send</button>' +
      '</div>';

    // Stream the coach's planning response
    try {
        var res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: trigger }),
        });
        var messagesEl = document.getElementById('coach-inline-messages');
        var bubble = messagesEl ? messagesEl.querySelector('.chat-bubble.coach') : null;
        if (bubble) bubble.innerHTML = '';
        var fullText = '';
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        while (true) {
            var result = await reader.read();
            if (result.done) break;
            var chunk = decoder.decode(result.value, { stream: true });
            var lines = chunk.split('\n');
            var stop = false;
            for (var li = 0; li < lines.length; li++) {
                if (lines[li].startsWith('data: ')) {
                    var data = lines[li].slice(6);
                    if (data === '[DONE]') { stop = true; break; }
                    if (data.startsWith('[ERROR')) {
                        var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
                        fullText += '\n\n[Coach error: ' + errMsg + ']';
                        if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
                        stop = true; break;
                    }
                    fullText += data.replace(/\\n/g, '\n');
                    if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
                    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
                }
            }
            if (stop) break;
        }
        if (!fullText.trim()) {
            if (bubble) bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
        }
        if (_chatHistory) {
            _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
        }
    } catch(e) {
        var bubble2 = document.querySelector('#coach-inline-messages .chat-bubble.coach');
        if (bubble2) bubble2.textContent = 'Let\'s plan next week. What\'s on your schedule?';
    }
    var input = document.getElementById('coach-inline-input');
    if (input) setTimeout(function() { input.focus(); }, 100);
}

function openInlineCoachChat() {
    var container = document.getElementById('coach-inline-chat');
    if (!container) return;
    container.innerHTML =
      '<div id="coach-inline-messages" style="max-height:50vh;overflow-y:auto;padding:8px 0">' +
        '<div class="chat-bubble coach" style="background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px"><div class="chat-typing"><span></span><span></span><span></span></div></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:8px">' +
        '<input type="text" id="coach-inline-input" placeholder="Message Erik..." enterkeyhint="send" ' +
          'onkeydown="if(event.key===\'Enter\')sendInlineCoachMsg()" ' +
          'style="flex:1;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;padding:10px 14px;color:var(--text);font-size:15px;outline:none">' +
        '<button onclick="sendInlineCoachMsg()" style="background:var(--coach);color:#000;border:none;border-radius:8px;padding:10px 16px;font-weight:600;cursor:pointer;font-size:14px">Send</button>' +
      '</div>';
    _fetchInlineCoachOpener();
}

async function _fetchInlineCoachOpener() {
    var messagesEl = document.getElementById('coach-inline-messages');
    if (!messagesEl) return;
    var trigger = '[CHAT_OPENED] ' + localTimeContext() + ' Look at workouts done, meals logged, timing compliance. Give a brief, relevant comment on where the athlete is RIGHT NOW. If something stands out (early/late meal, great day, rest evening, etc.), address it. 1-3 sentences. Ask what is on their mind.';
    try {
        var res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: trigger }),
        });
        var bubble = messagesEl.querySelector('.chat-bubble.coach');
        if (bubble) bubble.innerHTML = '';
        var fullText = '';
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        while (true) {
            var result = await reader.read();
            if (result.done) break;
            var chunk = decoder.decode(result.value, { stream: true });
            var lines = chunk.split('\n');
            var stop = false;
            for (var i = 0; i < lines.length; i++) {
                if (lines[i].startsWith('data: ')) {
                    var data = lines[i].slice(6);
                    if (data === '[DONE]') { stop = true; break; }
                    if (data.startsWith('[ERROR')) {
                        var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
                        fullText += '\n\n[Coach error: ' + errMsg + ']';
                        if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
                        stop = true; break;
                    }
                    fullText += data.replace(/\\n/g, '\n');
                    if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                }
            }
            if (stop) break;
        }
        if (!fullText.trim()) {
            if (bubble) bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
        }
        if (_chatHistory) {
            _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
        }
    } catch(e) {
        var bubble = messagesEl.querySelector('.chat-bubble.coach');
        if (bubble) bubble.textContent = 'What\'s on your mind?';
    }
    var input = document.getElementById('coach-inline-input');
    if (input) setTimeout(function() { input.focus(); }, 100);
}

function showNextPlanDay() {
    var blocks = window._planDayBlocks || {};
    var order = window._planDayOrder || [];
    var idx = window._planDayIdx || 0;
    if (idx >= order.length) return;

    var dayNum = order[idx];
    var dayLabel = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][dayNum] || 'Day';
    var html = blocks[dayNum] || '';
    var messagesEl = document.getElementById('coach-inline-messages');
    if (messagesEl && html) {
        var dayBubble = document.createElement('div');
        dayBubble.style.cssText = 'background:var(--surface2);border:1px solid var(--border2);border-radius:12px;padding:12px 14px;margin-bottom:8px';
        dayBubble.innerHTML = html;
        messagesEl.appendChild(dayBubble);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // Track which day is currently being discussed so the coach knows context
    window._planCurrentDay = dayLabel;

    window._planDayIdx = idx + 1;
    var btn = document.getElementById('plan-next-day-btn');
    if (btn) {
        if (window._planDayIdx < order.length) {
            var nextDayLabel = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][order[window._planDayIdx]] || 'Next';
            btn.textContent = 'Show ' + nextDayLabel;
        } else {
            btn.textContent = 'All Days Shown';
            btn.disabled = true;
            btn.style.opacity = '0.5';
        }
    }
}

async function sendInlineCoachMsg() {
    var input = document.getElementById('coach-inline-input');
    var text = (input.value || '').trim();
    if (!text) return;
    input.value = '';
    var displayText = text;
    // --- Weekly-planning walkthrough: the APP drives the day-by-day reveal ---
    // The advance must NOT depend on the LLM emitting [SHOW_NEXT_DAY] (it often
    // fails to, and instead tries to "lock the week"). We detect the athlete's
    // confirmation here and advance deterministically below. Confirmation is
    // detected in BOTH states: at the overview ("Ready to see Tuesday?" -> "yes")
    // and on a day card ("anything to swap?" -> "no / looks good").
    var _planning = !!window._planDayBlocks;
    var _isChange = false, _isReady = false, _isDone = false;
    if (_planning) {
        var _dl = displayText.toLowerCase().trim();
        _isChange = /swap|change|switch|replace|adjust|modify|push|increase|decrease|lower|raise|drop|bump|move|different/i.test(displayText);
        _isReady = /^(y(es|ep|eah|up)?|ready|ok(ay)?|sure|go|next|show( me)?|continue|proceed|let'?s? go|sounds good|looks good|perfect|great|do it)\b/.test(_dl);
        _isDone = /^(no|nope|that'?s? (it|all|good)|nothing|all good|good|done|looks good|we'?re? good|nah|i'?m good)\b/.test(_dl);
        if (window._planCurrentDay) {
            if (_isChange) window._planChangesPending = true;
            if (_isDone && window._planChangesPending) window._planChangesPending = false;
            text = '[Context: discussing ' + window._planCurrentDay + '. Exercise list shown by app.' +
                (window._planChangesPending ? ' CHANGES WERE JUST MADE — ask if anything else before advancing. Do NOT emit SHOW_NEXT_DAY yet.' : '') +
                '] ' + text;
        } else if (window._planDayIdx === 0) {
            text = '[Context: weekly planning overview was just shown. Exercise lists are shown by the app when you say SHOW_NEXT_DAY.] ' + text;
        }
    }

    var messagesEl = document.getElementById('coach-inline-messages');
    if (!messagesEl) return;

    // User bubble — show only what the user typed (skip if auto-triggered)
    if (displayText) {
        var userBubble = document.createElement('div');
        userBubble.style.cssText = 'background:var(--surface2);border:1px solid var(--border2);border-radius:12px;padding:10px 14px;font-size:14px;line-height:1.5;color:var(--text);margin-bottom:8px;align-self:flex-end;text-align:right';
        userBubble.textContent = displayText;
        messagesEl.appendChild(userBubble);
    }

    // Typing indicator
    var typingBubble = document.createElement('div');
    typingBubble.className = 'chat-bubble coach';
    typingBubble.style.cssText = 'background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px';
    typingBubble.innerHTML = '<div class="chat-typing"><span></span><span></span><span></span></div>';
    messagesEl.appendChild(typingBubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
        var res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: text }),
        });
        typingBubble.innerHTML = '';
        var fullText = '';
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        while (true) {
            var result = await reader.read();
            if (result.done) break;
            var chunk = decoder.decode(result.value, { stream: true });
            var lines = chunk.split('\n');
            var stop = false;
            for (var i = 0; i < lines.length; i++) {
                if (lines[i].startsWith('data: ')) {
                    var data = lines[i].slice(6);
                    if (data === '[DONE]') { stop = true; break; }
                    if (data.startsWith('[ERROR')) {
                        var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
                        fullText += '\n\n[Coach error: ' + errMsg + ']';
                        typingBubble.innerHTML = renderCoachMarkdown(fullText);
                        stop = true; break;
                    }
                    fullText += data.replace(/\\n/g, '\n');
                    typingBubble.innerHTML = renderCoachMarkdown(fullText);
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                }
            }
            if (stop) break;
        }
        if (!fullText.trim()) {
            typingBubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
        }
        if (_chatHistory) {
            _chatHistory.push({ role: 'user', content: text, date: todayStr() });
            _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
        }
        // Advance the day-by-day walkthrough. The APP drives this — it does NOT
        // depend on the model emitting [SHOW_NEXT_DAY]. If the athlete confirmed
        // (e.g. "yes" to "Ready to see Tuesday?") and days remain with no pending
        // changes, advance even when the model wrongly tried to lock the week.
        var _hasMarker = fullText.includes('[SHOW_NEXT_DAY]');
        var _daysRemain = window._planDayBlocks && ((window._planDayIdx || 0) < ((window._planDayOrder || []).length));
        var _confirmAdvance = _daysRemain && !window._planChangesPending && !_isChange && (_isReady || _isDone);
        if ((_hasMarker || _confirmAdvance) && window._planDayBlocks && !window._planChangesPending) {
            var _brief = '';
            if (_hasMarker) {
                var _beforeMarker = fullText.split('[SHOW_NEXT_DAY]')[0].trim();
                var _sentences = _beforeMarker.split(/[.!]\s/);
                _brief = _sentences.slice(0, 2).join('. ').trim();
                if (_brief && !_brief.endsWith('.')) _brief += '.';
            }
            // Deterministic path (no marker): drop the model's text — it may have
            // tried to lock the week off-protocol. The day card + follow-up speak.
            if (_brief && _brief.length > 3) {
                typingBubble.innerHTML = renderCoachMarkdown(_brief);
            } else {
                typingBubble.remove();
            }
            // Show the HTML plan, then auto-ask for feedback on the new day
            setTimeout(function() {
                var _beforeIdx = window._planDayIdx || 0;
                showNextPlanDay();
                var _dayName = window._planCurrentDay;
                var _allDone = (window._planDayIdx || 0) >= (window._planDayOrder || []).length;
                if (_allDone) {
                    // All days shown — ask for a weekly summary instead of day feedback
                    var _fbMsg = '[All 6 training days have been shown and confirmed. ' + localTimeContext() + ' Do two things: 1) Give a brief 1-sentence summary that the plan is locked. 2) Ask about soreness or tightness: "Any areas feeling tight or sore? I can add targeted stretching to next week\'s warmups." Do NOT list exercises. Do NOT say weigh-in is tomorrow if today is Sunday — Sunday IS weigh-in day.]';
                } else if (_dayName) {
                    var _fbMsg = '[The HTML exercise plan for ' + _dayName + ' was just shown. Ask ONE question: any swaps or weight adjustments for ' + _dayName + '? Do NOT list exercises. Do NOT mention any other day. One sentence.]';
                }
                if (_fbMsg) {
                    fetch('/api/chat/stream', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ message: _fbMsg }),
                    }).then(function(r) {
                        var _fbBubble = document.createElement('div');
                        _fbBubble.className = 'chat-bubble coach';
                        _fbBubble.style.cssText = 'background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px';
                        var _mel = document.getElementById('coach-inline-messages');
                        if (_mel) { _mel.appendChild(_fbBubble); }
                        var _fbFull = '';
                        var _fbReader = r.body.getReader();
                        var _fbDec = new TextDecoder();
                        (function _readFb() {
                            _fbReader.read().then(function(res) {
                                if (res.done) {
                                    if (!_fbFull.trim()) {
                                        _fbBubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
                                    }
                                    return;
                                }
                                var ch = _fbDec.decode(res.value, { stream: true });
                                var ls = ch.split('\n');
                                var fbStop = false;
                                for (var li = 0; li < ls.length; li++) {
                                    if (ls[li].startsWith('data: ')) {
                                        var dd = ls[li].slice(6);
                                        if (dd === '[DONE]') { fbStop = true; break; }
                                        if (dd.startsWith('[ERROR')) {
                                            var fbErr = dd.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
                                            _fbFull += '\n\n[Coach error: ' + fbErr + ']';
                                            _fbBubble.innerHTML = renderCoachMarkdown(_fbFull);
                                            fbStop = true; break;
                                        }
                                        _fbFull += dd.replace(/\\n/g, '\n');
                                        _fbBubble.innerHTML = renderCoachMarkdown(_fbFull);
                                        if (_mel) _mel.scrollTop = _mel.scrollHeight;
                                    }
                                }
                                if (!fbStop) _readFb();
                            });
                        })();
                    }).catch(function(){});
                }
            }, 300);
        }
    } catch(e) {
        typingBubble.textContent = 'Connection issue. Try again.';
    }
    if (input) input.focus();
}

async function _refreshCoachAccordionMsg() {
    var el = document.getElementById('coach-accordion-refresh');
    if (!el) return;
    var _todayMonIdx = new Date().getDay() === 0 ? 6 : new Date().getDay() - 1;
    var _todayDayData = workoutData && workoutData[String(currentWeek)] && workoutData[String(currentWeek)].days
        ? workoutData[String(currentWeek)].days[_todayMonIdx] : null;
    var _isFastDay = _todayDayData && _todayDayData.mealType && _todayDayData.mealType.toLowerCase().includes('fast');
    var trigger = '[COACH_CHECKIN] ' + localTimeContext() + (_isFastDay ? ' TODAY IS A FASTING DAY. The fast is ONGOING and continues until the next eating window opens. Do NOT say the athlete is "through" the fast or that it is complete. Ask how they are feeling.' : '') + ' Do NOT mention tomorrow unless the data explicitly contains it. Check your data carefully before speaking. Be specific and accurate. 1-2 sentences.';
    try {
        var res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: trigger }),
        });
        var fullText = '';
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        while (true) {
            var result = await reader.read();
            if (result.done) break;
            var chunk = decoder.decode(result.value, { stream: true });
            var lines = chunk.split('\n');
            var stop = false;
            for (var i = 0; i < lines.length; i++) {
                if (lines[i].startsWith('data: ')) {
                    var data = lines[i].slice(6);
                    if (data === '[DONE]') { stop = true; break; }
                    if (data.startsWith('[ERROR')) {
                        var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
                        fullText += '\n\n[Coach error: ' + errMsg + ']';
                        el.textContent = fullText;
                        stop = true; break;
                    }
                    fullText += data.replace(/\\n/g, '\n');
                    el.textContent = fullText;
                }
            }
            if (stop) break;
        }
        if (!fullText.trim()) {
            el.textContent = '(Coach returned an empty response — check server logs)';
        }
        if (_chatHistory) {
            _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
        }
    } catch(e) {
        el.textContent = 'Tap below to talk to Erik.';
    }
}

function buildExerciseContent(d, displayExercises, exRows, bwToggleHtml, runClass, isTraveling) {
    var html = '';
    // On rest days (Sunday), skip warmup/exercises — just show the run
    if (!d.isRest) {
        // FAIL LOUD: lifts come from the coach, never the static template. If
        // this training day has no prescription, say so and offer to plan.
        if (d.liftStatus === 'unplanned' && (!displayExercises || displayExercises.length === 0)) {
            html += '<div class="plan-missing">' +
                '<div>&#9888; Your coach hasn’t planned these lifts yet.</div>' +
                '<button class="btn btn-primary" style="width:100%;margin-top:10px" onclick="launchWeeklyPlanning(currentWeek)">Plan this week</button>' +
            '</div>';
        } else {
            html += renderWarmupInner(d);
            if (displayExercises.length > 0) {
                html += bwToggleHtml + exRows;
            }
        }
    }
    html += buildRunSubsection(d, runClass);
    return html;
}

async function fetchMeasurementsCache() {
    if (window._measurementsCache) return window._measurementsCache;
    try {
        var res = await fetch('/api/measurements');
        if (!res.ok) return [];
        var data = await res.json();
        // Normalize: GET /api/measurements returns `weight`, but renderer expects `weight_lbs`
        window._measurementsCache = (data || []).map(function(e) {
            return {
                date: e.date,
                weight_lbs: (e.weight_lbs != null ? e.weight_lbs : e.weight),
                waist: e.waist,
                chest: e.chest,
                hips: e.hips,
                neck: e.neck,
                bicep_left: e.bicep_left,
                bicep_right: e.bicep_right,
                thigh_left: e.thigh_left,
                thigh_right: e.thigh_right,
            };
        });
        return window._measurementsCache;
    } catch (e) {
        return [];
    }
}

function _buildSparkline(values, lowerIsBetter) {
    if (!values || values.length < 2) return '';
    var w = 80, h = 28, pad = 2;
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var range = max - min || 1;
    var points = [];
    for (var i = 0; i < values.length; i++) {
        var x = pad + (i / (values.length - 1)) * (w - pad * 2);
        var y = pad + (1 - (values[i] - min) / range) * (h - pad * 2);
        points.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    var last = values[values.length - 1];
    var first = values[0];
    var improved = lowerIsBetter ? last <= first : last >= first;
    var color = improved ? '#4ade80' : '#ef4444';
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="display:block">' +
        '<polyline points="' + points.join(' ') + '" fill="none" stroke="' + color + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
        '<circle cx="' + points[points.length - 1].split(',')[0] + '" cy="' + points[points.length - 1].split(',')[1] + '" r="2.5" fill="' + color + '"/>' +
    '</svg>';
}

function renderMeasurementsSection(measurements) {
    if (!measurements || measurements.length === 0) {
        return '<div class="measurements-section" style="margin-top:16px"><h4>Measurements</h4><div style="font-size:13px;color:var(--muted);padding:12px 0">No measurements yet — first entry on Sunday.</div></div>';
    }
    var latest = measurements[measurements.length - 1];
    // Delta vs BASELINE (first entry), not just vs previous week — shows total progress
    var baseline = measurements[0];
    var fields = [
        { key: 'weight_lbs', label: 'Weight', unit: 'lb', lower: true },
        { key: 'waist', label: 'Waist', unit: 'in', lower: true },
        { key: 'chest', label: 'Chest', unit: 'in', lower: true },
        { key: 'hips', label: 'Hips', unit: 'in', lower: true },
        { key: 'neck', label: 'Neck', unit: 'in', lower: true },
        { key: 'bicep_left', label: 'Bicep L', unit: 'in', lower: true },
        { key: 'bicep_right', label: 'Bicep R', unit: 'in', lower: true },
        { key: 'thigh_left', label: 'Thigh L', unit: 'in', lower: true },
        { key: 'thigh_right', label: 'Thigh R', unit: 'in', lower: true },
    ];
    var rows = '';
    for (var i = 0; i < fields.length; i++) {
        var f = fields[i];
        var cur = latest[f.key];
        if (cur == null) continue;
        // Build sparkline from all measurements
        var vals = [];
        for (var j = 0; j < measurements.length; j++) {
            var v = measurements[j][f.key];
            if (v != null) vals.push(v);
        }
        var sparkHtml = _buildSparkline(vals, f.lower);
        // Delta vs baseline (first measurement)
        var deltaHtml = '';
        if (baseline && baseline[f.key] != null && latest !== baseline) {
            var d = cur - baseline[f.key];
            if (d !== 0) {
                var sign = d > 0 ? '+' : '';
                var color = f.lower ? (d < 0 ? 'var(--lift)' : '#ef4444') : (d > 0 ? 'var(--lift)' : '#ef4444');
                deltaHtml = '<span class="m-delta" style="color:' + color + '">' + sign + d.toFixed(1) + '</span>';
            } else {
                deltaHtml = '<span class="m-delta" style="color:var(--muted)">0</span>';
            }
        }
        rows += '<div class="m-row">' +
            '<span class="m-label">' + f.label + '</span>' +
            '<span class="m-spark">' + sparkHtml + '</span>' +
            '<span class="m-val">' + cur + ' ' + f.unit + '</span>' +
            deltaHtml +
        '</div>';
    }
    var dateStr = latest.date || '';
    return '<div class="measurements-section" style="margin-top:16px">' +
        '<h4>Measurements <span style="font-size:11px;color:var(--muted);font-weight:400">' + dateStr + '</span></h4>' +
        '<div class="m-grid">' + (rows || '<div style="font-size:13px;color:var(--muted);padding:12px 0">No values recorded.</div>') + '</div>' +
    '</div>';
}

function buildStatsContent(d, weightSummaryHtml, garminStatsHtml, timingRows, dayIdx) {
    var html = '';
    if (!d.isRest) {
        html += weightSummaryHtml;
        if (timingRows.length > 0) {
            html += '<div style="margin-top:12px"><h4 style="font-family:\'DM Mono\',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:8px">Session Timing</h4>' + timingRows.join('') + '</div>';
        }
    }
    // Garmin stats are always useful (HRV, sleep, etc.)
    html += garminStatsHtml;
    // Measurements section — populated asynchronously so buildStatsContent stays sync
    html += '<div id="measurements-section-mount"></div>';
    // Async fetch + populate measurements with sparklines
    fetchMeasurementsCache().then(function(m) {
        var mount = document.getElementById('measurements-section-mount');
        if (mount) mount.innerHTML = renderMeasurementsSection(m);
    });
    return html;
}

function buildFoodContent(d) {
    // Sunday uses the fast_day meal plan from workout data — render normally, not a shortcut
    // Check for meal override — but fast_day should still render the actual meal plan (whey shake etc)
    var mealOverride = _mealOverrides.find(function(o) { return o.day_idx === currentDay; });
    if (mealOverride && mealOverride.meal_type === 'fast_day') {
        // Don't short-circuit — let renderMealInner show the actual fast_day plan with foods
    } else
    if (mealOverride && mealOverride.note) {
        return '<div style="color:var(--coach);font-size:12px;margin-bottom:8px;padding:8px;border:1px solid var(--border);border-radius:8px">' +
            '&#127860; Meal adjusted: ' + mealOverride.note +
        '</div>' + renderMealInner(d);
    }
    return renderMealInner(d);
}

function buildRunSubsection(d, runClass) {
    // Check for run override
    var runOv = _runOverrides.find(function(o) { return o.day_idx === currentDay; });
    if (runOv) {
        var ovLabel = runOv.run_type || (d.run && d.run.label) || 'Run';
        var ovTime = runOv.duration || (d.run && d.run.time) || '';
        var ovDetail = runOv.detail || (d.run && d.run.detail) || '';
        var ovClass = runOv.run_type ? 'run-' + runOv.run_type.toLowerCase().replace(/\s+/g, '') : runClass;
        return '<div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border)">' +
            '<h4 style="font-family:\'DM Mono\',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:8px">Run</h4>' +
            '<div style="color:var(--coach);font-size:12px;margin-bottom:8px">' +
                '&#127939; Run adjusted by coach' + (runOv.notes ? ' — ' + runOv.notes : '') +
            '</div>' +
            '<div class="run-detail-box">' +
                '<div class="rdl">Type</div>' +
                '<div class="rdt"><span class="run-pill ' + ovClass + '">' + ovLabel + ' &middot; ' + ovTime + '</span></div>' +
                (ovDetail ? '<div class="rdd" style="margin-top:8px">' + ovDetail + '</div>' : '') +
            '</div>' +
        '</div>';
    }

    // FAIL LOUD: no static template run. If the coach hasn't planned this run,
    // say so and offer to generate — never show a fabricated duration.
    if (!d.run || d.runStatus === 'unplanned') {
        return '<div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border)">' +
            '<h4 style="font-family:\'DM Mono\',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:8px">Run</h4>' +
            '<div class="plan-missing">' +
                '<div>&#9888; Your coach hasn’t planned this run yet.</div>' +
                '<button class="btn btn-primary" style="width:100%;margin-top:10px" onclick="launchWeeklyPlanning(currentWeek)">Plan this week</button>' +
            '</div>' +
        '</div>';
    }

    var runKey = currentWeek + '_' + currentDay;
    var existingRun = _runLogCache ? _runLogCache[runKey] : null;
    var runFormHtml = '';
    if (existingRun && (existingRun.distance_miles || existingRun.avg_hr || existingRun.elevation_ft || existingRun.duration_min)) {
        runFormHtml = '<div class="run-log-form" style="margin-top:10px">' +
            '<div style="display:flex;gap:12px;align-items:center;padding:8px 0;color:var(--accent);font-family:\'DM Mono\',monospace;font-size:13px;flex-wrap:wrap">' +
                '<span>&#10003; Logged</span>' +
                (existingRun.distance_miles ? '<span>' + existingRun.distance_miles + ' mi</span>' : '') +
                (existingRun.duration_min ? '<span>' + existingRun.duration_min + ' min</span>' : '') +
                (existingRun.avg_hr ? '<span>HR ' + existingRun.avg_hr + '</span>' : '') +
                (existingRun.elevation_ft ? '<span>' + existingRun.elevation_ft + ' ft</span>' : '') +
                (existingRun.source === 'garmin' ? '<span style="opacity:0.75">&#8986; from Garmin</span>' : '') +
            '</div>' +
            '<button class="btn btn-secondary" style="width:100%;font-size:13px;padding:6px" onclick="document.getElementById(\'run-edit-form\').style.display=\'block\';this.style.display=\'none\'">Edit</button>' +
            '<div id="run-edit-form" style="display:none;margin-top:8px">' +
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">' +
                    '<div><label style="font-size:12px;color:var(--muted)">Distance (mi)</label><input type="number" inputmode="decimal" step="0.1" id="run-dist" class="weight-input" style="width:100%" value="' + (existingRun.distance_miles || '') + '" placeholder="mi"></div>' +
                    '<div><label style="font-size:12px;color:var(--muted)">Duration (min)</label><input type="number" inputmode="numeric" id="run-dur" class="weight-input" style="width:100%" value="' + (existingRun.duration_min || '') + '" placeholder="min"></div>' +
                    '<div><label style="font-size:12px;color:var(--muted)">Avg HR</label><input type="number" inputmode="numeric" id="run-hr" class="weight-input" style="width:100%" value="' + (existingRun.avg_hr || '') + '" placeholder="bpm"></div>' +
                    '<div><label style="font-size:12px;color:var(--muted)">Elevation (ft)</label><input type="number" inputmode="numeric" id="run-elev" class="weight-input" style="width:100%" value="' + (existingRun.elevation_ft || '') + '" placeholder="ft"></div>' +
                '</div>' +
                '<button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="saveRunLog()">Update Run</button>' +
            '</div>' +
          '</div>';
    } else {
        runFormHtml = '<div class="run-log-form" style="margin-top:10px">' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">' +
                '<div><label style="font-size:12px;color:var(--muted)">Distance (mi)</label><input type="number" inputmode="decimal" step="0.1" id="run-dist" class="weight-input" style="width:100%" placeholder="mi"></div>' +
                '<div><label style="font-size:12px;color:var(--muted)">Duration (min)</label><input type="number" inputmode="numeric" id="run-dur" class="weight-input" style="width:100%" placeholder="min"></div>' +
                '<div><label style="font-size:12px;color:var(--muted)">Avg HR</label><input type="number" inputmode="numeric" id="run-hr" class="weight-input" style="width:100%" placeholder="bpm"></div>' +
                '<div><label style="font-size:12px;color:var(--muted)">Elevation (ft)</label><input type="number" inputmode="numeric" id="run-elev" class="weight-input" style="width:100%" placeholder="ft"></div>' +
            '</div>' +
            '<button class="btn btn-primary" style="width:100%;margin-top:8px" onclick="saveRunLog()">Log Run</button>' +
          '</div>';
    }
    var hiitBtn = '';
    if (d.run && d.run.type === 'hiit') {
        hiitBtn = '<button class="btn btn-primary" style="width:100%;margin-top:10px;font-size:15px;padding:12px" onclick="startHiitTimer()">Start HIIT Timer</button>';
    }
    return '<div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border)">' +
        '<h4 style="font-family:\'DM Mono\',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:8px">Run</h4>' +
        '<div class="run-detail-box">' +
            '<div class="rdl">Type</div>' +
            '<div class="rdt"><span class="run-pill ' + runClass + '">' + d.run.label + ' &middot; ' + d.run.time + '</span></div>' +
            '<div class="rdd" style="margin-top:8px">' + d.run.detail + '</div>' +
        '</div>' +
        hiitBtn +
        '<div id="hiit-timer-container"></div>' +
        runFormHtml +
    '</div>';
}

// ─── HIIT TIMER ──────────────────────────────────────────────────────────

let _hiitInterval = null;
let _hiitAudioCtx = null;

function _parseHiitDetail(detail, totalTime) {
    // Parse structured part: "5 min warmup, 8x 30:90, 3 min cooldown"
    // The structured part is canonical — never silently adjust to fit a label.
    // COACH-OR-NOTHING: if the coach's text doesn't parse, return null so the
    // caller fails loud. The old hardcoded defaults (8x30:90, 5-min warmup)
    // silently ran a DIFFERENT workout than the card described.
    var work = null, rest = null, rounds = null, warmup = 0;

    // Parse warmup: "5 min warmup" or "5 min warm"
    var warmupMatch = detail.match(/(\d+)\s*min\s*warm/i);
    if (warmupMatch) warmup = parseInt(warmupMatch[1]) * 60;

    // Parse work:rest ratio from "30:90" format (most reliable)
    var ratioMatch = detail.match(/(\d+):(\d+)/);
    if (ratioMatch) {
        work = parseInt(ratioMatch[1]);
        rest = parseInt(ratioMatch[2]);
    } else {
        // Fallback: "30 sec all-out / 90 sec walk"
        var workMatch = detail.match(/(\d+)\s*sec\s*all/i);
        if (workMatch) work = parseInt(workMatch[1]);
        var restMatch = detail.match(/(\d+)\s*sec\s*(?:walk|rest|recovery)/i);
        if (restMatch) rest = parseInt(restMatch[1]);
    }

    // Parse rounds: prefer the "Nx D:D" format adjacent to the ratio
    var roundMatch = detail.match(/(\d+)\s*x\s*\d+\s*:\s*\d+/);
    if (roundMatch) {
        rounds = parseInt(roundMatch[1]);
    } else {
        // Fallback: first "Nx" in the string
        var fallbackRound = detail.match(/(\d+)\s*x/);
        if (fallbackRound) rounds = parseInt(fallbackRound[1]);
    }

    // FAIL LOUD: the interval structure (work, rest, rounds) must all come from
    // the coach's text. No fabricated defaults.
    if (!work || !rest || !rounds) return null;

    // Cooldown always matches warmup
    return { rounds: rounds, work: work, rest: rest, warmup: warmup, cooldown: warmup };
}

function _playBeep(freq, duration) {
    try {
        if (!_hiitAudioCtx) _hiitAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = _hiitAudioCtx.createOscillator();
        var gain = _hiitAudioCtx.createGain();
        osc.connect(gain);
        gain.connect(_hiitAudioCtx.destination);
        osc.frequency.value = freq;
        gain.gain.value = 0.5;
        osc.start();
        setTimeout(function() { osc.stop(); }, duration);
    } catch(e) {}
}

function _hiitFlash(color) {
    var el = document.getElementById('hiit-timer-container');
    if (!el) return;
    el.style.transition = 'none';
    el.style.boxShadow = '0 0 60px ' + color + ', inset 0 0 60px ' + color;
    setTimeout(function() {
        el.style.transition = 'box-shadow 1s ease';
        el.style.boxShadow = 'none';
    }, 300);
    if (navigator.vibrate) navigator.vibrate([300, 100, 300]);
}

function startHiitTimer() {
    var weekData = workoutData[String(currentWeek)];
    if (!weekData) return;
    var d = weekData.days[currentDay];
    if (!d || !d.run || d.run.type !== 'hiit') return;

    var cfg = _parseHiitDetail(d.run.detail || '', d.run.time || '');
    if (!cfg) {
        // FAIL LOUD: never run a fabricated default (8x30:90) that differs from
        // the workout the card describes. Follow the coach's text manually.
        var errEl = document.getElementById('hiit-timer-container');
        if (errEl) {
            errEl.innerHTML = '<div class="plan-missing" style="margin-top:10px">' +
                '&#9888; Couldn’t read the interval structure from the coach’s prescription — ' +
                'run it from the card text (no timer).</div>';
        }
        return;
    }
    var phases = [];
    if (cfg.warmup > 0) phases.push({ name: 'WARMUP', duration: cfg.warmup, color: '#3b82f6' });
    for (var r = 0; r < cfg.rounds; r++) {
        phases.push({ name: 'ALL OUT', round: r + 1, total: cfg.rounds, duration: cfg.work, color: '#ef4444' });
        phases.push({ name: 'RECOVERY', round: r + 1, total: cfg.rounds, duration: cfg.rest, color: '#22c55e' });
    }
    if (cfg.cooldown > 0) phases.push({ name: 'COOLDOWN', duration: cfg.cooldown, color: '#3b82f6' });

    var phaseIdx = 0;
    var paused = false;
    var pausedAt = 0;
    var pausedRemaining = 0;
    // Wall clock: compute end time so timer works when app is backgrounded
    var phaseEndTime = Date.now() + phases[0].duration * 1000;
    var lastBeepAt = -1; // track which second we last beeped at

    function getRemaining() {
        if (paused) return pausedRemaining;
        return Math.max(0, Math.ceil((phaseEndTime - Date.now()) / 1000));
    }

    function renderTimer() {
        var el = document.getElementById('hiit-timer-container');
        if (!el) { clearInterval(_hiitInterval); return; }
        var remaining = getRemaining();
        var p = phases[phaseIdx];
        var mins = Math.floor(remaining / 60);
        var secs = remaining % 60;
        var timeStr = mins + ':' + (secs < 10 ? '0' : '') + secs;
        var roundStr = p.round ? 'Round ' + p.round + '/' + p.total : '';
        var totalPhases = phases.length;
        var progress = ((phaseIdx / totalPhases) * 100).toFixed(0);

        el.innerHTML = '<div style="background:var(--surface2);border:2px solid ' + p.color + ';border-radius:16px;padding:24px;margin-top:12px;text-align:center">' +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
                '<span style="font-size:12px;color:var(--muted)">' + roundStr + '</span>' +
                '<span style="font-size:12px;color:var(--muted)">' + progress + '% complete</span>' +
            '</div>' +
            '<div style="font-family:\'DM Mono\',monospace;font-size:14px;text-transform:uppercase;letter-spacing:0.15em;color:' + p.color + ';margin-bottom:4px">' + p.name + '</div>' +
            '<div style="font-family:\'DM Mono\',monospace;font-size:64px;font-weight:700;color:var(--text);line-height:1">' + timeStr + '</div>' +
            '<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">' +
                '<button class="btn btn-secondary" style="padding:8px 24px" onclick="toggleHiitPause()">' + (paused ? 'Resume' : 'Pause') + '</button>' +
                '<button class="btn btn-secondary" style="padding:8px 24px;opacity:0.6" onclick="stopHiitTimer()">Stop</button>' +
            '</div>' +
            '<div style="background:var(--border);border-radius:4px;height:4px;margin-top:16px;overflow:hidden">' +
                '<div style="background:' + p.color + ';height:100%;width:' + ((1 - remaining / p.duration) * 100) + '%"></div>' +
            '</div>' +
        '</div>';
    }

    function advancePhase() {
        phaseIdx++;
        if (phaseIdx >= phases.length) {
            clearInterval(_hiitInterval);
            _hiitInterval = null;
            _playBeep(440, 1000);
            _hiitFlash('#22c55e');
            var el = document.getElementById('hiit-timer-container');
            if (el) el.innerHTML = '<div style="background:var(--surface2);border:2px solid #22c55e;border-radius:16px;padding:24px;margin-top:12px;text-align:center">' +
                '<div style="font-size:48px;margin-bottom:8px">&#127942;</div>' +
                '<div style="font-family:\'DM Mono\',monospace;font-size:18px;color:#22c55e">HIIT COMPLETE</div>' +
                '<div style="color:var(--muted);font-size:14px;margin-top:8px">' + cfg.rounds + ' rounds done</div>' +
            '</div>';
            return false;
        }
        phaseEndTime = Date.now() + phases[phaseIdx].duration * 1000;
        lastBeepAt = -1;
        var p = phases[phaseIdx];
        if (p.name === 'ALL OUT') {
            _playBeep(1200, 300);
            setTimeout(function() { _playBeep(1200, 300); }, 400);
            setTimeout(function() { _playBeep(1200, 500); }, 800);
            _hiitFlash('#ef4444');
        } else if (p.name === 'RECOVERY') {
            _playBeep(600, 500);
            _hiitFlash('#22c55e');
        } else if (p.name === 'COOLDOWN') {
            _playBeep(440, 800);
            _hiitFlash('#3b82f6');
        }
        return true;
    }

    if (_hiitInterval) clearInterval(_hiitInterval);
    renderTimer();
    _playBeep(800, 500);

    _hiitInterval = setInterval(function() {
        if (paused) return;
        var remaining = getRemaining();
        // Advance through phases that may have elapsed while backgrounded
        while (remaining <= 0 && phaseIdx < phases.length) {
            if (!advancePhase()) return;
            remaining = getRemaining();
        }
        // 3-2-1 countdown beeps (only beep once per second)
        if (remaining <= 3 && remaining > 0 && remaining !== lastBeepAt) {
            lastBeepAt = remaining;
            _playBeep(1000, 100);
        }
        renderTimer();
    }, 250); // Check 4x/second for responsive UI when returning from background

    window._hiitPauseToggle = function() {
        if (!paused) {
            // Pausing: save remaining time
            paused = true;
            pausedRemaining = Math.max(0, Math.ceil((phaseEndTime - Date.now()) / 1000));
        } else {
            // Resuming: set new end time from saved remaining
            paused = false;
            phaseEndTime = Date.now() + pausedRemaining * 1000;
        }
        renderTimer();
    };
}

function toggleHiitPause() {
    if (window._hiitPauseToggle) window._hiitPauseToggle();
}

function stopHiitTimer() {
    if (_hiitInterval) { clearInterval(_hiitInterval); _hiitInterval = null; }
    var el = document.getElementById('hiit-timer-container');
    if (el) el.innerHTML = '';
}

async function renderDetail() {
  const panel = document.getElementById('detail-panel');
  if (currentDay === null) {
    panel.classList.remove('visible');
    return;
  }
  attachSwipeHandlers();

  try {

  // Morning check-in gate — lock until done
  const todayJsDay = new Date().getDay();
  const todayMonIdx = todayJsDay === 0 ? 6 : todayJsDay - 1;
  // Sync from localStorage — fastest check (same device)
  var _checkinDismissKey = todayJsDay === 0 ? 'sunday_measurements_' + todayStr() : 'checkin_done_' + todayStr();
  if (localStorage.getItem(_checkinDismissKey)) _morningCheckinDone = true;
  // Cross-device sync: if localStorage doesn't have it, ask the server
  if (!_morningCheckinDone && currentDay === todayMonIdx) {
    try {
      const _ciRes = await fetch('/api/morning-checkin?date=' + todayStr());
      const _ciData = await _ciRes.json();
      if (_ciData.exists) {
        _morningCheckinDone = true;
        localStorage.setItem(_checkinDismissKey, '1');
      }
    } catch(e) {}
  }
  if (currentDay === todayMonIdx && !_morningCheckinDone && !localStorage.getItem(_checkinDismissKey)) {
      panel.innerHTML = `<div class="detail-inner" style="padding:2rem;text-align:center">
          <div style="font-size:48px;margin-bottom:1rem">&#x1F512;</div>
          <h3 style="color:var(--text);margin-bottom:0.5rem">Morning Check-In Required</h3>
          <div style="color:var(--muted);font-size:14px;margin-bottom:1.5rem">Complete your morning session with Erik to unlock today's tracking.</div>
          <button class="btn btn-primary" onclick="startMorningCheckin()">Talk to Erik</button>
      </div>`;
      panel.classList.add('visible');
      return;
  }

  // Future week gate — show locked placeholder if browsing ahead AND no plan generated yet
  if (_stateCache && _stateCache.start_date) {
    const _startDt = new Date(_stateCache.start_date + 'T00:00:00');
    const _nowDt = new Date();
    const _diffDays = Math.floor((_nowDt - _startDt) / (1000 * 60 * 60 * 24));
    const _actualWeek = Math.min(12, Math.max(1, Math.floor(_diffDays / 7) + 1));
    const _futureWeekData = workoutData[String(currentWeek)];
    if (currentWeek > _actualWeek && (!_futureWeekData || !_futureWeekData.days || !_futureWeekData.days.length)) {
      panel.innerHTML = '<div class="detail-inner" style="padding:2rem;text-align:center">' +
          '<div style="font-size:48px;margin-bottom:1rem">&#128274;</div>' +
          '<h3 style="color:var(--text);margin-bottom:0.5rem">Coming Soon</h3>' +
          '<div style="color:var(--muted);font-size:14px">This week\'s plan will be set during Monday\'s check-in with Erik.</div>' +
      '</div>';
      panel.classList.add('visible');
      return;
    }
  }

  const weekData = workoutData[String(currentWeek)];
  if (!weekData) return;
  const d = weekData.days[currentDay];
  if (!d) return;
  const runClass = d.run ? `run-${d.run.type}` : 'run-z2';
  const isTraveling = _stateCache && _stateCache.traveling;

  // Check for schedule override — skip day shows rest message
  var schedOverride = _scheduleOverrides.find(function(o) { return o.day_idx === currentDay; });
  if (schedOverride && schedOverride.skip_day) {
    panel.innerHTML = '<div class="detail-inner" style="padding:2rem;text-align:center">' +
        '<div style="font-size:48px;margin-bottom:1rem">&#128524;</div>' +
        '<h3 style="color:var(--text);margin-bottom:0.5rem">Rest Day</h3>' +
        '<div style="color:var(--muted);font-size:14px;margin-bottom:8px">Coach adjusted — take it easy today.</div>' +
        (schedOverride.notes ? '<div style="color:var(--coach);font-size:13px">' + schedOverride.notes + '</div>' : '') +
    '</div>';
    panel.classList.add('visible');
    return;
  }

  // Load exercise swaps BEFORE sets — set lookup needs the swapped names
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
          // Also try original prescription name — sets might be saved under either name
          const origName = displayExercises[i].name;
          const dbKeyOrig = `${currentWeek}_${currentDay}_${origName}`;
          var _matchedKey = setData[dbKey] ? dbKey : (setData[dbKeyOrig] ? dbKeyOrig : null);
          // Also search all keys for partial match (handles KB Swing vs Kettlebell Swing)
          if (!_matchedKey) {
            for (var _sk in setData) {
              if (_sk.startsWith(currentWeek + '_' + currentDay + '_') && _sk !== dbKey && _sk !== dbKeyOrig) {
                // Check if the exercise part matches any known alias
                var _skEx = _sk.substring((currentWeek + '_' + currentDay + '_').length);
                if (_skEx.toLowerCase().replace(/[^a-z]/g,'').includes(exName.toLowerCase().replace(/[^a-z]/g,'').substring(0,6))) {
                  _matchedKey = _sk;
                  break;
                }
              }
            }
          }
          if (_matchedKey && setData[_matchedKey]) {
            for (const [setNum, setInfo] of Object.entries(setData[_matchedKey])) {
              _setCache[`${currentWeek}_${currentDay}_${i}_${setNum}`] = {
                done: !!setInfo.done,
                weight: setInfo.weight,
                reps: setInfo.reps,
              };
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
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  const exRows = displayExercises.map((ex, i) => {
    const swapKey = currentWeek + '_' + currentDay + '_' + i;
    const displayName = swaps[swapKey] || ex.name;
    const isSwapped = !!swaps[swapKey];
    const done = isExDone(currentWeek, currentDay, i);
    let suggestion = getWeightForExercise(displayName, currentWeek);
    let lastWt = getLastWeight(displayName);
    // Fallback: if swapped exercise has no history, estimate from original exercise's weight
    // Scale down for equipment changes (cable→dumbbell, barbell→dumbbell, machine→free)
    if (isSwapped && suggestion.weight == null) {
      var origSuggestion = getWeightForExercise(ex.name, currentWeek);
      if (origSuggestion.weight != null) {
        // Mirrors equipment_swaps.scale_for_swap() — keep in sync.
        var origLower = ex.name.toLowerCase();
        var swapLower = displayName.toLowerCase();
        var toDB = swapLower.includes('dumbbell') || swapLower.includes('db ');
        var scale = 1.0;
        if ((origLower.includes('cable') || origLower.includes('machine')) && toDB) scale = 0.5;
        else if (origLower.includes('barbell') && toDB) scale = 0.7;
        else if ((origLower.includes('cable') || origLower.includes('machine')) && origLower !== swapLower) scale = 0.8;
        suggestion = { weight: roundWeight(origSuggestion.weight * scale, displayName), reason: 'estimated from ' + ex.name };
      }
      if (!lastWt) lastWt = null; // Don't show original exercise's last weight — different movement
    }
    // Resolve the value to put in the weight input. Centralizes the
    // target_weight=0-is-bodyweight rule so the falsy-check bug can't
    // regress. See resolveDisplayWeight + tests/js/weight_prefill.test.mjs.
    const weightVal = resolveDisplayWeight(ex, suggestion);
    // Keep `suggestion.reason` accurate for the badge in the row label.
    if (ex.target_weight != null) {
      suggestion = {
        weight: weightVal === '' ? null : weightVal,
        reason: ex.target_weight === 0 ? 'bodyweight' : 'engine',
      };
    }

    // RPE removed — progression driven by actual data

    // Parse sets format: "4x10" → { count: 4, reps: "10" }
    const setsMatch = (ex.sets || '').match(/^(\d+)x(.+)/);
    const setCount = setsMatch ? parseInt(setsMatch[1]) : 1;
    const targetReps = setsMatch ? setsMatch[2] : ex.sets;
    var targetRepsDisplay = ex.reps || (setsMatch ? setsMatch[2] : ex.sets);
    // "each" is ambiguous — show "per side" so users know it means per leg/arm
    if (typeof targetRepsDisplay === 'string') targetRepsDisplay = targetRepsDisplay.replace(/\beach\b/gi, 'per side');
    const restSeconds = parseRestSeconds(ex.rest);
    const escapedName = displayName.replace(/'/g, "\\'");

    // Detect timed exercises — check ex.reps first (separate field), then parsed sets format
    const repsField = (ex.reps != null && ex.reps !== '') ? String(ex.reps) : targetReps;
    const isTimedEx = /^\d+s$/i.test(repsField);
    const timedSeconds = isTimedEx ? parseInt(repsField) : 0;

    // Detect bodyweight exercises (Ring Row, Plank, Push-Ups, etc.)
    const isBW = isBodyweightExercise(displayName, ex.note);
    // Detect height-tracked plyometrics (Box Jump): the catalog flags these
    // with tracked_metric: "height" so the input shows "in" not "lb".
    const isHeight = ex.tracked_metric === 'height';
    const unit = isHeight ? 'in' : 'lb';

    // Build per-set rows.
    //
    // Bodyweight prescription rule: when ex.target_weight === 0, the
    // prescription is explicitly bodyweight. Ignore historical
    // setData.weight entirely (athlete may have logged 5 lb on a
    // prior Nordic Hamstring Curl session but the current prescription
    // is BW; that historical 5 should NOT prefill today's inputs).
    // Empty inputs let them override if they're adding load this
    // session. setData.done and setData.reps still apply — only
    // setData.weight is suppressed.
    const isBodyweightPrescription = ex.target_weight === 0;
    let setRowsHtml = '';
    let carryWeight = weightVal;
    let firstUndoneSet = -1;  // for timed multi-set: where the HIIT cycle resumes
    for (let s = 0; s < setCount; s++) {
      const setKey = `${currentWeek}_${currentDay}_${i}_${s}`;
      const setData = _setCache && _setCache[setKey];
      const setDone = !!(setData && setData.done);
      if (!setDone && firstUndoneSet < 0) firstUndoneSet = s;
      const setWeight = isBodyweightPrescription
        ? ''  // BW: empty regardless of cache
        : (setData && setData.weight ? setData.weight : carryWeight);
      const setReps = setData && setData.reps ? setData.reps : '';
      if (!isBodyweightPrescription && setData && setData.weight) carryWeight = setData.weight;

      if (isTimedEx && setCount > 1) {
        // Multi-set timed exercise = ONE interval (HIIT-style) cycle: WORK / REST
        // repeated for every set. The single "Start interval timer" button above
        // runs the whole cycle and auto-marks each set done as it advances — so
        // these rows are STATUS ONLY (no per-set launch button, which used to read
        // as three separate manual timers). Tapping the checkbox still toggles a
        // set by hand if you did it without the timer.
        setRowsHtml += `<div class="set-row${setDone ? ' set-done' : ''}">
          <button class="set-check${setDone ? ' done' : ''}" onclick="toggleSet(${currentWeek},${currentDay},${i},${s},${restSeconds},'${escapedName}',this)">
            ${setDone ? '&#10003;' : ''}
          </button>
          <span class="set-label">Set ${s + 1}</span>
          <span style="margin-left:auto;color:var(--muted);font-family:'DM Mono',monospace;font-size:13px">${targetRepsDisplay}${setDone ? ' &#10003;' : ''}</span>
          <div id="inline-timer-${i}-${s}" style="margin-left:8px;font-family:'DM Mono',monospace;font-size:15px;color:var(--accent)"></div>
        </div>`;
      } else if (isTimedEx) {
        // Single-set timed hold → inline countdown timer in-row.
        setRowsHtml += `<div class="set-row${setDone ? ' set-done' : ''}">
          <button class="set-check${setDone ? ' done' : ''}" onclick="toggleSet(${currentWeek},${currentDay},${i},${s},${restSeconds},'${escapedName}',this)">
            ${setDone ? '&#10003;' : ''}
          </button>
          <span class="set-label">Set ${s + 1}</span>
          ${!setDone ? `<button class="btn btn-secondary" style="padding:4px 16px;font-size:13px;font-family:'DM Mono',monospace" onclick="startInlineTimer(${timedSeconds},this,'${escapedName}',${currentWeek},${currentDay},${i},${s},${restSeconds})">${targetRepsDisplay}</button>` : `<span style="color:var(--muted);font-family:'DM Mono',monospace;font-size:13px">${targetRepsDisplay} &#10003;</span>`}
          <div id="inline-timer-${i}-${s}" style="margin-left:8px;font-family:'DM Mono',monospace;font-size:15px;color:var(--accent)"></div>
        </div>`;
      } else if (isBW) {
        // Bodyweight exercise: checkbox + set label + "BW" tag + reps input (no weight input)
        setRowsHtml += `<div class="set-row bw-row${setDone ? ' set-done' : ''}" data-set="${s}">
          <button class="set-check${setDone ? ' done' : ''}" onclick="toggleSet(${currentWeek},${currentDay},${i},${s},${restSeconds},'${escapedName}',this)">${setDone ? '&#10003;' : ''}</button>
          <span class="set-label">Set ${s + 1}</span>
          <span class="bw-tag">BW</span>
          <span class="set-x">&times;</span>
          <input class="reps-input set-reps" type="number" inputmode="numeric" id="reps-${currentWeek}-${currentDay}-${i}-${s}" placeholder="${targetRepsDisplay}" value="${setReps}" min="0" max="100" onblur="saveSetField(${currentWeek},${currentDay},${i},${s},'${escapedName}')" />
        </div>`;
      } else {
        // Normal exercise: checkbox + set label + weight × reps
        setRowsHtml += `<div class="set-row${setDone ? ' set-done' : ''}">
          <button class="set-check${setDone ? ' done' : ''}" onclick="toggleSet(${currentWeek},${currentDay},${i},${s},${restSeconds},'${escapedName}',this)">
            ${setDone ? '&#10003;' : ''}
          </button>
          <span class="set-label">Set ${s + 1}</span>
          <input class="weight-input set-wt" type="number" inputmode="decimal" id="wt-${currentWeek}-${currentDay}-${i}-${s}" value="${setWeight}" placeholder="${unit}" onblur="saveSetField(${currentWeek},${currentDay},${i},${s},'${escapedName}')">
          <span class="set-x">&times;</span>
          <input class="reps-input set-reps" type="number" inputmode="numeric" id="reps-${currentWeek}-${currentDay}-${i}-${s}" value="${setReps}" placeholder="${targetRepsDisplay}" min="0" max="100" onblur="saveSetField(${currentWeek},${currentDay},${i},${s},'${escapedName}')">
        </div>`;
      }
    }

    // Multi-set timed exercise = one interval (HIIT-style) work/rest cycle.
    // A single button runs WORK/REST for every set, auto-marking each done as it
    // advances. Resumes at the first not-yet-completed set.
    const timedCycleBtnHtml = (isTimedEx && setCount > 1)
      ? `<button class="btn btn-primary" style="width:100%;margin:6px 0 10px;font-size:14px;padding:11px;font-family:'DM Mono',monospace" onclick="startExerciseHiit('${escapedName}',${currentWeek},${currentDay},${i},${timedSeconds},${restSeconds},${setCount},${firstUndoneSet < 0 ? 0 : firstUndoneSet})">&#9654; Start interval timer &mdash; ${setCount}&times;${timedSeconds}s work${restSeconds ? ' / ' + _fmtRest(restSeconds) + ' rest' : ''}</button>`
      : '';

    return `<div class="exercise-block">
      <div class="ex-name-row">
        <span class="ex-name">${displayName}</span>${isSwapped ? '<span class="exercise-swapped">(swapped)</span>' : ''}
        <span class="ex-actions"><a class="ex-video-link" href="https://www.youtube.com/results?search_query=${encodeURIComponent(displayName + ' form short')}&sp=EgIYAQ%253D%253D" target="_blank" rel="noopener" title="Watch form video">&#9654;</a> <span class="ex-swap-icon" onclick="showExerciseSwap(${i},'${escapedName}',event)" title="Swap exercise">&#128260;</span></span>
      </div>
      <div class="ex-detail-row">${ex.sets}${ex.rest ? ' · ' + _fmtRest(parseRestSeconds(ex.rest)) + ' rest' : ''}${lastWt != null && !isBodyweightPrescription ? ' · Last: ' + lastWt + ' ' + unit : ''}${(!isSwapped && ex.target_weight) ? ' → ' + ex.target_weight + ' ' + unit : ''}${suggestion.reason && suggestion.reason !== 'estimated' && suggestion.reason !== 'engine' ? ` <span class="ex-prog-indicator" title="${escapeHtml(suggestion.reason)}">${(ex.target_weight && lastWt != null) ? (parseFloat(ex.target_weight) > parseFloat(lastWt) ? '↑' : parseFloat(ex.target_weight) < parseFloat(lastWt) ? '↓' : '—') : '—'}</span>` : ''}</div>
      ${(!isSwapped && ex.note) ? `<div class="ex-note">${ex.note}</div>` : ''}
      ${timedCycleBtnHtml}
      <div class="set-rows">${setRowsHtml}</div>
      <div id="rest-timer-${i}" class="rest-timer"></div>
      <div id="swap-container-${i}"></div>
    </div>`;
  }).join('');

  // Timing rows
  const timingRows = [];
  // Show schedule override banner if workout time was adjusted
  if (schedOverride && schedOverride.workout_time) {
    timingRows.push('<div style="color:var(--coach);font-size:12px;margin-bottom:8px">' +
      '&#9200; Schedule adjusted: workout at ' + schedOverride.workout_time +
      (schedOverride.notes ? ' — ' + schedOverride.notes : '') +
    '</div>');
  }
  if (d.timing) {
    for (let i = 0; i < d.timing.length; i += 2) {
      var desc = d.timing[i+1];
      // Replace template run duration with actual run plan duration
      if (d.run && desc && (desc.toLowerCase().includes('run') || desc.toLowerCase().includes('hiit'))) {
        desc = d.run.label + ' ' + d.run.time;
      }
      timingRows.push(`<div class="timing-row">
        <div class="timing-time">${d.timing[i]}</div>
        <div class="timing-desc">${desc}</div>
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
  }

  // Daily Goals section removed

  // AI Coach chat
  // Chat history removed from accordion — full chat lives in overlay only

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
      // Estimate 1RM — take the BEST of: best logged e1RM ever, OR latest prescription's e1RM.
      // Walk history for weeks 1..maxWk only. Drop entries with NO week tag — they're
      // legacy/untrusted (no time anchor) and have caused phantom highs in the row that
      // contradicted the API timeline.
      const _maxWk = getActualProgramWeek() || currentWeek || 12;
      const exData = getExerciseData(name);
      let est1rm = '';
      let loggedRM = 0;
      if (exData && exData.history && exData.history.length > 0) {
        for (const h of exData.history) {
          const wkN = parseInt(h.week);
          if (!wkN || wkN < 1 || wkN > _maxWk) continue;
          const hw = h.weight || 0;
          const hr = h.reps_completed || h.reps || 10;
          if (hw > 0) {
            const rm = estimate1RM(hw, hr);
            if (rm > loggedRM) loggedRM = rm;
          }
        }
      }
      // Walk weeks of workoutData (capped at user's ACTUAL program week — not viewed week,
      // and not future weeks which may have stale stub prescriptions) to find the LATEST
      // real prescription for this exercise.
      let prescribedRM = 0;
      let latestPrescribedWk = 0;
      let latestTarget = 0;
      let latestRepsStr = '10';
      if (workoutData) {
        for (const wkKey of Object.keys(workoutData)) {
          const wkNum = parseInt(wkKey);
          if (!wkNum || wkNum < 1 || wkNum > _maxWk) continue;
          const wkData = workoutData[wkKey];
          const days = (wkData && wkData.days) || [];
          for (const day of days) {
            const exList = (day && day.exercises) || [];
            const found = exList.find(ex => (ex.name || ex.exercise) === name);
            if (found && found.target_weight && wkNum >= latestPrescribedWk) {
              latestPrescribedWk = wkNum;
              latestTarget = found.target_weight;
              // reps could be in ex.reps OR parsed from "3x12" in ex.sets
              latestRepsStr = String(found.reps || '');
              if (!latestRepsStr) {
                const setsStr = String(found.sets || '');
                // Match "Nx<reps>" — capture the part AFTER the x
                const m = setsStr.match(/^\d+x(.+)$/);
                latestRepsStr = m ? m[1] : '10';
              }
            }
          }
        }
      }
      if (latestTarget > 0) {
        let r = 10;
        const rs = latestRepsStr.trim();
        if (!rs.endsWith('s')) {
          if (rs.includes('-')) {
            const parts = rs.split('-').map(x => parseInt(x));
            if (parts[0] && parts[1]) r = Math.round((parts[0] + parts[1]) / 2);
          } else {
            const m = rs.match(/(\d+)/);
            if (m) r = parseInt(m[1]);
          }
        }
        prescribedRM = estimate1RM(latestTarget, r);
      }
      const oneRM = Math.max(loggedRM, prescribedRM);
      if (oneRM > 0) est1rm = oneRM;
      const displayVal = est1rm || wt;
      wsRows += `<div class="ws-row-wrap">
  <div class="ws-row" onclick="toggleWeightDetail('${name}', this)">
    <span class="ws-name">${shortName}</span>
    <span class="ws-val">${displayVal} lb ${trendIcon}</span>
  </div>
  <div class="ws-detail" id="ws-detail-${name.replace(/\s/g, '-')}" style="display:none"></div>
</div>`;
    }
    weightSummaryHtml = `<div class="weight-summary" id="weight-summary">
      <button class="weight-summary-toggle" onclick="document.getElementById('weight-summary').classList.toggle('open')">
        Estimated One Rep Max <span class="ws-arrow">\u25BC</span>
      </button>
      <div class="weight-summary-body">${wsRows}</div>
    </div>`;
  }

  // Accordion label for Exercise — "Run" on rest days since that's all it shows
  const exerciseLabel = d.isRest ? 'Run' : 'Exercise';

  panel.innerHTML = `<div class="detail-inner">
    <div class="detail-header">
      <div class="detail-title">Week ${currentWeek} &middot; ${d.day} &mdash; ${liftTitleHtml(d)}</div>
      <div class="detail-meta">
        ${!d.isRest || travelExercises ? `<span class="meta-chip" style="background:var(--lift-bg);border-color:var(--lift-border);color:var(--lift)">${isTraveling ? 'Travel' : 'Lift'} &middot; ${displayExercises.length} exercises</span>` : ''}
        ${(d.run && d.runStatus !== 'unplanned') ? `<span class="meta-chip ${runClass}">${d.run.label} &middot; ${d.run.time}</span>` : `<span class="meta-chip run-unplanned">&#9888; Run not planned</span>`}
      </div>
    </div>
    ${renderAccordion('coach', 'Coach', buildCoachContent(d), true)}
    ${renderAccordion('exercise', exerciseLabel, buildExerciseContent(d, displayExercises, exRows, bwToggleHtml, runClass, isTraveling), true)}
    ${renderAccordion('food', 'Food', buildFoodContent(d), false)}
    ${renderAccordion('stats', 'Stats', buildStatsContent(d, weightSummaryHtml, garminStatsHtml, timingRows, currentDay), false)}
  </div>`;

  panel.classList.add('visible');

  // Init sliders if check-in is present
  initCheckinSliders();

  // Sunday photo previews removed — photos handled by morning flow

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
  return dayData && dayData.mealType && dayData.mealType.toLowerCase().includes('fast');
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
    const _smRes = await fetch('/api/measurements', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (_smRes.status === 403) {
      let _smErr = {};
      try { _smErr = await _smRes.json(); } catch (e) {}
      alert('Measurements can only be recorded on Sundays. Next Sunday: ' + (_smErr.next_sunday_in_days || '?') + ' days.');
      btn.textContent = 'Save Measurements';
      btn.disabled = false;
      return;
    }
    window._measurementsCache = null;
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
  // Measurements handled by morning flow + Stats accordion; photos in morning flow
  return '';
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

// Service worker disabled — cache-busting handled by index.html

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

// ─── WORKOUT SESSION CONTROLLER ───────────────────────────────────────────
function startWorkoutSession() {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData || currentDay === null) return;
  const dayData = weekData.days[currentDay];
  if (!dayData || !dayData.exercises || dayData.exercises.length === 0) return;

  _workoutActive = true;
  _workoutStartTime = new Date().toISOString();
  // Prepend warm-up steps as timed single-set exercises
  const warmupSteps = (dayData.warmup && dayData.warmup.steps) || [];
  const warmupAsExercises = warmupSteps.map(s => ({
    name: s.name,
    sets: '1x' + (s.duration || '30s'),
    rest: '0s',
    note: s.note || '',
    _isWarmup: true,
  }));
  _workoutExercises = [...warmupAsExercises, ...dayData.exercises];
  _workoutExIdx = 0;

  // Go directly into the first exercise (no transition screen)
  enterExerciseFocus(0);
}

function advanceWorkoutSession() {
  if (_advancePending) return;
  _advancePending = true;
  _workoutExIdx++;
  if (_workoutExIdx < _workoutExercises.length) {
    enterExerciseFocus(_workoutExIdx);
    // Reset after a delay to prevent race conditions
    setTimeout(function() { _advancePending = false; }, 1000);
  } else {
    completeWorkoutSession();
    _advancePending = false;
  }
}

async function completeWorkoutSession() {
  var endTime = new Date().toISOString();
  var startMs = new Date(_workoutStartTime).getTime();
  var endMs = new Date(endTime).getTime();
  var durationMin = Math.round((endMs - startMs) / 60000);

  _workoutActive = false;

  // Save duration to backend — await to ensure it lands before navigation
  await apiPost('/api/completions/day', {
    week: currentWeek, day_idx: currentDay,
    workout_started_at: _workoutStartTime,
    workout_ended_at: endTime,
    workout_duration_min: durationMin,
  });

  // Build exercise summary for coach trigger (non-warmup only)
  var exerciseSummaryText = '';
  var swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  var realIdx = 0;
  for (var i = 0; i < _workoutExercises.length; i++) {
    var ex = _workoutExercises[i];
    if (ex._isWarmup) continue;
    var name = swaps[currentWeek + '_' + currentDay + '_' + realIdx] || ex.name;
    realIdx++;
    var exData = getExerciseData(name);
    var wt = exData ? exData.current : 0;
    if (wt > 0) exerciseSummaryText += name + ': ' + wt + 'lb. ';
  }

  var weekData = workoutData[String(currentWeek)];
  var dayData = weekData ? weekData.days[currentDay] : null;
  var workoutName = (dayData && dayData.liftName) || 'workout';

  // Show inline coach chat in the exercise-focus overlay
  var el = document.getElementById('exercise-focus');
  if (!el) return;

  window._liftChatExchanges = 0;

  el.innerHTML =
    '<div class="focus-content" style="max-width:400px;width:100%">' +
      '<div style="font-size:36px;text-align:center;margin-bottom:4px">&#10003;</div>' +
      '<div class="focus-ex-name" style="margin-bottom:4px">Lifting Complete</div>' +
      '<div style="font-family:\'DM Mono\',monospace;font-size:16px;color:var(--accent);text-align:center;margin-bottom:12px">' + durationMin + ' min</div>' +
      '<div id="lift-coach-messages" style="max-height:40vh;overflow-y:auto;padding:8px 0;width:100%">' +
        '<div class="chat-bubble coach" style="background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px"><div class="chat-typing"><span></span><span></span><span></span></div></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:8px;width:100%">' +
        '<input type="text" id="lift-coach-input" placeholder="Reply to Erik..." enterkeyhint="send" ' +
          'onkeydown="if(event.key===\'Enter\')sendLiftCoachMsg()" ' +
          'style="flex:1;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;padding:10px 14px;color:var(--text);font-size:15px;outline:none">' +
        '<button onclick="sendLiftCoachMsg()" style="background:var(--coach);color:#000;border:none;border-radius:8px;padding:10px 16px;font-weight:600;cursor:pointer;font-size:14px">Send</button>' +
      '</div>' +
      '<div id="lift-coach-run-btn-container" style="width:100%;margin-top:12px"></div>' +
    '</div>';
  el.classList.add('visible');

  // Send lifting-complete trigger
  var triggerMsg = '[LIFTING_COMPLETE] ' + workoutName + ' done in ' + durationMin + ' minutes. ' + exerciseSummaryText + 'Give brief post-lifting feedback. Ask how they felt. Be concise.';
  _fetchLiftCoachOpener(triggerMsg);
}

async function _fetchLiftCoachOpener(triggerMsg) {
  var messagesEl = document.getElementById('lift-coach-messages');
  if (!messagesEl) return;
  var bubble = messagesEl.querySelector('.chat-bubble.coach');
  try {
    var res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: triggerMsg }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    if (bubble) bubble.innerHTML = '';
    var fullText = '';
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      var chunk = decoder.decode(result.value, { stream: true });
      var lines = chunk.split('\n');
      var stop = false;
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('data: ')) {
          var data = lines[i].slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          if (bubble) bubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      if (bubble) bubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory && fullText.trim()) {
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    if (bubble) bubble.textContent = 'Nice work! How did the session feel?';
  }
  var input = document.getElementById('lift-coach-input');
  if (input) setTimeout(function() { input.focus(); }, 100);
}

async function sendLiftCoachMsg() {
  var input = document.getElementById('lift-coach-input');
  var text = (input.value || '').trim();
  if (!text) return;
  input.value = '';

  var messagesEl = document.getElementById('lift-coach-messages');
  if (!messagesEl) return;

  // User bubble
  var userBubble = document.createElement('div');
  userBubble.style.cssText = 'background:var(--surface2);border:1px solid var(--border2);border-radius:12px;padding:10px 14px;font-size:14px;line-height:1.5;color:var(--text);margin-bottom:8px;align-self:flex-end;text-align:right';
  userBubble.textContent = text;
  messagesEl.appendChild(userBubble);

  // Typing indicator
  var typingBubble = document.createElement('div');
  typingBubble.className = 'chat-bubble coach';
  typingBubble.style.cssText = 'background:var(--coach-bg);border:1px solid var(--coach-border);border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.6;color:var(--text);margin-bottom:8px';
  typingBubble.innerHTML = '<div class="chat-typing"><span></span><span></span><span></span></div>';
  messagesEl.appendChild(typingBubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  try {
    var res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text }),
    });
    typingBubble.innerHTML = '';
    var fullText = '';
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      var chunk = decoder.decode(result.value, { stream: true });
      var lines = chunk.split('\n');
      var stop = false;
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('data: ')) {
          var data = lines[i].slice(6);
          if (data === '[DONE]') { stop = true; break; }
          if (data.startsWith('[ERROR')) {
            var errMsg = data.replace(/^\[ERROR:?\s*/, '').replace(/\]$/, '').trim();
            fullText += '\n\n[Coach error: ' + errMsg + ']';
            typingBubble.innerHTML = renderCoachMarkdown(fullText);
            stop = true; break;
          }
          fullText += data.replace(/\\n/g, '\n');
          typingBubble.innerHTML = renderCoachMarkdown(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (stop) break;
    }
    if (!fullText.trim()) {
      typingBubble.innerHTML = '<em>(Coach returned an empty response — check server logs)</em>';
    }
    if (_chatHistory) {
      _chatHistory.push({ role: 'user', content: text, date: todayStr() });
      _chatHistory.push({ role: 'assistant', content: fullText, date: todayStr(), time: new Date().toISOString() });
    }
  } catch(e) {
    typingBubble.textContent = 'Connection issue. Try again.';
  }

  window._liftChatExchanges = (window._liftChatExchanges || 0) + 1;

  // After 2+ exchanges, show "Log Your Run" button
  if (window._liftChatExchanges >= 2) {
    var btnContainer = document.getElementById('lift-coach-run-btn-container');
    if (btnContainer && !btnContainer.querySelector('button')) {
      var btn = document.createElement('button');
      btn.className = 'focus-log-btn';
      btn.textContent = 'Log Your Run \u2192';
      btn.onclick = function() {
        exitExerciseFocus();
        // Scroll to the run section
        setTimeout(function() {
          var runSection = document.getElementById('run-section');
          if (runSection) runSection.scrollIntoView({ behavior: 'smooth' });
        }, 300);
      };
      btnContainer.appendChild(btn);
    }
  }

  if (input) input.focus();
}

// ─── EXERCISE FOCUS MODE ───────────────────────────────────────────────────
async function enterExerciseFocus(exIdx) {
  const weekData = workoutData[String(currentWeek)];
  if (!weekData || currentDay === null) return;
  const dayData = weekData.days[currentDay];

  // If in workout session, read from _workoutExercises (includes warm-ups)
  let ex;
  if (_workoutActive && _workoutExercises[exIdx]) {
    ex = _workoutExercises[exIdx];
  } else {
    if (!dayData || !dayData.exercises || !dayData.exercises[exIdx]) return;
    ex = dayData.exercises[exIdx];
  }
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  // Compute real index early for swap key (warmups don't have swap entries)
  let earlyRealIdx = exIdx;
  if (_workoutActive && _workoutExercises) {
    var earlyWarmupCount = _workoutExercises.filter(function(e) { return e._isWarmup; }).length;
    earlyRealIdx = (ex && ex._isWarmup) ? exIdx : exIdx - earlyWarmupCount;
  }
  const swapKey = currentWeek + '_' + currentDay + '_' + earlyRealIdx;
  const displayName = swaps[swapKey] || ex.name;

  const setsMatch = (ex.sets || '').match(/^(\d+)x(.+)/);
  _focusSetCount = setsMatch ? parseInt(setsMatch[1]) : 1;
  _focusTargetReps = setsMatch ? setsMatch[2] : ex.sets;
  _focusRestSec = parseRestSeconds(ex.rest);
  _focusExName = displayName;
  // Height-tracked plyo (Box Jump) is INCHES, not lb — the focus view hardcoded
  // 'lb', contradicting the detail card's 'in'.
  window._focusUnit = (ex.tracked_metric === 'height') ? 'in' : 'lb';
  _focusExIdx = exIdx;
  // Compute the real exercise index (without warmups) for cache/DB keys
  if (_workoutActive && _workoutExercises) {
    var warmupCount = _workoutExercises.filter(function(e) { return e._isWarmup; }).length;
    _focusRealExIdx = ex._isWarmup ? exIdx : exIdx - warmupCount;
  } else {
    _focusRealExIdx = exIdx;
  }

  let suggestion = getWeightForExercise(displayName, currentWeek);
  _focusLastWeight = getLastWeight(displayName);
  // Fallback: swapped exercise with no history → use original
  if (suggestion.weight == null && swaps[swapKey]) {
    suggestion = getWeightForExercise(ex.name, currentWeek);
    if (!_focusLastWeight) _focusLastWeight = getLastWeight(ex.name);
  }
  // Centralized resolver — same target_weight=0-is-bodyweight semantics
  // as the inline session view, plus roundWeight applied to non-zero
  // prescriptions for the focused set's larger inputs.
  _focusWeightVal = resolveDisplayWeight(ex, suggestion, displayName);

  // Fetch adaptive targets from training engine
  try {
      const targetRes = await fetch('/api/targets/' + encodeURIComponent(displayName));
      if (targetRes.ok) {
          const targets = await targetRes.json();
          if (!ex.target_weight) {
              // Coach set NO weight — fall back to the engine's full suggestion.
              if (targets.target_weight) {
                  _focusWeightVal = roundWeight(targets.target_weight, displayName);
              }
              window._focusTargetReps = targets.target_reps || _focusTargetReps;
              _focusTargetReps = window._focusTargetReps;  // sync local variable
              window._focusReason = targets.adjustment_reason || '';
              window._focusIndicator = targets.progression_indicator || 'hold';
          } else {
              // Coach set the weight — keep the coach's reps/why/arrow too, so the
              // explanation and indicator describe the number actually shown (not
              // the engine's value for a different weight).
              window._focusReason = ex.why || ex.adjustment_reason || ex.reason || '';
              window._focusIndicator = '';  // no fabricated arrow over a coach load
          }
      }
  } catch(e) {}

  // Warm-ups always start fresh — don't check _setCache
  // (warm-up indices collide with regular exercise indices in cache)
  const isWarmupEx = ex._isWarmup;
  if (!isWarmupEx) {
    // Carry forward from earlier completed sets in this session
    for (let s = 0; s < (_focusSetCount || 4); s++) {
      const sd = _setCache[`${currentWeek}_${currentDay}_${_focusRealExIdx}_${s}`];
      if (sd && sd.weight) _focusWeightVal = sd.weight;
    }
  }

  // Find first uncompleted set (warm-ups always start at 0)
  _focusSetIdx = 0;
  if (!isWarmupEx) {
    for (let s = 0; s < _focusSetCount; s++) {
      const key = `${currentWeek}_${currentDay}_${_focusRealExIdx}_${s}`;
      if (!_setCache[key] || !_setCache[key].done) {
        _focusSetIdx = s;
        break;
      }
      if (s === _focusSetCount - 1) _focusSetIdx = _focusSetCount; // All done
    }
  }

  // Push history state for back button
  history.pushState({ focus: true }, '');

  renderExerciseFocus();
}

function renderExerciseFocus() {
  const el = document.getElementById('exercise-focus');
  if (!el) return;

  // Check if all sets done → show RPE (skip RPE for warm-ups)
  if (_focusSetIdx >= _focusSetCount) {
    // All sets done — advance or exit (no RPE)
    if (_workoutActive) { advanceWorkoutSession(); } else { exitExerciseFocus(); }
    return;
  }

  const isTimedExercise = typeof _focusTargetReps === 'string' && _focusTargetReps.includes('s');
  const timedSeconds = isTimedExercise ? parseInt(_focusTargetReps) : 0;

  // Build video + note + swap bar (available during exercise, not a separate screen)
  const _videoUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(_focusExName + ' form short')}&sp=EgIYAQ%253D%253D`;
  const _currentEx = _workoutActive ? _workoutExercises[_workoutExIdx] : null;
  const _exNote = _currentEx ? (_currentEx.note || '') : '';
  const _isWu = _currentEx && _currentEx._isWarmup;
  const _escapedFocusName = _focusExName.replace(/'/g, "\\'");
  const _focusInfoBar = `
    <div style="display:flex;gap:10px;justify-content:center;margin-bottom:8px">
      <a href="${_videoUrl}" target="_blank" rel="noopener" style="font-size:13px;color:var(--accent);text-decoration:none">&#9654; Form</a>
      ${!_isWu ? `<button style="font-size:13px;color:var(--muted);background:none;border:1px solid var(--border);border-radius:6px;padding:4px 12px;cursor:pointer" onclick="showExerciseSwap(_focusExIdx,'${_escapedFocusName}',event)">&#128260; Swap</button>` : ''}
    </div>
    ${_exNote ? `<div style="font-size:12px;color:var(--muted);margin-bottom:10px;text-align:center">${escapeHtml(_exNote)}</div>` : ''}`;

  if (isTimedExercise) {
    el.innerHTML = `
      <button class="focus-back" onclick="exitExerciseFocus()">&#8249;</button>
      <div class="focus-content">
        <div class="focus-ex-name">${escapeHtml(_focusExName)}</div>
        <div class="focus-set-counter">${_isWu ? 'WARM-UP' : 'Set ' + (_focusSetIdx + 1) + ' of ' + _focusSetCount}</div>
        ${_focusInfoBar}
        <div style="font-size:48px;font-weight:800;color:var(--accent);font-family:'DM Mono',monospace;margin:16px 0">${timedSeconds}s</div>
        <button class="focus-log-btn" onclick="startTimedSet(${timedSeconds})">START</button>
      </div>`;
    el.classList.add('visible');
  } else {
    // Get saved weight for this set (if previously entered)
    const setKey = `${currentWeek}_${currentDay}_${_focusRealExIdx}_${_focusSetIdx}`;
    const setData = _setCache && _setCache[setKey];
    const wt = setData && setData.weight ? setData.weight : _focusWeightVal;
    const rp = setData && setData.reps ? setData.reps : '';

    el.innerHTML = `
      <button class="focus-back" onclick="exitExerciseFocus()">&#8249;</button>
      <div class="focus-content">
        <div class="focus-ex-name">${escapeHtml(_focusExName)}</div>
        <div class="focus-set-counter">Set ${_focusSetIdx + 1} of ${_focusSetCount}</div>
        ${_focusInfoBar}
        <div style="font-family:'DM Mono',monospace;font-size:18px;color:var(--accent);text-align:center;margin:8px 0">${_focusWeightVal || '?'} ${window._focusUnit || 'lb'} &times; ${_focusTargetReps} reps</div>
        ${_focusLastWeight && _focusLastWeight != _focusWeightVal ? `<div class="focus-last-perf">Last: ${_focusLastWeight} ${window._focusUnit || 'lb'}</div>` : ''}
        ${window._focusReason ? `<div class="focus-reason"><span class="focus-indicator focus-${window._focusIndicator || 'hold'}">${{'up':'↑','hold':'—','deload':'○','weak':'⚑','down':'↓'}[window._focusIndicator] || '—'}</span> ${escapeHtml(window._focusReason)}</div>` : ''}
        <div class="focus-input-group">
          <input class="focus-input" type="number" inputmode="decimal" id="focus-wt" value="${wt}" placeholder="${window._focusUnit || 'lb'}" autofocus>
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
}

function logFocusSet() {
  if (window._focusSaving) return;
  window._focusSaving = true;
  const wtInput = document.getElementById('focus-wt');
  const repsInput = document.getElementById('focus-reps');
  const weight = wtInput ? parseFloat(wtInput.value) || 0 : 0;
  const repsTyped = repsInput ? parseInt(repsInput.value) : 0;
  const reps = repsTyped || parseInt(_focusTargetReps) || 0;

  const key = `${currentWeek}_${currentDay}_${_focusRealExIdx}_${_focusSetIdx}`;
  _setCache[key] = { done: true, weight, reps };

  // Carry weight forward to next set
  if (weight > 0) _focusWeightVal = weight;

  // Save to DB
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  const isSwapped = !!swaps[`${currentWeek}_${currentDay}_${_focusRealExIdx}`];
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
    const _fsd = _setCache[`${currentWeek}_${currentDay}_${_focusRealExIdx}_${s}`];
    if (!_fsd || !_fsd.done) {
      allDone = false; break;
    }
  }

  if (allDone) {
    // Mark exercise complete
    if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
    if (!_completionsCache.exercises) _completionsCache.exercises = {};
    _completionsCache.exercises[`${currentWeek}_${currentDay}_${_focusRealExIdx}`] = true;
    apiPost('/api/completions/exercise', { week: currentWeek, day_idx: currentDay, exercise_idx: _focusRealExIdx });

    // Skip RPE for warm-up exercises
    const currentEx = _workoutActive ? _workoutExercises[_workoutExIdx] : null;
    if (currentEx && currentEx._isWarmup) {
      var wuKey = currentWeek + '_' + currentDay + '_' + _workoutExIdx;
      _warmupCache[wuKey] = true;
      apiPost('/api/warmup-completions', { week: currentWeek, day_idx: currentDay, step_idx: _workoutExIdx });
      if (_workoutActive) {
        advanceWorkoutSession();
      } else {
        exitExerciseFocus();
      }
      return;
    }

    // Last set done — auto-record weight and advance (no RPE)
    _focusSetIdx = _focusSetCount;

    // Gather last weight and reps for ExerciseLog history
    let recWeight = 0;
    let recReps = 0;
    for (let s = 0; s < _focusSetCount; s++) {
      const sd = _setCache[`${currentWeek}_${currentDay}_${_focusRealExIdx}_${s}`];
      if (sd) {
        if (sd.weight > 0) recWeight = sd.weight;
        if (sd.reps > 0) recReps = sd.reps;
      }
    }
    const weekDataRec = workoutData[String(currentWeek)];
    let setsLabelRec = '';
    if (_workoutActive && _workoutExercises[_workoutExIdx]) {
      setsLabelRec = _workoutExercises[_workoutExIdx].sets || '';
    } else if (weekDataRec && weekDataRec.days[currentDay] && weekDataRec.days[currentDay].exercises[_focusRealExIdx]) {
      setsLabelRec = weekDataRec.days[currentDay].exercises[_focusRealExIdx].sets;
    }
    recordWeight(_focusExName, recWeight, setsLabelRec, null, currentWeek, currentDay, null, recReps || null);

    if (_workoutActive) {
      advanceWorkoutSession();
    } else {
      exitExerciseFocus();
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
  setTimeout(function() { window._focusSaving = false; }, 500);
}

let _timedSetPaused = false;

function startTimedSet(seconds) {
  const el = document.getElementById('exercise-focus');
  if (!el) return;

  let remaining = seconds;
  _timedSetPaused = false;

  function render() {
    el.innerHTML = `
      <div class="focus-content">
        <div class="focus-ex-name">${escapeHtml(_focusExName)}</div>
        <div class="focus-set-counter">Set ${_focusSetIdx + 1} of ${_focusSetCount}</div>
        <div class="focus-timer-display${_timedSetPaused ? '' : ''}">${remaining}s</div>
        <button class="focus-skip-btn" onclick="toggleTimedPause()" style="margin-top:12px">${_timedSetPaused ? '&#9654; Resume' : '&#10074;&#10074; Pause'}</button>
      </div>`;
  }

  render();

  if (_focusTimerInterval) clearInterval(_focusTimerInterval);
  _focusTimerInterval = setInterval(() => {
    try {
    if (_timedSetPaused) return; // Skip tick when paused
    remaining--;
    if (remaining > 0) render(); // Render countdown (but not 0 — completion handles that)
    if (remaining <= 0) {
      clearInterval(_focusTimerInterval);
      _focusTimerInterval = null;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);

      // Auto-log this timed set
      const key = `${currentWeek}_${currentDay}_${_focusRealExIdx}_${_focusSetIdx}`;
      _setCache[key] = { done: true, weight: 0, reps: seconds };
      apiPost('/api/sets', {
        exercise: _focusExName, week: currentWeek, day_idx: currentDay,
        set_number: _focusSetIdx, weight: 0, reps: seconds, done: true
      });

      // Check if all sets done
      let allDone = true;
      for (let s = 0; s < _focusSetCount; s++) {
        const _tsd = _setCache[`${currentWeek}_${currentDay}_${_focusRealExIdx}_${s}`];
        if (!_tsd || !_tsd.done) { allDone = false; break; }
      }

      if (allDone) {
        if (!_completionsCache) _completionsCache = { exercises: {}, days: {} };
        if (!_completionsCache.exercises) _completionsCache.exercises = {};
        _completionsCache.exercises[`${currentWeek}_${currentDay}_${_focusRealExIdx}`] = true;
        apiPost('/api/completions/exercise', { week: currentWeek, day_idx: currentDay, exercise_idx: _focusRealExIdx });

        // Skip RPE for warm-up exercises
        const currentEx = _workoutActive ? _workoutExercises[_workoutExIdx] : null;
        if (currentEx && currentEx._isWarmup) {
          var wuKey = currentWeek + '_' + currentDay + '_' + _workoutExIdx;
          _warmupCache[wuKey] = true;
          apiPost('/api/warmup-completions', { week: currentWeek, day_idx: currentDay, step_idx: _workoutExIdx });
          if (_workoutActive) {
            advanceWorkoutSession();
          } else {
            exitExerciseFocus();
          }
          return;
        }

        _focusSetIdx = _focusSetCount;

        // Auto-record weight and advance (no RPE)
        let timedRecWeight = 0;
        let timedRecReps = 0;
        for (let ts = 0; ts < _focusSetCount; ts++) {
          const tsd = _setCache[`${currentWeek}_${currentDay}_${_focusRealExIdx}_${ts}`];
          if (tsd) {
            if (tsd.weight > 0) timedRecWeight = tsd.weight;
            if (tsd.reps > 0) timedRecReps = tsd.reps;
          }
        }
        const timedWeekData = workoutData[String(currentWeek)];
        let timedSetsLabel = '';
        if (_workoutActive && _workoutExercises[_workoutExIdx]) {
          timedSetsLabel = _workoutExercises[_workoutExIdx].sets || '';
        } else if (timedWeekData && timedWeekData.days[currentDay] && timedWeekData.days[currentDay].exercises[_focusRealExIdx]) {
          timedSetsLabel = timedWeekData.days[currentDay].exercises[_focusRealExIdx].sets;
        }
        recordWeight(_focusExName, timedRecWeight, timedSetsLabel, null, currentWeek, currentDay, null, timedRecReps || null);

        if (_workoutActive) {
          advanceWorkoutSession();
        } else {
          exitExerciseFocus();
        }
      } else {
        _focusSetIdx++;
        showFocusRestTimer(_focusRestSec, false); // Show next set after
      }
    }
    } catch(timerErr) { console.error('Timer tick error:', timerErr); }
  }, 1000);
}

function toggleTimedPause() {
  _timedSetPaused = !_timedSetPaused;
  // Re-render to update button text
  const el = document.getElementById('exercise-focus');
  if (el) {
    const btn = el.querySelector('.focus-skip-btn');
    if (btn) btn.innerHTML = _timedSetPaused ? '&#9654; Resume' : '&#10074;&#10074; Pause';
    const timer = el.querySelector('.focus-timer-display');
    if (timer) timer.style.animationPlayState = _timedSetPaused ? 'paused' : 'running';
  }
}

function showFocusRestTimer(seconds, showRpeAfter) {
  const el = document.getElementById('exercise-focus');
  if (!el) return;

  let remaining = seconds;

  function buildContextHtml() {
    let html = '';

    // Previous exercises (completed)
    if (_workoutActive && _workoutExercises) {
      const completedExs = [];
      let completedRealIdx = 0;
      for (let i = 0; i < _workoutExIdx; i++) {
        const ex = _workoutExercises[i];
        const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
        const realKey = ex._isWarmup ? null : completedRealIdx;
        if (!ex._isWarmup) completedRealIdx++;
        const name = (realKey !== null ? swaps[`${currentWeek}_${currentDay}_${realKey}`] : null) || ex.name;
        completedExs.push(`<div style="font-size:12px;color:var(--muted);padding:2px 0">&check; ${escapeHtml(name)}</div>`);
      }
      if (completedExs.length > 0) {
        html += `<div style="margin-bottom:12px;opacity:0.7">${completedExs.join('')}</div>`;
      }
    }

    // Current exercise completed sets
    const completedSets = [];
    for (let s = 0; s < _focusSetIdx; s++) {
      const sd = _setCache[`${currentWeek}_${currentDay}_${_focusRealExIdx}_${s}`];
      if (sd && sd.done) {
        completedSets.push(`<span style="font-size:11px;color:var(--muted)">S${s+1}: ${sd.weight}×${sd.reps}</span>`);
      }
    }
    if (completedSets.length > 0) {
      html += `<div style="font-size:13px;color:var(--text);margin-bottom:4px">${escapeHtml(_focusExName)}</div>`;
      html += `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">${completedSets.join('')}</div>`;
    }

    return html;
  }

  function buildUpcomingHtml() {
    var html = '';

    // Next set info (weight x reps) for current exercise
    if (!showRpeAfter) {
      var nextSetNum = _focusSetIdx + 1;
      var nextWeight = _focusWeightVal;
      // Check if a previous set had a weight logged
      for (var s = _focusSetIdx; s >= 0; s--) {
        var sd = _setCache[currentWeek + '_' + currentDay + '_' + _focusRealExIdx + '_' + s];
        if (sd && sd.weight) { nextWeight = sd.weight; break; }
      }
      if (_focusSetIdx < _focusSetCount) {
        html += '<div style="font-family:\'DM Mono\',monospace;font-size:15px;color:var(--text);margin-top:12px">Next: Set ' + nextSetNum + ' \u2014 ' + nextWeight + ' lb \u00D7 ' + _focusTargetReps + '</div>';
      }
    }

    // Remaining sets for current exercise
    var remainingSets = _focusSetCount - _focusSetIdx;
    if (remainingSets > 0 && !showRpeAfter) {
      html += '<div style="font-size:12px;color:var(--muted);margin-top:12px">' + remainingSets + ' set' + (remainingSets > 1 ? 's' : '') + ' remaining</div>';
    }

    // Coming up exercises
    if (_workoutActive && _workoutExercises) {
      const upcoming = [];
      const startIdx = _workoutExIdx + 1;
      for (let i = startIdx; i < Math.min(_workoutExercises.length, startIdx + 3); i++) {
        const ex = _workoutExercises[i];
        upcoming.push(`<div style="font-size:11px;color:var(--dim);padding:1px 0">${ex.name} · ${ex.sets}</div>`);
      }
      if (upcoming.length > 0) {
        html += `<div style="margin-top:10px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--muted);margin-bottom:4px">Coming up</div>`;
        html += upcoming.join('');
      }
    }

    return html;
  }

  function render() {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    const timeStr = m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;

    el.innerHTML = `
      <div class="focus-content" style="max-width:340px;width:100%">
        ${buildContextHtml()}
        <div class="focus-timer-label">REST</div>
        <div class="focus-timer-display">${timeStr}</div>
        <button class="focus-skip-btn" onclick="skipFocusRest()">Skip Rest &rarr;</button>
        ${buildUpcomingHtml()}
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

      el.innerHTML = `<div class="focus-content"><div class="focus-timer-display focus-timer-done" style="font-size:72px">GO</div></div>`;
      setTimeout(() => {
        renderExerciseFocus();
      }, 1000);
    } else {
      render();
    }
  }, 1000);
}

function skipFocusRest() {
  if (_focusTimerInterval) clearInterval(_focusTimerInterval);
  _focusTimerInterval = null;
  renderExerciseFocus();
}

function showFocusRPE() {
  // No-op: RPE removed from workout flow
}

function submitFocusRPE(rpe) {
  // No-op: RPE removed from workout flow
}

function showExerciseTransition(exIdx) {
  const ex = _workoutExercises[exIdx];
  if (!ex) { completeWorkoutSession(); return; }

  const el = document.getElementById('exercise-focus');
  if (!el) return;

  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  const displayName = swaps[`${currentWeek}_${currentDay}_${exIdx}`] || ex.name;
  const isWarmup = ex._isWarmup;
  const videoUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(displayName + ' form short')}&sp=EgIYAQ%253D%253D`;

  el.innerHTML = `
    <div class="focus-content" style="max-width:380px;width:100%">
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:8px">${isWarmup ? 'WARM-UP' : 'NEXT UP'}</div>
      <div class="focus-ex-name">${escapeHtml(displayName)}</div>
      <div style="font-family:'DM Mono',monospace;font-size:16px;color:var(--muted);margin-bottom:8px">${ex.sets}${ex.rest && ex.rest !== '0s' ? ' \u00B7 ' + ex.rest + ' rest' : ''}</div>
      ${ex.note ? '<div style="font-size:13px;color:var(--muted);margin-bottom:16px">' + escapeHtml(ex.note) + '</div>' : ''}
      <div style="display:flex;gap:10px;margin-bottom:16px;justify-content:center">
        <a href="${videoUrl}" target="_blank" rel="noopener" style="font-size:13px;color:var(--accent);text-decoration:none">&#9654; Form Video</a>
        ${!isWarmup ? `<button style="font-size:13px;color:var(--muted);background:none;border:1px solid var(--border);border-radius:6px;padding:4px 12px;cursor:pointer" onclick="showTransitionSwap(${exIdx},'${displayName.replace(/'/g, "\\'")}')">&#128260; Swap</button>` : ''}
      </div>
      <div id="transition-swap-container"></div>
      <button class="focus-log-btn" onclick="enterExerciseFocus(${exIdx})">LET'S GO</button>
    </div>`;
  el.classList.add('visible');
}

async function showTransitionSwap(exIdx, exerciseName) {
  const container = document.getElementById('transition-swap-container');
  if (!container) return;
  if (container.innerHTML.trim()) { container.innerHTML = ''; return; }
  container.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:4px 0">Loading...</div>';

  // Get original exercise name for alternatives lookup
  const weekData = workoutData[String(currentWeek)];
  const dayData = weekData ? weekData.days[currentDay] : null;
  const liftingIdx = exIdx - ((_workoutExercises || []).filter(e => e._isWarmup).length);
  const originalName = dayData && dayData.exercises && dayData.exercises[liftingIdx] ? dayData.exercises[liftingIdx].name : exerciseName;

  try {
    const res = await fetch('/api/exercise/alternatives/' + encodeURIComponent(originalName));
    const data = await res.json();
    if (!data.alternatives || data.alternatives.length === 0) {
      container.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:4px 0">No alternatives</div>';
      return;
    }
    const altsHtml = data.alternatives.filter(a => a.name !== exerciseName).map(alt =>
      `<div class="swap-option" onclick="transitionSwapTo(${exIdx},'${alt.name.replace(/'/g, "\\'")}')">
        <span class="swap-name">${alt.name}</span>
        <span class="swap-note">${alt.note}</span>
      </div>`
    ).join('');
    container.innerHTML = `<div class="swap-options">${altsHtml}</div>`;
  } catch(e) {
    container.innerHTML = '<div style="color:var(--muted);font-size:13px">Failed to load</div>';
  }
}

function transitionSwapTo(exIdx, newName) {
  // Update the exercise in the workout list
  if (_workoutExercises && _workoutExercises[exIdx]) {
    _workoutExercises[exIdx] = { ..._workoutExercises[exIdx], name: newName, _swapped: true };
  }
  // Save swap
  const swaps = JSON.parse(sessionStorage.getItem('exercise_swaps') || '{}');
  swaps[`${currentWeek}_${currentDay}_${exIdx}`] = newName;
  sessionStorage.setItem('exercise_swaps', JSON.stringify(swaps));
  apiPost('/api/exercise-swap', { week: currentWeek, day_idx: currentDay, exercise_idx: exIdx, swapped_to: newName });
  // Re-show transition with new name
  showExerciseTransition(exIdx);
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
  _focusRealExIdx = null;
  _focusSetIdx = null;
  _workoutActive = false;

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
