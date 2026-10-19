import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Runs e2e/*.test.ts against a REAL Component-01 backend (default http://127.0.0.1:8000).
//   Terminal 1:  uv run fastapi dev app/main.py   (with NOMOS_ENGINE=replay for speed)
//   Terminal 2:  npm run test:e2e
// To use another backend address, set E2E_API_URL.
//
// Uploads use XMLHttpRequest, which jsdom checks against CORS like a browser
// (fetch under Node does not). The test page therefore uses the dev server's
// origin, which the backend allows by default (NOMOS_CORS_ORIGINS).
export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  test: {
    include: ['e2e/**/*.test.ts'],
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
    env: { VITE_C1_BASE: process.env.E2E_API_URL ?? 'http://127.0.0.1:8000' },
    testTimeout: 60_000,
  },
})
