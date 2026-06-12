import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { DollarSign, Users, Target, Activity, Settings2, MapPin, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, CountUp, Skeleton, Button, Badge, Input, pageState } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

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
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {cards.map((c, i) => (
          <motion.div key={c.l} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
            <Card interactive className="p-5 flex items-start justify-between">
              <div>
                <div className="text-sm text-zinc-500">{c.l}</div>
                <div className="text-2xl font-extrabold mt-1 tabular-nums">{typeof c.v === 'number' ? <CountUp value={c.v} /> : c.v}</div>
              </div>
              <div className={`w-10 h-10 rounded-xl grid place-items-center ${c.bg} ${c.fg}`}>
                <c.icon size={18} />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
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
            <Users size={15} /> {syncBusy ? 'Importando…' : 'Importar leads de ads'}
          </Button>
          <Button variant="accent" onClick={optimize} disabled={optBusy}>
            <Sparkles size={15} /> {optBusy ? 'Analizando…' : 'Gestionar con Claude'}
          </Button>
        </div>
      </div>

      {summary.error && (
        <Card className="p-3 border-amber-200 bg-amber-50/70 text-sm text-amber-800">
          ⚠️ Meta no respondió — mostrando datos de ejemplo. Revisa el token / la cuenta en <b>Configuración → Meta Ads</b>.
          <div className="text-xs text-amber-700/80 mt-1 break-words">({summary.error})</div>
        </Card>
      )}
      {showCfg && <ClientConfig client={client} onClose={() => setShowCfg(false)} />}
      {opt && <OptimizePanel opt={opt} onClose={() => setOpt(null)} />}

      {campaigns.length === 0 ? (
        <Card className="py-16 text-center">
          <img src="/logo-mark.png" alt="" className="w-12 h-12 mx-auto mb-4 grayscale opacity-25" />
          <div className="font-semibold text-zinc-500">No hay campañas activas</div>
          <p className="text-sm text-zinc-400 mt-1">Conecta Meta Ads o crea una campaña para ver su rendimiento aquí.</p>
        </Card>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm min-w-[820px]">
            <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
              <tr>{['Campaña', 'Objetivo', 'Zona', 'Estado', 'Presupuesto', 'Gastado', 'Leads', 'CPL', 'Creada'].map((h) => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t border-zinc-100 hover:bg-zinc-50 transition-colors">
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
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={9} className="px-5 py-10 text-center text-zinc-400">Sin campañas en este filtro.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

const ACTIONS = {
  scale: { l: 'Escalar', c: '#16a34a', bg: '#ecfdf5' },
  reallocate: { l: 'Realojar', c: '#d97706', bg: '#fff7ed' },
  pause: { l: 'Pausar', c: '#e11d48', bg: '#fef2f2' },
  keep: { l: 'Mantener', c: '#64748b', bg: '#f4f4f5' },
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
            <div key={i} className="flex items-start gap-3 bg-white rounded-xl border border-zinc-200 p-3">
              <span className="text-xs font-bold px-2 py-1 rounded-full shrink-0" style={{ color: a.c, background: a.bg }}>{a.l}</span>
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
