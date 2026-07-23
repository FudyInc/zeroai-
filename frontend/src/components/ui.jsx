import { useEffect, useRef, useState } from 'react'
import { cn } from '../lib/util'

/* Superficie base. Estilo editorial premium dentro de la marca: hairline cálido,
   sombra casi plana (la profundidad viene del borde + contraste, no de
   drop-shadows), radio 16px. `interactive` agrega un lift sutil al hover. */
export function Card({ className, interactive, ...p }) {
  return (
    <div
      className={cn(
        'bg-white dark:bg-[#1D2016] border border-[#e8e3d9] dark:border-[#2A2E22] rounded-2xl shadow-[0_1px_2px_rgba(44,53,41,0.04)]',
        interactive && 'transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_14px_34px_-18px_rgba(44,53,41,0.20)] hover:border-[#ddd6c6] dark:hover:border-[#3a4030]',
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
   ~20% ('33') para que la píldora siga leyéndose como píldora. Escucha
   'zero-theme-change' (ver ThemeToggle) para reaccionar sin recargar. */
export function Badge({ color = '#71717a', children, className }) {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const onChange = () => setDark(document.documentElement.classList.contains('dark'))
    window.addEventListener('zero-theme-change', onChange)
    return () => window.removeEventListener('zero-theme-change', onChange)
  }, [])
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
        'w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition',
        'focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400',
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
        'border border-zinc-200 rounded-xl px-3 py-2 text-sm bg-white dark:bg-[#1D2016] outline-none transition',
        'focus:ring-4 focus:ring-champagne/40 focus:border-gold/60',
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
