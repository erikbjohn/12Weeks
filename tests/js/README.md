# JS test scaffold

Lightweight test setup for `static/app.js` — vanilla JS, vitest + jsdom.

## Run

```bash
npm install   # one-time, installs vitest + jsdom into node_modules
npm test      # runs everything in tests/js/**/*.test.mjs
npm run test:watch  # watch mode
```

## How it works

`static/app.js` is a 12k-line vanilla-JS file with no module exports —
top-level `function foo() {}` declarations land on `window` in the
browser. The `loadAppJs()` helper in `tests/js/load.mjs` reads the
file and `window.eval()`s it into the JSDOM `window`, so tests can
call `window.getSuggestedWeight(...)`, `window.isBodyweightExercise(...)`,
etc. directly.

## Adding a test

1. Create `tests/js/my_feature.test.mjs`
2. Import `loadAppJs` from `./load.mjs` and call it in `beforeAll`
3. Seed any global state your function needs (e.g., `window._weightsCache`)
4. Call functions on `window` and assert

## Limitations

- **Pure functions only, easily.** Render functions that touch the
  DOM mutate JSDOM and require manual cleanup between tests. Prefer
  extracting pure logic (like `resolveDisplayWeight`) when adding
  testable code paths.
- **No fetch mocking out of the box.** `window.fetch` is stubbed to
  reject; tests that need it should patch `window.fetch` per-test.
- **Side effects on load.** app.js attaches a `popstate` listener and
  runs IIFEs when loaded. Harmless under JSDOM, but if you load the
  module multiple times, behavior is cached (see `_loaded` flag in
  `load.mjs`).

## Why not Jest / Playwright?

- **Jest:** older, slower, more config. Vitest is the modern default.
- **Playwright:** full browser automation, heavier setup. Better for
  E2E flow tests later, not for unit-testing utility functions.
