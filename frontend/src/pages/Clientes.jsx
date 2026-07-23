import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowRight, Plus, Wallet } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Skeleton, Select, Input, Button, CountUp, pageState, SectionTitle } from '../components/ui'
import { useApp } from '../App'

const clp = (n) => '$' + Math.round(n || 0).toLocaleString('es-CL')

export default function Clientes() {
  const { setClient } = useApp()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const [creating, setCreating] = useState(false)

  const changePlan = async (client, tier) => {
    try {
      await api.setPlan(client, tier)
      qc.invalidateQueries({ queryKey: ['accounts'] })
      toast.success('Plan actualizado')
    } catch (e) { toast.error('No se pudo cambiar el plan: ' + e.message) }
  }

  // Alta real de cliente: registra el plan (mismo POST que changePlan) y de
  // inmediato lleva a /whatsapp — ahí ya viven ficha/catálogo/vendedor
  // (KnowledgeCard/PricingCard/VendorPicker/DeployCard), scopeados al cliente
  // recién creado vía setClient. Sin esto, un cliente no aparecía en ningún
  // lado hasta tener un lead (fix de CORE: _all_client_ids en api.py).
  const afterCreate = (id) => {
    qc.invalidateQueries({ queryKey: ['accounts'] })
    qc.invalidateQueries({ queryKey: ['clients'] })
    setClient(id)
    setCreating(false)
    nav('/whatsapp')
  }

  const gate = pageState({
    isLoading, error, onRetry: refetch,
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
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <Card className="p-5 inline-flex items-center gap-4 bg-brand text-white">
          <div className="w-11 h-11 rounded-xl grid place-items-center bg-white/10"><Wallet size={20} /></div>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-champagne/80">Ingreso mensual (MRR)</div>
            <div className="text-[32px] leading-none font-display font-extrabold tabular-nums mt-1.5">$<CountUp value={mrr_clp} /></div>
            <div className="text-[11px] text-champagne/70 mt-1">{accounts.length} cliente{accounts.length !== 1 ? 's' : ''} · CLP/mes</div>
          </div>
        </Card>
        <Button variant="accent" onClick={() => setCreating(true)}>
          <Plus size={15} /> Nuevo cliente
        </Button>
      </div>

      {accounts.length === 0 ? (
        <div className="py-16 text-center text-zinc-400">
          Sin clientes aún. Da de alta el primero con <b className="text-zinc-500">"Nuevo cliente"</b>.
        </div>
      ) : (
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
      )}

      {creating && <NewClientModal plans={plans} onClose={() => setCreating(false)} onCreated={afterCreate} />}
    </div>
  )
}

// Punto de entrada real de "dar de alta" un cliente — antes solo aparecía
// si ya le habías corrido una búsqueda de leads. El id se deriva igual que
// vendors/functions en el backend (api.py: alfanumérico en minúsculas), acá
// en el cliente para mostrar el preview antes de crear.
function NewClientModal({ plans, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [tier, setTier] = useState(Object.keys(plans)[0] || 'GROWTH')
  const [busy, setBusy] = useState(false)
  const id = name.trim().toLowerCase().replace(/[^a-z0-9]/g, '')

  const create = async () => {
    if (!id) return
    setBusy(true)
    try {
      await api.setPlan(id, tier)
      toast.success(`${id} creado — completa su ficha, catálogo y vendedor`)
      onCreated(id)
    } catch (e) {
      toast.error('No se pudo crear: ' + e.message)
    } finally { setBusy(false) }
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="bg-white rounded-2xl max-w-sm w-full p-6"
          initial={{ opacity: 0, scale: 0.96, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 12 }}
          transition={{ type: 'spring', stiffness: 320, damping: 28 }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-lg font-bold">Nuevo cliente</div>
          <div className="text-xs text-zinc-400 mt-0.5 mb-4">Queda con plan asignado de inmediato — sin necesitar un lead. Después de crearlo, completas su ficha, catálogo y vendedor.</div>

          <label className="block text-[11px] text-zinc-400 mb-1">Nombre o ID del cliente</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ej: Mar Austral" autoFocus
            onKeyDown={(e) => e.key === 'Enter' && create()} />
          <div className="text-[11px] text-zinc-400 mt-1">
            {id ? <>Se guardará como <code className="text-gold-deep font-medium">{id}</code></> : 'Escribe un nombre — se convierte en el id del cliente'}
          </div>

          <label className="block text-[11px] text-zinc-400 mb-1 mt-4">Plan</label>
          <Select value={tier} onChange={(e) => setTier(e.target.value)} className="w-full">
            {Object.entries(plans).map(([k, v]) => (
              <option key={k} value={k}>{v.segment} · {v.price_clp ? clp(v.price_clp) : 'Custom'}</option>
            ))}
          </Select>

          <div className="flex justify-end gap-2 mt-5">
            <Button variant="ghost" onClick={onClose} disabled={busy}>Cancelar</Button>
            <Button variant="accent" onClick={create} disabled={!id || busy}>
              {busy ? 'Creando…' : 'Crear y configurar'}
            </Button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
