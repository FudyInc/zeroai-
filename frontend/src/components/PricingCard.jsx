import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Calculator, Plus, Trash2, Check } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input, Skeleton } from './ui'

/* Lista de precios de la empresa: con ella el agente arma presupuestos exactos.
   Los números los calcula el sistema (zero/quotes.py), nunca la IA. El server
   normaliza al guardar (descarta filas sin nombre o sin precio > 0) y devuelve
   la lista definitiva — las filas se repueblan desde esa respuesta. */

const toRows = (pricing) => (pricing?.items || []).map((it) => ({
  id: it.id, name: it.name || '', price: String(it.unit_price ?? ''), unit: it.unit || '',
}))
const serialize = (rows) => JSON.stringify(rows.map((r) => [r.name.trim(), r.price, r.unit.trim()]))

export default function PricingCard({ client }) {
  const pricingQ = useQuery({ queryKey: ['pricing', client], queryFn: () => api.pricing(client) })
  const [rows, setRows] = useState([])
  const [loadedFor, setLoadedFor] = useState(null)
  useEffect(() => {
    if (pricingQ.data && pricingQ.data.client !== loadedFor) {
      setRows(toRows(pricingQ.data.pricing))
      setLoadedFor(pricingQ.data.client)
    }
  }, [pricingQ.data, loadedFor])

  const serverPricing = pricingQ.data?.pricing
  const ivaRate = serverPricing?.iva_rate ?? 0.19
  const ivaPct = Math.round(ivaRate * 100)

  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => api.setPricing(client, {
      currency: serverPricing?.currency || 'CLP',
      iva_rate: ivaRate,
      items: rows
        .map((r) => ({ ...(r.id ? { id: r.id } : {}), name: r.name.trim(), unit_price: Number(r.price) || 0, unit: r.unit.trim() || null }))
        .filter((it) => it.name && it.unit_price > 0),
    }),
    onSuccess: (d) => {
      const pricing = d.pricing || d
      qc.setQueryData(['pricing', client], { client, pricing })
      setRows(toRows(pricing))
      toast.success('Lista de precios guardada — el agente ya cotiza con ella')
    },
    onError: (e) => toast.error('No se pudo guardar: ' + e.message),
  })

  const setRow = (i, patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRow = () => setRows((rs) => [...rs, { name: '', price: '', unit: '' }])
  const dirty = serialize(rows) !== serialize(toRows(serverPricing))

  return (
    <Card className="p-6">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-xl bg-champagne/35 text-gold-deep grid place-items-center shrink-0">
          <Calculator size={17} />
        </div>
        <div>
          <div className="font-semibold leading-tight">Lista de precios</div>
          <div className="text-xs text-zinc-400 mt-0.5">
            Con esto el agente arma presupuestos exactos — los números los calcula el sistema,
            nunca la IA. Precios sin IVA: el {ivaPct}% se agrega al cotizar.
          </div>
        </div>
      </div>

      {pricingQ.isLoading ? (
        <div className="space-y-2"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>
      ) : (
        <div className="space-y-2">
          {rows.length > 0 && (
            <div className="grid grid-cols-[1fr_7rem_5.5rem_2rem] gap-2 text-[11px] text-zinc-400 px-1">
              <span>Producto o servicio</span><span>Precio neto</span><span>Unidad</span><span />
            </div>
          )}
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_7rem_5.5rem_2rem] gap-2 items-center">
              <Input value={r.name} onChange={(e) => setRow(i, { name: e.target.value })}
                placeholder="Ej: Sitio web" />
              <Input value={r.price} onChange={(e) => setRow(i, { price: e.target.value.replace(/[^\d]/g, '') })}
                inputMode="numeric" placeholder="250000" className="tabular-nums" />
              <Input value={r.unit} onChange={(e) => setRow(i, { unit: e.target.value })}
                placeholder="unidad" />
              <button onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                className="text-zinc-300 hover:text-rose-500 transition-colors grid place-items-center"
                title="Quitar de la lista">
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          {rows.length === 0 && (
            <div className="text-xs text-zinc-400 rounded-xl bg-zinc-50 px-3 py-2.5">
              Sin precios todavía — el agente responderá dudas pero no podrá cotizar.
            </div>
          )}
          <Button variant="ghost" onClick={addRow} className="px-2 py-1 text-xs">
            <Plus size={14} /> Agregar ítem
          </Button>
        </div>
      )}

      <div className="flex items-center justify-between mt-2">
        <span className="text-[11px] text-zinc-400">
          {rows.length > 0 ? 'Las filas sin nombre o sin precio no se guardan.' : ''}
        </span>
        <Button variant={dirty ? 'accent' : 'soft'} onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
          {save.isPending ? 'Guardando…' : dirty ? 'Guardar precios' : <><Check size={14} /> Guardada</>}
        </Button>
      </div>
    </Card>
  )
}
