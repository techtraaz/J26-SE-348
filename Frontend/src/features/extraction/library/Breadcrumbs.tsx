import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

interface Crumb {
  name: string
  to?: string // the last crumb is where you are: no link
}

const CURRENT = 'text-[15px] font-medium text-ink-h'
const PARENT = 'text-[15px] text-ink-muted hover:text-ink-h'

/** Where you are in the Folders tab: "Folders › Invoices › 2025". */
export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 flex-wrap items-center gap-1">
      {crumbs.map((crumb, index) => {
        const last = index === crumbs.length - 1
        return (
          <span key={`${index}-${crumb.name}`} className="flex min-w-0 items-center gap-1">
            {index > 0 && <ChevronRight size={15} className="shrink-0 text-ink-soft" aria-hidden />}
            {last || !crumb.to ? (
              <span aria-current={last ? 'page' : undefined} className={`truncate ${CURRENT}`}>
                {crumb.name}
              </span>
            ) : (
              <Link to={crumb.to} className={`truncate ${PARENT}`}>
                {crumb.name}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}
