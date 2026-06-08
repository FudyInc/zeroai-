import { useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Search } from 'lucide-react'
import { api } from '../lib/api'
import { STAGES, ORDER, scoreColor } from '../lib/util'
import { Card, Skeleton, Button, Input } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

const GROUPS = [
  { value: 'todos', label: 'Todos' },
  { value: 'activos', label: 'Activos' },
  { value: 'ganados', label: 'Ganados' },
  { value: 'perdidos', label: 'Perdidos' },
]
const PAGE = 50

export default function Leads() {
  const { client, openLead } = useApp()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [group, setGroup] = useState('todos')

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
  const rows = needle
    ? leads.filter((r) => [r.company, r.role, r.email, r.phone].some((x) => (x || '').toLowerCase().includes(needle)))
    : leads

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <Input className="pl-9" placeholder="Buscar en lo cargado…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Segmented options={GROUPS} value={group} onChange={setGroup} />
        {!isLoading && <span className="text-xs text-zinc-400">{leads.length} de {total}</span>}
      </div>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
            <tr>{['Empresa', 'Cargo', 'Contacto', 'Score', 'Etapa'].map((h) => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {isLoading && [0, 1, 2, 3, 4].map((i) => (
              <tr key={i} className="border-t border-zinc-100">
                {[0, 1, 2, 3, 4].map((j) => <td key={j} className="px-5 py-3"><Skeleton className="h-4 w-24" /></td>)}
              </tr>
            ))}

            {!isLoading && !error && rows.map((r) => (
              <tr key={r.key} onClick={() => openLead(r.key)} className="border-t border-zinc-100 hover:bg-zinc-50 cursor-pointer transition-colors">
                <td className="px-5 py-3 font-medium">{r.company}</td>
                <td className="px-5 py-3 text-zinc-500">{r.role || '—'}</td>
                <td className="px-5 py-3 text-zinc-500">{r.email || r.phone || '—'}</td>
                <td className="px-5 py-3 font-extrabold tabular-nums" style={{ color: scoreColor(r.score) }}>{r.score ?? '—'}</td>
                <td className="px-5 py-3" onClick={(e) => e.stopPropagation()}>
                  <select value={r.stage} onChange={(e) => move(r.key, e.target.value)}
                    className="text-xs border border-zinc-200 rounded-lg px-2 py-1 bg-zinc-50 text-zinc-600 outline-none focus:ring-2 focus:ring-emerald-200">
                    {ORDER.map((s) => <option key={s} value={s}>{STAGES[s].l}</option>)}
                  </select>
                </td>
              </tr>
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
          </tbody>
        </table>
      </Card>

      {hasNextPage && (
        <div className="flex justify-center">
          <Button variant="soft" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? 'Cargando…' : `Cargar más (${leads.length} de ${total})`}
          </Button>
        </div>
      )}
    </div>
  )
}
