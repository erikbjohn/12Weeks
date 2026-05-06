import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/js/**/*.test.mjs'],
    // Don't try to discover Python tests
    exclude: ['node_modules', 'venv', 'tests/coach_audit', 'tests/test_*.py'],
  },
});
