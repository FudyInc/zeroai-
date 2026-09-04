import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ChevronLeft, ChevronRight, DollarSign, TrendingDown, TrendingUp, PiggyBank } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from 'recharts'
import { api } from '../lib/api'
import { Card, Skeleton, Badge, pageState, Eyebrow, SectionTitle } from '../components/ui'
import { rise, fade, surface, stagger } from '../lib/motion'

const clp = (n) => '$' + Math.round(n || 0).toLocaleString('es-CL')
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const monthLabel = (ym) => {
  if (!ym) return '—'
  const [y, m] = ym.split('-').map(Number)
  return `${MESES[m - 1]} ${y}`
}
const currentMonth = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/* Finanzas de la agencia (entra/sale/margen) — vista exclusiva del rol "cro".
   Agregada, NO por cliente: no usa useApp().client ni el selector global. */
export default function Finanzas() {
  const [month, setMonth] = useState(null) // null = mes actual (default del backend)
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['finance', month],
    queryFn: () => api.finance(month || undefined),
  })

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    skeleton: (
      <div className="space-y-5">
        <Skeleton className="h-10 w-48" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
        <Skeleton className="h-56 w-full" />
      </div>
    ),
  })
  if (gate) return gate

  const shiftMonth = (delta) => {
    const [y, m] = data.month.split('-').map(Number)
    const d = new Date(y, m - 1 + delta, 1)
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  const atCurrentMonth = data.month >= currentMonth()

  const cards = [
    { label: 'Ingresos (MRR)', value: data.mrr_clp, icon: DollarSign, tone: 'slate' },
    { label: 'Costos', value: data.costs_clp, icon: TrendingDown, tone: 'slate' },
    { label: 'Margen', value: data.margin_clp, icon: PiggyBank, tone: 'gold' },
  ]

  const trend = [...(data.history || []), { month: data.month, mrr_clp: data.mrr_clp, costs_clp: data.costs_clp, margin_clp: data.margin_clp }]
    .map((h) => ({ name: monthLabel(h.month), margin: h.margin_clp, mrr: h.mrr_clp, costs: h.costs_clp }))

  return (
    <motion.div className="space-y-5" initial="hidden" animate="show" variants={rise}>
      <motion.div className="flex items-center justify-between gap-3 flex-wrap" variants={fade}>
        <div className="inline-flex items-center gap-1 bg-zinc-100 rounded-full p-1">
          <button onClick={() => shiftMonth(-1)} className="p-1.5 rounded-full hover:bg-white dark:hover:bg-zinc-200 transition-colors" aria-label="Mes anterior">
            <ChevronLeft size={15} />
          </button>
          <span className="text-sm font-semibold capitalize px-2 min-w-[92px] text-center tabular-nums">{monthLabel(data.month)}</span>
          <button onClick={() => shiftMonth(1)} disabled={atCurrentMonth}
            className="p-1.5 rounded-full hover:bg-white dark:hover:bg-zinc-200 transition-colors disabled:opacity-30 disabled:hover:bg-transparent" aria-label="Mes siguiente">
            <ChevronRight size={15} />
          </button>
        </div>
        {data.source === 'mock' && <Badge color="#8C929B">cifras de ejemplo — sin finance.json</Badge>}
      </motion.div>

      <motion.div className="grid grid-cols-1 sm:grid-cols-3 gap-4" variants={stagger()} initial="hidden" animate="show">
        {cards.map((c) => {
          const chip = c.tone === 'gold' ? 'bg-champagne/25 text-gold-deep border-champagne/60' : 'bg-brand/[0.05] text-brand/90 border-brand/10'
          return (
            <motion.div key={c.label} variants={surface}>
              <Card interactive className="p-5 flex items-start justify-between">
                <div className="min-w-0">
                  <Eyebrow>{c.label}</Eyebrow>
                  <div className="text-[28px] leading-none font-display font-extrabold tracking-tight text-brand mt-2.5 tabular-nums">{clp(c.value)}</div>
                </div>
                <div className={'w-10 h-10 rounded-xl grid place-items-center border shrink-0 ' + chip}>
                  <c.icon size={18} />
                </div>
              </Card>
            </motion.div>
          )
        })}
        <motion.div variants={surface}>
          <Card className="p-5 h-full flex flex-col items-center justify-center text-center">
            <Eyebrow>Margen</Eyebrow>
            <div className="text-[28px] leading-none font-display font-extrabold tracking-tight text-gold-deep mt-2.5 tabular-nums">
              {(data.margin_pct ?? 0).toFixed(1)}%
            </div>
          </Card>
        </motion.div>
      </motion.div>

      <motion.div className="grid grid-cols-1 lg:grid-cols-3 gap-4" variants={stagger()} initial="hidden" animate="show">
        <motion.div className="lg:col-span-2" variants={surface}>
          <Card className="p-5 h-full">
          <SectionTitle className="flex items-center gap-2 mb-1"><TrendingUp size={16} className="text-gold-deep" /> Margen mensual</SectionTitle>
          <div className="text-xs text-zinc-400 mb-3">Ingresos menos costos, mes a mes.</div>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trend} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <defs>
                  <linearGradient id="marginFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#C9A45C" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#C9A45C" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="var(--color-zinc-100)" />
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: 'var(--color-zinc-500)' }} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Tooltip cursor={{ stroke: '#C9A45C', strokeWidth: 1 }}
                  contentStyle={{ borderRadius: 12, border: '1px solid var(--color-zinc-200)', fontSize: 13, background: 'var(--color-zinc-50)' }}
                  labelStyle={{ color: 'var(--color-zinc-700)' }}
                  formatter={(v) => [clp(v), 'Margen']} />
                <Area type="monotone" dataKey="margin" stroke="var(--color-gold-deep)" strokeWidth={2} fill="url(#marginFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          </Card>
        </motion.div>

        <motion.div variants={surface}>
          <Card className="p-5 h-full">
          <SectionTitle className="mb-1">Desglose de costos</SectionTitle>
          <div className="text-xs text-zinc-400 mb-3">{monthLabel(data.month)}, por categoría.</div>
          {(data.costs || []).length === 0 ? (
            <div className="text-sm text-zinc-400 py-4 text-center">Sin costos cargados este mes.</div>
          ) : (
            <div className="space-y-2">
              {data.costs.map((c, i) => (
                <div key={i} className="flex items-center justify-between gap-3 bg-zinc-50 rounded-xl px-3 py-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium capitalize truncate">{c.category}</div>
                    {c.note && <div className="text-xs text-zinc-400 truncate">{c.note}</div>}
                  </div>
                  <div className="text-sm font-semibold tabular-nums shrink-0">{clp(c.amount_clp)}</div>
                </div>
              ))}
            </div>
          )}
          </Card>
        </motion.div>
      </motion.div>
    </motion.div>
  )
}
