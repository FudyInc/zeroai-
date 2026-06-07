import { cn } from '../lib/util'

export function Card({ className, ...p }) {
  return <div className={cn('bg-white border border-zinc-200/80 rounded-2xl shadow-sm', className)} {...p} />
}

export function Button({ className, variant = 'primary', ...p }) {
  const variants = {
    primary: 'bg-zinc-900 text-white hover:bg-zinc-800',
    accent: 'bg-emerald-700 text-white hover:bg-emerald-800',
    soft: 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200',
    ghost: 'text-zinc-600 hover:bg-zinc-100',
  }
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all active:scale-[.97] disabled:opacity-50 disabled:pointer-events-none',
        variants[variant], className,
      )}
      {...p}
    />
  )
}

export function Badge({ color = '#71717a', children, className }) {
  return (
    <span className={cn('px-2 py-0.5 rounded-full text-xs font-semibold', className)}
      style={{ background: color + '1a', color }}>
      {children}
    </span>
  )
}

export function Input({ className, ...p }) {
  return (
    <input
      className={cn(
        'w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition',
        'focus:ring-2 focus:ring-emerald-200 focus:border-emerald-300 placeholder:text-zinc-400',
        className,
      )}
      {...p}
    />
  )
}

export function Select({ className, ...p }) {
  return (
    <select
      className={cn(
        'border border-zinc-200 rounded-xl px-3 py-2 text-sm bg-white outline-none transition',
        'focus:ring-2 focus:ring-emerald-200 focus:border-emerald-300',
        className,
      )}
      {...p}
    />
  )
}

export function Spinner({ className }) {
  return (
    <span className={cn('inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin', className)} />
  )
}
