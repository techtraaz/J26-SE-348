import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'

interface Crumb {
  id: string
  name: string
}

const CURRENT = 'text-[15px] font-medium text-ink-h'
const PARENT = 'text-[15px] text-ink-muted hover:text-ink-h'

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 flex-wrap items-center gap-1">
      <Link to={extractionPaths.library} className={crumbs.length === 0 ? CURRENT : PARENT}>
        All documents
      </Link>
      {crumbs.map((crumb, index) => {
        const last = index === crumbs.length - 1
        return (
          <span key={crumb.id} className="flex min-w-0 items-center gap-1">
            <ChevronRight size={15} className="shrink-0 text-ink-soft" aria-hidden />
            {last ? (
              <span aria-current="page" className={`truncate ${CURRENT}`}>
                {crumb.name}
              </span>
            ) : (
              <Link to={extractionPaths.folder(crumb.id)} className={`truncate ${PARENT}`}>
                {crumb.name}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}
