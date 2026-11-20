import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Badge, Button, Card } from './ui'

const states = {
  applied: { label: 'Aplicado al Excel', color: '#166534' },
  queued: { label: 'En cola', color: '#1e40af' },
  review: { label: 'Requiere revisión', color: '#9a3412' },
}

const clp = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP' })
const quantity = new Intl.NumberFormat('es-CL')
const date = new Intl.DateTimeFormat('es-CL', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'America/Santiago',
})

function Timestamp({ at }) {
  return <time dateTime={at}>{date.format(new Date(at))}</time>
}

function amounts(snapshot) {
  return [
    snapshot.pieces == null ? null : `${quantity.format(snapshot.pieces)} ${snapshot.pieces === 1 ? 'pieza' : 'piezas'}`,
    snapshot.total == null ? null : clp.format(snapshot.total),
  ].filter(Boolean).join(' · ')
}

function OrderRow({ order }) {
  const { order_id: id, status, current, pending, reason, history } = order
  const state = states[status]
  return <li className="space-y-2 py-3 text-sm">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h3 className="font-semibold tabular-nums">{id}</h3>
      <Badge color={state.color}>{state.label}</Badge>
    </div>
    {current && <div>
      <p className="tabular-nums">
        <span className="font-medium">En Excel</span> · {amounts(current)}
      </p>
      {current.at && <p className="text-xs text-zinc-600">Última actualización · <Timestamp at={current.at} /></p>}
    </div>}
    {pending && <p className="tabular-nums">
      <span className="font-medium">Pendiente de sincronizar</span> · {amounts(pending)}
    </p>}
    {status === 'queued' && <p className="text-xs text-zinc-600">Se aplicará en el próximo ciclo con el Excel cerrado.</p>}
    {reason && <p>{reason}</p>}
    {history.length > 0 && <details>
      <summary className="w-fit cursor-pointer rounded text-gold-deep underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-offset-2" aria-label={`Historial de ${id}`}>
        Historial ({history.length})
      </summary>
      <ol className="mt-2 space-y-2 border-l border-champagne pl-3">
        {history.map((revision, index) => <li key={`${revision.at}-${index}`}>
          <p className="text-xs text-zinc-600"><Timestamp at={revision.at} /></p>
          {amounts(revision) && <p className="tabular-nums">{amounts(revision)}</p>}
          {revision.reason && <p>{revision.reason}</p>}
        </li>)}
      </ol>
    </details>}
  </li>
}

export default function PoolEdgeExcelReview({ client }) {
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['pooledge-excel-review', client],
    queryFn: () => api.pooledgeExcelReview(client),
    refetchInterval: 60_000,
    retry: false,
  })
  const orders = data?.orders ?? data?.issues.map(({ order_id, reason }) => ({
    order_id, reason, status: 'review', history: [],
  }))
  const empty = data?.orders ? 'Aún no hay presupuestos registrados.' : 'Sin discrepancias en la última revisión.'

  return <section aria-labelledby="excel-review-heading">
    <Card className="space-y-2 p-4">
      <h2 id="excel-review-heading" className="font-semibold">Presupuestos de Vendidos Diego</h2>
      {isLoading && <p className="text-sm">Consultando el estado del Excel…</p>}
      {error && <div className="flex items-center gap-3 text-sm" role="alert">
        El informe del Excel está fuera de servicio.
        <Button variant="soft" onClick={() => refetch()}>Reintentar</Button>
      </div>}
      {data && !error && <>
        <p className="text-xs text-zinc-600">
          Última revisión del importador · <Timestamp at={data.updated_at} />
        </p>
        {orders.length ? <ul className="divide-y divide-champagne/50">
          {orders.map(order => <OrderRow key={order.order_id} order={order} />)}
        </ul> : <p className="text-sm">{empty}</p>}
      </>}
    </Card>
  </section>
}
