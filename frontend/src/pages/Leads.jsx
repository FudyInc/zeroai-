import { useState, useEffect } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { ChevronRight, Search, Users } from 'lucide-react'
import { api } from '../lib/api'
import { STAGES, scoreColor } from '../lib/util'
import { Card, Skeleton, Button, Input, StageSelect } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { WorkspaceHero, WorkspaceSectionHeading } from '../components/WorkspaceHero'
import { useApp } from '../App'
import { NoClient } from './Dashboard'
import PipelineRun from '../components/PipelineRun'
import { rise, fade, surface, staggerDense } from '../lib/motion'
import { useClientLabel } from '../lib/clientLabels'

const GROUPS = [
  { value: 'todos', label: 'Todos' },
  { value: 'activos', label: 'Activos' },
  { value: 'ganados', label: 'Ganados' },
  { value: 'perdidos', label: 'Perdidos' },
]
const PAGE = 50
const viewKey = (client) => `zero_leads_view_${client}`

function LeadScore({ value }) {
  return <span className="inline-flex items-center gap-1.5 font-semibold tabular-nums">
    <span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ backgroundColor: scoreColor(value) }} />
    {value ?? '—'}
  </span>
}

export default function Leads() {
  const clientLabel = useClientLabel()
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
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <WorkspaceHero eyebrow="CRM" title={`Leads de ${clientLabel(client)}`}
          description="Busca contactos, revisa su calificación y actualiza cada etapa del proceso comercial."
          icon={Users}
          aside={!isLoading && !error ? { label: 'Leads registrados', value: total.toLocaleString('es-CL'), detail: 'Total según el filtro de etapa seleccionado' } : undefined} />
      </motion.div>

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

      <section className="workspace-section">
        <WorkspaceSectionHeading title="Contactos">
          {!isLoading && !error && <span role="status" className="text-xs tabular-nums text-zinc-600">
            {needle ? `${filtrados.length} ${filtrados.length === 1 ? 'coincidencia' : 'coincidencias'} · ` : ''}{leads.length} de {total} cargados
          </span>}
        </WorkspaceSectionHeading>
        <motion.div className="flex flex-wrap items-center gap-3" variants={fade}>
          <div className="relative min-w-0 grow basis-64">
            <Search aria-hidden="true" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <Input type="search" aria-label="Buscar en los contactos cargados" className="pl-9"
              placeholder="Buscar en los contactos cargados…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Segmented label="Filtrar por estado" options={GROUPS} value={group} onChange={setGroup} />
        </motion.div>

        <motion.div variants={surface} className="min-w-0">
          <Card className="overflow-hidden">
            <table aria-label="Contactos del negocio" className="w-full table-fixed text-left text-sm">
              <thead className="bg-zinc-50 text-xs text-zinc-600">
                <tr>
                  <th scope="col" className="px-3 py-3 sm:px-4">Empresa</th>
                  <th scope="col" className="hidden px-4 py-3 lg:table-cell">Contacto</th>
                  <th scope="col" className="hidden w-20 px-3 py-3 sm:table-cell">Score</th>
                  <th scope="col" className="w-36 px-2 py-3 sm:w-40 sm:px-4">Etapa</th>
                </tr>
              </thead>
              <motion.tbody variants={staggerDense()} initial="hidden" animate="show">
                {isLoading && [0, 1, 2, 3, 4].map((i) => (
                  <tr key={i} aria-hidden="true" className="border-t border-zinc-100">
                    <td colSpan={4} className="p-4"><Skeleton className="h-5 w-full" /></td>
                  </tr>
                ))}
                {!isLoading && !error && rows.map((r) => (
                  <motion.tr key={r.key} variants={fade} onClick={() => openLead(r.key)}
                    className="cursor-pointer border-t border-zinc-100 hover:bg-zinc-50 focus-within:bg-zinc-50">
                    <td className="px-3 py-3 sm:px-4">
                      <button type="button" onClick={(e) => { e.stopPropagation(); openLead(r.key) }}
                        aria-label={`Abrir detalle de ${r.company}`}
                        className="inline-flex max-w-full min-h-9 items-center gap-1 rounded text-left font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-gold-deep">
                        <span className="[overflow-wrap:anywhere]">{r.company}</span>
                        <ChevronRight size={14} aria-hidden="true" className="shrink-0 text-gold-deep" />
                      </button>
                      {r.role && <div className="text-xs text-zinc-600 [overflow-wrap:anywhere]">{r.role}</div>}
                      <div className="mt-1 text-xs text-zinc-600 [overflow-wrap:anywhere] lg:hidden">{r.email || r.phone || '—'}</div>
                    </td>
                    <td className="hidden px-4 py-3 text-zinc-600 [overflow-wrap:anywhere] lg:table-cell">{r.email || r.phone || '—'}</td>
                    <td className="hidden px-3 py-3 font-semibold tabular-nums sm:table-cell"><LeadScore value={r.score} /></td>
                    <td className="px-2 py-3 sm:px-4" onClick={(e) => e.stopPropagation()}>
                      <StageSelect className="min-h-9 max-w-full pl-2 pr-6" value={r.stage} onChange={(e) => move(r.key, e.target.value)} aria-label={`Etapa de ${r.company}`} />
                      <div className="mt-1 px-1 text-xs tabular-nums text-zinc-600 sm:hidden">Score <LeadScore value={r.score} /></div>
                    </td>
                  </motion.tr>
                ))}
                {!isLoading && error && (
                  <tr><td colSpan={4} className="px-4 py-10 text-center">
                    <p role="alert" className="text-rose-600 font-medium">No se pudieron cargar los leads.</p>
                    <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
                  </td></tr>
                )}
                {!isLoading && !error && rows.length === 0 && (
                  <tr><td colSpan={4} className="px-4 py-10 text-center text-zinc-600">
                    {filtrados.length ? 'Los contactos que coinciden aparecen en la búsqueda en curso.'
                      : needle ? 'Sin coincidencias entre los contactos cargados.'
                      : group === 'todos' ? 'Este negocio todavía no tiene leads.' : 'Sin leads en este grupo.'}
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
      </section>
    </motion.div>
  )
}
