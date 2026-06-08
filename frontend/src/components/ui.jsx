import { useEffect, useRef, useState } from 'react'
import { cn } from '../lib/util'

export function Card({ className, ...p }) {
  return (
    <div
      className={cn(
        'bg-white border border-zinc-200/70 rounded-2xl shadow-[0_1px_3px_rgba(16,24,40,0.04),0_8px_24px_-12px_rgba(16,24,40,0.08)]',
        className,
      )}
      {...p}
    />
  )
}

export function Button({ className, variant = 'primary', ...p }) {
  const variants = {
    primary: 'bg-zinc-900 text-white hover:bg-zinc-800 shadow-sm',
    accent: 'bg-brand-grad text-white shadow-sm hover:brightness-105',
    soft: 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200',
    ghost: 'text-zinc-600 hover:bg-zinc-100',
  }
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all duration-150 active:scale-[.97] disabled:opacity-50 disabled:pointer-events-none',
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
        'focus:ring-4 focus:ring-emerald-100 focus:border-emerald-300 placeholder:text-zinc-400',
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
        'focus:ring-4 focus:ring-emerald-100 focus:border-emerald-300',
        className,
      )}
      {...p}
    />
  )
}

export function Spinner({ className }) {
  return <span className={cn('inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin', className)} />
}

export function Skeleton({ className }) {
  return <div className={cn('animate-pulse rounded-xl bg-zinc-200/60', className)} />
}

/* Número que sube suavemente (easeOutCubic). */
export function CountUp({ value, prefix = '', duration = 850 }) {
  const target = Number(value) || 0
  const [n, setN] = useState(target)
  const raf = useRef()
  useEffect(() => {
    const start = performance.now()
    const from = 0
    cancelAnimationFrame(raf.current)
    const tick = (t) => {
      const p = Math.min(1, (t - start) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      setN(from + (target - from) * eased)
      if (p < 1) raf.current = requestAnimationFrame(tick)
      else setN(target)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [target, duration])
  return <span>{prefix}{Math.round(n).toLocaleString()}</span>
}

/* Maneja carga / error / vacío de forma robusta y consistente. */
export function DataState({ isLoading, error, isEmpty, skeleton, onRetry, emptyText = 'Sin datos.', children }) {
  if (isLoading) return skeleton || <div className="py-16 grid place-items-center text-zinc-400"><Spinner /></div>
  if (error) return (
    <div className="py-16 text-center">
      <p className="text-rose-600 font-medium">No se pudo cargar.</p>
      <p className="text-xs text-zinc-400 mt-1 mb-3">{error.message}</p>
      {onRetry && <Button variant="soft" onClick={onRetry}>Reintentar</Button>}
    </div>
  )
  if (isEmpty) return <div className="py-16 text-center text-zinc-400">{emptyText}</div>
  return children
}
