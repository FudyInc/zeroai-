import { useState, useEffect } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { Search } from 'lucide-react'
import { api } from '../lib/api'
import { STAGES, ORDER, scoreColor } from '../lib/util'
import { Card, Skeleton, Button, Input } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'
import PipelineRun from '../components/PipelineRun'
import { rise, fade, surface, staggerDense } from '../lib/motion'

const GROUPS = [
  { value: 'todos', label: 'Todos' },
  { value: 'activos', label: 'Activos' },
  { value: 'ganados', label: 'Ganados' },
  { value: 'perdidos', label: 'Perdidos' },
]
const PAGE = 50
const viewKey = (client) => `zero_leads_view_${client}`

export default function Leads() {
  const { client, openLead, runId, setRunId } = useApp()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [group, setGroup] = useState('todos')
  /* Las empresas que el panel en vivo está mostrando. Mientras la corrida avanza, esas
     filas se esconden de la tabla del CRM: el pipeline va escribiendo los leads a medida
     que los califica, así que sin esto la misma empresa aparecería arriba como celda y
     abajo como fila. */
  const [enVivo, setEnVivo] = useState([])
  // Recuerda la última búsqueda/filtro por cliente (localStorage) — útil para
  // el equipo: retomar donde quedaste al volver a un cliente, sin re-filtrar.
  const [loadedFor, setLoadedFor] = useState(null)

  useEffect(() => {
    if (!client || loadedFor === client) return
    let saved = null
    try { saved = JSON.parse(localStorage.getItem(viewKey(client)) || 'null') } catch { /* valor corrupto, se ignora */ }
    setGroup(saved?.group || 'todos')
    setQ(saved?.q || '')
    setLoadedFor(client)
  }, [client, loadedFor])

  useEffect(() => {
    if (!client || loadedFor !== client) return
    localStorage.setItem(viewKey(client), JSON.stringify({ group, q }))
  }, [client, loadedFor, group, q])

  /* Reengancha con una corrida que siga viva después de un F5. El backend recuerda las
     últimas 20, así que no hace falta guardar el id en el navegador: se pregunta una vez
     al entrar y solo si no venimos de disparar una recién. */
  useEffect(() => {
    if (runId || !client) return
    let vivo = true
    api.pipelineRuns(10)
      .then((rs) => {
        const activa = rs.find((r) => r.estado === 'corriendo' && r.cliente === client)
        if (vivo && activa) setRunId?.(activa.run)
      })
      .catch(() => { /* sin corridas que recordar: no hay nada que reenganchar */ })
    return () => { vivo = false }
  }, [client])   // eslint-disable-line react-hooks/exhaustive-deps

  const {
    data, isLoading, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['leads', client, group],
    queryFn: ({ pageParam = 0 }) => api.leads(client, { group, limit: PAGE, offset: pageParam }),
    enabled: !!client,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.leads.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })

  if (!client) return <NoClient />

  const move = async (k, s) => {
    try { await api.moveStage(client, k, s); qc.invalidateQueries(); toast.success('Lead movido a ' + STAGES[s].l) }
    catch (e) { toast.error('No se pudo mover: ' + e.message) }
  }

  const leads = data?.pages.flatMap((p) => p.leads) ?? []
  const total = data?.pages[0]?.total ?? 0
  const needle = q.trim().toLowerCase()
  const filtrados = needle
    ? leads.filter((r) => [r.company, r.role, r.email, r.phone].some((x) => (x || '').toLowerCase().includes(needle)))
    : leads
  /* Se comparan normalizados porque el nombre viaja por dos caminos distintos (la
     corrida y el CRM) y basta una mayúscula o un espacio de más para que el mismo lead
     se cuele dos veces. */
  const ocupadas = new Set(enVivo.map((e) => (e || '').trim().toLowerCase()))
  const rows = ocupadas.size
    ? filtrados.filter((r) => !ocupadas.has((r.company || '').trim().toLowerCase()))
    : filtrados

  return (
    <motion.div className="space-y-5" initial="hidden" animate="show" variants={rise}>
      {runId && (
        <PipelineRun
          runId={runId}
          onEmpresas={setEnVivo}
          onFin={() => {
            /* El pipeline ya escribió estos leads en el CRM; recargar la tabla es lo que
               permite soltar las celdas en vivo sin que nada desaparezca de la pantalla. */
            qc.invalidateQueries({ queryKey: ['leads'] })
            setEnVivo([])
          }}
        />
      )}

      <motion.div className="flex flex-wrap items-center gap-2" variants={fade}>
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <Input className="pl-9" placeholder="Buscar en lo cargado…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Segmented options={GROUPS} value={group} onChange={setGroup} />
        {!isLoading && <span className="text-xs text-zinc-400">{leads.length} de {total}</span>}
      </motion.div>

      <motion.div variants={surface}>
        <Card className="overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
            <tr>{['Empresa', 'Cargo', 'Contacto', 'Score', 'Etapa'].map((h) => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr>
          </thead>
          <motion.tbody variants={staggerDense()} initial="hidden" animate="show">
            {isLoading && [0, 1, 2, 3, 4].map((i) => (
              <tr key={i} className="border-t border-zinc-100">
                {[0, 1, 2, 3, 4].map((j) => <td key={j} className="px-5 py-3"><Skeleton className="h-4 w-24" /></td>)}
              </tr>
            ))}

            {!isLoading && !error && rows.map((r) => (
              <motion.tr key={r.key} variants={fade}
                onClick={() => openLead(r.key)} className="border-t border-zinc-100 hover:bg-zinc-50 cursor-pointer transition-colors">
                <td className="px-5 py-3 font-medium">{r.company}</td>
                <td className="px-5 py-3 text-zinc-500">{r.role || '—'}</td>
                <td className="px-5 py-3 text-zinc-500">{r.email || r.phone || '—'}</td>
                <td className="px-5 py-3 font-extrabold tabular-nums" style={{ color: scoreColor(r.score) }}>{r.score ?? '—'}</td>
                <td className="px-5 py-3" onClick={(e) => e.stopPropagation()}>
                  <select value={r.stage} onChange={(e) => move(r.key, e.target.value)}
                    className="text-xs border border-zinc-200 rounded-lg px-2 py-1 bg-zinc-50 text-zinc-600 outline-none focus:ring-2 focus:ring-champagne">
                    {ORDER.map((s) => <option key={s} value={s}>{STAGES[s].l}</option>)}
                  </select>
                </td>
              </motion.tr>
            ))}

            {!isLoading && error && (
              <tr><td colSpan={5} className="px-5 py-12 text-center">
                <p className="text-rose-600 font-medium">No se pudieron cargar los leads.</p>
                <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
              </td></tr>
            )}
            {!isLoading && !error && rows.length === 0 && (
              <tr><td colSpan={5} className="px-5 py-10 text-center text-zinc-400">
                {total ? 'Ningún lead coincide.' : 'Sin leads. Usá “Buscar leads”.'}
              </td></tr>
            )}
          </motion.tbody>
        </table>
        </Card>
      </motion.div>

      {hasNextPage && (
        <motion.div className="flex justify-center" variants={fade}>
          <Button variant="soft" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? 'Cargando…' : `Cargar más (${leads.length} de ${total})`}
          </Button>
        </motion.div>
      )}
    </motion.div>
  )
}
