import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Button, Card } from './ui'

export default function PoolEdgeExcelReview({ client }) {
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['pooledge-excel-review', client],
    queryFn: () => api.pooledgeExcelReview(client),
    refetchInterval: 60_000,
    retry: false,
  })

  return <section aria-labelledby="excel-review-heading">
    <Card className="space-y-2 p-4">
      <h2 id="excel-review-heading" className="font-semibold">Presupuestos de Vendidos Diego</h2>
      {isLoading && <p className="text-sm">Consultando revisiones del Excel…</p>}
      {error && <div className="flex items-center gap-3 text-sm" role="alert">
        El informe del Excel está fuera de servicio.
        <Button variant="secondary" onClick={() => refetch()}>Reintentar</Button>
      </div>}
      {data && !error && <>
        <p className="text-xs text-zinc-600">
          Última revisión del importador · <time dateTime={data.updated_at}>
            {new Date(data.updated_at).toLocaleString('es-CL')}
          </time>
        </p>
        {data.issues.length ? <>
          <p className="text-sm font-medium">Revisa estos pedidos antes de actualizar el Excel.</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.issues.map(({ order_id, reason }) =>
              <li key={order_id + reason}><strong>{order_id}</strong> · {reason}</li>)}
          </ul>
        </> : <p className="text-sm">Sin discrepancias en la última revisión.</p>}
      </>}
    </Card>
  </section>
}
