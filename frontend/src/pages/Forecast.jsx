import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import { Button, Card, CountUp, Skeleton, pageState, Eyebrow, Badge } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { WorkspaceHero, WorkspaceSectionHeading } from '../components/WorkspaceHero'
import { useApp } from '../App'
import { NoClient } from './Dashboard'
import { rise, fade, surface, stagger } from '../lib/motion'

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

  // El cálculo pasa por el motor y puede tardar: el hero se pinta desde el primer
  // momento y la espera va dentro de la sección, con un texto que dice qué se espera.
  // Antes la página era solo bloques grises, sin título, hasta que el motor contestaba.
  const gate = pageState({
    isLoading, error, onRetry: refetch,
    skeleton: (
      <div className="space-y-4">
        <p className="text-sm text-zinc-500">Calculando la proyección con el motor… puede tardar unos segundos.</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      </div>
    ),
  })
  const f = data?.forecast
  const ready = !!(f?.projection && f.assumptions && f.inputs)
  const p = f?.projection, a = f?.assumptions, i = f?.inputs
  const k = FACTOR[scen]
  const stats = ready ? [
    { l: 'Respuestas esperadas', v: Math.round(p.expected_replies * k), prefix: '~' },
    { l: 'Reuniones', v: Math.round(p.expected_meetings * k), prefix: '~' },
    { l: 'Cierres', v: Math.round(p.expected_wins * k), prefix: '~' },
    { l: 'Pipeline', v: Math.round(p.expected_pipeline_clp * k), prefix: '$' },
  ] : []
  const pct = (v) => (typeof v === 'number'
    ? (v * 100).toLocaleString('es-CL', { maximumFractionDigits: 1 }) + '%' : '—')
  return (
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <WorkspaceHero eyebrow="Proyección" title={`Forecast de ${client}`}
          description="Explora las respuestas, reuniones y cierres estimados a partir de la actividad comercial registrada."
          icon={TrendingUp}
          aside={ready && data.mode === 'live' ? { label: 'Pipeline proyectado', value: `$${Math.round(p.expected_pipeline_clp * k).toLocaleString('es-CL')}`, detail: `Escenario ${scen} · modelo real` } : undefined} />
      </motion.div>

      <section className="workspace-section">
        <WorkspaceSectionHeading eyebrow="01 / Escenarios" title="Resultado estimado"
          description="Ajusta el escenario para comparar posibles resultados." />
      {gate}
      {!gate && !ready && (
        <Card className="p-5 text-sm text-zinc-600 flex items-center justify-between gap-4" role="alert">
          <span>No se pudo preparar el forecast. Intenta de nuevo cuando el motor esté disponible.</span>
          <Button variant="soft" onClick={() => refetch()}>Reintentar</Button>
        </Card>
      )}
      {ready && <>
      <motion.div className="flex items-center justify-between gap-3 flex-wrap" variants={fade}>
        <Segmented options={SCENARIOS} value={scen} onChange={setScen} />
        <div className="flex items-center gap-2 flex-wrap">
          {/* De dónde salieron estas tasas. `_agent_op` cae al mock cuando el motor real
              falla o devuelve vacío, y manda el modo justo para que se pueda decir; esta
              página lo recibía y lo ignoraba, así que un forecast simulado se veía igual
              que uno real. Mismo patrón que Campanas.jsx y Vender.jsx. */}
          {data?.mode && (
            <Badge color={data.mode === 'live' ? '#16a34a' : '#94a3b8'}>
              {data.mode === 'live' ? 'modelo real' : data.mode === 'base_rates' ? 'tasas base · sin IA' : 'mock · cifras simuladas'}
            </Badge>
          )}
          <span className="text-xs text-zinc-400">
            {scen === 'base'
              ? data.mode === 'base_rates' ? 'Tasas base del sistema, sin ajuste de IA' : 'Tasas estimadas por el ANALYST'
              : `Escenario what-if: ×${k} sobre la base`}
          </span>
        </div>
      </motion.div>
      <motion.div className="grid grid-cols-2 lg:grid-cols-4 gap-4" variants={stagger()} initial="hidden" animate="show">
        {stats.map((s) => (
          <motion.div key={s.l} variants={surface}>
            <Card interactive className="p-5">
              <Eyebrow>{s.l}</Eyebrow>
              <div className="text-[28px] leading-none font-display font-extrabold tracking-tight text-brand mt-2.5 tabular-nums">{s.prefix}<CountUp value={s.v} /></div>
            </Card>
          </motion.div>
        ))}
      </motion.div>
      </>}
      </section>
      {ready && <section className="workspace-section">
        <WorkspaceSectionHeading eyebrow="02 / Origen de los datos" title="Supuestos del cálculo"
          description="Entradas y tasas que sostienen la proyección mostrada." />
      <motion.div variants={surface}>
        <Card className="p-5 text-sm text-zinc-600">
        Embudo: descubiertos {i.discovered} → calificados {i.qualified} → contactados {i.contacted}.<br />
        Tasas: respuesta {pct(a.reply_rate)} · reunión {pct(a.meeting_rate)} · cierre {pct(a.win_rate)} · ticket ${(a.avg_deal_value_clp || 0).toLocaleString('es-CL')} CLP.
        {f.commentary && <div className="mt-3 text-zinc-500 italic">{f.commentary}</div>}
        </Card>
      </motion.div>
      </section>}
    </motion.div>
  )
}
