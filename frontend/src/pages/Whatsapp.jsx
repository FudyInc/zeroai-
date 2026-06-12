import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MessageCircle, CheckCircle2, WifiOff, Copy, Check, Clock } from 'lucide-react'
import { api, BASE } from '../lib/api'
import { Card, Button, Badge, Skeleton } from '../components/ui'
import { STAGES } from '../lib/util'
import { useApp } from '../App'
import AgentTester from '../components/AgentTester'

export default function Whatsapp() {
  const { client } = useApp()
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: api.config })
  const leadsQ = useQuery({
    queryKey: ['leads', client, 'whatsapp-activity'],
    queryFn: () => api.leads(client, { group: 'todos', limit: 50 }),
    enabled: !!client && !!cfgQ.data?.whatsapp,
  })

  if (cfgQ.isLoading) {
    return (
      <Card className="p-6 max-w-2xl space-y-3">
        <Skeleton className="h-5 w-44" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-40 w-full" />
      </Card>
    )
  }

  if (cfgQ.isError) {
    return (
      <Card className="p-6 max-w-2xl">
        <div className="font-semibold mb-1">Agente de WhatsApp</div>
        <div className="text-sm text-zinc-500 mb-3">No se pudo cargar la configuración.</div>
        <Button variant="soft" onClick={() => cfgQ.refetch()}>Reintentar</Button>
      </Card>
    )
  }

  const cfg = cfgQ.data
  const connected = !!cfg?.whatsapp

  if (!connected) {
    return (
      <Card className="p-6 max-w-2xl">
        <div className="flex items-center gap-2 font-semibold mb-1">
          <MessageCircle size={18} className="text-[#16a34a]" /> Agente de WhatsApp
        </div>
        <div className="text-sm text-zinc-500 mb-3">
          Conecta tu cuenta de <b>WhatsApp Business (Meta Cloud API)</b> para activar este agente: responde
          dudas del lead y agenda dentro de la ventana de 24h.
        </div>
        <Link to="/config" className="text-gold-deep text-sm font-medium">Ir a Configuración →</Link>
      </Card>
    )
  }

  const webhookUrl = `${BASE || window.location.origin}/api/webhooks/whatsapp`

  return (
    <div className="max-w-2xl space-y-4">
      <StatusCard cfg={cfg} webhookUrl={webhookUrl} />
      <AgentTester
        title="Probar conversación"
        hint="Simula un mensaje entrante de WhatsApp y mira cómo responde el agente (CONCIERGE) con el negocio del cliente. Mock por intención · con Anthropic key, modelo real."
        defaultClient={client || 'demo'}
      />
      <ActivityCard leadsQ={leadsQ} />
    </div>
  )
}

function StatusCard({ cfg, webhookUrl }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(webhookUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <MessageCircle size={18} className="text-[#16a34a]" /> Agente de WhatsApp
        </div>
        <Badge color="#16a34a" className="inline-flex items-center gap-1">
          <CheckCircle2 size={12} /> Activo
        </Badge>
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-4">
        Token y phone number ID conectados. El agente responde dudas y agenda dentro de la ventana de 24h
        de WhatsApp Business.
      </div>

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
