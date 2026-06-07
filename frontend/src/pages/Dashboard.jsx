import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Users, GitBranch, Trophy, DollarSign } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Cell, Tooltip } from 'recharts'
import { api } from '../lib/api'
import { STAGES } from '../lib/util'
import { Card, CountUp, Skeleton } from '../components/ui'
import { useApp } from '../App'

const OPEN = ['new', 'qualified', 'contacted', 'nurturing', 'replied', 'meeting']

export default function Dashboard() {
  const { client } = useApp()
  const kpisQ = useQuery({ queryKey: ['kpis', client], queryFn: () => api.kpis(client), enabled: !!client })
  const boardQ = useQuery({ queryKey: ['board', client], queryFn: () => api.board(client), enabled: !!client })
  const kpis = kpisQ.data, board = boardQ.data

  if (!client) return <NoClient />

  const cards = [
    { label: 'Leads totales', value: kpis?.total, icon: Users, bg: '#eef2ff', fg: '#6366f1' },
    { label: 'En pipeline', value: kpis?.in_pipeline, icon: GitBranch, bg: '#ecfdf5', fg: '#10b981' },
    { label: 'Ganados', value: kpis?.won, icon: Trophy, bg: '#faf5ff', fg: '#a855f7' },
    { label: 'Pipeline ganado', value: kpis?.pipeline_usd, prefix: '$', icon: DollarSign, bg: '#fff7ed', fg: '#f59e0b' },
  ]

  const used = (board?.stages || []).filter((s) => s.leads.length)
  const chartData = used.map((s) => ({ name: STAGES[s.stage]?.l || s.stage, value: s.leads.length, c: STAGES[s.stage]?.c || '#94a3b8' }))
  const counts = Object.fromEntries((board?.stages || []).map((s) => [s.stage, s.leads.length]))
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const disq = counts.disqualified || 0, won = counts.won || 0
  const openN = OPEN.reduce((a, s) => a + (counts[s] || 0), 0)
  const pct = total ? Math.round((100 * (total - disq)) / total) : 0

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        {cards.map((c, i) => (
          <motion.div key={c.label} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06, ease: [0.22, 1, 0.36, 1] }}>
            <Card className="p-5 flex items-start justify-between transition-shadow hover:shadow-[0_2px_6px_rgba(16,24,40,0.06),0_16px_40px_-16px_rgba(16,24,40,0.14)]">
              <div>
                <div className="text-sm text-zinc-500">{c.label}</div>
                <div className="text-3xl font-extrabold mt-1 tabular-nums">
                  {kpisQ.isLoading ? <Skeleton className="h-8 w-16 mt-1" /> : <CountUp value={c.value ?? 0} prefix={c.prefix || ''} />}
                </div>
              </div>
              <div className="w-11 h-11 rounded-xl grid place-items-center" style={{ background: c.bg, color: c.fg }}>
                <c.icon size={20} />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <Card className="p-5">
            <div className="font-semibold">Leads por etapa</div>
            <div className="text-xs text-zinc-400 mb-4">Distribución del embudo</div>
            <div style={{ height: 300 }}>
              {boardQ.isLoading ? (
                <Skeleton className="h-full w-full" />
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="#f1f5f9" />
                    <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#71717a' }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#71717a' }} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: '#f4f4f5' }} contentStyle={{ borderRadius: 12, border: '1px solid #e4e4e7', fontSize: 13 }} />
                    <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={48} animationDuration={700}>
                      {chartData.map((d, i) => <Cell key={i} fill={d.c} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
          <Card className="p-5 h-full">
            <div className="font-semibold">Salud del embudo</div>
            <div className="text-xs text-zinc-400">% de leads que pasó el filtro</div>
            <div className="text-4xl font-extrabold text-emerald-600 text-center mt-4 tabular-nums">
              {boardQ.isLoading ? '—' : <CountUp value={pct} />}%
            </div>
            <div className="w-full h-2 bg-zinc-100 rounded-full mt-3 overflow-hidden">
              <motion.div className="h-full bg-zinc-900 rounded-full" initial={{ width: 0 }} animate={{ width: pct + '%' }} transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }} />
            </div>
            <div className="mt-5 space-y-3 text-sm">
              <Row c="#10b981" l="En proceso" v={openN} />
              <Row c="#16a34a" l="Ganados" v={won} />
              <Row c="#e11d48" l="Descartados" v={disq} />
            </div>
          </Card>
        </motion.div>
      </div>
    </div>
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

export function NoClient() {
  return (
    <div className="text-zinc-400 py-20 text-center">
      Aún no hay datos. Usá <b className="text-zinc-600">Buscar leads</b> para correr una pipeline.
    </div>
  )
}
