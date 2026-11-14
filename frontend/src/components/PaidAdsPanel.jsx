import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Sparkles, AlertTriangle, Copy, X, ImageOff, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Badge, Skeleton, Spinner, Eyebrow, SectionTitle } from './ui'
import { Segmented } from './Segmented'
import { WorkspaceSectionHeading } from './WorkspaceHero'
import { fade, surface, staggerDense } from '../lib/motion'
import { firstOfMonthChile, money, num, finite, VERDICT } from '../lib/ads'

/* Anuncios pagados de Meta: cada anuncio con su veredicto en lenguaje simple,
   lo que costó y cuántas consultas trajo. Las métricas técnicas van plegadas.
   Solo lectura: el texto propuesto es para copiarlo, nada se publica desde aquí. */

const PERIODS = [
  { value: 'month', label: 'Este mes' },
  { value: 'all', label: 'Todo' },
]
const SORTS = [
  { value: 'spend', label: 'Más gasto' },
  { value: 'cpl', label: 'Más baratos' },
]
// La API entrega effective_status en minúsculas ("active"); se normaliza aquí.
const STATUS = {
  ACTIVE: { l: 'Publicado', c: '#16a34a' },
  PAUSED: { l: 'Pausado', c: '#d97706' },
  CAMPAIGN_PAUSED: { l: 'Pausado', c: '#d97706' },
  ADSET_PAUSED: { l: 'Pausado', c: '#d97706' },
  PENDING_REVIEW: { l: 'En revisión', c: '#64748b' },
  DISAPPROVED: { l: 'Rechazado', c: '#e11d48' },
  WITH_ISSUES: { l: 'Con problemas', c: '#e11d48' },
  ARCHIVED: { l: 'Archivado', c: '#94a3b8' },
  DELETED: { l: 'Eliminado', c: '#94a3b8' },
}

// Sin consultas no hay costo por consulta: esos van al final en cualquier orden.
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
  const [period, setPeriod] = useState('all')
  useEffect(() => { setSort('spend'); setPeriod('month') }, [client])
  const since = period === 'month' ? firstOfMonthChile() : undefined
  const { data, isLoading, error } = useQuery({
    queryKey: ['campaign-ads', client, since ?? 'all'], queryFn: () => api.campaignAds(client, since),
    enabled: !!client, retry: false,
  })

  // Un fallo de la API se muestra igual que source="unavailable": vacío, con el
  // motivo. "Not Found" a secas es el 404 de FastAPI para una ruta que no
  // existe; cualquier otro 404 (cliente inexistente) trae su propio detail.
  const unavailable = error
    ? (error.status === 404 && error.message === 'Not Found' ? 'El backend todavía no expone /api/campaigns/ads (HTTP 404).' : error.message)
    : data && data.source !== 'live' ? (data.reason || 'Meta no entregó anuncios para este negocio.') : null
  const items = !unavailable && data ? sortAds(data.items || [], sort) : []
  // El objetivo de costo solo colorea si la API lo manda; el front no lo inventa.
  const target = typeof data?.target_cpl === 'number' ? data.target_cpl : null

  return (
    <section className="workspace-section">
      <WorkspaceSectionHeading eyebrow={eyebrow} title="Tus anuncios"
        description={target != null
          ? `Cada anuncio con su veredicto. «Va bien» = cada consulta te costó ${money(target)} o menos.`
          : 'Cada anuncio con su veredicto, lo que costó y las consultas que trajo.'}>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented options={PERIODS} value={period} onChange={setPeriod} />
          {items.length > 1 && <Segmented options={SORTS} value={sort} onChange={setSort} />}
        </div>
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
          <div className="font-semibold text-zinc-500">{period === 'month' ? 'Sin gasto en anuncios este mes' : 'Sin anuncios pagados'}</div>
          <p className="text-sm text-zinc-400 mt-1">
            {period === 'month' ? 'Revisa «Todo» para ver anuncios de meses anteriores.' : 'Meta respondió, pero esta cuenta no tiene anuncios con gasto.'}
          </p>
        </Card>
      ) : (
        <>
          <motion.div className="space-y-3" variants={staggerDense()} initial="hidden" animate="show">
            {items.map((ad, i) => (
              <AdCard key={ad.ad_id ?? i} ad={ad} client={client} currency={data.currency} target={target} />
            ))}
          </motion.div>
          <p className="text-xs text-zinc-400 mt-3">
            Consultas = personas que iniciaron una conversación de WhatsApp o dejaron sus datos desde el anuncio, según Meta.
          </p>
        </>
      )}
    </section>
  )
}

function AdCard({ ad, client, currency, target }) {
  const [open, setOpen] = useState(false)
  const [showMetrics, setShowMetrics] = useState(false)
  const [sug, setSug] = useState(null)
  const [busy, setBusy] = useState(false)
  const cr = ad.creative || {}
  const thumb = cr.thumbnail_url || cr.image_url
  const statusKey = String(ad.status || '').toUpperCase()
  const st = STATUS[statusKey] || { l: ad.status || '—', c: '#94a3b8' }
  const verdict = VERDICT[ad.verdict?.code]
  const hasLeads = (ad.leads || 0) > 0 && ad.cpl != null
  const body = cr.body || ''
  const long = body.length > 160

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

  // Lo que importa, en tres cifras grandes.
  const main = [
    ['Gastado', money(ad.spend, currency)],
    ['Consultas', num(ad.leads)],
    ['Costo por consulta', hasLeads ? money(ad.cpl, currency) : '—', verdict && hasLeads ? verdict.c : undefined],
  ]
  // El detalle técnico, para quien lo quiera.
  const tech = [
    ['Personas alcanzadas', num(ad.reach)],
    ['Veces mostrado', num(ad.impressions)],
    ['Clics', num(ad.clicks)],
    ['% que hizo clic (CTR)', finite(ad.ctr) ? `${Number(ad.ctr).toFixed(2)}%` : '—'],
  ]

  return (
    <motion.div variants={fade}>
      <Card className="p-5">
        <div className="flex flex-col sm:flex-row gap-5">
          <div className="w-full sm:w-28 h-40 sm:h-28 shrink-0 rounded-xl overflow-hidden border border-zinc-200 bg-zinc-100 grid place-items-center">
            {thumb ? <img src={thumb} alt="" className="w-full h-full object-cover" loading="lazy" />
              : <ImageOff size={20} className="text-zinc-400" aria-label="Sin imagen" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  {verdict && <Badge color={verdict.c}>{verdict.l}</Badge>}
                  <Badge color={st.c}>{st.l}</Badge>
                </div>
                <div className="font-semibold text-brand mt-2 truncate">{cr.title || ad.ad_name || 'Sin título'}</div>
                {ad.campaign_name && <div className="text-xs text-zinc-400 truncate mt-0.5">Campaña: {ad.campaign_name}</div>}
              </div>
              <Button variant="soft" onClick={suggest} disabled={busy}>
                {busy ? <Spinner /> : <Sparkles size={15} />} {busy ? 'Analizando…' : 'Cómo mejorarlo'}
              </Button>
            </div>
            {verdict && <p className="text-sm text-zinc-600 mt-2">{verdict.hint(target, currency)}</p>}
            <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-zinc-100">
              {main.map(([l, v, c]) => (
                <div key={l} className="min-w-0">
                  <div className="text-[11px] uppercase tracking-wide text-zinc-400">{l}</div>
                  <div className="text-lg font-display font-bold tabular-nums mt-0.5 text-brand" style={c ? { color: c } : undefined}>{v}</div>
                </div>
              ))}
            </div>
            <button className="mt-3 text-xs text-zinc-500 hover:text-gold-deep inline-flex items-center gap-1"
              onClick={() => setShowMetrics((v) => !v)} aria-expanded={showMetrics}>
              <ChevronDown size={13} className={'transition-transform ' + (showMetrics ? 'rotate-180' : '')} />
              {showMetrics ? 'Ocultar detalle' : 'Ver texto y métricas'}
            </button>
            {showMetrics && (
              <div className="mt-3 space-y-3">
                {body && (
                  <p className="text-sm text-zinc-600 whitespace-pre-line">
                    {long && !open ? body.slice(0, 160).trimEnd() + '…' : body}
                    {long && (
                      <button className="ml-1.5 text-gold-deep font-medium hover:underline" onClick={() => setOpen((v) => !v)}>
                        {open ? 'Ver menos' : 'Ver más'}
                      </button>
                    )}
                  </p>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {tech.map(([l, v]) => (
                    <div key={l}>
                      <div className="text-[11px] uppercase tracking-wide text-zinc-400">{l}</div>
                      <div className="text-sm font-semibold tabular-nums mt-0.5">{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-2">
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
