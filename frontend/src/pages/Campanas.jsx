import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { DollarSign, Users, Target, Settings2, MapPin, Sparkles, TrendingUp, AlertTriangle, X } from 'lucide-react'
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from 'recharts'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, CountUp, Skeleton, Button, Badge, Input, Spinner, pageState, Eyebrow, SectionTitle } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'
import { rise, fade, surface, stagger, staggerDense } from '../lib/motion'
import { WorkspaceHero, WorkspaceSectionHeading } from '../components/WorkspaceHero'
import { PaidAdsPanel } from '../components/PaidAdsPanel'

const FILTERS = [
  { value: 'todas', label: 'Todas' },
  { value: 'active', label: 'Activas' },
  { value: 'paused', label: 'Pausadas' },
]
const OBJ = { OUTCOME_LEADS: 'Leads', OUTCOME_TRAFFIC: 'Tráfico', OUTCOME_AWARENESS: 'Awareness' }
// [encabezado, ¿numérica?] — las numéricas se alinean a la derecha para leer en columna.
const COLS = [['Campaña'], ['Objetivo'], ['Zona'], ['Estado'], ['Presupuesto', 1], ['Gastado', 1], ['Leads', 1], ['CPL', 1], ['Creada']]
const clp = (n) => '$' + Math.round(n || 0).toLocaleString('es-CL')

// "hace X" relativo — tolera campañas sin created_at (mock aún no lo trae).
function timeAgo(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days <= 0) return 'hoy'
  if (days === 1) return 'hace 1 día'
  if (days < 30) return `hace ${days} días`
  const months = Math.floor(days / 30)
  if (months < 12) return `hace ${months} ${months === 1 ? 'mes' : 'meses'}`
  const years = Math.floor(months / 12)
  return `hace ${years} ${years === 1 ? 'año' : 'años'}`
}

// Leads por objetivo — agregación real de las campañas actuales (sin inventar datos).
function byObjective(campaigns) {
  const m = new Map()
  for (const c of campaigns) {
    const k = OBJ[c.objective] || c.objective || '—'
    m.set(k, (m.get(k) || 0) + (c.leads || 0))
  }
  return [...m.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
}

export default function Campanas() {
  const { client } = useApp()
  const qc = useQueryClient()
  const [filter, setFilter] = useState('todas')
  const [showCfg, setShowCfg] = useState(false)
  const [opt, setOpt] = useState(null)
  const [optBusy, setOptBusy] = useState(false)
  const [syncBusy, setSyncBusy] = useState(false)
  useEffect(() => { setShowCfg(false); setOpt(null); setFilter('todas') }, [client])
  const optimize = async () => {
    setOptBusy(true)
    try { setOpt(await api.optimizeCampaigns(client)) }
    catch (e) { toast.error('No se pudo optimizar: ' + e.message) }
    finally { setOptBusy(false) }
  }
  const syncLeads = async () => {
    const selectedClient = client
    setSyncBusy(true)
    try {
      const result = await api.syncAdLeads(selectedClient)
      qc.invalidateQueries({ queryKey: ['leads', selectedClient] })
      qc.invalidateQueries({ queryKey: ['board', selectedClient] })
      qc.invalidateQueries({ queryKey: ['kpis', selectedClient] })
      toast.success(`${result.imported} respuestas de formularios Meta importadas para ${selectedClient}`)
    } catch (e) { toast.error('No se pudo importar: ' + e.message) }
    finally { setSyncBusy(false) }
  }
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['campaigns', client], queryFn: () => api.campaigns(client), enabled: !!client,
  })
  if (!client) return <NoClient />

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    skeleton: (
      <div className="space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
        <Skeleton className="h-64 w-full" />
      </div>
    ),
  })
  if (gate) return gate
  const { campaigns, summary, daily_spend = [] } = data
  const trend = daily_spend.map((d) => ({ name: new Date(`${d.date}T12:00:00`).toLocaleDateString('es-CL', { weekday: 'short' }), spent: d.spent_clp }))
  const rows = filter === 'todas' ? campaigns : campaigns.filter((c) => c.status === filter)
  const cplOk = !!summary.cpl_clp && summary.cpl_clp <= summary.good_cpl_clp
  const cards = [
    { l: 'Gastado (mes)', v: clp(summary.spent_clp), icon: DollarSign, tone: 'gold' },
    { l: 'Leads de ads', v: summary.leads, icon: Users, tone: 'slate' },
    {
      l: 'CPL promedio', v: summary.cpl_clp ? clp(summary.cpl_clp) : '—', icon: Target, tone: 'slate',
      note: summary.good_cpl_clp ? { text: `Objetivo Chile ≤ ${clp(summary.good_cpl_clp)}`, color: summary.cpl_clp ? (cplOk ? '#16a34a' : '#d97706') : null } : null,
    },
  ]
  const live = summary.source === 'live'
  const hasTrend = campaigns.length > 0 && daily_spend.length > 0

  return (
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={surface}>
        <WorkspaceHero eyebrow="Meta Ads" title="Campañas"
          description="Revisa inversión, resultados y campañas del negocio seleccionado. Importa las respuestas de formularios y gestiona el plan desde aquí."
          icon={Target}
          aside={{ label: 'Campañas activas', value: summary.active, detail: `${campaigns.length} campañas registradas` }}>
          <Button variant="accent" onClick={optimize} disabled={optBusy || campaigns.length === 0}
            title={campaigns.length === 0 ? 'Necesitas al menos una campaña para generar un plan' : undefined}>
            {optBusy ? <Spinner /> : <Sparkles size={15} />} {optBusy ? 'Analizando…' : 'Generar plan con IA'}
          </Button>
          <Button variant="soft" onClick={syncLeads} disabled={syncBusy}>
            {syncBusy ? <Spinner /> : <Users size={15} />}
            {syncBusy ? 'Importando…' : 'Importar formularios'}
          </Button>
          <Button variant="soft" onClick={() => setShowCfg((v) => !v)} aria-expanded={showCfg}>
            <Settings2 size={15} /> {showCfg ? 'Cerrar configuración' : 'Configurar cuenta'}
          </Button>
        </WorkspaceHero>
      </motion.div>

      {(optBusy || summary.error || showCfg || opt) && (
        <section className="workspace-section">
          {optBusy && (
            <motion.div variants={fade} initial="hidden" animate="show">
              <Card className="p-4 border-champagne bg-champagne/20 text-sm text-gold-deep flex items-center gap-2">
                <Spinner /> Analizando las campañas y preparando el plan…
              </Card>
            </motion.div>
          )}
          {summary.error && (
            <motion.div variants={fade}>
              <Card className="p-4 border-amber-200 bg-amber-50/70 text-sm text-amber-800 flex items-start gap-3">
                <AlertTriangle size={17} className="shrink-0 mt-0.5" />
                <div className="min-w-0">
                  Meta no respondió. Revisa el token y la cuenta de este negocio en <b>Configuración → Meta Ads</b>.
                  <div className="text-xs text-amber-700/80 mt-1 break-words">{summary.error}</div>
                </div>
              </Card>
            </motion.div>
          )}
          {showCfg && <ClientConfig key={client} client={client} onClose={() => setShowCfg(false)} />}
          {opt && <OptimizePanel opt={opt} onClose={() => setOpt(null)} />}
        </section>
      )}

      <section className="workspace-section">
        <WorkspaceSectionHeading eyebrow="01 / Rendimiento" title="Resumen del mes"
          description="Inversión y captación registradas en Meta Ads.">
          <Badge color={live ? '#16a34a' : '#94a3b8'}>{live ? 'Meta conectado' : 'Meta sin conectar'}</Badge>
        </WorkspaceSectionHeading>
        <motion.div className="grid grid-cols-1 sm:grid-cols-3 gap-4" variants={stagger()} initial="hidden" animate="show">
          {cards.map((c) => {
            const chip = c.tone === 'gold' ? 'bg-champagne/25 text-gold-deep border-champagne/60' : 'bg-brand/[0.05] text-brand/90 border-brand/10'
            return (
              <motion.div key={c.l} variants={surface}>
                <Card interactive className="p-5 flex items-start justify-between h-full">
                  <div className="min-w-0">
                    <Eyebrow>{c.l}</Eyebrow>
                    <div className="text-[28px] leading-none font-display font-extrabold tracking-tight text-brand mt-2.5 tabular-nums">{typeof c.v === 'number' ? <CountUp value={c.v} /> : c.v}</div>
                    {c.note && (
                      <div className="text-xs mt-2.5 flex items-center gap-1.5 text-zinc-500">
                        {c.note.color && <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: c.note.color }} aria-hidden />}
                        {c.note.text}
                      </div>
                    )}
                  </div>
                  <div className={'w-10 h-10 rounded-xl grid place-items-center border shrink-0 ' + chip}>
                    <c.icon size={18} />
                  </div>
                </Card>
              </motion.div>
            )
          })}
        </motion.div>
      </section>

      <PaidAdsPanel client={client} eyebrow="02 / Anuncios" />

      {hasTrend && (
        <section className="workspace-section">
          <WorkspaceSectionHeading eyebrow="03 / Evolución" title="Tendencias"
            description="Gasto diario y distribución de leads por objetivo." />
          <motion.div className="grid grid-cols-1 lg:grid-cols-3 gap-4" variants={stagger()} initial="hidden" animate="show">
            <motion.div className="lg:col-span-2" variants={surface}>
              <Card className="p-5 h-full">
                <SectionTitle className="flex items-center gap-2 mb-1"><TrendingUp size={16} className="text-gold-deep" /> Gasto diario</SectionTitle>
                <div className="text-xs text-zinc-400 mb-3">Últimos 7 días, en CLP.</div>
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trend} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                      <defs>
                        <linearGradient id="spentFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#C9A45C" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#C9A45C" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid vertical={false} stroke="var(--color-zinc-100)" />
                      <XAxis dataKey="name" tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} />
                      <YAxis hide />
                      <Tooltip cursor={{ stroke: '#C9A45C', strokeWidth: 1 }}
                        contentStyle={{ borderRadius: 12, border: '1px solid var(--color-zinc-200)', fontSize: 13, background: 'var(--color-zinc-50)' }}
                        labelStyle={{ color: 'var(--color-zinc-700)' }}
                        formatter={(v) => [clp(v), 'Gasto']} />
                      <Area type="monotone" dataKey="spent" stroke="var(--color-gold-deep)" strokeWidth={2} fill="url(#spentFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            </motion.div>

            <motion.div variants={surface}>
              <Card className="p-5 h-full">
                <SectionTitle className="mb-1">Leads por objetivo</SectionTitle>
                <div className="text-xs text-zinc-400 mb-3">Leads del mes según el objetivo de la campaña.</div>
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={byObjective(campaigns)} layout="vertical" margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid horizontal={false} stroke="var(--color-zinc-100)" />
                      <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} width={78} />
                      <Tooltip cursor={{ fill: 'var(--color-zinc-100)' }}
                        contentStyle={{ borderRadius: 12, border: '1px solid var(--color-zinc-200)', fontSize: 13, background: 'var(--color-zinc-50)' }}
                        labelStyle={{ color: 'var(--color-zinc-700)' }}
                        formatter={(v) => [v, 'Leads']} />
                      <Bar dataKey="value" radius={[0, 8, 8, 0]} maxBarSize={28} fill="var(--color-brand)" animationDuration={700} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            </motion.div>
          </motion.div>
        </section>
      )}

      <section className="workspace-section">
        <WorkspaceSectionHeading eyebrow={hasTrend ? '04 / Detalle' : '03 / Detalle'} title="Campañas registradas"
          description="Estado, presupuesto y resultados de cada campaña.">
          {campaigns.length > 0 && <Segmented options={FILTERS} value={filter} onChange={setFilter} />}
        </WorkspaceSectionHeading>
        {campaigns.length === 0 ? (
          <motion.div variants={surface}>
            <Card className="py-16 text-center">
              <img src="/logo-mark.png" alt="" className="w-12 h-12 mx-auto mb-4 grayscale opacity-25" />
              {summary.source === 'sin_datos' ? (
                <>
                  <div className="font-semibold text-zinc-500">Sin datos de Meta para este negocio</div>
                  <p className="text-sm text-zinc-400 mt-1">Asigna su cuenta publicitaria en <b>Configurar cuenta</b> para ver campañas reales.</p>
                </>
              ) : (
                <>
                  <div className="font-semibold text-zinc-500">No hay campañas activas</div>
                  <p className="text-sm text-zinc-400 mt-1">Cuando la cuenta de Meta tenga campañas, su rendimiento aparecerá aquí.</p>
                </>
              )}
            </Card>
          </motion.div>
        ) : (
          <motion.div variants={surface}>
            <Card className="overflow-x-auto">
              <table className="w-full text-sm min-w-[820px]">
                <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
                  <tr>{COLS.map(([h, num]) => <th key={h} className={'px-5 py-3 font-medium' + (num ? ' text-right' : '')}>{h}</th>)}</tr>
                </thead>
                <motion.tbody variants={staggerDense()} initial="hidden" animate="show">
                  {rows.map((c) => (
                    <motion.tr key={c.id} variants={fade} className="border-t border-zinc-100 hover:bg-zinc-50 transition-colors">
                      <td className="px-5 py-3 font-medium">{c.name}</td>
                      <td className="px-5 py-3 text-zinc-500">{OBJ[c.objective] || c.objective}</td>
                      <td className="px-5 py-3 text-zinc-500"><span className="inline-flex items-center gap-1"><MapPin size={12} />{c.region || '—'}</span></td>
                      <td className="px-5 py-3"><Badge color={c.status === 'active' ? '#16a34a' : '#d97706'}>{c.status === 'active' ? 'Activa' : 'Pausada'}</Badge></td>
                      <td className="px-5 py-3 tabular-nums text-right text-zinc-500">{c.budget_clp == null ? '—' : `${clp(c.budget_clp)}${c.budget_period === 'daily' ? '/día' : c.budget_period === 'lifetime' ? ' total' : ''}`}</td>
                      <td className="px-5 py-3 tabular-nums text-right">{clp(c.spent_clp)}</td>
                      <td className="px-5 py-3 tabular-nums text-right font-semibold">{c.leads}</td>
                      <td className="px-5 py-3 tabular-nums text-right font-semibold" style={{ color: c.cpl_clp ? (c.cpl_clp <= summary.good_cpl_clp ? '#16a34a' : '#d97706') : undefined }}>
                        {c.cpl_clp ? clp(c.cpl_clp) : '—'}
                      </td>
                      <td className="px-5 py-3 text-zinc-400">{timeAgo(c.created_at)}</td>
                    </motion.tr>
                  ))}
                  {rows.length === 0 && <tr><td colSpan={COLS.length} className="px-5 py-10 text-center text-zinc-400">Sin campañas en este filtro.</td></tr>}
                </motion.tbody>
              </table>
            </Card>
          </motion.div>
        )}
      </section>
    </motion.div>
  )
}

// bg fijo (ej. #ecfdf5) se sacó del map: era un fondo opaco que en oscuro
// quedaba como una pastilla clara pegada de más — Badge ya resuelve
// color+alpha (y su versión oscura) solo, con el mismo `c`.
const ACTIONS = {
  scale: { l: 'Escalar', c: '#16a34a' },
  reallocate: { l: 'Realojar', c: '#d97706' },
  pause: { l: 'Pausar', c: '#e11d48' },
  keep: { l: 'Mantener', c: '#64748b' },
}

// El plan de gestión que propone Claude: recomienda acciones, no gasta.
function OptimizePanel({ opt, onClose }) {
  return (
    <Card className="p-5 space-y-3 border-champagne bg-champagne/20">
      <div className="flex items-center justify-between">
        <SectionTitle className="flex items-center gap-2"><Sparkles size={16} className="text-gold-deep" /> Plan de optimización</SectionTitle>
        <div className="flex items-center gap-2">
          <Badge color={opt.mode === 'live' ? '#16a34a' : '#94a3b8'}>{opt.mode === 'live' ? 'modelo real' : 'mock'}</Badge>
          <Button variant="ghost" onClick={onClose} aria-label="Cerrar plan"><X size={15} /></Button>
        </div>
      </div>
      <p className="text-sm text-zinc-700">{opt.plan}</p>
      <div className="space-y-2">
        {opt.recommendations.map((r, i) => {
          const a = ACTIONS[r.action] || ACTIONS.keep
          return (
            <div key={i} className="flex items-start gap-3 bg-white dark:bg-zinc-50 rounded-xl border border-zinc-200 p-3">
              <Badge color={a.c} className="shrink-0">{a.l}</Badge>
              <div>
                <div className="text-sm font-medium">{r.name}</div>
                <div className="text-xs text-zinc-500">{r.reason}</div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="text-[11px] text-zinc-400">Son recomendaciones: nada se gasta ni se aplica automáticamente. Conecta Meta real para ejecutar el plan.</div>
    </Card>
  )
}

// Mismo trazo que <Eyebrow>, pero como <label> para que cada input quede nombrado.
const LABEL = 'block mb-1.5 text-[11px] font-semibold uppercase tracking-[0.13em] text-pewter'

// Config de marketing POR CLIENTE: cuenta Meta, presupuesto y zonas (default Santiago).
function ClientConfig({ client, onClose }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['marketing', client], queryFn: () => api.marketing(client) })
  const cfg = data?.config || {}
  const [vals, setVals] = useState(null)
  const v = vals ?? {
    ad_account: cfg.ad_account || '',
    monthly_budget_clp: cfg.monthly_budget_clp || 300000,
    regions: (cfg.regions || ['Santiago (RM)']).join(', '),
  }
  const set = (k, val) => setVals({ ...v, [k]: val })
  const save = async () => {
    try {
      await api.setMarketing(client, {
        ad_account: v.ad_account.trim() || null,
        monthly_budget_clp: Number(v.monthly_budget_clp) || null,
        regions: v.regions.split(',').map((s) => s.trim()).filter(Boolean),
      })
      qc.invalidateQueries({ queryKey: ['marketing', client] })
      qc.invalidateQueries({ queryKey: ['campaigns', client] })
      toast.success('Configuración de marketing guardada')
      onClose?.()
    } catch (e) { toast.error('No se pudo guardar: ' + e.message) }
  }
  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <SectionTitle>Cuenta de marketing · <span className="text-gold-deep">{client}</span></SectionTitle>
        <Button variant="ghost" onClick={onClose} aria-label="Cerrar configuración"><X size={15} /></Button>
      </div>
      <p className="text-xs text-zinc-500 -mt-1">La cuenta publicitaria se asigna solo a este negocio. El token correspondiente se guarda en Configuración.</p>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><label htmlFor="mk-account" className={LABEL}>Cuenta publicitaria Meta (act_…)</label>
          <Input id="mk-account" value={v.ad_account} onChange={(e) => set('ad_account', e.target.value)} placeholder="act_123456789 (vacío = sin conectar)" /></div>
        <div><label htmlFor="mk-budget" className={LABEL}>Presupuesto mensual (CLP)</label>
          <Input id="mk-budget" type="number" value={v.monthly_budget_clp} onChange={(e) => set('monthly_budget_clp', e.target.value)} /></div>
        <div><label htmlFor="mk-regions" className={LABEL}>Zonas (foco Chile)</label>
          <Input id="mk-regions" value={v.regions} onChange={(e) => set('regions', e.target.value)} placeholder="Santiago (RM), Valparaíso" /></div>
      </div>
      <div><Button variant="primary" onClick={save}>Guardar cambios</Button></div>
    </Card>
  )
}
