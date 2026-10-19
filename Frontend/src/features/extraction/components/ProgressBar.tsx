import clsx from 'clsx'

interface ProgressBarProps {
  /** 0..1. Omit for an indeterminate bar. */
  value?: number
  tone?: 'indigo' | 'green'
  label?: string
}

export function ProgressBar({ value, tone = 'indigo', label }: ProgressBarProps) {
  const indeterminate = value === undefined
  const percent = indeterminate ? 40 : Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : percent}
      className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200"
    >
      <div
        className={clsx(
          'h-full rounded-full transition-[width] duration-300',
          tone === 'green' ? 'bg-green-500' : 'bg-indigo-500',
          indeterminate && 'animate-pulse',
        )}
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}
