import { useState } from 'react'

import { pageImageUrl } from '@/features/extraction/api/client'
import type { DraftLine, PageOut } from '@/features/extraction/api/types'
import { LineList } from './LineList'
import { PageViewer } from './PageViewer'

interface ReviewWorkspaceProps {
  documentId: string
  pages: PageOut[]
  lines: DraftLine[]
}

/** Split pane: the page with its boxes on the left, the lines on the right.
 * Selecting a box selects its line and vice versa. */
export function ReviewWorkspace({ documentId, pages, lines }: ReviewWorkspaceProps) {
  const [pageNumber, setPageNumber] = useState(pages[0]?.page_number ?? 1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const page = pages.find((p) => p.page_number === pageNumber) ?? pages[0]

  const select = (lineId: string) => {
    const line = lines.find((l) => l.line_id === lineId)
    if (!line) return
    setSelectedId(lineId)
    setPageNumber(line.page) // a line on another page opens that page
  }

  if (!page) return <p className="text-sm text-ink-muted">This document has no pages.</p>

  return (
    // On large screens the workspace fills the window below the page header,
    // and each pane scrolls inside itself.
    <div className="grid gap-4 lg:h-[calc(100vh-23rem)] lg:min-h-128 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="h-[65vh] min-h-0 lg:h-auto">
        <PageViewer
          page={page}
          pageCount={pages.length}
          imageUrl={pageImageUrl(documentId, page.page_number)}
          lines={lines.filter((l) => l.page === page.page_number)}
          selectedId={selectedId}
          onSelect={select}
          onPageChange={setPageNumber}
        />
      </div>
      <div className="h-[50vh] min-h-0 lg:h-auto">
        <LineList lines={lines} selectedId={selectedId} onSelect={select} />
      </div>
    </div>
  )
}
