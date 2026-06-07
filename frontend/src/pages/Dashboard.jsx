import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Users, GitBranch, Trophy, DollarSign } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Cell, Tooltip } from 'recharts'
import { api } from '../lib/api'
import { STAGES } from '../lib/util'
import { Card } from '../components/ui'
import { useApp } from '../App'

const OPEN = ['new', 'qualified', 'contacted', 'nurturing', 'replied', 'meeting']

export default function Dashboard() {
  const { client } = useApp()
  const { data: kpis } = useQuery({ queryKey: ['kpis', client], queryFn: () => api.kpis(client), enabled: !!client })
  const { data: board } = useQuery({ queryKey: ['board', client], queryFn: () => api.board(client), enabled: !!client })

  if (!client) return <NoClient />

  const cards = [
    { label: 'Leads totales', value: kpis?.total ?? '—', icon: Users, bg: '#eef2ff', fg: '#6366f1' },
    { label: 'En pipeline', value: kpis?.in_pipeline ?? '—', icon: GitBranch, bg: '#ecfdf5', fg: '#10b981' },
    { label: 'Ganados', value: kpis?.won ?? '—', icon: Trophy, bg: '#faf5ff', fg: '#a855f7' },
    { label: 'Pipeline ganado', value: kpis ? '$' + kpis.pipeline_usd.toLocaleString() : '—', icon: DollarSign, bg: '#fff7ed', fg: '#f59e0b' },
  ]

  const used = (board?.stages || []).filter((s) => s.leads.length)
  const chartData = used.map((s) => ({ name: STAGES[s.stage]?.l || s.stage, value: s.leads.length, c: STAGES[s.stage]?.c || '#94a3b8' }))

  const counts = Object.fromEntries((board?.stages || []).map((s) => [s.stage, s.leads.length]))
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const disq = counts.disqualified || 0
  const won = counts.won || 0
  const openN = OPEN.reduce((a, s) => a + (counts[s] || 0), 0)
  const pct = total ? Math.round((100 * (total - disq)) / total) : 0

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        {cards.map((c, i) => (
          <motion.div key={c.label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
            <Card className="p-5 flex items-start justify-between">
              <div>
                <div className="text-sm text-zinc-500">{c.label}</div>
                <div className="text-3xl font-extrabold mt-1 tabular-nums">{c.value}</div>
              </div>
              <div className="w-11 h-11 rounded-xl grid place-items-center" style={{ background: c.bg, color: c.fg }}>
                <c.icon size={20} />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="p-5">
            <div className="font-semibold">Leads por etapa</div>
            <div className="text-xs text-zinc-400 mb-4">Distribución del embudo</div>
            <div style={{ height: 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#71717a' }} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#71717a' }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: '#f4f4f5' }} contentStyle={{ borderRadius: 12, border: '1px solid #e4e4e7', fontSize: 13 }} />
                  <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={48}>
                    {chartData.map((d, i) => <Cell key={i} fill={d.c} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card className="p-5 h-full">
            <div className="font-semibold">Salud del embudo</div>
            <div className="text-xs text-zinc-400">% de leads que pasó el filtro</div>
            <div className="text-4xl font-extrabold text-emerald-600 text-center mt-4 tabular-nums">{pct}%</div>
            <div className="w-full h-2 bg-zinc-100 rounded-full mt-3 overflow-hidden">
              <motion.div className="h-full bg-zinc-900 rounded-full" initial={{ width: 0 }} animate={{ width: pct + '%' }} transition={{ duration: 0.6 }} />
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
