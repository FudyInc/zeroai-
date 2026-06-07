import { createContext, useContext, useEffect, useState } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Plus } from 'lucide-react'
import { api } from './lib/api'
import { Button, Input, Select } from './components/ui'
import Sidebar from './components/Sidebar'
import LeadModal from './components/LeadModal'
import Dashboard from './pages/Dashboard'
import Leads from './pages/Leads'
import Pipeline from './pages/Pipeline'
import Forecast from './pages/Forecast'
import Clientes from './pages/Clientes'
import Llamadas from './pages/Llamadas'
import Agentes from './pages/Agentes'
import Config from './pages/Config'
import Placeholder from './pages/Placeholder'

const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

const TITLES = {
  '/': ['Dashboard', 'Tu embudo de leads B2B en vivo'],
  '/leads': ['Leads', 'Todos los leads del cliente'],
  '/pipeline': ['Pipeline', 'El tablero por etapas'],
  '/agentes': ['Agentes', 'Tus canales de contacto, un agente por cada uno'],
  '/outreach': ['Outreach', 'Mensajes de primer toque'],
  '/seguimientos': ['Seguimientos', 'Secuencias de follow-up'],
  '/llamadas': ['Llamadas', 'Llamá a un prospecto con un agente de voz'],
  '/forecast': ['Forecast', 'Proyección de pipeline'],
  '/clientes': ['Clientes', 'Tus cuentas'],
  '/config': ['Configuración', 'Ajustes y conexiones'],
}

export default function App() {
  const [client, setClient] = useState(null)
  const [leadKey, setLeadKey] = useState(null)
  const [runOpen, setRunOpen] = useState(false)
  const { pathname } = useLocation()
  const [title, sub] = TITLES[pathname] || ['ZeroAI', '']

  const { data: clients = [] } = useQuery({ queryKey: ['clients'], queryFn: api.clients })
  useEffect(() => {
    if (!client && clients.length) setClient(clients[0])
  }, [clients, client])

  return (
    <AppCtx.Provider value={{ client, setClient, clients, openLead: setLeadKey }}>
      <div className="min-h-screen bg-zinc-50 text-zinc-900">
        <Sidebar />
        <div className="ml-60">
          <header className="h-[68px] sticky top-0 z-20 bg-white/80 backdrop-blur border-b border-zinc-200 flex items-center px-8 gap-3">
            <div>
              <div className="text-lg font-bold leading-tight">{title}</div>
              <div className="text-xs text-zinc-400">{sub}</div>
            </div>
            <div className="ml-auto flex items-center gap-2">
              {clients.length > 0 && (
                <Select value={client || ''} onChange={(e) => setClient(e.target.value)}>
                  {clients.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              )}
              <Button variant="primary" onClick={() => setRunOpen(true)}>
                <Plus size={15} /> Buscar leads
              </Button>
            </div>
          </header>

          <main className="p-8">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/leads" element={<Leads />} />
              <Route path="/pipeline" element={<Pipeline />} />
              <Route path="/forecast" element={<Forecast />} />
              <Route path="/clientes" element={<Clientes />} />
              <Route path="/agentes" element={<Agentes />} />
              <Route path="/llamadas" element={<Llamadas />} />
              <Route path="/config" element={<Config />} />
              <Route path="/outreach" element={<Placeholder icon="mail" title="Outreach" />} />
              <Route path="/seguimientos" element={<Placeholder icon="send" title="Seguimientos" />} />
            </Routes>
          </main>
        </div>

        <LeadModal client={client} leadKey={leadKey} onClose={() => setLeadKey(null)} />
        <RunModal open={runOpen} onClose={() => setRunOpen(false)} />
      </div>
    </AppCtx.Provider>
  )
}

function RunModal({ open, onClose }) {
  const { setClient } = useApp()
  const qc = useQueryClient()
  const [form, setForm] = useState({ client: 'demo', tier: 'GROWTH', query: '', count: 8 })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setBusy(true); setErr('')
    try {
      await api.runPipeline({
        client: form.client.trim() || 'demo',
        tier: form.tier,
        query: form.query.trim() || 'leads B2B',
        count: Number(form.count) || 8,
      })
      qc.invalidateQueries()
      setClient(form.client.trim() || 'demo')
      onClose()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4"
            initial={{ opacity: 0, scale: 0.96, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }} transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            onClick={(e) => e.stopPropagation()}>
            <div className="text-lg font-bold">Buscar leads</div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="block text-xs text-zinc-500 mb-1">Cliente</label>
                <Input value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} placeholder="acme" /></div>
              <div><label className="block text-xs text-zinc-500 mb-1">Plan</label>
                <Select className="w-full" value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })}>
                  {['STARTER', 'GROWTH', 'SCALE', 'ENTERPRISE'].map((t) => <option key={t}>{t}</option>)}
                </Select></div>
            </div>
            <div><label className="block text-xs text-zinc-500 mb-1">Búsqueda</label>
              <Input value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} placeholder="agencias de marketing en Santiago" /></div>
            <div><label className="block text-xs text-zinc-500 mb-1">Cantidad</label>
              <Input type="number" value={form.count} onChange={(e) => setForm({ ...form, count: e.target.value })} className="w-28" /></div>
            {err && <div className="text-sm text-rose-600">{err}</div>}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={onClose}>Cancelar</Button>
              <Button variant="accent" onClick={run} disabled={busy}>{busy ? 'Corriendo…' : 'Correr'}</Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
