import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { api } from '../lib/api'
import { STAGES, ORDER, scoreColor } from '../lib/util'
import { Card } from '../components/ui'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

export default function Pipeline() {
  const { client, openLead } = useApp()
  const qc = useQueryClient()
  const { data: board } = useQuery({ queryKey: ['board', client], queryFn: () => api.board(client), enabled: !!client })
  if (!client) return <NoClient />

  const move = async (k, s) => { await api.moveStage(client, k, s); qc.invalidateQueries() }
  const cols = (board?.stages || []).filter((s) => s.leads.length)

  return (
    <Card className="p-5">
      <div className="text-xs text-zinc-400 mb-4">Mové un lead con el menú, o tocá la tarjeta para ver el detalle.</div>
      <div className="flex gap-4 overflow-x-auto pb-2">
        {cols.map((s) => {
          const m = STAGES[s.stage] || { l: s.stage, c: '#94a3b8' }
          return (
            <div key={s.stage} className="shrink-0 w-64">
              <div className="flex items-center gap-2 mb-3 text-xs font-semibold uppercase tracking-wide" style={{ color: m.c }}>
                <span className="w-2 h-2 rounded-full" style={{ background: m.c }} />{m.l}
                <span className="ml-auto bg-zinc-100 text-zinc-500 rounded-full px-2 py-0.5 text-[11px]">{s.leads.length}</span>
              </div>
              <div className="space-y-2.5">
                {s.leads.map((r, i) => (
                  <motion.div key={r.key} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}
                    onClick={() => openLead(r.key)}
                    className="cursor-pointer bg-white border border-zinc-200 rounded-xl p-3.5 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all">
                    <div className="flex justify-between items-start gap-2">
                      <div className="font-semibold">{r.company}</div>
                      <span className="font-extrabold tabular-nums" style={{ color: scoreColor(r.score) }}>{r.score ?? '—'}</span>
                    </div>
                    <div className="text-[13px] text-zinc-500 mt-1">{r.role || '—'}</div>
                    <div className="text-[13px] text-zinc-500">{r.email || r.phone || '—'}</div>
                    <select value={r.stage} onClick={(e) => e.stopPropagation()} onChange={(e) => move(r.key, e.target.value)}
                      className="mt-2.5 w-full text-xs border border-zinc-200 rounded-lg px-2 py-1 bg-zinc-50 text-zinc-600 outline-none focus:ring-2 focus:ring-emerald-200">
                      {ORDER.map((st) => <option key={st} value={st}>{STAGES[st].l}</option>)}
                    </select>
                  </motion.div>
                ))}
              </div>
            </div>
          )
        })}
        {cols.length === 0 && <div className="text-zinc-400 py-10">Sin leads. Usá “Buscar leads”.</div>}
      </div>
    </Card>
  )
}
