import { createContext, useContext, useEffect, useState } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Toaster } from 'sonner'
import { Plus, Menu, ArrowLeft, Search } from 'lucide-react'
import { api, setToken } from './lib/api'
import { supabase } from './lib/supabase'
import { Button, Input, Select, Card } from './components/ui'
import { Glow } from './components/Glow'
import Sidebar from './components/Sidebar'
import Login from './components/Login'
import LeadModal from './components/LeadModal'
import CommandPalette from './components/CommandPalette'
import { canSeePage } from './lib/roles'
import Dashboard from './pages/Dashboard'
import Vender from './pages/Vender'
import Campanas from './pages/Campanas'
import Leads from './pages/Leads'
import Pipeline from './pages/Pipeline'
import Forecast from './pages/Forecast'
import Clientes from './pages/Clientes'
import Arquitectura from './pages/Arquitectura'
import Llamadas from './pages/Llamadas'
import Whatsapp from './pages/Whatsapp'
import Agentes from './pages/Agentes'
import Config from './pages/Config'
import Finanzas from './pages/Finanzas'

const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

const TITLES = {
  '/': ['Dashboard', 'Tu embudo de leads B2B en vivo'],
  '/vender': ['Vender', 'Envía un pitch con demo a un prospecto'],
  '/campanas': ['Campañas', 'Tus campañas de Meta Ads y su rendimiento'],
  '/leads': ['Leads', 'Todos los leads del cliente'],
  '/pipeline': ['Pipeline', 'El tablero por etapas'],
  '/agentes': ['Agentes', 'El estado de cada canal de contacto — elige uno para configurarlo'],
  '/llamadas': ['Llamadas', 'Llamá a un prospecto con un agente de voz'],
  '/whatsapp': ['WhatsApp', 'En 3 pasos deja un agente atendiendo: ficha, quién atiende, desplegar — prueba, estado y actividad'],
  '/forecast': ['Forecast', 'Proyección de pipeline'],
  '/clientes': ['Clientes', 'Tus cuentas'],
  '/finanzas': ['Finanzas', 'Entra, sale y margen de la agencia'],
  '/arquitectura': ['Arquitectura', 'Cómo está armado ZeroAI por dentro'],
  '/config': ['Configuración', 'Ajustes y conexiones'],
}

export default function App() {
  const [client, setClient] = useState(null)
  const [leadKey, setLeadKey] = useState(null)
  const [runOpen, setRunOpen] = useState(false)
  const { pathname } = useLocation()
  const nav = useNavigate()
  const [title, sub] = TITLES[pathname] || ['ZeroAI', '']
  const [authed, setAuthed] = useState(null)   // null=checking · false=login · true=in
  const [username, setUsername] = useState(null)
  const [role, setRole] = useState(null)         // "admin" | "cro" | "cto" | null
  const [authEnabled, setAuthEnabled] = useState(false) // false = sin cuentas dadas de alta (mock/dev), sin restricciones
  const [navOpen, setNavOpen] = useState(false) // drawer móvil del sidebar
  const [paletteOpen, setPaletteOpen] = useState(false)

  // Cmd/Ctrl+K en cualquier parte de la app abre el buscador de páginas/clientes.
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const refreshAuth = () => api.authStatus()
    .then((s) => {
      setAuthed(s.authenticated); setUsername(s.username || null)
      setRole(s.role || null); setAuthEnabled(!!s.enabled)
    })
    .catch(() => setAuthed(true))

  useEffect(() => {
    refreshAuth()
    const onUnauth = () => { setAuthed(false); setUsername(null); setRole(null); setAuthEnabled(false) }
    window.addEventListener('zero-unauth', onUnauth)
    return () => window.removeEventListener('zero-unauth', onUnauth)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Login con Google: al volver del redirect (o si ya había sesión activa),
  // Supabase dispara este evento con el JWT — lo guardamos con el MISMO
  // mecanismo que usa el login local (setToken) y refrescamos el status
  // contra nuestro backend, que es quien de verdad decide rol/permiso.
  useEffect(() => {
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session?.access_token) {
        setToken(session.access_token)
        refreshAuth()
      }
    })
    return () => sub.subscription.unsubscribe()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const { data: clients = [] } = useQuery({ queryKey: ['clients'], queryFn: api.clients, enabled: authed === true })
  useEffect(() => {
    if (!client && clients.length) setClient(clients[0])
  }, [clients, client])

  if (authed === null) return <div className="min-h-screen grid place-items-center text-zinc-400">Cargando…</div>
  if (authed === false) return <Login onSuccess={refreshAuth} />
  // Login válido (Google u otro) pero sin app_metadata.role asignado todavía
  // en Supabase — el backend ya bloquea todo con 403 (fail closed); acá se
  // corta ANTES de intentar cargar páginas, para no mostrar una app rota.
  if (authEnabled && !role) return <NoRoleScreen username={username} onLogout={() => api.logout()} />

  return (
    <AppCtx.Provider value={{ client, setClient, clients, openLead: setLeadKey, openRun: () => setRunOpen(true) }}>
      <div className="min-h-screen flex text-zinc-900 bg-[radial-gradient(120%_120%_at_100%_0%,#f2f1ec_0%,#f4f4f4_45%,#f6f5f2_100%)]">
        <Sidebar mobileOpen={navOpen} onClose={() => setNavOpen(false)} username={username} role={role} authEnabled={authEnabled} />
        <div className="flex-1 min-w-0">
          <header className="h-[68px] sticky top-0 z-20 bg-white/80 backdrop-blur border-b border-zinc-200 flex items-center px-4 md:px-8 gap-3">
            <button onClick={() => setNavOpen(true)} aria-label="Abrir menú"
              className="md:hidden p-2 -ml-1 rounded-lg text-zinc-600 hover:bg-zinc-100">
              <Menu size={20} />
            </button>
            {pathname !== '/' && (
              <button onClick={() => nav(-1)} aria-label="Volver" title="Volver"
                className="p-2 rounded-lg text-zinc-600 hover:bg-zinc-100 shrink-0 -ml-1 md:ml-0">
                <ArrowLeft size={18} />
              </button>
            )}
            <div className="min-w-0">
              <div className="font-display text-lg font-bold leading-tight truncate">{title}</div>
              <div className="text-xs text-zinc-500 truncate">{sub}</div>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <button onClick={() => setPaletteOpen(true)} title="Buscar (⌘K)"
                className="hidden sm:inline-flex items-center gap-1.5 text-xs text-zinc-400 border border-zinc-200 rounded-lg px-2.5 py-1.5 hover:bg-zinc-50 hover:text-zinc-600 transition-colors">
                <Search size={13} /> <kbd className="font-sans">⌘K</kbd>
              </button>
              {clients.length > 0 && (
                <Select value={client || ''} onChange={(e) => setClient(e.target.value)}>
                  {clients.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              )}
              <Glow>
                <Button variant="primary" onClick={() => setRunOpen(true)}>
                  <Plus size={15} /> Buscar leads
                </Button>
              </Glow>
            </div>
          </header>

          <main className="p-4 md:p-8">
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            >
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/vender" element={<Vender />} />
                <Route path="/campanas" element={<Campanas />} />
                <Route path="/leads" element={<Leads />} />
                <Route path="/pipeline" element={<Pipeline />} />
                <Route path="/forecast" element={<Forecast />} />
                <Route path="/clientes" element={<Clientes />} />
                <Route path="/finanzas" element={<Finanzas />} />
                <Route path="/arquitectura" element={<Arquitectura />} />
                <Route path="/agentes" element={<Agentes />} />
                <Route path="/llamadas" element={<Llamadas />} />
                <Route path="/whatsapp" element={<Whatsapp />} />
                <Route path="/config" element={<Config />} />
              </Routes>
            </motion.div>
          </main>
        </div>

        <LeadModal client={client} leadKey={leadKey} onClose={() => setLeadKey(null)} />
        <RunModal open={runOpen} onClose={() => setRunOpen(false)} />
        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          pages={Object.entries(TITLES)
            .filter(([path]) => canSeePage(path, role, authEnabled))
            .map(([path, [label]]) => ({ path, label }))}
          clients={clients}
          currentClient={client}
          onNavigate={nav}
          onSelectClient={setClient}
          onOpenLead={setLeadKey}
        />
        <Toaster richColors position="top-right" toastOptions={{ style: { borderRadius: '12px' } }} />
      </div>
    </AppCtx.Provider>
  )
}

function NoRoleScreen({ username, onLogout }) {
  return (
    <div className="min-h-screen grid place-items-center bg-[radial-gradient(120%_120%_at_100%_0%,#f2f1ec_0%,#f4f4f4_45%,#f6f5f2_100%)] p-4">
      <Card className="p-8 w-full max-w-sm text-center">
        <div className="font-display font-bold text-lg tracking-tight text-brand mb-2">Cuenta reconocida, sin rol asignado</div>
        <div className="text-sm text-zinc-500 mb-1">
          {username ? <>Tu cuenta (<b className="text-zinc-700">{username}</b>) inició sesión bien</> : 'Tu cuenta inició sesión bien'},
          pero todavía no tiene un rol asignado en ZeroAI.
        </div>
        <div className="text-sm text-zinc-500 mb-6">Avisale a Diego para que te asigne uno.</div>
        <Button variant="soft" onClick={onLogout} className="w-full">Salir</Button>
      </Card>
    </div>
  )
}

function RunModal({ open, onClose }) {
  const { setClient } = useApp()
  const qc = useQueryClient()
  const EMPTY_ICP = { sells: '', industry: '', roles: '', companySize: '', regions: '', mustHave: '', exclude: '', context: '' }
  const [form, setForm] = useState({ client: 'demo', tier: 'GROWTH', query: '', count: 8, ...EMPTY_ICP })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [showIcp, setShowIcp] = useState(false)
  const [icpLoaded, setIcpLoaded] = useState(false)

  // Map a saved (normalized) ICP back into the form so it's editable, not write-only.
  const fillFromIcp = (icp) => setForm((f) => ({
    ...f,
    sells: icp.sells || '', industry: icp.industry || '',
    roles: (icp.buyer_roles || []).join(', '), companySize: icp.company_size || '',
    regions: (icp.regions || []).join(', '), mustHave: (icp.must_have || []).join(', '),
    exclude: (icp.exclude || []).join(', '), context: icp.context || '',
  }))

  const loadSavedIcp = () => {
    api.icp(form.client.trim() || 'demo').then(fillFromIcp).catch(() => {}).finally(() => setIcpLoaded(true))
  }

  // When the ICP panel opens, pull the client's saved profile so they see/edit it.
  useEffect(() => {
    if (open && showIcp && !icpLoaded) loadSavedIcp()
  }, [open, showIcp]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setBusy(true); setErr('')
    try {
      const icp = {}
      if (form.sells.trim()) icp.sells = form.sells.trim()
      if (form.industry.trim()) icp.industry = form.industry.trim()
      if (form.roles.trim()) icp.buyer_roles = form.roles.trim()
      if (form.companySize.trim()) icp.company_size = form.companySize.trim()
      if (form.regions.trim()) icp.regions = form.regions.trim()
      if (form.mustHave.trim()) icp.must_have = form.mustHave.trim()
      if (form.exclude.trim()) icp.exclude = form.exclude.trim()
      if (form.context.trim()) icp.context = form.context.trim()
      await api.runPipeline({
        client: form.client.trim() || 'demo',
        tier: form.tier,
        query: form.query.trim() || 'leads B2B',
        count: Number(form.count) || 8,
        ...(Object.keys(icp).length ? { icp } : {}),
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
                <Input value={form.client} onChange={(e) => { setForm({ ...form, client: e.target.value }); setIcpLoaded(false) }} placeholder="acme" /></div>
              <div><label className="block text-xs text-zinc-500 mb-1">Plan</label>
                <Select className="w-full" value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })}>
                  {['STARTER', 'GROWTH', 'SCALE', 'ENTERPRISE'].map((t) => <option key={t}>{t}</option>)}
                </Select></div>
            </div>
            <div><label className="block text-xs text-zinc-500 mb-1">Búsqueda</label>
              <Input value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} placeholder="agencias de marketing en Santiago" /></div>
            <div><label className="block text-xs text-zinc-500 mb-1">Cantidad</label>
              <Input type="number" value={form.count} onChange={(e) => setForm({ ...form, count: e.target.value })} className="w-28" /></div>

            <div className="border-t border-zinc-100 pt-3">
              <div className="flex items-center justify-between">
                <button type="button" onClick={() => setShowIcp((v) => !v)}
                  className="text-xs font-medium text-gold-deep hover:underline">
                  {showIcp ? '− Ocultar' : '+ Definir'} perfil del cliente (ICP) — adaptación a medida
                </button>
                {showIcp && (
                  <button type="button" onClick={loadSavedIcp}
                    className="text-[11px] text-zinc-400 hover:text-zinc-600 hover:underline">
                    ↻ cargar guardado
                  </button>
                )}
              </div>
              {showIcp && (
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div className="col-span-2"><label className="block text-xs text-zinc-500 mb-1">Qué vende el cliente</label>
                    <Input value={form.sells} onChange={(e) => setForm({ ...form, sells: e.target.value })} placeholder="pallets de madera" /></div>
                  <div><label className="block text-xs text-zinc-500 mb-1">Rubro / industria</label>
                    <Input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} placeholder="logística, agro" /></div>
                  <div><label className="block text-xs text-zinc-500 mb-1">Tamaño de empresa</label>
                    <Input value={form.companySize} onChange={(e) => setForm({ ...form, companySize: e.target.value })} placeholder="PyME, 50–200" /></div>
                  <div><label className="block text-xs text-zinc-500 mb-1">Decisor (roles)</label>
                    <Input value={form.roles} onChange={(e) => setForm({ ...form, roles: e.target.value })} placeholder="Jefe de Logística" /></div>
                  <div><label className="block text-xs text-zinc-500 mb-1">Zonas</label>
                    <Input value={form.regions} onChange={(e) => setForm({ ...form, regions: e.target.value })} placeholder="RM, Valparaíso" /></div>
                  <div className="col-span-2"><label className="block text-xs text-zinc-500 mb-1">Requisitos (must-have)</label>
                    <Input value={form.mustHave} onChange={(e) => setForm({ ...form, mustHave: e.target.value })} placeholder="camión >12m, frío" /></div>
                  <div className="col-span-2"><label className="block text-xs text-zinc-500 mb-1">Excluir</label>
                    <Input value={form.exclude} onChange={(e) => setForm({ ...form, exclude: e.target.value })} placeholder="competidores, retail" /></div>
                  <div className="col-span-2"><label className="block text-xs text-zinc-500 mb-1">Contexto extra</label>
                    <Input value={form.context} onChange={(e) => setForm({ ...form, context: e.target.value })} placeholder="vende solo B2B, ticket alto" /></div>
                  <div className="col-span-2 text-[11px] text-zinc-400">Separá varios con coma. Se guarda por cliente y adapta el scoring y los mensajes.</div>
                </div>
              )}
            </div>

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
