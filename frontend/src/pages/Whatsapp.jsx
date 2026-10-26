import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import {
  MessageCircle, CheckCircle2, WifiOff, AlertCircle, Copy, Check, Clock,
  Building2, Rocket, Cpu, ChevronDown, ArrowUpRight, SlidersHorizontal,
} from 'lucide-react'
import { api, BASE } from '../lib/api'
import { Card, Button, Badge, Skeleton, SectionTitle, Input } from '../components/ui'
import { STAGES } from '../lib/util'
import { useApp } from '../App'
import AgentTester from '../components/AgentTester'
import KnowledgeHistory from '../components/KnowledgeHistory'
import CasesLab from '../components/CasesLab'
import PricingCard from '../components/PricingCard'
import ConversationThread from '../components/ConversationThread'
import WhatsAppWebInbox from '../components/WhatsAppWebInbox'
import AttentionCard from '../components/AttentionCard'
import { rise, fade, surface } from '../lib/motion'
import './whatsapp.css'

/* El agente de WhatsApp, en un solo lugar: en 3 pasos dejas a un agente
   atendiendo los leads de una empresa (cuéntale del negocio, elige quién
   atiende, despliega), lo pruebas en el chat, y ves el estado real de la
   conexión con Meta + la actividad reciente. Antes "la ficha"/"elige quién
   atiende" vivían en una página "Agentes" genérica separada — se movieron acá
   porque son 100% configuración del agente de WhatsApp (CONCIERGE), no de
   los otros canales (email es solo envío, sin ida y vuelta). */

export default function Whatsapp() {
  const { client: ctxClient } = useApp()
  // Sin cliente por defecto: ese cliente de prueba ya se borró del CRM, y volver a
  // usarlo como fallback lo resucitaría en la base real con solo abrir la página.
  const client = ctxClient || ''
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: api.config })

  const vendorsQ = useQuery({ queryKey: ['vendors'], queryFn: api.vendors })
  const assignedQ = useQuery({ queryKey: ['vendor', client], queryFn: () => api.vendorFor(client), enabled: !!client })
  const profileQ = useQuery({ queryKey: ['agent-profile', client], queryFn: () => api.agentProfile(client), enabled: !!client })
  const knowledgeQ = useQuery({ queryKey: ['knowledge', client], queryFn: () => api.knowledge(client), enabled: !!client })
  const readinessQ = useQuery({ queryKey: ['whatsapp-readiness', client], queryFn: () => api.whatsappReadiness(client), enabled: !!client })
  const integrationsQ = useQuery({ queryKey: ['integrations', client], queryFn: () => api.clientIntegrations(client), enabled: !!client })
  const leadsQ = useQuery({
    queryKey: ['leads', client, 'whatsapp-activity'],
    queryFn: () => api.leads(client, { group: 'todos', limit: 50 }),
    enabled: !!client,
  })

  const [selected, setSelected] = useState(null) // vendor_id elegido (aún sin desplegar)
  const assignedId = assignedQ.data?.vendor?.id
  useEffect(() => { setSelected(null) }, [client]) // al cambiar de empresa, volver a lo asignado
  const currentId = selected || assignedId
  const vendors = vendorsQ.data?.vendors || []
  const currentVendor = vendors.find((v) => v.id === currentId)

  const qc = useQueryClient()
  const deploy = useMutation({
    mutationFn: () => api.setVendor(client, currentId),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['vendor', client] })
      qc.invalidateQueries({ queryKey: ['whatsapp-readiness', client] })
      setSelected(null)
      toast.success(`Listo: ${d.vendor?.name || 'el agente'} atiende a los leads de ${client}`)
    },
    onError: (e) => toast.error('No se pudo desplegar: ' + e.message),
  })

  const knowledgeSaved = (knowledgeQ.data?.knowledge || '').trim().length > 0
  const cfg = cfgQ.data
  const provider = integrationsQ.data?.whatsapp_provider
  const connected = provider === 'web'
    ? !!cfg?.whatsapp && !!readinessQ.data?.number_bound
    : !!integrationsQ.data?.whatsapp_cloud
  const readyItems = readinessQ.data && [readinessQ.data.knowledge, readinessQ.data.response_rules,
    readinessQ.data.number_bound, (readinessQ.data.pricing_items || 0) > 0].filter(Boolean).length

  // Toda la página depende de un cliente elegido; sin uno no hay a quién
  // configurarle el agente, y consultar con cliente vacío pegaría contra la API mal.
  if (!client) {
    return (
      <Card className="wa-empty-client p-8 text-center">
        <MessageCircle size={28} className="mx-auto mb-3 text-gold-deep" />
        <h2 className="font-display text-lg font-bold text-brand">Elige una empresa</h2>
        <p className="mt-1 text-sm text-zinc-500">Selecciona un cliente en el encabezado para ver su agente y sus conversaciones.</p>
      </Card>
    )
  }

  return (
    <motion.div className="wa-page space-y-7" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <Card className="wa-hero">
          <div className="wa-hero-main">
            <div className="wa-eyebrow"><MessageCircle size={14} /> Centro de atención</div>
            <h1>WhatsApp <span>de {client}</span></h1>
            <p>Conversaciones, configuración del agente y pruebas en un solo lugar. Prepara su ficha y sus reglas antes de activar respuestas automáticas.</p>
            <div className="wa-hero-meta">
              <span className="wa-meta-pill"><span className={'wa-status-dot ' + (connected ? 'is-ready' : '')} />{connected ? 'Canal configurado' : 'Conexión pendiente'}</span>
              <span className="wa-meta-pill"><SlidersHorizontal size={13} /> {readinessQ.data?.response_mode === 'automatic' ? 'Respuesta automática' : 'Atención manual'}</span>
              {cfg?.local_model && <span className="wa-meta-pill"><Cpu size={13} /> {cfg.local_model}</span>}
            </div>
            <nav className="wa-quick-nav" aria-label="Ir a secciones de WhatsApp">
              {connected && provider === 'web' && <a href="#wa-bandeja">Ir a la bandeja <ArrowUpRight size={15} /></a>}
              <a href="#wa-atencion">Atención pendiente <ArrowUpRight size={15} /></a>
              <a href="#wa-configuracion">Configurar agente <ArrowUpRight size={15} /></a>
              <a href="#wa-pruebas">Pruebas y actividad <ArrowUpRight size={15} /></a>
            </nav>
          </div>
          <div className="wa-hero-progress">
            <span>Preparación del negocio</span>
            <strong>{readyItems == null ? '…' : `${readyItems}/4`}</strong>
            <div className="wa-progress-track"><div style={{ width: `${(readyItems || 0) * 25}%` }} /></div>
            <small>Ficha, reglas, número y precios</small>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={surface}>
        <ReadinessCard client={client} readinessQ={readinessQ} />
      </motion.div>

      {!cfgQ.isLoading && !connected && (
        <motion.div variants={fade}>
          <ConnectMetaBanner />
        </motion.div>
      )}

      {connected && provider === 'web' && (
        <section id="wa-bandeja" className="wa-section">
          <div className="wa-section-heading"><div><span className="wa-section-kicker">01 / Conversaciones</span><h2>Bandeja de entrada</h2><p>Lee los mensajes y toma los chats que necesitan atención humana.</p></div></div>
          <motion.div variants={surface}>
            <WhatsAppWebInbox client={client} expectedNumber={readinessQ.data?.number}
              responseMode={readinessQ.data?.response_mode} />
          </motion.div>
        </section>
      )}

      {client && (
        <section id="wa-atencion" className="wa-section">
          <div className="wa-section-heading"><div><span className="wa-section-kicker">{connected && provider === 'web' ? '02' : '01'} / Atención</span><h2>Lo que el agente no pudo resolver</h2><p>Respóndelo una vez: el cliente recibe tu mensaje y el agente lo aprende para la próxima.</p></div></div>
          <motion.div variants={surface}>
            <AttentionCard client={client} />
          </motion.div>
        </section>
      )}

      <section id="wa-configuracion" className="wa-section">
        <div className="wa-section-heading"><div><span className="wa-section-kicker">{connected && provider === 'web' ? '03' : '02'} / Agente</span><h2>Configuración del agente</h2><p>Define qué sabe, cómo responde y quién atiende a esta empresa.</p></div></div>
      <div className="wa-config-grid grid grid-cols-1 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,.85fr)] gap-5 items-start">
        <motion.div className="space-y-4" variants={surface}>
          <motion.div variants={surface}>
            <KnowledgeCard client={client} knowledgeQ={knowledgeQ} />
          </motion.div>
          <motion.div variants={surface} className="wa-card-shell">
            <PricingCard client={client} />
          </motion.div>
          <motion.div variants={surface}>
            <VendorPicker vendorsQ={vendorsQ} assignedId={assignedId} currentId={currentId} onPick={setSelected} />
          </motion.div>
          <motion.div variants={surface}>
            <ProfileCard client={client} profileQ={profileQ} vendor={currentVendor} />
          </motion.div>
          <motion.div variants={surface}>
            <DeployCard
              client={client} vendor={currentVendor} assignedId={assignedId}
              knowledgeSaved={knowledgeSaved} deploy={deploy} cfg={cfg}
            />
          </motion.div>
        </motion.div>
        <motion.div className="xl:sticky xl:top-24 space-y-4" variants={surface}>
          <motion.div variants={surface} className="wa-card-shell">
            <AgentTester
              title="Probar antes de desplegar"
              hint="Escribe como si fueras un lead de esta empresa. Nada de esto le llega a nadie: es solo un ensayo."
              fixedClient={client}
              vendorId={currentId}
              vendorName={currentVendor?.name}
            />
          </motion.div>
          {connected && provider === 'web' && (
            <motion.div variants={surface}>
              <WebStatusCard key={client} cfg={cfg} client={client} profile={profileQ.data?.profile} />
            </motion.div>
          )}
          {connected && provider === 'meta' && (
            <motion.div variants={surface}>
              <StatusCard
                key={client}
                cfg={cfg}
                client={client}
                webhookReady={integrationsQ.data?.whatsapp_webhook_ready}
                webhookUrl={`${BASE || window.location.origin}/api/webhooks/whatsapp`}
              />
            </motion.div>
          )}
        </motion.div>
      </div>
      </section>

      {/* A ancho completo y no en una columna: la comparación pone la respuesta esperada,
          la de antes y la de ahora una al lado de la otra, y eso no entra en media
          pantalla. Va después del chat de prueba porque es su versión sistemática: el
          chat sirve para tantear, esto para no romper lo que ya funcionaba. */}
      <section id="wa-pruebas" className="wa-section">
        <div className="wa-section-heading"><div><span className="wa-section-kicker">{connected && provider === 'web' ? '04' : '03'} / Seguimiento</span><h2>Pruebas y actividad</h2><p>Compara respuestas antes de usar la configuración con mensajes reales.</p></div></div>
        <motion.div variants={surface} className="wa-card-shell"><CasesLab client={client} vendorId={currentId} /></motion.div>
        {connected && <motion.div variants={surface} className="mt-5"><ActivityCard leadsQ={leadsQ} client={client} /></motion.div>}
      </section>
    </motion.div>
  )
}

/* Banner informativo cuando Meta todavía no está conectado — a diferencia de
   antes, YA NO bloquea el resto de la página: ficha/precios/vendedor/chat de
   prueba funcionan igual sin Meta conectado (solo el envío real por WhatsApp
   queda pendiente de esa conexión). */
function ConnectMetaBanner() {
  return (
    <Card className="wa-alert p-4 sm:p-5 flex items-start gap-3">
      <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 grid place-items-center shrink-0">
        <MessageCircle size={17} />
      </div>
      <div className="text-sm text-amber-900">
        <b>Conexión de WhatsApp pendiente.</b> Puedes preparar la ficha, los precios y las reglas,
        y probar al agente aquí. Completa la conexión para atender mensajes reales en{' '}
        <a href="/config" className="underline font-semibold underline-offset-2">Configuración <ArrowUpRight size={13} className="inline" /></a>.
      </div>
    </Card>
  )
}

/* Paso 1 — la ficha de la empresa: texto libre que el agente usa como conocimiento. */
function KnowledgeCard({ client, knowledgeQ }) {
  const [text, setText] = useState('')
  const [loadedFor, setLoadedFor] = useState(null)
  useEffect(() => {
    if (knowledgeQ.data && knowledgeQ.data.client !== loadedFor) {
      setText(knowledgeQ.data.knowledge || '')
      setLoadedFor(knowledgeQ.data.client)
    }
  }, [knowledgeQ.data, loadedFor])

  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => api.setKnowledge(client, text),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge', client] })
      qc.invalidateQueries({ queryKey: ['whatsapp-readiness', client] })
      toast.success('Ficha guardada — el agente ya la conoce')
    },
    onError: (e) => toast.error('No se pudo guardar: ' + e.message),
  })
  const dirty = text !== (knowledgeQ.data?.knowledge || '')

  return (
    <Card className="wa-panel p-5 sm:p-6">
      <StepHeader n={1} icon={Building2} title="La ficha de la empresa"
        sub="Pega aquí todo lo que el agente debe saber para atender bien: qué vende, precios, horarios, políticas. Texto libre, como se lo contarías a un vendedor nuevo." />
      {knowledgeQ.isLoading ? (
        <Skeleton className="h-36 w-full" />
      ) : knowledgeQ.isError ? (
        <div className="text-sm text-rose-600">
          No se pudo cargar la ficha. <button className="underline" onClick={() => knowledgeQ.refetch()}>Reintentar</button>
        </div>
      ) : (
        <textarea
          value={text} onChange={(e) => setText(e.target.value)} rows={7}
          placeholder={'Ej: Vendemos pallets de madera certificados para exportación.\nPrecios desde $8.900 + IVA por unidad, descuento sobre 500 unidades.\nDespacho en RM en 48h. Horario: lunes a viernes 9 a 18h.\nNo vendemos a particulares, solo empresas.'}
          className="w-full border border-zinc-200 rounded-xl px-3 py-2.5 text-sm outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400 resize-y"
        />
      )}
      {!knowledgeQ.isError && (
        <div className="flex items-center justify-between mt-2">
          <span className="text-[11px] text-zinc-400">
            {text.trim()
              ? `${text.length.toLocaleString('es-CL')} caracteres`
              : 'Sin ficha todavía — el agente responderá solo con lo básico.'}
          </span>
          <Button variant={dirty ? 'accent' : 'soft'} onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
            {save.isPending ? 'Guardando…' : dirty ? 'Guardar ficha' : <><Check size={14} /> Guardada</>}
          </Button>
        </div>
      )}
      {!knowledgeQ.isError && <KnowledgeHistory client={client} />}
    </Card>
  )
}

/* Paso 2 — el catálogo de personalidades. */
function VendorPicker({ vendorsQ, assignedId, currentId, onPick }) {
  const current = (vendorsQ.data?.vendors || []).find((v) => v.id === currentId)
  return (
    <Card className="wa-panel p-5 sm:p-6">
      <StepHeader n={2} icon={MessageCircle} title="Elige quién atiende"
        sub="Cada personalidad tiene su propio tono. La que elijas responderá a los leads de esta empresa." />
      {vendorsQ.isLoading ? (
        <div className="grid grid-cols-2 gap-3"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>
      ) : vendorsQ.isError ? (
        <div className="text-sm text-rose-600">No se pudo cargar el catálogo. <button className="underline" onClick={() => vendorsQ.refetch()}>Reintentar</button></div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(vendorsQ.data?.vendors || []).map((v) => {
            const active = v.id === currentId
            return (
              <button key={v.id} onClick={() => onPick(v.id)} type="button" aria-pressed={active}
                className={'wa-vendor text-left rounded-xl border p-3.5 transition-all duration-150 ' +
                  (active
                    ? 'border-gold/60 ring-2 ring-champagne/40 bg-champagne/10 dark:bg-zinc-100'
                    : 'border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-100')}>
                <div className="flex items-center gap-3">
                  <VendorAvatar vendor={v} />
                  <div className="min-w-0">
                    <div className="font-semibold text-sm flex items-center gap-1.5">
                      {v.name}
                      {active && <CheckCircle2 size={14} className="text-gold-deep shrink-0" />}
                    </div>
                    <div className="text-xs text-zinc-500 truncate capitalize">{v.tone || 'tono estándar'}</div>
                  </div>
                </div>
                <div className="flex items-center justify-between mt-2.5">
                  <span className="text-[11px] text-zinc-400">{v.phone || ''}</span>
                  {v.id === assignedId && (
                    <span className="text-[10px] font-semibold text-gold-deep bg-champagne/40 px-1.5 py-0.5 rounded-full">
                      Atiende ahora
                    </span>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </Card>
  )
}

/* Las instrucciones viven en la empresa; editar una personalidad del catálogo
   cambiaría el tono de todas las empresas que la comparten. */
function ProfileCard({ client, profileQ, vendor }) {
  const qc = useQueryClient()
  const [profile, setProfile] = useState({ tone: '', instructions: '', whatsapp_number: '',
    quote_mode: 'manual', response_mode: 'manual' })
  useEffect(() => {
    setProfile({ tone: profileQ.data?.profile?.tone || '', instructions: profileQ.data?.profile?.instructions || '',
      whatsapp_number: profileQ.data?.profile?.whatsapp_number || '',
      quote_mode: profileQ.data?.profile?.quote_mode || (client === 'zeroai' ? 'automatic' : 'manual'),
      response_mode: profileQ.data?.profile?.response_mode || (client === 'zeroai' ? 'automatic' : 'manual') })
  }, [client, profileQ.data])

  const save = useMutation({
    mutationFn: () => api.setAgentProfile(client, profile),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-profile', client] })
      qc.invalidateQueries({ queryKey: ['whatsapp-readiness', client] })
      toast.success('Forma de atención guardada para ' + client)
    },
    onError: (e) => toast.error('No se pudo guardar: ' + e.message),
  })
  const saved = profileQ.data?.profile || {}
  const dirty = profile.tone !== (saved.tone || '') || profile.instructions !== (saved.instructions || '') ||
    profile.whatsapp_number !== (saved.whatsapp_number || '') ||
    profile.quote_mode !== (saved.quote_mode || 'automatic') ||
    profile.response_mode !== (saved.response_mode || 'automatic')

  return (
    <Card className="wa-panel p-5 sm:p-6">
      <div className="wa-profile-heading"><div><div className="wa-field-kicker">Reglas del negocio</div><div className="font-display font-bold text-brand">Forma de atender</div></div><span>{vendor?.name || 'Sin agente'}</span></div>
      <p className="text-xs text-zinc-500 mt-1 mb-4">Estas indicaciones se aplican solo a {client}.</p>
      {profileQ.isError && <p className="text-xs text-rose-600 mb-2">No se pudo cargar. <button className="underline" onClick={() => profileQ.refetch()}>Reintentar</button></p>}
      <label className="block text-xs font-medium text-zinc-600 mb-1">Tono de respuesta</label>
      <textarea
        value={profile.tone} onChange={(e) => setProfile((p) => ({ ...p, tone: e.target.value }))} rows={2} maxLength={300}
        placeholder="Ej: cercana y cálida, chilena — usa 'ya', 'bacán' con moderación; tutea, sin muletillas ni sonar como robot"
        className="w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400 resize-y"
      />
      <label className="block text-xs font-medium text-zinc-600 mt-3 mb-1">Reglas de atención del negocio</label>
      <textarea
        value={profile.instructions} onChange={(e) => setProfile((p) => ({ ...p, instructions: e.target.value }))} rows={4} maxLength={1200}
        placeholder="Ej: pide comuna y medidas antes de cotizar; informa el plazo solo si figura en la ficha; deriva reclamos a una persona."
        className="w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400 resize-y"
      />
      <label className="block text-xs font-medium text-zinc-600 mt-3 mb-1">Número receptor de esta empresa</label>
      <Input value={profile.whatsapp_number} onChange={(e) => setProfile((p) => ({ ...p, whatsapp_number: e.target.value.replace(/[^\d]/g, '').slice(0, 15) }))}
        inputMode="tel" placeholder="56912345678" />
      <p className="text-[11px] text-zinc-500 mt-1">Debe coincidir con un número vinculado al servicio. El contacto nuevo se asociará a esta empresa por el número que recibió el mensaje.</p>
      <label className="block text-xs font-medium text-zinc-600 mt-3 mb-1">Quién responde los mensajes</label>
      <select value={profile.response_mode} onChange={(e) => setProfile((p) => ({ ...p, response_mode: e.target.value }))}
        className="w-full border border-zinc-200 rounded-xl px-3 py-2.5 text-sm bg-white dark:bg-zinc-100 text-zinc-900">
        <option value="manual">Yo respondo desde la bandeja de WhatsApp</option>
        <option value="automatic">El agente responde automáticamente</option>
      </select>
      <p className="text-[11px] text-zinc-500 mt-1">Durante la preparación, usa revisión manual. Activa respuestas automáticas después de probar la ficha y los presupuestos.</p>
      <label className="block text-xs font-medium text-zinc-600 mt-3 mb-1">Presupuestos por WhatsApp</label>
      <select value={profile.quote_mode} onChange={(e) => setProfile((p) => ({ ...p, quote_mode: e.target.value }))}
        className="w-full border border-zinc-200 rounded-xl px-3 py-2.5 text-sm bg-white dark:bg-zinc-100 text-zinc-900">
        <option value="manual">Revisión humana: el agente pide los datos y no envía montos</option>
        <option value="automatic">Automático: cantidad × precio unitario + impuesto</option>
      </select>
      <p className="text-[11px] text-zinc-500 mt-1">Activa el cálculo automático solo si esa fórmula representa exactamente cómo vende esta empresa.</p>
      <div className="flex items-center justify-between mt-2 gap-3">
        <span className="text-[11px] text-zinc-400">Guarda y prueba en el chat antes de atender mensajes reales.</span>
        <Button variant={dirty ? 'accent' : 'soft'} onClick={() => save.mutate()} disabled={profileQ.isError || profileQ.isLoading || save.isPending || !dirty} className="shrink-0">
          {save.isPending ? 'Guardando…' : dirty ? 'Guardar reglas' : <><Check size={14} /> Guardadas</>}
        </Button>
      </div>
    </Card>
  )
}

function ReadinessCard({ client, readinessQ }) {
  const data = readinessQ.data
  const rows = [
    ['Ficha de conocimiento', data?.knowledge, 'Agrega la información que el agente debe conocer.'],
    ['Reglas de respuesta', data?.response_rules, 'Define tono y reglas de atención.'],
    ['Número receptor', data?.number_bound, 'Vincula un número a esta empresa.'],
    ['Precios', (data?.pricing_items || 0) > 0, 'Opcional si no cotiza.'],
  ]
  return (
    <Card className="wa-readiness p-5 sm:p-6">
      <div className="wa-readiness-heading"><div><span className="wa-field-kicker">Estado de preparación</span><h2>Todo lo necesario, a la vista</h2></div><span>Para {client}</span></div>
      {readinessQ.isError ? <p className="text-sm text-rose-600">No se pudo consultar. <button className="underline" onClick={() => readinessQ.refetch()}>Reintentar</button></p> :
        <div className="wa-readiness-grid">{rows.map(([label, done, hint], index) => (
          <div key={label} className={'wa-readiness-item ' + (done ? 'is-done' : '')}>
            <span className="wa-readiness-icon" aria-hidden="true">{done ? <Check size={16} /> : String(index + 1).padStart(2, '0')}</span>
            <div><strong>{label}</strong><p>{done ? 'Configurado' : readinessQ.isLoading ? 'Consultando…' : hint}</p></div>
          </div>
        ))}</div>}
    </Card>
  )
}

/* Paso 3 — desplegar: la personalidad elegida queda atendiendo a esa empresa. */
function DeployCard({ client, vendor, assignedId, knowledgeSaved, deploy, cfg }) {
  const isDeployed = vendor && vendor.id === assignedId
  return (
    <Card className="wa-panel wa-deploy p-5 sm:p-6">
      <StepHeader n={3} icon={Rocket} title="Asignar agente a esta empresa"
        sub={vendor
          ? `${vendor.name} atenderá a los leads de ${client} usando la ficha guardada.`
          : 'Elige una personalidad en el paso 2.'} />
      {!knowledgeSaved && (
        <div className="text-xs text-amber-800 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          Aún no guardas la ficha (paso 1). Puedes desplegar igual, pero el agente sabrá muy poco de la empresa.
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button variant="accent" onClick={() => deploy.mutate()} disabled={!vendor || deploy.isPending}>
          <Rocket size={15} /> {deploy.isPending ? 'Guardando…' : isDeployed ? 'Guardar asignación' : 'Asignar agente'}
        </Button>
        {isDeployed && (
          <span className="text-xs text-gold-deep font-medium inline-flex items-center gap-1">
            <CheckCircle2 size={13} /> {vendor.name} está asignado a {client}
          </span>
        )}
      </div>
      <div className="text-[11px] text-zinc-400 mt-3">
        La asignación guarda quién responde. Para atender contactos nuevos de esta empresa hace falta
        asociarle un número o identificador de WhatsApp propio y verificar su enrutamiento.
        {cfg?.whatsapp_provider === 'web' && ' El puente web actual conecta un solo número.'}
      </div>
    </Card>
  )
}

function StepHeader({ n, icon: Icon, title, sub }) {
  return (
    <div className="wa-step-header flex items-start gap-3 mb-5">
      <div className="w-10 h-10 rounded-xl bg-champagne/35 text-gold-deep grid place-items-center shrink-0 relative">
        <Icon size={17} />
        <span className="absolute -top-1.5 -right-1.5 w-[18px] h-[18px] rounded-full bg-brand-surface text-white text-[10px] font-bold grid place-items-center">{n}</span>
      </div>
      <div>
        <div className="font-display font-bold tracking-tight leading-tight text-brand">{title}</div>
        <div className="text-xs text-zinc-500 mt-1 leading-relaxed">{sub}</div>
      </div>
    </div>
  )
}

function VendorAvatar({ vendor }) {
  if (vendor.photo) {
    return <img src={vendor.photo} alt={vendor.name} className="w-10 h-10 rounded-full object-cover shrink-0" />
  }
  const initials = (vendor.name || '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div className="w-10 h-10 rounded-full bg-brand-grad text-white grid place-items-center text-sm font-bold shrink-0">
      {initials}
    </div>
  )
}

/* Estado de la conexión con Meta WhatsApp Cloud API. */
function WebStatusCard({ cfg, client, profile }) {
  const status = useQuery({
    queryKey: ['whatsapp-web-status', client],
    queryFn: () => api.whatsappWebStatus(client),
    refetchInterval: 5000,
    retry: false,
  })
  const ready = status.data?.state === 'ready'
  const expectedNumber = profile?.whatsapp_number || (client === 'zeroai' ? '56964537891' : '')
  const numberMatches = ready && expectedNumber && status.data?.account === expectedNumber
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-3">
        <SectionTitle className="flex items-center gap-2">
          <MessageCircle size={18} className="text-[#16a34a]" /> WhatsApp Business
        </SectionTitle>
        <Badge color={numberMatches && cfg.outbox_live ? '#16a34a' : '#b45309'}>
          {numberMatches && cfg.outbox_live ? 'Número conectado' : 'Conexión pendiente'}
        </Badge>
      </div>
      {status.isError && <p className="text-sm text-rose-600 mt-3">{status.error.message}</p>}
      {status.data?.state === 'scan_qr' && status.data.qr && (
        <div className="mt-4 space-y-2">
          <p className="text-sm text-zinc-600">En tu teléfono: WhatsApp Business → Settings → Linked devices → Link a device. Escanea este QR.</p>
          <img src={status.data.qr} alt="QR para vincular WhatsApp Business" className="w-64 h-64 bg-white p-2 rounded-xl" />
        </div>
      )}
      {ready && <p className="text-sm text-zinc-600 mt-3">Número vinculado: {status.data.account || 'WhatsApp Business'}. Las respuestas del agente usan el motor local.</p>}
      {ready && !numberMatches && <p className="text-xs text-amber-700 mt-2">El número conectado no coincide con el guardado para {client}. Las respuestas automáticas no saldrán hasta corregirlo.</p>}
      {ready && <p className="text-xs text-amber-700 mt-2">Esta conexión corresponde a un solo número; cambiar la empresa en el dashboard no cambia el destinatario de los mensajes entrantes.</p>}
      {!ready && status.data?.state !== 'scan_qr' && <p className="text-sm text-zinc-600 mt-3">Estado: {status.data?.state || 'consultando…'}</p>}
      {status.data?.error && <p className="text-xs text-rose-600 mt-2">{status.data.error}</p>}
      <p className="text-xs text-zinc-500 mt-3">El servicio funciona en esta computadora. Debe permanecer encendida para recibir y responder mensajes.</p>
    </Card>
  )
}

/* Estado de la conexión con Meta WhatsApp Cloud API. */
function StatusCard({ cfg, client, webhookReady, webhookUrl }) {
  const [copied, setCopied] = useState(false)
  const [probe, setProbe] = useState(null) // null | { ok: true, data } | { ok: false, error }
  const [busy, setBusy] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(webhookUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  const testConnection = async () => {
    setBusy(true)
    try {
      const data = await api.whatsappStatus(client)
      setProbe({ ok: true, data })
      if (data.cloud_api_ready) toast.success('Número conectado a Cloud API')
      else toast.warning('El número aún no está conectado a Cloud API')
    } catch (e) {
      setProbe({ ok: false, error: e.message })
      toast.error('Conexión falló: ' + e.message)
    } finally { setBusy(false) }
  }
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <SectionTitle className="flex items-center gap-2">
          <MessageCircle size={18} className="text-[#16a34a]" /> Conexión con Meta
        </SectionTitle>
        <Badge color={probe?.data?.cloud_api_ready && cfg?.outbox_live && webhookReady ? '#16a34a' : '#b45309'} className="inline-flex items-center gap-1">
          <CheckCircle2 size={12} /> {probe?.data?.cloud_api_ready && cfg?.outbox_live && webhookReady ? 'Listo para probar mensajes' : 'Configuración pendiente'}
        </Badge>
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-3">
        Token y Phone Number ID guardados. Prueba la conexión y completa el webhook para recibir mensajes.
      </div>

      <div className="flex items-center gap-2 mb-3">
        <Button variant="soft" onClick={testConnection} disabled={busy}>
          {busy ? 'Probando…' : 'Probar conexión'}
        </Button>
        {probe?.ok && (
          <span className="text-xs text-zinc-500 flex items-center gap-1.5 min-w-0">
            <CheckCircle2 size={13} className="text-[#16a34a] shrink-0" />
            <span className="truncate">
              {probe.data?.display_phone_number}
              {probe.data?.verified_name ? ` · ${probe.data.verified_name}` : ''}
            </span>
          </span>
        )}
      </div>
      {probe?.ok === false && (
        <div className="text-xs text-rose-600 mb-3 flex items-start gap-1.5 break-words">
          <AlertCircle size={13} className="mt-0.5 shrink-0" /> {probe.error}
        </div>
      )}
      {probe?.ok && !probe.data?.cloud_api_ready && (
        <div className="text-xs text-amber-800 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          {probe.data?.is_on_biz_app
            ? 'El número está en WhatsApp Business, pero todavía no está conectado al agente. Para conservar ambos hay que completar el registro de coexistencia de Meta.'
            : `Meta indica ${probe.data?.status || 'sin conexión'} (${probe.data?.platform_type || 'sin plataforma'}). El agente todavía no puede recibir mensajes.`}
        </div>
      )}
      {!webhookReady && (
        <div className="text-xs text-amber-800 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          Faltan el Verify token o el App Secret propios de {client} en Configuración. Sin ellos Meta no puede validar el webhook.
        </div>
      )}

      <div className="rounded-xl bg-zinc-50 p-3 mb-3">
        <div className="text-xs font-medium text-zinc-600 mb-1">
          Webhook (configúralo en Meta for Developers → WhatsApp → Configuración)
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs bg-white dark:bg-zinc-50 border border-zinc-200 rounded-lg px-2 py-1.5 break-all">{webhookUrl}</code>
          <Button variant="soft" onClick={copy} className="shrink-0">
            {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copiado' : 'Copiar'}
          </Button>
        </div>
        <div className="text-[11px] text-zinc-400 mt-2">
          Usa como "Verify token" el mismo que guardaste en Configuración. En Meta suscribe también el campo "messages" de la cuenta WhatsApp correspondiente a +56 9 6453 7891.
        </div>
      </div>

      {/* Qué cerebro contesta. Informativo a propósito: no hay selector porque el
          modelo local está enjaulado en WhatsApp por decisión de producto, y
          poder cambiarlo desde acá sería abrir esa jaula. Se cambia en
          zero/config.py (WHATSAPP_ENGINE). */}
      {cfg?.whatsapp_engine && (
        <div className="text-xs text-zinc-500 bg-zinc-50 rounded-xl px-3 py-2 mb-2">
          <div className="flex items-center justify-between gap-2">
            <span>Motor que responde</span>
            <span className="text-gold-deep font-medium flex items-center gap-1 min-w-0">
              <Cpu size={13} className="shrink-0" />
              <span className="truncate">{cfg.whatsapp_engine.model}</span>
              <span className="text-zinc-400 font-normal shrink-0">· local, sin costo</span>
            </span>
          </div>
          <div className="text-[11px] text-zinc-400 mt-1">
            {cfg.whatsapp_engine.fallback_ready
              ? 'Si el motor local no responde, contesta Claude (API paga) y te llega un aviso al celular.'
              : cfg.whatsapp_engine.fallback_to_paid
                ? 'Respaldo a Claude declarado pero sin API key: si el motor local se cae, nadie contesta.'
                : 'Sin respaldo: si el motor local se cae, nadie contesta.'}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-zinc-500 bg-zinc-50 rounded-xl px-3 py-2">
        <span>Envío real (outbox)</span>
        {cfg?.outbox_live
          ? <span className="text-gold-deep font-medium flex items-center gap-1"><CheckCircle2 size={13} /> Activado — los mensajes se envían de verdad</span>
          : <span className="text-zinc-400 font-medium flex items-center gap-1"><WifiOff size={13} /> Mock — se simulan, no se envían</span>}
      </div>
    </Card>
  )
}

function ActivityCard({ leadsQ, client }) {
  const [expanded, setExpanded] = useState(null) // lead key expandido, o null
  if (leadsQ.isLoading) {
    return (
      <Card className="p-6 space-y-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </Card>
    )
  }
  if (leadsQ.isError) {
    return (
      <Card className="p-6">
        <div className="text-sm text-rose-600">
          No se pudo cargar la actividad. <button className="underline" onClick={() => leadsQ.refetch()}>Reintentar</button>
        </div>
      </Card>
    )
  }

  const leads = (leadsQ.data?.leads || []).filter((r) => r.channel === 'whatsapp')
  leads.sort((a, b) => (b.updated || '').localeCompare(a.updated || ''))

  return (
    <Card className="p-6">
      <div className="font-display font-bold tracking-tight text-brand flex items-center gap-2 mb-1">
        <Clock size={16} /> Actividad reciente (WhatsApp)
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-3">
        Leads de este canal y su último evento. Se actualiza con cada mensaje entrante.
      </div>

      {leads.length === 0 ? (
        <div className="text-sm text-zinc-400 py-6 text-center">
          Sin actividad todavía — cuando lleguen mensajes por WhatsApp, aparecerán aquí.
        </div>
      ) : (
        <div className="space-y-2">
          {leads.slice(0, 8).map((r) => {
            const last = (r.history || [])[r.history.length - 1]
            const stage = STAGES[r.stage] || { l: r.stage, c: '#71717a' }
            const isOpen = expanded === r.key
            return (
              <div key={r.key} className="bg-zinc-50 rounded-xl">
                <button
                  className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left"
                  onClick={() => setExpanded(isOpen ? null : r.key)}
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{r.company || r.name || r.key}</div>
                    {last && <div className="text-xs text-zinc-400 truncate">{last.event}{last.detail ? ` — ${last.detail}` : ''}</div>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {last?.ts && <span className="text-[11px] text-zinc-400">{new Date(last.ts).toLocaleString('es-CL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>}
                    <Badge color={stage.c}>{stage.l}</Badge>
                    <ChevronDown size={14} className={'text-zinc-400 transition-transform ' + (isOpen ? 'rotate-180' : '')} />
                  </div>
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 pt-1 border-t border-zinc-200/70">
                    <ConversationThread client={client} leadKey={r.key} />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
