import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Skeleton, Button } from './ui'

/* El diálogo real turno a turno (lead ⇄ agente), agnóstico de canal — sirve
   igual para WhatsApp, email o el que venga después. Distinto de "Historial"
   (eventos del CRM): esto es lo que realmente se dijeron. */
function formatAt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const isToday = d.toDateString() === new Date().toDateString()
  const time = d.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })
  return isToday ? time : `${d.toLocaleDateString('es-CL', { day: '2-digit', month: '2-digit' })} ${time}`
}

export default function ConversationThread({ client, leadKey, limit = 100 }) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['conversation', client, leadKey, limit],
    queryFn: () => api.conversation(client, leadKey, limit),
    enabled: !!client && !!leadKey,
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-10 w-2/3 ml-auto" />
        <Skeleton className="h-10 w-1/2" />
      </div>
    )
  }
  if (isError) {
    return (
      <div className="text-sm text-rose-600 py-3">
        No se pudo cargar la conversación.
        <button className="underline ml-1" onClick={() => refetch()}>Reintentar</button>
        {error?.message && <div className="text-xs text-zinc-400 mt-0.5">{error.message}</div>}
      </div>
    )
  }

  const turns = data?.turns || []
  if (turns.length === 0) {
    return <div className="text-sm text-zinc-400 py-4 text-center">Sin conversación registrada aún.</div>
  }

  return (
    <div className="space-y-2">
      {turns.map((t, i) => {
        const fromAgent = t.role === 'agent'
        return (
          <div key={i} className={'flex ' + (fromAgent ? 'justify-end' : 'justify-start')}>
            <div className={'max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ' +
              (fromAgent ? 'bg-champagne/40 text-brand-ink' : 'bg-zinc-100 text-zinc-700')}>
              <div>{t.text}</div>
              <div className={'text-[10px] mt-1 ' + (fromAgent ? 'text-gold-deep/70' : 'text-zinc-400')}>
                {formatAt(t.at)}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
