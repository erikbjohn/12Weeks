/**
 * Load static/app.js into the current JSDOM context and return a handle
 * to the global functions/state defined there.
 *
 * app.js is a 12k-line vanilla-JS file with no module exports — it relies
 * on the browser's globals (window, document, sessionStorage, fetch, etc).
 * Vitest's `jsdom` environment supplies those, so we can read the file as
 * a string and eval it into the test's window via `vm.runInContext` —
 * after which every top-level `function foo() {}` is reachable as a
 * property on `window`.
 *
 * Side-effects in app.js (popstate listener, IIFE setup) all run at load
 * time — but in the JSDOM environment they're harmless.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_JS_PATH = join(__dirname, '..', '..', 'static', 'app.js');

let _loaded = false;

export function loadAppJs() {
  if (_loaded) return window;

  const src = readFileSync(APP_JS_PATH, 'utf8') + `

// === TEST HOOKS (appended by tests/js/load.mjs only) ===
// app.js declares many top-level state vars with \`let\`, which are NOT
// attached to window in eval mode. These hooks close over the let-scoped
// variables so tests can read/seed them from outside.
window.__testHooks = {
  setWeightsCache: (cache) => { _weightsCache = cache; },
  getWeightsCache: () => _weightsCache,
};
`;

  // Stub out browser APIs JSDOM doesn't include but app.js calls.
  if (!window.fetch) {
    window.fetch = () => Promise.reject(new Error('fetch not stubbed in test'));
  }
  if (!window.sessionStorage) {
    const store = new Map();
    window.sessionStorage = {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
      clear: () => store.clear(),
    };
  }

  // Eval into the global scope so top-level `function` declarations land
  // on window (matching browser behavior).
  // eslint-disable-next-line no-eval
  window.eval(src);
  _loaded = true;
  return window;
}
