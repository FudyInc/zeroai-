import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import {
  Mail, Phone, MessageCircle, Instagram, Linkedin, Clock,
  Building2, Rocket, CheckCircle2, Check, Cpu,
} from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Skeleton } from '../components/ui'
import { useApp } from '../App'
import AgentTester from '../components/AgentTester'

/* Sección Agentes: en 3 pasos simples, cualquier persona del equipo deja a un agente
   atendiendo los leads de una empresa — sin saber nada de IA.
   1) Pegar la ficha de la empresa (texto libre).
   2) Elegir quién atiende (personalidad del catálogo).
   3) Desplegar. Y al lado, un chat para probarlo antes de que hable con leads reales. */

export default function Agentes() {
  const { client: ctxClient } = useApp()
  const client = ctxClient || 'demo'
  const { data: cfg } = useQuery({ queryKey: ['config'], queryFn: api.config })

  const vendorsQ = useQuery({ queryKey: ['vendors'], queryFn: api.vendors })
  const assignedQ = useQuery({ queryKey: ['vendor', client], queryFn: () => api.vendorFor(client) })
  const knowledgeQ = useQuery({ queryKey: ['knowledge', client], queryFn: () => api.knowledge(client) })

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        <div className="space-y-4">
          <KnowledgeCard client={client} knowledgeQ={knowledgeQ} />
          <VendorPicker vendorsQ={vendorsQ} assignedId={assignedId} currentId={currentId} onPick={setSelected} />
          <DeployCard
            client={client} vendor={currentVendor} assignedId={assignedId}
            knowledgeSaved={knowledgeSaved} deploy={deploy}
          />
        </div>
        <div className="lg:sticky lg:top-24">
          <AgentTester
            title="Probar antes de desplegar"
            hint="Escribe como si fueras un lead de esta empresa. Nada de esto le llega a nadie: es solo un ensayo."
            fixedClient={client}
            vendorId={currentId}
            vendorName={currentVendor?.name}
          />
        </div>
      </div>

      <Canales cfg={cfg} client={ctxClient} />
    </div>
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
      ) : (
        <textarea
          value={text} onChange={(e) => setText(e.target.value)} rows={7}
          placeholder={'Ej: Vendemos pallets de madera certificados para exportación.\nPrecios desde $8.900 + IVA por unidad, descuento sobre 500 unidades.\nDespacho en RM en 48h. Horario: lunes a viernes 9 a 18h.\nNo vendemos a particulares, solo empresas.'}
          className="w-full border border-zinc-200 rounded-xl px-3 py-2.5 text-sm outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400 resize-y"
        />
      )}
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

/* Estado de los canales de contacto (lo que antes era toda esta página). */
const TONES = {
  ok: 'text-gold-deep bg-champagne/30',
  warn: 'text-amber-700 bg-amber-50',
  soon: 'text-pewter bg-pewter/10',
  bad: 'text-rose-600 bg-rose-50',
}

const DAY_MS = 24 * 60 * 60 * 1000

// Cuenta leads de un canal que pasaron a "replied" en las últimas 24h, usando
// el historial del CRM (ya viene en /api/leads). null = sin datos todavía
// (sin cliente, cargando o error) → la card simplemente no muestra la línea.
function repliedRecently(leads, channel) {
  if (!leads) return null
  const cutoff = Date.now() - DAY_MS
  return leads.filter((r) => {
    if (r.channel !== channel || r.stage !== 'replied') return false
    const ev = (r.history || []).slice().reverse()
      .find((h) => h.event === 'stage' && (h.detail || '').includes('replied'))
    return ev?.ts && new Date(ev.ts).getTime() >= cutoff
  }).length
}

function Canales({ cfg, client }) {
  const leadsQ = useQuery({
    queryKey: ['leads', client, 'agentes-activity'],
    queryFn: () => api.leads(client, { group: 'todos', limit: 50 }),
    enabled: !!client,
  })
  const nav = useNavigate()

  const leadRows = leadsQ.data?.leads
  const emailReplied = repliedRecently(leadRows, 'email')
  const waReplied = repliedRecently(leadRows, 'whatsapp')
  const activityLine = (n) => n != null && n > 0
    ? `${n} ${n === 1 ? 'lead respondió' : 'leads respondieron'} en 24h`
    : null

  const agents = [
    {
      key: 'email', name: 'Email', icon: Mail, chip: 'bg-brand/8 text-brand',
      desc: 'Envía un pitch con demo a un prospecto y los seguimientos por correo.',
      status: cfg?.email ? { t: 'Conectado', tone: 'ok' } : { t: 'Configurar', tone: 'warn' },
      onClick: () => nav(cfg?.email ? '/vender' : '/config'),
      activity: activityLine(emailReplied),
    },
    {
      key: 'call', name: 'Llamadas', icon: Phone, chip: 'bg-champagne/35 text-gold-deep',
      desc: 'Llama con un agente de voz (Fernanda) por teléfono.',
      status: cfg?.vapi ? { t: 'Activo', tone: 'ok' } : { t: 'Configurar', tone: 'warn' },
      onClick: () => nav('/llamadas'),
      activity: null,
    },
    {
      key: 'wa', name: 'WhatsApp', icon: MessageCircle, chip: 'bg-gold/15 text-gold-deep',
      desc: 'Agente que responde dudas del lead y agenda (ventana de 24h).',
      status: cfg?.whatsapp ? { t: 'Activo', tone: 'ok' } : { t: 'Configurar / probar', tone: 'warn' },
      onClick: () => nav('/whatsapp'),
      activity: activityLine(waReplied),
    },
    {
      key: 'ig', name: 'Instagram', icon: Instagram, chip: 'bg-pewter/15 text-pewter',
      desc: 'DMs en frío: la plataforma los bloquea (sin API oficial).',
      status: { t: 'No viable (ToS)', tone: 'bad' },
      onClick: null, disabled: true, activity: null,
    },
    {
      key: 'li', name: 'LinkedIn', icon: Linkedin, chip: 'bg-pewter/15 text-pewter',
      desc: 'Automatizar mensajes rompe sus términos (riesgo de baneo).',
      status: { t: 'No viable (ToS)', tone: 'bad' },
      onClick: null, disabled: true, activity: null,
    },
  ]

  return (
    <div className="space-y-3 pt-2">
      <div>
        <div className="font-semibold">Estado de los canales</div>
        <div className="text-xs text-zinc-400">
          Un agente por canal, todos con el mismo cerebro — cambia solo la forma de llegar al prospecto.
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((a, i) => (
          <motion.div key={a.key} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card
              interactive={!a.disabled && !!a.onClick}
              onClick={a.disabled ? undefined : a.onClick}
              className={'p-5 h-full ' + (a.disabled ? 'opacity-60' : a.onClick ? 'cursor-pointer' : '')}
            >
              <div className="flex items-start justify-between">
                <div className={'w-11 h-11 rounded-xl grid place-items-center ' + a.chip}>
                  <a.icon size={20} />
                </div>
                <span className={'text-xs font-medium px-2 py-1 rounded-full ' + TONES[a.status.tone]}>{a.status.t}</span>
              </div>
              <div className="font-semibold mt-3">{a.name}</div>
              <div className="text-sm text-zinc-500 mt-1">{a.desc}</div>
              {a.activity && (
                <div className="flex items-center gap-1.5 text-xs font-medium text-gold-deep mt-3 pt-3 border-t border-zinc-100">
                  <Clock size={12} />{a.activity}
                </div>
              )}
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
