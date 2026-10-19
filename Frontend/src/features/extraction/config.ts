import { env } from '@/config/env'

// Base URL of the Component-01 API (VITE_C1_BASE). Empty means C1 is not
// configured: the extraction pages say so instead of calling a wrong address.
export const API_BASE_URL: string = env.c1Base
export const C1_CONFIGURED = Boolean(API_BASE_URL)

// Mirrors the backend limit (the backend stays authoritative); this only lets
// the UI reject an oversized file before uploading it.
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024

// File types the backend ingests (it checks the real content, not the name).
export const ACCEPTED_TYPES: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'image/png': ['.png'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/tiff': ['.tif', '.tiff'],
  'image/bmp': ['.bmp'],
  'image/webp': ['.webp'],
}

// How often to re-fetch while any document is still being processed.
export const POLL_INTERVAL_MS = 2000
