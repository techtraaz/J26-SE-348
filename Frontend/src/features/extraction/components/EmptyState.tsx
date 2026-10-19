import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-line px-6 py-14 text-center">
      <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-surface-muted text-ink-muted">
        {icon}
      </div>
      <h3 className="text-[15px] font-medium text-ink-h">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-[13px] text-ink-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
