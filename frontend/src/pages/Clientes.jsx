import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Wallet } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Skeleton, Select, CountUp, pageState, SectionTitle } from '../components/ui'
import { useApp } from '../App'

const clp = (n) => '$' + Math.round(n || 0).toLocaleString('es-CL')

export default function Clientes() {
  const { setClient } = useApp()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })

  const changePlan = async (client, tier) => {
    try {
      await api.setPlan(client, tier)
      qc.invalidateQueries({ queryKey: ['accounts'] })
      toast.success('Plan actualizado')
    } catch (e) { toast.error('No se pudo cambiar el plan: ' + e.message) }
  }

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    isEmpty: !data?.accounts?.length, emptyText: 'Sin clientes aún. Usá “Buscar leads”.',
    skeleton: (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full max-w-xs" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-36 w-full" />)}</div>
      </div>
    ),
  })
  if (gate) return gate
  const { accounts, mrr_clp, plans } = data

  return (
    <div className="space-y-5">
      <Card className="p-5 inline-flex items-center gap-4 bg-brand text-white">
        <div className="w-11 h-11 rounded-xl grid place-items-center bg-white/10"><Wallet size={20} /></div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-champagne/80">Ingreso mensual (MRR)</div>
          <div className="text-[32px] leading-none font-display font-extrabold tabular-nums mt-1.5">$<CountUp value={mrr_clp} /></div>
          <div className="text-[11px] text-champagne/70 mt-1">{accounts.length} cliente{accounts.length !== 1 ? 's' : ''} · CLP/mes</div>
        </div>
      </Card>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {accounts.map((a, i) => (
          <motion.div key={a.client} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card interactive className="p-5">
              <div className="flex items-start justify-between">
                <SectionTitle className="capitalize">{a.client}</SectionTitle>
                <div className="text-sm font-extrabold text-gold-deep tabular-nums">{a.price_clp ? clp(a.price_clp) : 'Custom'}</div>
              </div>
              <div className="text-xs text-zinc-400 mt-0.5">{a.leads_per_mo ? `${a.leads_per_mo} leads/mes` : 'leads a medida'}</div>

              <div className="mt-3">
                <label className="block text-[11px] text-zinc-400 mb-1">Plan</label>
                <Select value={a.tier} onChange={(e) => changePlan(a.client, e.target.value)} className="w-full">
                  {Object.entries(plans).map(([k, v]) => (
                    <option key={k} value={k}>{v.segment} · {v.price_clp ? clp(v.price_clp) : 'Custom'}</option>
                  ))}
                </Select>
              </div>

              <button onClick={() => { setClient(a.client); nav('/') }}
                className="text-sm text-gold-deep mt-3 flex items-center gap-1 hover:underline">
                Ver dashboard <ArrowRight size={14} />
              </button>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
