import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { X, MessageSquareReply, Send } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { STAGES, scoreColor } from '../lib/util'
import { Badge, Skeleton, Button, Input } from './ui'
import ConversationThread from './ConversationThread'

// Stages where the lead has been contacted but hasn't replied yet → offer to log a reply.
const REPLYABLE = new Set(['contacted', 'nurturing'])

export default function LeadModal({ client, leadKey, onClose }) {
  const open = !!leadKey
  const { data: r, isLoading, error, refetch } = useQuery({
    queryKey: ['lead', client, leadKey],
    queryFn: () => api.lead(client, leadKey),
    enabled: open,
  })

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="bg-white rounded-2xl max-w-lg w-full max-h-[85vh] overflow-auto p-6"
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            onClick={(e) => e.stopPropagation()}
          >
            {isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-24 w-full" />
              </div>
            ) : error ? (
              <div className="py-12 text-center">
                <p className="text-rose-600 font-medium">No se pudo cargar el lead.</p>
                <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
              </div>
            ) : r ? (
              <LeadBody r={r} client={client} onClose={onClose} />
            ) : null}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function LeadBody({ r, client, onClose }) {
  const stg = STAGES[r.stage] || { l: r.stage, c: '#94a3b8' }
  const o = r.outreach
  return (
    <>
      <div className="flex justify-between items-start gap-3">
        <div>
          <div className="text-lg font-bold">{r.company}</div>
          <div className="text-sm text-zinc-500">{r.role || '—'}</div>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700 transition"><X size={20} /></button>
      </div>

      <div className="flex items-center gap-2 mt-2">
        <Badge color={stg.c}>{stg.l}</Badge>
        <span className="text-sm font-extrabold" style={{ color: scoreColor(r.score) }}>
          score {r.score == null ? '—' : r.score}
        </span>
      </div>

      <div className="text-sm text-zinc-600 mt-3">{r.email || r.phone || '—'} · canal {r.channel || '—'}</div>

      {r.icp_reasons?.length > 0 && (
        <div className="mt-4">
          <div className="text-xs uppercase tracking-wide text-zinc-400 mb-1">Por qué calificó</div>
          <ul className="text-sm text-zinc-600 list-disc pl-5 space-y-0.5">
            {r.icp_reasons.map((x, i) => <li key={i}>{x}</li>)}
          </ul>
        </div>
      )}

      {o && o.status === 'draft' ? (
        <PendingOutreach o={o} r={r} client={client} />
      ) : o && (
        <div className="mt-4 border border-zinc-200 rounded-xl p-3 bg-zinc-50/80">
          <div className="text-xs uppercase tracking-wide text-zinc-400 mb-1">Primer mensaje · {o.channel}</div>
          {o.subject && <div className="text-sm font-medium">{o.subject}</div>}
          <div className="text-sm text-zinc-600 mt-1 whitespace-pre-wrap">{o.body}</div>
        </div>
      )}

      {REPLYABLE.has(r.stage) && <ReplyAction r={r} client={client} />}

      <div className="mt-4">
        <div className="text-xs uppercase tracking-wide text-zinc-400 mb-2">Historial</div>
        <div className="space-y-1.5">
          {(r.history || []).map((h, i) => (
            <div key={i} className="text-sm flex gap-2">
              <span className="text-zinc-400 tabular-nums shrink-0">{(h.ts || '').slice(11, 16)}</span>
              <span className="text-zinc-600">{h.event}{h.detail ? ' · ' + h.detail : ''}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4">
        <div className="text-xs uppercase tracking-wide text-zinc-400 mb-2">Conversación</div>
        <ConversationThread client={client} leadKey={r.key} />
      </div>
    </>
  )
}

// El primer mensaje quedó redactado pero SIN mandar (modo revisión, auto_send=false
// en "Buscar leads") — se puede editar la copia antes de aprobarla y mandarla.
function PendingOutreach({ o, r, client }) {
  const qc = useQueryClient()
  const [subject, setSubject] = useState(o.subject || '')
  const [body, setBody] = useState(o.body || '')

  const send = useMutation({
    mutationFn: () => api.sendOutreach(client, r.key, { channel: o.channel, subject, body }),
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: ['lead', client, r.key] })
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      if (out?.result?.status === 'sent') toast.success('Mensaje enviado')
      else toast.error('No se pudo enviar: ' + (out?.result?.error || 'error desconocido'))
    },
    onError: (e) => toast.error('No se pudo enviar: ' + e.message),
  })

  return (
    <div className="mt-4 border border-champagne bg-champagne/20 rounded-xl p-3">
      <div className="text-xs uppercase tracking-wide text-gold-deep mb-1.5">
        Borrador · {o.channel} — pendiente de revisión
      </div>
      {o.subject != null && (
        <Input value={subject} onChange={(e) => setSubject(e.target.value)}
          placeholder="Asunto" className="mb-2 w-full" />
      )}
      <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5}
        className="w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 resize-y" />
      {send.isError && <div className="text-sm text-rose-600 mt-2">{send.error.message}</div>}
      <div className="flex justify-end mt-2">
        <Button variant="accent" onClick={() => send.mutate()} disabled={send.isPending || !body.trim()}>
          <Send size={14} /> {send.isPending ? 'Enviando…' : 'Enviar'}
        </Button>
      </div>
    </div>
  )
}

// Closes the loop: the lead replied → stop follow-ups and move it to `replied`.
function ReplyAction({ r, client }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const m = useMutation({
    mutationFn: () => api.reply(client, r.key, { text: text.trim() || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['lead', client, r.key] })
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
    },
  })
  return (
    <div className="mt-4 border border-champagne bg-champagne/30 rounded-xl p-3">
      <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-gold-deep mb-1.5">
        <MessageSquareReply size={13} /> El lead respondió
      </div>
      <p className="text-xs text-zinc-500 mb-2">Lo movemos a <b>respondió</b> y detenemos los seguimientos automáticos.</p>
      <Input value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Nota de la respuesta (opcional)" className="mb-2 w-full" />
      {m.isError && <div className="text-sm text-rose-600 mb-2">{m.error.message}</div>}
      <Button variant="accent" onClick={() => m.mutate()} disabled={m.isPending}>
        {m.isPending ? 'Registrando…' : 'Registrar respuesta'}
      </Button>
    </div>
  )
}
