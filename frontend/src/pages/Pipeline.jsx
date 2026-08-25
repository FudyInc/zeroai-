import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { STAGES, ORDER, scoreColor } from '../lib/util'
import { Card, Skeleton, pageState } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

const DENSITY = [{ value: 'comodo', label: 'Cómodo' }, { value: 'compacto', label: 'Compacto' }]

export default function Pipeline() {
  const { client, openLead } = useApp()
  const qc = useQueryClient()
  const { data: board, isLoading, error, refetch } = useQuery({ queryKey: ['board', client], queryFn: () => api.board(client), enabled: !!client })
  const drag = useRef(null)           // { key, from }
  const [over, setOver] = useState(null)
  const [dense, setDense] = useState('comodo')
  const compact = dense === 'compacto'

  if (!client) return <NoClient />

  const move = async (k, s) => {
    try { await api.moveStage(client, k, s); qc.invalidateQueries(); toast.success('Lead movido a ' + STAGES[s].l) }
    catch (e) { toast.error('No se pudo mover: ' + e.message) }
  }

  const onDrop = (stage) => {
    const d = drag.current
    setOver(null); drag.current = null
    if (d && d.from !== stage) move(d.key, stage)
  }

  // Mapa etapa → leads, y mostramos TODAS las etapas como columnas (para poder
  // soltar incluso en una vacía). El orden lo da ORDER.
  const byStage = Object.fromEntries((board?.stages || []).map((s) => [s.stage, s.leads]))

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    skeleton: <div className="flex gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-64 w-64 shrink-0" />)}</div>,
  })
  if (gate) return gate

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="text-xs text-zinc-400">Arrastrá una tarjeta entre columnas para cambiar su etapa — o usá el menú. Tocala para ver el detalle.</div>
        <Segmented options={DENSITY} value={dense} onChange={setDense} />
      </div>
      <div className="flex gap-4 overflow-x-auto pb-2">
        {ORDER.map((stage) => {
          const m = STAGES[stage] || { l: stage, c: '#94a3b8' }
          const leads = byStage[stage] || []
          const isOver = over === stage
          return (
            <div
              key={stage}
              onDragOver={(e) => { e.preventDefault(); if (over !== stage) setOver(stage) }}
              onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver((s) => (s === stage ? null : s)) }}
              onDrop={(e) => { e.preventDefault(); onDrop(stage) }}
              className={
                'shrink-0 rounded-2xl p-3 transition-colors ' + (compact ? 'w-52 ' : 'w-64 ') +
                (isOver ? 'bg-champagne/20 ring-2 ring-gold/40' : 'bg-transparent')
              }
            >
              <div className="flex items-center gap-2 mb-3 px-1 text-xs font-semibold uppercase tracking-wide" style={{ color: m.c }}>
                <span className="w-2 h-2 rounded-full" style={{ background: m.c }} />{m.l}
                <span className="ml-auto bg-zinc-100 text-zinc-500 rounded-full px-2 py-0.5 text-[11px]">{leads.length}</span>
              </div>
              <div className="space-y-2.5 min-h-[60px]">
                {leads.map((r, i) => (
                  <motion.div
                    key={r.key}
                    layout
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}
                    draggable
                    onDragStart={() => { drag.current = { key: r.key, from: stage } }}
                    onDragEnd={() => { drag.current = null; setOver(null) }}
                    onClick={() => openLead(r.key)}
                    className={'cursor-grab active:cursor-grabbing bg-white dark:bg-[#1D2016] border border-champagne/50 dark:border-zinc-700/40 rounded-xl shadow-[0_1px_2px_rgba(44,53,41,0.04)] hover:shadow-[0_14px_34px_-18px_rgba(44,53,41,0.20)] hover:-translate-y-0.5 dark:hover:border-zinc-600/60 transition-all ' + (compact ? 'p-3' : 'p-4')}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <div className={'font-semibold ' + (compact ? 'text-sm' : '')}>{r.company}</div>
                      <span className="font-extrabold tabular-nums" style={{ color: scoreColor(r.score) }}>{r.score ?? '—'}</span>
                    </div>
                    {!compact && (
                      <>
                        <div className="text-xs text-zinc-500 mt-2">{r.role || '—'}</div>
                        <div className="text-xs text-zinc-400">{r.email || r.phone || '—'}</div>
                        <select value={r.stage} onClick={(e) => e.stopPropagation()} onChange={(e) => move(r.key, e.target.value)}
                          className="mt-3 w-full text-xs border border-zinc-200 dark:border-zinc-700/50 rounded-lg px-2.5 py-1.5 bg-white dark:bg-zinc-900/20 text-zinc-700 dark:text-zinc-300 outline-none focus:ring-2 focus:ring-champagne/40 transition">
                          {ORDER.map((st) => <option key={st} value={st}>{STAGES[st].l}</option>)}
                        </select>
                      </>
                    )}
                  </motion.div>
                ))}
                {leads.length === 0 && (
                  <div className="text-[12px] text-zinc-300 text-center py-6 border border-dashed border-zinc-200 rounded-xl">
                    soltá aquí
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
