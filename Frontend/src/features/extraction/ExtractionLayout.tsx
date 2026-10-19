import { PlugZap, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { EmptyState } from '@/features/extraction/components/EmptyState'
import { C1_CONFIGURED } from '@/features/extraction/config'
import { extractionPaths, isLibraryPath } from '@/features/extraction/paths'

/** Frame for the Component-01 pages inside the main app shell: the page title
 * and search above the routed page. Navigation lives in the main shell's tabs. */
export function ExtractionLayout({ configured = C1_CONFIGURED }: { configured?: boolean }) {
  if (!configured) {
    return (
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader />
        <div className="px-8 pb-12">
          <EmptyState
            icon={<PlugZap size={22} />}
            title="Component 01 is not configured"
            description="Set VITE_C1_BASE in the frontend .env (for example http://127.0.0.1:8000) and restart the dev server."
          />
        </div>
      </div>
    )
  }
  return <ConfiguredLayout />
}

function PageHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4 px-8 pb-6 pt-10">
      <div className="min-w-0">
        <h1 className="heading-serif text-[40px] leading-[1.1]">Your Library</h1>
        <p className="mt-1.5 text-[15px] text-ink-muted">
          Upload documents, follow their extraction and review what was read.
        </p>
      </div>
      {children}
    </header>
  )
}

function ConfiguredLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const urlQuery = params.get('q') ?? ''
  // What the user is typing, until it has been applied to the URL. While null,
  // the box simply shows the URL's query, so navigating (e.g. into a folder)
  // clears it without any syncing effect.
  const [draft, setDraft] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const text = draft ?? urlQuery

  useEffect(() => () => clearTimeout(timer.current), [])

  const applySearch = (value: string) => {
    const next = new URLSearchParams(location.search)
    if (value.trim()) next.set('q', value)
    else next.delete('q')
    // Search always lives on the library page.
    const pathname = isLibraryPath(location.pathname) ? location.pathname : extractionPaths.library
    void navigate({ pathname, search: next.toString() }, { replace: true })
    setDraft(null)
  }

  const onChange = (value: string) => {
    setDraft(value)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => applySearch(value), 250)
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader>
        <div className="relative w-full sm:w-72">
          <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-soft" aria-hidden />
          <input
            type="search"
            aria-label="Search documents"
            placeholder="Search documents by name"
            value={text}
            onChange={(event) => onChange(event.target.value)}
            className="h-10 w-full rounded-full border border-line bg-input pl-10 pr-9 text-sm text-ink-h placeholder:text-ink-soft focus:border-ink-muted focus:bg-surface focus:outline-none focus:ring-4 focus:ring-primary/10 [&::-webkit-search-cancel-button]:hidden"
          />
          {text && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                clearTimeout(timer.current)
                applySearch('')
              }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-ink-soft hover:text-ink-h"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </PageHeader>
      {/* A grid row stretches the page to the full height, so the library's
          drop zone covers the whole area below the search bar. grid-cols-1 is a
          minmax(0, 1fr) track: wide content (the table) scrolls inside its own
          box instead of widening the page. */}
      <div className="grid min-w-0 flex-1 grid-cols-1">
        <Outlet />
      </div>
    </div>
  )
}
