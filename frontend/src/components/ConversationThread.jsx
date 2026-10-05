import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
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

const factKinds = [
  ['product', 'Producto'], ['quantity', 'Cantidad'], ['location', 'Comuna o zona'],
  ['measurement', 'Medidas'], ['budget', 'Presupuesto'], ['preference', 'Preferencia'],
]

export default function ConversationThread({ client, leadKey, limit = 100, caseCapture = false }) {
  const qc = useQueryClient()
  const [caseTurn, setCaseTurn] = useState(null)
  const [expected, setExpected] = useState('')
  const [saving, setSaving] = useState(false)
  const [factEditing, setFactEditing] = useState(false)
  const [factDraft, setFactDraft] = useState({})
  const [factsSaving, setFactsSaving] = useState(false)
  useEffect(() => { setCaseTurn(null); setExpected(''); setFactEditing(false) }, [client, leadKey])
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
  const facts = data?.facts || []
  const openFactEditor = () => {
    setFactDraft(Object.fromEntries(facts.map((fact) => [fact.kind, fact.evidence])))
    setFactEditing(true)
  }
  if (turns.length === 0) {
    return <div className="text-sm text-zinc-400 py-4 text-center">Sin conversación registrada aún.</div>
  }

  return (
    <div className="space-y-2">
      {caseCapture && (
        <div className="rounded-xl border border-zinc-200 p-3 mb-3 text-xs">
          <div className="flex items-center justify-between gap-2">
            <b>Datos recordados del contacto</b>
            <button type="button" className="underline text-brand" onClick={openFactEditor}>Revisar datos</button>
          </div>
          {!factEditing && <div className="flex flex-wrap gap-1.5 mt-2">
            {facts.length ? facts.map((fact) => <span key={fact.kind} className="rounded-lg bg-zinc-100 px-2 py-1">
              {factKinds.find(([kind]) => kind === fact.kind)?.[1] || fact.kind}: {fact.evidence}
              {fact.source === 'human' ? ' ✓' : ''}
            </span>) : <span className="text-zinc-400">Todavía no hay datos guardados.</span>}
          </div>}
          {factEditing && <form className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-3" onSubmit={async (event) => {
            event.preventDefault()
            if (factsSaving) return
            setFactsSaving(true)
            try {
              await api.setConversationFacts(client, leadKey, factKinds.map(([kind]) => ({
                kind, evidence: (factDraft[kind] || '').trim(),
              })))
              await qc.invalidateQueries({ queryKey: ['conversation', client, leadKey] })
              setFactEditing(false)
              toast.success('Datos del contacto actualizados')
            } catch (error) { toast.error(error.message) }
            finally { setFactsSaving(false) }
          }}>
            {factKinds.map(([kind, label]) => <label key={kind} className="block text-zinc-600">
              {label}
              <input value={factDraft[kind] || ''} maxLength={120}
                onChange={(event) => setFactDraft((current) => ({ ...current, [kind]: event.target.value }))}
                className="block w-full mt-1 rounded-lg border border-zinc-200 px-2 py-1.5 text-sm" />
            </label>)}
            <div className="sm:col-span-2 flex gap-2">
              <Button type="submit" disabled={factsSaving}>Guardar datos</Button>
              <Button type="button" variant="soft" onClick={() => setFactEditing(false)}>Cancelar</Button>
            </div>
          </form>}
        </div>
      )}
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
              {caseCapture && !fromAgent && (
                <button type="button" className="text-[11px] underline mt-1 text-brand"
                  onClick={() => { setCaseTurn(i); setExpected('') }}>Guardar como caso de prueba</button>
              )}
              {caseCapture && !fromAgent && caseTurn === i && (
                <form className="mt-2 space-y-2" onSubmit={async (event) => {
                  event.preventDefault()
                  if (!expected.trim() || saving) return
                  setSaving(true)
                  try {
                    await api.caseFromConversation(client, leadKey, t.text, expected.trim())
                    qc.invalidateQueries({ queryKey: ['cases', client] })
                    setCaseTurn(null); setExpected('')
                    toast.success('Pregunta agregada al banco de casos')
                  } catch (error) { toast.error(error.message) }
                  finally { setSaving(false) }
                }}>
                  <textarea value={expected} onChange={(event) => setExpected(event.target.value)}
                    maxLength={2000} rows={2} placeholder="Respuesta correcta que debería dar el agente"
                    aria-label="Respuesta esperada" className="w-full rounded-lg border border-zinc-200 p-2 text-sm" />
                  <div className="flex gap-2">
                    <Button type="submit" disabled={!expected.trim() || saving}>Guardar caso</Button>
                    <Button type="button" variant="soft" onClick={() => setCaseTurn(null)}>Cancelar</Button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
