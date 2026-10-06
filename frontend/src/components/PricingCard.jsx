import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Calculator, Plus, Trash2, Check } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input, Skeleton } from './ui'
import { losetasCatalog } from './losetas-catalog'

/* Lista de precios de la empresa: con ella el agente arma presupuestos exactos.
   Los números los calcula el sistema (zero/quotes.py), nunca la IA. El server
   normaliza al guardar (descarta filas sin nombre o sin precio > 0) y devuelve
   la lista definitiva — las filas se repueblan desde esa respuesta. */

const toRows = (pricing) => (pricing?.items || []).map((it) => ({
  id: it.id, name: it.name || '', price: String(it.unit_price ?? ''), unit: it.unit || '',
}))
const serialize = (rows) => JSON.stringify(rows.map((r) => [r.name.trim(), r.price, r.unit.trim()]))

// Fotos recibidas del catálogo de Losetas Chile. Los precios siguen viniendo de
// /api/pricing; la imagen se asocia por el ID estable del producto.
const productPhotos = {
  losetaschile: Object.fromEntries(losetasCatalog.map((item) => [item.id, item.image])),
}

export default function PricingCard({ client }) {
  const pricingQ = useQuery({ queryKey: ['pricing', client], queryFn: () => api.pricing(client) })
  const [rows, setRows] = useState([])
  const [currency, setCurrency] = useState('CLP')
  const [ivaPctInput, setIvaPctInput] = useState('19')
  const [loadedFor, setLoadedFor] = useState(null)
  useEffect(() => {
    if (pricingQ.data && pricingQ.data.client !== loadedFor) {
      setRows(toRows(pricingQ.data.pricing))
      setCurrency(pricingQ.data.pricing?.currency || 'CLP')
      setIvaPctInput(String(Math.round((pricingQ.data.pricing?.iva_rate ?? 0.19) * 100)))
      setLoadedFor(pricingQ.data.client)
    }
  }, [pricingQ.data, loadedFor])

  const serverPricing = pricingQ.data?.pricing
  const ivaRate = serverPricing?.iva_rate ?? 0.19
  const ivaPct = Math.round(ivaRate * 100)

  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => api.setPricing(client, {
      currency: currency.trim().toUpperCase() || 'CLP',
      iva_rate: Number(ivaPctInput) / 100,
      items: rows
        .map((r) => ({ ...(r.id ? { id: r.id } : {}), name: r.name.trim(), unit_price: Number(r.price) || 0, unit: r.unit.trim() || null }))
        .filter((it) => it.name && it.unit_price > 0),
    }),
    onSuccess: (d) => {
      const pricing = d.pricing || d
      qc.setQueryData(['pricing', client], { client, pricing })
      qc.invalidateQueries({ queryKey: ['whatsapp-readiness', client] })
      setRows(toRows(pricing))
      setCurrency(pricing.currency)
      setIvaPctInput(String(Math.round(pricing.iva_rate * 100)))
      toast.success(client === 'pooledge'
        ? 'Lista de precios guardada — los presupuestos requieren revisión del despacho'
        : 'Lista de precios guardada — el agente ya cotiza con ella')
    },
    onError: (e) => toast.error('No se pudo guardar: ' + e.message),
  })

  const setRow = (i, patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRow = () => setRows((rs) => [...rs, { name: '', price: '', unit: '' }])
  const dirty = serialize(rows) !== serialize(toRows(serverPricing)) ||
    currency !== (serverPricing?.currency || 'CLP') || ivaPctInput !== String(ivaPct)
  const validRate = ivaPctInput.trim() !== '' && Number.isFinite(Number(ivaPctInput)) &&
    Number(ivaPctInput) >= 0 && Number(ivaPctInput) <= 100

  return (
    <Card className="p-6">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-xl bg-champagne/35 text-gold-deep grid place-items-center shrink-0">
          <Calculator size={17} />
        </div>
        <div>
          <div className="font-semibold leading-tight">Lista de precios</div>
          <div className="text-xs text-zinc-400 mt-0.5">
            {client === 'pooledge'
              ? 'Los precios de producto no habilitan un presupuesto final: faltan despacho y revisión humana.'
              : <>Con esto el agente arma presupuestos exactos — los números los calcula el sistema,
                nunca la IA. Configura el impuesto que corresponde a esta empresa.
                El catálogo de WhatsApp Business no se sincroniza automáticamente: guarda aquí los mismos precios.</>}
          </div>
        </div>
      </div>

      {pricingQ.isLoading ? (
        <div className="space-y-2"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>
      ) : pricingQ.isError ? (
        <div className="text-sm text-rose-600">
          No se pudo cargar. <button className="underline" onClick={() => pricingQ.refetch()}>Reintentar</button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-zinc-600">Moneda
              <Input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 6))} placeholder="CLP" className="mt-1" />
            </label>
            <label className="text-xs text-zinc-600">Impuesto (%)
              <Input value={ivaPctInput} onChange={(e) => setIvaPctInput(e.target.value.replace(/[^\d.]/g, ''))} inputMode="decimal" placeholder="19" className="mt-1" />
            </label>
          </div>
          {rows.length > 0 && (
            <div className="grid grid-cols-[1fr_7rem_5.5rem_2rem] gap-2 text-[11px] text-zinc-400 px-1">
              <span>Producto o servicio</span><span>{ivaRate === 0 ? 'Precio final' : 'Precio neto'}</span><span>Unidad</span><span />
            </div>
          )}
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_7rem_5.5rem_2rem] gap-2 items-center">
              <div className="flex items-center gap-2 min-w-0">
                {productPhotos[client]?.[r.id] && (
                  <a href={productPhotos[client][r.id]} target="_blank" rel="noreferrer"
                    title={`Ver foto de ${r.name}`} className="shrink-0">
                    <img src={productPhotos[client][r.id]} alt={r.name}
                      className="w-10 h-10 rounded-lg object-cover border border-zinc-200" />
                  </a>
                )}
                <Input value={r.name} onChange={(e) => setRow(i, { name: e.target.value })}
                  placeholder="Ej: Sitio web" className="min-w-0" />
              </div>
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
        <Button variant={dirty ? 'accent' : 'soft'} onClick={() => save.mutate()} disabled={pricingQ.isError || pricingQ.isLoading || save.isPending || !dirty || !validRate}>
          {save.isPending ? 'Guardando…' : dirty ? 'Guardar precios' : <><Check size={14} /> Guardada</>}
        </Button>
      </div>
      {client === 'losetaschile' && <LosetasGallery pricing={serverPricing} />}
    </Card>
  )
}

function LosetasGallery({ pricing }) {
  const priced = Object.fromEntries((pricing?.items || []).map((item) => [item.id, item]))
  const clp = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 0 })
  return (
    <section className="mt-6 border-t border-zinc-200 pt-5" aria-label="Fotos de productos Losetas Chile">
      <h3 className="font-semibold text-sm">Fotos de productos</h3>
      <p className="text-xs text-zinc-500 mt-1 mb-3">Los productos sin precio confirmado se muestran para consulta, pero no se cotizan.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {losetasCatalog.map((item) => {
          const price = priced[item.priceId || item.id]
          return <div key={item.id} className="rounded-xl border border-zinc-200 overflow-hidden">
            <a href={item.image} target="_blank" rel="noreferrer" title={`Abrir ficha de ${item.name}`}>
              <img src={item.image} alt={`Ficha de ${item.name}`} loading="lazy"
                className="w-full h-56 object-contain bg-zinc-950" />
            </a>
            <div className="p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="font-medium text-sm">{item.name}</div>
                <span className={'text-xs font-semibold whitespace-nowrap ' + (price ? 'text-green-700' : 'text-amber-700')}>
                  {price ? `${clp.format(price.unit_price)} c/u` : 'Precio pendiente'}
                </span>
              </div>
              <div className="text-xs text-zinc-600 mt-1">{item.size} · espesor {item.thickness}</div>
              <div className="text-xs text-zinc-500 mt-1">{item.features}</div>
            </div>
          </div>
        })}
      </div>
    </section>
  )
}
