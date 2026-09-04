import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { CheckCheck, Send, Mail, MessageCircle, ChevronDown } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Skeleton, pageState, SectionTitle, Eyebrow } from '../components/ui'
import { cn } from '../lib/util'
import { rise, fade, surface, stagger } from '../lib/motion'

/* La bandeja de aprobación: todo lo que los agentes redactaron solos y espera
   el visto bueno de una persona (ver la política de borradores en
   zero/config.py::FUNCTION_JOBS_AUTO_SEND — las corridas automáticas nunca
   envían).

   Pensada para el TELÉFONO antes que para el escritorio: es la vista que se
   abre a despachar el trabajo del día desde donde sea, no a analizar. Por eso
   una columna, texto grande, y el cuerpo del mensaje editable en el mismo
   lugar en vez de un modal. */

const CHANNEL_ICON = { email: Mail, whatsapp: MessageCircle }

function DraftCard({ item, onSent }) {
  const o = item.outreach || {}
  const [body, setBody] = useState(o.body || '')
  const [subject, setSubject] = useState(o.subject || '')
  const [open, setOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const Icon = CHANNEL_ICON[o.channel] || Send
  const editado = body !== (o.body || '') || subject !== (o.subject || '')

  const send = async () => {
    if (!body.trim() || sending) return
    setSending(true)
    try {
      await api.sendOutreach(item.client_id, item.key, {
        channel: o.channel, subject: subject || null, body,
      })
      toast.success(`Enviado a ${item.company || item.key}`)
      onSent()
    } catch (e) {
      toast.error('No se pudo enviar: ' + e.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-display text-sm font-semibold tracking-tight text-zinc-800 truncate">
            {item.company || item.key}
          </div>
          <div className="text-xs text-pewter truncate mt-0.5">
            {[item.name, item.role].filter(Boolean).join(' · ') || 'sin contacto identificado'}
          </div>
          <div className="text-[11px] text-pewter mt-1 flex items-center gap-1.5">
            <Icon size={11} className="shrink-0" />
            {o.channel || 'canal sin definir'}
            <span className="text-pewter/60">·</span>
            {item.client_id}
            {item.score != null && <><span className="text-pewter/60">·</span>score {item.score}</>}
          </div>
        </div>
      </div>

      {o.channel === 'email' && (
        <input
          value={subject} onChange={(e) => setSubject(e.target.value)}
          placeholder="Asunto"
          className="mt-3 w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition
                     focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400"
        />
      )}

      {/* Colapsado por defecto en pantallas chicas: con 15 borradores, 15
          textos completos abiertos son imposibles de recorrer con el pulgar. */}
      <button onClick={() => setOpen((v) => !v)}
        className="mt-3 w-full text-left text-xs text-pewter flex items-center gap-1.5 sm:hidden">
        <ChevronDown size={13} className={cn('transition-transform', open && 'rotate-180')} />
        {open ? 'Ocultar mensaje' : 'Ver y editar mensaje'}
      </button>

      <textarea
        value={body} onChange={(e) => setBody(e.target.value)} rows={5}
        className={cn(
          'mt-2 w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition resize-y',
          'focus:ring-4 focus:ring-champagne/40 focus:border-gold/60',
          !open && 'max-sm:hidden',
        )}
      />

      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-[11px] text-pewter">
          {editado ? 'editado' : (o.at ? new Date(o.at).toLocaleDateString('es-CL') : '')}
        </span>
        <Button variant="primary" onClick={send} disabled={sending || !body.trim()}
          className="max-sm:flex-1 max-sm:justify-center">
          <Send size={14} /> {sending ? 'Enviando…' : 'Aprobar y enviar'}
        </Button>
      </div>
    </Card>
  )
}

export default function Aprobar() {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['pending-outreach'],
    queryFn: () => api.pendingOutreach(),
    refetchInterval: 60000,   // llega trabajo solo mientras el panel está abierto
  })

  const gate = pageState({
    isLoading: q.isLoading, error: q.error, onRetry: q.refetch,
    skeleton: <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 w-full" />)}</div>,
  })
  if (gate) return gate

  const items = q.data || []
  const refresh = () => qc.invalidateQueries({ queryKey: ['pending-outreach'] })

  return (
    <motion.div className="space-y-5 max-w-2xl" initial="hidden" animate="show" variants={rise}>
      <motion.div className="flex items-center gap-2" variants={fade}>
        <CheckCheck size={18} className="text-gold-deep" />
        <SectionTitle>Por aprobar</SectionTitle>
      </motion.div>
      <motion.p className="text-sm text-pewter" variants={fade}>
        Lo que los agentes redactaron trabajando solos. Nada de esto se envió: revisa, edita si
        hace falta y aprueba. Lo más antiguo va primero.
      </motion.p>

      {items.length === 0 ? (
        <motion.div variants={fade}>
          <Card className="p-8 text-center">
            <CheckCheck size={22} className="text-pewter mx-auto mb-2" />
            <p className="text-sm font-medium text-zinc-800">Todo despachado.</p>
            <p className="text-xs text-pewter mt-1">
              No hay borradores esperando. Cuando una corrida automática redacte algo, aparece acá.
            </p>
          </Card>
        </motion.div>
      ) : (
        <motion.div className="space-y-3" variants={stagger()} initial="hidden" animate="show">
          <motion.div variants={fade}>
            <Eyebrow>{items.length} esperando</Eyebrow>
          </motion.div>
          {items.map((item) => (
            <motion.div key={`${item.client_id}:${item.key}`} variants={surface}>
              <DraftCard item={item} onSent={refresh} />
            </motion.div>
          ))}
        </motion.div>
      )}
    </motion.div>
  )
}
