import { useId } from 'react'
import { motion } from 'framer-motion'

/* Píldora deslizante reutilizable (efecto "Disney+"): el fondo del activo se
   desliza con shared layout. Úsalo donde haya 2–4 opciones excluyentes.

   <Segmented options={[{value,label}]} value={v} onChange={setV} variant="light|dark" />
*/
const VARIANTS = {
  light: { box: 'bg-zinc-100', pill: 'bg-brand-grad shadow', on: 'text-white', off: 'text-zinc-500 hover:text-zinc-700' },
  dark: { box: 'bg-brand-surface shadow-sm', pill: 'bg-brand-grad shadow', on: 'text-white', off: 'text-white/70 hover:text-white' },
}

export function Segmented({ options, value, onChange, variant = 'light', className = '' }) {
  const id = useId()
  const v = VARIANTS[variant] || VARIANTS.light
  return (
    <div className={`inline-flex gap-1 p-1 rounded-full ${v.box} ${className}`}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className="relative px-4 py-1.5 text-sm font-semibold rounded-full outline-none"
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                className={`absolute inset-0 rounded-full ${v.pill}`}
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              />
            )}
            <span className={`relative z-10 transition-colors ${active ? v.on : v.off}`}>{o.label}</span>
          </button>
        )
      })}
    </div>
  )
}
