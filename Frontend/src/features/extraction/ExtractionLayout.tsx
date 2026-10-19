import { PlugZap, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { EmptyState } from '@/features/extraction/components/EmptyState'
import { C1_CONFIGURED } from '@/features/extraction/config'
import { extractionPaths, isLibraryPath } from '@/features/extraction/paths'

/** Frame for the Component-01 pages inside the main app shell: a search bar
 * above the routed page. Navigation lives in the main shell's tabs. */
export function ExtractionLayout({ configured = C1_CONFIGURED }: { configured?: boolean }) {
  if (!configured) {
    return (
      <div className="min-w-0 flex-1 px-8 py-6">
        <EmptyState
          icon={<PlugZap size={22} />}
          title="Component 01 is not configured"
          description="Set VITE_C1_BASE in the frontend .env (for example http://127.0.0.1:8000) and restart the dev server."
        />
      </div>
    )
  }
  return <ConfiguredLayout />
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
    <div className="flex min-w-0 flex-1 flex-col bg-slate-50 text-slate-900">
      <div className="flex h-14 shrink-0 items-center border-b border-slate-200 bg-white px-8">
        <div className="relative w-full max-w-md">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden />
          <input
            type="search"
            aria-label="Search documents"
            placeholder="Search documents by name"
            value={text}
            onChange={(event) => onChange(event.target.value)}
            className="h-9 w-full rounded-md bg-slate-100 pl-9 pr-8 text-sm placeholder:text-slate-400 focus:bg-white focus:outline-2 focus:outline-indigo-600 [&::-webkit-search-cancel-button]:hidden"
          />
          {text && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                clearTimeout(timer.current)
                applySearch('')
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-400 hover:text-slate-600"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>
      {/* A grid row stretches the page to the full height, so the library's
          drop zone covers the whole area below the search bar. */}
      <div className="grid flex-1">
        <Outlet />
      </div>
    </div>
  )
}
