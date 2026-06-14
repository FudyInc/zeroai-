import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Gift } from 'lucide-react'
import { api } from '../lib/api'
import { Badge, Skeleton, Button } from './ui'
import { STAGES, scoreColor } from '../lib/util'

// El historial del CRM (zero/crm.py) ya trae la conversación real: cuando un lead
// responde, `handle_inbound` (zero/orchestrator.py) registra el texto del lead
// (evento "stage" → replied, detalle entre paréntesis) y la respuesta de CONCIERGE
// (evento "auto_reply" / "info_sent"). Acá lo reordenamos como timeline de chat —
// sin inventar datos, solo leyendo lo que el backend ya guarda.
function buildTimeline(r) {
  const msgs = []
  if (r.outreach?.body) {
    msgs.push({
      who: 'zero',
      text: r.outreach.body,
      tag: 'primer contacto · ' + (r.outreach.channel || r.channel || ''),
      ts: r.created,
    })
  }
  for (const h of r.history || []) {
    if (h.event === 'stage' && /→ replied/.test(h.detail || '')) {
      const m = /\(([^)]*)\)\s*$/.exec(h.detail || '')
      if (m) msgs.push({ who: 'lead', text: m[1], ts: h.ts })
    } else if (h.event === 'auto_reply') {
      msgs.push({ who: 'zero', text: h.detail, tag: 'CONCIERGE', ts: h.ts })
    } else if (h.event === 'info_sent') {
      msgs.push({ who: 'zero', text: h.detail, tag: 'oferta cumplida', ts: h.ts, gift: true })
    }
  }
  return msgs
}

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString('es-CL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// Modal con el historial de conversación de un lead (estilo chat), para revisar
// qué dijo y cómo respondió el agente. Se abre desde la Actividad reciente de
// /whatsapp.
export default function ChatDetailModal({ client, leadKey, onClose }) {
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
            className="bg-white rounded-2xl max-w-lg w-full max-h-[85vh] flex flex-col overflow-hidden"
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            onClick={(e) => e.stopPropagation()}
          >
            {isLoading ? (
              <div className="p-6 space-y-3">
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-32 w-full" />
              </div>
            ) : error ? (
              <div className="p-6 py-12 text-center">
                <p className="text-rose-600 font-medium">No se pudo cargar la conversación.</p>
                <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
              </div>
            ) : r ? (
              <ChatBody r={r} onClose={onClose} />
            ) : null}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function ChatBody({ r, onClose }) {
  const stg = STAGES[r.stage] || { l: r.stage, c: '#94a3b8' }
  const msgs = buildTimeline(r)
  return (
    <>
      <div className="flex justify-between items-start gap-3 p-5 pb-3 border-b border-zinc-100">
        <div className="min-w-0">
          <div className="font-bold truncate">{r.company || r.name || r.key}</div>
          <div className="text-xs text-zinc-500 mt-0.5 truncate">
            {r.name && r.company ? r.name + ' · ' : ''}{r.phone || r.email || '—'}
          </div>
          <div className="flex items-center gap-1.5 mt-1.5">
            <Badge color={stg.c}>{stg.l}</Badge>
            <span className="text-xs font-extrabold" style={{ color: scoreColor(r.score) }}>
              score {r.score == null ? '—' : r.score}
            </span>
          </div>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700 transition shrink-0"><X size={20} /></button>
      </div>

      <div className="p-5 space-y-3 overflow-auto flex-1">
        {msgs.length === 0 ? (
          <div className="text-sm text-zinc-400 text-center py-10">
            Sin conversación todavía — cuando el lead escriba por WhatsApp, su mensaje y la respuesta del
            agente aparecerán aquí.
          </div>
        ) : msgs.map((m, i) => (
          <div key={i} className={'flex ' + (m.who === 'lead' ? 'justify-start' : 'justify-end')}>
            <div className={'max-w-[80%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap ' +
              (m.who === 'lead'
                ? 'bg-zinc-100 text-zinc-700'
                : m.gift
                  ? 'bg-champagne/35 text-gold-deep border border-champagne'
                  : 'bg-brand-grad text-white')}>
              {m.gift && <Gift size={13} className="inline -mt-0.5 mr-1.5" />}
              {m.text}
              <div className={'text-[10px] mt-1 ' +
                (m.who === 'lead' ? 'text-zinc-400' : m.gift ? 'text-gold-deep/70' : 'text-white/70')}>
                {m.tag ? m.tag + ' · ' : ''}{fmtTime(m.ts)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
