import { useEffect, useRef, useState } from 'react'
import { cn } from '../lib/util'
import { useIsDark } from '../lib/theme'

/* Superficie base. Estilo editorial premium dentro de la marca: hairline cálido,
   sombra casi plana (la profundidad viene del borde + contraste, no de
   drop-shadows), radio 16px. `interactive` agrega un lift sutil al hover. */
export function Card({ className, interactive, ...p }) {
  return (
    <div
      className={cn(
        'bg-white dark:bg-[#1D2016] border border-champagne/50 dark:border-zinc-700/40 rounded-2xl shadow-[0_1px_2px_rgba(44,53,41,0.04)]',
        interactive && 'transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_14px_34px_-18px_rgba(44,53,41,0.20)] hover:border-champagne/70 dark:hover:border-zinc-600/60',
        className,
      )}
      {...p}
    />
  )
}

/* Botones: forma píldora. Primario = slate de marca; el resto, neutros para
   acciones secundarias. */
export function Button({ className, variant = 'primary', ...p }) {
  const variants = {
    primary: 'bg-brand text-white hover:bg-brand-ink shadow-sm',
    accent: 'bg-brand-grad text-white shadow-sm hover:brightness-105',
    soft: 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200',
    ghost: 'text-zinc-600 hover:bg-zinc-100',
  }
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-all duration-150 active:scale-[.97] disabled:opacity-50 disabled:pointer-events-none',
        variants[variant], className,
      )}
      {...p}
    />
  )
}

/* El color viene por prop (hex arbitrario, ej. por etapa) — no es un token
   Tailwind, así que no hereda .dark solo. El fondo es ese color a ~10% alpha
   ('1a'); sobre fondo oscuro casi no se nota, así que en dark subimos a
   ~20% ('33') para que la píldora siga leyéndose como píldora. */
export function Badge({ color = '#71717a', children, className }) {
  const dark = useIsDark()
  return (
    <span className={cn('px-2 py-0.5 rounded-full text-xs font-semibold', className)}
      style={{ background: color + (dark ? '33' : '1a'), color }}>
      {children}
    </span>
  )
}

/* Etiqueta "eyebrow" editorial (uppercase, tracking ancho, pewter) — el rótulo
   pequeño que encabeza secciones y métricas en todo el dashboard. */
export function Eyebrow({ children, className }) {
  return (
    <div className={cn('text-[11px] font-semibold uppercase tracking-[0.13em] text-pewter', className)}>
      {children}
    </div>
  )
}

/* Título de sección: Montserrat display, tracking apretado, slate. Se usa junto
   a <Eyebrow> para el patrón de cabecera consistente en cada página. */
export function SectionTitle({ children, className }) {
  return (
    <div className={cn('font-display font-bold text-lg tracking-tight text-brand', className)}>
      {children}
    </div>
  )
}

export function Input({ className, ...p }) {
  return (
    <input
      className={cn(
        'w-full border border-zinc-200 dark:border-zinc-700/50 bg-white dark:bg-zinc-900/20 rounded-xl px-3 py-2 text-sm outline-none transition',
        'focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 dark:focus:border-gold/40 placeholder:text-zinc-400 dark:placeholder:text-zinc-600',
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
        'border border-zinc-200 dark:border-zinc-700/50 bg-white dark:bg-zinc-900/20 rounded-xl px-3 py-2 text-sm outline-none transition',
        'focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 dark:focus:border-gold/40',
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

/* Estado de carga/error/vacío unificado. Devuelve el elemento del estado, o null si
   los datos están listos. Úsalo como compuerta con early-return (seguro, no crashea):
     const gate = pageState({ isLoading, error, isEmpty, onRetry, skeleton, emptyText })
     if (gate) return gate
*/
export function pageState({ isLoading, error, isEmpty, skeleton, onRetry, emptyText = 'Sin datos.' }) {
  if (isLoading) return skeleton || <div className="py-16 grid place-items-center text-zinc-400"><Spinner /></div>
  if (error) return (
    <div className="py-16 text-center">
      <p className="text-rose-600 font-medium">No se pudo cargar.</p>
      <p className="text-xs text-zinc-400 mt-1 mb-3">{error.message}</p>
      {onRetry && <Button variant="soft" onClick={onRetry}>Reintentar</Button>}
    </div>
  )
  if (isEmpty) return <div className="py-16 text-center text-zinc-400">{emptyText}</div>
  return null
}

/* Dropdown elegante: reemplaza <select> HTML básico. Mantiene el mismo contrato
   (value/onChange) pero con diseño consistente. Úsalo en cards inline. */
export function DropdownSelect({ value, onChange, options, className, 'aria-label': label, ...p }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const selected = options.find((o) => o.value === value)

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    if (open) document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [open])

  return (
    <div ref={ref} className={cn('relative inline-block w-full', className)}>
      <button
        onClick={() => setOpen(!open)}
        aria-label={label}
        className="w-full text-xs border border-zinc-200 dark:border-zinc-700/50 bg-white dark:bg-zinc-900/20 rounded-lg px-2.5 py-1.5 text-zinc-700 dark:text-zinc-300 font-medium flex items-center justify-between gap-2 outline-none hover:border-zinc-300 dark:hover:border-zinc-600/50 focus:ring-2 focus:ring-champagne/40 transition"
      >
        <span className="truncate">{selected?.label || 'Seleccionar'}</span>
        <svg className={cn('w-4 h-4 shrink-0 transition-transform', open && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
        </svg>
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-[#1D2016] border border-champagne/30 dark:border-zinc-700/40 rounded-lg shadow-lg z-10 overflow-hidden">
          {options.map((o) => (
            <button
              key={o.value}
              onClick={() => {
                onChange({ target: { value: o.value } })
                setOpen(false)
              }}
              className={cn(
                'block w-full text-left px-3 py-2 text-xs transition',
                value === o.value
                  ? 'bg-champagne/15 text-brand font-semibold'
                  : 'hover:bg-zinc-100 dark:hover:bg-zinc-800/50 text-zinc-700 dark:text-zinc-300'
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
