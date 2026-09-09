import { Calculator, AlertTriangle } from 'lucide-react'

/* Tarjeta de presupuesto: pinta un Quote del backend (líneas + subtotal + IVA + total).
   Los números vienen calculados por el sistema (zero/quotes.py); aquí solo se muestran. */

const clp = (n) => '$' + Math.round(n || 0).toLocaleString('es-CL')

export default function QuoteCard({ quote }) {
  if (!quote?.lines?.length) return null
  const ivaPct = Math.round((quote.iva_rate ?? 0.19) * 100)
  return (
    <div className="inline-block text-left rounded-2xl border border-gold/40 bg-white dark:bg-zinc-50 px-4 py-3 min-w-[250px] max-w-full shadow-sm">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-gold-deep uppercase tracking-wide">
        <Calculator size={12} /> Presupuesto
      </div>
      <div className="mt-2 space-y-1">
        {quote.lines.map((l) => (
          <div key={l.id} className="flex items-baseline justify-between gap-6 text-sm">
            <span className="text-zinc-600 min-w-0">
              {l.qty > 1 ? <b className="text-zinc-700">{l.qty} × </b> : null}{l.name}
            </span>
            <span className="text-zinc-700 tabular-nums shrink-0">{clp(l.subtotal)}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 pt-2 border-t border-zinc-100 space-y-1 text-sm">
        <div className="flex justify-between gap-6 text-zinc-500">
          <span>Subtotal</span><span className="tabular-nums">{clp(quote.subtotal)}</span>
        </div>
        <div className="flex justify-between gap-6 text-zinc-500">
          <span>IVA ({ivaPct}%)</span><span className="tabular-nums">{clp(quote.iva)}</span>
        </div>
        <div className="flex justify-between gap-6 font-semibold text-zinc-800">
          <span>Total</span>
          <span className="tabular-nums">{clp(quote.total)} <span className="text-[10px] font-normal text-zinc-400">{quote.currency || 'CLP'}</span></span>
        </div>
      </div>
      {quote.unmatched?.length > 0 && (
        <div className="flex items-start gap-1.5 text-[11px] text-amber-700 mt-2">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          Sin precio en la lista: {quote.unmatched.join(', ')}
        </div>
      )}
    </div>
  )
}
