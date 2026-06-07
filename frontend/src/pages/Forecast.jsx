import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { api } from '../lib/api'
import { Card } from '../components/ui'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

export default function Forecast() {
  const { client } = useApp()
  const { data, isLoading } = useQuery({ queryKey: ['forecast', client], queryFn: () => api.forecast(client), enabled: !!client })
  if (!client) return <NoClient />
  if (isLoading || !data) return <div className="text-zinc-400 py-16">Calculando…</div>

  const f = data.forecast, p = f.projection, a = f.assumptions, i = f.inputs
  const stats = [
    ['Respuestas esperadas', '~' + p.expected_replies],
    ['Reuniones', '~' + p.expected_meetings],
    ['Cierres', '~' + p.expected_wins],
    ['Pipeline', '$' + Math.round(p.expected_pipeline_usd).toLocaleString()],
  ]
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map(([l, v], idx) => (
          <motion.div key={l} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.06 }}>
            <Card className="p-5">
              <div className="text-sm text-zinc-500">{l}</div>
              <div className="text-2xl font-extrabold mt-1 tabular-nums">{v}</div>
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
