import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Sparkles, AlertTriangle, Copy, X, ImageOff } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Badge, Skeleton, Spinner, Eyebrow, SectionTitle } from './ui'
import { Segmented } from './Segmented'
import { WorkspaceSectionHeading } from './WorkspaceHero'
import { fade, surface, staggerDense } from '../lib/motion'

/* Anuncios pagados de Meta: creatividad + resultados de cada anuncio, y
   sugerencias del motor para mejorarlo. Solo lectura: el texto propuesto es
   para copiarlo, nada se publica ni se edita desde aquí. */

const SORTS = [
  { value: 'spend', label: 'Más gasto' },
  { value: 'cpl', label: 'Mejor CPL' },
]
const STATUS = {
  ACTIVE: { l: 'Activo', c: '#16a34a' },
  PAUSED: { l: 'Pausado', c: '#d97706' },
  ARCHIVED: { l: 'Archivado', c: '#94a3b8' },
  DELETED: { l: 'Eliminado', c: '#94a3b8' },
}
const finite = (n) => n != null && Number.isFinite(Number(n))
const num = (n) => (finite(n) ? Math.round(Number(n)).toLocaleString('es-CL') : '—')

// Moneda la trae la API; si el código no es válido, cae a número con el código al lado.
function money(n, currency) {
  if (!finite(n)) return '—'
  const cur = currency || 'CLP'
  try {
    return new Intl.NumberFormat('es-CL', { style: 'currency', currency: cur, maximumFractionDigits: cur === 'CLP' ? 0 : 2 }).format(n)
  } catch {
    return `${Math.round(n).toLocaleString('es-CL')} ${cur}`
  }
}

// Sin leads no hay CPL: esos van al final en cualquier orden.
function sortAds(items, by) {
  const hasLeads = (a) => (a.leads || 0) > 0 && a.cpl != null
  return [...items].sort((a, b) => {
    if (by === 'cpl') {
      if (hasLeads(a) !== hasLeads(b)) return hasLeads(a) ? -1 : 1
      if (hasLeads(a)) return a.cpl - b.cpl
    }
    return (b.spend || 0) - (a.spend || 0)
  })
}

export function PaidAdsPanel({ client, eyebrow }) {
  const [sort, setSort] = useState('spend')
  useEffect(() => { setSort('spend') }, [client])
  const { data, isLoading, error } = useQuery({
    queryKey: ['campaign-ads', client], queryFn: () => api.campaignAds(client), enabled: !!client, retry: false,
  })

  // Un fallo de la API se muestra igual que source="unavailable": vacío, con el
  // motivo. "Not Found" a secas es el 404 de FastAPI para una ruta que no
  // existe; cualquier otro 404 (cliente inexistente) trae su propio detail.
  const unavailable = error
    ? (error.status === 404 && error.message === 'Not Found' ? 'El backend todavía no expone /api/campaigns/ads (HTTP 404).' : error.message)
    : data?.source !== 'live' ? (data?.reason || 'Meta no entregó anuncios para este negocio.') : null
  const items = !unavailable && data ? sortAds(data.items || [], sort) : []
  // El objetivo de CPL solo colorea si la API lo manda; el front no lo inventa.
  const target = typeof data?.target_cpl === 'number' ? data.target_cpl : null

  return (
    <section className="workspace-section">
      <WorkspaceSectionHeading eyebrow={eyebrow} title="Anuncios pagados"
        description="Cada anuncio con su creatividad y sus resultados. Pide sugerencias para mejorar el texto.">
        {items.length > 1 && <Segmented options={SORTS} value={sort} onChange={setSort} />}
      </WorkspaceSectionHeading>
      {isLoading ? (
        <div className="space-y-3">{[0, 1].map((i) => <Skeleton key={i} className="h-36 w-full" />)}</div>
      ) : unavailable ? (
        <motion.div variants={surface} initial="hidden" animate="show">
          <Card className="py-14 px-6 text-center">
            <div className="font-semibold text-zinc-500">Anuncios no disponibles</div>
            <p className="text-sm text-zinc-400 mt-1 break-words max-w-xl mx-auto">{unavailable}</p>
          </Card>
        </motion.div>
      ) : items.length === 0 ? (
        <Card className="py-14 text-center">
          <div className="font-semibold text-zinc-500">Sin anuncios pagados</div>
          <p className="text-sm text-zinc-400 mt-1">Meta respondió, pero esta cuenta no tiene anuncios con gasto.</p>
        </Card>
      ) : (
        <motion.div className="space-y-3" variants={staggerDense()} initial="hidden" animate="show">
          {items.map((ad, i) => (
            <AdCard key={ad.ad_id ?? i} ad={ad} client={client} currency={data.currency} target={target} />
          ))}
        </motion.div>
      )}
    </section>
  )
}

function AdCard({ ad, client, currency, target }) {
  const [open, setOpen] = useState(false)
  const [sug, setSug] = useState(null)
  const [busy, setBusy] = useState(false)
  const cr = ad.creative || {}
  const thumb = cr.thumbnail_url || cr.image_url
  const st = STATUS[ad.status] || { l: ad.status || '—', c: '#94a3b8' }
  const hasLeads = (ad.leads || 0) > 0 && ad.cpl != null
  const cplColor = hasLeads && target != null ? (ad.cpl <= target ? '#16a34a' : '#d97706') : undefined
  const body = cr.body || ''
  const long = body.length > 180

  const suggest = async () => {
    setBusy(true)
    try {
      const r = await api.suggestAd(client, ad.ad_id)
      const list = Array.isArray(r?.sugerencias) ? r.sugerencias : []
      setSug(!r?.diagnostico && list.length === 0 ? { error: 'El motor no devolvió sugerencias.' } : { ok: { diagnostico: r.diagnostico, sugerencias: list } })
    }
    catch (e) { setSug({ error: e.message }) }
    finally { setBusy(false) }
  }

  const metrics = [
    ['Gasto', money(ad.spend, currency)],
    ['Impresiones', num(ad.impressions)],
    ['Clics', num(ad.clicks)],
    ['CTR', finite(ad.ctr) ? `${Number(ad.ctr).toFixed(2)}%` : '—'],
    ['Leads', num(ad.leads)],
    ['CPL', hasLeads ? money(ad.cpl, currency) : '—', cplColor],
  ]

  return (
    <motion.div variants={fade}>
      <Card className="p-5">
        <div className="flex gap-5">
          <div className="w-28 h-28 shrink-0 rounded-xl overflow-hidden border border-zinc-200 bg-zinc-100 grid place-items-center">
            {thumb ? <img src={thumb} alt="" className="w-full h-full object-cover" loading="lazy" />
              : <ImageOff size={20} className="text-zinc-400" aria-label="Sin imagen" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <Eyebrow className="truncate">{ad.campaign_name || '—'}</Eyebrow>
                <div className="font-semibold text-brand mt-1 truncate">{cr.title || ad.ad_name || 'Sin título'}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge color={st.c}>{st.l}</Badge>
                <Button variant="soft" onClick={suggest} disabled={busy}>
                  {busy ? <Spinner /> : <Sparkles size={15} />} {busy ? 'Analizando…' : 'Sugerir mejoras'}
                </Button>
              </div>
            </div>
            {body && (
              <p className="text-sm text-zinc-600 mt-2 whitespace-pre-line">
                {long && !open ? body.slice(0, 180).trimEnd() + '…' : body}
                {long && (
                  <button className="ml-1.5 text-gold-deep font-medium hover:underline" onClick={() => setOpen((v) => !v)}>
                    {open ? 'Ver menos' : 'Ver más'}
                  </button>
                )}
              </p>
            )}
            <div className="grid grid-cols-6 gap-3 mt-4 pt-4 border-t border-zinc-100">
              {metrics.map(([l, v, c]) => (
                <div key={l}>
                  <div className="text-[11px] uppercase tracking-wide text-zinc-400">{l}</div>
                  <div className="text-sm font-semibold tabular-nums mt-0.5" style={c ? { color: c } : undefined}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        {sug && <Suggestions sug={sug} onClose={() => setSug(null)} />}
      </Card>
    </motion.div>
  )
}

function Suggestions({ sug, onClose }) {
  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast.success('Texto copiado') }
    catch { toast.error('No se pudo copiar') }
  }
  return (
    <div className="mt-4 rounded-xl border border-champagne bg-champagne/20 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <SectionTitle className="flex items-center gap-2 text-base"><Sparkles size={15} className="text-gold-deep" /> Sugerencias</SectionTitle>
        <Button variant="ghost" onClick={onClose} aria-label="Cerrar sugerencias"><X size={15} /></Button>
      </div>
      {sug.error ? (
        <div className="text-sm text-amber-800 flex items-start gap-2">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" /><span className="break-words">{sug.error}</span>
        </div>
      ) : (
        <>
          {sug.ok.diagnostico && <p className="text-sm text-zinc-700">{sug.ok.diagnostico}</p>}
          {sug.ok.sugerencias.map((s, i) => (
            <div key={i} className="bg-white dark:bg-zinc-50 rounded-xl border border-zinc-200 p-3">
              <Eyebrow>{s.campo}</Eyebrow>
              <div className="grid grid-cols-2 gap-4 mt-2">
                <div>
                  <div className="text-[11px] text-zinc-400 mb-1">Actual</div>
                  <p className="text-sm text-zinc-500 whitespace-pre-line">{s.actual || '—'}</p>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-[11px] text-zinc-400">Propuesta</div>
                    {s.propuesta && (
                      <button className="text-xs text-gold-deep inline-flex items-center gap-1 hover:underline" onClick={() => copy(s.propuesta)}>
                        <Copy size={12} /> Copiar
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-zinc-800 whitespace-pre-line">{s.propuesta || '—'}</p>
                </div>
              </div>
              {s.por_que && <div className="text-xs text-zinc-500 mt-2 pt-2 border-t border-zinc-100">Por qué: {s.por_que}</div>}
            </div>
          ))}
          <div className="text-[11px] text-zinc-400">Nada se publica ni se edita desde aquí: copia el texto y cámbialo en Meta.</div>
        </>
      )}
    </div>
  )
}
