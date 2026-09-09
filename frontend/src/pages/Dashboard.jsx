import { useState } from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Users, GitBranch, Trophy, DollarSign, Plus, Rocket, Bell, CheckCircle2 } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Cell, Tooltip } from 'recharts'
import { api } from '../lib/api'
import { STAGES, repliedRecently } from '../lib/util'
import { Card, CountUp, Skeleton, Button, pageState, Eyebrow, SectionTitle } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { rise, fade, surface, stagger, meterFill } from '../lib/motion'

const OPEN = ['new', 'qualified', 'contacted', 'nurturing', 'replied', 'meeting']
const CLOSED = ['won', 'lost', 'disqualified']
const CHART_GROUPS = [
  { value: 'todas', label: 'Todas' },
  { value: 'activas', label: 'Activas' },
  { value: 'cerradas', label: 'Cerradas' },
]

export default function Dashboard() {
  const { client, clients, setClient } = useApp()
  const [chartG, setChartG] = useState('todas')
  const kpisQ = useQuery({ queryKey: ['kpis', client], queryFn: () => api.kpis(client), enabled: !!client })
  const boardQ = useQuery({ queryKey: ['board', client], queryFn: () => api.board(client), enabled: !!client })
  const kpis = kpisQ.data, board = boardQ.data

  if (!client) return <NoClient />
  const gate = pageState({ error: kpisQ.error || boardQ.error, onRetry: () => { kpisQ.refetch(); boardQ.refetch() } })
  if (gate) return gate

  // Monocromo-marca: un solo acento en champagne gold — la métrica primaria — y
  // el resto en slate. Nada de arcoíris genérico.
  const cards = [
    { label: 'Leads totales', value: kpis?.total, icon: Users, tone: 'gold' },
    { label: 'En pipeline', value: kpis?.in_pipeline, icon: GitBranch, tone: 'slate' },
    { label: 'Ganados', value: kpis?.won, icon: Trophy, tone: 'slate' },
    { label: 'Pipeline ganado', value: kpis?.pipeline_clp, prefix: '$', icon: DollarSign, tone: 'slate' },
  ]

  const inChart = (st) => chartG === 'todas' ? true : chartG === 'cerradas' ? CLOSED.includes(st) : OPEN.includes(st)
  const used = (board?.stages || []).filter((s) => s.leads.length && inChart(s.stage))
  const chartData = used.map((s) => ({ name: STAGES[s.stage]?.l || s.stage, value: s.leads.length, c: STAGES[s.stage]?.c || '#94a3b8' }))
  const counts = Object.fromEntries((board?.stages || []).map((s) => [s.stage, s.leads.length]))
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const disq = counts.disqualified || 0, won = counts.won || 0
  const openN = OPEN.reduce((a, s) => a + (counts[s] || 0), 0)
  const pct = total ? Math.round((100 * (total - disq)) / total) : 0

  return (
    <motion.div className="space-y-5" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <NeedsAttention clients={clients} setClient={setClient} />
      </motion.div>

      <motion.div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5" variants={stagger()} initial="hidden" animate="show">
        {cards.map((c) => {
          const chip = c.tone === 'gold'
            ? 'bg-champagne/25 text-gold-deep border-champagne/60'
            : 'bg-brand/[0.05] text-brand/90 border-brand/10'
          return (
            <motion.div key={c.label} variants={surface}>
              <Card interactive className="p-5 flex items-start justify-between">
                <div className="min-w-0">
                  <Eyebrow>{c.label}</Eyebrow>
                  <div className="text-[32px] leading-none font-display font-extrabold tracking-tight text-brand mt-2.5 tabular-nums">
                    {kpisQ.isLoading ? <Skeleton className="h-8 w-20 mt-1" /> : <CountUp value={c.value ?? 0} prefix={c.prefix || ''} />}
                  </div>
                </div>
                <div className={'w-10 h-10 rounded-xl grid place-items-center border shrink-0 ' + chip}>
                  <c.icon size={18} />
                </div>
              </Card>
            </motion.div>
          )
        })}
      </motion.div>

      <motion.div className="grid grid-cols-1 lg:grid-cols-3 gap-5" variants={stagger()} initial="hidden" animate="show">
        <motion.div className="lg:col-span-2" variants={surface}>
          <Card className="p-4">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <Eyebrow>Embudo</Eyebrow>
                <SectionTitle className="mt-0.5">Leads por etapa</SectionTitle>
              </div>
              <Segmented options={CHART_GROUPS} value={chartG} onChange={setChartG} />
            </div>
            <div style={{ height: 300 }}>
              {boardQ.isLoading ? (
                <Skeleton className="h-full w-full" />
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                    {/* Colores vía var(--color-zinc-*) en vez de hex fijo: son props
                        SVG/CSS reales (fill/stroke/style), así que el navegador
                        resuelve la CSS var con la cascada normal — heredan el
                        modo oscuro solos, igual que cualquier utilidad Tailwind,
                        sin necesitar un hook de tema acá. */}
                    <CartesianGrid vertical={false} stroke="var(--color-zinc-100)" />
                    <XAxis dataKey="name" tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} />
                    <Tooltip
                      cursor={{ fill: 'var(--color-zinc-100)' }}
                      contentStyle={{ borderRadius: 12, border: '1px solid var(--color-zinc-200)', fontSize: 13, background: 'var(--color-zinc-50)' }}
                      labelStyle={{ color: 'var(--color-zinc-700)' }}
                    />
                    <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={48} animationDuration={700}>
                      {chartData.map((d, i) => <Cell key={i} fill={d.c} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>
        </motion.div>

        <motion.div variants={surface}>
          <Card className="p-5 h-full">
            <Eyebrow>Salud</Eyebrow>
            <SectionTitle className="mt-0.5">Salud del embudo</SectionTitle>
            <div className="text-xs text-zinc-400 mt-0.5">% de leads que pasó el filtro</div>
            <div className="text-[44px] leading-none font-display font-extrabold text-gold-deep text-center mt-5 tabular-nums tracking-tight">
              {boardQ.isLoading ? '—' : <CountUp value={pct} />}%
            </div>
            <div className="w-full h-2 bg-zinc-100 rounded-full mt-3 overflow-hidden">
              <motion.div className="h-full bg-zinc-900 rounded-full" {...meterFill(pct)} />
            </div>
            <div className="mt-5 space-y-3 text-sm">
              <Row c="#10b981" l="En proceso" v={openN} />
              <Row c="#16a34a" l="Ganados" v={won} />
              <Row c="#e11d48" l="Descartados" v={disq} />
            </div>
          </Card>
        </motion.div>
      </motion.div>
    </motion.div>
  )
}

function Row({ c, l, v }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />
      <span className="text-zinc-600">{l}</span>
      <span className="ml-auto font-semibold tabular-nums">{v}</span>
    </div>
  )
}

/* Feed cross-cliente: quién respondió en 24h y sigue sin acción humana. Útil
   para un equipo — no hay que ir cliente por cliente para saber qué está
   pendiente. Sin backend nuevo: reusa /api/leads por cliente (ya existente) y
   el mismo cálculo que ya usaba Agentes.jsx (ahora compartido en lib/util). */
function NeedsAttention({ clients, setClient }) {
  const nav = useNavigate()
  const list = clients || []
  const results = useQueries({
    queries: list.map((c) => ({
      queryKey: ['leads', c, 'needs-attention'],
      queryFn: () => api.leads(c, { group: 'todos', limit: 50 }),
      staleTime: 60_000,
    })),
  })

  const loading = results.some((r) => r.isLoading)
  const rows = list
    .map((c, i) => ({ client: c, n: repliedRecently(results[i]?.data?.leads, undefined) }))
    .filter((r) => r.n)
    .sort((a, b) => b.n - a.n)

  const jump = (c) => { setClient(c); nav('/leads') }

  if (loading) {
    return <Card className="p-5"><Skeleton className="h-14 w-full" /></Card>
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <Bell size={16} className="text-gold-deep" />
        <SectionTitle>Necesita tu atención</SectionTitle>
      </div>
      {rows.length === 0 ? (
        <div className="text-sm text-zinc-400 flex items-center gap-2">
          <CheckCircle2 size={15} className="text-gold-deep" /> Todo al día — nadie esperando respuesta hace más de 24h.
        </div>
      ) : (
        <div className="space-y-1.5">
          {rows.map((r) => (
            <button key={r.client} onClick={() => jump(r.client)}
              className="w-full flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm bg-zinc-50 hover:bg-zinc-100 transition-colors text-left">
              <span className="font-medium capitalize truncate">{r.client}</span>
              <span className="text-xs text-gold-deep font-semibold shrink-0">
                {r.n} {r.n === 1 ? 'lead respondió' : 'leads respondieron'} en 24h
              </span>
            </button>
          ))}
        </div>
      )}
    </Card>
  )
}

export function NoClient() {
  const { openRun } = useApp()
  const steps = [
    ['Define tu cliente', 'Dile a ZeroAI qué vende y a quién (su ICP).'],
    ['Busca leads', 'Descubre, califica y deja listos para contactar.'],
    ['Contacta y sigue', 'Primer mensaje + follow-ups que corren solos.'],
  ]
  return (
    <motion.div className="max-w-lg mx-auto py-16 text-center" initial="hidden" animate="show" variants={rise}>
      <div className="w-14 h-14 rounded-2xl bg-champagne/40 text-gold-deep grid place-items-center mx-auto mb-4"><Rocket size={26} /></div>
      <h2 className="text-2xl font-display font-bold tracking-tight text-brand">Empieza con tu primer cliente</h2>
      <p className="text-zinc-500 mt-1.5 mb-6">En un clic, ZeroAI descubre, califica y prepara leads B2B listos para contactar.</p>
      <motion.div className="text-left space-y-3 mb-7" variants={stagger()}>
        {steps.map(([t, d], i) => (
          <motion.div key={i} className="flex gap-3" variants={fade}>
            <span className="w-6 h-6 shrink-0 rounded-full bg-brand-surface text-white text-xs font-bold grid place-items-center">{i + 1}</span>
            <div>
              <div className="text-sm font-semibold">{t}</div>
              <div className="text-xs text-zinc-500">{d}</div>
            </div>
          </motion.div>
        ))}
      </motion.div>
      {openRun && <Button variant="accent" className="rounded-full px-6" onClick={openRun}><Plus size={16} /> Buscar leads</Button>}
    </motion.div>
  )
}
