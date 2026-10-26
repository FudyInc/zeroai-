import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { Columns3 } from 'lucide-react'
import { api } from '../lib/api'
import { STAGES, LANE, scoreColor } from '../lib/util'
import { Skeleton, pageState, StageSelect } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'
import { rise, fade, surface, stagger, staggerDense } from '../lib/motion'
import LeadRoute from '../components/LeadRoute'
import IncomeBadge from '../components/IncomeBadge'
import { WorkspaceHero, WorkspaceSectionHeading } from '../components/WorkspaceHero'
import PipelineRun from '../components/PipelineRun'

/* Columnas del tablero: el camino del lead (LANE) y, al final, las dos salidas. ORDER
   ponía "Descartados" en tercer lugar, en medio del flujo, y a 1440px el ojo leía una
   salida como un paso; aquí las salidas quedan juntas a la derecha. Mismas 9 etapas. */
const BOARD = [...LANE, 'disqualified', 'lost']

const DENSITY = [{ value: 'comodo', label: 'Cómodo' }, { value: 'compacto', label: 'Compacto' }]

export default function Pipeline() {
  const { client, openLead, runId, setRunId, scoped } = useApp()
  const qc = useQueryClient()
  const { data: board, isLoading, error, refetch } = useQuery({ queryKey: ['board', client], queryFn: () => api.board(client), enabled: !!client })
  const drag = useRef(null)           // { key, from }
  const [over, setOver] = useState(null)
  const [dense, setDense] = useState('comodo')
  const compact = dense === 'compacto'

  /* El operador no pasa por Leads: tras "Buscar leads" aterriza acá, así que el avance de
     la corrida se muestra acá (mismo panel que Leads) y, tras un F5, se reengancha con la
     corrida viva de su cliente. Los demás roles siguen viéndolo en Leads. */
  useEffect(() => {
    if (!scoped || runId || !client) return
    let vivo = true
    api.pipelineRuns(10)
      .then((rs) => {
        const activa = rs.find((r) => r.estado === 'corriendo' && r.cliente === client)
        if (vivo && activa) setRunId?.(activa.run)
      })
      .catch(() => { /* sin corridas que recordar: no hay nada que reenganchar */ })
    return () => { vivo = false }
  }, [client, scoped])   // eslint-disable-line react-hooks/exhaustive-deps

  if (!client) return <NoClient />

  const move = async (k, s) => {
    try { await api.moveStage(client, k, s); qc.invalidateQueries(); toast.success('Lead movido a ' + STAGES[s].l) }
    catch (e) { toast.error('No se pudo mover: ' + e.message) }
  }

  const onDrop = (stage) => {
    const d = drag.current
    setOver(null); drag.current = null
    if (d && d.from !== stage) move(d.key, stage)
  }

  // Mapa etapa → leads, y mostramos TODAS las etapas como columnas (para poder
  // soltar incluso en una vacía). El orden lo da BOARD.
  const byStage = Object.fromEntries((board?.stages || []).map((s) => [s.stage, s.leads]))
  const totalLeads = (board?.stages || []).reduce((total, stage) => total + stage.leads.length, 0)

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    skeleton: <div className="flex gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-64 w-64 shrink-0" />)}</div>,
  })
  if (gate) return gate

  return (
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <WorkspaceHero
          eyebrow="Gestión comercial"
          title="Pipeline"
          description={`Sigue el avance de los leads de ${client} y organiza cada oportunidad según su etapa.`}
          icon={Columns3}
          aside={{
            label: 'Leads en el tablero',
            value: totalLeads.toLocaleString('es-CL'),
            detail: `Distribuidos en ${BOARD.length} etapas`,
          }}
        />
      </motion.div>
      {scoped && runId && (
        <div className="mb-4">
          <PipelineRun runId={runId} onFin={() => qc.invalidateQueries({ queryKey: ['board'] })} />
        </div>
      )}

      <section className="workspace-section" aria-label="Tablero de etapas">
        <WorkspaceSectionHeading
          eyebrow="01 / Vista Kanban"
          title="Etapas del pipeline"
          description="Arrastra una tarjeta a otra columna o usa su menú para cambiarla de etapa. Tócala para ver el detalle."
        >
          <Segmented options={DENSITY} value={dense} onChange={setDense} />
        </WorkspaceSectionHeading>
        <motion.div className="flex min-w-0 w-full gap-3 sm:gap-4 overflow-x-auto rounded-2xl border border-zinc-200/70 bg-zinc-50/60 dark:bg-zinc-100/30 p-2 sm:p-3 pb-3" variants={stagger()} initial="hidden" animate="show">
        {BOARD.map((stage) => {
          const m = STAGES[stage] || { l: stage, c: '#94a3b8' }
          const leads = byStage[stage] || []
          const isOver = over === stage
          return (
            <motion.div
              key={stage}
              variants={fade}
              onDragOver={(e) => { e.preventDefault(); if (over !== stage) setOver(stage) }}
              onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver((s) => (s === stage ? null : s)) }}
              onDrop={(e) => { e.preventDefault(); onDrop(stage) }}
              className={
                'flex-1 rounded-xl p-3 transition-colors ' + (compact ? 'min-w-52 ' : 'min-w-60 ') +
                (isOver ? 'bg-champagne/20 ring-2 ring-gold/40' : 'bg-zinc-100/70 dark:bg-zinc-50/70')
              }
            >
              <div className="flex items-center gap-2 mb-3 px-1 text-xs font-semibold uppercase tracking-wide" style={{ color: m.c }}>
                <span className="w-2 h-2 rounded-full" style={{ background: m.c }} />{m.l}
                <span className="ml-auto bg-white dark:bg-zinc-100 text-zinc-500 rounded-full px-2 py-0.5 text-[11px]">{leads.length}</span>
              </div>
              <motion.div className="space-y-2.5 min-h-[60px]" variants={staggerDense()}>
                {leads.map((r) => (
                  <motion.div
                    key={r.key}
                    layout
                    variants={surface}
                    draggable
                    onDragStart={() => { drag.current = { key: r.key, from: stage } }}
                    onDragEnd={() => { drag.current = null; setOver(null) }}
                    onClick={() => openLead(r.key)}
                    className={'cursor-grab active:cursor-grabbing bg-white dark:bg-zinc-50 border border-champagne/50 dark:border-zinc-700/40 rounded-xl shadow-[0_1px_2px_rgba(44,53,41,0.04)] hover:shadow-[0_14px_34px_-18px_rgba(44,53,41,0.20)] hover:-translate-y-0.5 dark:hover:border-zinc-600/60 transition-all ' + (compact ? 'p-3' : 'p-4')}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <div className={'min-w-0 break-words font-semibold ' + (compact ? 'text-sm' : '')}>{r.company}</div>
                      <span className="font-extrabold tabular-nums" style={{ color: scoreColor(r.score) }}>{r.score ?? '—'}</span>
                    </div>
                    {/* Va en ambas densidades: son 4px y en compacto es lo único que
                        queda del recorrido, que es justo cuando más se agradece. */}
                    <LeadRoute lead={r} compact />
                    {!compact && (
                      <>
                        <div className="text-xs text-zinc-500 mt-2">{r.role || '—'}</div>
                        <div className="text-xs text-zinc-400">{r.email || r.phone || '—'}</div>
                        {r.source === 'instagram_ads' && r.income_range && (
                          <div className="text-xs text-zinc-600 mt-2 flex items-center gap-1.5 flex-wrap">
                            <span><span className="font-medium">Renta:</span> {r.income_range}</span>
                            <IncomeBadge ok={r.income_ok} />
                          </div>
                        )}
                        <StageSelect value={r.stage} onClick={(e) => e.stopPropagation()} onChange={(e) => move(r.key, e.target.value)}
                          aria-label={`Etapa de ${r.company}`} className="mt-3" />
                      </>
                    )}
                  </motion.div>
                ))}
                {leads.length === 0 && (
                  <div className="text-[12px] text-zinc-500 text-center py-6 border border-dashed border-zinc-300 rounded-xl">
                    suelta aquí
                  </div>
                )}
              </motion.div>
            </motion.div>
          )
        })}
        </motion.div>
      </section>
    </motion.div>
  )
}
