import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  MessageCircle, CheckCircle2, WifiOff, AlertCircle, Copy, Check, Clock,
  Building2, Rocket, Cpu,
} from 'lucide-react'
import { api, BASE } from '../lib/api'
import { Card, Button, Badge, Skeleton } from '../components/ui'
import { STAGES } from '../lib/util'
import { useApp } from '../App'
import AgentTester from '../components/AgentTester'
import PricingCard from '../components/PricingCard'

/* El agente de WhatsApp, en un solo lugar: en 3 pasos dejas a un agente
   atendiendo los leads de una empresa (cuéntale del negocio, elige quién
   atiende, despliega), lo pruebas en el chat, y ves el estado real de la
   conexión con Meta + la actividad reciente. Antes "la ficha"/"elige quién
   atiende" vivían en una página "Agentes" genérica separada — se movieron acá
   porque son 100% configuración del agente de WhatsApp (CONCIERGE), no de
   los otros canales (email es solo envío, sin ida y vuelta). */

export default function Whatsapp() {
  const { client: ctxClient } = useApp()
  const client = ctxClient || 'demo'
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: api.config })

  const vendorsQ = useQuery({ queryKey: ['vendors'], queryFn: api.vendors })
  const assignedQ = useQuery({ queryKey: ['vendor', client], queryFn: () => api.vendorFor(client) })
  const knowledgeQ = useQuery({ queryKey: ['knowledge', client], queryFn: () => api.knowledge(client) })
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
      setSelected(null)
      toast.success(`Listo: ${d.vendor?.name || 'el agente'} atiende a los leads de ${client}`)
    },
    onError: (e) => toast.error('No se pudo desplegar: ' + e.message),
  })

  const knowledgeSaved = (knowledgeQ.data?.knowledge || '').trim().length > 0
  const cfg = cfgQ.data
  const connected = !!cfg?.whatsapp

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <p className="text-sm text-zinc-500 max-w-2xl">
          En 3 pasos dejas un agente atendiendo a los leads de <b className="text-zinc-700">{client}</b>:
          cuéntale de la empresa, elige quién atiende y despliega. Pruébalo en el chat antes de que
          hable con leads reales.
        </p>
        {cfg?.local_model && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-zinc-400">
            <Cpu size={12} /> Cerebro: {cfg.local_model}{cfg.discover === 'web' ? ' · búsqueda web' : ''}
          </span>
        )}
      </div>

      {!cfgQ.isLoading && !connected && <ConnectMetaBanner />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        <div className="space-y-4">
          <KnowledgeCard client={client} knowledgeQ={knowledgeQ} />
          <PricingCard client={client} />
          <VendorPicker vendorsQ={vendorsQ} assignedId={assignedId} currentId={currentId} onPick={setSelected} />
          <DeployCard
            client={client} vendor={currentVendor} assignedId={assignedId}
            knowledgeSaved={knowledgeSaved} deploy={deploy}
          />
        </div>
        <div className="lg:sticky lg:top-24 space-y-4">
          <AgentTester
            title="Probar antes de desplegar"
            hint="Escribe como si fueras un lead de esta empresa. Nada de esto le llega a nadie: es solo un ensayo."
            fixedClient={client}
            vendorId={currentId}
            vendorName={currentVendor?.name}
          />
          {connected && <StatusCard cfg={cfg} webhookUrl={`${BASE || window.location.origin}/api/webhooks/whatsapp`} />}
        </div>
      </div>

      {connected && <ActivityCard leadsQ={leadsQ} />}
    </div>
  )
}

/* Banner informativo cuando Meta todavía no está conectado — a diferencia de
   antes, YA NO bloquea el resto de la página: ficha/precios/vendedor/chat de
   prueba funcionan igual sin Meta conectado (solo el envío real por WhatsApp
   queda pendiente de esa conexión). */
function ConnectMetaBanner() {
  return (
    <Card className="p-4 flex items-start gap-3 bg-amber-50/60 border-amber-200">
      <div className="w-9 h-9 rounded-xl bg-amber-100 text-amber-700 grid place-items-center shrink-0">
        <MessageCircle size={17} />
      </div>
      <div className="text-sm text-amber-800">
        <b>Meta todavía no está conectada.</b> Puedes preparar todo (ficha, precios, quién atiende) y
        probarlo en el chat de al lado igual — el envío real por WhatsApp se activa apenas conectes tu
        cuenta de <b>WhatsApp Business (Meta Cloud API)</b> en{' '}
        <a href="/config" className="underline font-medium">Configuración</a>.
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
      toast.success('Ficha guardada — el agente ya la conoce')
    },
    onError: (e) => toast.error('No se pudo guardar: ' + e.message),
  })
  const dirty = text !== (knowledgeQ.data?.knowledge || '')

  return (
    <Card className="p-6">
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
              ? `${text.length.toLocaleString()} caracteres`
              : 'Sin ficha todavía — el agente responderá solo con lo básico.'}
          </span>
          <Button variant={dirty ? 'accent' : 'soft'} onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
            {save.isPending ? 'Guardando…' : dirty ? 'Guardar ficha' : <><Check size={14} /> Guardada</>}
          </Button>
        </div>
      )}
    </Card>
  )
}

/* Paso 2 — el catálogo de personalidades. */
function VendorPicker({ vendorsQ, assignedId, currentId, onPick }) {
  return (
    <Card className="p-6">
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
              <button key={v.id} onClick={() => onPick(v.id)}
                className={'text-left rounded-xl border p-3.5 transition-all duration-150 ' +
                  (active
                    ? 'border-gold/60 ring-4 ring-champagne/40 bg-champagne/10'
                    : 'border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50')}>
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

/* Paso 3 — desplegar: la personalidad elegida queda atendiendo a esa empresa. */
function DeployCard({ client, vendor, assignedId, knowledgeSaved, deploy }) {
  const isDeployed = vendor && vendor.id === assignedId
  return (
    <Card className="p-6">
      <StepHeader n={3} icon={Rocket} title="Desplegar agente"
        sub={vendor
          ? `${vendor.name} atenderá a los leads de ${client} usando la ficha guardada.`
          : 'Elige una personalidad en el paso 2.'} />
      {!knowledgeSaved && (
        <div className="text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          Aún no guardas la ficha (paso 1). Puedes desplegar igual, pero el agente sabrá muy poco de la empresa.
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button variant="accent" onClick={() => deploy.mutate()} disabled={!vendor || deploy.isPending}>
          <Rocket size={15} /> {deploy.isPending ? 'Desplegando…' : isDeployed ? 'Volver a desplegar' : 'Desplegar agente'}
        </Button>
        {isDeployed && (
          <span className="text-xs text-gold-deep font-medium inline-flex items-center gap-1">
            <CheckCircle2 size={13} /> {vendor.name} está atendiendo a {client}
          </span>
        )}
      </div>
      <div className="text-[11px] text-zinc-400 mt-3">
        El envío real por WhatsApp se activa cuando se conecte la cuenta de Meta; mientras tanto el
        agente ya responde en el chat de prueba y por email.
      </div>
    </Card>
  )
}

function StepHeader({ n, icon: Icon, title, sub }) {
  return (
    <div className="flex items-start gap-3 mb-4">
      <div className="w-9 h-9 rounded-xl bg-champagne/35 text-gold-deep grid place-items-center shrink-0 relative">
        <Icon size={17} />
        <span className="absolute -top-1.5 -right-1.5 w-[18px] h-[18px] rounded-full bg-zinc-900 text-white text-[10px] font-bold grid place-items-center">{n}</span>
      </div>
      <div>
        <div className="font-semibold leading-tight">{title}</div>
        <div className="text-xs text-zinc-400 mt-0.5">{sub}</div>
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

/* Estado real de la conexión con Meta (token, phone number, webhook) — solo
   tiene sentido una vez conectado, por eso se muestra únicamente si connected. */
function StatusCard({ cfg, webhookUrl }) {
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
      const data = await api.whatsappStatus()
      setProbe({ ok: true, data })
      toast.success('Conexión con WhatsApp OK')
    } catch (e) {
      setProbe({ ok: false, error: e.message })
      toast.error('Conexión falló: ' + e.message)
    } finally { setBusy(false) }
  }
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <MessageCircle size={18} className="text-[#16a34a]" /> Conexión con Meta
        </div>
        <Badge color="#16a34a" className="inline-flex items-center gap-1">
          <CheckCircle2 size={12} /> Activo
        </Badge>
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-3">
        Token y phone number ID conectados. El agente responde dudas y agenda dentro de la ventana de 24h
        de WhatsApp Business.
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

      <div className="rounded-xl bg-zinc-50 p-3 mb-3">
        <div className="text-xs font-medium text-zinc-600 mb-1">Webhook (configúralo en Meta for Developers → WhatsApp → Configuración)</div>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs bg-white border border-zinc-200 rounded-lg px-2 py-1.5 break-all">{webhookUrl}</code>
          <Button variant="soft" onClick={copy} className="shrink-0">
            {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copiado' : 'Copiar'}
          </Button>
        </div>
        <div className="text-[11px] text-zinc-400 mt-2">
          Usa como "Verify token" el mismo que guardaste en Configuración. Meta llamará a esta URL para
          validar el webhook y para reenviar los mensajes entrantes.
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-zinc-500 bg-zinc-50 rounded-xl px-3 py-2">
        <span>Envío real (outbox)</span>
        {cfg?.outbox_live
          ? <span className="text-gold-deep font-medium flex items-center gap-1"><CheckCircle2 size={13} /> Activado — los mensajes se envían de verdad</span>
          : <span className="text-zinc-400 font-medium flex items-center gap-1"><WifiOff size={13} /> Mock — se simulan, no se envían</span>}
      </div>
    </Card>
  )
}

function ActivityCard({ leadsQ }) {
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
      <div className="font-semibold flex items-center gap-2 mb-1">
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
            return (
              <div key={r.key} className="flex items-center justify-between gap-3 bg-zinc-50 rounded-xl px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{r.company || r.name || r.key}</div>
                  {last && <div className="text-xs text-zinc-400 truncate">{last.event}{last.detail ? ` — ${last.detail}` : ''}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {last?.ts && <span className="text-[11px] text-zinc-400">{new Date(last.ts).toLocaleString('es-CL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>}
                  <Badge color={stage.c}>{stage.l}</Badge>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
