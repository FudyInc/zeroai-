import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

const format = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'USD', currencyDisplay: 'code', minimumFractionDigits: 2 })
const date = (value) => new Date(value).toLocaleString('es-CL', { dateStyle: 'short', timeStyle: 'short' })

export default function ClaudeCredit() {
  const cache = useQueryClient()
  const query = useQuery({ queryKey: ['pooledge-claude-credit'], queryFn: api.claudeCredit, refetchInterval: 300000 })
  const [editing, setEditing] = useState(false)
  const data = query.data
  const save = useMutation({
    mutationFn: api.saveClaudeCredit,
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ['pooledge-claude-credit'] })
      setEditing(false)
    },
  })
  const hasBalance = data?.capacity > 0
  const percent = hasBalance ? 100 * data.available / data.capacity : 0
  const stale = data?.state === 'billing_stale'
  const level = stale ? 'Sin actualizar' : percent <= 10 ? 'Crítico' : percent <= 30 ? 'Bajo' : 'Disponible'
  const color = stale ? '#aab1ac' : percent <= 10 ? '#ff776a' : percent <= 30 ? '#edbc4d' : '#63d99a'
  return <section className="wa-hero-progress wa-credit" aria-label="Crédito de Claude API">
    <span>Crédito de Claude API · PoolEdge</span>
    {query.isLoading ? <p>Consultando saldo…</p> : query.isError ? <p role="alert">No se pudo consultar el saldo.</p> :
      hasBalance ? <>
        <strong>{format.format(data.available)}</strong>
        <div role="meter" aria-label="Saldo respecto al cupo" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={Math.min(100, Math.round(percent))} className="wa-progress-track">
          <div style={{ width: Math.min(percent, 100) + '%', background: color }} />
        </div>
        <p>{level} · {Math.round(percent)} % del cupo de {format.format(data.capacity)}</p>
        <small>{data.state === 'estimated' ? 'Estimado al ' + date(data.through) :
          'Último saldo registrado el ' + date(data.at)}</small>
        {data.state === 'billing' && <small>Saldo verificado automáticamente en Claude Billing.</small>}
        {stale && <small>Sin lectura reciente. Comprueba la ventana de Billing en Brave.</small>}
        {data.state === 'unavailable' && <small>Consulta de costos no disponible.</small>}
        {data.state === 'recorded' && <small>Actualización manual.</small>}
      </> : <p>Saldo pendiente de registrar.</p>}
    <a href="https://platform.claude.com/settings/billing" target="_blank" rel="noreferrer">Ver saldo en Claude ↗</a>
    {!editing && !query.isLoading && !query.isError && <button type="button" onClick={() => setEditing(true)}>
      {hasBalance ? 'Actualizar saldo' : 'Registrar saldo'}</button>}
    {editing && <form className="grid gap-2" onSubmit={event => {
      event.preventDefault()
      const values = new FormData(event.currentTarget)
      save.mutate({ available: Number(values.get('available')), capacity: Number(values.get('capacity')) })
    }}>
      <label>Saldo actual (USD)<input type="number" name="available" min="0" step=".01" required defaultValue={data?.available} /></label>
      <label>Cupo de referencia (USD)<input type="number" name="capacity" min=".01" step=".01" required defaultValue={data?.capacity} /></label>
      {save.isError && <p role="alert">{save.error.message}</p>}
      <button type="submit" disabled={save.isPending}>Guardar saldo</button>
      <button type="button" onClick={() => setEditing(false)}>Cancelar</button>
    </form>}
  </section>
}
