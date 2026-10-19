import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { configDefaults, defineConfig } from 'vitest/config'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Unit tests mock fetch; this only gives the C1 client an absolute base URL.
    env: { VITE_C1_BASE: 'http://127.0.0.1:8000' },
    // e2e tests need a running backend; run them with `npm run test:e2e`.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
