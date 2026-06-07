import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { api } from '../lib/api'
import { Card, CountUp, Skeleton, Button } from '../components/ui'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

export default function Forecast() {
  const { client } = useApp()
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
  const stats = [
    { l: 'Respuestas esperadas', v: p.expected_replies, prefix: '~' },
    { l: 'Reuniones', v: p.expected_meetings, prefix: '~' },
    { l: 'Cierres', v: p.expected_wins, prefix: '~' },
    { l: 'Pipeline', v: Math.round(p.expected_pipeline_usd), prefix: '$' },
  ]
  return (
    <div className="space-y-5">
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
        Tasas: respuesta {a.reply_rate} · reunión {a.meeting_rate} · cierre {a.win_rate} · ticket ${a.avg_deal_value_usd}.
        {f.commentary && <div className="mt-3 text-zinc-500 italic">{f.commentary}</div>}
      </Card>
    </div>
  )
}
