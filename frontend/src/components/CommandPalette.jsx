import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ArrowRight, Building2, CornerDownLeft } from 'lucide-react'
import { cn } from '../lib/util'

/* Buscador rápido (Cmd/Ctrl+K): salta entre páginas y cambia de cliente sin
   tocar el mouse — útil cuando el equipo maneja varias cuentas. Mismo patrón
   visual que el resto de los modales (backdrop + spring), sin buscador de
   leads todavía: eso necesitaría un endpoint cross-cliente que hoy no existe. */
export default function CommandPalette({ open, onClose, pages, clients, currentClient, onNavigate, onSelectClient }) {
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) { setQ(''); setActive(0); setTimeout(() => inputRef.current?.focus(), 30) }
  }, [open])

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const pageItems = pages
      .filter((p) => !needle || p.label.toLowerCase().includes(needle))
      .map((p) => ({ kind: 'page', key: 'p:' + p.path, label: p.label, path: p.path }))
    const clientItems = (clients || [])
      .filter((c) => !needle || c.toLowerCase().includes(needle))
      .map((c) => ({ kind: 'client', key: 'c:' + c, label: c }))
    return [...pageItems, ...clientItems]
  }, [q, pages, clients])

  useEffect(() => { setActive(0) }, [q])

  const choose = (item) => {
    if (!item) return
    if (item.kind === 'page') onNavigate(item.path)
    else onSelectClient(item.label)
    onClose()
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, items.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); choose(items[active]) }
    else if (e.key === 'Escape') onClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-start justify-center p-4 pt-[12vh]"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div className="bg-white rounded-2xl max-w-lg w-full overflow-hidden shadow-2xl"
            initial={{ opacity: 0, scale: 0.96, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }} transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2.5 px-4 border-b border-zinc-100">
              <Search size={16} className="text-zinc-400 shrink-0" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Ir a una página o cambiar de cliente…"
                className="flex-1 py-3.5 text-sm outline-none placeholder:text-zinc-400"
              />
              <kbd className="text-[10px] text-zinc-400 border border-zinc-200 rounded px-1.5 py-0.5 shrink-0">esc</kbd>
            </div>

            <div className="max-h-80 overflow-y-auto p-2">
              {items.length === 0 && (
                <div className="text-sm text-zinc-400 text-center py-8">Sin resultados.</div>
              )}
              {items.map((item, i) => (
                <button
                  key={item.key}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(item)}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-left transition-colors',
                    i === active ? 'bg-champagne/25 text-brand' : 'text-zinc-600 hover:bg-zinc-50',
                  )}
                >
                  {item.kind === 'page'
                    ? <ArrowRight size={15} className={i === active ? 'text-gold-deep' : 'text-zinc-400'} />
                    : <Building2 size={15} className={i === active ? 'text-gold-deep' : 'text-zinc-400'} />}
                  <span className="flex-1 truncate capitalize">{item.label}</span>
                  {item.kind === 'client' && item.label === currentClient && (
                    <span className="text-[10px] font-semibold text-gold-deep bg-champagne/40 px-1.5 py-0.5 rounded-full shrink-0">actual</span>
                  )}
                  {i === active && <CornerDownLeft size={13} className="text-zinc-300 shrink-0" />}
                </button>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
