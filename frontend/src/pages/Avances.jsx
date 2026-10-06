import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Clock3, Lightbulb, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import { Button, Card, SectionTitle } from '../components/ui'

const FILTERS = [
  ['todos', 'Todos'],
  ['input', 'Tus pedidos'],
  ['decision', 'Decisiones'],
  ['change', 'Cambios'],
]

const TYPE_LABEL = { input: 'Pedido', decision: 'Decisión', change: 'Cambio' }

export default function Avances() {
  const [filter, setFilter] = useState('todos')
  const { data: entries = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['avances'], queryFn: api.avances,
  })
  const visible = filter === 'todos' ? entries : entries.filter((entry) => entry.type === filter)

  return <div className="max-w-4xl space-y-5">
    <div className="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <SectionTitle>Avances</SectionTitle>
        <p className="text-sm text-zinc-500 mt-1">Tus pedidos, las decisiones tomadas y lo que quedó comprobado.</p>
      </div>
      <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>
        <RefreshCw size={15} className={isFetching ? 'animate-spin' : ''} /> Actualizar
      </Button>
    </div>

    <Card className="p-4 text-sm text-zinc-600">
      Cada avance indica dónde se verificó. «Código local» no significa que el cambio ya esté activo en producción.
    </Card>

    <div className="flex gap-2 flex-wrap" role="group" aria-label="Filtrar avances">
      {FILTERS.map(([value, label]) => <button key={value} type="button" onClick={() => setFilter(value)}
        aria-pressed={filter === value}
        className={`rounded-full px-3 py-1.5 text-xs font-semibold border transition-colors ${filter === value
          ? 'bg-zinc-900 text-white border-zinc-900'
          : 'bg-white text-zinc-600 border-zinc-200 hover:border-zinc-400'}`}>
        {label}
      </button>)}
    </div>

    {isLoading && <p className="text-sm text-zinc-500">Cargando avances…</p>}
    {error && <Card className="p-5 text-sm text-red-700" role="alert">
      No se pudo cargar el registro: {error.message}. <button className="underline" onClick={() => refetch()}>Reintentar</button>
    </Card>}
    {!isLoading && !error && visible.length === 0 && <Card className="p-6 text-sm text-zinc-500">
      No hay avances en esta categoría.
    </Card>}

    <div className="space-y-3">
      {visible.map((entry) => <Card key={entry.id} className="p-5 space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3 min-w-0">
            <span className="mt-0.5 rounded-lg bg-amber-50 text-amber-700 p-2 shrink-0">
              {entry.type === 'input' ? <Lightbulb size={17} /> : entry.status.startsWith('verificado')
                ? <CheckCircle2 size={17} /> : <Clock3 size={17} />}
            </span>
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                <time dateTime={entry.date}>{entry.date}</time> · {TYPE_LABEL[entry.type] || entry.type}
              </div>
              <h2 className="font-semibold text-zinc-900 mt-1">{entry.title}</h2>
            </div>
          </div>
          <span className="rounded-full px-2.5 py-1 text-xs font-medium bg-zinc-100 text-zinc-700">
            {entry.status}
          </span>
        </div>
        <p className="text-sm text-zinc-700">{entry.summary}</p>
        <dl className="grid gap-2 text-xs text-zinc-600 sm:grid-cols-2 border-t border-zinc-100 pt-3">
          <div><dt className="font-semibold text-zinc-800">Origen</dt><dd>{entry.origin}</dd></div>
          <div><dt className="font-semibold text-zinc-800">Comprobado en</dt><dd>{entry.scope}</dd></div>
          <div><dt className="font-semibold text-zinc-800">Evidencia</dt><dd className="break-words">{entry.evidence}</dd></div>
          {entry.pending && <div><dt className="font-semibold text-zinc-800">Pendiente</dt><dd>{entry.pending}</dd></div>}
        </dl>
      </Card>)}
    </div>
  </div>
}
