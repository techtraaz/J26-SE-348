import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'

interface Crumb {
  id: string
  name: string
}

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-sm">
      <Link
        to={extractionPaths.library}
        className={crumbs.length === 0 ? 'text-xl font-semibold text-slate-900' : 'text-slate-500 hover:text-slate-900'}
      >
        Documents
      </Link>
      {crumbs.map((crumb, index) => {
        const last = index === crumbs.length - 1
        return (
          <span key={crumb.id} className="flex items-center gap-1">
            <ChevronRight size={16} className="text-slate-400" aria-hidden />
            {last ? (
              <span aria-current="page" className="text-xl font-semibold text-slate-900">
                {crumb.name}
              </span>
            ) : (
              <Link to={extractionPaths.folder(crumb.id)} className="text-slate-500 hover:text-slate-900">
                {crumb.name}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}
