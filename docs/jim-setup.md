# Jim Johnson — Account Setup

## Step 1: Fix Jim's Weight (Erik does this)

Open your browser, log in as admin, open the browser console (Cmd+Option+J), and run:

```javascript
// Set Jim's weight and recompute his plan
fetch('/api/admin/set-weight', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({email: 'johnsonjimc@gmail.com', weight: WEIGHT_HERE})
}).then(r => r.json()).then(d => {
  console.log('Result:', d);
  if (d.recomputed) console.log('Plan recomputed — calories:', d.calories, 'protein:', d.protein);
  else console.log('Weight saved but goal not recomputed. Jim may need to redo onboarding.');
})
```

Replace `WEIGHT_HERE` with Jim's actual weight in lbs (e.g., `195`).

If the response says `recomputed: false` and Jim has no TrainingGoal record yet, he'll need to complete onboarding (Step 3 below) — the weight will already be saved so the plan will compute correctly.

## Step 2: Reset Jim's Password (if not done already)

```javascript
fetch('/api/admin/reset-password', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({email: 'johnsonjimc@gmail.com'})
}).then(r => r.json()).then(d => console.log('Temp password:', d.temp_password))
```

Text Jim the temp password from the console output.

## Step 3: Instructions for Jim

Send Jim this:

---

**Hey Jim — here's how to get set up:**

1. Go to **one2weeks-9ewf.onrender.com** on your phone
2. Log in with:
   - Email: `johnsonjimc@gmail.com`
   - Password: *(the temp password you gave him)*
3. It will walk you through setup — answer the coach's questions honestly
4. When it asks for your weight, enter it accurately (morning weight, no clothes)
5. At the end you'll see **Your Training Plan** with calories, macros, and schedule
6. Pick **"Next Monday"** as your start date
7. After setup, add it to your home screen:
   - **iPhone**: Tap the share button (box with arrow) > "Add to Home Screen"
   - **Android**: Tap the 3-dot menu > "Add to Home Screen"

If anything shows "?" or looks wrong, close the app completely and reopen it.

---
