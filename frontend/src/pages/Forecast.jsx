import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { api } from '../lib/api'
import { Card, CountUp, Skeleton, Button } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

const SCENARIOS = [
  { value: 'conservador', label: 'Conservador' },
  { value: 'base', label: 'Base' },
  { value: 'optimista', label: 'Optimista' },
]
const FACTOR = { conservador: 0.8, base: 1, optimista: 1.25 }

export default function Forecast() {
  const { client } = useApp()
  const [scen, setScen] = useState('base')
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['forecast', client], queryFn: () => api.forecast(client), enabled: !!client,
  })
  if (!client) return <NoClient />

  if (isLoading) return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      <Skeleton className="h-28 w-full" />
    </div>
  )
  if (error) return (
    <div className="py-16 text-center">
      <p className="text-rose-600 font-medium">No se pudo calcular el forecast.</p>
      <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
    </div>
  )

  const f = data.forecast, p = f.projection, a = f.assumptions, i = f.inputs
  const k = FACTOR[scen]
  const stats = [
    { l: 'Respuestas esperadas', v: Math.round(p.expected_replies * k), prefix: '~' },
    { l: 'Reuniones', v: Math.round(p.expected_meetings * k), prefix: '~' },
    { l: 'Cierres', v: Math.round(p.expected_wins * k), prefix: '~' },
    { l: 'Pipeline', v: Math.round(p.expected_pipeline_clp * k), prefix: '$' },
  ]
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Segmented options={SCENARIOS} value={scen} onChange={setScen} />
        <span className="text-xs text-zinc-400">
          {scen === 'base' ? 'Tasas estimadas por el ANALYST' : `Escenario what-if: ×${k} sobre la base`}
        </span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s, idx) => (
          <motion.div key={s.l} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.06 }}>
            <Card className="p-5">
              <div className="text-sm text-zinc-500">{s.l}</div>
              <div className="text-2xl font-extrabold mt-1 tabular-nums">{s.prefix}<CountUp value={s.v} /></div>
            </Card>
          </motion.div>
        ))}
      </div>
      <Card className="p-5 text-sm text-zinc-600">
        <div className="font-semibold text-zinc-900 mb-2">Supuestos</div>
        Embudo: descubiertos {i.discovered} → calificados {i.qualified} → contactados {i.contacted}.<br />
        Tasas: respuesta {a.reply_rate} · reunión {a.meeting_rate} · cierre {a.win_rate} · ticket ${(a.avg_deal_value_clp || 0).toLocaleString('es-CL')} CLP.
        {f.commentary && <div className="mt-3 text-zinc-500 italic">{f.commentary}</div>}
      </Card>
    </div>
  )
}
