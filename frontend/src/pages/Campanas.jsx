import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { DollarSign, Users, Target, Activity, Settings2, MapPin, Sparkles, TrendingUp } from 'lucide-react'
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from 'recharts'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, CountUp, Skeleton, Button, Badge, Input, Spinner, pageState, Eyebrow, SectionTitle } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'
import { rise, fade, surface, stagger, staggerDense } from '../lib/motion'

const FILTERS = [
  { value: 'todas', label: 'Todas' },
  { value: 'active', label: 'Activas' },
  { value: 'paused', label: 'Pausadas' },
]
const OBJ = { OUTCOME_LEADS: 'Leads', OUTCOME_TRAFFIC: 'Tráfico', OUTCOME_AWARENESS: 'Awareness' }
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

// Tendencia de 7 días — Meta no entrega series diarias por campaña, así que
// repartimos el gasto del mes con una curva leve (ramp ascendente) para dar
// una idea visual de evolución. Se marca como "estimado" en la UI; cuando
// /api/campaigns entregue una serie diaria real, esto se reemplaza 1:1.
const TREND_WEIGHTS = [0.11, 0.13, 0.12, 0.15, 0.14, 0.17, 0.18]
function buildTrend(summary) {
  return TREND_WEIGHTS.map((w, i) => {
    const d = new Date(Date.now() - (6 - i) * 86400000)
    return {
      name: d.toLocaleDateString('es-CL', { weekday: 'short' }),
      spent: Math.round((summary.spent_clp || 0) * w),
    }
  })
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
  const optimize = async () => {
    setOptBusy(true)
    try { setOpt(await api.optimizeCampaigns(client)) }
    catch (e) { toast.error('No se pudo optimizar: ' + e.message) }
    finally { setOptBusy(false) }
  }
  const syncLeads = async () => {
    setSyncBusy(true)
    try {
      const r = await api.syncAdLeads(client)
      toast.success(`${r.imported} leads de ads importados al CRM`)
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
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
  const { campaigns, summary } = data
  const rows = filter === 'todas' ? campaigns : campaigns.filter((c) => c.status === filter)
  const cards = [
    { l: 'Gastado (mes)', v: clp(summary.spent_clp), icon: DollarSign, bg: 'bg-champagne/35', fg: 'text-gold-deep' },
    { l: 'Leads de ads', v: summary.leads, icon: Users, bg: 'bg-brand/8', fg: 'text-brand' },
    { l: 'CPL promedio', v: clp(summary.cpl_clp), icon: Target, bg: 'bg-pewter/15', fg: 'text-pewter' },
  ]

  return (
    <motion.div className="space-y-5" initial="hidden" animate="show" variants={rise}>
      <motion.div className="grid grid-cols-1 sm:grid-cols-3 gap-4" variants={stagger()} initial="hidden" animate="show">
        {cards.map((c) => (
          <motion.div key={c.l} variants={surface}>
            <Card interactive className="p-5 flex items-start justify-between">
              <div className="min-w-0">
                <Eyebrow>{c.l}</Eyebrow>
                <div className="text-[28px] leading-none font-display font-extrabold tracking-tight text-brand mt-2.5 tabular-nums">{typeof c.v === 'number' ? <CountUp value={c.v} /> : c.v}</div>
              </div>
              <div className={`w-10 h-10 rounded-xl grid place-items-center border border-brand/10 shrink-0 ${c.bg} ${c.fg}`}>
                <c.icon size={18} />
              </div>
            </Card>
          </motion.div>
        ))}
      </motion.div>

      <motion.div className="flex items-center justify-between gap-3 flex-wrap" variants={fade}>
        <Segmented options={FILTERS} value={filter} onChange={setFilter} />
        <div className="flex items-center gap-2">
          <Badge color="#8C929B"><Activity size={11} className="inline -mt-px mr-1" />{summary.active} activas</Badge>
          <Badge color={summary.cpl_clp && summary.cpl_clp <= summary.good_cpl_clp ? '#16a34a' : '#d97706'}>
            CPL objetivo Chile ≤ {clp(summary.good_cpl_clp)}
          </Badge>
          <Badge color={summary.source === 'live' ? '#16a34a' : '#94a3b8'}>
            {summary.source === 'live' ? 'Meta conectado' : 'datos mock'}
          </Badge>
          <Button variant="soft" onClick={() => setShowCfg((v) => !v)}><Settings2 size={15} /> Config del cliente</Button>
          <Button variant="soft" onClick={syncLeads} disabled={syncBusy}>
            {syncBusy ? <Spinner /> : <Users size={15} />} {syncBusy ? 'Importando…' : 'Importar leads de ads'}
          </Button>
          <Button variant="accent" onClick={optimize} disabled={optBusy}>
            {optBusy ? <Spinner /> : <Sparkles size={15} />} {optBusy ? 'Analizando…' : 'Gestionar con Claude'}
          </Button>
        </div>
      </motion.div>

      {optBusy && (
        <motion.div variants={fade} initial="hidden" animate="show">
          <Card className="p-3 border-champagne bg-champagne/20 text-sm text-gold-deep flex items-center gap-2">
            <Spinner /> Analizando campañas con Claude…
          </Card>
        </motion.div>
      )}

      {summary.error && (
        <motion.div variants={fade}>
          <Card className="p-3 border-amber-200 bg-amber-50/70 text-sm text-amber-800">
          ⚠️ Meta no respondió — mostrando datos de ejemplo. Revisa el token / la cuenta en <b>Configuración → Meta Ads</b>.
            <div className="text-xs text-amber-700/80 mt-1 break-words">({summary.error})</div>
          </Card>
        </motion.div>
      )}
      {showCfg && <ClientConfig client={client} onClose={() => setShowCfg(false)} />}
      {opt && <OptimizePanel opt={opt} onClose={() => setOpt(null)} />}

      {campaigns.length > 0 && (
        <motion.div className="grid grid-cols-1 lg:grid-cols-3 gap-4" variants={stagger()} initial="hidden" animate="show">
          <motion.div className="lg:col-span-2" variants={surface}>
            <Card className="p-5 h-full">
            <div className="flex items-center justify-between mb-1">
              <SectionTitle className="flex items-center gap-2"><TrendingUp size={16} className="text-gold-deep" /> Tendencia de gasto (7 días)</SectionTitle>
              <Badge color="#8C929B">estimado</Badge>
            </div>
            <div className="text-xs text-zinc-400 mb-3">
              Proyección a partir del gasto del mes — Meta aún no entrega series diarias por campaña.
            </div>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={buildTrend(summary)} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
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
                    formatter={(v) => [clp(v), 'Gasto (estimado)']} />
                  <Area type="monotone" dataKey="spent" stroke="var(--color-gold-deep)" strokeWidth={2} strokeDasharray="4 4" fill="url(#spentFill)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            </Card>
          </motion.div>

          <motion.div variants={surface}>
            <Card className="p-5 h-full">
            <SectionTitle className="mb-1">Leads por objetivo</SectionTitle>
            <div className="text-xs text-zinc-400 mb-3">Distribución real de leads del mes.</div>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byObjective(campaigns)} layout="vertical" margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid horizontal={false} stroke="var(--color-zinc-100)" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} width={70} />
                  <Tooltip cursor={{ fill: 'var(--color-zinc-100)' }}
                    contentStyle={{ borderRadius: 12, border: '1px solid var(--color-zinc-200)', fontSize: 13, background: 'var(--color-zinc-50)' }}
                    labelStyle={{ color: 'var(--color-zinc-700)' }} />
                  <Bar dataKey="value" radius={[0, 8, 8, 0]} maxBarSize={28} fill="#2C3529" animationDuration={700} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            </Card>
          </motion.div>
        </motion.div>
      )}

      {campaigns.length === 0 ? (
        <motion.div variants={surface}>
          <Card className="py-16 text-center">
          <img src="/logo-mark.png" alt="" className="w-12 h-12 mx-auto mb-4 grayscale opacity-25" />
          <div className="font-semibold text-zinc-500">No hay campañas activas</div>
            <p className="text-sm text-zinc-400 mt-1">Conecta Meta Ads o crea una campaña para ver su rendimiento aquí.</p>
          </Card>
        </motion.div>
      ) : (
        <motion.div variants={surface}>
          <Card className="overflow-x-auto">
          <table className="w-full text-sm min-w-[820px]">
            <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
              <tr>{['Campaña', 'Objetivo', 'Zona', 'Estado', 'Presupuesto', 'Gastado', 'Leads', 'CPL', 'Creada'].map((h) => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr>
            </thead>
            <motion.tbody variants={staggerDense()} initial="hidden" animate="show">
              {rows.map((c) => (
                <motion.tr key={c.id} variants={fade} className="border-t border-zinc-100 hover:bg-zinc-50 transition-colors">
                  <td className="px-5 py-3 font-medium">{c.name}</td>
                  <td className="px-5 py-3 text-zinc-500">{OBJ[c.objective] || c.objective}</td>
                  <td className="px-5 py-3 text-zinc-500"><span className="inline-flex items-center gap-1"><MapPin size={12} />{c.region}</span></td>
                  <td className="px-5 py-3"><Badge color={c.status === 'active' ? '#16a34a' : '#d97706'}>{c.status === 'active' ? 'Activa' : 'Pausada'}</Badge></td>
                  <td className="px-5 py-3 tabular-nums text-zinc-500">{clp(c.budget_clp)}</td>
                  <td className="px-5 py-3 tabular-nums">{clp(c.spent_clp)}</td>
                  <td className="px-5 py-3 tabular-nums font-semibold">{c.leads}</td>
                  <td className="px-5 py-3 tabular-nums font-semibold" style={{ color: c.cpl_clp && c.cpl_clp <= summary.good_cpl_clp ? '#16a34a' : '#d97706' }}>
                    {c.cpl_clp ? clp(c.cpl_clp) : '—'}
                  </td>
                  <td className="px-5 py-3 text-zinc-400">{timeAgo(c.created_at)}</td>
                </motion.tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={9} className="px-5 py-10 text-center text-zinc-400">Sin campañas en este filtro.</td></tr>}
            </motion.tbody>
          </table>
          </Card>
        </motion.div>
      )}
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
function OptimizePanel({ opt }) {
  return (
    <Card className="p-5 space-y-3 border-champagne bg-champagne/20">
      <div className="flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2"><Sparkles size={16} className="text-gold-deep" /> Plan de Claude</div>
        <Badge color={opt.mode === 'live' ? '#16a34a' : '#94a3b8'}>{opt.mode === 'live' ? 'modelo real' : 'mock'}</Badge>
      </div>
      <p className="text-sm text-zinc-700">{opt.plan}</p>
      <div className="space-y-2">
        {opt.recommendations.map((r, i) => {
          const a = ACTIONS[r.action] || ACTIONS.keep
          return (
            <div key={i} className="flex items-start gap-3 bg-white dark:bg-[#1D2016] rounded-xl border border-zinc-200 p-3">
              <Badge color={a.c} className="shrink-0">{a.l}</Badge>
              <div>
                <div className="text-sm font-medium">{r.name}</div>
                <div className="text-xs text-zinc-500">{r.reason}</div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="text-[11px] text-zinc-400">Recomendaciones — Claude no gasta ni aplica cambios solo. Conecta Meta real para ejecutar el plan.</div>
    </Card>
  )
}

// Config de marketing POR CLIENTE: cuenta Meta, presupuesto y zonas (default Santiago).
function ClientConfig({ client }) {
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
      toast.success('Config de marketing guardada')
    } catch (e) { toast.error('No se pudo guardar: ' + e.message) }
  }
  return (
    <Card className="p-5 space-y-3 border-champagne">
      <div className="font-semibold">Marketing de <span className="text-gold-deep">{client}</span></div>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><label className="block text-xs text-zinc-500 mb-1">Cuenta publicitaria Meta (act_…)</label>
          <Input value={v.ad_account} onChange={(e) => set('ad_account', e.target.value)} placeholder="act_123456789 (vacío = mock)" /></div>
        <div><label className="block text-xs text-zinc-500 mb-1">Presupuesto mensual (CLP)</label>
          <Input type="number" value={v.monthly_budget_clp} onChange={(e) => set('monthly_budget_clp', e.target.value)} /></div>
        <div><label className="block text-xs text-zinc-500 mb-1">Zonas (foco Chile)</label>
          <Input value={v.regions} onChange={(e) => set('regions', e.target.value)} placeholder="Santiago (RM), Valparaíso" /></div>
      </div>
      <Button variant="accent" onClick={save}>Guardar</Button>
    </Card>
  )
}
