import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import { STAGES, scoreColor } from '../lib/util'
import { Badge, Spinner } from './ui'

export default function LeadModal({ client, leadKey, onClose }) {
  const open = !!leadKey
  const { data: r, isLoading } = useQuery({
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
            {isLoading || !r ? (
              <div className="py-16 grid place-items-center text-zinc-400"><Spinner /></div>
            ) : (
              <LeadBody r={r} onClose={onClose} />
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function LeadBody({ r, onClose }) {
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

      {o && (
        <div className="mt-4 border border-zinc-200 rounded-xl p-3 bg-zinc-50/80">
          <div className="text-xs uppercase tracking-wide text-zinc-400 mb-1">Primer mensaje · {o.channel}</div>
          {o.subject && <div className="text-sm font-medium">{o.subject}</div>}
          <div className="text-sm text-zinc-600 mt-1 whitespace-pre-wrap">{o.body}</div>
        </div>
      )}

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
    </>
  )
}
