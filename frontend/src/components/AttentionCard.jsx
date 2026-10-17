import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { MessageSquareText, CheckCheck, ChevronDown, Send, Lightbulb, X } from 'lucide-react'
import { api } from '../lib/api'
import { timeAgo } from '../lib/whatsapp-attention'
import { Card, Button, Badge, Select, Skeleton } from './ui'

/* Módulo «Atención»: lo que el agente no pudo resolver. Solo lo ve el equipo.
   Un caso se cierra de tres maneras: respondiendo (se envía al cliente y el agente
   lo aprende), enseñando un sinónimo, o descartándolo / marcándolo atendido. */

const TYPE = {
  pregunta: { label: 'Pregunta', color: '#b45309' },
  pedido: { label: 'Pedido', color: '#0f766e' },
}

export default function AttentionCard({ client }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [showLearned, setShowLearned] = useState(false)
  const attn = useQuery({
    queryKey: ['whatsapp-attention', client, 'all'], queryFn: () => api.whatsappAttention(client, true),
    enabled: !!client, refetchInterval: 30000, retry: false,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['whatsapp-attention', client] })

  const openChat = (chatId) => {
    nav('/whatsapp', { state: { waChat: chatId, client } })
    document.getElementById('wa-bandeja')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (attn.isLoading) return <Skeleton className="h-40" />
  if (attn.isError) return (
    <Card className="wa-attn-empty">
      <p>No se pudo cargar la atención pendiente: {attn.error?.message || 'error desconocido'}.</p>
      <Button variant="soft" onClick={() => attn.refetch()}>Reintentar</Button>
    </Card>
  )

  const items = attn.data?.items || []
  const options = attn.data?.options || []
  const open = items.filter((i) => i.estado === 'abierta')
  const learned = items.filter((i) => i.estado === 'resuelta')

  return (
    <div className="wa-attn">
      {open.length === 0 ? (
        <Card className="wa-attn-empty">
          <CheckCheck size={20} />
          <p>El agente resolvió todo lo que le llegó.</p>
        </Card>
      ) : (
        <div className="wa-attn-list">
          {open.map((item) => (
            <CaseRow key={item.clave} item={item} client={client} options={options} onDone={refresh} onOpenChat={openChat} />
          ))}
        </div>
      )}

      {learned.length > 0 && (
        <div className="wa-attn-learned">
          <button type="button" className="wa-attn-learned-toggle" aria-expanded={showLearned} onClick={() => setShowLearned((v) => !v)}>
            <ChevronDown size={15} className={showLearned ? 'is-open' : ''} /> Aprendidas ({learned.length})
          </button>
          {showLearned && (
            <ul>
              {learned.map((item) => (
                <li key={item.clave}>
                  <q>{item.pregunta}</q>
                  <span className="wa-attn-arrow" aria-hidden="true">→</span>
                  {item.estado === 'descartada' ? <em>Descartada</em>
                    : item.equivale ? <span>equivale a «{item.equivale}»</span>
                    : <span>{item.respuesta || 'Atendida'}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function CaseRow({ item, client, options, onDone, onOpenChat }) {
  const [text, setText] = useState('')
  const [option, setOption] = useState('')
  const isQuestion = item.tipo !== 'pedido'
  const type = TYPE[item.tipo] || TYPE.pregunta
  const who = item.contacto || 'el cliente'

  const answer = useMutation({
    mutationFn: () => api.answerAttention(client, item.clave, text.trim()),
    onSuccess: (r) => {
      const to = r?.sent_count > 1 ? `${r.sent_count} clientes que esperaban` : who
      if (!r?.sent) toast.warning(r?.learned ? 'Respuesta aprendida, pero no se envió' : 'Caso cerrado, pero no se envió',
        { description: 'El caso no tiene un chat asociado; escríbele al cliente por tu cuenta.' })
      else toast.success(r.learned ? `Respuesta enviada a ${to} y aprendida` : `Respuesta enviada a ${who}`)
      setText('')
      onDone()
    },
    onError: (e) => toast.error('No se pudo enviar: ' + e.message),
  })
  const alias = useMutation({
    mutationFn: () => api.aliasAttention(client, item.clave, option),
    onSuccess: () => { toast.success('Sinónimo enseñado: el agente ya lo entiende'); setOption(''); onDone() },
    onError: (e) => toast.error('No se pudo enseñar el sinónimo: ' + e.message),
  })
  const dismiss = useMutation({
    mutationFn: () => api.dismissAttention(client, item.clave),
    onSuccess: () => { toast.success(isQuestion ? 'Caso descartado' : 'Caso marcado como atendido'); onDone() },
    onError: (e) => toast.error('No se pudo actualizar el caso: ' + e.message),
  })
  const busy = answer.isPending || alias.isPending || dismiss.isPending

  return (
    <Card className="wa-attn-case">
      <div className="wa-attn-head">
        <Badge color={type.color}>{type.label}</Badge>
        {item.veces > 1 && <span className="wa-attn-repeat">Se repitió {item.veces} veces</span>}
        <span className="wa-attn-when">{[item.contacto, timeAgo(item.ultima)].filter(Boolean).join(' · ')}</span>
        {item.chat_id && (
          <Button variant="soft" className="wa-attn-open" onClick={() => onOpenChat(item.chat_id)}>
            <MessageSquareText size={14} /> Abrir chat
          </Button>
        )}
      </div>
      <blockquote className="wa-attn-question">«{item.pregunta}»</blockquote>
      {item.reason && <p className="wa-attn-reason">{item.reason}</p>}

      <div className="wa-attn-actions">
        <label className="wa-attn-label" htmlFor={`wa-attn-r-${item.clave}`}>
          {item.chat_id ? `Respuesta para ${who}` : 'Respuesta (este caso no tiene chat asociado)'}
        </label>
        <textarea id={`wa-attn-r-${item.clave}`} rows={3} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Escribe cómo debería responder el agente…" disabled={busy} />
        <div className="wa-attn-buttons">
          <Button disabled={!text.trim() || busy} onClick={() => answer.mutate()}>
            <Send size={14} /> {answer.isPending ? 'Enviando…' : isQuestion ? 'Enviar y enseñar' : 'Enviar al cliente'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => dismiss.mutate()}>
            <X size={14} /> {isQuestion ? 'Descartar' : 'Marcar atendido'}
          </Button>
        </div>
        {isQuestion && options.length > 0 && (
          <div className="wa-attn-alias">
            <label className="wa-attn-label" htmlFor={`wa-attn-o-${item.clave}`}>Equivale a…</label>
            <div>
              <Select id={`wa-attn-o-${item.clave}`} value={option} onChange={(e) => setOption(e.target.value)} disabled={busy}>
                <option value="">Elige una opción del flujo</option>
                {options.map((g) => (
                  <optgroup key={g.pregunta} label={g.pregunta}>
                    {g.opciones.map((o) => <option key={o} value={o}>{o}</option>)}
                  </optgroup>
                ))}
              </Select>
              <Button variant="soft" disabled={!option || busy} onClick={() => alias.mutate()}>
                <Lightbulb size={14} /> Enseñar sinónimo
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
