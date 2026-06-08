import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { DollarSign, Users, Target, Activity } from 'lucide-react'
import { api } from '../lib/api'
import { Card, CountUp, Skeleton, Button, Badge } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

const FILTERS = [
  { value: 'todas', label: 'Todas' },
  { value: 'active', label: 'Activas' },
  { value: 'paused', label: 'Pausadas' },
]
const OBJ = {
  OUTCOME_LEADS: 'Leads', OUTCOME_TRAFFIC: 'Tráfico', OUTCOME_AWARENESS: 'Awareness',
}

export default function Campanas() {
  const { client } = useApp()
  const [filter, setFilter] = useState('todas')
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['campaigns', client], queryFn: () => api.campaigns(client), enabled: !!client,
  })
  if (!client) return <NoClient />

  if (isLoading) return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      <Skeleton className="h-64 w-full" />
    </div>
  )
  if (error) return (
    <div className="py-16 text-center">
      <p className="text-rose-600 font-medium">No se pudieron cargar las campañas.</p>
      <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
    </div>
  )

  const { campaigns, summary } = data
  const rows = filter === 'todas' ? campaigns : campaigns.filter((c) => c.status === filter)
  const cards = [
    { l: 'Gastado', v: summary.spent_usd, prefix: '$', icon: DollarSign, bg: '#fff7ed', fg: '#f59e0b' },
    { l: 'Leads de ads', v: summary.leads, icon: Users, bg: '#eef2ff', fg: '#6366f1' },
    { l: 'CPL promedio', v: summary.cpl_usd, prefix: '$', icon: Target, bg: '#ecfdf5', fg: '#10b981' },
    { l: 'Campañas activas', v: summary.active, icon: Activity, bg: '#faf5ff', fg: '#a855f7' },
  ]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((c, i) => (
          <motion.div key={c.l} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
            <Card className="p-5 flex items-start justify-between">
              <div>
                <div className="text-sm text-zinc-500">{c.l}</div>
                <div className="text-2xl font-extrabold mt-1 tabular-nums">{c.prefix || ''}<CountUp value={c.v ?? 0} /></div>
              </div>
              <div className="w-10 h-10 rounded-xl grid place-items-center" style={{ background: c.bg, color: c.fg }}>
                <c.icon size={18} />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Segmented options={FILTERS} value={filter} onChange={setFilter} />
        <Badge color={summary.source === 'live' ? '#16a34a' : '#94a3b8'}>
          {summary.source === 'live' ? 'Meta Ads conectado' : 'datos mock'}
        </Badge>
      </div>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
            <tr>{['Campaña', 'Objetivo', 'Estado', 'Presupuesto', 'Gastado', 'Leads', 'CPL'].map((h) => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t border-zinc-100">
                <td className="px-5 py-3 font-medium">{c.name}</td>
                <td className="px-5 py-3 text-zinc-500">{OBJ[c.objective] || c.objective}</td>
                <td className="px-5 py-3">
                  <Badge color={c.status === 'active' ? '#16a34a' : '#d97706'}>{c.status === 'active' ? 'Activa' : 'Pausada'}</Badge>
                </td>
                <td className="px-5 py-3 tabular-nums text-zinc-500">${c.budget_usd}</td>
                <td className="px-5 py-3 tabular-nums">${c.spent_usd}</td>
                <td className="px-5 py-3 tabular-nums font-semibold">{c.leads}</td>
                <td className="px-5 py-3 tabular-nums">{c.cpl_usd ? '$' + c.cpl_usd : '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={7} className="px-5 py-10 text-center text-zinc-400">Sin campañas en este filtro.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
